"""Build a resumable local database from the latest sanitized watchlists."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from local_data_store import LocalDataStore


PROJECT_DIR = Path(__file__).resolve().parents[1]
SANITIZED_DIR = PROJECT_DIR / "data" / "sanitized_watchlists"
DATABASE_PATH = PROJECT_DIR / "data" / "quant_terminal.db"
PROGRESS_PATH = PROJECT_DIR / "data" / "market_db_build_progress.json"
FILE_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[-_]watchlist[-_](?P<key>[A-Za-z0-9][A-Za-z0-9_-]*?)(?:_SANITIZED(?:-options)?)?\.csv$",
    re.IGNORECASE,
)
OPTION_PATTERN = re.compile(r"^\.[A-Za-z]+\d{6}")
FUTURES_CONTRACT_PATTERN = re.compile(r"^/?(?P<root>[A-Z0-9]{1,4})[FGHJKMNQUVXZ]\d{2}$")
PERSONAL_TOKENS = ("name", "email", "account", "client", "personal")
PORTFOLIO_TOKENS = ("qty", "p/l", "net liq", "mark %", "position")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the local QuantTerminal market database")
    parser.add_argument("--date", help="Session date override in YYYY-MM-DD format")
    parser.add_argument("--period", default="6y", help="yfinance history period, default: 6y")
    parser.add_argument("--batch-size", type=int, default=20, help="Maximum symbols per download batch")
    parser.add_argument("--pause-seconds", type=int, default=60, help="Pause between batches, default: 60")
    parser.add_argument("--max-batches", type=int, help="Stop after this many batches for a staged build")
    parser.add_argument("--retry-failed", action="store_true", help="Retry symbols previously marked failed")
    parser.add_argument(
        "--privacy_guard",
        type=int,
        choices=(0, 1),
        default=1,
        help="Require privacy-guarded source data: 1=on (default), 0=off is not permitted",
    )
    parser.add_argument("--source-dir", type=Path, default=SANITIZED_DIR)
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    parser.add_argument("--progress-file", type=Path, default=PROGRESS_PATH)
    args = parser.parse_args()
    if args.batch_size < 1 or args.pause_seconds < 0:
        parser.error("--batch-size must be positive and --pause-seconds cannot be negative")
    if args.privacy_guard != 1:
        parser.error("build_market_db.py only accepts privacy-guarded input; run processor.py with --privacy_guard 1 first")
    return args


def file_metadata(path: Path) -> tuple[str, str] | None:
    match = FILE_PATTERN.fullmatch(path.name)
    if not match:
        return None
    key = match.group("key").lower().replace("allposition", "allpos")
    return match.group("date"), key


def latest_files(source_dir: Path, requested_date: str | None) -> tuple[str, list[tuple[Path, str]]]:
    candidates: list[tuple[Path, str, str]] = []
    if source_dir.exists():
        for path in source_dir.glob("*.csv"):
            metadata = file_metadata(path)
            if metadata:
                candidates.append((path, metadata[0], metadata[1]))
    if not candidates:
        raise FileNotFoundError(f"No keyed sanitized CSV files found in {source_dir}")
    source_date = requested_date or max(item[1] for item in candidates)
    selected = [(path, key) for path, date, key in candidates if date == source_date and "-options" not in path.stem.lower()]
    if not selected:
        raise FileNotFoundError(f"No keyed sanitized CSV files found for {source_date} in {source_dir}")
    return source_date, sorted(selected)


def classify_symbol(symbol: str) -> tuple[str, str | None]:
    clean = str(symbol).strip().upper()
    if OPTION_PATTERN.match(clean):
        parent = re.match(r"^\.([A-Z]+)\d{6}", clean)
        return "option", parent.group(1) if parent else None
    if clean.startswith("/") or clean.endswith("=F") or clean in {"^VIX", "^VVIX"}:
        return "future_or_index", None
    return "equity_or_fund", None


def yahoo_symbol(symbol: str) -> str:
    """Translate a TOS symbol into a Yahoo Finance-compatible download ticker."""
    clean = str(symbol).strip().upper()
    if clean.startswith("/"):
        contract = FUTURES_CONTRACT_PATTERN.fullmatch(clean)
        root = contract.group("root") if contract else clean[1:]
        return f"{root}=F"
    return clean


def safe_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in row.items()
        if not any(token in str(key).lower() for token in PERSONAL_TOKENS + PORTFOLIO_TOKENS)
    }


def ingest_files(store: LocalDataStore, source_date: str, files: list[tuple[Path, str]]) -> list[dict[str, Any]]:
    assets: dict[str, dict[str, Any]] = {}
    for path, watchlist_key in files:
        frame = pd.read_csv(path, encoding="utf-8-sig", on_bad_lines="skip")
        if "Symbol" not in frame.columns:
            print(f"Skipping {path.name}: no Symbol column")
            continue
        for row in frame.to_dict(orient="records"):
            symbol = str(row.get("Symbol", "")).strip().upper()
            if not symbol or symbol.lower() in {"nan", "symbol", "()"}:
                continue
            asset_type, underlying = classify_symbol(symbol)
            asset = assets.setdefault(symbol, {"symbol": symbol, "asset_type": asset_type, "underlying_symbol": underlying, "lists": []})
            asset["lists"].append((watchlist_key, path.name, safe_row(row)))
    for asset in assets.values():
        asset_id = store.upsert_asset(asset["symbol"], asset["asset_type"], asset["underlying_symbol"], source_date)
        for watchlist_key, source_file, row in asset["lists"]:
            store.save_observation(asset_id, watchlist_key, source_date, source_file, row)
    store.commit()
    return list(assets.values())


def extract_symbol_frame(downloaded: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if downloaded.empty:
        return pd.DataFrame()
    if isinstance(downloaded.columns, pd.MultiIndex):
        level_zero = set(str(value) for value in downloaded.columns.get_level_values(0))
        if ticker in level_zero:
            return downloaded[ticker].copy()
        if ticker in set(str(value) for value in downloaded.columns.get_level_values(1)):
            return downloaded.xs(ticker, axis=1, level=1).copy()
        return pd.DataFrame()
    return downloaded.copy()


def bars_from_frame(frame: pd.DataFrame) -> list[tuple[Any, ...]]:
    if frame.empty or "Close" not in frame.columns:
        return []
    rows = []
    for index, row in frame.dropna(subset=["Close"]).iterrows():
        def value(column: str) -> float | None:
            raw = row.get(column)
            return None if pd.isna(raw) else float(raw)
        rows.append((pd.Timestamp(index).date().isoformat(), value("Open"), value("High"), value("Low"), value("Close"), value("Adj Close"), value("Volume")))
    return rows


def write_progress(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    args = parse_args()
    source_date, files = latest_files(args.source_dir, args.date)
    store = LocalDataStore(args.database)
    run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        assets = ingest_files(store, source_date, files)
        downloadable = [asset for asset in assets if asset["asset_type"] != "option"]
        symbols = sorted(asset["symbol"] for asset in downloadable)
        download_map = {symbol: yahoo_symbol(symbol) for symbol in symbols}
        cached = set() if args.retry_failed else store.cached_symbols(symbols, args.period)
        pending = [symbol for symbol in symbols if symbol not in cached]
        store.start_run(run_id, source_date, len(pending), args.batch_size, args.pause_seconds, args.progress_file)
        progress = {"run_id": run_id, "source_date": source_date, "database": str(args.database), "total_symbols": len(pending), "completed_symbols": 0, "skipped_cached": sorted(cached), "failed_symbols": [], "status": "running", "started_at": started_at}
        write_progress(args.progress_file, progress)
        print(f"Source date: {source_date} | keyed files: {len(files)} | unique assets: {len(assets)}")
        print(f"Download queue: {len(pending)} non-option symbols | cached: {len(cached)} | batch size: {args.batch_size}")
        for batch_number, start in enumerate(range(0, len(pending), args.batch_size), 1):
            batch = pending[start:start + args.batch_size]
            yahoo_batch = sorted({download_map[symbol] for symbol in batch})
            print(f"\nBatch {batch_number}: downloading {len(batch)} assets / {len(yahoo_batch)} Yahoo tickers ({start + 1}-{start + len(batch)} of {len(pending)})")
            try:
                downloaded = yf.download(yahoo_batch, period=args.period, interval="1d", group_by="ticker", progress=False, threads=True)
            except Exception as error:
                downloaded = pd.DataFrame()
                print(f"Batch download failed: {error}")
            for symbol in batch:
                asset_id = store.asset_id(symbol)
                ticker = download_map[symbol]
                bars = bars_from_frame(extract_symbol_frame(downloaded, ticker))
                if bars:
                    count = store.save_bars(asset_id, bars)
                    store.save_download_status(asset_id, "complete", args.period, count)
                else:
                    count = 0
                    progress["failed_symbols"].append(symbol)
                    store.save_download_status(asset_id, "failed", args.period, 0, "No usable bars returned")
                progress["completed_symbols"] += 1
                store.update_run_progress(run_id, progress["completed_symbols"])
                label = f"{symbol} -> {ticker}" if symbol != ticker else symbol
                print(f"  {label}: {count} bars | overall {progress['completed_symbols']}/{len(pending)}")
            store.commit()
            write_progress(args.progress_file, progress)
            if args.max_batches and batch_number >= args.max_batches:
                progress["status"] = "paused"
                write_progress(args.progress_file, progress)
                store.finish_run(run_id, "paused")
                print(f"Paused after batch {batch_number}. Resume with the same command.")
                return 0
            if start + args.batch_size < len(pending) and args.pause_seconds:
                print(f"Waiting {args.pause_seconds} seconds before the next batch.")
                time.sleep(args.pause_seconds)
        progress["status"] = "complete"
        progress["completed_at"] = datetime.now(timezone.utc).isoformat()
        write_progress(args.progress_file, progress)
        store.finish_run(run_id, "complete")
        print(f"\nDatabase build complete: {progress['completed_symbols']}/{len(pending)} symbols processed")
        return 0
    except Exception as error:
        store.finish_run(run_id, "failed", str(error))
        raise
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())

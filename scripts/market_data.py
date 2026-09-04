"""Shared local-first market history loading and ticker translation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from local_data_store import LocalDataStore


TOS_TO_YAHOO = {
    "ES": "SPY", "NQ": "QQQ", "YM": "DIA", "RTY": "IWM",
    "GC": "GLD", "SI": "SLV", "BZ": "BNO", "NG": "UNG",
    "ZT": "SHY", "ZB": "TLT", "ZN": "IEF", "ZF": "IEI",
    "VX": "^VIX", "VIX": "^VIX", "VVIX": "^VVIX",
}


def translate_tos_symbol(symbol: str) -> str:
    clean = str(symbol).strip().upper().lstrip("/")
    return TOS_TO_YAHOO.get(clean, clean)


def frame_from_rows(rows: list[tuple[Any, ...]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(
        rows,
        columns=["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"],
    )
    frame["Date"] = pd.to_datetime(frame["Date"])
    return frame.set_index("Date").sort_index()


def history_to_store_bars(frame: pd.DataFrame) -> list[tuple[Any, ...]]:
    rows = []
    for index, row in frame.dropna(subset=["Close"]).iterrows():
        def value(column: str) -> float | None:
            raw = row.get(column)
            return None if pd.isna(raw) else float(raw)
        rows.append((
            pd.Timestamp(index).date().isoformat(), value("Open"), value("High"),
            value("Low"), value("Close"), value("Adj Close"), value("Volume"),
        ))
    return rows


def load_market_history(
    symbol: str,
    data_source: str,
    db_path: Path,
    minimum_bars: int = 400,
    verbose: bool = False,
) -> pd.DataFrame:
    """Load cached bars first; optionally backfill once and cache the result."""
    clean = str(symbol).strip().upper()
    lookup_symbols = [clean]
    translated = translate_tos_symbol(clean)
    if translated not in lookup_symbols:
        lookup_symbols.append(translated)

    if data_source in ("local", "auto") and db_path.exists():
        store = LocalDataStore(db_path)
        try:
            for lookup in lookup_symbols:
                frame = frame_from_rows(store.market_bars(lookup))
                if len(frame) >= minimum_bars:
                    if verbose:
                        print(f"   Using {len(frame)} local bars for {clean}.")
                    return frame
        finally:
            store.close()

    if data_source == "local":
        return pd.DataFrame()

    try:
        frame = yf.download(translated, period="6y", auto_adjust=False, progress=False)
        if frame.empty:
            return pd.DataFrame()
        if isinstance(frame.columns, pd.MultiIndex):
            for level in range(frame.columns.nlevels):
                if "Close" in {str(value) for value in frame.columns.get_level_values(level)}:
                    frame.columns = frame.columns.get_level_values(level)
                    break
        frame.columns = [str(column) for column in frame.columns]
        store = LocalDataStore(db_path)
        try:
            asset_id = store.upsert_asset(
                clean,
                "future_or_index" if clean.startswith("/") else "equity_or_fund",
                None,
                datetime.now().strftime("%Y-%m-%d"),
            )
            store.save_bars(asset_id, history_to_store_bars(frame))
            store.commit()
        finally:
            store.close()
        if verbose:
            print(f"   Cached {len(frame)} online bars for {clean}.")
        return frame
    except Exception as error:
        if verbose:
            print(f"   Warning: unable to load {clean}: {error}")
        return pd.DataFrame()

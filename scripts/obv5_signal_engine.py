"""
=========================================================================
📡 QUANT TERMINAL: STANDALONE OBV5 SIGNAL GENERATION ENGINE
=========================================================================
File Name: obv5_signal_engine.py

Calculates continuous On-Balance Volume (OBV) vectors on raw daily bars,
detects TOS-style OBV extrema (global mins/maxs) and local turns across 
P1 (360), P2 (270), P3 (180), P4 (90), and P5 (50) trailing windows,
and records structured signal records into SQLite (obv5_signals) and CSV outputs.
"""

from __future__ import annotations

import os
import re
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import yfinance as yf

from local_data_store import LocalDataStore

# Default OBV periods and labels
OBV_PERIODS = {
    360: "P1",
    270: "P2",
    180: "P3",
    90: "P4",
    50: "P5",
}

OBV_SIGNAL_TOLERANCE = 3

# P5_ALL keeps every signal; P4_ALL keeps P1-P4; P5_EXT keeps P5 global extrema only.
HITS_VARIANTS = ("P5_ALL", "P4_ALL", "P5_EXT")

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_DIR / "data" / "quant_terminal.db"
OUTPUT_DIR = PROJECT_DIR / "output" / "obv5_engine"


def translate_tos_symbol(sym: str) -> str:
    """Map Thinkorswim futures notation to ETF/Yahoo equivalents."""
    clean_sym = str(sym).strip().upper()
    if clean_sym.startswith('/'):
        clean_sym = clean_sym[1:]
    mapping = {
        'ES': 'SPY', 'NQ': 'QQQ', 'YM': 'DIA', 'RTY': 'IWM',
        'GC': 'GLD', 'SI': 'SLV', 'BZ': 'BNO', 'NG': 'UNG',
        'ZT': 'SHY', 'ZB': 'TLT', 'ZN': 'IEF', 'ZF': 'IEI',
        'VX': '^VIX', 'VVIX': '^VVIX'
    }
    return mapping.get(clean_sym, clean_sym)


def compute_raw_obv_vector(close_series: pd.Series, volume_series: pd.Series) -> pd.Series:
    """Compute continuous cumulative On-Balance Volume (OBV)."""
    closes = close_series.to_numpy()
    volumes = volume_series.to_numpy()
    obv_array = np.zeros(len(closes), dtype=np.float64)

    current_obv = 0.0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            current_obv += float(volumes[i])
        elif closes[i] < closes[i - 1]:
            current_obv -= float(volumes[i])
        obv_array[i] = current_obv

    return pd.Series(obv_array, index=close_series.index)


def consolidate_obv_signals(results: dict[str, list[dict[str, Any]]], tolerance: int = OBV_SIGNAL_TOLERANCE) -> dict[str, list[dict[str, Any]]]:
    """Collapse nearby same-direction extrema while preserving alternating turns."""
    consolidated = {"min": [], "max": []}

    periods = sorted({
        item["period"]
        for kind in ("min", "max")
        for item in results[kind]
    })

    for period in periods:
        for kind in ("min", "max"):
            directional = sorted(
                (item for item in results[kind] if item["period"] == period),
                key=lambda item: item["offset"]
            )
            cluster = []

            def keep_representative(signals: list[dict[str, Any]]) -> dict[str, Any]:
                if kind == "min":
                    return min(signals, key=lambda item: (item["value"], -item["offset"]))
                return max(signals, key=lambda item: (item["value"], -item["offset"]))

            for signal in directional:
                if cluster and signal["offset"] - cluster[-1]["offset"] <= tolerance:
                    cluster.append(signal)
                else:
                    if cluster:
                        consolidated[kind].append(keep_representative(cluster))
                    cluster = [signal]

            if cluster:
                consolidated[kind].append(keep_representative(cluster))

    for kind in ("min", "max"):
        consolidated[kind].sort(key=lambda item: item["offset"])

    return consolidated


def detect_tos_obv_extrema(
    raw_obv: pd.Series,
    end_idx: int,
    shift_bars: int = 0,
    detailed: bool = True,
    recent_bars: int = 20
) -> dict[str, list[dict[str, Any]]]:
    """
    Scans raw OBV up to end_idx for TOS-style extrema and local turns.
    Returns dictionary with 'min' (accumulation) and 'max' (distribution) lists.
    """
    latest_idx = end_idx - 1
    results: dict[str, list[dict[str, Any]]] = {"min": [], "max": []}

    if latest_idx < 0:
        return results

    for period, label in OBV_PERIODS.items():
        segment_offsets = (0,)
        if detailed and period == 90:
            segment_offsets = (0, 90, 180)
        elif detailed and period == 50:
            segment_offsets = (0, 50, 100, 150, 200)

        for segment_offset in segment_offsets:
            window_end = end_idx - segment_offset
            if window_end <= 0:
                continue

            window_start = max(0, window_end - period)
            window = raw_obv.iloc[window_start:window_end]

            if window.empty:
                continue

            for kind, extreme in (("min", window.min()), ("max", window.max())):
                hits = np.flatnonzero(window.to_numpy() == extreme)
                if len(hits):
                    idx = window_start + hits[-1]
                    results[kind].append({
                        "period": label,
                        "period_bars": period,
                        "offset": idx - latest_idx - shift_bars,
                        "value": float(extreme),
                        "signal_type": "window_extreme",
                        "index_pos": idx,
                    })

    if detailed and recent_bars > 0:
        recent_start = max(0, latest_idx - recent_bars + 1)
        for period, label in ((90, "P4"), (50, "P5")):
            for target_idx in range(recent_start, latest_idx + 1):
                window_start = max(0, target_idx - period + 1)
                window = raw_obv.iloc[window_start:target_idx + 1]
                if window.empty:
                    continue

                target_value = float(raw_obv.iloc[target_idx])
                for kind, extreme in (("min", window.min()), ("max", window.max())):
                    if target_value != float(extreme):
                        continue

                    offset = target_idx - latest_idx - shift_bars
                    prior_same_kind = any(
                        item["period"] == label and item["offset"] == offset
                        for item in results[kind]
                    )
                    if not prior_same_kind:
                        results[kind].append({
                            "period": label,
                            "period_bars": period,
                            "offset": offset,
                            "value": target_value,
                            "signal_type": "window_extreme",
                            "index_pos": target_idx,
                        })

        for target_idx in range(recent_start + 1, latest_idx):
            previous_value = float(raw_obv.iloc[target_idx - 1])
            target_value = float(raw_obv.iloc[target_idx])
            next_value = float(raw_obv.iloc[target_idx + 1])
            turn_candidates = []
            if target_value > previous_value and target_value >= next_value:
                turn_candidates.append(("max", target_value))
            if target_value < previous_value and target_value <= next_value:
                turn_candidates.append(("min", target_value))

            for kind, value in turn_candidates:
                offset = target_idx - latest_idx - shift_bars
                if not any(
                    item["period"] == "P5" and item["offset"] == offset
                    for item in results[kind]
                ):
                    results[kind].append({
                        "period": "P5",
                        "period_bars": 50,
                        "offset": offset,
                        "value": value,
                        "signal_type": "local_turn",
                        "index_pos": target_idx,
                    })

    return consolidate_obv_signals(results)


def load_history_for_symbol(
    symbol: str,
    data_source: str = "local",
    db_path: Path = DATABASE_PATH,
    minimum_bars: int = 400
) -> pd.DataFrame:
    """Load daily OHLCV bars from local SQLite DB or backfill online if permitted."""
    clean_symbol = str(symbol).strip().upper()
    lookup_symbols = [clean_symbol]
    translated = translate_tos_symbol(clean_symbol)
    if translated not in lookup_symbols:
        lookup_symbols.append(translated)

    if data_source in ("local", "auto") and db_path.exists():
        store = LocalDataStore(db_path)
        try:
            for lookup_symbol in lookup_symbols:
                rows = store.market_bars(lookup_symbol)
                if len(rows) >= minimum_bars:
                    df = pd.DataFrame(
                        rows,
                        columns=["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"],
                    )
                    df["Date"] = pd.to_datetime(df["Date"])
                    return df.set_index("Date")
        finally:
            store.close()

    if data_source == "local":
        return pd.DataFrame()

    # Online backfill
    yahoo_symbol = translated
    try:
        downloaded = yf.download(yahoo_symbol, period="6y", auto_adjust=False, progress=False)
        if downloaded.empty:
            return pd.DataFrame()

        if isinstance(downloaded.columns, pd.MultiIndex):
            for level in range(downloaded.columns.nlevels):
                vals = {str(v) for v in downloaded.columns.get_level_values(level)}
                if "Close" in vals:
                    downloaded.columns = downloaded.columns.get_level_values(level)
                    break
        downloaded.columns = [str(c) for c in downloaded.columns]

        if db_path.parent.exists():
            store = LocalDataStore(db_path)
            try:
                asset_id = store.upsert_asset(
                    clean_symbol,
                    "future_or_index" if clean_symbol.startswith("/") else "equity_or_fund",
                    None,
                    datetime.now().strftime("%Y-%m-%d")
                )
                bars = []
                for idx, row in downloaded.dropna(subset=["Close"]).iterrows():
                    bars.append((
                        pd.Timestamp(idx).date().isoformat(),
                        float(row["Open"]) if pd.notna(row.get("Open")) else None,
                        float(row["High"]) if pd.notna(row.get("High")) else None,
                        float(row["Low"]) if pd.notna(row.get("Low")) else None,
                        float(row["Close"]) if pd.notna(row.get("Close")) else None,
                        float(row["Adj Close"]) if pd.notna(row.get("Adj Close")) else None,
                        float(row["Volume"]) if pd.notna(row.get("Volume")) else None,
                    ))
                store.save_bars(asset_id, bars)
                store.commit()
            finally:
                store.close()

        return downloaded
    except Exception as error:
        print(f"   ⚠️ Exception loading history for {clean_symbol}: {error}")
        return pd.DataFrame()


def generate_obv5_signals_for_symbol(
    symbol: str,
    data_source: str = "local",
    db_path: Path = DATABASE_PATH,
    history: pd.DataFrame | None = None,
    shift_bars: int = 0,
    detailed: bool = True,
    recent_bars: int = 20,
    save_to_db: bool = True
) -> list[dict[str, Any]]:
    """
    Generates OBV5 signals for a single symbol and optionally saves them to SQLite.
    Returns a list of structured signal dictionaries.
    """
    clean_sym = str(symbol).strip().upper()
    df_hist = history if history is not None else load_history_for_symbol(
        clean_sym, data_source=data_source, db_path=db_path
    )

    if df_hist.empty or len(df_hist) < 50:
        return []

    close_ser = df_hist["Close"].iloc[:, 0] if isinstance(df_hist["Close"], pd.DataFrame) else df_hist["Close"]
    vol_ser = df_hist["Volume"].iloc[:, 0] if isinstance(df_hist["Volume"], pd.DataFrame) else df_hist["Volume"]

    raw_obv = compute_raw_obv_vector(close_ser, vol_ser)
    end_idx = len(df_hist) - abs(shift_bars)

    if end_idx <= 0:
        return []

    raw_signals = detect_tos_obv_extrema(
        raw_obv,
        end_idx=end_idx,
        shift_bars=abs(shift_bars),
        detailed=detailed,
        recent_bars=recent_bars
    )

    data_first_date = pd.Timestamp(df_hist.index[0]).date().isoformat()
    data_last_date = pd.Timestamp(df_hist.index[-1]).date().isoformat()
    utc_now_str = datetime.now(timezone.utc).isoformat()

    structured_signals: list[dict[str, Any]] = []

    for kind, direction_name in (("min", "green"), ("max", "red")):
        for item in raw_signals[kind]:
            idx_pos = item.get("index_pos")
            if idx_pos is not None and 0 <= idx_pos < len(df_hist):
                sig_date = pd.Timestamp(df_hist.index[idx_pos]).date().isoformat()
            else:
                # fallback calculation
                target_pos = max(0, min(len(df_hist) - 1, end_idx - 1 + item["offset"]))
                sig_date = pd.Timestamp(df_hist.index[target_pos]).date().isoformat()

            structured_signals.append({
                "symbol": clean_sym,
                "signal_date": sig_date,
                "period": item["period"],
                "period_bars": item["period_bars"],
                "direction": direction_name,
                "bar_offset": item["offset"],
                "signal_type": item.get("signal_type", "window_extreme"),
                "signal_value": item["value"],
                "shift_bars": abs(shift_bars),
                "data_first_date": data_first_date,
                "data_last_date": data_last_date,
                "generated_at": utc_now_str,
            })

    if save_to_db and structured_signals and db_path.exists():
        store = LocalDataStore(db_path)
        try:
            asset_id = store.upsert_asset(
                clean_sym,
                "future_or_index" if clean_sym.startswith("/") else "equity_or_fund",
                None,
                datetime.now().strftime("%Y-%m-%d")
            )
            store.save_obv5_signals(asset_id, structured_signals)
            store.commit()
        finally:
            store.close()

    return structured_signals


def run_obv5_signal_engine(
    symbols: list[str] | None = None,
    data_source: str = "local",
    db_path: Path = DATABASE_PATH,
    shift_bars: int = 0,
    detailed: bool = True,
    recent_bars: int = 20,
    output_dir: Path = OUTPUT_DIR
) -> pd.DataFrame:
    """
    Executes the OBV5 signal engine across specified symbols (or all database assets if empty).
    Exports timestamped CSV summaries and returns the combined DataFrame of signals.
    """
    print("========================================================")
    print("🌊 QUANT TERMINAL: EXECUTING OBV5 SIGNAL GENERATION ENGINE")
    print(f"📡 Data Source:        {data_source}")
    print(f"⚖️ Shift Bars:         {shift_bars}")
    print(f"🔍 Detailed Scanning:  {detailed}")
    print(f"🎯 Recent Focus Bars:  {recent_bars}")
    print("========================================================\n")

    if not symbols:
        if db_path.exists():
            store = LocalDataStore(db_path)
            try:
                symbols = store.known_symbols()
            finally:
                store.close()
        else:
            symbols = ["SPY", "QQQ", "IWM", "DIA", "^VIX", "UUP"]

    all_signals: list[dict[str, Any]] = []
    symbol_histories: dict[str, pd.DataFrame] = {}
    processed_count = 0

    for sym in symbols:
        clean_sym = str(sym).strip().upper()
        history = load_history_for_symbol(clean_sym, data_source=data_source, db_path=db_path)
        symbol_histories[clean_sym] = history
        sigs = generate_obv5_signals_for_symbol(
            clean_sym,
            data_source=data_source,
            db_path=db_path,
            history=history,
            shift_bars=shift_bars,
            detailed=detailed,
            recent_bars=recent_bars,
            save_to_db=True
        )
        if sigs:
            all_signals.extend(sigs)
            processed_count += 1

    print(f"✅ Processed {len(symbols)} symbols ({processed_count} yielded active OBV5 signals).")
    print(f"📊 Total Signal Instances Generated: {len(all_signals)}")

    df_signals = pd.DataFrame(all_signals)

    if not df_signals.empty:
        output_dir.mkdir(parents=True, exist_ok=True)
        today_str = datetime.now().strftime("%Y-%m-%d")
        timestamp_str = datetime.now().strftime("%H%M%S")

        csv_filename = f"{today_str}_OBV5_SIGNALS_{timestamp_str}.csv"
        csv_path = output_dir / csv_filename
        df_signals.to_csv(csv_path, index=False)
        print(f"📄 Exported detailed signal ledger -> {csv_path}")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        today_str = datetime.now().strftime("%Y-%m-%d")
        timestamp_str = datetime.now().strftime("%H%M%S")

    def signal_label(signal: pd.Series) -> str:
        direction_code = {"green": "G", "red": "R"}[signal["direction"]]
        if signal["signal_type"] == "local_turn":
            direction_code = f"LT{direction_code}"
        return f"{signal['period']}:{direction_code}"

    def build_summary(scoped_signals: pd.DataFrame) -> pd.DataFrame:
        grouped = {
            symbol: group for symbol, group in scoped_signals.groupby("symbol")
        } if not scoped_signals.empty else {}

        summary_rows = []
        for symbol in symbols:
            clean_sym = str(symbol).strip().upper()
            group = grouped.get(clean_sym, pd.DataFrame())
            recent_sigs = group[group["bar_offset"] >= -recent_bars] if not group.empty else group
            latest_counts = [0, 0, 0]
            latest_labels = [[], [], []]
            if not group.empty:
                for _, signal in group[group["bar_offset"].between(-2, 0)].iterrows():
                    slot = int(signal["bar_offset"]) + 2
                    latest_counts[slot] += 1
                    latest_labels[slot].append(signal_label(signal))
            latest_periods = [
                ",".join(sorted(labels)) if labels else "-"
                for labels in latest_labels
            ]
            history = symbol_histories.get(clean_sym, pd.DataFrame())
            data_last_date = ""
            if not history.empty:
                data_last_date = pd.Timestamp(history.index[-1]).date().isoformat()
            green_count = len(group[group["direction"] == "green"]) if not group.empty else 0
            red_count = len(group[group["direction"] == "red"]) if not group.empty else 0
            periods_triggered = "|".join(sorted(group["period"].unique())) if not group.empty else "-"

            summary_rows.append({
                "Symbol": clean_sym,
                "Total_Signals": len(group),
                "Accumulation_Green": green_count,
                "Distribution_Red": red_count,
                f"Recent_Signals_{recent_bars}B": len(recent_sigs),
                "Latest_Signals_3B": "|".join(str(count) for count in latest_counts),
                "Latest_Signal_Periods_3B": "|".join(latest_periods),
                "Periods_Triggered": periods_triggered,
                "Data_Last_Date": data_last_date,
            })
        return pd.DataFrame(summary_rows)

    def latest_hits(summary: pd.DataFrame) -> pd.DataFrame:
        return summary[
            summary["Latest_Signals_3B"].str.split("|").apply(
                lambda counts: any(int(count) > 0 for count in counts)
            )
        ].copy()

    df_summary = build_summary(df_signals)
    summary_filename = f"{today_str}_OBV5_SUMMARY_{timestamp_str}.csv"
    summary_path = output_dir / summary_filename
    df_summary.to_csv(summary_path, index=False)
    print(f"📊 Exported summary report -> {summary_path}")

    if df_signals.empty:
        scoped_variants = {variant: df_signals for variant in HITS_VARIANTS}
    else:
        scoped_variants = {
            "P5_ALL": df_signals,
            "P4_ALL": df_signals[df_signals["period"] != "P5"],
            "P5_EXT": df_signals[
                (df_signals["period"] == "P5")
                & (df_signals["signal_type"] == "window_extreme")
            ],
        }

    for variant, scoped_signals in scoped_variants.items():
        variant_hits = latest_hits(build_summary(scoped_signals))
        hits_path = output_dir / f"{today_str}_OBV5_LATEST3_HITS_{variant}_{timestamp_str}.csv"
        variant_hits.to_csv(hits_path, index=False)
        print(f"🎯 Exported {variant} latest-three-bar hits ({len(variant_hits)} symbols) -> {hits_path}")

    return df_signals


def main():
    parser = argparse.ArgumentParser(description="QUANT TERMINAL: OBV5 Signal Engine")
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated symbols or 'all' (default: all db assets)")
    parser.add_argument("--data-source", choices=("local", "auto", "online"), default="local", help="Market data source")
    parser.add_argument("--shift", type=int, default=0, help="Mathematical backtest shift in bars")
    parser.add_argument("--detailed", type=int, choices=(0, 1), default=1, help="Detailed P4/P5 recent scanning: 1=on, 0=off")
    parser.add_argument("--recent_bars", type=int, default=20, help="Recent focus bar scan depth (default: 20)")

    args = parser.parse_args()

    symbol_list = []
    if args.symbols and args.symbols.lower() != "all":
        symbol_list = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    run_obv5_signal_engine(
        symbols=symbol_list if symbol_list else None,
        data_source=args.data_source,
        shift_bars=args.shift,
        detailed=(args.detailed == 1),
        recent_bars=args.recent_bars
    )


if __name__ == "__main__":
    main()

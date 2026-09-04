"""Persistent normalized asset-to-anchor delta calculations.

This module owns the daily calculations previously embedded in
``macro_barometer.py``: normalized asset price versus normalized VIX, UUP,
and a normalized rolling SMA. Market bars are read from SQLite first and
online backfills are cached into the same database when explicitly allowed.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from local_data_store import LocalDataStore
from market_data import load_market_history
from macro_barometer_vector import telemetry_index_symbols


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_DIR / "data" / "quant_terminal.db"


def normalize_shifted_series(
    series: pd.Series,
    range_bars: int,
    shift_bars: int,
    scale_min: float,
    scale_max: float,
) -> pd.Series:
    """Match macro_barometer's static min/max normalization exactly."""
    end = len(series) - shift_bars
    start = max(0, end - range_bars)
    bounds = series.iloc[start:end].dropna()
    if bounds.empty:
        return pd.Series(np.nan, index=series.index, dtype="float64")
    minimum = float(bounds.min())
    maximum = float(bounds.max())
    denominator = maximum - minimum if maximum != minimum else 1.0
    return scale_min + ((series - minimum) / denominator) * (scale_max - scale_min)


def calculate_delta_metrics(
    asset: pd.DataFrame,
    vix: pd.DataFrame,
    uup: pd.DataFrame,
    normalization_window: int = 252,
    range_bars: int = 400,
    shift_bars: int = 0,
    scale_min: float = 1.0,
    scale_max: float = 11.0,
) -> pd.DataFrame:
    """Calculate the same normalized values and deltas used by macro_barometer."""
    if normalization_window < 1 or range_bars < 1 or shift_bars < 0:
        raise ValueError("normalization_window and range_bars must be positive; shift_bars cannot be negative")
    frame = pd.DataFrame({
        "asset_close": asset["Close"],
        "vix_close": vix["Close"],
        "uup_close": uup["Close"],
    }).sort_index().ffill().dropna()
    if frame.empty:
        return frame

    frame["sma_close"] = frame["asset_close"].rolling(
        normalization_window, min_periods=1
    ).mean()
    for source, target in (
        ("asset_close", "norm_asset"),
        ("vix_close", "norm_vix"),
        ("uup_close", "norm_uup"),
        ("sma_close", "norm_sma"),
    ):
        frame[target] = normalize_shifted_series(
            frame[source], range_bars, shift_bars, scale_min, scale_max
        )
    frame["delta_vix"] = frame["norm_asset"] - frame["norm_vix"]
    frame["delta_uup"] = frame["norm_asset"] - frame["norm_uup"]
    frame["delta_sma"] = frame["norm_asset"] - frame["norm_sma"]
    return frame


def calculate_and_store_asset(
    symbol: str,
    data_source: str = "local",
    db_path: Path = DATABASE_PATH,
    normalization_window: int = 252,
    range_bars: int = 400,
    shift_bars: int = 0,
    scale_min: float = 1.0,
    scale_max: float = 11.0,
) -> pd.DataFrame:
    """Calculate one asset's deltas and upsert every aligned daily result."""
    minimum_bars = max(normalization_window, range_bars, 400)
    asset = load_market_history(symbol, data_source, db_path, minimum_bars, verbose=True)
    vix = load_market_history("^VIX", data_source, db_path, minimum_bars, verbose=True)
    uup = load_market_history("UUP", data_source, db_path, minimum_bars, verbose=True)
    metrics = calculate_delta_metrics(
        asset, vix, uup, normalization_window, range_bars, shift_bars, scale_min, scale_max
    )
    if metrics.empty or not db_path.exists():
        return metrics

    store = LocalDataStore(db_path)
    try:
        asset_id = store.upsert_asset(
            str(symbol).strip().upper(),
            "future_or_index" if str(symbol).startswith("/") else "equity_or_fund",
            None,
            datetime.now().strftime("%Y-%m-%d"),
        )
        records = []
        for bar_date, row in metrics.iterrows():
            records.append({
                "bar_date": pd.Timestamp(bar_date).date().isoformat(),
                "normalization_window": normalization_window,
                "range_bars": range_bars,
                "shift_bars": shift_bars,
                **{column: (None if pd.isna(row[column]) else float(row[column])) for column in metrics.columns},
            })
        store.save_delta_metrics(asset_id, records)
        store.commit()
    finally:
        store.close()
    return metrics


def run_delta_engine(
    symbols: list[str],
    data_source: str = "local",
    db_path: Path = DATABASE_PATH,
    **options: Any,
) -> None:
    for symbol in symbols:
        metrics = calculate_and_store_asset(symbol, data_source, db_path, **options)
        print(f"   {symbol}: stored {len(metrics)} delta rows")


def main() -> None:
    parser = argparse.ArgumentParser(description="Persistent asset/VIX/UUP/SMAn delta engine")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols; default is telemetry index vector")
    parser.add_argument("--data-source", choices=("local", "auto", "online"), default="local")
    parser.add_argument("--normalization-window", type=int, default=252)
    parser.add_argument("--range", dest="range_bars", type=int, default=400)
    parser.add_argument("--shift", type=int, default=0)
    parser.add_argument("--scale-min", type=float, default=1.0)
    parser.add_argument("--scale-max", type=float, default=11.0)
    args = parser.parse_args()
    symbols = [value.strip().upper() for value in args.symbols.split(",") if value.strip()]
    run_delta_engine(
        symbols or telemetry_index_symbols(),
        data_source=args.data_source,
        normalization_window=args.normalization_window,
        range_bars=args.range_bars,
        shift_bars=abs(args.shift),
        scale_min=args.scale_min,
        scale_max=args.scale_max,
    )


if __name__ == "__main__":
    main()

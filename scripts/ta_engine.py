"""Reusable technical-analysis calculations for macro chart Panel 3."""

from __future__ import annotations

import numpy as np
import pandas as pd


MF_DAMPENER = 2.0
STOCH_DAMPENER = 2.0


def normalize_panel3_series(
    series: pd.Series,
    range_param: int,
    shift_param: int,
    scale_min: float = 1.0,
    scale_max: float = 11.0,
) -> pd.Series:
    """Normalize a TA series using the fixed historical-to-latest window."""
    end_idx = len(series) - shift_param
    start_idx = max(0, end_idx - range_param)
    window = series.iloc[start_idx:end_idx].dropna()
    if window.empty:
        return pd.Series(np.nan, index=series.index)

    minimum = float(window.min())
    maximum = float(window.max())
    denominator = maximum - minimum
    if denominator == 0:
        return pd.Series(scale_min, index=series.index)

    return scale_min + ((series - minimum) / denominator) * (scale_max - scale_min)


def compute_kst(close: pd.Series) -> pd.Series:
    """Compute the standard four-ROC Know Sure Thing oscillator."""
    def roc(period: int) -> pd.Series:
        previous = close.shift(period).replace(0, np.nan)
        return ((close - previous) / previous) * 100.0

    sroc1 = roc(10).rolling(10).mean()
    sroc2 = roc(15).rolling(10).mean()
    sroc3 = roc(20).rolling(10).mean()
    sroc4 = roc(30).rolling(15).mean()
    return sroc1 + (2.0 * sroc2) + (3.0 * sroc3) + (4.0 * sroc4)


def compute_money_flow_oscillator(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    period: int,
) -> pd.Series:
    """Compute a Chaikin-style money-flow oscillator safely."""
    price_range = (high - low).replace(0, np.nan)
    money_flow_multiplier = ((close - low) - (high - close)) / price_range
    money_flow_volume = money_flow_multiplier * volume
    volume_sum = volume.rolling(period).sum().replace(0, np.nan)
    return money_flow_volume.rolling(period).sum() / volume_sum


def compute_tmf(high, low, close, volume, period: int = 21) -> pd.Series:
    """Compute Twiggs Money Flow."""
    return compute_money_flow_oscillator(high, low, close, volume, period)


def compute_cmf(high, low, close, volume, period: int = 20) -> pd.Series:
    """Compute Chaikin Money Flow."""
    return compute_money_flow_oscillator(high, low, close, volume, period)


def compute_cvd(close: pd.Series, volume: pd.Series) -> pd.Series:
    """Compute directional-volume CVD from daily OHLCV data."""
    direction = np.sign(close.diff()).fillna(0.0)
    return (direction * volume).cumsum()


def calculate_panel3_indicators(
    frame: pd.DataFrame,
    range_bars: int,
    shift_bars: int,
    mf_window: int = 12,
    stoch_k: int = 9,
    stoch_d: int = 5,
    scale_min: float = 1.0,
    scale_max: float = 11.0,
) -> pd.DataFrame:
    """Return Panel 3 TA columns without mutating the input frame."""
    result = frame.copy()
    result["tmf"] = compute_tmf(result["High"], result["Low"], result["Close"], result["Volume"])
    result["cmf"] = compute_cmf(result["High"], result["Low"], result["Close"], result["Volume"])
    result["cvd"] = compute_cvd(result["Close"], result["Volume"])
    result["kst"] = compute_kst(result["Close"])
    for indicator_name in ("tmf", "cmf", "cvd", "kst"):
        result[f"norm_{indicator_name}"] = normalize_panel3_series(
            result[indicator_name], range_bars, shift_bars, scale_min, scale_max
        )

    roll_low = result["Low"].rolling(window=mf_window, min_periods=1).min()
    roll_high = result["High"].rolling(window=mf_window, min_periods=1).max()
    denom_mf = np.where((roll_high - roll_low) == 0, 1.0, roll_high - roll_low)
    raw_market_forecast = ((result["Close"] - roll_low) / denom_mf) * 100.0
    result["market_forecast"] = 50.0 + (raw_market_forecast - 50.0) / MF_DAMPENER

    stoch_lowest = result["Low"].rolling(window=stoch_k, min_periods=1).min()
    stoch_highest = result["High"].rolling(window=stoch_k, min_periods=1).max()
    denom_stoch = np.where((stoch_highest - stoch_lowest) == 0, 1.0, stoch_highest - stoch_lowest)
    raw_pct_k = ((result["Close"] - stoch_lowest) / denom_stoch) * 100.0
    slow_k = raw_pct_k.rolling(window=3, min_periods=1).mean()
    slow_d = slow_k.rolling(window=stoch_d, min_periods=1).mean()
    result["stoch_delta_wave"] = 50.0 + ((slow_k - slow_d) * 1.5) / STOCH_DAMPENER
    return result

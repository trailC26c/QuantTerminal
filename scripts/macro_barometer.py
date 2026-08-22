"""
=========================================================================
📡 QUANT TERMINAL: STEP 5 MULTI-REGIME REAL-TIME MACRO BAROMETER
=========================================================================
File Name: macro_barometer.py
Block 1 of 6: Environment Modules, CLI Argument Parsers, and Directory Layouts.
Standardized to an absolute flat 4-space nested indentation frame.
"""

import os
import glob
import re
import time
import json
import traceback
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

# Silence yfinance terminal internal data warnings
import logging
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

# =========================================================================
# 🎛️ COMMAND LINE INTERFACE (CLI) ARGUMENT EXTENSION PARSER
# =========================================================================
parser = argparse.ArgumentParser(description="QUANT TERMINAL: Macro Engine")
parser.add_argument("--window", type=int, default=252, help="Normalization lookback window (default: 252)")
parser.add_argument(
    "--shift",
    type=int,
    default=0,
    help="Mathematical backtest shift; positive or negative N evaluates N bars back (default: 0)"
)
parser.add_argument("--range", type=int, default=400, help="Visual plot horizon range in bars (default: 400)")
parser.add_argument("--scale_min", type=float, default=1.0, help="Lower bound coefficient (default: 1.0)")
parser.add_argument("--scale_max", type=float, default=11.0, help="Upper bound ceiling coefficient (default: 11.0)")

# OSCILLATOR LOOKBACK SWITCHES
parser.add_argument("--mf_window", type=int, default=12, help="Market Forecast intermediate lookback (default: 12)")
parser.add_argument("--stoch_k", type=int, default=9, help="Stochastic Slow %K channel window (default: 9)")
parser.add_argument("--stoch_d", type=int, default=5, help="Stochastic Slow %D smoothing filter (default: 5)")
parser.add_argument(
    "--mf_stoch",
    type=int,
    choices=(0, 1),
    default=0,
    help="Plot Market Forecast and Stochastic lines: 1=on, 0=off (default)"
)
parser.add_argument(
    "--obv5_detailed",
    type=int,
    choices=(0, 1),
    default=1,
    help="Stitch P4/P5 OBV extrema scans across recent blocks: 1=on, 0=off (default: on)"
)
parser.add_argument(
    "--price_candlestick",
    type=int,
    choices=(0, 1),
    default=1,
    help="Plot raw price as OHLC candlesticks: 1=on, 0=off (default)"
)
parser.add_argument(
    "--obv5_recent_bars",
    type=int,
    default=20,
    help="Recent P4/P5 focus bars: 0=off (default: 20)"
)

args, unknown = parser.parse_known_args()

if args.obv5_recent_bars < 0:
    parser.error("--obv5_recent_bars must be zero or greater")

NORM_WINDOW = args.window
SHIFT_BARS = abs(args.shift)
PLOT_RANGE = args.range
SCALE_MIN = args.scale_min
SCALE_MAX = args.scale_max
MF_WINDOW = args.mf_window
STOCH_K = args.stoch_k
STOCH_D = args.stoch_d
MF_STOCH = args.mf_stoch
OBV5_DETAILED = args.obv5_detailed
PRICE_CANDLESTICK = args.price_candlestick
RECENT_OBV_SIGNAL_BARS = args.obv5_recent_bars

# =========================================================================
# 📂 DIRECTORY STRUCTURE & ROUTING SPECIFICATIONS
# =========================================================================
BASE_DIR = r"C:\Users\tcnet\TOS_Data_Local"
WATCHLIST_DIR = os.path.join(BASE_DIR, "sanitized_watchlists")

PROJECT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = str(PROJECT_DIR / "output")
MACRO_DIR = OUTPUT_DIR
CHARTS_DIR = str(PROJECT_DIR / "output" / "charts")

LEGACY_MACRO_DIR = os.path.join(BASE_DIR, "macro_barometer")

os.makedirs(MACRO_DIR, exist_ok=True)
os.makedirs(CHARTS_DIR, exist_ok=True)

SPRING_OFFSET = 0.0

def parse_telemetry_config():
    """Reads telemetry_list.txt configuration and handles multi-line vertical columns."""
    project_config_path = os.path.join(PROJECT_DIR, "data", "telemetry_list.txt")
    config_path = os.path.join(MACRO_DIR, "telemetry_list.txt")
    legacy_config_path = os.path.join(LEGACY_MACRO_DIR, "telemetry_list.txt")
    index_symbols = []
    alpha_singles = []
    current_section = None

    if os.path.exists(project_config_path):
        config_path = project_config_path
    elif not os.path.exists(config_path) and os.path.exists(legacy_config_path):
        config_path = legacy_config_path

    if not os.path.exists(config_path):
        return index_symbols, alpha_singles

    with open(config_path, 'r', encoding='utf-8') as f:
        for line in f:
            line_str = line.strip()
            if not line_str or line_str.startswith('#'): continue
            if line_str == "[INDEX_PAIRS]":
                current_section = "INDEX"
                continue
            elif line_str == "[ALPHA_SINGLES]":
                current_section = "ALPHA"
                continue
            
            tokens = [t.strip().upper() for t in line_str.split(',') if t.strip()]
            if current_section == "INDEX": index_symbols.extend(tokens)
            elif current_section == "ALPHA": alpha_singles.extend(tokens)

    return index_symbols, alpha_singles
"""
QUANT TERMINAL - Step 5: Real-Time Multi-Regime Macro Barometer Dashboard
Block 2 of 6: Technical Indicator Engines and Cumulative Math Normalizers.
🎯 TYPE SHIELD ADDED: Natively forces date objects to strings to prevent strptime crashes.
"""

def translate_tos_symbol(sym):
    """Maps Thinkorswim system notation futures seamlessly into ETF anchors."""
    clean_sym = str(sym).strip().upper()
    if clean_sym.startswith('/'): clean_sym = clean_sym[1:]
    mapping = {
        'ES': 'SPY', 'NQ': 'QQQ', 'YM': 'DIA', 'RTY': 'IWM', 
        'GC': 'GLD', 'SI': 'SLV', 'BZ': 'BNO', 'NG': 'UNG',
        'ZT': 'SHY', 'ZB': 'TLT', 'ZN': 'IEF', 'ZF': 'IEI'
    }
    return mapping.get(clean_sym, clean_sym)


def min_max_normalize_shifted_series(window, shift, series):
    """Calculates static bounds across defined blocks to enforce continuous curves."""
    total_len = len(series)
    end_idx = total_len - shift
    start_idx = max(0, end_idx - PLOT_RANGE)
    boundary_range_subset = series.iloc[start_idx:end_idx]
    h_min = boundary_range_subset.min()
    h_max = boundary_range_subset.max()
    denom = h_max - h_min if (h_max - h_min) != 0 else 1.0
    return pd.Series(SCALE_MIN + ((series - h_min) / denom) * (SCALE_MAX - SCALE_MIN), index=series.index)


def compute_raw_obv_vector(close_series, volume_series):
    """Computes continuous cumulative On-Balance Volume on raw statistics first."""
    closes = close_series.to_numpy()
    volumes = volume_series.to_numpy()
    obv_array = np.zeros(len(closes), dtype=np.float64)
    
    current_obv = 0.0
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]:
            current_obv += float(volumes[i])
        elif closes[i] < closes[i-1]:
            current_obv -= float(volumes[i])
        obv_array[i] = current_obv
        
    return pd.Series(obv_array, index=close_series.index)

OBV_PERIODS = {
    360: "P1",
    270: "P2",
    180: "P3",
    90: "P4",
    50: "P5",
}
OBV_SIGNAL_TOLERANCE = 3


def consolidate_obv_signals(results, tolerance=OBV_SIGNAL_TOLERANCE):
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

            def keep_representative(signals):
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


def detect_tos_obv_extrema(raw_obv, end_idx, shift_bars=0, detailed=False):
    """Match TOS: latest global min/max in each trailing period."""
    latest_idx = end_idx - 1
    results = {"min": [], "max": []}

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

            for kind, extreme in (
                ("min", window.min()),
                ("max", window.max())
            ):
                hits = np.flatnonzero(window.to_numpy() == extreme)
                if len(hits):
                    idx = window_start + hits[-1]
                    results[kind].append({
                        "period": label,
                        "period_bars": period,
                        "offset": idx - latest_idx - shift_bars,
                        "value": float(extreme),
                    })

    if detailed:
        recent_start = max(0, latest_idx - RECENT_OBV_SIGNAL_BARS + 1)
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
                    })

    return consolidate_obv_signals(results)

def calculate_opex_coordinates(df_chart, timeline_x, effective_today_date):
    """Returns historical OpEx lines plus the next two projected OpEx dates."""
    effective_date = pd.Timestamp(effective_today_date).normalize()
    chart_dates = pd.DatetimeIndex(df_chart.index).tz_localize(None).normalize()
    last_chart_date = chart_dates[-1]

    def third_friday(year, month):
        first_day = pd.Timestamp(year=year, month=month, day=1)
        return first_day + pd.offsets.Week(weekday=4) + pd.Timedelta(weeks=2)

    historical_x = []
    for year_month in pd.period_range(
        chart_dates[0], last_chart_date, freq="M"
    ):
        expiry = third_friday(year_month.year, year_month.month)
        if expiry <= last_chart_date:
            idx = chart_dates.searchsorted(expiry, side="left")
            if idx < len(chart_dates):
                historical_x.append(float(timeline_x[idx]))

    projected_x = []
    cursor = effective_date.replace(day=1)

    while len(projected_x) < 2:
        expiry = third_friday(cursor.year, cursor.month)

        if expiry > effective_date:
            bars_forward = np.busday_count(
                last_chart_date.date(),
                expiry.date()
            )
            projected_x.append(float(timeline_x[-1] + bars_forward))

        cursor = cursor + pd.offsets.MonthBegin(1)

    return historical_x + projected_x, 15, 45
"""
QUANT TERMINAL - Step 5: Real-Time Multi-Regime Macro Barometer Dashboard
Block 3 of 6: Master Charting Data Frame Pre-Processors and Raw OBV Radar Sweeps.
"""

def generate_unified_two_pane_chart(symbol, anchors, consensus_positions, current_run_date):
    """Processes indices and alpha tokens identically into stretched 2-pane charts."""
    clean_sym = str(symbol).strip().upper()
    lbl_sym = clean_sym.replace('/', '')
    tick_lookup = translate_tos_symbol(clean_sym)
    
    try:
        # Pull 6 years of deep history to provide complete lookback cushions
        px_raw = yf.download(tick_lookup, period="6y", auto_adjust=False, progress=False)
        close_ser = px_raw['Close'].iloc[:, 0] if isinstance(px_raw['Close'], pd.DataFrame) else px_raw['Close']
        vol_ser = px_raw['Volume'].iloc[:, 0] if isinstance(px_raw['Volume'], pd.DataFrame) else px_raw['Volume']
        open_ser = px_raw['Open'].iloc[:, 0] if isinstance(px_raw['Open'], pd.DataFrame) else px_raw['Open']
        high_ser = px_raw['High'].iloc[:, 0] if isinstance(px_raw['High'], pd.DataFrame) else px_raw['High']
        low_ser = px_raw['Low'].iloc[:, 0] if isinstance(px_raw['Low'], pd.DataFrame) else px_raw['Low']
        
        df_p = pd.DataFrame(index=close_ser.index)
        df_p['Close'] = close_ser
        df_p['Volume'] = vol_ser
        df_p['Open'] = open_ser
        df_p['High'] = high_ser
        df_p['Low'] = low_ser
        df_p.index = df_p.index.tz_localize(None)
        df_p = df_p.join(anchors, how='inner').dropna()
        
        # --- THE PHYSICAL ACCELERATOR: RAW OBV5 ANALYSIS LOOP ---
        df_p['raw_obv'] = compute_raw_obv_vector(df_p['Close'], df_p['Volume'])
        
        buy_marker_stack = {}
        sell_marker_stack = {}

        end_idx = len(df_p) - SHIFT_BARS
        start_idx = max(0, end_idx - PLOT_RANGE)

        df_slice = df_p.iloc[start_idx:end_idx].copy()
        timeline_x = np.arange(-len(df_slice) + 1, 1) - SHIFT_BARS

        obv_signal_cache = detect_tos_obv_extrema(
            df_p["raw_obv"],
            end_idx=end_idx,
            shift_bars=SHIFT_BARS,
            detailed=OBV5_DETAILED == 1
        )

        # TOS semantics:
        # global minimum = up/accumulation arrow
        # global maximum = down/distribution arrow
        for signal in obv_signal_cache["min"]:
            if -len(df_slice) <= signal["offset"] <= -SHIFT_BARS:
                buy_marker_stack.setdefault(
                    signal["offset"], []
                ).append(signal["period"])

        for signal in obv_signal_cache["max"]:
            if -len(df_slice) <= signal["offset"] <= -SHIFT_BARS:
                sell_marker_stack.setdefault(
                    signal["offset"], []
                ).append(signal["period"])

        g_min_p = df_slice['Close'].min(); g_max_p = df_slice['Close'].max()
        denom_p = g_max_p - g_min_p if (g_max_p - g_min_p) != 0 else 1.0
        df_slice['norm_A'] = SCALE_MIN + ((df_slice['Close'] - g_min_p) / denom_p) * (SCALE_MAX - SCALE_MIN)
        normalize_price = lambda price_series: SCALE_MIN + ((price_series - g_min_p) / denom_p) * (SCALE_MAX - SCALE_MIN)


        # --- ADVANCED PANEL 2 INDEPENDENT INDICATOR PIPELINES ---
        raw_obv_wave = min_max_normalize_shifted_series(NORM_WINDOW, SHIFT_BARS, df_slice['raw_obv'])
        
        # Pure amplitude scaling factor right from the absolute zero floor up
        OBV5_MULTIP = 1.0
        df_slice['norm_OBV_wave'] = raw_obv_wave * OBV5_MULTIP
        
        roll_low = df_slice['Low'].rolling(window=MF_WINDOW, min_periods=1).min()
        roll_high = df_slice['High'].rolling(window=MF_WINDOW, min_periods=1).max()
        denom_mf = np.where((roll_high - roll_low) == 0, 1.0, roll_high - roll_low)
        raw_market_forecast = ((df_slice['Close'] - roll_low) / denom_mf) * 100.0
        
        # INTERNAL FACTOR DAMPENERS: Compresses raw indicator amplitudes by half to prevent panel clutter
        MF_DAMPENER = 2.0
        STOCH_DAMPENER = 2.0
        df_slice['market_forecast'] = 50.0 + (raw_market_forecast - 50.0) / MF_DAMPENER
        
        stoch_lowest = df_slice['Low'].rolling(window=STOCH_K, min_periods=1).min()
        stoch_highest = df_slice['High'].rolling(window=STOCH_K, min_periods=1).max()
        denom_stoch = np.where((stoch_highest - stoch_lowest) == 0, 1.0, stoch_highest - stoch_lowest)
        raw_pct_k = ((df_slice['Close'] - stoch_lowest) / denom_stoch) * 100.0
        
        slow_k = raw_pct_k.rolling(window=3, min_periods=1).mean()
        slow_d = slow_k.rolling(window=STOCH_D, min_periods=1).mean()
        df_slice['stoch_delta_wave'] = 50.0 + ((slow_k - slow_d) * 1.5) / STOCH_DAMPENER
        
        df_slice['sma_r'] = df_slice['Close'].rolling(window=NORM_WINDOW, min_periods=1).mean()
        df_slice['norm_s'] = min_max_normalize_shifted_series(NORM_WINDOW, SHIFT_BARS, df_slice['sma_r'])
        df_slice['vs_vx'] = df_slice['norm_A'] - df_slice['norm_VIX']
        df_slice['vs_uup'] = df_slice['norm_A'] - df_slice['norm_UUP']
        df_slice['spring'] = df_slice['norm_A'] - df_slice['norm_s']
        
        # FIX PASS INITIALIZATION KEY: Enforces absolute dual-Y channel readiness across both panels
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05,
            row_heights=[0.6, 0.4],
            specs=[[{"secondary_y": True}], [{"secondary_y": True}]],
            subplot_titles=("Panel 1: Asset price (raw/norm), VIX, UUP norm", "Panel 2: Delta norm Asset to norm VIX, UUP, SMA<n>")
        )
        x_vals = timeline_x.tolist()
        
        # Panel 1 Traces
        if PRICE_CANDLESTICK == 1:
            fig.add_trace(
                go.Candlestick(
                    x=x_vals,
                    open=normalize_price(df_slice['Open']).tolist(),
                    high=normalize_price(df_slice['High']).tolist(),
                    low=normalize_price(df_slice['Low']).tolist(),
                    close=normalize_price(df_slice['Close']).tolist(),
                    name=f"norm_{lbl_sym} OHLC",
                    increasing_line_color="#00FF66",
                    increasing_line_width=1.0,
                    increasing_fillcolor="rgba(0,0,0,0)",
                    decreasing_line_color="#FF3B30",
                    decreasing_line_width=1.0,
                    decreasing_fillcolor="#FF3B30",
                    showlegend=True
                ),
                row=1,
                col=1,
                secondary_y=False
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=x_vals,
                    y=df_slice['norm_A'].tolist(),
                    name=f"norm_{lbl_sym}",
                    line=dict(color='#00F0FF', width=2.5)
                ),
                row=1,
                col=1,
                secondary_y=False
            )
        fig.add_trace(go.Scatter(x=x_vals, y=df_slice['norm_VIX'].tolist(), name='norm_VIX', line=dict(color='#FF3B30', width=1.5, dash='dot')), row=1, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=x_vals, y=df_slice['norm_UUP'].tolist(), name='norm_UUP', line=dict(color='#34C759', width=1.5, dash='dot')), row=1, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=x_vals, y=df_slice['Close'].tolist(), name=f"Raw {lbl_sym} Price", line=dict(color='#63E6BE', width=1.0)), row=1, col=1, secondary_y=True)
        
        # Plot Stacked Accumulation Entries
        # Accumulation / global minimum signals
        for x_pos, hit_labels in buy_marker_stack.items():
            base_y = float(
                df_slice['norm_A'].iloc[int(x_pos - timeline_x[0])]
            )
            for stack_idx, lbl in enumerate(hit_labels):
                offset_y = base_y - 0.45 - (stack_idx * 0.40)
                marker_color = "#00FFFF" if lbl == "P5" else "#00FF66"

                fig.add_trace(go.Scatter(
                    x=[x_pos],
                    y=[offset_y],
                    mode="markers+text",
                    name=f"Accumulation {lbl}",
                    showlegend=False,
                    marker=dict(
                        symbol="triangle-up",
                        size=10,
                        color=marker_color
                    ),
                    text=f"{lbl}",
                    textposition="middle right",
                    textfont=dict(size=9, color=marker_color)
                ), row=1, col=1, secondary_y=False)
                
        # Plot Stacked Distribution Breakdowns
        for x_pos, hit_labels in sell_marker_stack.items():
            base_y = float(
                df_slice['norm_A'].iloc[int(x_pos - timeline_x[0])]
            )
            for stack_idx, lbl in enumerate(hit_labels):
                offset_y = base_y + 0.45 + (stack_idx * 0.40)
                marker_color = "#FF9500" if lbl == "P5" else "#FF3B30"

                fig.add_trace(
                    go.Scatter(
                        x=[x_pos], y=[offset_y], mode="markers+text", name=f"Distribution {lbl}", showlegend=False,
                        marker=dict(symbol="triangle-down", size=10, color=marker_color),
                        text=f"{lbl}", textposition="middle right", textfont=dict(size=9, color=marker_color)
                    ),
                    row=1, col=1, secondary_y=False
                )

        panel_1_trace_count = len(fig.data)
        panel_1_debug = []
        for trace in fig.data[:panel_1_trace_count]:
            x_values = np.asarray(trace.x if trace.x is not None else [], dtype=float)
            if trace.type == "candlestick":
                y_values = np.concatenate([
                    np.asarray(getattr(trace, field), dtype=float)
                    for field in ("open", "high", "low", "close")
                ])
            else:
                y_values = np.asarray(trace.y if trace.y is not None else [], dtype=float)
            finite_y_values = y_values[np.isfinite(y_values)]
            panel_1_debug.append({
                "name": trace.name,
                "type": trace.type,
                "xaxis": trace.xaxis or "x",
                "yaxis": trace.yaxis or "y",
                "x_length": int(x_values.size),
                "x_finite": int(np.isfinite(x_values).sum()),
                "y_length": int(y_values.size),
                "y_finite": int(np.isfinite(y_values).sum()),
                "x_first": float(x_values[0]) if x_values.size else None,
                "x_last": float(x_values[-1]) if x_values.size else None,
                "y_min": float(finite_y_values.min()) if finite_y_values.size else None,
                "y_max": float(finite_y_values.max()) if finite_y_values.size else None,
            })
        
        # Panel 2 Traces
        fig.add_trace(go.Scatter(x=x_vals, y=df_slice['vs_vx'].tolist(), name=f'vs VIX Delta', line=dict(color='#FF9500', width=2.2)), row=2, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=x_vals, y=df_slice['vs_uup'].tolist(), name=f'vs UUP Delta', line=dict(color='#AF52DE', width=2.2)), row=2, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=x_vals, y=df_slice['spring'].tolist(), name=f'vs SMA Delta (spring ext.)', line=dict(color='#00FF66', width=2.5)), row=2, col=1, secondary_y=False)
        fig.add_trace(
            go.Scatter(
                x=x_vals,
                y=df_slice['norm_OBV_wave'].tolist(),
                name="norm OBV5",
                line=dict(
                    color="#4D96FF",
                    width=1.0,
                    dash="solid"
                )
            ),
            row=2,
            col=1,
            secondary_y=True
        )
        if MF_STOCH == 1:
            fig.add_trace(
                go.Scatter(
                    x=x_vals,
                    y=df_slice['market_forecast'].tolist(),
                    name="TOS Market Forecast (Int)",
                    line=dict(color='#B5179E', width=1.0, dash='dot')
                ),
                row=2,
                col=1,
                secondary_y=True
            )
            fig.add_trace(
                go.Scatter(
                    x=x_vals,
                    y=df_slice['stoch_delta_wave'].tolist(),
                    name="Stochastic Slow Delta %K-%D",
                    line=dict(color='#4CC9F0', width=1.0, dash='dot')
                ),
                row=2,
                col=1,
                secondary_y=True
            )
        hist_opex_x, n_opex, f_opex = calculate_opex_coordinates(
            df_slice, timeline_x, current_run_date
        )
        for h_x in hist_opex_x:
            for r in [1, 2]:
                fig.add_vline(
                    x=h_x,
                    line=dict(color="#9B5DE5", width=1.2, dash="dot"),
                    row=r,
                    col=1
                )

        bar_date_lookup = {
            float(bar_x): bar_date.strftime("%Y-%m-%d")
            for bar_x, bar_date in zip(timeline_x, df_slice.index)
        }
        for trace in fig.data:
            if trace.x is None:
                continue
            trace.customdata = [
                bar_date_lookup.get(float(bar_x), "")
                for bar_x in trace.x
            ]
            if trace.type == "candlestick":
                trace.hovertemplate = (
                    "%{x} (%{customdata})<br>"
                    "%{fullData.name}<br>"
                    "Open: %{open}<br>High: %{high}<br>"
                    "Low: %{low}<br>Close: %{close}<extra></extra>"
                )
            else:
                trace.hovertemplate = (
                    "%{x} (%{customdata})<br>"
                    "%{fullData.name}: %{y}<extra></extra>"
                )

        future_opex_x = [
            x_pos for x_pos in hist_opex_x if x_pos > timeline_x[-1]
        ]
        next_opex_x = future_opex_x[0] if future_opex_x else timeline_x[-1]
        reset_opex_x = future_opex_x[1] if len(future_opex_x) > 1 else next_opex_x
        full_x_range = [max(-PLOT_RANGE, timeline_x[0]), float(next_opex_x)]
        reset_x_range = [max(-PLOT_RANGE, timeline_x[0]), float(reset_opex_x)]
        recent_x_range = [
            max(-100, float(timeline_x[0])),
            float(next_opex_x)
        ]
        slider_steps = [{
            "label": "Full Range",
            "method": "relayout",
            "args": [{
                "xaxis.range": full_x_range,
                "xaxis2.range": full_x_range
            }]
        }]
        slider_window = min(100, len(timeline_x))
        next_opex_start_idx = max(0, len(timeline_x) - slider_window)
        slider_steps.append({
            "label": "Next OptExp",
            "method": "relayout",
            "args": [{
                "xaxis.range": [
                    float(timeline_x[next_opex_start_idx]),
                    float(next_opex_x)
                ],
                "xaxis2.range": [
                    float(timeline_x[next_opex_start_idx]),
                    float(next_opex_x)
                ]
            }]
        })
        for window_end_idx in range(len(timeline_x) - 1, slider_window - 2, -1):
            window_start_idx = window_end_idx - slider_window + 1
            window_range = [
                float(timeline_x[window_start_idx]),
                float(timeline_x[window_end_idx])
            ]
            slider_steps.append({
                "label": str(int(timeline_x[window_end_idx])),
                "method": "relayout",
                "args": [{
                    "xaxis.range": window_range,
                    "xaxis2.range": window_range
                }]
            })

        default_annotations = [
            annotation.to_plotly_json()
            for annotation in fig.layout.annotations
        ]
        panel_1_annotations = [{
            "text": "Panel 1: Asset price (raw/norm), VIX, UUP norm",
            "xref": "paper",
            "yref": "paper",
            "x": 0.5,
            "y": 0.985,
            "showarrow": False,
            "font": {"size": 14, "color": "#FFFFFF"}
        }]
        panel_2_annotations = [{
            "text": "Panel 2: Delta norm Asset to norm VIX, UUP, SMA<n>",
            "xref": "paper",
            "yref": "paper",
            "x": 0.5,
            "y": 0.985,
            "showarrow": False,
            "font": {"size": 14, "color": "#FFFFFF"}
        }]

        def _axis_values(trace_obj):
            if trace_obj.type == "candlestick":
                lows = np.asarray(trace_obj.low, dtype=float)
                highs = np.asarray(trace_obj.high, dtype=float)
                return np.concatenate([lows, highs])
            y_vals = getattr(trace_obj, "y", None)
            if y_vals is None:
                return np.array([], dtype=float)
            return np.asarray(y_vals, dtype=float)

        def _padded_range(values, pad_ratio=0.08):
            finite_vals = values[np.isfinite(values)]
            if finite_vals.size == 0:
                return [0.0, 1.0]
            v_min = float(np.min(finite_vals))
            v_max = float(np.max(finite_vals))
            span = max(v_max - v_min, 1e-6)
            pad = span * pad_ratio
            return [v_min - pad, v_max + pad]

        panel_1_primary_vals = []
        panel_1_secondary_vals = []
        for t in fig.data[:panel_1_trace_count]:
            t_axis = t.yaxis or "y"
            t_vals = _axis_values(t)
            if t_vals.size == 0:
                continue
            if t_axis == "y":
                panel_1_primary_vals.append(t_vals)
            elif t_axis == "y2":
                panel_1_secondary_vals.append(t_vals)

        panel_1_primary_range = _padded_range(
            np.concatenate(panel_1_primary_vals) if panel_1_primary_vals else np.array([], dtype=float)
        )
        panel_1_secondary_range = _padded_range(
            np.concatenate(panel_1_secondary_vals) if panel_1_secondary_vals else np.array([], dtype=float)
        )

        panel_2_primary_vals = []
        panel_2_secondary_vals = []
        for t in fig.data[panel_1_trace_count:]:
            t_axis = t.yaxis or "y"
            t_vals = _axis_values(t)
            if t_vals.size == 0:
                continue
            if t_axis == "y3":
                panel_2_primary_vals.append(t_vals)
            elif t_axis == "y4":
                panel_2_secondary_vals.append(t_vals)

        panel_2_primary_range = _padded_range(
            np.concatenate(panel_2_primary_vals) if panel_2_primary_vals else np.array([], dtype=float)
        )
        panel_2_secondary_range = _padded_range(
            np.concatenate(panel_2_secondary_vals) if panel_2_secondary_vals else np.array([], dtype=float)
        )

        total_trace_count = len(fig.data)
        dual_visibility = [True] * total_trace_count
        panel_1_visibility = [
            idx < panel_1_trace_count for idx in range(total_trace_count)
        ]
        panel_2_visibility = [
            idx >= panel_1_trace_count for idx in range(total_trace_count)
        ]
        panel_1_trace_indices = list(range(panel_1_trace_count))
        panel_2_trace_indices = list(range(panel_1_trace_count, total_trace_count))

        dual_domains = {
            "yaxis.domain": [0.42, 1.0],
            "yaxis2.domain": [0.42, 1.0],
            "yaxis3.domain": [0.0, 0.38],
            "yaxis4.domain": [0.0, 0.38],
            "yaxis.visible": True,
            "yaxis2.visible": True,
            "yaxis3.visible": True,
            "yaxis4.visible": True,
            "yaxis.autorange": True,
            "yaxis2.autorange": True,
            "yaxis3.autorange": True,
            "yaxis4.autorange": True,
            "xaxis.visible": True,
            "xaxis2.visible": True,
            "xaxis.matches": "x2",
            "xaxis2.matches": None,
            "xaxis.showticklabels": False,
            "xaxis.anchor": "y",
            "xaxis2.anchor": "y3",
            "annotations": default_annotations
        }
        panel_1_domains = {
            "yaxis.domain": [0.0, 1.0],
            "yaxis2.domain": [0.0, 1.0],
            "yaxis3.domain": [0.0, 0.0],
            "yaxis4.domain": [0.0, 0.0],
            "yaxis.visible": True,
            "yaxis2.visible": True,
            "yaxis3.visible": False,
            "yaxis4.visible": False,
            "yaxis.autorange": False,
            "yaxis2.autorange": False,
            "yaxis.range": panel_1_primary_range,
            "yaxis2.range": panel_1_secondary_range,
            "xaxis.visible": True,
            "xaxis2.visible": False,
            "xaxis.autorange": True,
            "xaxis.matches": None,
            "xaxis.showticklabels": True,
            "xaxis.anchor": "y",
            "annotations": panel_1_annotations
        }
        panel_2_domains = {
            "yaxis.domain": [0.0, 0.0],
            "yaxis2.domain": [0.0, 0.0],
            "yaxis3.domain": [0.0, 1.0],
            "yaxis4.domain": [0.0, 1.0],
            "yaxis.visible": False,
            "yaxis2.visible": False,
            "yaxis3.visible": True,
            "yaxis4.visible": True,
            "yaxis3.autorange": False,
            "yaxis4.autorange": False,
            "yaxis3.range": panel_2_primary_range,
            "yaxis4.range": panel_2_secondary_range,
            "xaxis.visible": False,
            "xaxis2.visible": True,
            "xaxis.matches": None,
            "xaxis2.matches": None,
            "xaxis.anchor": "y3",
            "xaxis2.anchor": "y3",
            "annotations": panel_2_annotations
        }

        # Restore the dark, wide, two-panel dashboard layout.
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#1C1C1E",
            plot_bgcolor="#1C1C1E",
            height=1200,
            width=1600,
            margin=dict(l=100, r=80, t=60, b=50),
            title=dict(
                text=f"📡 QUANT MATRIX TERMINAL: {lbl_sym} ADVANCED PROFILE",
                font=dict(size=16, color="#FFFFFF"),
                x=0.5,
                y=0.992,
                xanchor="center",
                yanchor="top"
            ),
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="top",
                y=1.05,
                xanchor="center",
                x=0.5,
                font=dict(size=10, color="#D1D1D6")
            ),
            yaxis_domain=[0.42, 1.0],
            yaxis2_domain=[0.42, 1.0],
            yaxis3_domain=[0.0, 0.38],
            yaxis4_domain=[0.0, 0.38],
            yaxis=dict(title_text="Norm Asset/VIX/UUP"),
            yaxis2=dict(title_text="Raw Asset price ($)"),
            yaxis3=dict(title_text="Delta Norm Asset to Norm VIX/UUP"),
            yaxis4=dict(title_text="Norm OBV (range)"),
            xaxis=dict(
                type="linear",
                range=reset_x_range,
                rangeslider=dict(visible=False)
            ),
            xaxis2=dict(
                type="linear",
                range=reset_x_range
            ),
            sliders=[
                dict(
                    active=0,
                    currentvalue={"prefix": "Bar window end: "},
                    pad={"t": 28},
                    ticklen=3,
                    tickwidth=1,
                    font={"size": 8},
                    x=0.08,
                    xanchor="left",
                    len=0.84,
                    steps=slider_steps
                )
            ],
            updatemenus=[
                dict(
                    type="buttons",
                    visible=False,
                    direction="right",
                    x=0.005,
                    xanchor="left",
                    y=1.14,
                    yanchor="top",
                    pad={"r": 1, "t": 1, "b": 1, "l": 1},
                    font={"size": 9},
                    buttons=[
                        dict(label="Dual Panel", method="skip"),
                        dict(label="Panel 1", method="skip"),
                        dict(label="Panel 2", method="skip")
                    ]
                ),
                dict(
                    type="buttons",
                    direction="right",
                    x=0.005,
                    xanchor="left",
                    y=1.06,
                    yanchor="top",
                    pad={"r": 1, "t": 1, "b": 1, "l": 1},
                    font={"size": 9},
                    buttons=[
                        dict(
                            label="Zoom In",
                            method="relayout",
                            args=[{
                                "xaxis.range": [
                                    recent_x_range[0], recent_x_range[1]
                                ],
                                "xaxis2.range": [
                                    recent_x_range[0], recent_x_range[1]
                                ]
                            }]
                        ),
                        dict(
                            label="Zoom Out",
                            method="relayout",
                            args=[{
                                "xaxis.range": [
                                    full_x_range[0], full_x_range[1]
                                ],
                                "xaxis2.range": [
                                    full_x_range[0], full_x_range[1]
                                ]
                            }]
                        ),
                        dict(
                            label="Reset X",
                            method="relayout",
                            args=[{
                                "xaxis.range": reset_x_range,
                                "xaxis2.range": reset_x_range
                            }]
                        )
                    ]
                )
            ],
            hovermode="x unified",
            font=dict(color="#FFFFFF")
        )

        # Add synchronized crosshair segments to both panels.
        fig.add_shape(
            type="line",
            x0=0, x1=0, y0=0, y1=1,
            xref="x", yref="y domain",
            line=dict(
                color="rgba(255,255,255,0.35)",
                width=1.0,
                dash="dot"
            ),
            opacity=0
        )
        fig.add_shape(
            type="line",
            x0=0, x1=0, y0=0, y1=1,
            xref="x", yref="y3 domain",
            line=dict(
                color="rgba(255,255,255,0.35)",
                width=1.0,
                dash="dot"
            ),
            opacity=0
        )

        shape_1 = len(fig.layout.shapes) - 2
        shape_2 = len(fig.layout.shapes) - 1

        def _to_json_native(obj):
            if isinstance(obj, np.generic):
                return obj.item()
            if isinstance(obj, dict):
                return {k: _to_json_native(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_to_json_native(v) for v in obj]
            return obj

        dual_domains_js = json.dumps(_to_json_native(dual_domains))
        panel_1_domains_js = json.dumps(_to_json_native(panel_1_domains))
        panel_2_domains_js = json.dumps(_to_json_native(panel_2_domains))
        dual_visibility_js = json.dumps(_to_json_native(dual_visibility))
        panel_1_visibility_js = json.dumps(_to_json_native(panel_1_visibility))
        panel_2_visibility_js = json.dumps(_to_json_native(panel_2_visibility))
        panel_1_trace_indices_js = json.dumps(_to_json_native(panel_1_trace_indices))
        panel_2_trace_indices_js = json.dumps(_to_json_native(panel_2_trace_indices))

        post_script = f"""
        const gd = document.getElementById('{{plot_id}}');
        const dualLayout = {dual_domains_js};
        const panel1Layout = {panel_1_domains_js};
        const panel2Layout = {panel_2_domains_js};
        const dualVisible = {dual_visibility_js};
        const panel1Visible = {panel_1_visibility_js};
        const panel2Visible = {panel_2_visibility_js};
        const panel1Indices = {panel_1_trace_indices_js};
        const panel2Indices = {panel_2_trace_indices_js};

        function buildModeStatus() {{
            const parent = gd.parentElement || document.body;
            let badge = parent.querySelector('.qt-mode-status');
            if (!badge) {{
                badge = document.createElement('div');
                badge.className = 'qt-mode-status';
                badge.style.position = 'absolute';
                badge.style.right = '12px';
                badge.style.top = '10px';
                badge.style.zIndex = '50';
                badge.style.padding = '4px 8px';
                badge.style.fontSize = '11px';
                badge.style.fontFamily = 'monospace';
                badge.style.background = 'rgba(28,28,30,0.8)';
                badge.style.color = '#D1D1D6';
                badge.style.border = '1px solid rgba(255,255,255,0.2)';
                badge.style.borderRadius = '4px';
                badge.style.pointerEvents = 'none';
                parent.style.position = 'relative';
                parent.appendChild(badge);
            }}
            return badge;
        }}

        function updateModeStatus(label) {{
            if (!gd || !gd.data) return;
            const badge = buildModeStatus();
            const traces = gd.data.map((t, i) => {{
                const visible = (t.visible === undefined) ? true : t.visible;
                return {{ i, yaxis: t.yaxis || 'y', visible }};
            }});
            const top = traces.filter(t => t.visible !== false && (t.yaxis === 'y' || t.yaxis === 'y2')).length;
            const bottom = traces.filter(t => t.visible !== false && (t.yaxis === 'y3' || t.yaxis === 'y4')).length;
            badge.textContent = `mode=${{label}} top=${{top}} bottom=${{bottom}}`;
        }}

        function applyMode(mode) {{
            let layoutUpdate = dualLayout;
            let visibleIndices = panel1Indices.concat(panel2Indices);
            let hiddenIndices = [];

            if (mode === 'panel1') {{
                visibleIndices = panel1Indices;
                hiddenIndices = panel2Indices;
                layoutUpdate = panel1Layout;
            }} else if (mode === 'panel2') {{
                visibleIndices = panel2Indices;
                hiddenIndices = panel1Indices;
                layoutUpdate = panel2Layout;
            }}

            const showActive = Plotly.restyle(gd, {{ visible: true }}, visibleIndices);
            const hideInactive = hiddenIndices.length
                ? showActive.then(() => Plotly.restyle(gd, {{ visible: false }}, hiddenIndices))
                : showActive;
            return hideInactive
                .then(() => Plotly.relayout(gd, layoutUpdate))
                .then(() => Plotly.Plots.resize(gd))
                .then(() => Plotly.redraw(gd));
        }}

        gd.on('plotly_hover', function(eventData) {{
            if (!eventData.points || !eventData.points.length) return;

            const x = eventData.points[0].x;
            const barDate = eventData.points[0].customdata;
            const update = {{}};

            for (const i of [{shape_1}, {shape_2}]) {{
                update[`shapes[${{i}}].x0`] = x;
                update[`shapes[${{i}}].x1`] = x;
                update[`shapes[${{i}}].opacity`] = 1;
            }}

            Plotly.relayout(gd, update);

            if (barDate) {{
                setTimeout(() => {{
                    gd.querySelectorAll('.axistext').forEach((axisLabel) => {{
                        if (axisLabel.textContent.trim() === String(x)) {{
                            axisLabel.textContent = `${{x}} (${{barDate}})`;
                        }}
                    }});
                }}, 0);
            }}
        }});

        gd.on('plotly_unhover', function() {{
            Plotly.relayout(gd, {{
                'shapes[{shape_1}].opacity': 0,
                'shapes[{shape_2}].opacity': 0
            }});
        }});

        gd.on('plotly_buttonclicked', function(eventData) {{
            const label = eventData && eventData.button ? eventData.button.label : '';
            if (label === 'Dual Panel') {{
                applyMode('dual');
            }} else if (label === 'Panel 1') {{
                applyMode('panel1');
            }} else if (label === 'Panel 2') {{
                applyMode('panel2');
            }}
            setTimeout(() => updateModeStatus(label || 'click'), 120);
        }});

        setTimeout(() => updateModeStatus('initial'), 120);

        """

        dt_file_lbl = (
            current_run_date.strftime("%Y-%m-%d")
            if hasattr(current_run_date, "strftime")
            else str(current_run_date).split(" ")[0]
        )
        ts_suffix = datetime.now().strftime("%H%M%S")
        out_name = f"{dt_file_lbl}_{lbl_sym}_BAROMETER_{ts_suffix}.html"

        output_chart_path = os.path.join(CHARTS_DIR, out_name)

        def build_focus_figure(
            trace_start,
            trace_end,
            title,
            axis_map,
            primary_range,
            secondary_range,
            secondary_trace_names=None
        ):
            secondary_trace_names = set(secondary_trace_names or ())
            focus_traces = []
            for source_trace in fig.data[trace_start:trace_end]:
                trace_json = source_trace.to_plotly_json()
                trace_json["xaxis"] = "x"
                trace_json["yaxis"] = (
                    "y2"
                    if trace_json.get("name") in secondary_trace_names
                    else axis_map.get(trace_json.get("yaxis", "y"), "y")
                )
                focus_traces.append(trace_json)

            focus_fig = go.Figure(data=focus_traces)
            focus_fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="#1C1C1E",
                plot_bgcolor="#1C1C1E",
                height=1200,
                width=1600,
                margin=dict(l=100, r=80, t=105, b=50),
                title=dict(
                    text=title,
                    font=dict(size=16, color="#FFFFFF"),
                    x=0.5,
                    y=0.99,
                    xanchor="center",
                    yanchor="top"
                ),
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="top",
                    y=1.05,
                    xanchor="center",
                    x=0.5
                ),
                hovermode="x unified",
                xaxis=dict(
                    type="linear",
                    range=reset_x_range,
                    title_text="Bars",
                    rangeslider=dict(visible=False)
                ),
                yaxis=dict(
                    title_text=(
                        "Norm Asset/VIX/UUP"
                        if "Panel 1" in title
                        else "Delta Norm Asset to Norm VIX/UUP"
                    ),
                    range=primary_range,
                    autorange=False,
                    side="left",
                    anchor="x"
                ),
                yaxis2=dict(
                    title_text=(
                        "Raw Asset price ($)"
                        if "Panel 1" in title
                        else "Norm OBV (range)"
                    ),
                    range=secondary_range,
                    autorange=False,
                    overlaying="y",
                    side="right",
                    anchor="x",
                    showgrid=False
                ),
                font=dict(color="#FFFFFF")
            )
            for h_x in hist_opex_x:
                focus_fig.add_vline(
                    x=h_x,
                    line=dict(color="#9B5DE5", width=1.2, dash="dot")
                )
            return focus_fig

        panel_1_fig = build_focus_figure(
            0,
            panel_1_trace_count,
            f"QUANT MATRIX TERMINAL: {lbl_sym} - Panel 1",
            {"y": "y", "y2": "y2"},
            panel_1_primary_range,
            panel_1_secondary_range,
            {f"Raw {lbl_sym} Price"}
        )
        panel_2_fig = build_focus_figure(
            panel_1_trace_count,
            len(fig.data),
            f"QUANT MATRIX TERMINAL: {lbl_sym} - Panel 2",
            {"y3": "y", "y4": "y2"},
            panel_2_primary_range,
            panel_2_secondary_range
        )

        debug_path = f"{output_chart_path}.panel1-debug.json"
        with open(debug_path, "w", encoding="utf-8") as debug_file:
            json.dump({
                "symbol": lbl_sym,
                "rows": int(len(df_slice)),
                "timeline_length": int(len(timeline_x)),
                "panel_1_trace_count": int(panel_1_trace_count),
                "traces": panel_1_debug,
            }, debug_file, indent=2)

            dual_html = pio.to_html(
                fig,
                full_html=False,
                include_plotlyjs="inline",
                post_script=post_script
            )
            panel_1_html = pio.to_html(panel_1_fig, full_html=False, include_plotlyjs=False)
            panel_2_html = pio.to_html(panel_2_fig, full_html=False, include_plotlyjs=False)
            tabbed_html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>QUANT MATRIX TERMINAL: {lbl_sym}</title>
<style>
body {{ margin: 0; background: #1C1C1E; color: #FFFFFF; font-family: monospace; }}
.qt-tabs {{ display: flex; gap: 4px; padding: 8px; background: #111113; position: sticky; top: 0; z-index: 20; }}
.qt-tab {{ border: 1px solid #555; background: #303038; color: #FFF; padding: 8px 14px; cursor: pointer; }}
.qt-tab.active {{ background: #4D6A8A; }}
.qt-view {{ display: none; }}
.qt-view.active {{ display: block; }}
</style></head>
<body>
<nav class="qt-tabs" aria-label="Chart views">
    <button class="qt-tab active" data-view="dual">Dual Panel</button>
    <button class="qt-tab" data-view="panel1">Panel 1</button>
    <button class="qt-tab" data-view="panel2">Panel 2</button>
</nav>
<main>
    <section id="dual" class="qt-view active">{dual_html}</section>
    <section id="panel1" class="qt-view">{panel_1_html}</section>
    <section id="panel2" class="qt-view">{panel_2_html}</section>
</main>
<script>
document.querySelectorAll('.qt-tab').forEach((tab) => tab.addEventListener('click', () => {{
    document.querySelectorAll('.qt-tab').forEach((item) => item.classList.toggle('active', item === tab));
    document.querySelectorAll('.qt-view').forEach((view) => view.classList.toggle('active', view.id === tab.dataset.view));
    const plot = document.querySelector(`#${{tab.dataset.view}} .js-plotly-plot`);
    if (plot && window.Plotly) window.Plotly.Plots.resize(plot);
}}));
</script>
</body></html>"""
        with open(output_chart_path, "w", encoding="utf-8") as chart_file:
            chart_file.write(tabbed_html)
        print(f"   ✨ Unified Portrait Canvas Compiled Successfully -> {out_name}")
        print(f"      📂 Chart path: {output_chart_path}")
        print(f"      🔎 Panel 1 diagnostics: {debug_path}")
        consensus_positions.append(float(df_slice['spring'].iloc[-1]))
    except Exception as e:
        print(f"   ⚠️ Visual Engine Exception for {lbl_sym}: {e}")
        traceback.print_exc()

"""
QUANT TERMINAL - Step 5: Real-Time Multi-Regime Macro Barometer Dashboard
Block 5 of 6: Central Pipeline Orchestration and Broad Anchor Data Harvesters.
"""

def run_macro_barometer_pipeline():
    print("========================================================")
    print("🌍 RUNNING CORE MACRO BAROMETER PIPELINE ENGINE")
    print(f"📡 Math Normalization Window:    {NORM_WINDOW} Bars")
    print(f"📊 Display View Range Horizon:   {PLOT_RANGE} Bars")
    print(f"⚖️ Mathematical Backtest Shift:  {SHIFT_BARS} Bars Back")
    print(f"📏 Scale Constraints Injected:  Min={SCALE_MIN} | Max={SCALE_MAX}")
    print("========================================================\n")
    
    current_run_date = datetime.now().strftime("%Y-%m-%d")
    index_symbols, alpha_singles = parse_telemetry_config()
    
    print("📡 Ingesting Risk Anchors (^VIX, UUP) from yfinance...")
    vix_df = yf.download('^VIX', period="6y", auto_adjust=False, progress=False)
    uup_df = yf.download('UUP', period="6y", auto_adjust=False, progress=False)
    
    ser_vix = vix_df['Close'].iloc[:, 0] if isinstance(vix_df['Close'], pd.DataFrame) else vix_df['Close']
    ser_uup = uup_df['Close'].iloc[:, 0] if isinstance(uup_df['Close'], pd.DataFrame) else uup_df['Close']
    
    anchors = pd.DataFrame(index=vix_df.index)
    anchors['VIX_Close'] = ser_vix
    anchors['UUP_Close'] = ser_uup
    anchors.index = anchors.index.tz_localize(None)
    anchors = anchors.ffill().bfill().dropna()
    
    anchors['norm_VIX'] = min_max_normalize_shifted_series(NORM_WINDOW, SHIFT_BARS, anchors['VIX_Close'])
    anchors['norm_UUP'] = min_max_normalize_shifted_series(NORM_WINDOW, SHIFT_BARS, anchors['UUP_Close'])
    
    consensus_positions = []
    
    print("📈 Executing Engine 1: Unified Macro Index Core Parsing...")
    if index_symbols:
        for sym in index_symbols:
            generate_unified_two_pane_chart(sym, anchors, consensus_positions, current_run_date)
        
    print("\n🔬 Executing Engine 2: Alpha Tracking Stock Single Slices...")
    if alpha_singles:
        for sym in alpha_singles:
            generate_unified_two_pane_chart(sym, anchors, consensus_positions, current_run_date)
    """
    QUANT TERMINAL - Step 5: Real-Time Multi-Regime Macro Barometer Dashboard
    Block 6 of 6: Symmetrical Ledger Exporter with Precision Timeline Bar String Logs.
    🎯 DATA INSULATION BLOCK: Protects current_run_date from object mutations inside loop.
    """
    print("\n⚖️ Computing Portfolio Risk Allocation Consensus Models...")
    core_equity_anchors = ('SPY', 'QQQ', 'DIA', 'IWM')
    ledger_rows = []
    breadth_tension_pool = []
    
    obv4_periods = {90: "P4", 180: "P3", 270: "P2", 360: "P1"}
    
    # 🎯 SHIELD PASS: Capture immutable baseline text token to immunize lookups
    static_dt_str = datetime.now().strftime("%Y-%m-%d")
    
    for tick in core_equity_anchors:
        try:
            raw_px = yf.download(tick, period="6y", auto_adjust=False, progress=False)
            close_ser = raw_px['Close'].iloc[:, 0] if isinstance(raw_px['Close'], pd.DataFrame) else raw_px['Close']
            vol_ser = raw_px['Volume'].iloc[:, 0] if isinstance(raw_px['Volume'], pd.DataFrame) else raw_px['Volume']
            
            df_m = pd.DataFrame(index=anchors.index)
            df_m['Close'] = close_ser
            df_m['Volume'] = vol_ser
            df_m.index = df_m.index.tz_localize(None)
            df_m = df_m.join(anchors, how='inner').dropna()
            
            df_m['raw_obv'] = np.zeros(len(df_m))
            current_obv = 0.0
            for i in range(1, len(df_m)):
                if df_m['Close'].iloc[i] > df_m['Close'].iloc[i-1]:
                    current_obv += float(df_m['Volume'].iloc[i])
                elif df_m['Close'].iloc[i] < df_m['Close'].iloc[i-1]:
                    current_obv -= float(df_m['Volume'].iloc[i])
                df_m.loc[df_m.index[i], 'raw_obv'] = current_obv
                
            df_m['norm_A'] = min_max_normalize_shifted_series(NORM_WINDOW, SHIFT_BARS, df_m['Close'])
            df_m['sma_r'] = df_m['Close'].rolling(window=NORM_WINDOW, min_periods=1).mean()
            df_m['norm_s'] = min_max_normalize_shifted_series(NORM_WINDOW, SHIFT_BARS, df_m['sma_r'])
            df_m['vs_vx'] = df_m['norm_A'] - df_m['norm_VIX']
            df_m['vs_uup'] = df_m['norm_A'] - df_m['norm_UUP']
            df_m['spring'] = df_m['Close'] - df_m['sma_r']
            
            end_idx = len(df_m) - SHIFT_BARS
            start_idx = max(0, end_idx - PLOT_RANGE)
            
            obv4_triggered_labels = []
            obv4_triggered_bars = []
            obv50_triggered_labels = []
            obv50_triggered_bars = []
            
            for bar_offset in range(0, 6):
                target_idx = end_idx - 1 - bar_offset
                if target_idx < 360: continue
                bar_str = f"-{SHIFT_BARS + bar_offset}" if SHIFT_BARS > 0 or bar_offset > 0 else "0"
                
                for length, label in obv4_periods.items():
                    lookback_chunk = df_m['raw_obv'].iloc[target_idx - length : target_idx + 1]
                    if df_m['raw_obv'].iloc[target_idx] == lookback_chunk.max() or df_m['raw_obv'].iloc[target_idx] == lookback_chunk.min():
                        if label not in obv4_triggered_labels: obv4_triggered_labels.append(label)
                        if bar_str not in obv4_triggered_bars: obv4_triggered_bars.append(bar_str)
                            
                p5_lookback = df_m['raw_obv'].iloc[target_idx - 50 : target_idx + 1]
                if df_m['raw_obv'].iloc[target_idx] == p5_lookback.max() or df_m['raw_obv'].iloc[target_idx] == p5_lookback.min():
                    if "P5" not in obv50_triggered_labels: obv50_triggered_labels.append("P5")
                    if bar_str not in obv50_triggered_bars: obv50_triggered_bars.append(bar_str)
            
            row_metrics = {
                "Symbol": tick, "Sub_Weighting": 1.0, "cross_pct": 1.0,
                "obv4_Score": len(obv4_triggered_labels),
                "obv4_Trigger_Periods": "|".join(obv4_triggered_labels) if obv4_triggered_labels else "None",
                "obv4_Trigger_Bars": "|".join(obv4_triggered_bars) if obv4_triggered_bars else "None",
                "obv50_Score": 1 if obv50_triggered_labels else 0,
                "obv50_Trigger_Periods": "50" if obv50_triggered_labels else "None",
                "obv50_Trigger_Bars": "|".join(obv50_triggered_bars) if obv50_triggered_bars else "None"
            }
            
            for col, key in [('vs_vx', 'vix'), ('vs_uup', 'uup'), ('spring', 'sma')]:
                curr_val = df_m[col].iloc[end_idx - 1]
                hist = df_m[col].iloc[start_idx:end_idx]
                h_min = float(hist.min()); h_max = float(hist.max())
                ceil_M = max(abs(h_max), abs(h_min)); denom = ceil_M if ceil_M != 0 else 1.0
                pct_pos = (curr_val / denom) * 100.0
                
                row_metrics[f"{key}_M"] = round(ceil_M, 4)
                row_metrics[f"{key}_min"] = round(h_min, 4)
                row_metrics[f"{key}_max"] = round(h_max, 4)
                row_metrics[f"{key}_pct"] = round(pct_pos, 2)
                breadth_tension_pool.append(pct_pos)
                
            ledger_rows.append(row_metrics)
        except Exception as e:
            print(f"   ⚠️ Exporter Extraction Exception for {tick}: {e}")

    if ledger_rows:
        ledger_df = pd.DataFrame(ledger_rows)
        avg_vix_pct = round(np.mean(ledger_df['vix_pct']), 2)
        avg_uup_pct = round(np.mean(ledger_df['uup_pct']), 2)
        avg_sma_pct = round(np.mean(ledger_df['sma_pct']), 2)
        avg_global_cross = round(np.mean([avg_vix_pct, avg_uup_pct, avg_sma_pct]), 2)
        
        row_5 = {
            "Symbol": "UNIFIED_MACRO_CONSENSUS", "Sub_Weighting": "---", "cross_pct": avg_global_cross,
            "obv4_Score": "---", "obv4_Trigger_Periods": "---", "obv4_Trigger_Bars": "---",
            "obv50_Score": "---", "obv50_Trigger_Periods": "---", "obv50_Trigger_Bars": "---",
            "vix_M": "---", "vix_min": "---", "vix_max": "---", "vix_pct": avg_vix_pct,
            "uup_M": "---", "uup_min": "---", "uup_max": "---", "uup_pct": avg_uup_pct,
            "sma_M": "---", "sma_min": "---", "sma_max": "---", "sma_pct": avg_sma_pct
        }
        ledger_df = pd.concat([ledger_df, pd.DataFrame([row_5])], ignore_index=True)
        
        ordered_cols = [
            "Symbol", "Sub_Weighting", "cross_pct", 
            "obv4_Score", "obv4_Trigger_Periods", "obv4_Trigger_Bars",
            "obv50_Score", "obv50_Trigger_Periods", "obv50_Trigger_Bars",
            "vix_M", "vix_min", "vix_max", "vix_pct", 
            "uup_M", "uup_min", "uup_max", "uup_pct", 
            "sma_M", "sma_min", "sma_max", "sma_pct"
        ]
        ledger_df = ledger_df[[c for c in ordered_cols if c in ledger_df.columns]]
        
        ledger_path = os.path.join(MACRO_DIR, "macro_tension_ledger.csv")
        ledger_df.to_csv(ledger_path, index=False)
        
        mean_tension_pct = np.nanmean(breadth_tension_pool)
        consensus_level = int(round((-mean_tension_pct) / 20.0))
        consensus_level = max(-5, min(5, consensus_level))
        long_multiplier = round(max(0.00, min(5.00, 2.50 - (mean_tension_pct / 40.0))), 2)
        short_multiplier = round(max(0.00, min(5.00, 2.50 + (mean_tension_pct / 40.0))), 2)
        
        if mean_tension_pct >= 60.0: final_regime = "STRATEGIC OVERVALUATION PEAK (PLAY DEFENSE)"
        elif mean_tension_pct >= 20.0: final_regime = "UPWARD STRETCH WAVE (TRIM SIZING)"
        elif mean_tension_pct >= -20.0: final_regime = "BALANCED EQUILIBRIUM COOLDOWN"
        elif mean_tension_pct >= -60.0: final_regime = "CYCLIC CAPITULATION EXHAUSTION (SCALE UP)"
        else: final_regime = "EXTREME SELLING EXHAUSTION FLOOR (MAX DEPLOYMENT)"
        
        output_data = {
            "Barometer_Level": [consensus_level], "Regime": [f"{final_regime} ({mean_tension_pct:0.1f}%)"],
            "Long_Multiplier": [long_multiplier], "Short_Multiplier": [short_multiplier],
            "Normalization_Lookback": [NORM_WINDOW], "Backtest_Shift_Bars": [SHIFT_BARS], "Effective_Run_Date": [static_dt_str]
        }
        gauge_path = os.path.join(MACRO_DIR, "market_pressure_gauge.csv")
        pd.DataFrame(output_data).to_csv(gauge_path, index=False)
        
        print("\n" + "-" * 75)
        print(f"🏆 Unified Macro Consensus Position (As of {static_dt_str}): {mean_tension_pct:+.1f}%")
        print(f"📡 Portfolio Defensive Level Stance: {consensus_level:+} | {final_regime}")
        print(f"📊 Anti-Cyclical Capital Multiplier (long/cover):  {long_multiplier}x")
        print(f"📉 Anti-Cyclical Capital Multiplier (short/close): {short_multiplier}x")
        print(f"📊 Metric Ledgers Exported to Folder: {os.path.basename(MACRO_DIR)}")
        print("-" * 75 + "\n")
        
    print("🏆 Master Macro Barometer execution cycle finalized successfully.")

if __name__ == "__main__":
    run_macro_barometer_pipeline()

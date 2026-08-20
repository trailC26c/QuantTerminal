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
import traceback
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Silence yfinance terminal internal data warnings
import logging
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

# =========================================================================
# 🎛️ COMMAND LINE INTERFACE (CLI) ARGUMENT EXTENSION PARSER
# =========================================================================
parser = argparse.ArgumentParser(description="QUANT TERMINAL: Macro Engine")
parser.add_argument("--window", type=int, default=200, help="Normalization lookback window (default: 200)")
parser.add_argument(
    "--shift",
    type=int,
    default=0,
    help="Mathematical backtest shift; positive or negative N evaluates N bars back (default: 0)"
)
parser.add_argument("--range", type=int, default=300, help="Visual plot horizon range in bars (default: 300)")
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

args, unknown = parser.parse_known_args()

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

# =========================================================================
# 📂 DIRECTORY STRUCTURE & ROUTING SPECIFICATIONS
# =========================================================================
BASE_DIR = r"C:\Users\tcnet\TOS_Data_Local"
WATCHLIST_DIR = os.path.join(BASE_DIR, "sanitized_watchlists")
MACRO_DIR = os.path.join(BASE_DIR, "macro_barometer")
CHARTS_DIR = os.path.join(MACRO_DIR, "charts")

os.makedirs(MACRO_DIR, exist_ok=True)
os.makedirs(CHARTS_DIR, exist_ok=True)

SPRING_OFFSET = 0.0

def parse_telemetry_config():
    """Reads telemetry_list.txt configuration and handles multi-line vertical columns."""
    config_path = os.path.join(MACRO_DIR, "telemetry_list.txt")
    index_symbols = []
    alpha_singles = []
    current_section = None

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

    return results

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
        px_raw = yf.download(tick_lookup, period="6y", progress=False)
        close_ser = px_raw['Close'].iloc[:, 0] if isinstance(px_raw['Close'], pd.DataFrame) else px_raw['Close']
        vol_ser = px_raw['Volume'].iloc[:, 0] if isinstance(px_raw['Volume'], pd.DataFrame) else px_raw['Volume']
        high_ser = px_raw['High'].iloc[:, 0] if isinstance(px_raw['High'], pd.DataFrame) else px_raw['High']
        low_ser = px_raw['Low'].iloc[:, 0] if isinstance(px_raw['Low'], pd.DataFrame) else px_raw['Low']
        
        df_p = pd.DataFrame(index=close_ser.index)
        df_p['Close'] = close_ser
        df_p['Volume'] = vol_ser
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
            specs=[[{"secondary_y": True}], [{"secondary_y": True}]],
            subplot_titles=(f"PANEL 1: CORE RECONCILED PROFILE ({lbl_sym})", f"PANEL 2: HOOKE'S LAW RISK MATRIX FACTOR OVERLAYS FOR {lbl_sym}")
        )
        
        # Panel 1 Traces
        fig.add_trace(
            go.Scatter(
                x=timeline_x,
                y=df_slice['norm_A'],
                name=f"norm_{lbl_sym}",
                line=dict(color='#00F0FF', width=2.5)
            ),
            row=1,
            col=1,
            secondary_y=False
        )
        fig.add_trace(go.Scatter(x=timeline_x, y=df_slice['norm_VIX'], name='norm_VIX', line=dict(color='#FF3B30', width=1.5, dash='dot')), row=1, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=timeline_x, y=df_slice['norm_UUP'], name='norm_UUP', line=dict(color='#34C759', width=1.5, dash='dot')), row=1, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=timeline_x, y=df_slice['Close'], name=f"Raw {lbl_sym} Price", line=dict(color='#63E6BE', width=1.0)), row=1, col=1, secondary_y=True)
        
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
        
        # Panel 2 Traces
        fig.add_trace(go.Scatter(x=timeline_x, y=df_slice['vs_vx'], name=f'vs VIX Delta', line=dict(color='#FF9500', width=2.2)), row=2, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=timeline_x, y=df_slice['vs_uup'], name=f'vs UUP Delta', line=dict(color='#AF52DE', width=2.2)), row=2, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=timeline_x, y=df_slice['spring'], name=f'vs SMA Delta (spring ext.)', line=dict(color='#00FF66', width=2.5)), row=2, col=1, secondary_y=False)
        fig.add_trace(
            go.Scatter(
                x=timeline_x,
                y=df_slice['norm_OBV_wave'],
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
                    x=timeline_x,
                    y=df_slice['market_forecast'],
                    name="TOS Market Forecast (Int)",
                    line=dict(color='#B5179E', width=1.0, dash='dot')
                ),
                row=2,
                col=1,
                secondary_y=True
            )
            fig.add_trace(
                go.Scatter(
                    x=timeline_x,
                    y=df_slice['stoch_delta_wave'],
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

        # Restore the dark, wide, two-panel dashboard layout.
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#1C1C1E",
            plot_bgcolor="#1C1C1E",
            height=1200,
            width=1100,
            margin=dict(l=100, r=80, t=110, b=50),
            title=dict(
                text=f"📡 QUANT MATRIX TERMINAL: {lbl_sym} ADVANCED PROFILE",
                font=dict(size=16, color="#FFFFFF"),
                x=0.5,
                y=0.995,
                xanchor="center",
                yanchor="top"
            ),
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="top",
                y=1.08,
                xanchor="center",
                x=0.5,
                font=dict(size=10, color="#D1D1D6")
            ),
            yaxis=dict(title_text="Norm Asset/VIX/UUP"),
            yaxis2=dict(title_text="Raw Asset price ($)"),
            yaxis3=dict(title_text="Delta Norm Asset to Norm VIX/UUP"),
            yaxis4=dict(title_text="Norm OBV (range)"),
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

        post_script = f"""
        const gd = document.getElementById('{{plot_id}}');

        gd.on('plotly_hover', function(eventData) {{
            if (!eventData.points || !eventData.points.length) return;

            const x = eventData.points[0].x;
            const update = {{}};

            for (const i of [{shape_1}, {shape_2}]) {{
                update[`shapes[${{i}}].x0`] = x;
                update[`shapes[${{i}}].x1`] = x;
                update[`shapes[${{i}}].opacity`] = 1;
            }}

            Plotly.relayout(gd, update);
        }});

        gd.on('plotly_unhover', function() {{
            Plotly.relayout(gd, {{
                'shapes[{shape_1}].opacity': 0,
                'shapes[{shape_2}].opacity': 0
            }});
        }});
        """

        dt_file_lbl = (
            current_run_date.strftime("%Y-%m-%d")
            if hasattr(current_run_date, "strftime")
            else str(current_run_date).split(" ")[0]
        )
        out_name = f"{dt_file_lbl}_{lbl_sym}_BAROMETER.html"

        fig.write_html(
            os.path.join(CHARTS_DIR, out_name),
            include_plotlyjs="inline",
            post_script=post_script
        )
        print(f"   ✨ Unified Portrait Canvas Compiled Successfully -> {out_name}")
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
    vix_df = yf.download('^VIX', period="6y", progress=False)
    uup_df = yf.download('UUP', period="6y", progress=False)
    
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
            raw_px = yf.download(tick, period="6y", progress=False)
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

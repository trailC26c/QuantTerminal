"""
QUANT TERMINAL - Step 2: Integrated Multi-Regime SEPA Filter Matrix (Part 1/3)
Configures pathing architectures, cross-asset dictionaries, and date context tracking.
"""

import os
import re
import glob
import logging
import argparse
import random
from datetime import datetime
import pandas as pd
from pathlib import Path
import yfinance as yf
from local_data_store import LocalDataStore

# Silence yfinance terminal internal warnings
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

# Path Declarations: Aligned cleanly with your step 1 output folders
BASE_DIR = Path(r"C:\Users\tcnet\TOS_Data_Local")
PROJECT_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_DIR / "data" / "sanitized_watchlists"
OUTPUT_DIR = BASE_DIR / "sepa_matrix"
DATABASE_PATH = PROJECT_DIR / "data" / "quant_terminal.db"
SEPA_RESULTS_DIR = PROJECT_DIR / "output" / "sepa_results"

# Ensure target directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SEPA_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Broad Asset Translation Dictionary
MACRO_MAP = {
    "/ES": "ES=F", "/NQ": "NQ=F", "/YM": "YM=F", 
    "/VX": "^VIX", "VX": "^VIX", "VIX": "^VIX", "VVIX": "^VVIX"
}


def yahoo_history_ticker(symbol: str) -> str:
    """Translate TOS futures, index aliases, and bracketed contracts for Yahoo."""
    clean = str(symbol).strip().upper()
    if clean in {"SPX", "^SPX"}:
        return "^SPX"
    if clean in {"VIX", "^VIX", "VX", "/VX"}:
        return "^VIX"
    if clean in {"VVIX", "^VVIX", "/VVIX"}:
        return "^VVIX"
    if clean.startswith("/"):
        root_match = re.match(
            r"^/(?P<root>[A-Z0-9]{1,4})(?:[FGHJKMNQUVXZ]\d{2}|\[[A-Z]\d{2}\])$",
            clean,
        )
        if root_match is None:
            root_match = re.match(r"^/(?P<root>[A-Z0-9]{1,4})", clean)
        if root_match:
            root = root_match.group("root")
            if root == "VX":
                return "^VIX"
            if root == "VVIX":
                return "^VVIX"
            return f"{root}=F"
    return MACRO_MAP.get(clean, clean)


def get_latest_date_from_files() -> str:
    """Return the newest native TOS session date, or generic date if native is absent."""
    native_dates = []
    all_dates = []
    for path in glob.glob(os.path.join(INPUT_DIR, "*_SANITIZED.csv")):
        name = os.path.basename(path)
        match = re.search(r"(\d{4}-\d{2}-\d{2})", name)
        if not match:
            continue
        date_value = match.group(1)
        all_dates.append(date_value)
        if "watchlist-generic" not in name.lower() and "watchlist_generic" not in name.lower():
            native_dates.append(date_value)

    if not all_dates:
        raise FileNotFoundError(f"❌ No valid dated files found in processed directory: {INPUT_DIR}")

    latest_date = max(native_dates or all_dates)
    print(f"📅 Auto-Detected Processed Target Date Context: {latest_date}")
    return latest_date


def get_analysis_source_files(requested_key: str | None) -> list[Path]:
    """Select latest native files plus the latest generic file for combined analysis."""
    candidates = []
    for path in Path(INPUT_DIR).glob("*.csv"):
        if "-options" in path.name.lower():
            continue
        match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
        if not match:
            continue
        key_match = re.search(r"watchlist[-_]([A-Za-z0-9][A-Za-z0-9_+\-]*?)_SANITIZED\.csv$", path.name, re.IGNORECASE)
        if key_match:
            candidates.append((path, match.group(1), key_match.group(1).lower()))
    if not candidates:
        return []
    if requested_key and requested_key != "all":
        dates = [date for _, date, key in candidates if key == requested_key]
        if not dates:
            return []
        target_date = max(dates)
        return [path for path, date, key in candidates if date == target_date and key == requested_key]
    native_dates = [date for _, date, key in candidates if key != "generic"]
    native_date = max(native_dates) if native_dates else None
    generic_dates = [date for _, date, key in candidates if key == "generic"]
    generic_date = max(generic_dates) if generic_dates else None
    return [
        path for path, date, key in candidates
        if (key != "generic" and date == native_date) or (key == "generic" and date == generic_date)
    ]


def history_to_store_bars(history: pd.DataFrame) -> list[tuple]:
    """Convert a yfinance history frame into the local bar-store tuple format."""
    if history.empty or "Close" not in history.columns:
        return []
    bars = []
    for index, row in history.dropna(subset=["Close"]).iterrows():
        def value(column: str):
            raw = row.get(column)
            return None if pd.isna(raw) else float(raw)
        bars.append((
            pd.Timestamp(index).date().isoformat(),
            value("Open"), value("High"), value("Low"), value("Close"),
            value("Adj Close"), value("Volume"),
        ))
    return bars
"""
QUANT TERMINAL - Step 2: Integrated Multi-Regime SEPA Filter Matrix (Part 2/3)
Runs multi-regime evaluation routines across fixed income, indicators, IPOs, and equities.
Upgraded to explicitly map and isolate Stage 1 Accumulation and Stage 3 Distribution phases.
"""

def evaluate_asset_trend(ticker_str: str, df_hist: pd.DataFrame) -> dict:
    """Evaluates trend rules over historical data to map a stock into Stage 1, 2, 3, or 4 lifecycle regimes."""
    default_metrics = {
        "Type": "UNKNOWN", "Strict_SEPA": False, "Cyclic_Turnaround": False, 
        "Stage1_Base": False, "Stage3_Dist": False, "Stage4_Short": False, 
        "Fail_Reason": "No_Data", "Pass_Reason": "None", "Trend_Score": 0.0
    }
    
    if df_hist.empty or len(df_hist) < 5:
        return default_metrics

    current_price = df_hist['Close'].iloc[-1]
    total_bars = len(df_hist)
    
    # ----------------------------------------------------
    # ROUTINE A: FIXED INCOME & CASH PROXIES
    # ----------------------------------------------------
    is_treasury_or_fixed = (
        bool(re.match(r"^S[A-Za-z]*XX$", ticker_str)) or 
        ticker_str in ['SGOV', 'BIL', 'SHV', 'TLT', 'IEI', 'SHY', 'VMFXX']
    )
    if is_treasury_or_fixed:
        return {
            "Type": "Fixed_Income", "Strict_SEPA": False, "Cyclic_Turnaround": False, 
            "Stage1_Base": False, "Stage3_Dist": False, "Stage4_Short": False, 
            "Fail_Reason": "Cash_Sweep", "Pass_Reason": "None", "Trend_Score": 0.0
        }

    # ----------------------------------------------------
    # ROUTINE B: VOLATILITY BENCHMARKS REGIME
    # ----------------------------------------------------
    if ticker_str in ['/VX', 'VX', 'VIX', 'VVIX', '^VIX', '^VVIX']:
        return {
            "Type": "Volatility_Index", "Strict_SEPA": False, "Cyclic_Turnaround": False, 
            "Stage1_Base": False, "Stage3_Dist": False, "Stage4_Short": False, 
            "Fail_Reason": "Volatility", "Pass_Reason": "None", "Trend_Score": 0.0
        }

    # ----------------------------------------------------
    # ROUTINE C: WIDENED ETF / COM-PROXIES REGIME
    # ----------------------------------------------------
    is_sector_etf = bool(re.match(r"^X[A-Za-z]{2}$", ticker_str))
    is_macro_indicator = ticker_str.startswith('/') or ticker_str.endswith('=F') or ticker_str in [
        'SPY', 'QQQ', 'DIA', 'IWM', 'SMH', 'VWO', 'ASHR', 'MCHI', 'GLD', 'SLV', 'UNG', 'USO', 'SCHP', 'BND'
    ]
    
    if is_sector_etf or is_macro_indicator:
        if total_bars >= 200:
            df_hist['SMA_50'] = df_hist['Close'].rolling(window=50).mean()
            df_hist['SMA_200'] = df_hist['Close'].rolling(window=200).mean()
            
            macro_bullish = current_price > df_hist['SMA_200'].iloc[-1] and df_hist['SMA_50'].iloc[-1] > df_hist['SMA_200'].iloc[-1]
            trend_score = round((current_price / df_hist['SMA_200'].iloc[-1] - 1) * 100, 2)
            
            pass_msg = "Cleared_Macro_Index_Filter" if macro_bullish else "Index_Below_MAs"
            fail_msg = "None" if macro_bullish else "Index_Below_MAs"
            stage4_short = not macro_bullish
        else:
            macro_bullish = True
            stage4_short = False
            trend_score = 0.0
            pass_msg = "Cleared_Macro_Index_Filter"
            fail_msg = "None"
            
        return {
            "Type": "ETF/Indicator", "Strict_SEPA": macro_bullish, "Cyclic_Turnaround": macro_bullish, 
            "Stage1_Base": False, "Stage3_Dist": False, "Stage4_Short": stage4_short, 
            "Fail_Reason": fail_msg, "Pass_Reason": pass_msg, "Trend_Score": trend_score
        }

    # ----------------------------------------------------
    # ROUTINE D: HIGH-VELOCITY RECENT IPO REGIME
    # ----------------------------------------------------
    if total_bars < 200:
        df_hist['SMA_20'] = df_hist['Close'].rolling(window=min(20, total_bars)).mean()
        df_hist['SMA_50'] = df_hist['Close'].rolling(window=min(50, total_bars)).mean()
        
        sma_20 = df_hist['SMA_20'].iloc[-1]
        sma_50 = df_hist['SMA_50'].iloc[-1]
        ipo_high = df_hist['High'].max()
        
        ipo_sepa_pass = current_price > sma_20 and current_price > sma_50 and current_price >= (ipo_high * 0.65)
        stage4_short = current_price < sma_50 and current_price <= (ipo_high * 0.40)
        
        fail_msg = "None" if ipo_sepa_pass else "Failed_IPO_Filters"
        pass_msg = "Cleared_IPO_Short_Horizon_SEPA" if ipo_sepa_pass else "None"
        
        return {
            "Type": "Recent_IPO", "Strict_SEPA": ipo_sepa_pass, "Cyclic_Turnaround": ipo_sepa_pass, 
            "Stage1_Base": not ipo_sepa_pass, "Stage3_Dist": False, "Stage4_Short": stage4_short, 
            "Fail_Reason": fail_msg, "Pass_Reason": pass_msg, 
            "Trend_Score": round((current_price / sma_50 - 1) * 100, 2) if sma_50 > 0 else 0.0
        }

    # ----------------------------------------------------
    # ROUTINE E: ESTABLISHED INDIVIDUAL EQUITIES REGIME
    # ----------------------------------------------------
    df_hist['SMA_50'] = df_hist['Close'].rolling(window=50).mean()
    df_hist['SMA_150'] = df_hist['Close'].rolling(window=150).mean()
    df_hist['SMA_200'] = df_hist['Close'].rolling(window=200).mean()
    
    sma_50 = df_hist['SMA_50'].iloc[-1]
    sma_150 = df_hist['SMA_150'].iloc[-1]
    sma_200 = df_hist['SMA_200'].iloc[-1]
    
    sma_200_is_trending_up = df_hist['SMA_200'].iloc[-1] > df_hist['SMA_200'].iloc[-20]
    
    yearly_high = df_hist['High'].rolling(window=252).max().iloc[-1]
    yearly_low = df_hist['Low'].rolling(window=252).min().iloc[-1]

    # Minervini 7-Point Screening Rules (Stage 2 Uptrend Requirements)
    criteria = {
        "R1_Price_Above_SMA150_200": current_price > sma_150 and current_price > sma_200,
        "R2_SMA150_Above_SMA200": sma_150 > sma_200,
        "R3_SMA200_Trending_Up": sma_200_is_trending_up,
        "R4_SMA50_Stacked": sma_50 > sma_150 and sma_50 > sma_200,
        "R5_Price_Above_SMA50": current_price > sma_50,
        "R6_Within_30Pct_Of_Year_Low": current_price >= yearly_low * 1.30,
        "R7_Within_25Pct_Of_Year_High": current_price >= yearly_high * 0.75,
    }
    fail_reasons = [name for name, passed in criteria.items() if not passed]
    
    strict_sepa_pass = len(fail_reasons) == 0
    fail_string = "|".join(fail_reasons) if not strict_sepa_pass else "None"

    # Cyclic Recovery Turnaround Checker
    cyclic_c1 = current_price > sma_150 and current_price > sma_200
    cyclic_c2 = sma_50 > sma_200
    cyclic_c3 = current_price > sma_50
    cyclic_c4 = current_price >= (yearly_high * 0.55)  
    cyclic_turnaround_pass = all([cyclic_c1, cyclic_c2, cyclic_c3, cyclic_c4])

    # Stage 4 Institutional Downtrend Checklist
    s1 = current_price < sma_50 and current_price < sma_200         
    s2 = sma_50 < sma_200                                             
    s3 = (not sma_200_is_trending_up) and (df_hist['SMA_200'].iloc[-1] < df_hist['SMA_200'].iloc[-20])    
    s4 = current_price <= (yearly_high * 0.75)                        
    s5 = current_price <= (yearly_low * 1.15)                         
    stage4_short_pass = all([s1, s2, s3, s4, s5]) and pd.notna(sma_200)

    # 🔬 NEW REGIME SCORING: Define Stage 1 Base vs Stage 3 Distribution
    stage1_base_pass = False
    stage3_dist_pass = False
    
    if not strict_sepa_pass and not cyclic_turnaround_pass and not stage4_short_pass:
        # Stage 3 Rules: Price breaking key averages after recent highs, but SMA 200 isn't yet fully collapsing
        is_below_50_or_150 = current_price < sma_50 or current_price < sma_150
        is_near_yearly_highs = current_price >= (yearly_high * 0.65)
        
        if is_below_50_or_150 and is_near_yearly_highs:
            stage3_dist_pass = True
        else:
            # Stage 1 Rules: Churning, flat sideways base context
            stage1_base_pass = True

    # Assign comprehensive descriptive reason tags
    if strict_sepa_pass:
        pass_string = "Cleared_All_7_SEPA_Rules"
    elif cyclic_turnaround_pass:
        pass_string = "Cleared_Cyclic_Turnaround_Template"
    elif stage3_dist_pass:
        pass_string = "Identified_Stage3_Distribution_Regime"
    elif stage1_base_pass:
        pass_string = "Identified_Stage1_Accumulation_Base"
    elif stage4_short_pass:
        pass_string = "Confirmed_Stage4_Institutional_Downtrend"
    else:
        pass_string = "None"

    trend_score = round((current_price / sma_200 - 1) * 100, 2) if sma_200 > 0 else 0.0
    
    return {
        "Type": "Equity", "Strict_SEPA": strict_sepa_pass, "Cyclic_Turnaround": cyclic_turnaround_pass,
        "Stage1_Base": stage1_base_pass, "Stage3_Dist": stage3_dist_pass, "Stage4_Short": stage4_short_pass, 
        "Fail_Reason": fail_string, "Pass_Reason": pass_string, "Trend_Score": trend_score
        , **criteria
    }
"""
QUANT TERMINAL - Step 2: Integrated Multi-Regime SEPA Filter Matrix (Part 3/3)
Runs multi-threaded screening loops, applies column anchors, and exports the final matrix.
Upgraded to position the Stage 1 Accumulation indicator exactly to the left of Stage 2 flags.
"""

def run_sepa_pipeline():
    parser = argparse.ArgumentParser(description="QUANT TERMINAL: Step 2 Multi-Regime Filter Layer")
    parser.add_argument("--date", type=str, default=None, help="Target date string override (YYYY-MM-DD).")
    args = parser.parse_args()

    print("=================================================================")
    print("🎯 [STEP 2/7] Running Ingestion Multi-Regime SEPA Filter Matrix...")
    print("=================================================================")

    target_date = args.date if args.date else get_latest_date_from_files()
    
    # 🧼 HARDENED MATCH SELECTION: Find sanitized files, explicitly avoiding option derivatives
    raw_files = glob.glob(os.path.join(INPUT_DIR, f"*{target_date}*_SANITIZED.csv"))
    processed_files = [f for f in raw_files if "-options" not in os.path.basename(f)]

    if not processed_files:
        print(f"⚠️ Warning: No processed input matrices found for target date context: {target_date}")
        return

    for file_path in processed_files:
        base_name = os.path.basename(file_path).replace('.csv', '')
        print(f"📈 Screening Trends for Watchlist Matrix: {base_name}.csv")
        
        df_assets = pd.read_csv(file_path)
        if df_assets.empty:
            continue
            
        # Initialize uniform metric lifecycle headers
        df_assets['Asset_Class'] = "Unknown"
        df_assets['SEPA_Stage2_Pass'] = False
        df_assets['Stage2_Pass_Reason'] = "None"
        df_assets['Cyclic_Turnaround_Pass'] = False
        df_assets['Stage1_Base_Pass'] = False
        df_assets['Stage3_Distribution_Pass'] = False
        df_assets['Stage4_Short_Reference'] = False
        df_assets['Strict_Fail_Reason'] = "None"
        df_assets['Trend_Distance_Pct'] = 0.0
        
        # Evaluate standard equities and index assets via yfinance charts
        for idx, row in df_assets.iterrows():
            ticker = str(row['Symbol']).strip()
            yf_ticker = MACRO_MAP.get(ticker, ticker)
            
            # Skip derivative option contracts or invalid tracking labels
            if ticker.startswith(".") or ticker == "UNKNOWN" or ticker == "()":
                continue
                
            try:
                ticker_obj = yf.Ticker(yf_ticker)
                hist = ticker_obj.history(period="2y", interval="1d", timeout=5)
                metrics = evaluate_asset_trend(ticker, hist)
                
                df_assets.at[idx, 'Asset_Class'] = metrics['Type']
                df_assets.at[idx, 'SEPA_Stage2_Pass'] = metrics['Strict_SEPA']
                df_assets.at[idx, 'Stage2_Pass_Reason'] = metrics['Pass_Reason']
                df_assets.at[idx, 'Cyclic_Turnaround_Pass'] = metrics['Cyclic_Turnaround']
                df_assets.at[idx, 'Stage1_Base_Pass'] = metrics['Stage1_Base']
                df_assets.at[idx, 'Stage3_Distribution_Pass'] = metrics['Stage3_Dist']
                df_assets.at[idx, 'Stage4_Short_Reference'] = metrics['Stage4_Short']
                df_assets.at[idx, 'Strict_Fail_Reason'] = metrics['Fail_Reason']
                df_assets.at[idx, 'Trend_Distance_Pct'] = metrics['Trend_Score']
            except Exception as e:
                print(f"   ⚠️ Skipping yfinance fetch anomaly for {ticker}: {e}")
                continue
                
        # Dual-track sorting hierarchy: Prioritize Long Turnarounds first, then sort by Trend Score
        df_assets = df_assets.sort_values(by=['Cyclic_Turnaround_Pass', 'Trend_Distance_Pct'], ascending=[False, False])
        
        # 📐 EXACT ALIGNMENT MATCH: Stage 1 sits precisely to the left of the Stage 2 columns array
        anchor_cols = [
            'Symbol', 'Last', 'Delta', 'Volume', 'PE', 'Yield', 'Bid', 'Ask', 'Asset_Class', 
            'Stage1_Base_Pass', 
            'SEPA_Stage2_Pass', 'Stage2_Pass_Reason', 'Cyclic_Turnaround_Pass', 
            'Stage3_Distribution_Pass', 'Stage4_Short_Reference', 
            'Strict_Fail_Reason', 'Trend_Distance_Pct'
        ]
        
        remaining_cols = [c for c in df_assets.columns if c not in anchor_cols]
        final_layout = [c for c in (anchor_cols + remaining_cols) if c in df_assets.columns]
        df_assets = df_assets[final_layout]
        
        # 🏷️ Padded Output Token Alignment
        output_path = OUTPUT_DIR / f"{base_name}_SEPA_SCREENED.csv"
        df_assets.to_csv(output_path, index=False)
        print(f"   ↳ Screen Complete -> Saved to {output_path.name}")

    print("\n💾 Step 2 matrix processing complete. Ready for Step 3 indicators calculation.\n")


def run_sepa_diagnostic():
    """Evaluate a small random sample from the local database before full rollout."""
    parser = argparse.ArgumentParser(description="Run a local SEPA diagnostic sample")
    parser.add_argument("--date", type=str, default=None, help="Target date string override (YYYY-MM-DD).")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="Unique non-option symbols to test; all symbols for allpos by default, 0 evaluates all symbols",
    )
    parser.add_argument("--seed", type=int, default=20260824, help="Stable random sample seed")
    parser.add_argument("--history-period", type=str, default="2y", help="Fallback yfinance history period")
    parser.add_argument("--download-missing", type=int, choices=(0, 1), default=1, help="Download when local bars are insufficient")
    parser.add_argument("--offline", action="store_true", help="Use only local database bars; do not access Yahoo Finance")
    parser.add_argument(
        "--watchlist-key",
        type=str,
        default=None,
        help="Select one keyed list, such as allpos, or all keyed lists with 'all'",
    )
    args = parser.parse_args()
    if args.sample_size is not None and args.sample_size < 0:
        parser.error("--sample-size cannot be negative")

    requested_key = args.watchlist_key.lower().replace("allposition", "allpos") if args.watchlist_key else None
    source_files = get_analysis_source_files(requested_key) if not args.date else [
        path for path in get_analysis_source_files(requested_key)
        if args.date in path.name
    ]
    target_date = args.date or get_latest_date_from_files()
    if requested_key and requested_key != "all" and not source_files:
        raise FileNotFoundError(
            f"No sanitized watchlist found for key '{requested_key}'"
        )
    symbol_sources = {}
    for path in source_files:
        frame = pd.read_csv(path, encoding="utf-8-sig", on_bad_lines="skip")
        if "Symbol" in frame.columns:
            source_match = re.search(r"watchlist[-_]([A-Za-z0-9][A-Za-z0-9_-]*?)(?:_SANITIZED)?(?:-options)?\.csv$", path.name, re.IGNORECASE)
            source_key = source_match.group(1).lower() if source_match else "unknown"
            for symbol_value in frame["Symbol"].dropna():
                symbol = str(symbol_value).strip().upper()
                if symbol and not symbol.startswith("."):
                    symbol_sources.setdefault(symbol, set()).add(source_key)
    symbols = set(symbol_sources)
    if not symbols:
        raise FileNotFoundError(f"No non-option symbols found for {target_date} in {INPUT_DIR}")

    rng = random.Random(args.seed)
    effective_sample_size = args.sample_size
    if effective_sample_size is None:
        effective_sample_size = 0 if requested_key == "allpos" else 20

    if effective_sample_size == 0 or len(symbols) <= effective_sample_size:
        selected_symbols = sorted(symbols)
    else:
        selected_symbols = sorted(rng.sample(sorted(symbols), effective_sample_size))
    store = LocalDataStore(DATABASE_PATH) if DATABASE_PATH.exists() else None
    results = []
    try:
        for symbol in selected_symbols:
            history = pd.DataFrame()
            source = "missing"
            if store is not None:
                stored_rows = store.market_bars(symbol)
                if stored_rows:
                    history = pd.DataFrame(stored_rows, columns=["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"])
                    source = "local_db"

            if len(history) < 200 and args.download_missing == 1 and not args.offline:
                yahoo_ticker = symbol
                if symbol.startswith("/"):
                    yahoo_ticker = f"{symbol[1:]}=F"
                print(f"⚠️ {symbol}: local history has {len(history)} bars; requesting {args.history_period} from Yahoo as fallback.")
                try:
                    downloaded = yf.Ticker(yahoo_history_ticker(symbol)).history(period=args.history_period, interval="1d")
                    if not downloaded.empty:
                        history = downloaded.reset_index()
                        history.columns = [str(column).replace(" ", "_") for column in history.columns]
                        history.rename(columns={"Adj_Close": "Adj Close"}, inplace=True)
                        source = "fallback_yahoo"
                        if store is not None:
                            try:
                                if not store.market_data_coverage([symbol]):
                                    asset_type = "future_or_index" if symbol.startswith("/") else "equity_or_fund"
                                    store.upsert_asset(symbol, asset_type, None, target_date)
                                asset_id = store.asset_id(symbol)
                                store.save_bars(asset_id, history_to_store_bars(history.set_index("Date")))
                                store.commit()
                                print(f"   ↳ {symbol}: fallback history cached locally for future SEPA runs.")
                            except (KeyError, ValueError) as error:
                                print(f"   ⚠️ {symbol}: fallback history used but not cached ({error}).")
                except Exception as error:
                    print(f"⚠️ {symbol}: fallback history unavailable ({error}).")

            metrics = evaluate_asset_trend(symbol, history)
            if args.offline and len(history) < 200:
                source = "missing_offline"
            coverage = store.market_data_coverage([symbol])[0] if store is not None and store.market_data_coverage([symbol]) else {}
            result = {
                "Symbol": symbol,
                "Source_Watchlists": "|".join(sorted(symbol_sources.get(symbol, set()))),
                "Data_Source": source,
                "Stored_Bars": coverage.get("bar_count", 0),
                "Stored_First_Date": coverage.get("first_bar_date"),
                "Stored_Last_Date": coverage.get("last_bar_date"),
                "Evaluated_Bars": len(history),
                "Stage": metrics.get("Pass_Reason", "No_Data"),
                "Stage1_Base": metrics.get("Stage1_Base", False),
                "Stage2_SEPA": metrics.get("Strict_SEPA", False),
                "Stage3_Distribution": metrics.get("Stage3_Dist", False),
                "Stage4_Downtrend": metrics.get("Stage4_Short", False),
                "Fail_Reason": metrics.get("Fail_Reason", "No_Data"),
                "Pass_Reason": metrics.get("Pass_Reason", "None"),
                "Trend_Score": metrics.get("Trend_Score", 0.0),
            }
            result.update({name: metrics.get(name, False) for name in (
                "R1_Price_Above_SMA150_200", "R2_SMA150_Above_SMA200", "R3_SMA200_Trending_Up",
                "R4_SMA50_Stacked", "R5_Price_Above_SMA50", "R6_Within_30Pct_Of_Year_Low",
                "R7_Within_25Pct_Of_Year_High",
            )})
            results.append(result)
    finally:
        if store is not None:
            store.close()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = SEPA_RESULTS_DIR / f"{target_date}_SEPA_DIAGNOSTIC_{stamp}.csv"
    pd.DataFrame(results).to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n🧪 SEPA diagnostic complete: {len(results)} symbols -> {output_path}")
    print("   Prior diagnostic files are preserved; no result file was overwritten.")


if __name__ == "__main__":
    run_sepa_diagnostic()

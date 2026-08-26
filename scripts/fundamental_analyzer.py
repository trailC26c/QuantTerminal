"""
QUANT TERMINAL - Step 4: Integrated Equity & ETF Fundamental Analyzer (Part 1/3)
Configures pathing architectures, cross-asset dictionaries, and option/index stripping filters.
"""

import os
import re
import sys
import time
import glob
import json
import traceback
import argparse
from datetime import datetime
from pathlib import Path
from datetime import timezone
import pandas as pd
import numpy as np

import yfinance as yf
from local_data_store import LocalDataStore

# Silence yfinance terminal internal warnings
import logging
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

# 📌 Directory Realignment: Clean pipeline structures matching your workspace folders
# 📌 Directory Realignment: Raw input remains external; sanitized input is project-local
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(PROJECT_DIR, "data", "sanitized_watchlists")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output", "fundemental_matrix")
DATABASE_PATH = os.path.join(PROJECT_DIR, "data", "quant_terminal.db")
SCORING_CONFIG_PATH = os.path.join(PROJECT_DIR, "data", "fundamental_scoring.json")

os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_scoring_config():
    """Load scoring rules once so each output records the active configuration."""
    with open(SCORING_CONFIG_PATH, "r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    weights = config["weights"]
    if sum(weights.values()) <= 0:
        raise ValueError("Fundamental scoring weights must have a positive total")
    candidate_limit = config.get("candidate_limit")
    if candidate_limit is not None and candidate_limit < 1:
        raise ValueError("candidate_limit must be positive")
    return config


def bounded_score(value, lower, upper, score_min=-100.0, score_max=100.0):
    if upper <= lower:
        return 0.0
    normalized = ((float(value) - lower) / (upper - lower)) * (score_max - score_min) + score_min
    return round(max(score_min, min(score_max, normalized)), 2)


def calculate_fundamental_score(row, config):
    """Return score, completeness, and confidence for one equity or ETF row."""
    score_min, score_max = config.get("normalized_score_bounds", [-100.0, 100.0])
    if str(row.get("Sector", "")).upper() == "ETF_FUNDS":
        expense_score = bounded_score(-float(row.get("Expense_Ratio", 0.0)), -2.0, 0.0, score_min, score_max)
        yield_score = bounded_score(float(row.get("Net_Yield_After_Expense", 0.0)), -2.0, 12.0, score_min, score_max)
        score = round((0.65 * yield_score) + (0.35 * expense_score), 2)
        return score, 1.0, "ETF_RULES"

    ranges = config["score_ranges"]
    components = {
        "earnings_growth": bounded_score(row.get("Earnings_Growth_YoY", 0.0), *ranges["earnings_growth"], score_min, score_max),
        "ebitda_margin": bounded_score(row.get("EBITDA_Margin", 0.0), *ranges["ebitda_margin"], score_min, score_max),
        "gross_margin": bounded_score(row.get("Gross_Margin", 0.0), *ranges["gross_margin"], score_min, score_max),
        "free_cash_flow_yield": bounded_score(row.get("Free_Cash_Flow_Yield", 0.0), *ranges["free_cash_flow_yield"], score_min, score_max),
        "analyst_consensus": bounded_score(3.0 - float(row.get("Analyst_Rec_Score", 3.0)), -2.0, 2.0, score_min, score_max),
        "target_upside": bounded_score(row.get("Sentiment_Target_Upside", 0.0), *ranges["target_upside"], score_min, score_max),
        "institutional_ownership": bounded_score(row.get("Institutional_Ownership_Pct", 0.0), *ranges["institutional_ownership"], score_min, score_max),
    }
    weights = config["weights"]
    score = round(sum(components[name] * weights[name] for name in components) / sum(weights.values()), 2)
    required = ["Earnings_Growth_YoY", "EBITDA_Margin", "Gross_Margin", "Free_Cash_Flow_Yield", "Analyst_Rec_Score", "Sentiment_Target_Upside", "Institutional_Ownership_Pct"]
    available = sum(pd.notna(row.get(name)) for name in required)
    completeness = round(available / len(required), 2)
    return score, completeness, "EQUITY_RULES"


def write_candidate_outputs(frame, target_date, scope, config):
    """Write scored candidate views without changing the complete fundamental matrix."""
    scored = frame.copy()
    analyst_columns = {
        "Analyst_Strong_Buy_Count": 0,
        "Analyst_Buy_Count": 0,
        "Analyst_Hold_Count": 0,
        "Analyst_Sell_Count": 0,
        "Analyst_Strong_Sell_Count": 0,
        "Analyst_Total_Count": 0,
        "Analyst_Consensus_Confidence": 0.0,
    }
    for column, default in analyst_columns.items():
        if column not in scored.columns:
            scored[column] = default
    calculated = scored.apply(lambda row: calculate_fundamental_score(row, config), axis=1, result_type="expand")
    scored[["Fundamental_Score", "Fundamental_Data_Completeness", "Fundamental_Score_Model"]] = calculated
    scored["Fundamental_Qualification"] = "UNQUALIFIED"
    eligible = scored["Fundamental_Data_Completeness"] >= config["minimum_completeness"]
    scored.loc[~eligible, "Fundamental_Qualification"] = "INSUFFICIENT_DATA"
    ranked = scored.loc[eligible].sort_values("Fundamental_Score", ascending=False)
    long_rows = ranked.head(config["long_limit"]).copy()
    short_rows = ranked.tail(config["short_limit"]).sort_values("Fundamental_Score").copy()
    scored.loc[long_rows.index, "Fundamental_Qualification"] = "QUALIFIED_LONG"
    scored.loc[short_rows.index, "Fundamental_Qualification"] = "QUALIFIED_SHORT"
    scored["Candidate_Selection_Reason"] = "TOP_SCORE_LIMIT"
    generic_mask = scored["Source_Watchlists"].fillna("").astype(str).str.split("|").apply(
        lambda values: "generic" in values
    )
    if scope == "all" and config.get("include_generic_overflow", False):
        generic_long = scored.index[generic_mask & eligible & (scored["Fundamental_Score"] > config.get("generic_long_min_score", 0))]
        generic_short = scored.index[generic_mask & eligible & (scored["Fundamental_Score"] < config.get("generic_short_max_score", 0))]
        scored.loc[generic_long, "Fundamental_Qualification"] = "QUALIFIED_LONG"
        scored.loc[generic_long, "Candidate_Selection_Reason"] = "GENERIC_SCORE_OVERFLOW_LONG"
        scored.loc[generic_short, "Fundamental_Qualification"] = "QUALIFIED_SHORT"
        scored.loc[generic_short, "Candidate_Selection_Reason"] = "GENERIC_SCORE_OVERFLOW_SHORT"
    scored["Fundamental_Rank"] = scored["Fundamental_Score"].rank(method="min", ascending=False).astype("Int64")
    prefix = f"{target_date}_FUNDAMENTAL"
    if scope != "all":
        prefix = f"{target_date}_{scope}_FUNDAMENTAL"
    scored[scored["Fundamental_Qualification"] == "UNQUALIFIED"].to_csv(
        os.path.join(OUTPUT_DIR, f"{prefix}_UNQUALIFIED.csv"), index=False, encoding="utf-8-sig"
    )
    long_rows = scored[scored["Fundamental_Qualification"] == "QUALIFIED_LONG"]
    short_rows = scored[scored["Fundamental_Qualification"] == "QUALIFIED_SHORT"]
    long_rows.to_csv(os.path.join(OUTPUT_DIR, f"{prefix}_QUALIFIED_LONG.csv"), index=False, encoding="utf-8-sig")
    short_rows.to_csv(os.path.join(OUTPUT_DIR, f"{prefix}_QUALIFIED_SHORT.csv"), index=False, encoding="utf-8-sig")


def parse_args():
    parser = argparse.ArgumentParser(description="Run fundamental analysis on sanitized watchlists")
    parser.add_argument(
        "--watchlist-key",
        default="all",
        help="Process one keyed list or all latest keyed lists (default: all)",
    )
    parser.add_argument(
        "--refresh-days",
        type=int,
        default=7,
        help="Refresh fundamental snapshots older than this many days (default: 7)",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Refresh fundamentals even when a local snapshot is within the refresh window",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use only local fundamental snapshots; do not access Yahoo Finance",
    )
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=None,
        help="Override the JSON long and short candidate limits for this run",
    )
    args = parser.parse_args()
    if args.refresh_days < 0:
        parser.error("--refresh-days cannot be negative")
    if args.candidate_limit is not None and args.candidate_limit < 1:
        parser.error("--candidate-limit must be positive")
    return args


def get_latest_sanitized_file_date():
    """Prefer the newest native session date over a generic-only date cluster."""
    files = glob.glob(os.path.join(INPUT_DIR, "*_SANITIZED.csv"))
    if not files:
        print("❌ Diagnostic Warning: Could not find any sanitized watchlist files in tracking directory.")
        return datetime.now().strftime("%Y-%m-%d")
        
    def extract_date(f):
        match = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(f))
        return match.group(1) if match else "0000-00-00"
        
    dated_files = [(f, extract_date(f)) for f in files]
    dated_files = [(f, date_value) for f, date_value in dated_files if date_value != "0000-00-00"]
    native_dates = [
        date_value for file_path, date_value in dated_files
        if "watchlist-generic" not in os.path.basename(file_path).lower()
        and "watchlist_generic" not in os.path.basename(file_path).lower()
    ]
    return max(native_dates or [date_value for _, date_value in dated_files]) if dated_files else datetime.now().strftime("%Y-%m-%d")


def get_analysis_target_files(requested_key):
    """Select one file per key from the latest native and generic date clusters."""
    files = []
    for path in glob.glob(os.path.join(INPUT_DIR, "*_SANITIZED.csv")):
        name = os.path.basename(path)
        if "-options" in name.lower():
            continue
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", name)
        key_match = re.search(r"watchlist[-_]([A-Za-z0-9][A-Za-z0-9_-]*?)_SANITIZED\.csv$", name, re.IGNORECASE)
        if date_match and key_match:
            files.append((path, date_match.group(1), key_match.group(1).lower()))
    if requested_key != "all":
        dates = [date for _, date, key in files if key == requested_key]
        target = max(dates) if dates else None
        selected = [path for path, date, key in files if key == requested_key and date == target]
        return [sorted(selected, key=lambda path: ("-watchlist-" not in os.path.basename(path), path))[0]] if selected else []
    native_dates = [date for _, date, key in files if key != "generic"]
    generic_dates = [date for _, date, key in files if key == "generic"]
    native_target = max(native_dates) if native_dates else None
    generic_target = max(generic_dates) if generic_dates else None
    selected = [
        (path, date, key)
        for path, date, key in files
        if (key != "generic" and date == native_target)
        or (key == "generic" and date == generic_target)
    ]
    selected_by_key = {}
    for path, date, key in selected:
        current = selected_by_key.get(key)
        if current is None or "-watchlist-" not in os.path.basename(current):
            selected_by_key[key] = path
    return sorted(selected_by_key.values())


def is_option_contract(symbol_str):
    """Filters out options contracts, continuous index symbols, and raw futures contract rows upfront."""
    sym = str(symbol_str).strip().upper()
    
    if sym.startswith("/") or sym.startswith("^") or sym in ["SPCX", "SPX", "COMP", "IXIC", "DJI", "RTY", "VIX"]:
        return True
        
    if sym.startswith(".") or " " in sym or len(sym) > 6:
        if re.search(r'\d', sym):
            return True
            
    if sym in ["", "nan", "()", "UNKNOWN"]:
        return True
        
    return False


def parse_percent_value(raw_value, decimal_threshold=1.0):
    """Normalize decimal or percentage-formatted provider values to percent."""
    if raw_value is None or pd.isna(raw_value):
        return 0.0
    text = str(raw_value).strip().replace(",", "")
    has_percent_sign = text.endswith("%")
    if has_percent_sign:
        text = text[:-1].strip()
    if not text:
        return 0.0
    try:
        value = float(text)
    except (TypeError, ValueError):
        return 0.0
    if not has_percent_sign and abs(value) < decimal_threshold:
        value *= 100.0
    return round(value, 3)


def parse_etf_expense_ratio(raw_value):
    """Normalize ETF expense ratios while preserving provider percent values."""
    return parse_percent_value(raw_value, decimal_threshold=0.01)


def parse_etf_yield(raw_value):
    """Normalize ETF yield and reject implausible provider artifacts."""
    value = parse_percent_value(raw_value)
    if abs(value) > 20.0:
        value /= 100.0
    return value if -20.0 <= value <= 20.0 else 0.0


def parse_analyst_recommendation_counts(trend_data):
    """Extract current-period analyst vote counts from Yahoo recommendation data."""
    fields = {
        "Analyst_Strong_Buy_Count": "strongBuy",
        "Analyst_Buy_Count": "buy",
        "Analyst_Hold_Count": "hold",
        "Analyst_Sell_Count": "sell",
        "Analyst_Strong_Sell_Count": "strongSell",
    }
    counts = {field: 0 for field in fields}
    if isinstance(trend_data, pd.DataFrame):
        trend_data = trend_data.to_dict(orient="records")
    if not isinstance(trend_data, list):
        return counts
    current = next(
        (
            item for item in trend_data
            if str(item.get("period", "")).strip().lower() in {"0", "0m", "current"}
        ),
        trend_data[0] if trend_data else {},
    )
    for output_name, provider_name in fields.items():
        try:
            counts[output_name] = max(0, int(current.get(provider_name, 0) or 0))
        except (TypeError, ValueError):
            counts[output_name] = 0
    return counts
"""
QUANT TERMINAL - Step 4: Integrated Equity & ETF Fundamental Analyzer (Part 2/3)
Queries yfinance to extract core stock metrics, gross/EBITDA margins, and structural FCF yields.
"""

def fetch_adaptive_ticker_telemetry(symbol_str):
    """Dynamically parses Yahoo Finance data to extract Equity, ETF, or continuous index futures metrics."""
    raw_ticker = str(symbol_str).strip().upper()
    ticker_key = raw_ticker
    
    if ticker_key.startswith('/'):
        clean_base = ticker_key[1:]
        match_futures = re.match(r"^(ES|NQ|YM|RTY|CL|GC|SI|HG|NG|ZC|ZO|ZS|ZM|ZL|LH|LE|KC|CC|SB|CT|ZF|ZN|ZT|ZB|VX)", clean_base)
        if match_futures:
            ticker_key = f"{match_futures.group(1)}=F"
        else:
            ticker_key = f"{clean_base}=F"
            
    if ticker_key in ["SPCX", "SPX"]: ticker_key = "^SPX"
    if ticker_key in ["COMP", "IXIC"]: ticker_key = "^IXIC"

    obj = yf.Ticker(ticker_key)
    
    metrics = {
        "Sector": "N/A", 
        "Industry": "GENERAL_EQUITY", 
        "Gross_Margin": 0.0, 
        "EBITDA_Margin": 0.0,
        "Free_Cash_Flow_Yield": 0.0,
        "Expense_Ratio": 0.0,
        "Yield": 0.0,
        "Net_Yield_After_Expense": 0.0,
        "Beta_vs_ES": 1.0, 
        "Cap_Billions": 0.0, 
        "PE_Ratio": 0.0,
        "Earnings_Growth_YoY": 0.0,
        "Institutional_Ownership_Pct": 0.0,
        "Analyst_Rec_Score": 3.0,          
        "Analyst_Consensus": "NEUTRAL",     
        "Analyst_Strong_Buy_Count": 0,
        "Analyst_Buy_Count": 0,
        "Analyst_Hold_Count": 0,
        "Analyst_Sell_Count": 0,
        "Analyst_Strong_Sell_Count": 0,
        "Analyst_Total_Count": 0,
        "Analyst_Consensus_Confidence": 0.0,
        "Sentiment_Target_Upside": 0.0,
        "Short_Percent_Of_Float": 0.0      
    }
    
    try:
        inf = obj.info
        if not inf:
            if "=F" in ticker_key or ticker_key.startswith("^"):
                metrics["Sector"] = "MACRO_INDEX_FUTURE"
                metrics["Industry"] = "COMMODITY_FINANCIAL"
            return metrics
            
        quote_type = str(inf.get('quoteType', 'EQUITY')).upper()
        current_price = inf.get('currentPrice', inf.get('previousClose', 0.0))
        mcap = float(inf.get('marketCap', 0.0))
        
        # 📌 ETF / Fund Parsing Branch 
        if quote_type in ['ETF', 'MUTUALFUND', 'FUTURE'] or '=F' in ticker_key or 'expenseRatio' in inf or 'fundFamily' in inf:
            metrics["Sector"] = "ETF_FUNDS" if quote_type != 'FUTURE' else "MACRO_INDEX_FUTURE"
            metrics["Industry"] = str(inf.get('fundFamily', inf.get('category', 'CROSS_ASSET_INDEX'))).upper()
            
            raw_expense = inf.get('expenseRatio', 
                             inf.get('annualReportExpenseRatio', 
                             inf.get('feesExpensesInvestment', 
                             inf.get('netExpenseRatio', 0.0))))
            
            metrics["Expense_Ratio"] = parse_etf_expense_ratio(raw_expense)

            raw_yield = inf.get(
                "yield",
                inf.get("trailingAnnualDividendYield", inf.get("dividendYield", 0.0)),
            )
            metrics["Yield"] = parse_etf_yield(raw_yield)
            metrics["Net_Yield_After_Expense"] = round(
                metrics["Yield"] - metrics["Expense_Ratio"], 3
            )
            
            raw_beta = inf.get('beta3Year', inf.get('beta', 1.0))
            metrics["Beta_vs_ES"] = round(float(raw_beta), 2) if raw_beta else 1.0
            metrics["Cap_Billions"] = round(float(inf.get('totalAssets', 0.0)) / 1e9, 3)
            metrics["PE_Ratio"] = round(float(inf.get('trailingPE', 0.0)), 1) if inf.get('trailingPE') else 0.0
            
        # 📌 Corporate Stock Parsing Branch
        else:
            metrics["Sector"] = str(inf.get('sector', 'EQUITY_RISK')).upper()
            metrics["Industry"] = str(inf.get('industry', 'GENERAL_EQUITY')).upper()
            metrics["Gross_Margin"] = round(float(inf.get('grossMargins', 0.0)) * 100.0, 2)
            
            raw_ebitda = inf.get('ebitdaMargins')
            if raw_ebitda is not None:
                metrics["EBITDA_Margin"] = round(float(raw_ebitda) * 100.0, 2)
                
            raw_fcf = inf.get('freeCashflow')
            if raw_fcf is not None and mcap > 0:
                metrics["Free_Cash_Flow_Yield"] = round((float(raw_fcf) / mcap) * 100.0, 2)
                
            metrics["Beta_vs_ES"] = round(float(inf.get('beta', 1.0)), 2)
            metrics["Cap_Billions"] = round(mcap / 1e9, 2)
            metrics["PE_Ratio"] = round(float(inf.get('trailingPE', 0.0)), 1) if inf.get('trailingPE') else 0.0
            metrics["Earnings_Growth_YoY"] = round(float(inf.get('earningsGrowth', 0.0)) * 100.0, 2)
            metrics["Institutional_Ownership_Pct"] = round(float(inf.get('heldPercentInstitutions', 0.0)) * 100.0, 2)
            
            target_price = inf.get('targetMeanPrice')
            if target_price and current_price > 0:
                upside_pct = ((float(target_price) - float(current_price)) / float(current_price)) * 100.0
                metrics["Sentiment_Target_Upside"] = round(upside_pct, 2)
                
            raw_short_float = inf.get('shortPercentOfFloat')
            if raw_short_float is not None:
                metrics["Short_Percent_Of_Float"] = round(float(raw_short_float) * 100.0, 2)

        raw_rec_score = inf.get('recommendationMean')
        if raw_rec_score is not None:
            metrics["Analyst_Rec_Score"] = round(float(raw_rec_score), 2)
        metrics["Analyst_Consensus"] = str(inf.get('recommendationKey', 'NEUTRAL')).upper().replace('_', ' ')
        recommendation_data = inf.get("recommendationTrend")
        if recommendation_data is None:
            try:
                recommendation_data = obj.recommendations
            except Exception:
                recommendation_data = None
        analyst_counts = parse_analyst_recommendation_counts(recommendation_data)
        metrics.update(analyst_counts)
        metrics["Analyst_Total_Count"] = sum(analyst_counts.values())
        metrics["Analyst_Consensus_Confidence"] = round(
            min(100.0, (metrics["Analyst_Total_Count"] / 20.0) * 100.0), 2
        )
                
    except Exception:
        pass
        
    return metrics
"""
QUANT TERMINAL - Step 4: Integrated Equity & ETF Fundamental Analyzer (Part 3/3)
Ingests target watchlists contextually, runs standard options filtering passes,
maps local historical bi-weekly file short deltas, and saves padded data tables.
"""

def run_fundamental_stage_analyzer():
    print("========================================================")
    print("🌍 [STEP 5] Running Adaptive Equity/ETF Fundamental Analyzer...")
    print("📡 Extracting Operational Margins, Short Interest Deltas & Multi-File Overlays...")
    print("========================================================\n")
    
    cli_args = parse_args()
    scoring_config = load_scoring_config()
    if cli_args.candidate_limit is not None:
        scoring_config["long_limit"] = cli_args.candidate_limit
        scoring_config["short_limit"] = cli_args.candidate_limit
    requested_key = cli_args.watchlist_key.strip().lower().replace("allposition", "allpos")
    target_files = get_analysis_target_files(requested_key)
    target_date = get_latest_sanitized_file_date()

    if requested_key != "all" and not target_files:
        raise FileNotFoundError(
            f"No sanitized watchlist found for key '{requested_key}' and date {target_date}"
        )

    print(f"🔑 Fundamental watchlist scope: {requested_key}")
    
    telemetry_cache = {}
    store = LocalDataStore(Path(DATABASE_PATH))
    combined_frames = []
    
    # LOCAL BACKSTOP OVERLAY SCANNER: Look into filesystem directory to grab the previous session's metrics
    historical_matrix_files = glob.glob(os.path.join(OUTPUT_DIR, "*_FUND_PROCESSED.csv"))
    previous_short_map = {}
    
    if historical_matrix_files:
        sorted_history = sorted(historical_matrix_files)
        valid_history_files = [f for f in sorted_history if target_date not in os.path.basename(f)]
        
        if valid_history_files:
            prior_file_path = valid_history_files[-1]
            print(f"📁 Local File Backstop Target Lock -> Found Prior File: {os.path.basename(prior_file_path)}")
            try:
                df_prior = pd.read_csv(prior_file_path)
                if 'Symbol' in df_prior.columns and 'Short_Percent_Of_Float' in df_prior.columns:
                    previous_short_map = dict(zip(df_prior['Symbol'].astype(str), df_prior['Short_Percent_Of_Float'].astype(float)))
            except Exception as history_read_err:
                print(f"⚠️ Notice: Failed parsing older matrix profile records: {history_read_err}")

    for position_file in target_files:
        filename = os.path.basename(position_file)
        
        print(f"--------------------------------------------------------")
        print(f"🔍 Processing Targeted File Matrix: {filename}")
        print(f"--------------------------------------------------------")
        
        if not os.path.exists(position_file):
            print(f"⚠️ Notice: Targeted sheet missing -> {filename}. Skipping to next template.")
            continue
            
        try:
            df_base = pd.read_csv(position_file)
            if df_base.empty or 'Symbol' not in df_base.columns:
                print("⚠️ Notice: Loaded sheet contains an invalid symbol index schema array.")
                continue
                
            df_filtered = df_base[df_base['Symbol'].apply(lambda x: not is_option_contract(x))].copy()
            if df_filtered.empty:
                print("⚠️ Notice: Skipping file - no valid stock/ETF rows remain after options filter pass.")
                continue
                
            all_symbols = df_filtered['Symbol'].dropna().unique()
            print(f"📡 Found {len(df_base)} total rows. Processed {len(all_symbols)} unique underlying equities/funds...")
            
            collected_matrix = []
            for idx, sym in enumerate(all_symbols):
                if sym in telemetry_cache:
                    data_package = telemetry_cache[sym].copy()
                else:
                    data_package = None
                    data_status = "missing_offline"
                    if not cli_args.force_refresh:
                        data_package = store.get_fundamental_snapshot(sym, cli_args.refresh_days)
                        if data_package is not None:
                            data_status = "local_fresh"
                            print(
                                f"   ↳ {sym}: using local fundamental snapshot "
                                f"({data_package['_snapshot_age_days']} days old)."
                            )

                    if data_package is None and cli_args.offline:
                        data_package = store.get_fundamental_snapshot(sym, 36500)
                        if data_package is not None:
                            data_status = "local_stale_offline"
                            print(
                                f"   ↳ {sym}: using older local fundamental snapshot "
                                f"({data_package['_snapshot_age_days']} days old; offline)."
                            )

                    if data_package is None:
                        if cli_args.offline:
                            print(
                                f"   ⚠️ {sym}: no local fundamental snapshot within "
                                f"{cli_args.refresh_days} days; skipping provider pull (offline)."
                            )
                            data_package = {
                                "Sector": "N/A",
                                "Industry": "N/A",
                                "Gross_Margin": 0.0,
                                "EBITDA_Margin": 0.0,
                                "Free_Cash_Flow_Yield": 0.0,
                                "Expense_Ratio": 0.0,
                                "Yield": 0.0,
                                "Net_Yield_After_Expense": 0.0,
                                "Beta_vs_ES": 1.0,
                                "Cap_Billions": 0.0,
                                "PE_Ratio": 0.0,
                                "Earnings_Growth_YoY": 0.0,
                                "Institutional_Ownership_Pct": 0.0,
                                "Analyst_Rec_Score": 3.0,
                                "Analyst_Consensus": "NEUTRAL",
                                "Analyst_Strong_Buy_Count": 0,
                                "Analyst_Buy_Count": 0,
                                "Analyst_Hold_Count": 0,
                                "Analyst_Sell_Count": 0,
                                "Analyst_Strong_Sell_Count": 0,
                                "Analyst_Total_Count": 0,
                                "Analyst_Consensus_Confidence": 0.0,
                                "Sentiment_Target_Upside": 0.0,
                                "Short_Percent_Of_Float": 0.0,
                                "Fundamental_Data_Status": data_status,
                            }
                        elif cli_args.force_refresh:
                            print(f"   ↻ {sym}: force refresh requested; pulling fundamentals.")
                            data_status = "provider_refresh"
                        else:
                            print(f"   ↻ {sym}: snapshot missing or older than {cli_args.refresh_days} days; pulling fundamentals.")
                            data_status = "provider_refresh"
                        if not cli_args.offline:
                            data_package = fetch_adaptive_ticker_telemetry(sym)
                            asset_id = store.upsert_asset(sym, "equity_or_fund", None, target_date)
                            store.save_fundamental_snapshot(asset_id, data_package)
                            store.commit()
                    data_package.pop("_snapshot_retrieved_at", None)
                    data_package.pop("_snapshot_age_days", None)
                    data_package.setdefault("Fundamental_Data_Status", data_status)
                    data_package.setdefault("Analyst_Strong_Buy_Count", 0)
                    data_package.setdefault("Analyst_Buy_Count", 0)
                    data_package.setdefault("Analyst_Hold_Count", 0)
                    data_package.setdefault("Analyst_Sell_Count", 0)
                    data_package.setdefault("Analyst_Strong_Sell_Count", 0)
                    data_package.setdefault("Analyst_Total_Count", 0)
                    data_package.setdefault("Analyst_Consensus_Confidence", 0.0)
                    data_package["Symbol"] = sym
                    
                    prior_value = previous_short_map.get(str(sym), np.nan)
                    if pd.isna(prior_value) or prior_value == 0.0:
                        data_package["Short_Percent_Of_Float_Last"] = data_package["Short_Percent_Of_Float"]
                    else:
                        data_package["Short_Percent_Of_Float_Last"] = prior_value
                        
                    telemetry_cache[sym] = data_package
                    if data_package["Fundamental_Data_Status"] == "provider_refresh":
                        time.sleep(0.35)
                
                collected_matrix.append(data_package)
                
                # 📊 RESTORED DYNAMIC TERMINAL FORMATTER LOGS: Weaves EBITDA, short float, and analyst consensus side-by-side
                if data_package["Sector"] == "ETF_FUNDS":
                    print(f"   ↳ ETF   [{idx+1}/{len(all_symbols)}]: {sym:<5} | Expense: {data_package['Expense_Ratio']:.3f}% | AUM: ${data_package['Cap_Billions']:.2f}B")
                elif data_package["Sector"] == "MACRO_INDEX_FUTURE":
                    print(f"   ↳ Futures [{idx+1}/{len(all_symbols)}]: {sym:<5} | Aligned continuous ticker endpoint fetch clean.")
                else:
                    print(f"   ↳ Stock [{idx+1}/{len(all_symbols)}]: {sym:<5} | EBITDA Margin: {data_package['EBITDA_Margin']:.1f}% | Short Float: {data_package['Short_Percent_Of_Float']:.1f}% | Sentiment: {data_package['Analyst_Consensus']:<9}")
            
            df_fundamentals = pd.DataFrame(collected_matrix) if collected_matrix else pd.DataFrame(columns=["Symbol"])
            
            if 'Margin' in df_filtered.columns:
                df_filtered.rename(columns={'Margin': 'Legacy_Margin'}, inplace=True)
                
            if 'PE_Ratio' in df_fundamentals.columns and 'PE' in df_filtered.columns:
                df_fundamentals['PE_Ratio'] = df_fundamentals['PE_Ratio'].replace(0.0, np.nan)
                df_filtered['PE'] = df_filtered['PE'].replace(0.0, np.nan)
                
            overlapping_columns = [
                column for column in df_fundamentals.columns
                if column != 'Symbol' and column in df_filtered.columns
            ]
            df_filtered = df_filtered.drop(columns=overlapping_columns, errors='ignore')
            df_final = pd.merge(df_filtered, df_fundamentals, on='Symbol', how='left')

            source_match = re.search(
                r"watchlist[-_]([A-Za-z0-9][A-Za-z0-9_-]*?)_SANITIZED\.csv$",
                filename,
                re.IGNORECASE,
            )
            source_key = source_match.group(1).lower() if source_match else "unknown"
            df_final["Source_Watchlists"] = source_key
            
            if 'PE_Ratio' in df_final.columns and 'PE' in df_final.columns:
                df_final['PE_Ratio'] = df_final['PE_Ratio'].fillna(df_final['PE'])
                df_final.drop(columns=['PE'], inplace=True, errors='ignore')
                df_final.rename(columns={'PE_Ratio': 'PE'}, inplace=True)
                
            if 'Legacy_Margin' in df_final.columns:
                df_final.drop(columns=['Legacy_Margin'], inplace=True, errors='ignore')
            
            if requested_key == "all":
                combined_frames.append(df_final)
            else:
                base_filename_string = filename.replace('.csv', '')
                out_name = f"{base_filename_string}_FUND_PROCESSED.csv"
                out_path = os.path.join(OUTPUT_DIR, out_name)
                df_final.to_csv(out_path, index=False, encoding="utf-8-sig")
                print(f"\n🏆 SUCCESS: Generated unified fundamental metrics sheet.")
                print(f"💾 File archived safely -> {os.path.basename(out_path)}\n")
            
        except Exception as file_pipeline_err:
            print(f"❌ Error processing file pipeline layout {filename}: {file_pipeline_err}")
            traceback.print_exc()
            
    if requested_key == "all" and combined_frames:
        combined = pd.concat(combined_frames, ignore_index=True)
        source_map = combined.groupby("Symbol")["Source_Watchlists"].agg(
            lambda values: "|".join(sorted(set(values)))
        )
        combined = combined.drop_duplicates(subset=["Symbol"], keep="first")
        combined["Source_Watchlists"] = combined["Symbol"].map(source_map)
        combined_path = os.path.join(
            OUTPUT_DIR,
            f"{target_date}_watchlist_all_FUND_PROCESSED.csv",
        )
        combined.to_csv(combined_path, index=False, encoding="utf-8-sig")
        write_candidate_outputs(combined, target_date, requested_key, scoring_config)
        print(f"\n🏆 SUCCESS: Combined fundamental matrix generated.")
        print(f"💾 File archived safely -> {os.path.basename(combined_path)}")

    print("========================================================")
    print("🏆 ALL TARGETED FILES COMPILED AND UPDATED SUCCESSFULLY.")
    print("========================================================\n")
    store.close()

if __name__ == "__main__":
    run_fundamental_stage_analyzer()

"""
=========================================================================
📡 QUANT TERMINAL: STEP 1 RAW WORKSPACE CONVERGENCE & PROCESSOR ENGINE
=========================================================================
File Name: processor.py
Block 1 of 4: Workspace Paths, CLI Generic Slicers, and Configuration Ingestors.
Standardized to an absolute flat 4-space nested indentation frame.
🎯 TELEMETRY ALIGNMENT MATCH: Synchronizes the flat text reading loops 
to accept vertical newline single stock columns underneath [ALPHA_SINGLES].
"""

import os
import re
import sys
import argparse
import traceback
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
import yfinance as yf
from local_data_store import LocalDataStore

# =========================================================================
# 🎛️ COMMAND LINE INTERFACE (CLI) ARGUMENT EXTENSION PARSER
# =========================================================================
parser = argparse.ArgumentParser(description="QUANT TERMINAL: Step 1 Raw Watchlist Processor")
parser.add_argument(
    "--input", 
    type=str, 
    default="native", 
    choices=["native", "generic", "all"],
    help="Input mode: native keyed files, generic telemetry, or both"
)
parser.add_argument("--privacy_guard", type=int, choices=(0, 1), default=1, help="Strip personal and portfolio data: 1=on, 0=off")
parser.add_argument("--offline", action="store_true", help="Use only local data; do not access Yahoo Finance")
args, unknown = parser.parse_known_args()
INPUT_MODE = args.input.lower().strip()
PRIVACY_GUARD = args.privacy_guard == 1
OFFLINE = args.offline

# Standard Workspace Path Layout
BASE_DIR = Path(r"C:\Users\tcnet\TOS_Data_Local")
PROJECT_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "raw_watchlists"
MACRO_DIR = BASE_DIR / "macro_barometer"
SANITIZED_DIR = PROJECT_DIR / "data" / "sanitized_watchlists"
PROCESSED_DIR = PROJECT_DIR / "data" / "processed_watchlists"
DATABASE_PATH = PROJECT_DIR / "data" / "quant_terminal.db"

# Ensure workspace runtime folders are present
INPUT_DIR.mkdir(parents=True, exist_ok=True)
SANITIZED_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

def get_latest_date_from_files() -> str:
    """Scans raw folder for files containing YYYY-MM-DD pattern and returns the newest date."""
    if not INPUT_DIR.exists():
        raise FileNotFoundError(f"❌ Input folder does not exist at path: {INPUT_DIR}")
        
    files = [f for f in os.listdir(INPUT_DIR) if os.path.isfile(INPUT_DIR / f)]
    print(f"🔎 Scanning raw directory: found {len(files)} total files.")
    
    dates = []
    for f in files:
        match = re.search(r"(\d{4}-\d{2}-\d{2})", f)
        if match:
            dates.append(match.group(1))

    if not dates:
        raise FileNotFoundError(f"❌ No valid dated files found in raw folder matching YYYY-MM-DD: {INPUT_DIR}")

    latest_date = sorted(dates)[-1]
    print(f"📅 Auto-Detected Latest Target Date Context: {latest_date}")
    return latest_date


WATCHLIST_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[-_]watchlist[-_](?P<key>[A-Za-z0-9][A-Za-z0-9_-]*?)(?:_SANITIZED(?:-options)?)?\.csv$",
    re.IGNORECASE,
)


def watchlist_metadata(file_path: Path) -> tuple[str, str] | None:
    match = WATCHLIST_PATTERN.fullmatch(file_path.name)
    if not match:
        return None
    return match.group("date"), match.group("key").lower().replace("allposition", "allpos")


def get_keyed_watchlist_files(target_date: str) -> list[Path]:
    return sorted(
        path for path in INPUT_DIR.iterdir()
        if path.is_file()
        and (metadata := watchlist_metadata(path))
        and metadata[0] == target_date
    )


def parse_generic_telemetry_symbols() -> list:
    """🎯 SYNCHRONIZED MATRIX PARSER CORE: Crawls telemetry_list.txt configuration,
    extracting index tokens and multi-line vertical single-column symbols ([ALPHA_SINGLES]) 
    into a single unified flat row array for yfinance synthetic table processing."""
    config_path = PROJECT_DIR / "data" / "telemetry_list.txt"
    if not config_path.exists():
        config_path = MACRO_DIR / "telemetry_list.txt"
    flat_symbols_pool = []
    current_section = None
    
    if not config_path.exists():
        print(f"   ⚠️ Ingestion Failure: Missing config file target at {config_path}")
        return flat_symbols_pool

    with open(config_path, 'r', encoding='utf-8') as f:
        for line in f:
            line_str = line.strip()
            # Safely bypass empty rows or commented script blocks
            if not line_str or line_str.startswith('#'):
                continue
                
            # Track active configuration structural header zones
            if line_str == "[INDEX_PAIRS]":
                current_section = "INDEX"
                continue
            elif line_str == "[ALPHA_SINGLES]":
                current_section = "ALPHA"
                continue
            elif line_str == "[POSITIONS]":
                current_section = "POSITIONS"
                continue
                
            # Tokenize on commas to seamlessly blend flat string lines and newlines together
            tokens = [t.strip().upper() for t in line_str.split(',') if t.strip()]
            for token in tokens:
                token_clean = token.replace('"', '').replace("'", "").strip()
                if token_clean and token_clean not in flat_symbols_pool:
                    flat_symbols_pool.append(token_clean)
                    
    return flat_symbols_pool


def get_local_cached_data(symbols: list[str]) -> dict[str, dict]:
    """Return latest locally stored values for offline generic generation."""
    if not DATABASE_PATH.exists():
        return {}
    store = LocalDataStore(DATABASE_PATH)
    cached = {}
    try:
        for symbol in symbols:
            lookup_key = translate_tos_symbol(symbol)
            rows = store.market_bars(lookup_key) or store.market_bars(symbol)
            if rows:
                latest = rows[-1]
                snapshot = store.get_fundamental_snapshot(symbol, 36500) or {}
                cached[symbol] = {
                    "Last": latest[4] or "",
                    "Volume": latest[6] or 0,
                    "PE": snapshot.get("PE_Ratio", ""),
                    "Yield": snapshot.get("Yield", ""),
                }
                cached[lookup_key] = cached[symbol]
    finally:
        store.close()
    return cached

"""
QUANT TERMINAL - Step 1: Integrated Watchlist Ingestion & Option Stripper Engine
Block 3 of 5: Tabular Anchor Scanners, Option Symbol Parsers, and Ticker Validation Gates.
"""

def locate_data_start(file_path: Path) -> int:
    """Precision scanner that anchors onto the true tabular header line via specific TOS layout keys."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for idx, line in enumerate(f):
            fields = [field.strip().strip('"').strip("'").lower() for field in line.split(",")]
            if any(f in fields for f in ["symbol", "ticker", "mark % of pos", "p/l open", "obv5"]):
                return idx
    return 0


def parse_option_symbol(symbol: str) -> tuple:
    """Parses a TOS option string into a tuple of (Is_Option, Parent_Stock)."""
    sym_str = str(symbol).strip()
    if sym_str.startswith("."):
        match = re.match(r"^\.([A-Za-z]+)\d{6}", sym_str)
        if match:
            return True, match.group(1).upper()
        return True, "UNKNOWN"
    return False, sym_str.upper()


def is_valid_ticker(symbol: str) -> bool:
    """Validates that a string is strictly a tradeable underlying asset ticker symbol."""
    ignored_headers = {
        "VOLUME", "VALUE", "RATIO", "SIZE", "BID", "ASK", "LAST", "OPEN", "DELTA", "MARK",
        "DAY", "QTY", "LIQ", "DAYS", "YIELD", "PE", "WATCHLIST", "CALL", "OPT", "SYMBOL"
    }
    cleaned = str(symbol).strip().upper()
    if cleaned in ignored_headers or len(cleaned) < 1 or len(cleaned) > 5:
        return False
    return bool(re.match(r"^[A-Z0-9\.\=\^]{1,7}$", cleaned))
"""
QUANT TERMINAL - Step 1: Integrated Watchlist Ingestion & Option Stripper Engine
Block 4 of 5: yfinance Time-Series Handlers and Corporate Fundamental Ingestion Pass.
🎯 DUAL-MULTIPLICATION BUG FIX: Corrects the dividend yield percentage string tracking.
"""

def translate_tos_symbol(sym):
    """Maps Thinkorswim system notation futures seamlessly into ETF anchors."""
    clean_sym = str(sym).strip().upper()
    if clean_sym.startswith('/'):
        clean_sym = clean_sym[1:]
    
    mapping = {
        'ES': 'SPY', 'NQ': 'QQQ', 'YM': 'DIA', 'RTY': 'IWM', 
        'GC': 'GLD', 'SI': 'SLV', 'BZ': 'BNO', 'NG': 'UNG',
        'ZT': 'SHY', 'ZB': 'TLT', 'ZN': 'IEF', 'ZF': 'IEI'
    }
    return mapping.get(clean_sym, clean_sym)

def fetch_yfinance_underlying_data(tickers: list, target_date_str: str) -> dict:
    """Fetches pricing and basic fundamental metrics for missing/flatlined symbols via yfinance."""
    translated_tickers = [translate_tos_symbol(t) for t in tickers]
    valid_tickers = [t for t in translated_tickers if is_valid_ticker(t)]
    ticker_data = {}
    if not valid_tickers:
        return ticker_data
        
    print(f"🌐 Fetching market metrics for {len(valid_tickers)} symbols via yfinance...")
    try:
        target_dt = datetime.strptime(target_date_str, "%Y-%m-%d")
        start_date = (target_dt - timedelta(days=6)).strftime("%Y-%m-%d")
        end_date = (target_dt + timedelta(days=3)).strftime("%Y-%m-%d")
    except Exception:
        start_date, end_date = None, None

    try:
        if start_date and end_date:
            df_download = yf.download(valid_tickers, start=start_date, end=end_date, group_by="ticker", progress=False)
        else:
            df_download = yf.download(valid_tickers, period="5d", group_by="ticker", progress=False)
            
        for ticker in valid_tickers:
            try:
                if isinstance(df_download.columns, pd.MultiIndex):
                    if ticker in df_download.columns.levels:
                        ticker_df = df_download[ticker].dropna(subset=["Close"])
                    else: continue
                else:
                    ticker_df = df_download.dropna(subset=["Close"]) if len(valid_tickers) == 1 else pd.DataFrame()
                
                if not ticker_df.empty:
                    latest_row = ticker_df.iloc[-1]
                    ticker_data[ticker] = {"Last": float(latest_row.get("Close", 0.0)), "Volume": int(latest_row.get("Volume", 0)), "PE": "", "Yield": ""}
            except Exception: pass
    except Exception as e:
        print(f"⚠️ Global yfinance download batch note: {e}")

    for ticker in valid_tickers:
        clean_t = ticker.replace("SPCX", "^SPX")
        if ticker not in ticker_data or ticker_data[ticker]["Last"] == 0:
            try:
                t_obj = yf.Ticker(clean_t)
                hist = t_obj.history(period="3d")
                if not hist.empty:
                    latest_row = hist.iloc[-1]
                    ticker_data[ticker] = {"Last": float(latest_row.get("Close", 0.0)), "Volume": int(latest_row.get("Volume", 0)), "PE": "", "Yield": ""}
            except Exception: pass

        if ticker in ticker_data and ticker_data[ticker]["Last"] > 0:
            try:
                t_obj = yf.Ticker(clean_t)
                t_info = t_obj.info
                pe_val = t_info.get("trailingPE", t_info.get("forwardPE", ""))
                if pe_val: ticker_data[ticker]["PE"] = round(float(pe_val), 2)
                yield_val = t_info.get("dividendYield", "")
                
                # 🎯 PERMANENT BUG FIX LOCK: Strips the manual * 100 multiplier to align database metrics
                if yield_val: ticker_data[ticker]["Yield"] = f"{round(float(yield_val), 2)}%"
            except Exception: pass
        
    return ticker_data
"""
QUANT TERMINAL - Step 1: Integrated Watchlist Ingestion & Option Stripper Engine
Block 5 of 5: Synthetic Generic Watchlist Template Writers, Native Sanitizers, and Central Loops.
"""

def generate_synthetic_generic_watchlist(target_date_str: str):
    """Generates an explicit synthetic watchlist from telemetry configurations matching TOS formats."""
    print("🛠️ Launching On-Demand Synthetic Generic Watchlist Builder Engine...")
    symbols = parse_generic_telemetry_symbols()
    if not symbols:
        print("   ⚠️ Generation Halt: No valid symbols extracted from config parameters.")
        return
        
    market_db = get_local_cached_data(symbols) if OFFLINE else fetch_yfinance_underlying_data(symbols, target_date_str)
    if OFFLINE:
        print(f"🔌 Offline mode: using local cached data for {len(set(symbols) & set(market_db))}/{len(symbols)} telemetry symbols.")
    synthetic_rows = []
    
    for orig_sym in symbols:
        lookup_key = translate_tos_symbol(orig_sym)
        m_data = market_db.get(lookup_key, {"Last": "", "Volume": "", "PE": "", "Yield": ""})
        
        row_template = {
            "Symbol": orig_sym.upper(), "Source_Watchlists": "generic", "Last": m_data["Last"], "Delta": 1, "Mark % of Pos": "()", "%Change": "()",
            "Volume": m_data["Volume"], "Open.Int": 0, "Size": "0 x 0", "PE": m_data["PE"], "Yield": m_data["Yield"],
            "P/C Ratio": 0.0, "Bid": m_data["Last"], "Ask": m_data["Last"], "P/L Open": "()", "P/L %": "()",
            "P/L Day": "()", "Net Liq": "()", "Days": ""
        }
        synthetic_rows.append(row_template)
        
    if synthetic_rows:
        synthetic_df = pd.DataFrame(synthetic_rows)
        for col in ["Last", "Bid", "Ask"]:
            synthetic_df[col] = pd.to_numeric(synthetic_df[col], errors='coerce').fillna(0.0)
        if "Volume" in synthetic_df.columns:
            synthetic_df["Volume"] = synthetic_df["Volume"].apply(lambda x: f"{int(x):,}" if pd.notna(x) and str(x).replace('.0','').isdigit() and int(x) > 0 else "0")
            
        out_name = f"{target_date_str}-watchlist-generic_SANITIZED.csv"
        try:
            synthetic_df.to_csv(SANITIZED_DIR / out_name, index=False, encoding="utf-8-sig")
        except PermissionError:
            print(f"⚠️ Generic output is locked by another application: {SANITIZED_DIR / out_name}")
            print("   Close the existing CSV in Excel or another viewer, then rerun the processor.")
            return
        print("\n" + "=" * 75)
        print(f"🏆 SUCCESS: Synthetic Generic Watchlist Compiled Natively -> {out_name}")
        print(f"📊 Active Tracking Universe: {len(synthetic_df)} Asset Rows Structurally Formatted")
        print("=" * 75 + "\n")

def process_and_export_matrix(file_path: Path, target_date_str: str):
    """Loads raw file, fixes zero-flatlines, generates clean stock-only, and combined sheets."""
    skip_rows = locate_data_start(file_path)
    df = pd.read_csv(file_path, skiprows=skip_rows, encoding="utf-8", on_bad_lines="skip")
    df.columns = [str(c).strip() for c in df.columns]
    if "Symbol" not in df.columns:
        if "SYMBOL" in df.columns: df.rename(columns={"SYMBOL": "Symbol"}, inplace=True)
        else: return

    df = df[df["Symbol"].dropna().astype(str).str.strip().str.lower() != "symbol"].copy()
    rename_map = {"Bid.Size": "Bid Size", "Ask.Size": "Ask Size", "P/C.Ratio": "P/C Ratio", "PC Ratio": "P/C Ratio", "Open.Int": "Open.Int", "Open Interest": "Open.Int", "Pos Qty": "Pos Qty", "Qty": "Pos Qty", "pos qty": "Pos Qty"}
    df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns}, inplace=True)

    metadata = watchlist_metadata(file_path)
    if metadata is None:
        raise ValueError(f"Unsupported keyed watchlist filename: {file_path.name}")
    _, watchlist_key = metadata
    core_columns = ["Symbol", "Source_Watchlists", "Last", "Delta", "Mark % of Pos", "Qty", "%Change", "Volume", "Open.Int", "Size", "PE", "Yield", "P/C Ratio", "Bid", "Ask", "P/L Open", "P/L %", "P/L Day", "Net Liq", "Days"]
    for col in core_columns:
        if col not in df.columns: df[col] = ""
    df["Source_Watchlists"] = watchlist_key

    sensitive_columns = ["Pos Qty", "Qty", "Pos Qty Qty", "%Change", "P/L Open", "P/L %", "P/L Day", "Net Liq", "Mark % of Pos"]
    df_options_only = df[df["Symbol"].astype(str).str.strip().str.startswith(".")].copy()
    df_stocks_only = df[~df["Symbol"].astype(str).str.strip().str.startswith(".")].copy()

    observed_parent_stocks = set()
    for _, row in df_options_only.iterrows():
        symbol_val = str(row["Symbol"]).strip()
        is_option, parent_ticker = parse_option_symbol(symbol_val)
        if is_option and parent_ticker != "UNKNOWN" and is_valid_ticker(parent_ticker): observed_parent_stocks.add(parent_ticker)

    stocks_needing_patch = []
    for idx, row in df_stocks_only.iterrows():
        sym = str(row["Symbol"]).strip()
        last_raw = re.sub(r'[^\d\.]', '', str(row.get("Last", ""))).strip()
        vol_raw = re.sub(r'[^\d]', '', str(row.get("Volume", ""))).strip()
        if (last_raw in ["", "0", "0.0", "0.00"] or vol_raw in ["", "0"]) and is_valid_ticker(sym): stocks_needing_patch.append(sym)
            
    existing_symbols = set(df_stocks_only["Symbol"].dropna().astype(str).str.strip().tolist())
    for s in observed_parent_stocks:
        if s not in existing_symbols: stocks_needing_patch.append(s)
            
    stocks_needing_patch = list(set(stocks_needing_patch))
    if stocks_needing_patch and not OFFLINE:
        synthetic_data_map = fetch_yfinance_underlying_data(stocks_needing_patch, target_date_str)
    else:
        synthetic_data_map = {}
        if stocks_needing_patch and OFFLINE:
            print(f"🔌 Offline mode: leaving {len(stocks_needing_patch)} missing enrichment values unchanged.")
        for idx, row in df_stocks_only.iterrows():
            sym = str(row["Symbol"]).strip()
            lookup_key = translate_tos_symbol(sym)
            if lookup_key in synthetic_data_map:
                last_raw = re.sub(r'[^\d\.]', '', str(row.get("Last", ""))).strip()
                vol_raw = re.sub(r'[^\d]', '', str(row.get("Volume", ""))).strip()
                if last_raw in ["", "0", "0.0", "0.00"] or vol_raw in ["", "0"]:
                    yf_m = synthetic_data_map[lookup_key]
                    df_stocks_only.at[idx, "Last"] = yf_m["Last"]; df_stocks_only.at[idx, "Volume"] = yf_m["Volume"]; df_stocks_only.at[idx, "Bid"] = yf_m["Last"]; df_stocks_only.at[idx, "Ask"] = yf_m["Last"]; df_stocks_only.at[idx, "PE"] = yf_m["PE"]; df_stocks_only.at[idx, "Yield"] = yf_m["Yield"]; df_stocks_only.at[idx, "Delta"] = 1

        all_current_symbols = set(df_stocks_only["Symbol"].dropna().astype(str).str.strip().tolist())
        missing_structural_stocks = [s for s in stocks_needing_patch if s not in all_current_symbols]
        synthetic_rows = []
        for stock in missing_structural_stocks:
            synthetic_row = {col: "" for col in df.columns}
            lookup_key = translate_tos_symbol(stock)
            yf_metrics = synthetic_data_map.get(lookup_key, {"Last": 0.0, "Volume": 0, "PE": "", "Yield": ""})
            synthetic_row["Symbol"] = stock; synthetic_row["Last"] = yf_metrics["Last"]; synthetic_row["Volume"] = yf_metrics["Volume"]; synthetic_row["Bid"] = yf_metrics["Last"]; synthetic_row["Ask"] = yf_metrics["Last"]; synthetic_row["PE"] = yf_metrics["PE"]; synthetic_row["Yield"] = yf_metrics["Yield"]; synthetic_row["Delta"] = 1
            for col in df.columns:
                if col not in ["Symbol", "Last", "Volume", "Bid", "Ask", "PE", "Yield", "Delta"]: synthetic_row[col] = ""
            synthetic_rows.append(synthetic_row)
        if synthetic_rows: df_stocks_only = pd.concat([pd.DataFrame(synthetic_rows), df_stocks_only], ignore_index=True)

    for col in ["Last", "Volume", "Bid", "Ask"]:
        if col in df_stocks_only.columns: df_stocks_only[col] = pd.to_numeric(df_stocks_only[col].astype(str).str.replace(r'[^\d\.]', '', regex=True), errors='coerce').fillna(0.0)
    if "Volume" in df_stocks_only.columns:
        df_stocks_only["Volume"] = df_stocks_only["Volume"].apply(lambda x: f"{int(x):,}" if pd.notna(x) and str(x).replace('.0','').isdigit() and int(x) > 0 else x)

    df_combined_options = pd.concat([df_stocks_only, df_options_only], ignore_index=True)
    df_stocks_only["Source_Watchlists"] = watchlist_key
    df_combined_options["Source_Watchlists"] = watchlist_key
    for col in df_stocks_only.columns:
        if col in sensitive_columns or any(s in col.lower() for s in ["p/l", "liq", "position"]): df_stocks_only[col] = "()"
    for col in df_combined_options.columns:
        if col in sensitive_columns or any(s in col.lower() for s in ["p/l", "liq", "position"]): df_combined_options[col] = "()"

    df_stocks_only = df_stocks_only[[c for c in core_columns if c in df_stocks_only.columns]]
    df_combined_options = df_combined_options[[c for c in core_columns if c in df_combined_options.columns]]
    base_stem = file_path.stem
    df_stocks_only.to_csv(SANITIZED_DIR / f"{base_stem}_SANITIZED.csv", index=False)
    print(f"   ✨ Success: Cleaned desktop data ledger sheet -> {base_stem}_SANITIZED.csv")
    if not df_options_only.empty: df_combined_options.to_csv(SANITIZED_DIR / f"{base_stem}_SANITIZED-options.csv", index=False)

def main():
    print("========================================================")
    print("📡 RUNNING WORKSPACE STEP 1 INGESTION ENGINE INITIALIZER")
    print(f"🎯 Selected Processing Ingestion Mode Type: [{INPUT_MODE.upper()}]")
    print("========================================================\n")
    if INPUT_MODE in {"generic", "all"}:
        current_date_str = datetime.now().strftime("%Y-%m-%d")
        if INPUT_MODE == "generic":
            generate_synthetic_generic_watchlist(current_date_str)

    if INPUT_MODE in {"native", "all"}:
        try:
            raw_candidates = get_keyed_watchlist_files(max(
                (metadata[0] for path in INPUT_DIR.iterdir() if (metadata := watchlist_metadata(path))),
                default="",
            )) if INPUT_DIR.exists() else []
            matching_files = [path for path in raw_candidates if not path.stem.lower().endswith("_sanitized")]
            if matching_files:
                for file_path in matching_files:
                    print(f"🚀 Ingesting Watchlist Dataset: {file_path.name}")
                    process_and_export_matrix(file_path, watchlist_metadata(file_path)[0])
            elif INPUT_MODE == "native":
                print("🛰️ No raw keyed watchlists found; native mode has nothing to process.")
        except Exception as err:
            print(f"❌ Native script tracking halt error: {err}"); sys.exit(1)

    if INPUT_MODE == "all":
        telemetry_date = datetime.now().strftime("%Y-%m-%d")
        print(f"🛰️ Generic telemetry output date: {telemetry_date} (processor run date).")
        generate_synthetic_generic_watchlist(telemetry_date)
    print("\n💾 Step 1 pipeline processing complete. Clean files written to sanitized_watchlists.")

if __name__ == "__main__":
    try: main()
    except Exception as e:
        print("\n💥 CRITICAL TERMINAL CRASH CAPTURED:"); traceback.print_exc(); sys.exit(1)

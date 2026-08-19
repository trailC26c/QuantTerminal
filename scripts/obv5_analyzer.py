"""
QUANT TERMINAL - Step 3: Decoupled Multi-Regime OBV Indicator Matrix (Part 1/3)
Configures pathing architectures, cross-asset dictionaries, and adaptive weekly anchor breakout scorers.
Upgraded with an extended lookback boundary to capture recent signals within a 5-day trading window.
"""

import os
import pandas as pd
import numpy as np
import yfinance as yf
import glob
import re
import logging

# SILENCE CORE ACTION: Stop yfinance internal warnings from polluting the terminal prompt screen
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

# 📌 Directory Realignment: Updated to your new QuanTerminal pipeline structure
PROCESSED_DIR = r"C:\Users\tcnet\TOS_Data_Local\sanitized_watchlists"
OUTPUT_DIR = r"C:\Users\tcnet\TOS_Data_Local\obv5_matrix"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# 📐 PARAMETER REALIGNMENT: Macro periods (P1-P4) decoupled from the Short-Term proxy (P5)
P1, P2, P3, P4 = 360, 270, 180, 90
P5 = 50

# 📅 ADAPTIVE MATRIX UPGRADE: Expanded to 5 days to cover a full weekly execution window
TOLERANCE = 5

MACRO_MAP = {
    "/ES": "ES=F", "ES": "ES=F", "/NQ": "NQ=F", "NQ": "NQ=F",
    "/YM": "YM=F", "YM": "YM=F", "/VX": "^VIX", "VX": "^VIX", 
    "VIX": "^VIX", "/VVIX": "^VVIX", "VVIX": "^VVIX"
}

def clean_futures_ticker(ticker_str):
    """Scans and converts any complex month/year futures contract string to its Yahoo equivalent."""
    ticker_str = str(ticker_str).strip().upper()
    
    if ticker_str in MACRO_MAP:
        return MACRO_MAP[ticker_str]
        
    futures_match = re.match(r"^/?(ES|NQ|YM|VX|VVIX)[A-Z]\d{2}$", ticker_str)
    if futures_match:
        base = futures_match.group(1)
        if base == "VX": return "^VIX"
        if base == "VVIX": return "^VVIX"
        return f"{base}=F" 
        
    return ticker_str

def parse_parent_ticker(option_symbol):
    """Extracts the underlying parent stock ticker from a TOS options string."""
    clean_sym = str(option_symbol).strip().upper().lstrip('.')
    match = re.match(r"^([A-Za-z]+)\d{6}", clean_sym)
    if match:
        return match.group(1)
    return clean_sym

def calculate_obv_regimes(df_hist):
    """Computes decoupled macro (OBV4) and short-term (OBV50) metrics using unadjusted closing prints to match TOS."""
    total_bars = len(df_hist)
    if total_bars < 50:
        return 0.0, "Data_Insufficient", 0.0, "Data_Insufficient"

    # Standardize column headers to enforce clean tracking references
    df_hist.columns = [str(c).strip().capitalize() for c in df_hist.columns]
    
    # Prioritize standard unadjusted close prints to prevent dividend warping on blue-chips
    if 'Close' in df_hist.columns:
        close_series = df_hist['Close']
    elif 'Adj close' in df_hist.columns:
        close_series = df_hist['Adj close']
    elif 'Adj_close' in df_hist.columns:
        close_series = df_hist['Adj_close']
    else:
        close_series = df_hist.iloc[:, 0]
        
    volume = df_hist['Volume']
    close_diff = close_series.diff()
    
    df_hist['OBV'] = np.where(close_diff > 0, volume, np.where(close_diff < 0, -volume, 0)).cumsum()
    df_hist = df_hist.reset_index(drop=True)

    macro_periods = [P1, P2, P3, P4]
    last_idx = total_bars - 1
    
    # ----------------------------------------------------
    # PHASE A: COMPUTE MACRO REGIME (OBV4)
    # ----------------------------------------------------
    max_hits_4 = {p: False for p in macro_periods}
    min_hits_4 = {p: False for p in macro_periods}
    
    for p in macro_periods:
        actual_p = min(p, total_bars)
        if actual_p < 2: continue
        start_idx = max(0, total_bars - actual_p)
        window_df = df_hist.iloc[start_idx:total_bars]
        
        max_val = window_df['OBV'].max()
        min_val = window_df['OBV'].min()
        
        max_pos = window_df[window_df['OBV'] == max_val].index.tolist()
        min_pos = window_df[window_df['OBV'] == min_val].index.tolist()
        
        if max_pos and (last_idx - max_pos[-1]) < TOLERANCE: max_hits_4[p] = True
        if min_pos and (last_idx - min_pos[-1]) < TOLERANCE: min_hits_4[p] = True

    total_max_4 = sum(1 for p in macro_periods if max_hits_4[p])
    total_min_4 = sum(1 for p in macro_periods if min_hits_4[p])
    
    triggered_4 = []
    if total_min_4 >= total_max_4 and total_min_4 > 0:
        for p in macro_periods:
            if min_hits_4[p]: triggered_4.append(f"{p}(Capped_{total_bars}B)" if p > total_bars else str(p))
        obv4_score, obv4_str = float(-total_min_4), "|".join(triggered_4)
    elif total_max_4 > total_min_4 and total_max_4 > 0:
        for p in macro_periods:
            if max_hits_4[p]: triggered_4.append(f"{p}(Capped_{total_bars}B)" if p > total_bars else str(p))
        obv4_score, obv4_str = float(total_max_4), "|".join(triggered_4)
    else:
        obv4_score, obv4_str = 0.0, "None"

    # ----------------------------------------------------
    # PHASE B: COMPUTE SHORT-TERM REGIME (OBV50)
    # ----------------------------------------------------
    start_idx_50 = max(0, total_bars - P5)
    window_50 = df_hist.iloc[start_idx_50:total_bars]
    
    max_50 = window_50['OBV'].max()
    min_50 = window_50['OBV'].min()
    
    max_pos_50 = window_50[window_50['OBV'] == max_50].index.tolist()
    min_pos_50 = window_50[window_50['OBV'] == min_50].index.tolist()
    
    hit_max_50 = max_pos_50 and (last_idx - max_pos_50[-1]) < TOLERANCE
    hit_min_50 = min_pos_50 and (last_idx - min_pos_50[-1]) < TOLERANCE
    
    if hit_min_50 and not hit_max_50:
        obv50_score, obv50_str = -1.0, "50"
    elif hit_max_50 and not hit_min_50:
        obv50_score, obv50_str = 1.0, "50"
    elif hit_max_50 and hit_min_50:
        obv50_score, obv50_str = 0.0, "Dual_Extreme_Conflict"
    else:
        obv50_score, obv50_str = 0.0, "None"

    return obv4_score, obv4_str, obv50_score, obv50_str

"""
QUANT TERMINAL - Step 3: Decoupled Multi-Regime OBV Indicator Matrix (Part 2/3)
Ingests all watchlists contextually, strips option roots, and streams matching core assets.
"""

def execute_obv5_pipeline():
    print("========================================================")
    print("🔬 [STEP MODULE 3] Initializing Decoupled Multi-Regime OBV Inverted Filtration...")
    print("========================================================")
    
    all_files = glob.glob(os.path.join(PROCESSED_DIR, "*.csv"))
    if not all_files:
        print(f"⚠️ Notice: No active processed CSV watchlists detected inside {PROCESSED_DIR}.")
        print("   Skipping OBV filtration loops.")
        return

    all_dates = []
    for f in all_files:
        match = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(f))
        if match:
            all_dates.append(match.group(1))
            
    if not all_dates:
        print("⚠️ Notice: No files containing a standard YYYY-MM-DD date stamp were found.")
        print("   Processing all available CSV files as fallback.")
        matrix_files = all_files
    else:
        latest_date = max(all_dates)
        print(f"📅 Isolated Newest Active Session Cluster: {latest_date}")
        
        raw_matches = [f for f in all_files if latest_date in os.path.basename(f) and "_SANITIZED" in os.path.basename(f)]
        matrix_files = [f for f in raw_matches if "-options" not in os.path.basename(f)]
        print(f"📡 Synchronizing pointers onto {len(matrix_files)} matching files.")
    
    for file_path in matrix_files:
        base_name = os.path.basename(file_path).replace('.csv', '')
        print(f"\n🌊 Extracting unique underlying symbols for download: {base_name}.csv")
        
        try:
            df = pd.read_csv(file_path)
        except Exception as e:
            print(f"❌ Failed to read {base_name}.csv: {str(e)}")
            continue

        if df.empty or 'Symbol' not in df.columns:
            print(f"⚠️ Skipping {base_name}.csv: empty data or missing 'Symbol' tracking column.")
            continue
            
        ticker_mapping = {}  
        unique_yf_tickers = set()
        
        for idx, row in df.iterrows():
            ticker = str(row['Symbol']).strip()
            if not ticker or ticker.lower() in ['symbol', 'nan', '()']:
                continue
            
            target_ticker = parse_parent_ticker(ticker)
            if not target_ticker:
                continue
                
            yf_ticker = clean_futures_ticker(target_ticker)
            ticker_mapping[ticker] = (target_ticker, yf_ticker)
            unique_yf_tickers.add(yf_ticker)

        print(f"📥 Launching parallel network download for {len(unique_yf_tickers)} underlying charts...")
        bulk_data = {}
        if unique_yf_tickers:
            try:
                bulk_df = yf.download(list(unique_yf_tickers), period="2y", interval="1d", group_by='ticker', timeout=15, progress=False)
                
                if isinstance(bulk_df.columns, pd.MultiIndex):
                    downloaded_tickers = bulk_df.columns.get_level_values(0).unique()
                    for yf_tick in unique_yf_tickers:
                        if yf_tick in downloaded_tickers:
                            try:
                                tick_df = bulk_df[yf_tick].copy()
                                if tick_df.empty or tick_df.isna().all().all():
                                    continue
                                tick_df.columns = [str(c).capitalize() for c in tick_df.columns]
                                bulk_data[yf_tick] = tick_df
                            except KeyError:
                                continue
                else:
                    if not bulk_df.empty:
                        single_df = bulk_df.copy()
                        single_df.columns = [str(c).capitalize() for c in single_df.columns]
                        for yf_tick in unique_yf_tickers:
                            bulk_data[yf_tick] = single_df
                            
            except Exception as e:
                print(f"❌ Bulk download network failure: {str(e)}. Falling back to isolated verification loops.")
        """
        QUANT TERMINAL - Step 3: Integrated 5-Period OBV Indicator Matrix (Part 3/3)
        Calculates indicator vectors out of memory, handles sorting cascades, and appends the exact target file padding format token string.
        """

        print(f"📊 Calculating matrix indicators locally out of memory...")
        df['obv4_Score'] = 0.0
        df['obv4_Trigger_Periods'] = "Pending_Calculation"
        df['obv50_Score'] = 0.0
        df['obv50_Trigger_Periods'] = "Pending_Calculation"
        
        processed_count = 0
        chart_cache = {} 
        
        for idx, row in df.iterrows():
            ticker = str(row['Symbol']).strip()
            
            if ticker.startswith("."):
                df.at[idx, 'obv4_Score'] = 0.0
                df.at[idx, 'obv4_Trigger_Periods'] = "Option_Row_Skipped"
                df.at[idx, 'obv50_Score'] = 0.0
                df.at[idx, 'obv50_Trigger_Periods'] = "Option_Row_Skipped"
                continue
                
            if ticker not in ticker_mapping:
                df.at[idx, 'obv4_Trigger_Periods'] = "Mapping_Invalid"
                df.at[idx, 'obv50_Trigger_Periods'] = "Mapping_Invalid"
                continue
                
            target_ticker, yf_ticker = ticker_mapping[ticker]
            
            if target_ticker in chart_cache:
                score4, str4, score50, str50 = chart_cache[target_ticker]
                df.at[idx, 'obv4_Score'] = score4
                df.at[idx, 'obv4_Trigger_Periods'] = str4
                df.at[idx, 'obv50_Score'] = score50
                df.at[idx, 'obv50_Trigger_Periods'] = str50
                processed_count += 1
                continue
                
            hist = bulk_data.get(yf_ticker, pd.DataFrame())
            
            if hist.empty or 'Close' not in hist.columns:
                try:
                    fallback_ticker = yf.Ticker(yf_ticker)
                    hist = fallback_ticker.history(period="2y", interval="1d")
                    if not hist.empty:
                        hist.columns = [str(c).capitalize() for c in hist.columns]
                except Exception:
                    hist = pd.DataFrame()
            
            if not hist.empty and 'Close' in hist.columns:
                total_bars = len(hist)
                if total_bars >= 50:
                    s4, txt4, s50, txt50 = calculate_obv_regimes(hist.copy())
                    df.at[idx, 'obv4_Score'] = s4
                    df.at[idx, 'obv4_Trigger_Periods'] = txt4
                    df.at[idx, 'obv50_Score'] = s50
                    df.at[idx, 'obv50_Trigger_Periods'] = txt50
                    chart_cache[target_ticker] = (s4, txt4, s50, txt50)
                    processed_count += 1
                else:
                    df.at[idx, 'obv4_Score'] = 0.0
                    df.at[idx, 'obv4_Trigger_Periods'] = f"Data_Insufficient_{total_bars}B"
                    df.at[idx, 'obv50_Score'] = 0.0
                    df.at[idx, 'obv50_Trigger_Periods'] = f"Data_Insufficient_{total_bars}B"
                    chart_cache[target_ticker] = (0.0, f"Data_Len_{total_bars}B", 0.0, f"Data_Len_{total_bars}B")
            else:
                df.at[idx, 'obv4_Score'] = 0.0
                df.at[idx, 'obv4_Trigger_Periods'] = "Data_Failed_API_Fetch"
                df.at[idx, 'obv50_Score'] = 0.0
                df.at[idx, 'obv50_Trigger_Periods'] = "Data_Failed_API_Fetch"
                
        for redundant in ['obv5_Score', 'obv5_Trigger_Periods', 'obv5', 'obv4']:
            if redundant in df.columns: df.drop(columns=[redundant], inplace=True)
                
        if 'allopt' in base_name.lower() or 'options' in base_name.lower():
            if 'Size_Imbalance_Ratio' in df.columns:
                df = df.sort_values(by='Size_Imbalance_Ratio', ascending=False)
        else:
            if 'obv4_Score' in df.columns:
                df = df.sort_values(by='obv4_Score', ascending=True)
        
        privacy_indicators = ['name', 'email', 'account', 'client', 'personal']
        portfolio_indicators = ['qty', 'p/l', 'net liq', 'mark %', 'open_int', 'p/c ratio']
        
        found_privacy_cols = [col for col in df.columns if any(ind in col.lower() for ind in privacy_indicators)]
        found_portfolio_cols = [col for col in df.columns if any(ind in col.lower() for ind in portfolio_indicators)]
        
        if not found_privacy_cols:
            privacy_stripped = True
        else:
            privacy_stripped = all(df[col].isna().all() or (df[col].astype(str).str.strip().replace('nan', '') == '').all() for col in found_privacy_cols)
            
        if privacy_stripped:
            print(f"   🔒 Privacy stripping verified. Purging residual raw headers and live account metrics...")
            all_cols_to_clear = found_privacy_cols + found_portfolio_cols
            
            mandatory_keeps = [
                'obv4_Score', 'obv4_Trigger_Periods', 'obv50_Score', 'obv50_Trigger_Periods', 
                'Symbol', 'Volume', 'Close', 'Bid', 'Ask'
            ]
            cols_to_drop = [col for col in all_cols_to_clear if col not in mandatory_keeps]
            if cols_to_drop:
                df.drop(columns=cols_to_drop, inplace=True, errors='ignore')
            
            output_file_path = os.path.join(OUTPUT_DIR, f"{base_name}_OBV5_PROCESSED.csv")
            df.to_csv(output_file_path, index=False)
            print(f"   ↳ Complete. Processed {processed_count}/{len(df)} rows -> saved to {OUTPUT_DIR}")
        else:
            print(f"   ⚠️  CRITICAL ALERT: Active un-sanitized client data values found in {base_name}.csv!")
            print(f"      Skipping file save operation to guarantee terminal privacy compliance.")

    print("\n💾 Decoupled OBV wave isolation sequence complete. Proceeding to Master Leaderboards.")

if __name__ == "__main__":
    execute_obv5_pipeline()

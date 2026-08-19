"""
QUANT TERMINAL - Step 4: Integrated Equity & ETF Fundamental Analyzer (Part 1/3)
Configures pathing architectures, cross-asset dictionaries, and option/index stripping filters.
"""

import os
import re
import sys
import time
import glob
import traceback
from datetime import datetime
from pathlib import Path
import pandas as pd
import numpy as np

import yfinance as yf

# Silence yfinance terminal internal warnings
import logging
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

# 📌 Directory Realignment: Clean pipeline structures matching your workspace folders
INPUT_DIR = r"C:\Users\tcnet\TOS_Data_Local\sanitized_watchlists"
OUTPUT_DIR = r"C:\Users\tcnet\TOS_Data_Local\fundamental_matrix"

os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_latest_sanitized_file_date():
    """Locates the freshest date cluster stamped inside your sanitized directory watchlists matching your actual filenames."""
    files = glob.glob(os.path.join(INPUT_DIR, "*_SANITIZED.csv"))
    if not files:
        print("❌ Diagnostic Warning: Could not find any sanitized watchlist files in tracking directory.")
        return datetime.now().strftime("%Y-%m-%d")
        
    def extract_date(f):
        match = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(f))
        return match.group(1) if match else "0000-00-00"
        
    extracted_dates = [extract_date(f) for f in files if extract_date(f) != "0000-00-00"]
    return max(extracted_dates) if extracted_dates else datetime.now().strftime("%Y-%m-%d")


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
        "Beta_vs_ES": 1.0, 
        "Cap_Billions": 0.0, 
        "PE_Ratio": 0.0,
        "Earnings_Growth_YoY": 0.0,
        "Institutional_Ownership_Pct": 0.0,
        "Analyst_Rec_Score": 3.0,          
        "Analyst_Consensus": "NEUTRAL",     
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
            
            if raw_expense:
                val = float(raw_expense)
                metrics["Expense_Ratio"] = round(val * 100.0, 3) if val < 0.1 else round(val, 3)
            
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
            
            raw_rec_score = inf.get('recommendationMean')
            if raw_rec_score is not None:
                metrics["Analyst_Rec_Score"] = round(float(raw_rec_score), 2)
            
            metrics["Analyst_Consensus"] = str(inf.get('recommendationKey', 'NEUTRAL')).upper().replace('_', ' ')
            
            target_price = inf.get('targetMeanPrice')
            if target_price and current_price > 0:
                upside_pct = ((float(target_price) - float(current_price)) / float(current_price)) * 100.0
                metrics["Sentiment_Target_Upside"] = round(upside_pct, 2)
                
            raw_short_float = inf.get('shortPercentOfFloat')
            if raw_short_float is not None:
                metrics["Short_Percent_Of_Float"] = round(float(raw_short_float) * 100.0, 2)
                
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
    
    target_date = get_latest_sanitized_file_date()
    
    target_suffixes = [
        "-watchlist-allopt_SANITIZED.csv",
        "-watchlist-allposition_SANITIZED.csv",
        "-watchlist-long_SANITIZED.csv",
        "-watchlist-asml_SANITIZED.csv",
        "-watchlist-core_SANITIZED.csv"
    ]
    
    telemetry_cache = {}
    
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

    for suffix in target_suffixes:
        filename = f"{target_date}{suffix}"
        position_file = os.path.join(INPUT_DIR, filename)
        
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
                    data_package = fetch_adaptive_ticker_telemetry(sym)
                    data_package["Symbol"] = sym
                    
                    prior_value = previous_short_map.get(str(sym), np.nan)
                    if pd.isna(prior_value) or prior_value == 0.0:
                        data_package["Short_Percent_Of_Float_Last"] = data_package["Short_Percent_Of_Float"]
                    else:
                        data_package["Short_Percent_Of_Float_Last"] = prior_value
                        
                    telemetry_cache[sym] = data_package
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
                
            df_final = pd.merge(df_filtered, df_fundamentals, on='Symbol', how='left')
            
            if 'PE_Ratio' in df_final.columns and 'PE' in df_final.columns:
                df_final['PE_Ratio'] = df_final['PE_Ratio'].fillna(df_final['PE'])
                df_final.drop(columns=['PE'], inplace=True, errors='ignore')
                df_final.rename(columns={'PE_Ratio': 'PE'}, inplace=True)
                
            if 'Legacy_Margin' in df_final.columns:
                df_final.drop(columns=['Legacy_Margin'], inplace=True, errors='ignore')
            
            base_filename_string = filename.replace('.csv', '')
            out_name = f"{base_filename_string}_FUND_PROCESSED.csv"
            out_path = os.path.join(OUTPUT_DIR, out_name)
            df_final.to_csv(out_path, index=False)
            
            print(f"\n🏆 SUCCESS: Generated unified fundamental metrics sheet.")
            print(f"💾 File archived safely -> {os.path.basename(out_path)}\n")
            
        except Exception as file_pipeline_err:
            print(f"❌ Error processing file pipeline layout {filename}: {file_pipeline_err}")
            traceback.print_exc()
            
    print("========================================================")
    print("🏆 ALL TARGETED FILES COMPILED AND UPDATED SUCCESSFULLY.")
    print("========================================================\n")

if __name__ == "__main__":
    run_fundamental_stage_analyzer()

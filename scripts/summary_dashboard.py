"""
=========================================================================
📡 QUANT TERMINAL: HIGH-VELOCITY SUMMARY COCKPIT GENERATOR
=========================================================================
File Name: summary_dashboard.py
Block 1 of 2: System Environments and Target Ingestion Timeline Scanners.
Standardized to absolute flat 4-space nested indentation frames.
"""

import os
import glob
import re
from datetime import datetime
import pandas as pd

# =========================================================================
# 📂 REPOSITORY TRACKING SPECIFICATIONS
# =========================================================================
BASE_DIR = r"C:\Users\tcnet\TOS_Data_Local"
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST_DIR = os.path.join(PROJECT_DIR, "data", "sanitized_watchlists")
MACRO_DIR = os.path.join(BASE_DIR, "macro_barometer")
INPUT_DIR = os.path.join(BASE_DIR, "master_leaderboard")
OUTPUT_DIR = os.path.join(BASE_DIR, "master_leaderboard")

def get_latest_processed_file_date():
    """Scans the local master leaderboard directory to target the latest file run date."""
    files = glob.glob(os.path.join(INPUT_DIR, "*_COMBINED_LEADERBOARD_PROCESSED.csv"))
    if not files:
        return datetime.now().strftime("%Y-%m-%d")
    dates = []
    for f in files:
        match = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(f))
        if match: dates.append(match.group(1))
    return max(dates) if dates else datetime.now().strftime("%Y-%m-%d")
"""
QUANT TERMINAL - High-Velocity Summary Cockpit Generator
Block 2 of 2: Watchlist Aggregators, Barometer Spring Slicers, and Regime Injectors.
🎯 ZERO RECALCULATION RISK: Operates strictly as a post-processed layout formatter.
"""

def generate_lightweight_summary_cockpit():
    print("========================================================")
    print("📡 INITIALIZING HIGH-VELOCITY OPERATIONAL SUMMARY COCKPIT")
    print("🎯 STRIPPING MASTER LEDGER TO 7 PERFORMANCE PILLARS")
    print("========================================================\n")
    
    latest_date_str = get_latest_processed_file_date()
    combined_filename = f"{latest_date_str}_COMBINED_LEADERBOARD_PROCESSED.csv"
    combined_filepath = os.path.join(INPUT_DIR, combined_filename)
    
    print(f"📡 Locating Consolidated Master Source File: {combined_filename}")
    
    if not os.path.exists(combined_filepath):
        print(f"⚠️ Warning: Target master spreadsheet file not found at {combined_filepath}. Aborting pass.")
        return
        
    try:
        # --- STEP 1: Crawl watchlists dynamically to map cross-watchlist memberships natively ---
        search_pattern = os.path.join(WATCHLIST_DIR, f"*{latest_date_str}*_SANITIZED*.csv")
        raw_files = glob.glob(search_pattern)
        raw_membership_dict = {}
        
        for f in raw_files:
            fname = os.path.basename(f)
            if "-options" in fname.lower() or "_options" in fname.lower():
                continue
            token_match = re.search(r"watchlist-[a-zA-Z0-9_]+", fname.lower())
            if not token_match: continue
            list_label = token_match.group(0).replace("watchlist-", "").replace("_sanitized", "").strip()
            
            try:
                df_raw = pd.read_csv(f, on_bad_lines='skip')
                if 'Symbol' in df_raw.columns:
                    for symbol in df_raw['Symbol'].dropna().unique():
                        sym_clean = str(symbol).strip().upper()
                        if sym_clean not in raw_membership_dict:
                            raw_membership_dict[sym_clean] = []
                        if list_label not in raw_membership_dict[sym_clean]:
                            raw_membership_dict[sym_clean].append(list_label)
            except Exception:
                pass
                
        watchlist_map = {k: f"[{', '.join(v)}]" for k, v in raw_membership_dict.items()}
        
        # --- 🎯 STEP 2: Ingest the pre-calculated dynamic SMA delta percentages from your barometer file ---
        baro_ledger_path = os.path.join(MACRO_DIR, "macro_tension_ledger.csv")
        baro_spring_map = {}
        
        if os.path.exists(baro_ledger_path):
            try:
                df_baro = pd.read_csv(baro_ledger_path)
                if 'Symbol' in df_baro.columns and 'sma_pct' in df_baro.columns:
                    for _, b_row in df_baro.iterrows():
                        b_sym = str(b_row['Symbol']).strip().upper()
                        baro_spring_map[b_sym] = str(b_row['sma_pct']).strip()
            except Exception:
                pass

        # --- STEP 3: Read the finished calculated master sheet directly from disk ---
        df = pd.read_csv(combined_filepath)
        if df.empty:
            print("   ⚠️ Error: Consolidated source file is empty.")
            return
            
        # Isolate strictly your core performance tracking columns
        target_pillars = [
            'Symbol', 
            'Final_Composite_Score', 
            'Source_Watchlist', 
            'Score_SEPA', 
            'Score_OBV5', 
            'Trend_Distance_Pct'
        ]
        
        available_columns = [col for col in target_pillars if col in df.columns]
        summary_df = df[available_columns].copy().astype(str)
        
        # 🎯 STEP 4: Inject the brand-new SMA_Delta_Pct column right next to Trend_Distance_Pct
        sma_delta_values = []
        for idx in summary_df.index:
            sym_token = str(summary_df.loc[idx, 'Symbol']).strip().upper()
            # If the stock has a calculated barometer value, print it; otherwise default to neutral pass
            sma_delta_values.append(baro_spring_map.get(sym_token, "0.0"))
            
        summary_df['SMA_Delta_Pct'] = sma_delta_values
        
        # Map combined cross-watchlist tokens into your Source_Watchlist cells
        for idx in summary_df.index:
            sym = str(summary_df.loc[idx, 'Symbol']).strip().upper()
            if sym in watchlist_map:
                summary_df.loc[idx, 'Source_Watchlist'] = watchlist_map[sym]
                
        # Split your long buys block away from your short sells block based on your original row dividers
        boundary_indices = summary_df[summary_df['Symbol'].str.contains("REGIME BOUNDARY", na=False, case=False)].index
        
        if not boundary_indices.empty:
            b_val = boundary_indices[0]
            buy_block = summary_df.loc[:b_val-1].copy()
            sell_block = summary_df.loc[b_val+1:].copy()
            
            boundary_row = pd.DataFrame([{col: "---" for col in summary_df.columns}])
            boundary_row.loc[0, 'Symbol'] = "=== SHORT / DEFENSIVE EXPOSURE REGIME BOUNDARY ==="
        else:
            buy_block = summary_df.copy()
            sell_block = pd.DataFrame(columns=summary_df.columns)
            boundary_row = pd.DataFrame(columns=summary_df.columns)
            
        long_header_row = pd.DataFrame([{col: "---" for col in summary_df.columns}])
        long_header_row.loc[0, 'Symbol'] = "=== LONG / MOMENTUM ACCUMULATION REGIME ==="
        
        # Assemble the final unified layout cockpit sheet sequentially
        final_cockpit_df = pd.concat([
            long_header_row,
            buy_block,
            boundary_row,
            sell_block
        ], ignore_index=True)
        
        # Ensure optimal column chronology layout sequence
        ordered_cols = ['Symbol', 'Final_Composite_Score', 'Source_Watchlist', 'Score_SEPA', 'Score_OBV5', 'Trend_Distance_Pct', 'SMA_Delta_Pct']
        final_cockpit_df = final_cockpit_df[ordered_cols]
        
        # Step 5: Export your pristine lightweight cockpit table directly to disk
        summary_filename = f"{latest_date_str}_SUMMARY_DASHBOARD.csv"
        summary_filepath = os.path.join(OUTPUT_DIR, summary_filename)
        final_cockpit_df.to_csv(summary_filepath, index=False)
        
        print("\n" + "=" * 75)
        print(f"🏆 SUCCESS: High-Velocity Summary Cockpit Generated -> {summary_filename}")
        print(f"📊 Extracted Rows: {len(final_cockpit_df)} Rows Balanced across 7 Core Pillars")
        print(f"📂 Output Routing: Saved safely in local folder -> {os.path.basename(OUTPUT_DIR)}")
        print("=" * 75 + "\n")
        
    except Exception as err:
        print(f"⚠️ Operational Crash: Failed to generate lightweight summary dashboard: {err}")

if __name__ == "__main__":
    generate_lightweight_summary_cockpit()

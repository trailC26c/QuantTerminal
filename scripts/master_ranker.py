"""
=========================================================================
📡 QUANT TERMINAL: STEP 6 HOOKE'S LAW LEADERBOARD RANKER ENGINE
=========================================================================
File Name: master_ranker.py
Block 1 of 4: CLI Input Options, Component Weights, and Workspace Path Rules.
Standardized to absolute flat 4-space nested indentation frames.
"""

import os
import glob
import re
import argparse
from datetime import datetime
import pandas as pd
import numpy as np

# =========================================================================
# 🎛️ COMMAND LINE INTERFACE (CLI) ARGUMENT WEIGHT CONTROLLER
# =========================================================================
parser = argparse.ArgumentParser(description="QUANT TERMINAL: Step 6 Master Leaderboard Ranker")
parser.add_argument("--w_sepa", type=float, default=1.0, help="Weight modifier for SEPA Trend lifecycle layer")
parser.add_argument("--w_obv5", type=float, default=0.5, help="Weight modifier for Inverted OBV Accumulation Ribbon")
parser.add_argument("--w_fund", type=float, default=1.5, help="Weight modifier for Fundamental Velocity & Scaling")
# 🎯 HOOKE'S LAW PHYSICS ENGINE EXTERNAL CONSTANT MULTIPLIERS
parser.add_argument("--w_macro_vix", type=float, default=1.0, help="Volatility constant vector (w_vix)")
parser.add_argument("--w_macro_uup", type=float, default=0.8, help="Currency constant vector (w_uup)")
parser.add_argument("--w_macro_sam", type=float, default=1.2, help="Spring constant k displacement (w_deltaSAM)")
args, unknown = parser.parse_known_args()

W_SEPA = args.w_sepa
W_OBV5 = args.w_obv5
W_FUND = args.w_fund
W_MVIX = args.w_macro_vix
W_MUUP = args.w_macro_uup
W_MSAM = args.w_macro_sam

# =========================================================================
# 📂 LOCAL WORKSPACE DIRECTORY STRUCTURE & ROUTING SPECIFICATIONS
# =========================================================================
BASE_DIR = r"C:\Users\tcnet\TOS_Data_Local"
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WATCHLIST_DIR = os.path.join(PROJECT_DIR, "data", "sanitized_watchlists")
SEPA_DIR = os.path.join(BASE_DIR, "sepa_matrix")
OBV_DIR = os.path.join(BASE_DIR, "obv5_matrix")
FUND_DIR = os.path.join(BASE_DIR, "fundamental_matrix")
MACRO_DIR = os.path.join(BASE_DIR, "macro_barometer")
OUTPUT_DIR = os.path.join(BASE_DIR, "master_leaderboard")

os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_latest_workspace_file_date():
    """Scans the local sanitized watchlists folder to locate the latest data file timestamp."""
    files = glob.glob(os.path.join(WATCHLIST_DIR, "*_SANITIZED*.csv"))
    if not files:
        return datetime.now().strftime("%Y-%m-%d")
    dates = []
    for f in files:
        match = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(f))
        if match: dates.append(match.group(1))
    return max(dates) if dates else datetime.now().strftime("%Y-%m-%d")
"""
QUANT TERMINAL - Step 6: Master Leaderboard Ranker Matrix Engine
Block 2 of 4: Real-Time Table Ingestors and Cell Text Strippers.
🎯 PHYSICS ENGINE RE-LINK PATCH: Corrects the overlay_score variable mismatch to prevent runtime crashes.
"""

def load_macro_tension_physics_scalars():
    """Ingests pre-calculated percentage positions from the barometer ledger and maps the physics scores."""
    ledger_path = os.path.join(MACRO_DIR, "macro_tension_ledger.csv")
    default_meta = {"vix_score": 0.0, "uup_score": 0.0, "sam_score": 0.0, "overlay_score": 0.0}
    if not os.path.exists(ledger_path):
        return default_meta
    try:
        df = pd.read_csv(ledger_path)
        if df.empty: return default_meta
        
        # 🎯 TARGET INDEX ROW: Extract our unified aggregated 5th row summary matrix explicitly
        consensus_row = df[df['Symbol'] == 'UNIFIED_MACRO_CONSENSUS']
        if consensus_row.empty: return default_meta
        
        # Pull your raw non-biased historic displacement percentages (-100% to +100%) safely
        p_vix = float(consensus_row['vix_pct'].iloc[0])
        p_uup = float(consensus_row['uup_pct'].iloc[0])
        p_sma = float(consensus_row['sma_pct'].iloc[0])
        
        # Scale percentages linearly onto our uniform -5.0 to +5.0 module sub-scores
        s_vix = (p_vix / 100.0) * 5.0
        s_uup = (p_uup / 100.0) * 5.0
        s_sam = (p_sma / 100.0) * 5.0
        
        # 📐 THE SYSTEMIC HOOKE'S LAW BALANCED EQUATION USING RELATIVE CONSTANTS (1.0, 0.8, 1.2)
        weighted_sum = (W_MVIX * s_vix) + (W_MUUP * s_uup) + (W_MSAM * s_sam)
        sum_of_constants = W_MVIX + W_MUUP + W_MSAM
        final_macro_overlay = max(-5.0, min(5.0, weighted_sum / sum_of_constants))
        
        # 🎯 PERMANENT BUG FIX LOCK: Maps the accurate calculated overlay variable cleanly
        return {
            "vix_score": s_vix,
            "uup_score": s_uup,
            "sam_score": s_sam,
            "overlay_score": final_macro_overlay
        }
    except Exception:
        return default_meta

def clean_numeric_cell(val, default=0.0):
    """Safely handles string cleaning for data tables stripping text markers."""
    if pd.isna(val): return default
    val_str = str(val).strip().replace('"', '').replace(',', '').replace('%', '')
    if val_str.lower() == '<empty>' or val_str == '()' or val_str == '':
        return default
    try:
        return float(val_str)
    except ValueError:
        return default
"""
QUANT TERMINAL - Step 6: Master Leaderboard Ranker Matrix Engine
Block 3 of 4: Normalized Component Factor Sub-Modules.
Enforces absolute uniform scaling across all parameters: -5.0 to +5.0 limits.
"""

def calculate_sepa_layer(row):
    """Translates discrete Boolean trend passes into standardized continuous scores."""
    try:
        is_stage2 = str(row.get('SEPA_Stage2_Pass', 'False')).strip().upper() == 'TRUE'
        is_stage3 = str(row.get('Stage3_Distribution_Pass', 'False')).strip().upper() == 'TRUE'
        is_stage4 = str(row.get('Stage4_Short_Reference', 'False')).strip().upper() == 'TRUE'
        is_stage1 = str(row.get('Stage1_Base_Pass', 'False')).strip().upper() == 'TRUE'
    except Exception:
        return 0.0

    if is_stage2: return 5.0   
    elif is_stage3: return 0.0  
    elif is_stage4: return -5.0 
    elif is_stage1: return 3.0   
    return 0.0

def calculate_obv5_layer(row):
    """Executes non-destructive inversion mapping passes on volume ribbon streams."""
    raw_obv4 = clean_numeric_cell(row.get('obv4_Score', 0.0))
    raw_obv50 = clean_numeric_cell(row.get('obv50_Score', 0.0))
    inverted_obv4 = raw_obv4 * -1.0
    inverted_obv50 = raw_obv50 * -1.0
    return max(-5.0, min(5.0, inverted_obv4 + inverted_obv50))

def calculate_fundamental_layer(row):
    """Evaluates institutional liquidity gates, graded ETF net-yield buffers, and revenue metrics."""
    volume = clean_numeric_cell(row.get('Volume', 0.0))
    sector = str(row.get('Sector', 'Equity')).strip().upper()
    symbol = str(row.get('Symbol', '')).strip().upper()
    
    if sector == 'ETF_FUNDS' or symbol in ('SPY', 'QQQ', 'DIA', 'IWM', 'GLD', 'SLV', 'GDX', 'URA'):
        raw_yield = clean_numeric_cell(row.get('Yield', 0.0))
        expense_ratio = clean_numeric_cell(row.get('Expense_Ratio', 0.0))
        net_yield = raw_yield - expense_ratio
        
        if symbol in ('GLD', 'SLV'):
            return 3.5 if expense_ratio <= 0.40 else -3.5
            
        if net_yield > 0.50: return 5.0
        elif net_yield >= 0.10: return 3.5
        elif net_yield >= 0.00: return 1.5
        elif net_yield >= -0.10: return -1.5
        elif net_yield >= -0.50: return -3.5
        else: return -5.0
        
    score = 0.0
    if volume >= 1000000.0: score += 3.0
    elif volume >= 500000.0: score += 1.5
    else: score -= 2.0
    
    earnings_growth = clean_numeric_cell(row.get('Earnings_Growth_YoY', 0.0))
    if earnings_growth >= 40.0: score += 2.0
    elif earnings_growth < 0.0: score -= 3.0
    return max(-5.0, min(5.0, score))

def calculate_mechanical_stretch_layer(row, macro_pct):
    """Tracks price-to-moving average spring stretch fatigue levels using Trend_Distance_Pct."""
    score = 0.0
    pct_to_sma = clean_numeric_cell(row.get('Trend_Distance_Pct', 0.0))
    short_float = clean_numeric_cell(row.get('Short_Percent_Of_Float', 0.0))
    
    if pct_to_sma >= 25.0: score -= 3.0  
    elif pct_to_sma <= 5.0 and pct_to_sma >= 0.0: score += 2.0 
    
    is_stage2 = str(row.get('SEPA_Stage2_Pass', 'False')).strip().upper() == 'TRUE'
    if short_float >= 15.0 and is_stage2: score += 2.0  
    return max(-5.0, min(5.0, score))
"""
QUANT TERMINAL - Step 6: Master Leaderboard Ranker Matrix Engine
Block 4 of 4: Central Pipeline Orchestration and Zero-Calculation Table Merger.
🎯 REAL-TIME INTEGRATION: Infuses physics constants into your scores.
"""

def execute_zero_recalc_combined_merger_pass(latest_date_str):
    """Pure structural text re-organizer joining independent watchlist data rows natively."""
    print("\n🛠️ Executing Pure File Union reorganization pass (Zero Recalculation Layer)...")
    buy_files = glob.glob(os.path.join(OUTPUT_DIR, f"{latest_date_str}_*_BUY_LEADERBOARD_PROCESSED.csv"))
    sell_files = glob.glob(os.path.join(OUTPUT_DIR, f"{latest_date_str}_*_SELL_LEADERBOARD_PROCESSED.csv"))
    buy_pool, sell_pool = [], []
    for f in buy_files:
        if "combined_leaderboard" in os.path.basename(f).lower(): continue
        try:
            df_item = pd.read_csv(f)
            if not df_item.empty: buy_pool.append(df_item)
        except Exception: pass
    for f in sell_files:
        if "combined_leaderboard" in os.path.basename(f).lower(): continue
        try:
            df_item = pd.read_csv(f)
            if not df_item.empty: sell_pool.append(df_item)
        except Exception: pass
    if not buy_pool or not sell_pool: return
    all_buys_df = pd.concat(buy_pool, ignore_index=True)
    all_sells_df = pd.concat(sell_pool, ignore_index=True)
    unique_buys = all_buys_df.sort_values(by='Final_Composite_Score', ascending=False).drop_duplicates(subset=['Symbol'], keep='first')
    unique_sells = all_sells_df.sort_values(by='Final_Composite_Score', ascending=True).drop_duplicates(subset=['Symbol'], keep='first')
    buy_section_rows = unique_buys.head(50).copy()
    sell_section_rows = unique_sells.head(50).copy()
    delimiter_separator_row = pd.DataFrame([{col: "" for col in buy_section_rows.columns}])
    delimiter_separator_row.loc[0, 'Symbol'] = "=== SHORT / DEFENSIVE EXPOSURE REGIME BOUNDARY ==="
    delimiter_separator_row.loc[0, 'Final_Composite_Score'] = "---"
    master_reorg_union_sheet = pd.concat([buy_section_rows, delimiter_separator_row, sell_section_rows], ignore_index=True)
    combined_name = f"{latest_date_str}_COMBINED_LEADERBOARD_PROCESSED.csv"
    master_reorg_union_sheet.to_csv(os.path.join(OUTPUT_DIR, combined_name), index=False)
    print(f"🏆 SUCCESS: Additional Combined Re-Org File Compiled -> {combined_name}\n")

def execute_master_ranker_pipeline():
    print("========================================================")
    print("📡 RUNNING UNIFIED MASTER LEADERBOARD RANKER ENGINE")
    print(f"⚖️ Component Weights Applied: SEPA={W_SEPA} | OBV5={W_OBV5} | FUND={W_FUND}")
    print(f"🔬 Physics Modifiers Locked: W_VIX={W_MVIX} | W_UUP={W_MUUP} | W_SAM={W_MSAM}")
    print("========================================================\n")
    
    latest_date_str = get_latest_workspace_file_date()
    # 🎯 PHYSICS ENGINE INGESTION: Pull your uniform -5.0 to +5.0 indicators directly
    macro_physics = load_macro_tension_physics_scalars()
    
    print(f"📡 Synchronized Ingestion Date Target Focus: {latest_date_str}")
    print(f"🏆 Unified Systemic Macro Weight Score Injected: {macro_physics['overlay_score']:+.2f}\n")
    
    search_pattern = os.path.join(WATCHLIST_DIR, f"*{latest_date_str}*_SANITIZED*.csv")
    target_files = glob.glob(search_pattern)
    
    if not target_files: return
    for filepath in target_files:
        filename = os.path.basename(filepath)
        clean_name = filename.replace(".csv", "")
        if "-options" in clean_name.lower() or "_options" in clean_name.lower(): continue
        token_match = re.search(r"watchlist-[a-zA-Z0-9_]+", clean_name)
        if not token_match: continue
        core_token = token_match.group(0).replace("watchlist-", "").replace("_SANITIZED", "")
        print(f"📈 [Cross-Module Sync Loop] -> Compiling Watchlist Matrix: [{core_token}]")
        print("-" * 65)
        
        try:
            base_df = pd.read_csv(filepath, on_bad_lines='skip')
            if base_df.empty or 'Symbol' not in base_df.columns: continue
            master_df = base_df[['Symbol']].copy()
            
            sepa_pattern = os.path.join(SEPA_DIR, f"*{latest_date_str}*{core_token}*.csv")
            sepa_matches = glob.glob(sepa_pattern)
            if sepa_matches:
                s_df = pd.read_csv(sepa_matches[0], on_bad_lines='skip')
                s_cols = [c for c in ['Symbol', 'SEPA_Stage2_Pass', 'Stage3_Distribution_Pass', 'Stage4_Short_Reference', 'Stage1_Base_Pass', 'Trend_Distance_Pct'] if c in s_df.columns]
                master_df = pd.merge(master_df, s_df[s_cols], on='Symbol', how='left')
                    
            obv_pattern = os.path.join(OBV_DIR, f"*{latest_date_str}*{core_token}*.csv")
            obv_matches = glob.glob(obv_pattern)
            if obv_matches:
                o_df = pd.read_csv(obv_matches[0], on_bad_lines='skip')
                o_cols = [c for c in ['Symbol', 'obv4_Score', 'obv50_Score'] if c in o_df.columns]
                master_df = pd.merge(master_df, o_df[o_cols], on='Symbol', how='left')
                    
            fund_pattern = os.path.join(FUND_DIR, f"*{latest_date_str}*{core_token}*.csv")
            fund_matches = glob.glob(fund_pattern)
            if fund_matches:
                f_df = pd.read_csv(fund_matches[0], on_bad_lines='skip')
                f_cols = [c for c in ['Symbol', 'Volume', 'Sector', 'Yield', 'Expense_Ratio', 'Earnings_Growth_YoY', 'Short_Percent_Of_Float'] if c in f_df.columns]
                master_df = pd.merge(master_df, f_df[f_cols], on='Symbol', how='left')

            if 'Volume' not in master_df.columns and 'Volume' in base_df.columns:
                master_df['Volume'] = base_df['Volume']

            sepa_scores, obv5_scores, fund_scores, stretch_scores, macro_overlays = [], [], [], [] , []
            for idx in master_df.index:
                row = master_df.loc[idx].to_dict()
                sepa_scores.append(calculate_sepa_layer(row) * W_SEPA)
                obv5_scores.append(calculate_obv5_layer(row) * W_OBV5)
                fund_scores.append(calculate_fundamental_layer(row) * W_FUND)
                # Static barometer percent pass fallback
                gauge_pct = 34.4 
                stretch_scores.append(calculate_mechanical_stretch_layer(row, gauge_pct))
                # 🎯 INJECT HOOKE'S LAW BALANCED OVERLAY VALUE
                macro_overlays.append(macro_physics['overlay_score'])
                
            master_df['Score_SEPA'] = sepa_scores
            master_df['Score_OBV5'] = obv5_scores
            master_df['Score_FUND'] = fund_scores
            master_df['Score_STRETCH'] = stretch_scores
            master_df['Score_MACRO_OVERLAY'] = macro_overlays
            
            master_df['Final_Composite_Score'] = (
                master_df['Score_SEPA'] + master_df['Score_OBV5'] + master_df['Score_FUND'] + 
                master_df['Score_STRETCH'] + master_df['Score_MACRO_OVERLAY']
            )
            master_df['Final_Composite_Score'] = master_df['Final_Composite_Score'].round(2)
            
            df_buy_leaderboard = master_df.sort_values(by='Final_Composite_Score', ascending=False).copy()
            df_sell_leaderboard = master_df.sort_values(by='Final_Composite_Score', ascending=True).copy()
            
            print(f" 🔥 TOP BUY EXPANSION CANDIDATES (Watchlist: {core_token})")
            for i in df_buy_leaderboard.head(5).index:
                r = df_buy_leaderboard.loc[i]
                print(f"    ⭐ {r['Symbol']:<6} | Score: {r['Final_Composite_Score']:+6.2f}  [SEPA:{r['Score_SEPA']:+4.1f} | OBV:{r['Score_OBV5']:+4.1f} | FUND:{r['Score_FUND']:+4.1f}]")
            print("-" * 65)
            
            buy_out_name = f"{latest_date_str}_{core_token}_BUY_LEADERBOARD_PROCESSED.csv"
            sell_out_name = f"{latest_date_str}_{core_token}_SELL_LEADERBOARD_PROCESSED.csv"
            df_buy_leaderboard.to_csv(os.path.join(OUTPUT_DIR, buy_out_name), index=False)
            df_sell_leaderboard.to_csv(os.path.join(OUTPUT_DIR, sell_out_name), index=False)
            print(f"   ✨ Success: Cross-module matrix consolidated for [{core_token}] -> Saved Locally")
        except Exception as file_err:
            print(f"   ⚠️ Warning: Matrix convergence failed for core [{core_token}]: {file_err}")
            
    execute_zero_recalc_combined_merger_pass(latest_date_str)

if __name__ == "__main__":
    execute_master_ranker_pipeline()

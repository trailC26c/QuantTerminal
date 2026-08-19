import pandas as pd
import glob
import os
import re
from datetime import datetime

LEADERBOARD_DIR = r"C:\Users\tcnet\TOS_Data_Local\master_leaderboard"
MACRO_DIR = r"C:\Users\tcnet\TOS_Data_Local\macro_indicators"
OUTPUT_DIR = r"C:\Users\tcnet\TOS_Data_Local\summary_reports"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_latest_leaderboard_date():
    """Scans the directory and extracts the latest available YYYY-MM-DD cluster."""
    files = glob.glob(os.path.join(LEADERBOARD_DIR, "*-MASTER_LEADERBOARD.csv"))
    if not files:
        return None
    dates = [re.match(r"^(\d{4}-\d{2}-\d{2})", os.path.basename(f)).group(1) for f in files if re.match(r"^(\d{4}-\d{2}-\d{2})", os.path.basename(f))]
    return max(dates) if dates else None

def generate_final_alpha_dashboard():
    print("\n========================================================")
    print("📊 [STEP MODULE 9] Generating Alpha Console Dashboard and Text Summary Report...")
    print("🛰️  QUANT TERMINAL: MASTER TELEMETRY RADAR DASHBOARD")
    print("========================================================\n")
    
    macro_path = os.path.join(MACRO_DIR, "market_pressure_gauge.csv")
    barometer_display_str = "Level +0 [NEUTRAL]"
    level = 0
    multiplier = 1.0
    mtf_lines = []
    
    if os.path.exists(macro_path):
        try:
            df_macro = pd.read_csv(macro_path)
            if not df_macro.empty:
                row_dict = {str(k).lower(): v for k, v in df_macro.iloc[0].to_dict().items()}
                
                level = int(row_dict.get('barometer_level', 0))
                regime = str(row_dict.get('regime', 'NEUTRAL')).upper()
                multiplier = float(row_dict.get('modulation_multiplier', 1.0))
                barometer_display_str = f"Level {level:+} [{regime}]"
                
                # 📌 REVISED INTERFACE LAYER: Displays raw percentage locations inside lookback windows
                l20, l50 = int(row_dict.get('level_20', 0)), int(row_dict.get('level_50', 0))
                l100, l200 = int(row_dict.get('level_100', 0)), int(row_dict.get('level_200', 0))
                
                print(f"🌍 BROAD MARKET OVERARCHING ENVIRONMENT CONSENSUS:")
                print(f"   ↳ Unified Radar Gauge: {barometer_display_str}")
                print(f"   ↳ Sizing Modifier:     {multiplier}x allocation limit")
                print(f"   📈 Multi-Timeframe Structural Array (Relative Positions):")
                print(f"      [ES-VX: {l20}%]  [NQ-VX: {l50}%]  [ES-USD: {l100}%]  [NQ-USD: {l200}%]")
                print("-" * 56)
                
                mtf_lines.append(f"🌍 Broad Market Radar Gauge Consensus: {barometer_display_str}")
                mtf_lines.append(f"📐 Unified Macro Sizing Modifier: {multiplier}x")
                mtf_lines.append(f"📈 Multi-Timeframe Matrix (Relative Positions): [ES-VX: {l20}%] [NQ-VX: {l50}%] [ES-USD: {l100}%] [NQ-USD: {l200}%]")
        except Exception as e:
            print(f"📝 Note: Parsing multi-timeframe indicators using fallback parameters. Detail: {e}")

    target_date = get_latest_leaderboard_date()
    if not target_date:
        print("⚠️ Error: No final weighted Alpha leaderboards found to parse.")
        return
        
    print(f"📡 Parsing Core Leaderboard Telemetry for Date Cluster: {target_date}")
    print("-" * 56)

    leaderboard_files = glob.glob(os.path.join(LEADERBOARD_DIR, f"{target_date}-*-MASTER_LEADERBOARD.csv"))

    report_lines = []
    report_lines.append("========================================================")
    report_lines.append("🛰️ QUANT TERMINAL: ACTIONABLE INSIGHT SUMMARY REPORT")
    for m_line in mtf_lines:
        report_lines.append(m_line)
    report_lines.append(f"📅 Selected File Date Cluster Group: {target_date}")
    report_lines.append(f"⏰ Execution Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("========================================================\n")

    for file_path in leaderboard_files:
        base_name = os.path.basename(file_path).replace('-MASTER_LEADERBOARD.csv', '')
        
        df = pd.read_csv(file_path)
        if df.empty:
            print(f"\n🏆 TOP 5 ALPHA OPPORTUNITIES\nWatchlist: {base_name}\n   ↳ Leaderboard matrix is currently empty.\n" + "-"*56)
            report_lines.append(f"🎯 WATCHLIST SELECTION: {base_name}\n   ↳ Leaderboard matrix is currently empty.\n")
            continue
            
        top_alphas = df.head(5).copy()
        setup_tags = [("STRICT_SEPA" if row.get('SEPA_Stage2_Pass', False) else ("CYCLIC_BASE" if row.get('Cyclic_Pass', False) else "CONSOLIDATING")) for _, row in top_alphas.iterrows()]
        
        is_universal_setup = len(set(setup_tags)) == 1
        universal_setup_tag = setup_tags[0] if is_universal_setup else None
        has_options = bool(top_alphas['Has_Options_Context'].iloc[0]) if 'Has_Options_Context' in top_alphas.columns else True

        print(f"\n🏆 TOP 5 ALPHA OPPORTUNITIES")
        mode_str = "EQUITY+OPTIONS" if has_options else "PURE EQUITY SCAN (NO OPTIONS)"
        if is_universal_setup:
            print(f"Watchlist: {base_name} | Universe: {mode_str} | Setup: {universal_setup_tag}")
            report_lines.append(f"🎯 WATCHLIST SELECTION: {base_name} | Universe: {mode_str} | Setup: {universal_setup_tag}")
        else:
            print(f"Watchlist: {base_name} | Universe: {mode_str}")
            report_lines.append(f"🎯 WATCHLIST SELECTION: {base_name} | Universe: {mode_str}")
        print("-" * 56)
        report_lines.append("-" * 56)

        for _, row in top_alphas.iterrows():
            sym = row['Symbol']
            alpha = row['Alpha_Score']
            obv5 = row['OBV5_Score']
            opt_wall = row.get('Opt_Imbalance_Wall', 0.0)
            tag = "STRICT_SEPA" if row.get('SEPA_Stage2_Pass', False) else ("CYCLIC_BASE" if row.get('Cyclic_Pass', False) else "CONSOLIDATING")
            
            # Reconstruct scores dynamically
            tech_score = (abs(float(obv5)) / 5.0) * 100 if float(obv5) < 0 else 0.0
            q1_surprise = float(row.get('Q1_Surprise_Pct', 0.0))
            buy_count = int(row.get('Analyst_Buy_Count', 0))
            fund_score = min(50.0, max(0.0, q1_surprise)) + min(50.0, (buy_count / 10.0) * 50)
            
            if has_options:
                opt_score = min(100.0, (opt_wall / 20.0) * 100)
                math_str = f"(Tech_40%:{tech_score:0.1f}, OptFlow_30%:{opt_score:0.1f}, Fund_30%:{fund_score:0.1f})"
                wall_str = f" | Opt Wall: {opt_wall:<5}x"
            else:
                math_str = f"(Tech_50%:{tech_score:0.1f}, Fund_50%:{fund_score:0.1f})"
                wall_str = ""

            setup_str = "" if is_universal_setup else f" | Setup: {tag:<14}"
            
            line_out = f"      • [{level:+}] Ticker: {sym:<6} | Alpha: {alpha:<6} | OBV5: {obv5:<4}{wall_str}{setup_str} | Vectors: {math_str}"
            print(line_out)
            report_lines.append(line_out)
            
        print("-" * 56)
        report_lines.append("\n" + "="*56 + "\n")

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    text_out_path = os.path.join(OUTPUT_DIR, f"terminal_insight_summary_{timestamp_str}.txt")
    with open(text_out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))
    print(f"\n💾 Timestamped archive summary written to disk -> {os.path.basename(text_out_path)}\n")

if __name__ == "__main__":
    generate_final_alpha_dashboard()

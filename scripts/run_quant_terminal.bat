@echo off
:: =========================================================================
:: 📡 QUANT TERMINAL: SYSTEM AUTOMATION AUTOMATED MASTER PIPELINE SCRIPT
:: =========================================================================
:: File Name: run_quant_terminal.bat
:: Purpose: Automates Step 1 through Step 6 Workspace Convergence Routines.
:: Enforces flat command-line weights, B/W theme, and PowerShell clock anchors.
:: =========================================================================

title QUANT TERMINAL: MASTER PIPELINE CONTINUOUS RUNNER
:: 🎯 EYE COMFORT: Standard crisp Black and White text layout
color 0F
cls

:: 🎯 POWERSHELL HIGH-PRECISION BENCHMARK START TICK
for /f "delims=" %%i in ('powershell -Command "[DateTime]::Now.ToString('HH:mm:ss')"') do set START_TIME=%%i
for /f "delims=" %%i in ('powershell -Command "[DateTime]::Now.Ticks"') do set START_TICKS=%%i

echo =======================================================================
echo 🚀 INITIALIZING SYSTEM AUTOMATION PIPELINE OPERATIONAL COMMAND MATRIX
echo =======================================================================
echo 📡 Active Directory: %cd%
echo 🕒 Ingestion Start:  %date% %START_TIME%
echo =======================================================================
echo.

:: -------------------------------------------------------------------------
:: 🔄 STAGE 1: RAW THINKORSWIM DATA TABLE CLEANING PASS
:: -------------------------------------------------------------------------
echo 📥 [STAGE 1/7] Launching Raw Watchlist cell text sanitization loop...
:: 🎯 CONTROL TOGGLE: Switch --input native to --input generic to auto-scan your telemetry symbols!
python processor.py --input generic
if %errorlevel% neq 0 goto STAGE_CRASH_HALT

:: -------------------------------------------------------------------------
:: 🔄 STAGE 2: SEPA TREND LIFECYCLE MATRICES ALIGNMENT
:: -------------------------------------------------------------------------
echo.
echo 🌿 [STAGE 2/7] Executing discrete Boolean Stage trend filter analysis...
python sepa_matrix.py
if %errorlevel% neq 0 goto STAGE_CRASH_HALT

:: -------------------------------------------------------------------------
:: 🔄 STAGE 3: VOLUME REVERSAL OBV5 ACCELERATION MATRIX
:: -------------------------------------------------------------------------
echo.
echo 📊 [STAGE 3/7] Generating non-destructive inverted volume ribbon sweeps...
python obv5_analyzer.py
if %errorlevel% neq 0 goto STAGE_CRASH_HALT

:: -------------------------------------------------------------------------
:: 🔄 STAGE 4: INSTITUTIONAL FUNDAMENTAL AND NET-YIELD FILTERS
:: -------------------------------------------------------------------------
echo.
echo 🔑 [STAGE 4/7] Parsing liquidity gates, yields, and growth velocities...
python fundamental_analyzer.py
if %errorlevel% neq 0 goto STAGE_CRASH_HALT

:: -------------------------------------------------------------------------
:: 🔄 STAGE 5: REAL-TIME TIME-SERIES HOOKE'S LAW MACRO BAROMETER
:: -------------------------------------------------------------------------
echo.
echo 🌍 [STAGE 5/7] Running rolling range-normalized intermarket tension ledger...
:: 🎯 PLOT CALIBRATION: Synchronizes your exact 252-bar window and 504-bar visual range block
python macro_barometer.py --window 200 --shift 0 --range 300 --scale_min 1.0 --scale_max 11.0
if %errorlevel% neq 0 goto STAGE_CRASH_HALT

:: -------------------------------------------------------------------------
:: 🔄 STAGE 6: HOOKE'S LAW BALANCED MASTER RANKER MULTI-FACTOR ENGINE
:: -------------------------------------------------------------------------
echo.
echo ⚖️ [STAGE 6/7] Synthesizing continuous 100-point uniform leaderboard metrics...
python master_ranker.py --w_sepa 1.0 --w_obv5 0.5 --w_fund 1.5 --w_macro_vix 1.0 --w_macro_uup 0.8 --w_macro_sam 1.2
if %errorlevel% neq 0 goto STAGE_CRASH_HALT

:: -------------------------------------------------------------------------
:: 🔄 STAGE 7: HIGH-VELOCITY 6-COLUMN MOBILE COCKPIT FORMATTER
:: -------------------------------------------------------------------------
echo.
echo 🎛️ [STAGE 7/7] Stripping consolidated rows into vertical cockpit overview...
python summary_dashboard.py
if %errorlevel% neq 0 goto STAGE_CRASH_HALT

:: =========================================================================
:: 🎉 AUTOMATION SUCCESS TERMINAL LOG REPORT INTERFACE
:: =========================================================================
for /f "delims=" %%i in ('powershell -Command "[DateTime]::Now.ToString('HH:mm:ss')"') do set END_TIME=%%i
for /f "delims=" %%i in ('powershell -Command "[DateTime]::Now.Ticks"') do set END_TICKS=%%i

:: Compute exact delta seconds using PowerShell's robust integer math engine
for /f "delims=" %%i in ('powershell -Command "[Math]::Round( (%END_TICKS% - %START_TICKS%) / 10000000 )"') do set ELAPSED_SECONDS=%%i

:: REAL-TIME LOGGING TO LOGGING FILE (Appends run details to your macro path ledger folder)
set LOG_FILE=C:\Users\tcnet\TOS_Data_Local\macro_barometer\pipeline_automation_log.txt
echo [%date% %START_TIME%] Run Date Focus: %date% ^| Total Operational Pipeline Runtime: %ELAPSED_SECONDS% Seconds ^| Status: SUCCESS >> "%LOG_FILE%"

echo.
echo =======================================================================
echo 🏆 SUCCESS: QUANT TERMINAL FULL PIPELINE RE-RUN COMPLETE
echo =======================================================================
echo 📁 Long/Short Leaderboard Sheets and Mobile Summary Dashboard compiled
echo 🕒 Ingestion Finalized: %date% %END_TIME%
echo ⏱️ TOTAL OPERATIONAL PIPELINE RUNTIME: %ELAPSED_SECONDS% Seconds
echo 📄 Automation Run Log Appended to: \macro_barometer\pipeline_automation_log.txt
echo =======================================================================
pause
exit /b 0

:: =========================================================================
:: 🛑 CRITICAL STAGE EXECUTION FAIL-SAFE SYSTEM EMERGENCY BRAKE ROUTINE
:: =========================================================================
:STAGE_CRASH_HALT
for /f "delims=" %%i in ('powershell -Command "[DateTime]::Now.Ticks"') do set CRASH_TICKS=%%i
for /f "delims=" %%i in ('powershell -Command "[Math]::Round( (%CRASH_TICKS% - %START_TICKS%) / 10000000 )"') do set ELAPSED_CRASH_SECONDS=%%i

set LOG_FILE=C:\Users\tcnet\TOS_Data_Local\macro_barometer\pipeline_automation_log.txt
echo [%date% %START_TIME%] Run Date Focus: %date% ^| Total Operational Pipeline Runtime: %ELAPSED_CRASH_SECONDS% Seconds ^| Status: CRASH_FAILED >> "%LOG_FILE%"

echo.
echo #######################################################################
echo 🛑 AUTOMATION PIPELINE FAILURE DETECTED: SCRIPT ERROR RUNTIME RE-ENTRY HALT
echo #######################################################################
echo ⚠️ Crash Status Location: Processing crashed at active Stage index parameter.
echo ⏱️ Run Duration Before Failure: %ELAPSED_CRASH_SECONDS% Seconds
echo #######################################################################
echo.
pause
exit /b %errorlevel%

# QuantTerminal

QuantTerminal is a local-first toolkit for market data ingestion, SEPA and
fundamental diagnostics, macro-barometer charts, and reproducible historical
analysis.

## Setup

From the project root:

```powershell
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

All commands below assume the virtual environment is active.

## Data Layout

Raw TOS exports remain outside the project:

```text
C:\Users\tcnet\TOS_Data_Local\raw_watchlists\
```

The primary keyed input files follow this pattern:

```text
<date>-watchlist-<key>.csv
```

The normal keys are `core`, `long`, `allopt`, `allpos`, `asml+`, and `others`.
Every keyed list may contain equities, ETFs, futures, and option rows.
`allopt` is the broad market-wide scan list; the filename key is retained as
row-level provenance in `Source_Watchlists`.

Project-local data and results:

```text
data/
	sanitized_watchlists/       Privacy-guarded analytics inputs
	processed_watchlists/       Private, unsanitized portfolio-aware outputs
	quant_terminal.db           Local SQLite database
	database_backups/           Verified SQLite backups
	market_db_build_progress.json
	telemetry_list.txt          Curated barometer and alpha launch universe
output/
	sepa_results/
	fundemental_matrix/
 obv5_engine/
	charts/
```

`processed_watchlists` may contain quantities, P/L, net liquidation, and
other private position fields. Keep it private. The active analytics pipeline
reads `data/sanitized_watchlists`.

## Processor

Process every latest-date raw keyed file with the privacy guard enabled:

```powershell
python scripts/processor.py --input native --privacy_guard 1
```

Generate only the curated telemetry watchlist:

```powershell
python scripts/processor.py --input generic --privacy_guard 1
```

Process the latest raw keyed files and generate the telemetry watchlist in
one pass:

```powershell
python scripts/processor.py --input all --privacy_guard 1
```

For travel or unreliable VPN connectivity, use:

```powershell
python scripts/processor.py --input all --privacy_guard 1 --offline
```

Offline mode never calls Yahoo Finance. It reuses local database values for
generic telemetry generation and leaves unavailable enrichment fields blank.
If the external raw folder is empty, `--input all` still generates the
generic sanitized watchlist from `data/telemetry_list.txt`.

The generated telemetry file is tagged with `Source_Watchlists=generic`.
Native outputs are tagged with their source key, such as `core`, `allpos`, or
`allopt`.

Native files use their latest available TOS session date. Generic files use
the processor run date when generated independently. In `--input all` mode,
both are produced in one pass, but their dates remain independent so a quick
generic run cannot hide the latest native TOS session.

## Local Market Database

Build or resume the local database from sanitized snapshots:

```powershell
python scripts/build_market_db.py --privacy_guard 1 --batch-size 20 --pause-seconds 60
```

The builder stores each unique asset once, tracks dated membership in every
keyed list, retains sanitized row observations, and caches non-option market
bars. Option rows are retained as observations, but option historical bars are
not downloaded. Futures contracts are translated to continuous Yahoo symbols
for acquisition while their original TOS symbols remain stored.

Use `--max-batches 1` for a staged run. The builder is resumable and records
progress in `data/market_db_build_progress.json`.

## SEPA Diagnostics

Run a cautious 20-symbol diagnostic:

```powershell
python scripts/sepa_matrix.py
```

Run all unique non-option symbols from `allpos`:

```powershell
python scripts/sepa_matrix.py --watchlist-key allpos
```

Run the full combined keyed universe:

```powershell
python scripts/sepa_matrix.py --watchlist-key all --sample-size 0 --download-missing 1
```

Run the same analysis strictly offline:

```powershell
python scripts/sepa_matrix.py --watchlist-key all --sample-size 0 --offline
```

SEPA output is timestamped under `output/sepa_results`. It includes stage
flags, R1-R7 criteria, reasons, data source, stored bar counts, stored date
range, and `Source_Watchlists` provenance. Missing offline history is reported
as `missing_offline` rather than causing a network request.

## Fundamental Analysis

Fundamentals are cached in SQLite and reused for seven days by default:

```powershell
python scripts/fundamental_analyzer.py --watchlist-key all
```

Change the freshness window when needed:

```powershell
python scripts/fundamental_analyzer.py --watchlist-key all --refresh-days 14
```

Use `--refresh-days 0` to force a refresh without using `--force-refresh`.

Run one keyed list:

```powershell
python scripts/fundamental_analyzer.py --watchlist-key allpos
```

Force a provider refresh:

```powershell
python scripts/fundamental_analyzer.py --watchlist-key all --force-refresh
```

Run without internet access:

```powershell
python scripts/fundamental_analyzer.py --watchlist-key all --offline
```

The combined output is written to `output/fundemental_matrix` and includes
`Source_Watchlists`, `Expense_Ratio`, `Yield`, and
`Net_Yield_After_Expense`. Previous keyed-list output files are preserved;
the combined filename represents the latest combined run. The short-interest
fields `Short_Percent_Of_Float` and `Short_Percent_Of_Float_Last` represent
the current value and latest available prior value. The prior field may be
empty on the first observation; it is not a fabricated daily history.

The scoring configuration is stored in `data/fundamental_scoring.json`.
Use `--profile base` for the current baseline or `--profile qgr` for the
Quality-Growth-Risk test profile. `qgr` adds short interest as a capped risk
component: 0% short interest maps to +100, 25% maps to 0, and 50% or higher
maps to -100. Its raw weight is 10, making the total raw weight 115 and the
effective short-interest share about 8.7% after normalization. The selected
profile is recorded in `Scoring_Profile` in candidate outputs.
Additional profiles can be added under `profiles` in the JSON configuration;
the CLI accepts those names without a code change and writes the uppercase
profile shorthand into the output filename.
After the complete matrix is written, the analyzer also creates timestamped
candidate views using the configured weights and limits:

```text
<date>_<PROFILE>_FUNDAMENTAL_QUALIFIED_LONG.csv
<date>_<PROFILE>_FUNDAMENTAL_QUALIFIED_SHORT.csv
<date>_<PROFILE>_FUNDAMENTAL_QUALIFIED_SCORE0.csv
<date>_<PROFILE>_FUNDAMENTAL_UNQUALIFIED.csv
```

The complete `*_watchlist_all_<PROFILE>_FUND_PROCESSED.csv` matrix remains
intact. Fundamental output filenames include the uppercase profile shorthand,
such as `2026-08-27_BASE_FUNDAMENTAL_QUALIFIED_LONG.csv` and
`2026-08-27_QGR_FUNDAMENTAL_QUALIFIED_LONG.csv`, so comparison runs do not
overwrite one another. The
candidate views add `Fundamental_Score`, `Fundamental_Rank`,
`Fundamental_Qualification`, `Fundamental_Data_Completeness`, and
`Fundamental_Score_Model`.

`minimum_completeness: 0.6` means an equity must have at least 60% of these
seven required fields available to enter candidate ranking:

```text
Earnings_Growth_YoY
EBITDA_Margin
Gross_Margin
Free_Cash_Flow_Yield
Analyst_Rec_Score
Sentiment_Target_Upside
Institutional_Ownership_Pct
```

Completeness is calculated as available fields divided by seven. Because the
result is rounded to two decimals, 5 of 7 fields (`0.71`) is eligible while
4 of 7 (`0.57`) is labeled `INSUFFICIENT_DATA` and placed in the unqualified
output. The current measure checks field availability; a default numeric
value can therefore count as present. ETF rows use their separate
yield/expense model and currently receive full model completeness.

Eligible symbols with an exact `Fundamental_Score` of zero are retained in
the separate `QUALIFIED_SCORE0` output. They are not forced into either the
long or short candidate list. Symbols with insufficient data remain labeled
`INSUFFICIENT_DATA`.

All four fundamental outputs carry the same analyst-reference fields:

```text
Analyst_Strong_Buy_Count
Analyst_Buy_Count
Analyst_Hold_Count
Analyst_Sell_Count
Analyst_Strong_Sell_Count
Analyst_Total_Count
Analyst_Consensus_Confidence
```

These fields are collected per symbol from the current provider
recommendation distribution and propagate unchanged through the complete
fundamental matrix, qualified-long output, qualified-short output, and
unqualified output. `Analyst_Rec_Score` remains the current per-symbol
average recommendation used in the score. The count and confidence fields
are preserved as reference data for future model refinement and are not yet
additional score components.

The default long and short candidate counts are configured as
`long_limit: 250` and `short_limit: 250` in `data/fundamental_scoring.json`.
Override both counts for one run, for example:

```powershell
python scripts/fundamental_analyzer.py --watchlist-key all --candidate-limit 30
```

Compare the baseline and risk-aware profiles with the same candidate limit:

```powershell
python scripts/fundamental_analyzer.py --watchlist-key all --profile base --candidate-limit 20
python scripts/fundamental_analyzer.py --watchlist-key all --profile qgr --candidate-limit 20
```

The candidate limit applies independently to qualified long and short output.
Those outputs can optionally extend the macro chart universe:

```powershell
python scripts/macro_barometer.py --data-source local --fundamental-candidates long
python scripts/macro_barometer.py --data-source local --fundamental-candidates short
python scripts/macro_barometer.py --data-source local --fundamental-candidates both
```

The default is `--fundamental-candidates none`, which preserves the telemetry
and configured alpha universe. Candidate symbols are read from the newest
dated fundamental output files and deduplicated against the existing universe.
The candidate modes are:

```text
none  = macro/telemetry universe only; clean baseline
long  = macro/telemetry plus selected long candidates
short = macro/telemetry plus selected short candidates
both  = macro/telemetry plus selected long and short candidates
```

Use `none` when validating the original macro barometer purpose or when you
want a controlled baseline before measuring the effect of candidate overlays.
For integrated macro charts, select one candidate profile and limit its long
and short additions independently:

```powershell
python scripts/macro_barometer.py --data-source auto --fundamental-candidates both --fundamental-profile base --fundamental-limit 20
python scripts/macro_barometer.py --data-source auto --fundamental-candidates both --fundamental-profile qgr --fundamental-limit 20
```

Use `--fundamental-limit 0` to include all candidates from the selected profile.

To append symbols that produced at least one OBV5 signal in the latest three
bars, select one hits variant:

```powershell
python scripts/macro_barometer.py --data-source local --obv5-candidates p4_all
python scripts/macro_barometer.py --data-source local --obv5-candidates p5_ext
python scripts/macro_barometer.py --data-source local --obv5-candidates p5_all
```

This is opt-in; the default `none` leaves the telemetry-defined universe
unchanged. Hit symbols are deduplicated against the telemetry symbols and any
other appended candidates. The source file is the latest matching
`output/obv5_engine/*_OBV5_LATEST3_HITS_<VARIANT>_*.csv` artifact produced by
`obv5_signal_engine.py`.

The engine writes three hits variants on every run, each with its own
recomputed `Latest_Signals_3B` and `Latest_Signal_Periods_3B` values:

```text
P4_ALL = P1-P4 signals only; the steadier near-action set
P5_EXT = P5 global window extrema only, excluding local turns
P5_ALL = every signal, including P5 local turns; experimental reference
```

P5 local turns are intentionally sensitive and can dominate the latest bars,
so `P4_ALL` is the conservative near-action feed while `P5_EXT` narrows P5 to
global extrema. The full summary and detailed ledger remain unfiltered.

For combined `all` runs, curated telemetry symbols tagged with `generic` can
remain visible beyond the top-candidate limit when their score is directional.
This is controlled by `include_generic_overflow` and the
`generic_long_min_score` / `generic_short_max_score` thresholds in the same
configuration file. The candidate output records whether a row came from the
main score limit or from generic overflow in `Candidate_Selection_Reason`.

## OBV5 Engine

OBV5 is the action-timing confirmation layer after fundamental qualification
and SEPA stage analysis. The reusable implementation is
`scripts/obv5_signal_engine.py` and preserves period-level evidence for each
symbol:

The reusable signal engine will preserve period-level evidence for each
symbol:

```text
P1 = 360 bars
P2 = 270 bars
P3 = 180 bars
P4 = 90 bars
P5 = 50 bars
```

Each stored signal should retain:

```text
symbol
signal_date
evaluation_date
period
period_bars
direction              # green/min or red/max
extreme_type
signal_type
bar_offset
shift_bars
signal_value
source_first_date
source_last_date
algorithm_version
calculated_at
```

The durable representation is long-format, one row per signal event, with a
generated summary for charting and review. Green signals represent the
buy-side/minimum interpretation; red signals represent the sell-side/maximum
interpretation.

Historical signals must remain available for P5 study, including exact bar
offsets, period alignment, conflicts, clusters, and subsequent forward
returns. Rerunning the same evaluation should update identical logical signal
records without duplicating them; prior evaluation dates remain intact.

The stored signal evidence will be reused by:

```text
OBV5 timing filters
macro-barometer charts
offline analysis
backtests and regressions
```

The detailed OBV5 CSV exports are written to `output/obv5_engine/`. The
SQLite `obv5_signals` table remains the durable historical source for queries,
event studies, and offline analysis.

The macro chart CLI exposes the recent P4/P5 focus length as
`--obv5_recent_bars`; the current default is `20`. For example:

```powershell
python scripts/macro_barometer.py --data-source local --obv5_recent_bars 20
```

There is no option currently named `focus_length`; `--obv5_recent_bars` is the
current equivalent. The standalone signal engine uses the corresponding
`--recent_bars` option.

Run the standalone engine online across all symbols known to the local
database, then run the local-only comparison:

```powershell
python scripts/obv5_signal_engine.py --symbols all --data-source online
python scripts/obv5_signal_engine.py --symbols all --data-source local
```

Prefer `--data-source auto` for routine refreshes; it downloads only the
symbols whose local history is missing or too short, then caches the result:

```powershell
python scripts/obv5_signal_engine.py --symbols all --data-source auto --recent_bars 7
```

Each run preserves timestamped files under `output/obv5_engine/`:

```text
<date>_OBV5_SIGNALS_<time>.csv                detailed event-level signal ledger
<date>_OBV5_SUMMARY_<time>.csv                complete symbol-universe scanner
<date>_OBV5_LATEST3_HITS_P4_ALL_<time>.csv    P1-P4 signals only
<date>_OBV5_LATEST3_HITS_P5_EXT_<time>.csv    P5 global extrema, no local turns
<date>_OBV5_LATEST3_HITS_P5_ALL_<time>.csv    every signal, including local turns
```

Each variant recomputes its own recent-signal count, `Latest_Signals_3B`, and
`Latest_Signal_Periods_3B` from its own signal subset, so the counts and detail
tokens stay internally consistent rather than being filtered leftovers of the
full set.

The full summary includes every processed symbol, including symbols with no
recent signals. Its recent-signal count is dynamically named according to the
selected setting, such as `Recent_Signals_20B` or `Recent_Signals_7B`.
`Latest_Signals_3B` and `Latest_Signal_Periods_3B` use the fixed order
`bar -2 | bar -1 | bar 0`. A symbol with no signals in those bars is recorded
as:

```text
Latest_Signals_3B:        0|0|0
Latest_Signal_Periods_3B: -|-|-
```

Signal detail tokens use `PERIOD:DIRECTION` notation. `G` and `R` identify
window-extreme green and red signals; `LTG` and `LTR` identify local-turn
green and red signals. For example, `P5:G` is a P5 window-extreme green
signal and `P5:LTG` is a P5 local-turn green signal. Multiple signals in one
bar are comma-separated. The latest-three-bar hits file is a filtered copy of
the summary with at least one nonzero latest-bar count and is intended for
current signal verification and near-term analysis; the full summary remains
the historical backtesting record.

P5 remains an evidence and validation feature rather than an automatic action
rule. Run the standalone engine locally with:

```powershell
python scripts/obv5_signal_engine.py --data-source local
```

The variants exist because P5 local turns are deliberately sensitive and can
dominate the most recent bars, while P1-P4 window extrema are comparatively
stable. A representative `--recent_bars 7` run over 446 symbols produced:

```text
P5_ALL   313 symbols
P5_EXT    92 symbols
P4_ALL    59 symbols
```

The intended usage order is `P4_ALL` for near-action review, `P5_EXT` for
earlier scouting, and `P5_ALL` as the experimental reference set.

### OBV5 Calibration And Simulation

After the initial TOS comparison, tune P5 first, then P4 and other periods as
needed. Use `--recent_bars` as a calibration input and compare the resulting
signals against the same symbol, session date, and historical bars in TOS.
The goal is a useful trading interpretation, not necessarily an exact copy of
TOS: a Python-only signal may be retained when it is more sensible visually or
performs better in simulation, while visually noisy signals should be reduced.

The NQ session ending 2026-08-25 is a reference case for this judgment. The
preferred result retained two green signals that matched TOS and a separate
Python red signal that appeared more meaningful than the TOS result. The
closely clustered red signals marked as undesirable should not drive repeated
entries or reversals. This example is subjective and must be confirmed across
symbols and dates by simulation.

Keep the raw OBV5 evidence intact while testing a filtered simulation view.
The filtered view may apply these initial rules:

```text
same-direction signals within 1-2 bars: consolidate to the strongest event
repeated weak local reversals: suppress when they do not establish a meaningful extreme
opposite-direction signals: retain initially and evaluate as possible conflicts
every suppressed event: retain with a reason for audit and later retuning
```

For each P<n> and `recent_bars` combination, record TOS alignment, raw signal
count, filtered signal count, close-spaced signal pairs, simulated turnover,
returns, drawdown, and missed or delayed meaningful turns. Do not optimize a
single chart in isolation. A setting is stronger when it reduces overtrading
across the comparison set while preserving useful Python-only signals and
improving simulation results after costs.

## Delta Engine

`scripts/delta_engine.py` owns the normalized asset-to-anchor calculations
previously embedded in `macro_barometer.py`. It calculates rolling `SMAn`,
normalized asset/VIX/UUP/SMA series, and these deltas:

```text
delta_vix = norm_asset - norm_vix
delta_uup = norm_asset - norm_uup
delta_sma = norm_asset - norm_sma
```

The engine uses the same static shifted min/max normalization and scale bounds
as the macro charts. Daily inputs and calculated values are stored in
`data/quant_terminal.db`; the calculation key includes normalization window,
range, and shift, so alternate studies remain available without overwriting
each other. Both the delta engine and macro charts use the shared
`scripts/market_data.py` local-first loader.

Run the telemetry index vector locally:

```powershell
python scripts/delta_engine.py --data-source local
```

Use `--data-source auto` when missing history may be backfilled and cached.

### Macro Consensus Calibration

The macro barometer's portfolio consensus is calculated from the four broad
equity proxies `SPY`, `QQQ`, `DIA`, and `IWM`, corresponding conceptually to
ES, NQ, YM, and RTY. Each proxy contributes its normalized delta versus VIX,
its normalized delta versus UUP, and its price-to-SMA spring. The consensus is
the mean of those readings, expressed as a percentage.

The defensive-level divisor `20` is intentional. The normalized chart detail
range is `-10` to `+10`, so its full span is:

$$
10 - (-10) = 20
$$

The long/cover and short/close multipliers use a deliberately broader divisor
of `40`. This is a calibration choice for the SMA delta presentation and for a
more gradual risk-allocation response on the shared chart. The formulas are:

$$
	ext{Long/Cover} = \operatorname{clamp}\left(2.5 - \frac{\text{Mean Tension \%}}{40}, 0, 5\right)
$$

$$
	ext{Short/Close} = \operatorname{clamp}\left(2.5 + \frac{\text{Mean Tension \%}}{40}, 0, 5\right)
$$

The two multipliers are complementary within the unclipped range and sum to
`5.0`. For example, a `+77.2%` consensus produces `0.57x` long/cover and
`4.43x` short/close. These constants are verified calibration choices, not
values to change during ordinary regression testing unless the chart scaling
or portfolio response model is intentionally redesigned.

The three delta families are parameterized with `--delta-weights` in
`VIX:UUP:SMA` order. The default is `1:1:2`: VIX captures dramatic risk
shocks, UUP provides a subtler macro/currency confirmation, and the SMA spring
receives extra weight as the quieter trend/restoring-force signal. The family
means are calculated first and then combined by the normalized weights, so
each of the four equity proxies remains equally weighted within each family.
The selected weights and family means are recorded in the consensus ledger.

For comparison, preserve the default behavior explicitly or test an equal
weight alternative:

```powershell
python scripts/macro_barometer.py --data-source auto --delta-weights 1:1:2
python scripts/macro_barometer.py --data-source auto --delta-weights 1:1:1
```

## Modular Chart Architecture

The chart pipeline now has clear ownership boundaries:

```text
market_data.py              shared SQLite-first history loading and caching
obv5_signal_engine.py       P1-P5 OBV extrema and signal persistence
delta_engine.py             normalized asset/VIX/UUP/SMAn deltas and persistence
ta_engine.py                Panel 3 TA calculations and normalization
macro_barometer_vector.py   telemetry index and optional candidate selection
macro_barometer.py          chart orchestration and HTML output
```

The generated chart pages provide Dual Panel, standalone Panel 1, standalone
Panel 2, and standalone Panel 3 views. The chart builder consumes the shared
delta and TA calculations while preserving the established normalization
parameters and visual behavior.

## Fresh TOS Retest

### Verified Checkpoint: 2026-08-27

The following online checks passed against the newest TOS exports:

```text
processor.py: selected only the 2026-08-27 native files, accepted asml+,
			 applied the privacy guard, and generated the run-dated generic list
SEPA sample: --sample-size 20 produced 20 symbol results
SEPA full:   --sample-size 0 produced 365 symbol results
```

The full SEPA output was written to
`output/sepa_results/2026-08-27_SEPA_DIAGNOSTIC_20260827_082829.csv`.
Most symbols used `local_db`; ten symbols used `fallback_yahoo` because local
history was initially too short, and each successful fallback was cached for
future runs. This mixed source result is expected in online local-first mode.

The `asml+` source key is carried in `Source_Watchlists`. The `allopt` export
continues to be the only expected option-chain input, and its option rows are
preserved in the separate sanitized options output.

The fundamental analyzer supports the two current comparison profiles:
`base` preserves the baseline weights, while `qgr` adds capped short-interest
risk at raw weight 10. Profile-aware output filenames use uppercase labels,
such as `2026-08-27_BASE_FUNDAMENTAL_QUALIFIED_LONG.csv` and
`2026-08-27_QGR_FUNDAMENTAL_QUALIFIED_LONG.csv`. The profile is also recorded
in `Scoring_Profile`.

The next regression checks are the `qgr` comparison against `base`, the
seven-day fundamental cache skip, and the offline-only pipeline. Offline
results must use local data or report clear non-fatal insufficient-history
skips; `fallback_yahoo` must not appear in an offline run.

For a new watchlist session, wait until the market has opened and the latest
TOS exports are available. The first pass is online and validates ingestion,
refresh, candidate selection, and chart generation:

```powershell
python scripts/processor.py --input all --privacy_guard 1
python scripts/build_market_db.py --privacy_guard 1 --batch-size 20 --pause-seconds 60
python scripts/sepa_matrix.py --watchlist-key all --sample-size 0 --download-missing 1
python scripts/fundamental_analyzer.py --watchlist-key all --profile base --force-refresh --candidate-limit 0
python scripts/fundamental_analyzer.py --watchlist-key all --profile base --candidate-limit 20
python scripts/fundamental_analyzer.py --watchlist-key all --profile qgr --candidate-limit 20
python scripts/delta_engine.py --data-source auto
python scripts/obv5_signal_engine.py --data-source online --detailed 1 --recent_bars 7
python scripts/macro_barometer.py --data-source auto --delta-weights 1:1:2 --obv5_detailed 1 --obv5_recent_bars 7 --fundamental-candidates none
python scripts/macro_barometer.py --data-source auto --delta-weights 1:1:2 --obv5_detailed 1 --obv5_recent_bars 7 --fundamental-candidates both --fundamental-profile base --fundamental-limit 20
python scripts/macro_barometer.py --data-source auto --delta-weights 1:1:2 --obv5_detailed 1 --obv5_recent_bars 7 --fundamental-candidates both --fundamental-profile qgr --fundamental-limit 20
```

Repeat the fundamental run within the seven-day freshness window to verify
that cached provider data is reused and the download is skipped. Vary
`--candidate-limit` after the zero and twenty cases. Test both fundamental
candidate modes where supported, including `--fundamental-candidates long`,
`short`, `both`, and `none`.

For the macro-barometer comparison, keep the core settings fixed and run the
candidate overlays in this order:

```text
none                         macro/telemetry baseline only
both + profile=base + 20     baseline top 20 long and top 20 short candidates
both + profile=qgr  + 20     QGR top 20 long and top 20 short candidates
```

The default `--delta-weights 1:1:2` gives VIX:UUP:SMA effective weights of
25%:25%:50%. The optional `--delta-weights 1:1:1` run is an equal-weight
comparison, not a required production setting. For each run, record the
number of charts generated, skipped symbols, source/cache behavior, output
file names, consensus percentage, defensive level, long/cover multiplier,
and short/close multiplier. Candidate overlays should not change the core
macro consensus, which is calculated from SPY, QQQ, DIA, and IWM.

After the online pass, run the same workflow offline using only the local
database and sanitized watchlists:

```powershell
python scripts/processor.py --input all --privacy_guard 1 --offline
python scripts/sepa_matrix.py --watchlist-key all --sample-size 0 --offline
python scripts/fundamental_analyzer.py --watchlist-key all --profile base --offline --candidate-limit 20
python scripts/fundamental_analyzer.py --watchlist-key all --profile qgr --offline --candidate-limit 20
python scripts/delta_engine.py --data-source local --window 252 --range 400 --shift 0
python scripts/obv5_signal_engine.py --data-source local --detailed 1 --recent_bars 7 --shift 0
python scripts/macro_barometer.py --data-source local --window 252 --range 400 --shift 0 --obv5_detailed 1 --obv5_recent_bars 7 --fundamental-candidates both
```

The offline pass must not make network requests. Repeat the macro and OBV5
runs with `recent_bars` values such as `9`, with detailed mode disabled, and
with non-zero shifts such as `--shift -7`. The default stress case is
`window=252`, `range=400`, and a non-zero shift. A local database may not have
enough history for the resulting delta, SMA, or OBV5 lookback.

When local history is insufficient, the script must skip the affected
symbol or calculation, continue where possible, and report a clear reason,
including the required and available date or bar range when available. It
must not fabricate values, silently present a shortened calculation as
complete, or fall back to an online download. These are successful offline
outcomes; the same cases can be completed later in online mode after the
additional history is cached.

Before any run that may backfill data, create a database backup:

```powershell
python scripts/maintain_market_db.py backup
```

The final macro run generates the chart pages and viewer under
`output/charts/`. Review the P5 signals in `output/obv5_engine/` and the
corresponding chart views. Confirm that chart outputs use the current
watchlist/session date and that valid partial results remain available when
individual symbols are skipped.

## Database Maintenance

Run a read-only integrity and coverage check:

```powershell
python scripts/maintain_market_db.py check
```

Create a verified timestamped backup:

```powershell
python scripts/maintain_market_db.py backup
```

Restore a specific backup. The current database is backed up automatically
before replacement:

```powershell
python scripts/maintain_market_db.py restore --source data/database_backups/quant_terminal_YYYYMMDDTHHMMSSZ.db
```

Backups are complete SQLite database files, not partial chunks. Ignore any
leftover `.db.tmp` file; it is an incomplete temporary artifact and cannot be
used for restore.

## Offline Design

The intended architecture is local-first:

```text
Online acquisition -> SQLite and sanitized snapshots -> offline analysis
```

SEPA and fundamentals can already run offline. Macro-barometer data source
selection is explicit:

```powershell
python scripts/macro_barometer.py --data-source local
python scripts/macro_barometer.py --data-source auto
python scripts/macro_barometer.py --data-source online
```

`local` is the default and uses SQLite only. It never attempts a network
request; symbols whose local coverage is insufficient are reported and
skipped. `auto` prefers SQLite and backfills missing or insufficient history
online only when needed, caching successful bars for later local runs. If
connectivity is unavailable, the backfill failure is reported and that symbol
is skipped without aborting the complete run. `online` preserves the legacy
direct-download path as an explicit safety option. OBV5 and delta calculations
now use the modular local-first engines, and analysis should report
insufficient local coverage explicitly rather than silently reaching the
network.

Two offline conventions are in use. `processor.py`, `sepa_matrix.py`, and
`fundamental_analyzer.py` take an `--offline` switch, while
`macro_barometer.py` and `obv5_signal_engine.py` take `--data-source`. There
is no `--data-source offline`; the equivalent is `--data-source local`:

```powershell
python scripts/sepa_matrix.py --watchlist-key all --sample-size 0 --offline
python scripts/obv5_signal_engine.py --symbols all --data-source local
```

A full local-first refresh runs acquisition before analysis, because the hits
variants and chart universe are only rebuilt when their producing script runs:

```powershell
python scripts/processor.py --input all
python scripts/sepa_matrix.py --watchlist-key all --sample-size 0 --download-missing 1
python scripts/fundamental_analyzer.py --watchlist-key all --force-refresh
python scripts/obv5_signal_engine.py --symbols all --data-source auto --recent_bars 7
python scripts/macro_barometer.py --data-source auto --obv5-candidates p4_all
```

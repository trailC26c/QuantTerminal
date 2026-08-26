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

The normal keys are `core`, `long`, `allopt`, `allpos`, and `others`.
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
After the complete matrix is written, the analyzer also creates timestamped
candidate views using the configured weights and limits:

```text
<date>_FUNDAMENTAL_QUALIFIED_LONG.csv
<date>_FUNDAMENTAL_QUALIFIED_SHORT.csv
<date>_FUNDAMENTAL_UNQUALIFIED.csv
```

The complete `*_watchlist_all_FUND_PROCESSED.csv` matrix remains intact. The
candidate views add `Fundamental_Score`, `Fundamental_Rank`,
`Fundamental_Qualification`, `Fundamental_Data_Completeness`, and
`Fundamental_Score_Model`.

All three outputs carry the same analyst-reference fields:

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

The default top-candidate count is configured as `candidate_limit: 20` in
`data/fundamental_scoring.json`. Override both long and short counts for one
run, for example:

```powershell
python scripts/fundamental_analyzer.py --watchlist-key all --candidate-limit 30
```

For combined `all` runs, curated telemetry symbols tagged with `generic` can
remain visible beyond the top-candidate limit when their score is directional.
This is controlled by `include_generic_overflow` and the
`generic_long_min_score` / `generic_short_max_score` thresholds in the same
configuration file. The candidate output records whether a row came from the
main score limit or from generic overflow in `Candidate_Selection_Reason`.

## OBV5 Next Phase

OBV5 is the next major development phase and remains separate from this
stable checkpoint. It will follow fundamental qualification and SEPA stage
analysis as an action-timing confirmation layer.

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

The durable representation should be long-format, one row per signal event,
with a generated wide summary for charting and quick review. Green signals
represent the buy-side/minimum interpretation; red signals represent the
sell-side/maximum interpretation.

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

P5 initially remains an evidence and validation feature rather than an
automatic action rule. OBV5 charting and signal logic will be consolidated
from the existing macro-barometer implementation in the next checkpoint.

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
direct-download path as an explicit safety option. The later OBV5
consolidation remains a planned follow-up, and analysis should report
insufficient local coverage explicitly rather than silently reaching the
network.

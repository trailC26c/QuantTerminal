"""SQLite storage for dated watchlist observations and cached market bars."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS assets (
    asset_id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    asset_type TEXT NOT NULL,
    underlying_symbol TEXT,
    first_seen_date TEXT NOT NULL,
    last_seen_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist_memberships (
    asset_id INTEGER NOT NULL REFERENCES assets(asset_id),
    watchlist_key TEXT NOT NULL,
    session_date TEXT NOT NULL,
    source_file TEXT NOT NULL,
    PRIMARY KEY (asset_id, watchlist_key, session_date)
);

CREATE TABLE IF NOT EXISTS watchlist_observations (
    observation_id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(asset_id),
    watchlist_key TEXT NOT NULL,
    session_date TEXT NOT NULL,
    source_file TEXT NOT NULL,
    row_json TEXT NOT NULL,
    UNIQUE (asset_id, watchlist_key, session_date, source_file)
);

CREATE TABLE IF NOT EXISTS market_bars (
    asset_id INTEGER NOT NULL REFERENCES assets(asset_id),
    bar_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    adjusted_close REAL,
    volume REAL,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (asset_id, bar_date)
);

CREATE TABLE IF NOT EXISTS download_status (
    asset_id INTEGER PRIMARY KEY REFERENCES assets(asset_id),
    status TEXT NOT NULL,
    requested_period TEXT NOT NULL,
    bars_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS fundamental_snapshots (
    asset_id INTEGER PRIMARY KEY REFERENCES assets(asset_id),
    retrieved_at TEXT NOT NULL,
    metrics_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS obv5_signals (
    signal_id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(asset_id),
    signal_date TEXT NOT NULL,
    period TEXT NOT NULL,
    period_bars INTEGER NOT NULL,
    direction TEXT NOT NULL,
    bar_offset INTEGER NOT NULL,
    signal_type TEXT NOT NULL,
    signal_value REAL,
    shift_bars INTEGER NOT NULL DEFAULT 0,
    data_first_date TEXT,
    data_last_date TEXT,
    generated_at TEXT NOT NULL,
    UNIQUE (asset_id, signal_date, period, direction, bar_offset, signal_type, shift_bars)
);

CREATE INDEX IF NOT EXISTS idx_obv5_signals_asset_date
    ON obv5_signals (asset_id, signal_date);

CREATE TABLE IF NOT EXISTS delta_metrics (
    asset_id INTEGER NOT NULL REFERENCES assets(asset_id),
    bar_date TEXT NOT NULL,
    normalization_window INTEGER NOT NULL,
    range_bars INTEGER NOT NULL,
    shift_bars INTEGER NOT NULL,
    asset_close REAL,
    vix_close REAL,
    uup_close REAL,
    sma_close REAL,
    norm_asset REAL,
    norm_vix REAL,
    norm_uup REAL,
    norm_sma REAL,
    delta_vix REAL,
    delta_uup REAL,
    delta_sma REAL,
    generated_at TEXT NOT NULL,
    PRIMARY KEY (asset_id, bar_date, normalization_window, range_bars, shift_bars)
);

CREATE INDEX IF NOT EXISTS idx_delta_metrics_asset_date
    ON delta_metrics (asset_id, bar_date);

CREATE TABLE IF NOT EXISTS build_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    source_date TEXT NOT NULL,
    total_assets INTEGER NOT NULL DEFAULT 0,
    completed_assets INTEGER NOT NULL DEFAULT 0,
    batch_size INTEGER NOT NULL,
    pause_seconds INTEGER NOT NULL,
    progress_path TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_market_bars_asset_date
    ON market_bars (asset_id, bar_date);

CREATE VIEW IF NOT EXISTS market_bar_coverage AS
SELECT
    a.symbol,
    a.asset_type,
    COUNT(mb.bar_date) AS bar_count,
    MIN(mb.bar_date) AS first_bar_date,
    MAX(mb.bar_date) AS last_bar_date,
    MAX(mb.retrieved_at) AS last_retrieved_at
FROM assets AS a
LEFT JOIN market_bars AS mb ON mb.asset_id = a.asset_id
GROUP BY a.asset_id, a.symbol, a.asset_type;
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class LocalDataStore:
    """Small transaction-oriented wrapper around the project SQLite database."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def start_run(
        self,
        run_id: str,
        source_date: str,
        total_assets: int,
        batch_size: int,
        pause_seconds: int,
        progress_path: Path,
    ) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO build_runs
            (run_id, started_at, status, source_date, total_assets, completed_assets,
             batch_size, pause_seconds, progress_path)
            VALUES (?, ?, 'running', ?, ?, 0, ?, ?, ?)""",
            (run_id, utc_now(), source_date, total_assets, batch_size, pause_seconds, str(progress_path)),
        )
        self.connection.commit()

    def finish_run(self, run_id: str, status: str, error: str | None = None) -> None:
        self.connection.execute(
            "UPDATE build_runs SET completed_at = ?, status = ?, error = ? WHERE run_id = ?",
            (utc_now(), status, error, run_id),
        )
        self.connection.commit()

    def update_run_progress(self, run_id: str, completed_assets: int) -> None:
        self.connection.execute(
            "UPDATE build_runs SET completed_assets = ? WHERE run_id = ?",
            (completed_assets, run_id),
        )
        self.connection.commit()

    def upsert_asset(
        self,
        symbol: str,
        asset_type: str,
        underlying_symbol: str | None,
        session_date: str,
    ) -> int:
        self.connection.execute(
            """INSERT INTO assets
            (symbol, asset_type, underlying_symbol, first_seen_date, last_seen_date)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                asset_type = excluded.asset_type,
                underlying_symbol = COALESCE(excluded.underlying_symbol, assets.underlying_symbol),
                first_seen_date = MIN(assets.first_seen_date, excluded.first_seen_date),
                last_seen_date = MAX(assets.last_seen_date, excluded.last_seen_date)""",
            (symbol, asset_type, underlying_symbol, session_date, session_date),
        )
        asset_id = self.connection.execute(
            "SELECT asset_id FROM assets WHERE symbol = ?", (symbol,)
        ).fetchone()[0]
        return int(asset_id)

    def save_observation(
        self,
        asset_id: int,
        watchlist_key: str,
        session_date: str,
        source_file: str,
        row: dict[str, Any],
    ) -> None:
        row_json = json.dumps(row, ensure_ascii=False, default=str, sort_keys=True)
        self.connection.execute(
            """INSERT OR REPLACE INTO watchlist_memberships
            (asset_id, watchlist_key, session_date, source_file)
            VALUES (?, ?, ?, ?)""",
            (asset_id, watchlist_key, session_date, source_file),
        )
        self.connection.execute(
            """INSERT OR REPLACE INTO watchlist_observations
            (asset_id, watchlist_key, session_date, source_file, row_json)
            VALUES (?, ?, ?, ?, ?)""",
            (asset_id, watchlist_key, session_date, source_file, row_json),
        )

    def save_bars(self, asset_id: int, bars: Iterable[tuple[Any, ...]]) -> int:
        rows = list(bars)
        self.connection.executemany(
            """INSERT OR REPLACE INTO market_bars
            (asset_id, bar_date, open, high, low, close, adjusted_close, volume, retrieved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(asset_id, *row, utc_now()) for row in rows],
        )
        return len(rows)

    def save_download_status(
        self,
        asset_id: int,
        status: str,
        requested_period: str,
        bars_count: int,
        error: str | None = None,
    ) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO download_status
            (asset_id, status, requested_period, bars_count, last_attempt_at, error)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (asset_id, status, requested_period, bars_count, utc_now(), error),
        )

    def commit(self) -> None:
        self.connection.commit()

    def cached_symbols(self, symbols: Iterable[str], requested_period: str) -> set[str]:
        symbol_list = list(symbols)
        if not symbol_list:
            return set()
        placeholders = ",".join("?" for _ in symbol_list)
        rows = self.connection.execute(
            f"""SELECT a.symbol FROM assets a
            JOIN download_status d ON d.asset_id = a.asset_id
            WHERE a.symbol IN ({placeholders})
              AND d.status = 'complete' AND d.requested_period = ?""",
            (*symbol_list, requested_period),
        ).fetchall()
        return {str(row[0]) for row in rows}

    def market_data_coverage(self, symbols: Iterable[str]) -> list[dict[str, Any]]:
        """Return compact stored-history coverage metadata for the requested symbols."""
        symbol_list = list(symbols)
        if not symbol_list:
            return []
        placeholders = ",".join("?" for _ in symbol_list)
        rows = self.connection.execute(
            f"""SELECT symbol, asset_type, bar_count, first_bar_date,
                      last_bar_date, last_retrieved_at
                FROM market_bar_coverage
                WHERE symbol IN ({placeholders})
                ORDER BY symbol""",
            symbol_list,
        ).fetchall()
        columns = (
            "symbol",
            "asset_type",
            "bar_count",
            "first_bar_date",
            "last_bar_date",
            "last_retrieved_at",
        )
        return [dict(zip(columns, row)) for row in rows]

    def market_bars(self, symbol: str) -> list[tuple[Any, ...]]:
        """Return stored daily bars for one symbol in date order."""
        rows = self.connection.execute(
            """SELECT mb.bar_date, mb.open, mb.high, mb.low, mb.close,
                      mb.adjusted_close, mb.volume
               FROM market_bars AS mb
               JOIN assets AS a ON a.asset_id = mb.asset_id
               WHERE a.symbol = ?
               ORDER BY mb.bar_date""",
            (symbol,),
        ).fetchall()
        return rows

    def known_symbols(self) -> list[str]:
        """Return all locally known asset symbols in stable order."""
        rows = self.connection.execute(
            "SELECT symbol FROM assets ORDER BY symbol"
        ).fetchall()
        return [str(row[0]) for row in rows]

    def get_fundamental_snapshot(self, symbol: str, max_age_days: int) -> dict[str, Any] | None:
        """Return a recent fundamental snapshot, or None when it needs refresh."""
        row = self.connection.execute(
            """SELECT fs.retrieved_at, fs.metrics_json
               FROM fundamental_snapshots AS fs
               JOIN assets AS a ON a.asset_id = fs.asset_id
               WHERE a.symbol = ?""",
            (symbol,),
        ).fetchone()
        if row is None:
            return None
        retrieved_at = datetime.fromisoformat(str(row[0]))
        age_days = (datetime.now(timezone.utc) - retrieved_at).total_seconds() / 86400
        if age_days > max_age_days:
            return None
        metrics = json.loads(row[1])
        metrics["_snapshot_retrieved_at"] = str(row[0])
        metrics["_snapshot_age_days"] = round(age_days, 2)
        return metrics

    def save_fundamental_snapshot(self, asset_id: int, metrics: dict[str, Any]) -> None:
        """Persist the latest provider metrics for one asset."""
        stored_metrics = {key: value for key, value in metrics.items() if not key.startswith("_")}
        self.connection.execute(
            """INSERT OR REPLACE INTO fundamental_snapshots
               (asset_id, retrieved_at, metrics_json)
               VALUES (?, ?, ?)""",
            (asset_id, utc_now(), json.dumps(stored_metrics, ensure_ascii=False, default=str, sort_keys=True)),
        )

    def save_obv5_signals(self, asset_id: int, signals: Iterable[dict[str, Any]]) -> int:
        """Upsert period-aware OBV5 signals while preserving historical runs."""
        rows = list(signals)
        self.connection.executemany(
            """INSERT INTO obv5_signals
               (asset_id, signal_date, period, period_bars, direction, bar_offset,
                signal_type, signal_value, shift_bars, data_first_date,
                data_last_date, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(asset_id, signal_date, period, direction, bar_offset,
                           signal_type, shift_bars) DO UPDATE SET
                   period_bars = excluded.period_bars,
                   signal_value = excluded.signal_value,
                   data_first_date = excluded.data_first_date,
                   data_last_date = excluded.data_last_date,
                   generated_at = excluded.generated_at""",
            [
                (
                    asset_id,
                    signal["signal_date"],
                    signal["period"],
                    signal["period_bars"],
                    signal["direction"],
                    signal["bar_offset"],
                    signal["signal_type"],
                    signal.get("signal_value"),
                    signal.get("shift_bars", 0),
                    signal.get("data_first_date"),
                    signal.get("data_last_date"),
                    utc_now(),
                )
                for signal in rows
            ],
        )
        return len(rows)

    def save_delta_metrics(self, asset_id: int, metrics: Iterable[dict[str, Any]]) -> int:
        """Upsert normalized daily delta metrics for one asset and parameter set."""
        rows = list(metrics)
        self.connection.executemany(
            """INSERT INTO delta_metrics
               (asset_id, bar_date, normalization_window, range_bars, shift_bars,
                asset_close, vix_close, uup_close, sma_close, norm_asset, norm_vix,
                norm_uup, norm_sma, delta_vix, delta_uup, delta_sma, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(asset_id, bar_date, normalization_window, range_bars, shift_bars)
               DO UPDATE SET asset_close = excluded.asset_close,
                   vix_close = excluded.vix_close, uup_close = excluded.uup_close,
                   sma_close = excluded.sma_close, norm_asset = excluded.norm_asset,
                   norm_vix = excluded.norm_vix, norm_uup = excluded.norm_uup,
                   norm_sma = excluded.norm_sma, delta_vix = excluded.delta_vix,
                   delta_uup = excluded.delta_uup, delta_sma = excluded.delta_sma,
                   generated_at = excluded.generated_at""",
            [
                (
                    asset_id, metric["bar_date"], metric["normalization_window"],
                    metric["range_bars"], metric["shift_bars"], metric.get("asset_close"),
                    metric.get("vix_close"), metric.get("uup_close"), metric.get("sma_close"),
                    metric.get("norm_asset"), metric.get("norm_vix"), metric.get("norm_uup"),
                    metric.get("norm_sma"), metric.get("delta_vix"), metric.get("delta_uup"),
                    metric.get("delta_sma"), utc_now(),
                )
                for metric in rows
            ],
        )
        return len(rows)

    def delta_metrics(
        self,
        symbol: str,
        normalization_window: int,
        range_bars: int,
        shift_bars: int,
    ) -> list[dict[str, Any]]:
        """Return stored delta metrics for one symbol and exact calculation parameters."""
        rows = self.connection.execute(
            """SELECT dm.bar_date, dm.normalization_window, dm.range_bars, dm.shift_bars,
                      dm.asset_close, dm.vix_close, dm.uup_close, dm.sma_close,
                      dm.norm_asset, dm.norm_vix, dm.norm_uup, dm.norm_sma,
                      dm.delta_vix, dm.delta_uup, dm.delta_sma, dm.generated_at
               FROM delta_metrics AS dm
               JOIN assets AS a ON a.asset_id = dm.asset_id
               WHERE a.symbol = ? AND dm.normalization_window = ?
                 AND dm.range_bars = ? AND dm.shift_bars = ?
               ORDER BY dm.bar_date""",
            (symbol, normalization_window, range_bars, shift_bars),
        ).fetchall()
        columns = (
            "bar_date", "normalization_window", "range_bars", "shift_bars",
            "asset_close", "vix_close", "uup_close", "sma_close", "norm_asset",
            "norm_vix", "norm_uup", "norm_sma", "delta_vix", "delta_uup",
            "delta_sma", "generated_at",
        )
        return [dict(zip(columns, row)) for row in rows]

    def obv5_signals(self, symbol: str, signal_date: str | None = None) -> list[dict[str, Any]]:
        """Return stored OBV5 signals with period and offset evidence."""
        parameters: list[Any] = [symbol]
        date_filter = ""
        if signal_date is not None:
            date_filter = "AND os.signal_date = ?"
            parameters.append(signal_date)
        rows = self.connection.execute(
            f"""SELECT os.signal_date, os.period, os.period_bars, os.direction,
                      os.bar_offset, os.signal_type, os.signal_value, os.shift_bars,
                      os.data_first_date, os.data_last_date, os.generated_at
               FROM obv5_signals AS os
               JOIN assets AS a ON a.asset_id = os.asset_id
               WHERE a.symbol = ? {date_filter}
               ORDER BY os.signal_date, os.bar_offset, os.period""",
            parameters,
        ).fetchall()
        columns = (
            "signal_date", "period", "period_bars", "direction", "bar_offset",
            "signal_type", "signal_value", "shift_bars", "data_first_date",
            "data_last_date", "generated_at",
        )
        return [dict(zip(columns, row)) for row in rows]

    def asset_id(self, symbol: str) -> int:
        row = self.connection.execute(
            "SELECT asset_id FROM assets WHERE symbol = ?", (symbol,)
        ).fetchone()
        if row is None:
            raise KeyError(symbol)
        return int(row[0])

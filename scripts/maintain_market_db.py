"""Maintain, verify, and restore the local QuantTerminal SQLite database."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_DIR / "data" / "quant_terminal.db"
DEFAULT_BACKUP_DIR = PROJECT_DIR / "data" / "database_backups"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def connect(path: Path, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def integrity_report(database: Path) -> dict[str, object]:
    if not database.exists():
        raise FileNotFoundError(f"Database does not exist: {database}")
    connection = connect(database, read_only=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        counts = {}
        for table in ("assets", "watchlist_memberships", "watchlist_observations", "market_bars", "download_status", "build_runs"):
            counts[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        coverage = connection.execute(
            """SELECT COUNT(*),
                      COALESCE(SUM(CASE WHEN bar_count > 0 THEN 1 ELSE 0 END), 0),
                      MIN(first_bar_date), MAX(last_bar_date)
               FROM (
                   SELECT a.asset_id, COUNT(mb.bar_date) AS bar_count,
                          MIN(mb.bar_date) AS first_bar_date,
                          MAX(mb.bar_date) AS last_bar_date
                   FROM assets AS a
                   LEFT JOIN market_bars AS mb ON mb.asset_id = a.asset_id
                   GROUP BY a.asset_id
               )"""
        ).fetchone()
    finally:
        connection.close()
    return {
        "database": str(database),
        "integrity_check": integrity,
        "foreign_key_errors": len(foreign_keys),
        "table_counts": counts,
        "coverage": {
            "assets_with_coverage_rows": coverage[0],
            "assets_with_bars": coverage[1],
            "earliest_bar_date": coverage[2],
            "latest_bar_date": coverage[3],
        },
    }


def require_healthy(database: Path) -> dict[str, object]:
    report = integrity_report(database)
    if report["integrity_check"] != "ok" or report["foreign_key_errors"]:
        raise RuntimeError(f"Integrity check failed: {report}")
    return report


def backup_database(database: Path, destination: Path) -> dict[str, object]:
    require_healthy(database)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    source = connect(database, read_only=True)
    target = sqlite3.connect(temporary)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    temporary.replace(destination)
    report = require_healthy(destination)
    report["backup"] = str(destination)
    return report


def default_backup_path() -> Path:
    return DEFAULT_BACKUP_DIR / f"quant_terminal_{utc_stamp()}.db"


def restore_database(source: Path, destination: Path, backup_current: bool) -> dict[str, object]:
    if source.name.lower().endswith(".db.tmp"):
        raise ValueError(f"Temporary backup files cannot be restored: {source}")
    require_healthy(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if backup_current and destination.exists():
        current_backup = DEFAULT_BACKUP_DIR / f"quant_terminal_pre_restore_{utc_stamp()}.db"
        backup_database(destination, current_backup)
        print(f"Current database backed up to: {current_backup}")

    temporary = destination.with_suffix(destination.suffix + ".restore.tmp")
    if temporary.exists():
        temporary.unlink()
    source_connection = connect(source, read_only=True)
    target = sqlite3.connect(temporary)
    try:
        source_connection.backup(target)
    finally:
        target.close()
        source_connection.close()
    require_healthy(temporary)
    temporary.replace(destination)
    report = require_healthy(destination)
    report["restored_from"] = str(source)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Maintain the QuantTerminal local market database")
    parser.add_argument("command", choices=("check", "backup", "restore"))
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--destination", type=Path, help="Backup destination or restore target")
    parser.add_argument("--source", type=Path, help="Backup database used for restore")
    parser.add_argument("--no-current-backup", action="store_true", help="Do not back up the current database before restore")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "check":
        report = require_healthy(args.database)
    elif args.command == "backup":
        report = backup_database(args.database, args.destination or default_backup_path())
    else:
        if args.source is None:
            raise SystemExit("restore requires --source")
        report = restore_database(args.source, args.destination or args.database, not args.no_current_backup)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

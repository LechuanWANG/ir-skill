"""Versioned SQLite migrations for market-data extensions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


MIGRATION_TABLE = "market_data_schema_migration"


@dataclass(frozen=True)
class MarketDataTableNames:
    sector_master: str
    sector_daily: str
    sector_flow_daily: str
    sector_membership: str


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection, MarketDataTableNames], None]


def applied_market_data_migrations(connection: sqlite3.Connection) -> dict[int, str]:
    """Return migration versions already recorded by an existing database."""

    table_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (MIGRATION_TABLE,),
    ).fetchone()
    if not table_exists:
        return {}
    return {
        int(version): str(name)
        for version, name in connection.execute(
            f"SELECT version, name FROM {MIGRATION_TABLE}"
        )
    }


def pending_market_data_migrations(connection: sqlite3.Connection) -> tuple[Migration, ...]:
    """Return unapplied migrations and reject incompatible historical records."""

    applied = applied_market_data_migrations(connection)
    pending: list[Migration] = []
    for migration in MIGRATIONS:
        applied_name = applied.get(migration.version)
        if applied_name is None:
            pending.append(migration)
        elif applied_name != migration.name:
            raise RuntimeError(
                "数据库迁移版本与当前代码不一致："
                f"{migration.version} 已记录为 {applied_name!r}，当前为 {migration.name!r}。"
            )
    return tuple(pending)


def backup_database_before_migration(db_path: Path) -> Path:
    """Create a verified SQLite backup next to an existing database."""

    source_path = Path(db_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"无法备份不存在的数据库：{source_path}")
    timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    destination = source_path.with_name(
        f"{source_path.stem}.pre-migration-{timestamp}{source_path.suffix}"
    )
    suffix = 1
    while destination.exists():
        destination = source_path.with_name(
            f"{source_path.stem}.pre-migration-{timestamp}-{suffix}{source_path.suffix}"
        )
        suffix += 1
    with sqlite3.connect(source_path) as source, sqlite3.connect(destination) as backup:
        source.backup(backup)
        integrity = backup.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"迁移前备份完整性检查失败：{integrity}")
    return destination


def _create_sector_data_tables(connection: sqlite3.Connection, tables: MarketDataTableNames) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {tables.sector_master} (
            provider TEXT NOT NULL,
            sector_code TEXT NOT NULL,
            sector_name TEXT,
            sector_type TEXT,
            exchange TEXT,
            payload_json TEXT NOT NULL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (provider, sector_code)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {tables.sector_daily} (
            provider TEXT NOT NULL,
            sector_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            sector_name TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            pre_close REAL,
            change REAL,
            pct_chg REAL,
            vol REAL,
            amount REAL,
            turnover_rate REAL,
            payload_json TEXT NOT NULL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (provider, sector_code, trade_date)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {tables.sector_flow_daily} (
            provider TEXT NOT NULL,
            sector_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            sector_name TEXT,
            pct_chg REAL,
            company_num REAL,
            lead_stock TEXT,
            lead_stock_pct_chg REAL,
            net_buy_amount REAL,
            net_sell_amount REAL,
            net_amount REAL,
            payload_json TEXT NOT NULL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (provider, sector_code, trade_date)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {tables.sector_membership} (
            dataset TEXT NOT NULL,
            index_code TEXT NOT NULL,
            con_code TEXT NOT NULL,
            trade_date TEXT,
            in_date TEXT,
            out_date TEXT,
            name TEXT,
            payload_json TEXT NOT NULL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (dataset, index_code, con_code, trade_date, in_date)
        )
        """
    )
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{tables.sector_daily}_date_provider
        ON {tables.sector_daily} (trade_date, provider, pct_chg)
        """
    )
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{tables.sector_flow_daily}_date_provider
        ON {tables.sector_flow_daily} (trade_date, provider, net_amount)
        """
    )
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{tables.sector_membership}_constituent
        ON {tables.sector_membership} (dataset, con_code, trade_date)
        """
    )


MIGRATIONS = (
    Migration(1, "sector_data_tables", _create_sector_data_tables),
)


def apply_market_data_migrations(
    connection: sqlite3.Connection,
    *,
    tables: MarketDataTableNames,
) -> list[int]:
    """Apply missing extension migrations atomically and return applied versions."""

    connection.execute("SAVEPOINT market_data_migrations")
    try:
        pending = pending_market_data_migrations(connection)
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied_now: list[int] = []
        for migration in pending:
            migration.apply(connection, tables)
            connection.execute(
                f"INSERT INTO {MIGRATION_TABLE} (version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
            applied_now.append(migration.version)
        if applied_now:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"数据库完整性检查失败：{integrity}")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT market_data_migrations")
        connection.execute("RELEASE SAVEPOINT market_data_migrations")
        raise
    connection.execute("RELEASE SAVEPOINT market_data_migrations")
    return applied_now

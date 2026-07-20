#!/usr/bin/env python3
"""SQLite-backed market data store helpers for local investment research."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from market_data_migrations import (
    MarketDataTableNames,
    apply_market_data_migrations,
    backup_database_before_migration,
    pending_market_data_migrations,
)
from project_context import project_paths


# Resolve once per process so command-line defaults always belong to the selected project,
# never to the installed Skill package.
DEFAULT_DB_PATH = project_paths().database_path
DAILY_TABLE = "a_share_daily"
DAILY_BASIC_TABLE = "a_share_daily_basic"
FINA_INDICATOR_TABLE = "a_share_fina_indicator"
STOCK_BASIC_TABLE = "a_share_stock_basic"
RESEARCH_OBSERVATION_TABLE = "tushare_research_observation"
TUSHARE_CAPABILITY_TABLE = "tushare_capability"
TRADING_CALENDAR_TABLE = "market_trading_calendar"
INDEX_DAILY_TABLE = "market_index_daily"
INDEX_DAILY_BASIC_TABLE = "market_index_daily_basic"
INDUSTRY_CLASSIFICATION_TABLE = "market_industry_classification"
INDEX_MEMBER_TABLE = "market_index_member"
INDEX_WEIGHT_TABLE = "market_index_weight"
MARKET_DAILY_INFO_TABLE = "market_daily_info"
MARKET_MONEYFLOW_TABLE = "market_moneyflow"
MARKET_MARGIN_TABLE = "market_margin"
MARKET_FLOW_DAILY_TABLE = "market_flow_daily"
LIMIT_EVENT_DAILY_TABLE = "limit_event_daily"
SECTOR_MASTER_TABLE = "market_sector_master"
SECTOR_DAILY_TABLE = "market_sector_daily"
SECTOR_FLOW_DAILY_TABLE = "market_sector_flow_daily"
SECTOR_MEMBERSHIP_TABLE = "sector_membership_daily"
CHIP_DISTRIBUTION_TABLE = "chip_distribution_daily"
FACTOR_DAILY_TABLE = "factor_daily"
INSTITUTIONAL_RESEARCH_TABLE = "institutional_research"
CORPORATE_EVENTS_TABLE = "corporate_events"
NORMALIZED_ENDPOINT_DATE_TABLES = {
    "daily": DAILY_TABLE,
    "daily_basic": DAILY_BASIC_TABLE,
    "index_daily": INDEX_DAILY_TABLE,
    "moneyflow": MARKET_FLOW_DAILY_TABLE,
}
SECTOR_MASTER_ENDPOINT_PROVIDERS = {
    "ths_index": "ths",
    "dc_index": "dc",
    "tdx_index": "tdx",
}
SECTOR_DAILY_ENDPOINT_PROVIDERS = {
    "ths_daily": "ths",
    "dc_daily": "dc",
    "tdx_daily": "tdx",
}
SECTOR_MEMBER_ENDPOINT_PROVIDERS = {
    "ths_member": "ths",
    "dc_member": "dc",
    "tdx_member": "tdx",
}

RESEARCH_IDENTITY_FIELDS = (
    "ts_code",
    "trade_date",
    "end_date",
    "report_date",
    "surv_date",
    "float_date",
    "cal_date",
    "month",
    "date",
    "index_code",
    "con_code",
    "exchange",
    "org_name",
    "holder_name",
    "holder_type",
    "report_type",
    "comp_type",
    "end_type",
)

DAILY_BASIC_NUMERIC_FIELDS = [
    "close",
    "turnover_rate",
    "volume_ratio",
    "pe",
    "pe_ttm",
    "pb",
    "ps",
    "ps_ttm",
    "dv_ratio",
    "dv_ttm",
    "total_mv",
    "circ_mv",
    "total_share",
    "float_share",
    "free_share",
]

FINA_INDICATOR_NUMERIC_FIELDS = [
    "roe",
    "roe_dt",
    "roa",
    "netprofit_margin",
    "grossprofit_margin",
    "netprofit_yoy",
    "or_yoy",
    "debt_to_assets",
    "current_ratio",
    "quick_ratio",
    "ocf_to_or",
    "bps",
    "eps",
]

STOCK_BASIC_TEXT_FIELDS = ["name", "industry", "market", "list_date"]

INDEX_DAILY_NUMERIC_FIELDS = [
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
]

INDEX_DAILY_BASIC_NUMERIC_FIELDS = [
    "total_mv",
    "float_mv",
    "total_share",
    "float_share",
    "free_share",
    "turnover_rate",
    "turnover_rate_f",
    "pe",
    "pe_ttm",
    "pb",
]

MARKET_DAILY_INFO_NUMERIC_FIELDS = [
    "com_count",
    "total_share",
    "float_share",
    "total_mv",
    "float_mv",
    "amount",
    "vol",
    "trans_count",
    "pe",
    "tr",
]

MARKET_MONEYFLOW_NUMERIC_FIELDS = [
    "close_sh",
    "pct_change_sh",
    "close_sz",
    "pct_change_sz",
    "net_amount",
    "net_amount_rate",
    "buy_elg_amount",
    "buy_elg_amount_rate",
    "buy_lg_amount",
    "buy_lg_amount_rate",
    "buy_md_amount",
    "buy_md_amount_rate",
    "buy_sm_amount",
    "buy_sm_amount_rate",
]

MARKET_MARGIN_NUMERIC_FIELDS = [
    "rzye",
    "rzmre",
    "rzche",
    "rqye",
    "rqmcl",
    "rzrqye",
    "rqyl",
]

SECTOR_DAILY_NUMERIC_FIELDS = [
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
    "turnover_rate",
]

SECTOR_FLOW_NUMERIC_FIELDS = [
    "pct_chg",
    "company_num",
    "lead_stock_pct_chg",
    "net_buy_amount",
    "net_sell_amount",
    "net_amount",
]


def normalize_trade_date(value: object) -> str:
    text = str(value).strip()
    if text.isdigit() and len(text) == 8:
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return pd.Timestamp(value).date().isoformat()


def _normalize_optional_date(value: object) -> str | None:
    if pd.isna(value) or str(value).strip() == "":
        return None
    return normalize_trade_date(value)


def _research_business_key(
    dataset: str,
    payload: Mapping[str, object],
    row_hash: str,
) -> str:
    identity: dict[str, str] = {}
    for field in RESEARCH_IDENTITY_FIELDS:
        value = payload.get(field)
        if value is None or str(value).strip() == "":
            continue
        text = str(value).strip()
        if field.endswith("date") or field in {"trade_date", "month"}:
            try:
                text = normalize_trade_date(value)
            except (TypeError, ValueError):
                pass
        identity[field] = text
    if not any(field in identity for field in ("trade_date", "end_date", "report_date", "surv_date", "float_date", "cal_date", "month", "date")):
        ann_date = payload.get("ann_date") or payload.get("f_ann_date")
        if ann_date is not None and str(ann_date).strip():
            try:
                identity["ann_date"] = normalize_trade_date(ann_date)
            except (TypeError, ValueError):
                identity["ann_date"] = str(ann_date).strip()
    if not identity:
        return f"row:{row_hash}"
    encoded = json.dumps(
        {"dataset": dataset, "identity": identity},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {DAILY_TABLE} (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            close_qfq REAL,
            high_qfq REAL,
            low_qfq REAL,
            volume REAL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, ts_code)
        )
        """
    )
    daily_columns = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({DAILY_TABLE})")
    }
    for column in ("high_qfq", "low_qfq"):
        if column not in daily_columns:
            connection.execute(f"ALTER TABLE {DAILY_TABLE} ADD COLUMN {column} REAL")
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{DAILY_TABLE}_ts_code_date
        ON {DAILY_TABLE} (ts_code, trade_date)
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {DAILY_BASIC_TABLE} (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            close REAL,
            turnover_rate REAL,
            volume_ratio REAL,
            pe REAL,
            pe_ttm REAL,
            pb REAL,
            ps REAL,
            ps_ttm REAL,
            dv_ratio REAL,
            dv_ttm REAL,
            total_mv REAL,
            circ_mv REAL,
            total_share REAL,
            float_share REAL,
            free_share REAL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, ts_code)
        )
        """
    )
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{DAILY_BASIC_TABLE}_ts_code_date
        ON {DAILY_BASIC_TABLE} (ts_code, trade_date)
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {FINA_INDICATOR_TABLE} (
            end_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            ann_date TEXT,
            roe REAL,
            roe_dt REAL,
            roa REAL,
            netprofit_margin REAL,
            grossprofit_margin REAL,
            netprofit_yoy REAL,
            or_yoy REAL,
            debt_to_assets REAL,
            current_ratio REAL,
            quick_ratio REAL,
            ocf_to_or REAL,
            bps REAL,
            eps REAL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (end_date, ts_code)
        )
        """
    )
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{FINA_INDICATOR_TABLE}_ts_code_ann
        ON {FINA_INDICATOR_TABLE} (ts_code, ann_date, end_date)
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {STOCK_BASIC_TABLE} (
            ts_code TEXT PRIMARY KEY,
            name TEXT,
            industry TEXT,
            market TEXT,
            list_date TEXT,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TRADING_CALENDAR_TABLE} (
            exchange TEXT NOT NULL,
            cal_date TEXT NOT NULL,
            is_open INTEGER,
            pretrade_date TEXT,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (exchange, cal_date)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {INDEX_DAILY_TABLE} (
            ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            pre_close REAL,
            change REAL,
            pct_chg REAL,
            vol REAL,
            amount REAL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (ts_code, trade_date)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {INDEX_DAILY_BASIC_TABLE} (
            ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            total_mv REAL,
            float_mv REAL,
            total_share REAL,
            float_share REAL,
            free_share REAL,
            turnover_rate REAL,
            turnover_rate_f REAL,
            pe REAL,
            pe_ttm REAL,
            pb REAL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (ts_code, trade_date)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {INDUSTRY_CLASSIFICATION_TABLE} (
            src TEXT NOT NULL,
            index_code TEXT NOT NULL,
            industry_code TEXT,
            industry_name TEXT,
            level TEXT,
            is_pub TEXT,
            parent_code TEXT,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (src, index_code)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {INDEX_MEMBER_TABLE} (
            index_code TEXT NOT NULL,
            con_code TEXT NOT NULL,
            in_date TEXT NOT NULL,
            out_date TEXT,
            is_new TEXT,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (index_code, con_code, in_date)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {INDEX_WEIGHT_TABLE} (
            index_code TEXT NOT NULL,
            con_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            weight REAL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (index_code, con_code, trade_date)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MARKET_DAILY_INFO_TABLE} (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            ts_name TEXT,
            exchange TEXT,
            com_count REAL,
            total_share REAL,
            float_share REAL,
            total_mv REAL,
            float_mv REAL,
            amount REAL,
            vol REAL,
            trans_count REAL,
            pe REAL,
            tr REAL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, ts_code)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MARKET_MONEYFLOW_TABLE} (
            trade_date TEXT PRIMARY KEY,
            close_sh REAL,
            pct_change_sh REAL,
            close_sz REAL,
            pct_change_sz REAL,
            net_amount REAL,
            net_amount_rate REAL,
            buy_elg_amount REAL,
            buy_elg_amount_rate REAL,
            buy_lg_amount REAL,
            buy_lg_amount_rate REAL,
            buy_md_amount REAL,
            buy_md_amount_rate REAL,
            buy_sm_amount REAL,
            buy_sm_amount_rate REAL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MARKET_MARGIN_TABLE} (
            trade_date TEXT NOT NULL,
            exchange_id TEXT NOT NULL,
            rzye REAL,
            rzmre REAL,
            rzche REAL,
            rqye REAL,
            rqmcl REAL,
            rzrqye REAL,
            rqyl REAL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, exchange_id)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MARKET_FLOW_DAILY_TABLE} (
            ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            net_mf_amount REAL,
            buy_elg_amount REAL,
            buy_lg_amount REAL,
            buy_md_amount REAL,
            buy_sm_amount REAL,
            payload_json TEXT NOT NULL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (ts_code, trade_date)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {LIMIT_EVENT_DAILY_TABLE} (
            ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            name TEXT,
            limit_type TEXT,
            pct_chg REAL,
            amount REAL,
            first_time TEXT,
            last_time TEXT,
            open_times REAL,
            up_stat TEXT,
            payload_json TEXT NOT NULL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (ts_code, trade_date, limit_type)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CHIP_DISTRIBUTION_TABLE} (
            ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            price REAL,
            percent REAL,
            vol REAL,
            payload_json TEXT NOT NULL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (ts_code, trade_date, price)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {FACTOR_DAILY_TABLE} (
            ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (ts_code, trade_date)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {INSTITUTIONAL_RESEARCH_TABLE} (
            ts_code TEXT NOT NULL,
            surv_date TEXT NOT NULL,
            org_name TEXT,
            ann_date TEXT,
            payload_json TEXT NOT NULL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (ts_code, surv_date, org_name)
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CORPORATE_EVENTS_TABLE} (
            dataset TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            event_date TEXT NOT NULL,
            event_key TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (dataset, ts_code, event_date, event_key)
        )
        """
    )
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{INDEX_MEMBER_TABLE}_con_code
        ON {INDEX_MEMBER_TABLE} (con_code, in_date, out_date)
        """
    )
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{MARKET_DAILY_INFO_TABLE}_exchange_date
        ON {MARKET_DAILY_INFO_TABLE} (exchange, trade_date)
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {RESEARCH_OBSERVATION_TABLE} (
            dataset TEXT NOT NULL,
            row_hash TEXT NOT NULL,
            business_key TEXT,
            ts_code TEXT,
            event_date TEXT,
            available_at TEXT,
            payload_json TEXT NOT NULL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            first_seen_at TEXT,
            last_seen_at TEXT,
            revision INTEGER NOT NULL DEFAULT 1,
            is_current INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (dataset, row_hash)
        )
        """
    )
    existing_columns = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({RESEARCH_OBSERVATION_TABLE})")
    }
    additions = {
        "business_key": "TEXT",
        "available_at": "TEXT",
        "first_seen_at": "TEXT",
        "last_seen_at": "TEXT",
        "revision": "INTEGER NOT NULL DEFAULT 1",
        "is_current": "INTEGER NOT NULL DEFAULT 1",
    }
    for column, definition in additions.items():
        if column not in existing_columns:
            connection.execute(
                f"ALTER TABLE {RESEARCH_OBSERVATION_TABLE} ADD COLUMN {column} {definition}"
            )
    _backfill_research_observation_metadata(connection)
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{RESEARCH_OBSERVATION_TABLE}_dataset_symbol_date
        ON {RESEARCH_OBSERVATION_TABLE} (dataset, ts_code, event_date)
        """
    )
    connection.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{RESEARCH_OBSERVATION_TABLE}_business_revision
        ON {RESEARCH_OBSERVATION_TABLE} (dataset, business_key, revision, first_seen_at)
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TUSHARE_CAPABILITY_TABLE} (
            endpoint TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            status TEXT NOT NULL,
            rows_seen INTEGER NOT NULL,
            details_json TEXT NOT NULL,
            checked_at TEXT NOT NULL
        )
        """
    )
    apply_market_data_migrations(
        connection,
        tables=MarketDataTableNames(
            sector_master=SECTOR_MASTER_TABLE,
            sector_daily=SECTOR_DAILY_TABLE,
            sector_flow_daily=SECTOR_FLOW_DAILY_TABLE,
            sector_membership=SECTOR_MEMBERSHIP_TABLE,
        ),
    )


def ensure_database(db_path: Path = DEFAULT_DB_PATH) -> Path:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    if db_path.is_file():
        with closing(sqlite3.connect(db_path)) as connection:
            if pending_market_data_migrations(connection):
                backup_path = backup_database_before_migration(db_path)
    try:
        with closing(sqlite3.connect(db_path)) as connection:
            ensure_schema(connection)
            connection.commit()
    except (OSError, RuntimeError, sqlite3.Error) as error:
        if backup_path is not None:
            raise RuntimeError(
                f"SQLite 迁移失败；原数据库备份保留在 {backup_path}。"
            ) from error
        raise
    return db_path


def _matrix_to_long(frame: pd.DataFrame, value_name: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["trade_date", "ts_code", value_name])

    matrix = frame.copy()
    matrix.index = pd.to_datetime(matrix.index)
    matrix.index.name = "trade_date"
    matrix.columns = matrix.columns.astype(str)
    matrix.columns.name = "ts_code"
    return matrix.reset_index().melt(id_vars="trade_date", var_name="ts_code", value_name=value_name)


def _float_or_none(value: object) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _text_or_none(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _timestamp(retrieved_at: str | None = None) -> str:
    if retrieved_at is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    parsed = datetime.fromisoformat(str(retrieved_at).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _json_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    missing = pd.isna(value)
    if isinstance(missing, bool) and missing:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _research_event_date(payload: Mapping[str, object]) -> str | None:
    for field in ["trade_date", "ann_date", "report_date", "surv_date", "float_date", "end_date", "date", "month", "cal_date"]:
        value = payload.get(field)
        if value is None or str(value).strip() == "":
            continue
        text = str(value).strip()
        if text.isdigit() and len(text) == 6:
            return f"{text[:4]}-{text[4:]}"
        try:
            return normalize_trade_date(value)
        except (TypeError, ValueError):
            return text
    return None


def _research_available_at(
    payload: Mapping[str, object],
    retrieved_at: str,
) -> str:
    for field in ("f_ann_date", "ann_date", "report_date", "surv_date", "float_date", "trade_date", "cal_date"):
        value = payload.get(field)
        if value is None or str(value).strip() == "":
            continue
        try:
            return normalize_trade_date(value)
        except (TypeError, ValueError):
            return str(value).strip()
    return retrieved_at


def _payload_looks_revised(payload: Mapping[str, object]) -> bool:
    value = str(payload.get("update_flag") or "").strip().lower()
    return value in {"1", "true", "yes", "updated", "revised"}


def _backfill_research_observation_metadata(connection: sqlite3.Connection) -> None:
    needs_backfill = connection.execute(
        f"""
        SELECT 1 FROM {RESEARCH_OBSERVATION_TABLE}
        WHERE business_key IS NULL OR available_at IS NULL
           OR first_seen_at IS NULL OR last_seen_at IS NULL
        LIMIT 1
        """
    ).fetchone()
    if needs_backfill is None:
        return
    rows = connection.execute(
        f"""
        SELECT rowid, dataset, row_hash, payload_json, retrieved_at
        FROM {RESEARCH_OBSERVATION_TABLE}
        ORDER BY retrieved_at, rowid
        """
    ).fetchall()
    grouped: dict[tuple[str, str], list[tuple[int, str, str, str, bool]]] = {}
    for rowid, dataset, row_hash, payload_json, retrieved_at in rows:
        payload = json.loads(str(payload_json))
        business_key = _research_business_key(str(dataset), payload, str(row_hash))
        available_at = _research_available_at(payload, str(retrieved_at))
        grouped.setdefault((str(dataset), business_key), []).append(
            (
                int(rowid),
                str(retrieved_at),
                available_at,
                str(row_hash),
                _payload_looks_revised(payload),
            )
        )
    for (_, business_key), versions in grouped.items():
        for revision, (rowid, first_seen_at, available_at, _, looks_revised) in enumerate(versions, start=1):
            effective_available_at = (
                first_seen_at if revision > 1 or looks_revised else available_at
            )
            connection.execute(
                f"""
                UPDATE {RESEARCH_OBSERVATION_TABLE}
                SET business_key = ?, available_at = ?, first_seen_at = ?,
                    last_seen_at = ?, revision = ?, is_current = ?
                WHERE rowid = ?
                """,
                (
                    business_key,
                    effective_available_at,
                    first_seen_at,
                    first_seen_at,
                    revision,
                    int(revision == len(versions)),
                    rowid,
                ),
            )


def _available_as_of_timestamp(value: str) -> str:
    text = str(value).strip()
    local_timezone = ZoneInfo("Asia/Hong_Kong")
    date_only = (text.isdigit() and len(text) == 8) or (
        len(text) == 10 and text[4] == "-" and text[7] == "-"
    )
    if text.isdigit() and len(text) == 8:
        parsed = datetime.strptime(text, "%Y%m%d")
    else:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if date_only:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_timezone)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def write_research_observations(
    dataset: str,
    frame: pd.DataFrame,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    """Store arbitrary TuShare research rows without adding one table per endpoint."""
    if frame.empty:
        ensure_database(db_path)
        return 0

    timestamp = _timestamp(retrieved_at)
    records: list[dict[str, object]] = []
    for row in frame.to_dict(orient="records"):
        payload = {str(key): _json_value(value) for key, value in row.items()}
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        row_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        records.append(
            {
                "dataset": dataset,
                "row_hash": row_hash,
                "business_key": _research_business_key(dataset, payload, row_hash),
                "ts_code": _text_or_none(payload.get("ts_code")),
                "event_date": _research_event_date(payload),
                "available_at": _research_available_at(payload, timestamp),
                "looks_revised": _payload_looks_revised(payload),
                "payload_json": payload_json,
            }
        )

    db_path = ensure_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        for record in records:
            existing = connection.execute(
                f"""
                SELECT row_hash, revision, first_seen_at
                FROM {RESEARCH_OBSERVATION_TABLE}
                WHERE dataset = ? AND business_key = ?
                ORDER BY revision DESC
                """,
                (record["dataset"], record["business_key"]),
            ).fetchall()
            same_payload = next(
                (item for item in existing if str(item[0]) == record["row_hash"]),
                None,
            )
            connection.execute(
                f"""
                UPDATE {RESEARCH_OBSERVATION_TABLE}
                SET is_current = 0
                WHERE dataset = ? AND business_key = ? AND is_current = 1
                """,
                (record["dataset"], record["business_key"]),
            )
            if same_payload is not None:
                connection.execute(
                    f"""
                    UPDATE {RESEARCH_OBSERVATION_TABLE}
                    SET source = ?, retrieved_at = ?, last_seen_at = ?, is_current = 1
                    WHERE dataset = ? AND row_hash = ?
                    """,
                    (source, timestamp, timestamp, record["dataset"], record["row_hash"]),
                )
                continue
            revision = max((int(item[1]) for item in existing), default=0) + 1
            effective_available_at = (
                timestamp
                if revision > 1 or bool(record["looks_revised"])
                else record["available_at"]
            )
            connection.execute(
                f"""
                INSERT INTO {RESEARCH_OBSERVATION_TABLE}(
                    dataset, row_hash, business_key, ts_code, event_date,
                    available_at, payload_json, source, retrieved_at,
                    first_seen_at, last_seen_at, revision, is_current
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    record["dataset"],
                    record["row_hash"],
                    record["business_key"],
                    record["ts_code"],
                    record["event_date"],
                    effective_available_at,
                    record["payload_json"],
                    source,
                    timestamp,
                    timestamp,
                    timestamp,
                    revision,
                ),
            )
        connection.commit()
    return len(records)


def load_research_observations(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    dataset: str | None = None,
    symbols: Sequence[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    available_as_of: str | None = None,
    observed_as_of: str | None = None,
    include_revisions: bool = False,
    limit: int = 200,
) -> pd.DataFrame:
    """Load cached TuShare research rows and expand their JSON payloads."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Market data database not found: {db_path}")
    if limit <= 0:
        raise ValueError("limit must be positive")

    where: list[str] = []
    params: list[object] = []
    if dataset:
        where.append("dataset = ?")
        params.append(dataset)
    if symbols:
        clean_symbols = [str(symbol) for symbol in symbols if symbol]
        if clean_symbols:
            placeholders = ", ".join("?" for _ in clean_symbols)
            where.append(f"ts_code IN ({placeholders})")
            params.extend(clean_symbols)
    if start_date:
        where.append("event_date >= ?")
        params.append(normalize_trade_date(start_date))
    if end_date:
        where.append("event_date <= ?")
        params.append(normalize_trade_date(end_date))
    if available_as_of:
        where.append("SUBSTR(available_at, 1, 10) <= ?")
        params.append(normalize_trade_date(available_as_of))
    if observed_as_of:
        where.append("first_seen_at <= ?")
        params.append(_available_as_of_timestamp(observed_as_of))
    if not available_as_of and not observed_as_of and not include_revisions:
        where.append("is_current = 1")

    predicate = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(int(limit))
    metadata_columns = """
        dataset, row_hash, business_key, ts_code, event_date, available_at,
        payload_json, source, retrieved_at, first_seen_at, last_seen_at,
        revision, is_current
    """
    if (available_as_of or observed_as_of) and not include_revisions:
        query = f"""
            WITH eligible AS (
                SELECT {metadata_columns},
                       ROW_NUMBER() OVER (
                           PARTITION BY dataset, business_key
                           ORDER BY revision DESC, first_seen_at DESC
                       ) AS version_rank
                FROM {RESEARCH_OBSERVATION_TABLE}
                {predicate}
            )
            SELECT {metadata_columns}
            FROM eligible
            WHERE version_rank = 1
            ORDER BY COALESCE(event_date, '') DESC, dataset, ts_code
            LIMIT ?
        """
    else:
        query = f"""
            SELECT {metadata_columns}
            FROM {RESEARCH_OBSERVATION_TABLE}
            {predicate}
            ORDER BY COALESCE(event_date, '') DESC, dataset, ts_code, revision DESC
            LIMIT ?
        """
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        rows = pd.read_sql_query(
            query,
            connection,
            params=params,
        )

    expanded = []
    for row in rows.to_dict(orient="records"):
        payload = json.loads(str(row.pop("payload_json")))
        for key, value in payload.items():
            target = key if key not in row else f"payload_{key}"
            row[target] = value
        expanded.append(row)
    return pd.DataFrame(expanded)


def load_research_observation_dates(
    dataset: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    symbols: Sequence[str] | None = None,
) -> set[str]:
    """Return current cached observation dates for one dataset.

    This lightweight query is intentionally narrower than
    :func:`load_research_observations`: callers that only need to decide
    whether a network refresh is required should not deserialize every raw
    payload stored in SQLite.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return set()

    where = ["dataset = ?", "is_current = 1", "event_date IS NOT NULL", "event_date <> ''"]
    params: list[object] = [dataset]
    if symbols:
        clean_symbols = [str(symbol) for symbol in symbols if symbol]
        if clean_symbols:
            placeholders = ", ".join("?" for _ in clean_symbols)
            where.append(f"ts_code IN ({placeholders})")
            params.extend(clean_symbols)

    query = f"""
        SELECT DISTINCT event_date
        FROM {RESEARCH_OBSERVATION_TABLE}
        WHERE {' AND '.join(where)}
    """
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        rows = connection.execute(query, params).fetchall()

    dates: set[str] = set()
    for (value,) in rows:
        try:
            dates.add(normalize_trade_date(value))
        except (TypeError, ValueError):
            continue
    return dates


def load_normalized_endpoint_dates(
    endpoint: str,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    symbols: Sequence[str] | None = None,
) -> set[str]:
    """Return stored dates from normalized core-market tables for one endpoint."""
    table = NORMALIZED_ENDPOINT_DATE_TABLES.get(endpoint)
    db_path = Path(db_path)
    if table is None or not db_path.exists():
        return set()

    where = ["trade_date IS NOT NULL", "trade_date <> ''"]
    params: list[object] = []
    if symbols:
        clean_symbols = [str(symbol) for symbol in symbols if symbol]
        if clean_symbols:
            placeholders = ", ".join("?" for _ in clean_symbols)
            where.append(f"ts_code IN ({placeholders})")
            params.extend(clean_symbols)

    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        rows = connection.execute(
            f"SELECT DISTINCT trade_date FROM {table} WHERE {' AND '.join(where)}",
            params,
        ).fetchall()
    return {normalize_trade_date(value) for (value,) in rows}


def load_trading_calendar(
    *,
    start_date: str,
    end_date: str,
    exchange: str = "SSE",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    """Load a local exchange calendar without triggering a network request."""
    columns = ["exchange", "cal_date", "is_open", "pretrade_date"]
    db_path = Path(db_path)
    if not db_path.exists():
        return pd.DataFrame(columns=columns)

    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        return pd.read_sql_query(
            f"""
            SELECT exchange, cal_date, is_open, pretrade_date
            FROM {TRADING_CALENDAR_TABLE}
            WHERE exchange = ? AND cal_date >= ? AND cal_date <= ?
            ORDER BY cal_date
            """,
            connection,
            params=(exchange, normalize_trade_date(start_date), normalize_trade_date(end_date)),
        )


def write_tushare_capabilities(
    records: Sequence[Mapping[str, object]],
    *,
    db_path: Path = DEFAULT_DB_PATH,
    checked_at: str | None = None,
) -> int:
    """Persist endpoint permission probes without storing credentials."""
    timestamp = _timestamp(checked_at)
    rows = []
    for record in records:
        endpoint = str(record.get("endpoint", "")).strip()
        if not endpoint:
            continue
        details = {
            str(key): _json_value(value)
            for key, value in record.items()
            if key not in {"endpoint", "category", "status", "rows"}
        }
        rows.append(
            (
                endpoint,
                str(record.get("category", "unknown")),
                str(record.get("status", "unknown")),
                int(record.get("rows", 0) or 0),
                json.dumps(details, ensure_ascii=False, sort_keys=True),
                timestamp,
            )
        )

    db_path = ensure_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        connection.executemany(
            f"""
            INSERT INTO {TUSHARE_CAPABILITY_TABLE}
                (endpoint, category, status, rows_seen, details_json, checked_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                category = excluded.category,
                status = excluded.status,
                rows_seen = excluded.rows_seen,
                details_json = excluded.details_json,
                checked_at = excluded.checked_at
            """,
            rows,
        )
        connection.commit()
    return len(rows)


def load_tushare_capabilities(*, db_path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    db_path = Path(db_path)
    if not db_path.exists():
        return pd.DataFrame(columns=["endpoint", "category", "status", "rows_seen", "details_json", "checked_at"])
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        return pd.read_sql_query(
            f"SELECT * FROM {TUSHARE_CAPABILITY_TABLE} ORDER BY endpoint",
            connection,
        )


def write_daily_market_data(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    *,
    high_prices: pd.DataFrame | None = None,
    low_prices: pd.DataFrame | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    """Upsert forward-adjusted daily close, high, low, and volume into SQLite."""
    price_rows = _matrix_to_long(prices, "close_qfq")
    volume_rows = _matrix_to_long(volumes, "volume")
    daily = price_rows.merge(volume_rows, on=["trade_date", "ts_code"], how="outer")
    if high_prices is not None:
        high_rows = _matrix_to_long(high_prices, "high_qfq")
        daily = daily.merge(high_rows, on=["trade_date", "ts_code"], how="outer")
    else:
        daily["high_qfq"] = None
    if low_prices is not None:
        low_rows = _matrix_to_long(low_prices, "low_qfq")
        daily = daily.merge(low_rows, on=["trade_date", "ts_code"], how="outer")
    else:
        daily["low_qfq"] = None
    if daily.empty:
        ensure_database(db_path)
        return 0

    timestamp = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = [
        (
            normalize_trade_date(row.trade_date),
            str(row.ts_code),
            _float_or_none(row.close_qfq),
            _float_or_none(row.high_qfq),
            _float_or_none(row.low_qfq),
            _float_or_none(row.volume),
            source,
            timestamp,
        )
        for row in daily.itertuples(index=False)
    ]

    db_path = ensure_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        connection.executemany(
            f"""
            INSERT INTO {DAILY_TABLE}
                (trade_date, ts_code, close_qfq, high_qfq, low_qfq, volume, source, retrieved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_date, ts_code) DO UPDATE SET
                close_qfq = excluded.close_qfq,
                high_qfq = COALESCE(excluded.high_qfq, {DAILY_TABLE}.high_qfq),
                low_qfq = COALESCE(excluded.low_qfq, {DAILY_TABLE}.low_qfq),
                volume = excluded.volume,
                source = excluded.source,
                retrieved_at = excluded.retrieved_at
            """,
            records,
        )
        connection.commit()
    return len(records)


def write_daily_basic(
    frame: pd.DataFrame,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    """Upsert TuShare daily_basic rows into SQLite."""
    if frame.empty:
        ensure_database(db_path)
        return 0

    timestamp = _timestamp(retrieved_at)
    records = []
    for _, row in frame.iterrows():
        records.append(
            (
                normalize_trade_date(row.get("trade_date")),
                str(row.get("ts_code")),
                *[_float_or_none(row.get(field)) for field in DAILY_BASIC_NUMERIC_FIELDS],
                source,
                timestamp,
            )
        )

    columns = ["trade_date", "ts_code", *DAILY_BASIC_NUMERIC_FIELDS, "source", "retrieved_at"]
    assignments = ", ".join(
        [
            *[
                f"{column} = COALESCE(excluded.{column}, {column})"
                for column in DAILY_BASIC_NUMERIC_FIELDS
            ],
            "source = excluded.source",
            "retrieved_at = excluded.retrieved_at",
        ]
    )
    placeholders = ", ".join("?" for _ in columns)
    db_path = ensure_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        connection.executemany(
            f"""
            INSERT INTO {DAILY_BASIC_TABLE}
                ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(trade_date, ts_code) DO UPDATE SET
                {assignments}
            """,
            records,
        )
        connection.commit()
    return len(records)


def write_fina_indicator(
    frame: pd.DataFrame,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    """Upsert supplementary TuShare financial-indicator rows into SQLite."""
    if frame.empty:
        ensure_database(db_path)
        return 0

    timestamp = _timestamp(retrieved_at)
    records = []
    for _, row in frame.iterrows():
        records.append(
            (
                normalize_trade_date(row.get("end_date")),
                str(row.get("ts_code")),
                _normalize_optional_date(row.get("ann_date")),
                *[_float_or_none(row.get(field)) for field in FINA_INDICATOR_NUMERIC_FIELDS],
                source,
                timestamp,
            )
        )

    columns = ["end_date", "ts_code", "ann_date", *FINA_INDICATOR_NUMERIC_FIELDS, "source", "retrieved_at"]
    assignments = ", ".join(
        [
            *[
                f"{column} = COALESCE(excluded.{column}, {column})"
                for column in ["ann_date", *FINA_INDICATOR_NUMERIC_FIELDS]
            ],
            "source = excluded.source",
            "retrieved_at = excluded.retrieved_at",
        ]
    )
    placeholders = ", ".join("?" for _ in columns)
    db_path = ensure_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        connection.executemany(
            f"""
            INSERT INTO {FINA_INDICATOR_TABLE}
                ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(end_date, ts_code) DO UPDATE SET
                {assignments}
            """,
            records,
        )
        connection.commit()
    return len(records)


def write_stock_basic(
    frame: pd.DataFrame,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    """Upsert TuShare stock_basic rows into SQLite."""
    if frame.empty:
        ensure_database(db_path)
        return 0

    timestamp = _timestamp(retrieved_at)
    records = []
    for _, row in frame.iterrows():
        records.append(
            (
                str(row.get("ts_code")),
                _text_or_none(row.get("name")),
                _text_or_none(row.get("industry")),
                _text_or_none(row.get("market")),
                _normalize_optional_date(row.get("list_date")),
                source,
                timestamp,
            )
        )

    db_path = ensure_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        connection.executemany(
            f"""
            INSERT INTO {STOCK_BASIC_TABLE}
                (ts_code, name, industry, market, list_date, source, retrieved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ts_code) DO UPDATE SET
                name = excluded.name,
                industry = excluded.industry,
                market = excluded.market,
                list_date = excluded.list_date,
                source = excluded.source,
                retrieved_at = excluded.retrieved_at
            """,
            records,
        )
        connection.commit()
    return len(records)


def _write_normalized_frame(
    frame: pd.DataFrame,
    *,
    table: str,
    columns: Sequence[str],
    key_columns: Sequence[str],
    date_columns: Sequence[str] = (),
    numeric_columns: Sequence[str] = (),
    integer_columns: Sequence[str] = (),
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    if frame.empty:
        ensure_database(db_path)
        return 0

    date_fields = set(date_columns)
    numeric_fields = set(numeric_columns)
    integer_fields = set(integer_columns)
    timestamp = _timestamp(retrieved_at)
    records = []
    for _, row in frame.iterrows():
        values = []
        for column in columns:
            value = row.get(column)
            if column in date_fields:
                value = _normalize_optional_date(value)
            elif column in numeric_fields:
                value = _float_or_none(value)
            elif column in integer_fields:
                value = None if pd.isna(value) else int(value)
            else:
                value = _text_or_none(value)
            values.append(value)
        records.append((*values, source, timestamp))

    all_columns = [*columns, "source", "retrieved_at"]
    assignments = ", ".join(
        [
            *[
                f"{column} = COALESCE(excluded.{column}, {column})"
                for column in columns
                if column not in key_columns
            ],
            "source = excluded.source",
            "retrieved_at = excluded.retrieved_at",
        ]
    )
    placeholders = ", ".join("?" for _ in all_columns)
    db_path = ensure_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        connection.executemany(
            f"""
            INSERT INTO {table} ({", ".join(all_columns)})
            VALUES ({placeholders})
            ON CONFLICT({", ".join(key_columns)}) DO UPDATE SET
                {assignments}
            """,
            records,
        )
        connection.commit()
    return len(records)


def write_trading_calendar(
    frame: pd.DataFrame,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    return _write_normalized_frame(
        frame,
        table=TRADING_CALENDAR_TABLE,
        columns=["exchange", "cal_date", "is_open", "pretrade_date"],
        key_columns=["exchange", "cal_date"],
        date_columns=["cal_date", "pretrade_date"],
        integer_columns=["is_open"],
        db_path=db_path,
        source=source,
        retrieved_at=retrieved_at,
    )


def write_index_daily(
    frame: pd.DataFrame,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    return _write_normalized_frame(
        frame,
        table=INDEX_DAILY_TABLE,
        columns=["ts_code", "trade_date", *INDEX_DAILY_NUMERIC_FIELDS],
        key_columns=["ts_code", "trade_date"],
        date_columns=["trade_date"],
        numeric_columns=INDEX_DAILY_NUMERIC_FIELDS,
        db_path=db_path,
        source=source,
        retrieved_at=retrieved_at,
    )


def write_index_daily_basic(
    frame: pd.DataFrame,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    return _write_normalized_frame(
        frame,
        table=INDEX_DAILY_BASIC_TABLE,
        columns=["ts_code", "trade_date", *INDEX_DAILY_BASIC_NUMERIC_FIELDS],
        key_columns=["ts_code", "trade_date"],
        date_columns=["trade_date"],
        numeric_columns=INDEX_DAILY_BASIC_NUMERIC_FIELDS,
        db_path=db_path,
        source=source,
        retrieved_at=retrieved_at,
    )


def write_industry_classification(
    frame: pd.DataFrame,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    return _write_normalized_frame(
        frame,
        table=INDUSTRY_CLASSIFICATION_TABLE,
        columns=["src", "index_code", "industry_code", "industry_name", "level", "is_pub", "parent_code"],
        key_columns=["src", "index_code"],
        db_path=db_path,
        source=source,
        retrieved_at=retrieved_at,
    )


def write_index_members(
    frame: pd.DataFrame,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    return _write_normalized_frame(
        frame,
        table=INDEX_MEMBER_TABLE,
        columns=["index_code", "con_code", "in_date", "out_date", "is_new"],
        key_columns=["index_code", "con_code", "in_date"],
        date_columns=["in_date", "out_date"],
        db_path=db_path,
        source=source,
        retrieved_at=retrieved_at,
    )


def write_index_weights(
    frame: pd.DataFrame,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    return _write_normalized_frame(
        frame,
        table=INDEX_WEIGHT_TABLE,
        columns=["index_code", "con_code", "trade_date", "weight"],
        key_columns=["index_code", "con_code", "trade_date"],
        date_columns=["trade_date"],
        numeric_columns=["weight"],
        db_path=db_path,
        source=source,
        retrieved_at=retrieved_at,
    )


def write_market_daily_info(
    frame: pd.DataFrame,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    return _write_normalized_frame(
        frame,
        table=MARKET_DAILY_INFO_TABLE,
        columns=["trade_date", "ts_code", "ts_name", "exchange", *MARKET_DAILY_INFO_NUMERIC_FIELDS],
        key_columns=["trade_date", "ts_code"],
        date_columns=["trade_date"],
        numeric_columns=MARKET_DAILY_INFO_NUMERIC_FIELDS,
        db_path=db_path,
        source=source,
        retrieved_at=retrieved_at,
    )


def write_market_moneyflow(
    frame: pd.DataFrame,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    return _write_normalized_frame(
        frame,
        table=MARKET_MONEYFLOW_TABLE,
        columns=["trade_date", *MARKET_MONEYFLOW_NUMERIC_FIELDS],
        key_columns=["trade_date"],
        date_columns=["trade_date"],
        numeric_columns=MARKET_MONEYFLOW_NUMERIC_FIELDS,
        db_path=db_path,
        source=source,
        retrieved_at=retrieved_at,
    )


def write_market_margin(
    frame: pd.DataFrame,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    return _write_normalized_frame(
        frame,
        table=MARKET_MARGIN_TABLE,
        columns=["trade_date", "exchange_id", *MARKET_MARGIN_NUMERIC_FIELDS],
        key_columns=["trade_date", "exchange_id"],
        date_columns=["trade_date"],
        numeric_columns=MARKET_MARGIN_NUMERIC_FIELDS,
        db_path=db_path,
        source=source,
        retrieved_at=retrieved_at,
    )


def _payload_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return [
        {str(key): _json_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _write_payload_table(
    table: str,
    frame: pd.DataFrame,
    *,
    key_columns: Sequence[str],
    columns: Sequence[str],
    numeric_columns: Sequence[str] = (),
    date_columns: Sequence[str] = (),
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    if frame.empty:
        ensure_database(db_path)
        return 0
    timestamp = _timestamp(retrieved_at)
    numeric_fields = set(numeric_columns)
    date_fields = set(date_columns)
    records: list[tuple[object, ...]] = []
    for payload in _payload_records(frame):
        values: list[object] = []
        for column in columns:
            value = payload.get(column)
            if column in date_fields:
                value = _normalize_optional_date(value)
            elif column in numeric_fields:
                value = _float_or_none(value)
            else:
                value = _text_or_none(value)
            values.append(value)
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        values.extend((payload_json, source, timestamp))
        records.append(tuple(values))
    all_columns = [*columns, "payload_json", "source", "retrieved_at"]
    assignments = ", ".join(
        [f"{column} = COALESCE(excluded.{column}, {column})" for column in columns if column not in key_columns]
        + ["payload_json = excluded.payload_json", "source = excluded.source", "retrieved_at = excluded.retrieved_at"]
    )
    placeholders = ", ".join("?" for _ in all_columns)
    db_path = ensure_database(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        connection.executemany(
            f"""
            INSERT INTO {table} ({", ".join(all_columns)})
            VALUES ({placeholders})
            ON CONFLICT({", ".join(key_columns)}) DO UPDATE SET {assignments}
            """,
            records,
        )
        connection.commit()
    return len(records)


def write_market_flow_daily(frame: pd.DataFrame, **kwargs: object) -> int:
    return _write_payload_table(
        MARKET_FLOW_DAILY_TABLE,
        frame,
        key_columns=["ts_code", "trade_date"],
        columns=["ts_code", "trade_date", "net_mf_amount", "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount"],
        numeric_columns=["net_mf_amount", "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount"],
        date_columns=["trade_date"],
        **kwargs,
    )


def write_limit_events(frame: pd.DataFrame, **kwargs: object) -> int:
    frame = frame.copy()
    if "limit_type" not in frame.columns:
        frame["limit_type"] = ""
    else:
        frame["limit_type"] = frame["limit_type"].fillna("").astype(str)
    return _write_payload_table(
        LIMIT_EVENT_DAILY_TABLE,
        frame,
        key_columns=["ts_code", "trade_date", "limit_type"],
        columns=["ts_code", "trade_date", "name", "limit_type", "pct_chg", "amount", "first_time", "last_time", "open_times", "up_stat"],
        numeric_columns=["pct_chg", "amount", "open_times"],
        date_columns=["trade_date"],
        **kwargs,
    )


def write_sector_master(provider: str, frame: pd.DataFrame, **kwargs: object) -> int:
    from market_data_sector import write_sector_master as implementation

    return implementation(provider, frame, **kwargs)


def write_sector_daily(provider: str, frame: pd.DataFrame, **kwargs: object) -> int:
    from market_data_sector import write_sector_daily as implementation

    return implementation(provider, frame, **kwargs)


def write_sector_flow_daily(provider: str, frame: pd.DataFrame, **kwargs: object) -> int:
    from market_data_sector import write_sector_flow_daily as implementation

    return implementation(provider, frame, **kwargs)


def write_sector_membership(dataset: str, frame: pd.DataFrame, **kwargs: object) -> int:
    from market_data_sector import write_sector_membership as implementation

    return implementation(dataset, frame, **kwargs)


def write_chip_distribution(frame: pd.DataFrame, **kwargs: object) -> int:
    return _write_payload_table(
        CHIP_DISTRIBUTION_TABLE,
        frame,
        key_columns=["ts_code", "trade_date", "price"],
        columns=["ts_code", "trade_date", "price", "percent", "vol"],
        numeric_columns=["price", "percent", "vol"],
        date_columns=["trade_date"],
        **kwargs,
    )


def write_factor_daily(frame: pd.DataFrame, **kwargs: object) -> int:
    return _write_payload_table(
        FACTOR_DAILY_TABLE,
        frame,
        key_columns=["ts_code", "trade_date"],
        columns=["ts_code", "trade_date"],
        date_columns=["trade_date"],
        **kwargs,
    )


def write_institutional_research(frame: pd.DataFrame, **kwargs: object) -> int:
    frame = frame.copy()
    for column in ("ts_code", "surv_date", "org_name"):
        if column not in frame.columns:
            frame[column] = ""
        frame[column] = frame[column].fillna("").astype(str)
    return _write_payload_table(
        INSTITUTIONAL_RESEARCH_TABLE,
        frame,
        key_columns=["ts_code", "surv_date", "org_name"],
        columns=["ts_code", "surv_date", "org_name", "ann_date"],
        date_columns=["surv_date", "ann_date"],
        **kwargs,
    )


def write_corporate_events(dataset: str, frame: pd.DataFrame, **kwargs: object) -> int:
    frame = frame.copy()
    frame["dataset"] = dataset
    date_column = next((column for column in ("ann_date", "trade_date", "holder_trade_date", "imp_date", "release_date") if column in frame.columns), None)
    frame["event_date"] = frame[date_column] if date_column else None
    frame["event_key"] = frame.apply(lambda row: _research_business_key(dataset, {str(k): _json_value(v) for k, v in row.items()}, "event"), axis=1)
    return _write_payload_table(
        CORPORATE_EVENTS_TABLE,
        frame,
        key_columns=["dataset", "ts_code", "event_date", "event_key"],
        columns=["dataset", "ts_code", "event_date", "event_key"],
        date_columns=["event_date"],
        **kwargs,
    )


@dataclass(frozen=True)
class _NormalizationContext:
    dataset: str
    endpoint: str
    frame: pd.DataFrame
    db_path: Path
    source: str
    retrieved_at: str


@dataclass(frozen=True)
class _NormalizerRule:
    endpoints: frozenset[str]
    required_columns: frozenset[str]
    handler: Callable[[_NormalizationContext], int]

    def matches(self, context: _NormalizationContext) -> bool:
        return context.endpoint in self.endpoints and self.required_columns.issubset(context.frame.columns)


def _frame_handler(writer: Callable[..., int]) -> Callable[[_NormalizationContext], int]:
    def handle(context: _NormalizationContext) -> int:
        return writer(
            context.frame,
            db_path=context.db_path,
            source=context.source,
            retrieved_at=context.retrieved_at,
        )

    return handle


def _sector_master_handler(context: _NormalizationContext) -> int:
    return write_sector_master(
        SECTOR_MASTER_ENDPOINT_PROVIDERS[context.endpoint],
        context.frame,
        db_path=context.db_path,
        source=context.source,
        retrieved_at=context.retrieved_at,
    )


def _sector_daily_handler(context: _NormalizationContext) -> int:
    return write_sector_daily(
        SECTOR_DAILY_ENDPOINT_PROVIDERS[context.endpoint],
        context.frame,
        db_path=context.db_path,
        source=context.source,
        retrieved_at=context.retrieved_at,
    )


def _sector_flow_handler(context: _NormalizationContext) -> int:
    return write_sector_flow_daily(
        "ths",
        context.frame,
        db_path=context.db_path,
        source=context.source,
        retrieved_at=context.retrieved_at,
    )


def _sector_membership_handler(context: _NormalizationContext) -> int:
    return write_sector_membership(
        context.endpoint,
        context.frame,
        db_path=context.db_path,
        source=context.source,
        retrieved_at=context.retrieved_at,
    )


def _corporate_events_handler(context: _NormalizationContext) -> int:
    return write_corporate_events(
        context.dataset,
        context.frame,
        db_path=context.db_path,
        source=context.source,
        retrieved_at=context.retrieved_at,
    )


NORMALIZER_RULES = (
    _NormalizerRule(frozenset({"daily_basic"}), frozenset({"ts_code", "trade_date"}), _frame_handler(write_daily_basic)),
    _NormalizerRule(frozenset({"fina_indicator"}), frozenset({"ts_code", "end_date"}), _frame_handler(write_fina_indicator)),
    _NormalizerRule(
        frozenset({"stock_basic"}),
        frozenset({"ts_code", "name", "industry", "market", "list_date"}),
        _frame_handler(write_stock_basic),
    ),
    _NormalizerRule(frozenset({"trade_cal"}), frozenset({"exchange", "cal_date"}), _frame_handler(write_trading_calendar)),
    _NormalizerRule(frozenset({"index_daily"}), frozenset({"ts_code", "trade_date"}), _frame_handler(write_index_daily)),
    _NormalizerRule(frozenset({"index_dailybasic"}), frozenset({"ts_code", "trade_date"}), _frame_handler(write_index_daily_basic)),
    _NormalizerRule(frozenset({"index_classify"}), frozenset({"src", "index_code"}), _frame_handler(write_industry_classification)),
    _NormalizerRule(frozenset({"index_member"}), frozenset({"index_code", "con_code", "in_date"}), _frame_handler(write_index_members)),
    _NormalizerRule(frozenset({"index_weight"}), frozenset({"index_code", "con_code", "trade_date"}), _frame_handler(write_index_weights)),
    _NormalizerRule(frozenset({"daily_info"}), frozenset({"trade_date", "ts_code"}), _frame_handler(write_market_daily_info)),
    _NormalizerRule(frozenset({"moneyflow_mkt_dc"}), frozenset({"trade_date", "net_amount"}), _frame_handler(write_market_moneyflow)),
    _NormalizerRule(frozenset({"margin"}), frozenset({"trade_date", "exchange_id"}), _frame_handler(write_market_margin)),
    _NormalizerRule(frozenset(SECTOR_MASTER_ENDPOINT_PROVIDERS), frozenset(), _sector_master_handler),
    _NormalizerRule(frozenset(SECTOR_DAILY_ENDPOINT_PROVIDERS), frozenset(), _sector_daily_handler),
    _NormalizerRule(frozenset({"moneyflow_ind_ths"}), frozenset(), _sector_flow_handler),
    _NormalizerRule(frozenset({"moneyflow", "moneyflow_ths", "moneyflow_dc"}), frozenset({"ts_code", "trade_date"}), _frame_handler(write_market_flow_daily)),
    _NormalizerRule(frozenset({"limit_list_d", "limit_step", "kpl_list", "kpl_stock_rank"}), frozenset({"ts_code", "trade_date"}), _frame_handler(write_limit_events)),
    _NormalizerRule(frozenset(SECTOR_MEMBER_ENDPOINT_PROVIDERS), frozenset({"con_code"}), _sector_membership_handler),
    _NormalizerRule(frozenset({"cyq_chips", "cyq_perf"}), frozenset({"ts_code", "trade_date", "price"}), _frame_handler(write_chip_distribution)),
    _NormalizerRule(frozenset({"stk_factor", "stk_factor_pro"}), frozenset({"ts_code", "trade_date"}), _frame_handler(write_factor_daily)),
    _NormalizerRule(frozenset({"stk_surv"}), frozenset({"ts_code", "surv_date"}), _frame_handler(write_institutional_research)),
    _NormalizerRule(
        frozenset({"repurchase", "pledge_detail", "stk_holdertrade", "block_trade", "namechange", "share_float"}),
        frozenset({"ts_code"}),
        _corporate_events_handler,
    ),
)


def persist_tushare_collection(
    dataset: str,
    endpoint: str,
    frame: pd.DataFrame,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> tuple[int, int]:
    """Persist every fetched response and materialize safe core-table rows.

    Arbitrary endpoint responses always enter the append-aware research cache.
    Known row-oriented core datasets are additionally upserted into their
    normalized SQLite tables when the response includes their identifying
    columns. Partial observations preserve already stored normalized fields.
    """
    timestamp = _timestamp(retrieved_at)
    observation_rows = write_research_observations(
        dataset,
        frame,
        db_path=db_path,
        source=source,
        retrieved_at=timestamp,
    )
    context = _NormalizationContext(
        dataset=dataset,
        endpoint=endpoint,
        frame=frame,
        db_path=db_path,
        source=source,
        retrieved_at=timestamp,
    )
    rule = next((candidate for candidate in NORMALIZER_RULES if candidate.matches(context)), None)
    normalized_rows = rule.handler(context) if rule else 0
    return observation_rows, normalized_rows


def load_sector_master(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    provider: str = "ths",
    sector_type: str | None = None,
    sector_codes: Sequence[str] | None = None,
) -> pd.DataFrame:
    from market_data_sector import load_sector_master as implementation

    return implementation(
        db_path=db_path,
        provider=provider,
        sector_type=sector_type,
        sector_codes=sector_codes,
    )


def load_sector_daily_history(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    provider: str = "ths",
    start_date: str | None = None,
    end_date: str | None = None,
    sector_type: str | None = None,
    sector_codes: Sequence[str] | None = None,
) -> pd.DataFrame:
    from market_data_sector import load_sector_daily_history as implementation

    return implementation(
        db_path=db_path,
        provider=provider,
        start_date=start_date,
        end_date=end_date,
        sector_type=sector_type,
        sector_codes=sector_codes,
    )


def load_sector_memberships(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    provider: str = "ths",
    stock_code: str | None = None,
    sector_code: str | None = None,
    as_of: str | None = None,
) -> pd.DataFrame:
    from market_data_sector import load_sector_memberships as implementation

    return implementation(
        db_path=db_path,
        provider=provider,
        stock_code=stock_code,
        sector_code=sector_code,
        as_of=as_of,
    )


def load_sector_cached_dates(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    provider: str,
    dataset: Literal["daily", "flow"],
    start_date: str | None = None,
    end_date: str | None = None,
) -> set[str]:
    from market_data_sector import load_sector_cached_dates as implementation

    return implementation(
        db_path=db_path,
        provider=provider,
        dataset=dataset,
        start_date=start_date,
        end_date=end_date,
    )


def load_daily_matrices(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    start_date: str | None = None,
    end_date: str | None = None,
    symbols: Sequence[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load forward-adjusted price and volume matrices from the local SQLite store."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Market data database not found: {db_path}")

    where: list[str] = []
    params: list[str] = []
    if start_date:
        where.append("trade_date >= ?")
        params.append(normalize_trade_date(start_date))
    if end_date:
        where.append("trade_date <= ?")
        params.append(normalize_trade_date(end_date))
    if symbols:
        clean_symbols = [str(symbol) for symbol in symbols if symbol]
        if clean_symbols:
            placeholders = ", ".join("?" for _ in clean_symbols)
            where.append(f"ts_code IN ({placeholders})")
            params.extend(clean_symbols)

    predicate = f"WHERE {' AND '.join(where)}" if where else ""
    query = f"""
        SELECT trade_date, ts_code, close_qfq, volume
        FROM {DAILY_TABLE}
        {predicate}
        ORDER BY trade_date, ts_code
    """

    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        frame = pd.read_sql_query(query, connection, params=params, parse_dates=["trade_date"])

    if frame.empty:
        empty_index = pd.DatetimeIndex([], name="trade_date")
        return pd.DataFrame(index=empty_index), pd.DataFrame(index=empty_index)

    prices = frame.pivot(index="trade_date", columns="ts_code", values="close_qfq").sort_index()
    volumes = frame.pivot(index="trade_date", columns="ts_code", values="volume").sort_index()
    prices = prices.sort_index(axis=1)
    volumes = volumes.sort_index(axis=1)
    prices.columns.name = None
    volumes.columns.name = None
    return prices, volumes


def load_daily_price_history(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    start_date: str | None = None,
    end_date: str | None = None,
    symbols: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Load stored forward-adjusted close, high, and low rows for historical context."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Market data database not found: {db_path}")

    where: list[str] = []
    params: list[str] = []
    if start_date:
        where.append("trade_date >= ?")
        params.append(normalize_trade_date(start_date))
    if end_date:
        where.append("trade_date <= ?")
        params.append(normalize_trade_date(end_date))
    if symbols:
        clean_symbols = [str(symbol) for symbol in symbols if symbol]
        if clean_symbols:
            placeholders = ", ".join("?" for _ in clean_symbols)
            where.append(f"ts_code IN ({placeholders})")
            params.extend(clean_symbols)

    predicate = f"WHERE {' AND '.join(where)}" if where else ""
    query = f"""
        SELECT trade_date, ts_code, close_qfq, high_qfq, low_qfq
        FROM {DAILY_TABLE}
        {predicate}
        ORDER BY trade_date, ts_code
    """
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        return pd.read_sql_query(query, connection, params=params, parse_dates=["trade_date"])


def _symbol_predicate(symbols: Sequence[str] | None, params: list[str]) -> str:
    if not symbols:
        return ""
    clean_symbols = [str(symbol) for symbol in symbols if symbol]
    if not clean_symbols:
        return ""
    placeholders = ", ".join("?" for _ in clean_symbols)
    params.extend(clean_symbols)
    return f" AND ts_code IN ({placeholders})"


def load_daily_basic_history(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    as_of: str,
    symbols: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Load daily_basic rows up to as_of for valuation history calculations."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Market data database not found: {db_path}")

    params = [normalize_trade_date(as_of)]
    symbol_sql = _symbol_predicate(symbols, params)
    query = f"""
        SELECT *
        FROM {DAILY_BASIC_TABLE}
        WHERE trade_date <= ?{symbol_sql}
        ORDER BY ts_code, trade_date
    """
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        return pd.read_sql_query(query, connection, params=params)


def load_fina_indicator_history(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    as_of: str,
    symbols: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Load point-in-time available secondary financial-indicator history."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Market data database not found: {db_path}")

    as_of_date = normalize_trade_date(as_of)
    params = [as_of_date, as_of_date]
    symbol_sql = _symbol_predicate(symbols, params)
    query = f"""
        SELECT *
        FROM {FINA_INDICATOR_TABLE}
        WHERE (ann_date IS NULL OR ann_date <= ?) AND end_date <= ?{symbol_sql}
        ORDER BY ts_code, end_date, ann_date
    """
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        return pd.read_sql_query(query, connection, params=params)


def load_factor_inputs(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    as_of: str,
    symbols: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Load latest daily_basic, announced financials, and stock metadata for factor screening."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Market data database not found: {db_path}")

    as_of_date = normalize_trade_date(as_of)
    daily_params = [as_of_date]
    daily_symbol_sql = _symbol_predicate(symbols, daily_params)
    fina_params = [as_of_date, as_of_date]
    fina_symbol_sql = _symbol_predicate(symbols, fina_params)
    stock_params: list[str] = []
    stock_symbol_sql = _symbol_predicate(symbols, stock_params)
    stock_where = f"WHERE 1=1{stock_symbol_sql}" if stock_symbol_sql else ""

    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        daily = pd.read_sql_query(
            f"""
            SELECT *
            FROM {DAILY_BASIC_TABLE}
            WHERE trade_date <= ?{daily_symbol_sql}
            ORDER BY ts_code, trade_date
            """,
            connection,
            params=daily_params,
        )
        fina = pd.read_sql_query(
            f"""
            SELECT *
            FROM {FINA_INDICATOR_TABLE}
            WHERE (ann_date IS NULL OR ann_date <= ?) AND end_date <= ?{fina_symbol_sql}
            ORDER BY ts_code, ann_date, end_date
            """,
            connection,
            params=fina_params,
        )
        stock = pd.read_sql_query(
            f"""
            SELECT *
            FROM {STOCK_BASIC_TABLE}
            {stock_where}
            """,
            connection,
            params=stock_params,
        )

    if daily.empty:
        return pd.DataFrame()

    latest_daily = daily.sort_values(["ts_code", "trade_date"]).groupby("ts_code", as_index=False).tail(1)
    if not fina.empty:
        latest_fina = fina.sort_values(["ts_code", "ann_date", "end_date"]).groupby("ts_code", as_index=False).tail(1)
    else:
        latest_fina = pd.DataFrame(columns=["ts_code"])

    result = latest_daily.merge(stock, on="ts_code", how="left", suffixes=("", "_stock"))
    result = result.merge(latest_fina, on="ts_code", how="left", suffixes=("", "_fina"))
    return result.reset_index(drop=True)

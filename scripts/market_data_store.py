#!/usr/bin/env python3
"""SQLite-backed market data store helpers for local investment research."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd


DEFAULT_DB_PATH = Path("data/investment_research.sqlite")
DAILY_TABLE = "a_share_daily"
DAILY_BASIC_TABLE = "a_share_daily_basic"
FINA_INDICATOR_TABLE = "a_share_fina_indicator"
STOCK_BASIC_TABLE = "a_share_stock_basic"
RESEARCH_OBSERVATION_TABLE = "tushare_research_observation"
TUSHARE_CAPABILITY_TABLE = "tushare_capability"

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
            volume REAL,
            source TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, ts_code)
        )
        """
    )
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


def ensure_database(db_path: Path = DEFAULT_DB_PATH) -> Path:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as connection:
        ensure_schema(connection)
        connection.commit()
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
    db_path: Path = DEFAULT_DB_PATH,
    source: str = "tushare",
    retrieved_at: str | None = None,
) -> int:
    """Upsert forward-adjusted prices and volumes into the local SQLite store."""
    price_rows = _matrix_to_long(prices, "close_qfq")
    volume_rows = _matrix_to_long(volumes, "volume")
    daily = price_rows.merge(volume_rows, on=["trade_date", "ts_code"], how="outer")
    if daily.empty:
        ensure_database(db_path)
        return 0

    timestamp = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = [
        (
            normalize_trade_date(row.trade_date),
            str(row.ts_code),
            _float_or_none(row.close_qfq),
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
                (trade_date, ts_code, close_qfq, volume, source, retrieved_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_date, ts_code) DO UPDATE SET
                close_qfq = excluded.close_qfq,
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
    assignments = ", ".join(f"{column} = excluded.{column}" for column in [*DAILY_BASIC_NUMERIC_FIELDS, "source", "retrieved_at"])
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
    """Upsert TuShare fina_indicator rows into SQLite."""
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
        f"{column} = excluded.{column}" for column in ["ann_date", *FINA_INDICATOR_NUMERIC_FIELDS, "source", "retrieved_at"]
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
    """Load point-in-time available financial-indicator history for Stage-L coverage checks."""
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

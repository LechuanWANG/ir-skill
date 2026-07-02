#!/usr/bin/env python3
"""SQLite-backed market data store helpers for local investment research."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pandas as pd


DEFAULT_DB_PATH = Path("data/investment_research.sqlite")
DAILY_TABLE = "a_share_daily"
DAILY_BASIC_TABLE = "a_share_daily_basic"
FINA_INDICATOR_TABLE = "a_share_fina_indicator"
STOCK_BASIC_TABLE = "a_share_stock_basic"

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
    return retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")


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

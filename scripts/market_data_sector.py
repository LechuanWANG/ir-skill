"""Sector-specific normalization, persistence, and cache coverage helpers."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, Sequence

import pandas as pd

import market_data_store as store


SectorSnapshotDataset = Literal["daily", "flow"]


def _copy_sector_column(
    frame: pd.DataFrame,
    target: str,
    candidates: Sequence[str],
    *,
    default: object = None,
) -> None:
    if target in frame.columns:
        return
    source_column = next((column for column in candidates if column in frame.columns), None)
    frame[target] = frame[source_column] if source_column else default


def _canonical_sector_frame(
    provider: str,
    frame: pd.DataFrame,
    *,
    require_trade_date: bool = False,
) -> pd.DataFrame:
    normalized = frame.copy()
    normalized["provider"] = provider
    _copy_sector_column(normalized, "sector_code", ("ts_code", "index_code", "code"))
    _copy_sector_column(normalized, "sector_name", ("name", "ts_name", "industry_name", "industry"))
    _copy_sector_column(normalized, "sector_type", ("type", "category", "level"))
    _copy_sector_column(normalized, "exchange", ("market",))
    if require_trade_date:
        _copy_sector_column(normalized, "trade_date", ("date",))
    if "sector_code" not in normalized.columns:
        return normalized.iloc[0:0]
    normalized = normalized.loc[
        normalized["sector_code"].notna()
        & normalized["sector_code"].astype(str).str.strip().ne("")
    ].copy()
    if require_trade_date:
        if "trade_date" not in normalized.columns:
            return normalized.iloc[0:0]
        normalized = normalized.loc[
            normalized["trade_date"].notna()
            & normalized["trade_date"].astype(str).str.strip().ne("")
        ].copy()
    return normalized


def write_sector_master(provider: str, frame: pd.DataFrame, **kwargs: object) -> int:
    normalized = _canonical_sector_frame(provider, frame)
    return store._write_payload_table(
        store.SECTOR_MASTER_TABLE,
        normalized,
        key_columns=["provider", "sector_code"],
        columns=["provider", "sector_code", "sector_name", "sector_type", "exchange"],
        **kwargs,
    )


def write_sector_daily(provider: str, frame: pd.DataFrame, **kwargs: object) -> int:
    normalized = _canonical_sector_frame(provider, frame, require_trade_date=True)
    _copy_sector_column(normalized, "pct_chg", ("pct_change", "change_pct"))
    _copy_sector_column(normalized, "vol", ("volume",))
    return store._write_payload_table(
        store.SECTOR_DAILY_TABLE,
        normalized,
        key_columns=["provider", "sector_code", "trade_date"],
        columns=[
            "provider",
            "sector_code",
            "trade_date",
            "sector_name",
            *store.SECTOR_DAILY_NUMERIC_FIELDS,
        ],
        numeric_columns=store.SECTOR_DAILY_NUMERIC_FIELDS,
        date_columns=["trade_date"],
        **kwargs,
    )


def write_sector_flow_daily(provider: str, frame: pd.DataFrame, **kwargs: object) -> int:
    normalized = _canonical_sector_frame(provider, frame, require_trade_date=True)
    _copy_sector_column(normalized, "pct_chg", ("pct_change",))
    _copy_sector_column(normalized, "lead_stock_pct_chg", ("pct_change_stock",))
    return store._write_payload_table(
        store.SECTOR_FLOW_DAILY_TABLE,
        normalized,
        key_columns=["provider", "sector_code", "trade_date"],
        columns=[
            "provider",
            "sector_code",
            "trade_date",
            "sector_name",
            "lead_stock",
            *store.SECTOR_FLOW_NUMERIC_FIELDS,
        ],
        numeric_columns=store.SECTOR_FLOW_NUMERIC_FIELDS,
        date_columns=["trade_date"],
        **kwargs,
    )


def write_sector_membership(dataset: str, frame: pd.DataFrame, **kwargs: object) -> int:
    frame = frame.copy()
    frame["dataset"] = dataset
    if "index_code" not in frame.columns:
        frame["index_code"] = frame.get("ts_code")
    if "con_code" not in frame.columns:
        frame["con_code"] = frame.get("con_code", frame.get("ts_code"))
    if "in_date" not in frame.columns:
        frame["in_date"] = ""
    if "name" not in frame.columns and "con_name" in frame.columns:
        frame["name"] = frame["con_name"]
    if "trade_date" not in frame.columns:
        retrieved_at = store._timestamp(
            kwargs.get("retrieved_at") if isinstance(kwargs.get("retrieved_at"), str) else None
        )
        frame["trade_date"] = retrieved_at[:10]
    for column in ("index_code", "con_code", "trade_date", "in_date"):
        frame[column] = frame[column].fillna("").astype(str)
    return store._write_payload_table(
        store.SECTOR_MEMBERSHIP_TABLE,
        frame,
        key_columns=["dataset", "index_code", "con_code", "trade_date", "in_date"],
        columns=["dataset", "index_code", "con_code", "trade_date", "in_date", "out_date", "name"],
        date_columns=["trade_date", "in_date", "out_date"],
        **kwargs,
    )


def _clean_sector_codes(sector_codes: Sequence[str] | None) -> list[str]:
    return [str(code) for code in sector_codes or () if code]


def load_sector_master(
    *,
    db_path: Path = store.DEFAULT_DB_PATH,
    provider: str = "ths",
    sector_type: str | None = None,
    sector_codes: Sequence[str] | None = None,
) -> pd.DataFrame:
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Market data database not found: {db_path}")
    where = ["provider = ?"]
    params: list[object] = [provider]
    if sector_type:
        where.append("sector_type = ?")
        params.append(sector_type)
    clean_codes = _clean_sector_codes(sector_codes)
    if clean_codes:
        placeholders = ", ".join("?" for _ in clean_codes)
        where.append(f"sector_code IN ({placeholders})")
        params.extend(clean_codes)
    with closing(sqlite3.connect(db_path)) as connection:
        store.ensure_schema(connection)
        return pd.read_sql_query(
            f"""
            SELECT provider, sector_code, sector_name, sector_type, exchange, source, retrieved_at
            FROM {store.SECTOR_MASTER_TABLE}
            WHERE {' AND '.join(where)}
            ORDER BY sector_type, sector_name, sector_code
            """,
            connection,
            params=params,
        )


def load_sector_daily_history(
    *,
    db_path: Path = store.DEFAULT_DB_PATH,
    provider: str = "ths",
    start_date: str | None = None,
    end_date: str | None = None,
    sector_type: str | None = None,
    sector_codes: Sequence[str] | None = None,
) -> pd.DataFrame:
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Market data database not found: {db_path}")
    where = ["daily.provider = ?"]
    params: list[object] = [provider]
    if start_date:
        where.append("daily.trade_date >= ?")
        params.append(store.normalize_trade_date(start_date))
    if end_date:
        where.append("daily.trade_date <= ?")
        params.append(store.normalize_trade_date(end_date))
    if sector_type:
        where.append("master.sector_type = ?")
        params.append(sector_type)
    clean_codes = _clean_sector_codes(sector_codes)
    if clean_codes:
        placeholders = ", ".join("?" for _ in clean_codes)
        where.append(f"daily.sector_code IN ({placeholders})")
        params.extend(clean_codes)
    with closing(sqlite3.connect(db_path)) as connection:
        store.ensure_schema(connection)
        return pd.read_sql_query(
            f"""
            SELECT
                daily.provider,
                daily.sector_code,
                daily.trade_date,
                COALESCE(daily.sector_name, master.sector_name) AS sector_name,
                master.sector_type,
                master.exchange,
                daily.open,
                daily.high,
                daily.low,
                daily.close,
                daily.pre_close,
                daily.change,
                daily.pct_chg,
                daily.vol,
                daily.amount,
                daily.turnover_rate,
                flow.pct_chg AS flow_pct_chg,
                flow.company_num,
                flow.lead_stock,
                flow.lead_stock_pct_chg,
                flow.net_buy_amount,
                flow.net_sell_amount,
                flow.net_amount,
                daily.source,
                daily.retrieved_at
            FROM {store.SECTOR_DAILY_TABLE} AS daily
            LEFT JOIN {store.SECTOR_MASTER_TABLE} AS master
                ON master.provider = daily.provider
                AND master.sector_code = daily.sector_code
            LEFT JOIN {store.SECTOR_FLOW_DAILY_TABLE} AS flow
                ON flow.provider = daily.provider
                AND flow.sector_code = daily.sector_code
                AND flow.trade_date = daily.trade_date
            WHERE {' AND '.join(where)}
            ORDER BY daily.sector_code, daily.trade_date
            """,
            connection,
            params=params,
        )


def load_sector_memberships(
    *,
    db_path: Path = store.DEFAULT_DB_PATH,
    provider: str = "ths",
    stock_code: str | None = None,
    sector_code: str | None = None,
    as_of: str | None = None,
) -> pd.DataFrame:
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Market data database not found: {db_path}")
    dataset = f"{provider}_member"
    where = ["membership.dataset = ?"]
    params: list[object] = [dataset]
    if stock_code:
        where.append("membership.con_code = ?")
        params.append(stock_code)
    if sector_code:
        where.append("membership.index_code = ?")
        params.append(sector_code)
    if as_of:
        where.append("membership.trade_date <= ?")
        params.append(store.normalize_trade_date(as_of))
    with closing(sqlite3.connect(db_path)) as connection:
        store.ensure_schema(connection)
        return pd.read_sql_query(
            f"""
            WITH eligible AS (
                SELECT membership.*
                FROM {store.SECTOR_MEMBERSHIP_TABLE} AS membership
                WHERE {' AND '.join(where)}
            ),
            latest AS (
                SELECT dataset, index_code, MAX(trade_date) AS trade_date
                FROM eligible
                GROUP BY dataset, index_code
            )
            SELECT
                eligible.dataset,
                ? AS provider,
                eligible.index_code AS sector_code,
                master.sector_name,
                master.sector_type,
                eligible.con_code AS stock_code,
                eligible.name AS stock_name,
                eligible.trade_date AS snapshot_date,
                eligible.in_date,
                eligible.out_date,
                eligible.source,
                eligible.retrieved_at
            FROM eligible
            INNER JOIN latest
                ON latest.dataset = eligible.dataset
                AND latest.index_code = eligible.index_code
                AND latest.trade_date = eligible.trade_date
            LEFT JOIN {store.SECTOR_MASTER_TABLE} AS master
                ON master.provider = ?
                AND master.sector_code = eligible.index_code
            ORDER BY master.sector_type, master.sector_name, eligible.index_code, eligible.con_code
            """,
            connection,
            params=[*params, provider, provider],
        )


def load_sector_cached_dates(
    *,
    db_path: Path = store.DEFAULT_DB_PATH,
    provider: str,
    dataset: SectorSnapshotDataset,
    start_date: str | None = None,
    end_date: str | None = None,
) -> set[str]:
    """Return locally materialized cross-section dates for a sector dataset."""
    table_by_dataset = {
        "daily": store.SECTOR_DAILY_TABLE,
        "flow": store.SECTOR_FLOW_DAILY_TABLE,
    }
    try:
        table = table_by_dataset[dataset]
    except KeyError as exc:
        raise ValueError(f"unsupported sector snapshot dataset: {dataset}") from exc

    db_path = Path(db_path)
    if not db_path.exists():
        return set()
    where = ["provider = ?"]
    params: list[object] = [provider]
    if start_date:
        where.append("trade_date >= ?")
        params.append(store.normalize_trade_date(start_date))
    if end_date:
        where.append("trade_date <= ?")
        params.append(store.normalize_trade_date(end_date))
    with closing(sqlite3.connect(db_path)) as connection:
        store.ensure_schema(connection)
        rows = connection.execute(
            f"SELECT DISTINCT trade_date FROM {table} WHERE {' AND '.join(where)}",
            params,
        )
        return {str(row[0]) for row in rows if row[0]}

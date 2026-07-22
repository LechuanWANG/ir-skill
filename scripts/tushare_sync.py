#!/usr/bin/env python3
"""TuShare database sync helpers for local investment research.

The network-facing pieces are intentionally thin. Most logic is kept as pure
helpers so tests can verify batching and date slicing without a TuShare token.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pandas as pd

from market_data_store import (
    DEFAULT_DB_PATH,
    write_daily_basic,
    write_daily_market_data,
    write_fina_indicator,
    write_stock_basic,
    write_tushare_capabilities,
)
from tushare_config import DEFAULT_ENV_PATH, read_env_values, resolve_tushare_token, tushare_config_status
from tushare_transport import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
    TushareEndpointError,
    TushareRequestPolicy,
    request_endpoint,
)


DATE_FMT = "%Y%m%d"
DEFAULT_BATCH_SIZE = 500
DEFAULT_DAYS_PER_CHUNK = 5
DEFAULT_SLEEP_SECONDS = 0.15
TUSHARE_API_URL = "https://api.tushare.pro"
DAILY_BASIC_FIELDS = (
    "ts_code,trade_date,close,turnover_rate,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,"
    "dv_ratio,dv_ttm,total_mv,circ_mv,total_share,float_share,free_share"
)
FINA_INDICATOR_FIELDS = (
    "ts_code,end_date,ann_date,roe,roe_dt,roa,netprofit_margin,grossprofit_margin,"
    "netprofit_yoy,or_yoy,debt_to_assets,current_ratio,quick_ratio,ocf_to_or,bps,eps"
)
STOCK_BASIC_FIELDS = "ts_code,name,industry,market,list_date,list_status,delist_date"


@dataclass(frozen=True)
class SyncConfig:
    start_date: str
    end_date: str
    db_path: Path = DEFAULT_DB_PATH
    batch_size: int = DEFAULT_BATCH_SIZE
    days_per_chunk: int = DEFAULT_DAYS_PER_CHUNK
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS
    daily_basic: bool = False
    fina_indicator: bool = False
    stock_basic: bool = False
    env_path: Path | None = None
    min_request_interval: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS


@dataclass(frozen=True)
class ForwardAdjustedDailyFrames:
    """Forward-adjusted daily price matrices returned by one TuShare sync window."""

    open: pd.DataFrame
    close: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    volume: pd.DataFrame
    amount: pd.DataFrame
    raw_open: pd.DataFrame
    raw_close: pd.DataFrame
    raw_high: pd.DataFrame
    raw_low: pd.DataFrame
    adjustment_factor: pd.DataFrame


class TushareHttpClient:
    """Small TuShare Pro client using the public JSON API and standard library only."""

    def __init__(
        self,
        token: str,
        *,
        api_url: str = TUSHARE_API_URL,
        timeout_seconds: float = 30.0,
        opener=urllib.request.urlopen,
    ) -> None:
        self._token = token
        self._api_url = api_url
        self._timeout_seconds = timeout_seconds
        self._opener = opener

    def __getattr__(self, endpoint: str):
        if endpoint.startswith("_") or not endpoint.isidentifier():
            raise AttributeError(endpoint)

        def request(**params: object) -> pd.DataFrame:
            return self._request(endpoint, params)

        return request

    def _request(self, endpoint: str, params: Mapping[str, object]) -> pd.DataFrame:
        request_params = dict(params)
        fields = request_params.pop("fields", None)
        payload: dict[str, object] = {
            "api_name": endpoint,
            "token": self._token,
            "params": request_params,
        }
        if fields is not None:
            payload["fields"] = fields
        request = urllib.request.Request(
            self._api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        response = None
        try:
            response = self._opener(request, timeout=self._timeout_seconds)
            raw_payload = response.read()
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        try:
            response_payload = json.loads(raw_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"TuShare endpoint '{endpoint}' returned invalid JSON") from exc
        if not isinstance(response_payload, Mapping):
            raise RuntimeError(f"TuShare endpoint '{endpoint}' returned an invalid response object")
        code = response_payload.get("code")
        if code != 0:
            message = str(response_payload.get("msg") or "unknown API error")
            raise RuntimeError(f"TuShare endpoint '{endpoint}' failed (code={code}): {message}")
        data = response_payload.get("data")
        if data is None:
            return pd.DataFrame()
        if not isinstance(data, Mapping):
            raise RuntimeError(f"TuShare endpoint '{endpoint}' returned an invalid data payload")
        columns = data.get("fields", [])
        rows = data.get("items", [])
        if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
            raise RuntimeError(f"TuShare endpoint '{endpoint}' returned invalid field metadata")
        if not isinstance(rows, list):
            raise RuntimeError(f"TuShare endpoint '{endpoint}' returned invalid row data")
        return pd.DataFrame(rows, columns=columns)


def _read_env_value(path: Path, key: str) -> str:
    return read_env_values(path).get(key, "")


def get_tushare_token(
    env: Mapping[str, str] | None = None,
    *,
    env_path: Path | None = None,
) -> str:
    return resolve_tushare_token(
        environ=env,
        env_path=env_path,
        # Supplying a mapping is a test/embedding mode and has historically not read files.
        read_file=env is None,
    ).value


def create_tushare_client(*, env_path: Path | None = None):
    token = get_tushare_token(env_path=env_path)
    return TushareHttpClient(token)


def chunk_date_range(start_date: str, end_date: str, days_per_chunk: int = DEFAULT_DAYS_PER_CHUNK) -> list[tuple[str, str]]:
    if days_per_chunk <= 0:
        raise ValueError("days_per_chunk must be positive")

    start = datetime.strptime(start_date, DATE_FMT)
    end = datetime.strptime(end_date, DATE_FMT)
    if start > end:
        raise ValueError("start_date must be earlier than or equal to end_date")

    chunks: list[tuple[str, str]] = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=days_per_chunk - 1), end)
        chunks.append((current.strftime(DATE_FMT), chunk_end.strftime(DATE_FMT)))
        current = chunk_end + timedelta(days=1)
    return chunks


def chunk_symbols(symbols: Sequence[str], batch_size: int = DEFAULT_BATCH_SIZE) -> Iterable[list[str]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    clean = [symbol for symbol in symbols if symbol]
    for index in range(0, len(clean), batch_size):
        yield clean[index:index + batch_size]


def list_active_symbols(pro, *, request_policy: TushareRequestPolicy | None = None) -> list[str]:
    frame = request_endpoint(
        pro,
        "stock_basic",
        {"list_status": "L", "fields": "ts_code"},
        policy=request_policy,
    )
    if frame.empty:
        return []
    return frame["ts_code"].dropna().astype(str).tolist()


def list_symbols_for_period(
    pro,
    start_date: str,
    end_date: str,
    *,
    request_policy: TushareRequestPolicy | None = None,
) -> list[str]:
    """Return symbols listed at any point in the requested research interval."""
    frames: list[pd.DataFrame] = []
    for status in ("L", "D", "P"):
        frame = request_endpoint(
            pro,
            "stock_basic",
            {
                "list_status": status,
                "fields": "ts_code,list_date,delist_date,list_status",
            },
            policy=request_policy,
        )
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return []
    metadata = pd.concat(frames, ignore_index=True).drop_duplicates("ts_code")
    listed = pd.to_datetime(metadata.get("list_date"), errors="coerce")
    delisted = pd.to_datetime(metadata.get("delist_date"), errors="coerce")
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    keep = listed.le(end) & (delisted.isna() | delisted.ge(start))
    return metadata.loc[keep, "ts_code"].dropna().astype(str).drop_duplicates().tolist()


def fetch_daily_ohlcv_with_adjustment(
    pro,
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    days_per_chunk: int = DEFAULT_DAYS_PER_CHUNK,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    request_policy: TushareRequestPolicy | None = None,
) -> ForwardAdjustedDailyFrames:
    """Fetch daily OHLCV/amount and adjust each price field without filling suspensions."""
    price_frames: list[pd.DataFrame] = []
    adjust_frames: list[pd.DataFrame] = []
    policy = request_policy or TushareRequestPolicy()

    for date_start, date_end in chunk_date_range(start_date, end_date, days_per_chunk):
        for batch in chunk_symbols(symbols, batch_size):
            codes = ",".join(batch)
            daily = request_endpoint(
                pro,
                "daily",
                {
                    "ts_code": codes,
                    "start_date": date_start,
                    "end_date": date_end,
                    "fields": "ts_code,trade_date,open,close,high,low,vol,amount",
                },
                policy=policy,
            )
            adjustment = request_endpoint(
                pro,
                "adj_factor",
                {"ts_code": codes, "start_date": date_start, "end_date": date_end},
                policy=policy,
            )
            if not daily.empty:
                price_frames.append(daily)
            if not adjustment.empty:
                adjust_frames.append(adjustment)
            time.sleep(sleep_seconds)

    if not price_frames or not adjust_frames:
        return ForwardAdjustedDailyFrames(
            open=pd.DataFrame(),
            close=pd.DataFrame(),
            high=pd.DataFrame(),
            low=pd.DataFrame(),
            volume=pd.DataFrame(),
            amount=pd.DataFrame(),
            raw_open=pd.DataFrame(),
            raw_close=pd.DataFrame(),
            raw_high=pd.DataFrame(),
            raw_low=pd.DataFrame(),
            adjustment_factor=pd.DataFrame(),
        )

    raw = pd.concat(price_frames, ignore_index=True).drop_duplicates()
    adj = pd.concat(adjust_frames, ignore_index=True).drop_duplicates()
    raw["trade_date"] = pd.to_datetime(raw["trade_date"])
    adj["trade_date"] = pd.to_datetime(adj["trade_date"])

    open_prices = raw.pivot(index="trade_date", columns="ts_code", values="open").sort_index()
    close = raw.pivot(index="trade_date", columns="ts_code", values="close").sort_index()
    high = raw.pivot(index="trade_date", columns="ts_code", values="high").sort_index()
    low = raw.pivot(index="trade_date", columns="ts_code", values="low").sort_index()
    volume = raw.pivot(index="trade_date", columns="ts_code", values="vol").sort_index()
    amount = raw.pivot(index="trade_date", columns="ts_code", values="amount").sort_index()
    adj_factor = adj.pivot(index="trade_date", columns="ts_code", values="adj_factor").sort_index()

    last_adjustment = adj_factor.ffill().iloc[-1]
    adjusted_open = (open_prices * adj_factor).div(last_adjustment, axis=1).sort_index()
    adjusted_close = (close * adj_factor).div(last_adjustment, axis=1).sort_index()
    adjusted_high = (high * adj_factor).div(last_adjustment, axis=1).sort_index()
    adjusted_low = (low * adj_factor).div(last_adjustment, axis=1).sort_index()
    return ForwardAdjustedDailyFrames(
        open=adjusted_open,
        close=adjusted_close,
        high=adjusted_high,
        low=adjusted_low,
        volume=volume,
        amount=amount,
        raw_open=open_prices,
        raw_close=close,
        raw_high=high,
        raw_low=low,
        adjustment_factor=adj_factor,
    )


def fetch_daily_with_adjustment(
    pro,
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    days_per_chunk: int = DEFAULT_DAYS_PER_CHUNK,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    request_policy: TushareRequestPolicy | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the legacy close/volume subset of the forward-adjusted daily data."""
    daily = fetch_daily_ohlcv_with_adjustment(
        pro,
        symbols,
        start_date,
        end_date,
        batch_size=batch_size,
        days_per_chunk=days_per_chunk,
        sleep_seconds=sleep_seconds,
        request_policy=request_policy,
    )
    return daily.close, daily.volume


def fetch_stock_basic(pro, *, request_policy: TushareRequestPolicy | None = None) -> pd.DataFrame:
    """Fetch listed, delisted, and paused A-share metadata for lifecycle-aware replay."""
    frames: list[pd.DataFrame] = []
    for status in ("L", "D", "P"):
        frame = request_endpoint(
            pro,
            "stock_basic",
            {"list_status": status, "fields": STOCK_BASIC_FIELDS},
            policy=request_policy,
        )
        if not frame.empty:
            frames.append(frame)
    return pd.concat(frames, ignore_index=True).drop_duplicates("ts_code") if frames else pd.DataFrame()


def fetch_daily_basic(
    pro,
    symbols: Sequence[str] | None,
    start_date: str,
    end_date: str,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    days_per_chunk: int = DEFAULT_DAYS_PER_CHUNK,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    request_policy: TushareRequestPolicy | None = None,
    failures: list[dict[str, object]] | None = None,
) -> pd.DataFrame:
    """Fetch TuShare daily_basic rows by trade date.

    TuShare returns the complete market snapshot when ``trade_date`` is used
    without ``ts_code``. It does not reliably support a comma-separated stock
    batch for this endpoint, so an explicit symbol list is fetched one symbol
    at a time instead.
    """
    frames: list[pd.DataFrame] = []
    policy = request_policy or TushareRequestPolicy()
    for date_start, date_end in chunk_date_range(start_date, end_date, days_per_chunk):
        for trade_date in pd.date_range(date_start, date_end, freq="B"):
            trade_date_text = trade_date.strftime(DATE_FMT)
            if symbols is None:
                try:
                    frame = request_endpoint(
                        pro,
                        "daily_basic",
                        {"trade_date": trade_date_text, "fields": DAILY_BASIC_FIELDS},
                        policy=policy,
                    )
                except TushareEndpointError as error:
                    if failures is not None:
                        failures.append(error.as_record(trade_date=trade_date_text))
                    continue
                if not frame.empty:
                    frames.append(frame)
                time.sleep(sleep_seconds)
                continue

            for symbol in symbols:
                try:
                    frame = request_endpoint(
                        pro,
                        "daily_basic",
                        {"ts_code": symbol, "trade_date": trade_date_text, "fields": DAILY_BASIC_FIELDS},
                        policy=policy,
                    )
                except TushareEndpointError as error:
                    if failures is not None:
                        failures.append(error.as_record(symbol=symbol, trade_date=trade_date_text))
                    continue
                if not frame.empty:
                    frames.append(frame)
                time.sleep(sleep_seconds)
    return pd.concat(frames, ignore_index=True).drop_duplicates() if frames else pd.DataFrame()


def fetch_fina_indicator(
    pro,
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    request_policy: TushareRequestPolicy | None = None,
    failures: list[dict[str, object]] | None = None,
) -> pd.DataFrame:
    """Fetch supplementary financial-indicator series without discarding other symbols on failure."""

    frames: list[pd.DataFrame] = []
    policy = request_policy or TushareRequestPolicy()
    for batch in chunk_symbols(symbols, batch_size):
        for symbol in batch:
            try:
                frame = request_endpoint(
                    pro,
                    "fina_indicator",
                    {
                        "ts_code": symbol,
                        "start_date": start_date,
                        "end_date": end_date,
                        "fields": FINA_INDICATOR_FIELDS,
                    },
                    policy=policy,
                )
            except TushareEndpointError as error:
                if failures is not None:
                    failures.append(error.as_record(symbol=symbol))
                continue
            if not frame.empty:
                frames.append(frame)
            time.sleep(sleep_seconds)
    return pd.concat(frames, ignore_index=True).drop_duplicates() if frames else pd.DataFrame()


def sync_daily(config: SyncConfig, symbols: Sequence[str] | None = None) -> tuple[Path, int]:
    pro = create_tushare_client(env_path=config.env_path)
    policy = TushareRequestPolicy(
        min_interval_seconds=config.min_request_interval,
        max_attempts=config.max_attempts,
    )
    selected = list(symbols) if symbols else list_symbols_for_period(
        pro,
        config.start_date,
        config.end_date,
        request_policy=policy,
    )
    daily = fetch_daily_ohlcv_with_adjustment(
        pro,
        selected,
        config.start_date,
        config.end_date,
        batch_size=config.batch_size,
        days_per_chunk=config.days_per_chunk,
        sleep_seconds=config.sleep_seconds,
        request_policy=policy,
    )
    rows = write_daily_market_data(
        daily.close,
        daily.volume,
        open_prices=daily.open,
        high_prices=daily.high,
        low_prices=daily.low,
        amounts=daily.amount,
        raw_open_prices=daily.raw_open,
        raw_close_prices=daily.raw_close,
        raw_high_prices=daily.raw_high,
        raw_low_prices=daily.raw_low,
        adjustment_factors=daily.adjustment_factor,
        db_path=config.db_path,
        source="tushare",
    )
    return config.db_path, rows


def sync_factor_data(config: SyncConfig, symbols: Sequence[str] | None = None) -> tuple[Path, dict[str, int]]:
    pro = create_tushare_client(env_path=config.env_path)
    selected = list(symbols) if symbols else None
    row_counts: dict[str, int] = {}
    policy = TushareRequestPolicy(
        min_interval_seconds=config.min_request_interval,
        max_attempts=config.max_attempts,
    )

    if config.stock_basic:
        stock_basic = fetch_stock_basic(pro, request_policy=policy)
        row_counts["stock_basic"] = write_stock_basic(stock_basic, db_path=config.db_path, source="tushare")
    if config.daily_basic:
        daily_basic_rows = 0
        daily_basic_failures: list[dict[str, object]] = []
        for date_start, date_end in chunk_date_range(config.start_date, config.end_date, config.days_per_chunk):
            daily_basic = fetch_daily_basic(
                pro,
                selected,
                date_start,
                date_end,
                batch_size=config.batch_size,
                days_per_chunk=config.days_per_chunk,
                sleep_seconds=config.sleep_seconds,
                request_policy=policy,
                failures=daily_basic_failures,
            )
            daily_basic_rows += write_daily_basic(daily_basic, db_path=config.db_path, source="tushare")
        row_counts["daily_basic"] = daily_basic_rows
        if daily_basic_failures:
            write_tushare_capabilities(daily_basic_failures, db_path=config.db_path)
            row_counts["daily_basic_failed"] = len(daily_basic_failures)
    if config.fina_indicator:
        fina_symbols = selected if selected is not None else list_symbols_for_period(
            pro,
            config.start_date,
            config.end_date,
            request_policy=policy,
        )
        fina_failures: list[dict[str, object]] = []
        fina_indicator = fetch_fina_indicator(
            pro,
            fina_symbols,
            config.start_date,
            config.end_date,
            batch_size=config.batch_size,
            sleep_seconds=config.sleep_seconds,
            request_policy=policy,
            failures=fina_failures,
        )
        row_counts["fina_indicator"] = write_fina_indicator(fina_indicator, db_path=config.db_path, source="tushare")
        if fina_failures:
            write_tushare_capabilities(fina_failures, db_path=config.db_path)
            row_counts["fina_indicator_failed"] = len(fina_failures)

    return config.db_path, row_counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync TuShare A-share daily data into the local SQLite database.")
    parser.add_argument("start_date", nargs="?", help="Start date, YYYYMMDD")
    parser.add_argument("end_date", nargs="?", help="End date, YYYYMMDD")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, type=Path)
    parser.add_argument("--env-file", type=Path, help="Optional dotenv path; overrides the project-local default when no process token is set.")
    parser.add_argument("--check-config", action="store_true", help="Print a secret-safe TuShare configuration diagnostic and exit.")
    parser.add_argument("--symbols", nargs="*", help="Optional ts_code list. Defaults to all listed A-shares.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--days-per-chunk", type=int, default=DEFAULT_DAYS_PER_CHUNK)
    parser.add_argument("--sleep-seconds", type=float, default=DEFAULT_SLEEP_SECONDS)
    parser.add_argument("--min-request-interval", type=float, default=DEFAULT_MIN_REQUEST_INTERVAL_SECONDS)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--daily-basic", action="store_true", help="Sync TuShare daily_basic valuation/liquidity data.")
    parser.add_argument(
        "--fina-indicator",
        action="store_true",
        help="Sync supplementary financial-indicator trends; never use them as final financial-statement facts.",
    )
    parser.add_argument("--stock-basic", action="store_true", help="Sync TuShare stock_basic industry/name metadata.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check_config:
        status = tushare_config_status(env_path=args.env_file)
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if status["status"] == "configured" else 2
    if not args.start_date or not args.end_date:
        raise ValueError("start_date and end_date are required unless --check-config is used")
    config = SyncConfig(
        start_date=args.start_date,
        end_date=args.end_date,
        db_path=args.db_path,
        batch_size=args.batch_size,
        days_per_chunk=args.days_per_chunk,
        sleep_seconds=args.sleep_seconds,
        daily_basic=args.daily_basic,
        fina_indicator=args.fina_indicator,
        stock_basic=args.stock_basic,
        env_path=args.env_file,
        min_request_interval=args.min_request_interval,
        max_attempts=args.max_attempts,
    )
    if args.daily_basic or args.fina_indicator or args.stock_basic:
        db_path, row_counts = sync_factor_data(config, args.symbols)
        for name, rows in row_counts.items():
            print(f"saved {name} rows: {rows}")
    else:
        db_path, rows = sync_daily(config, args.symbols)
        print(f"saved rows: {rows}")
    print(f"database: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

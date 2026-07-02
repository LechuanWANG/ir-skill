# Data Sources

Use deterministic data for numbers and AI judgment for interpretation.

## Source Layering

| Data Need | Primary Source | Cross-Check | Notes |
|---|---|---|---|
| Historical A-share price/volume/adjustment | TuShare synced into local SQLite | Database freshness checks | Use forward-adjusted prices for returns |
| Intraday/latest price/quote | Current web or official exchange/company source | Latest stored daily close | If current quote data is unavailable, say so |
| A-share screening financial indicators | TuShare `fina_indicator` | Public annual, semiannual, or quarterly report | TuShare is acceptable for normalized screening inputs |
| A-share deep-report financial statements | Public annual, semiannual, or quarterly reports from CNInfo, exchanges, or company IR pages | TuShare, EastMoney, Sina, or other normalized databases | Original public filings are the source of record for final financial figures |
| News/policy/macro | Current web search; official sources first | Independent reporting if consequential | Must refresh for policy, war/conflict, rates, liquidity, currency, commodities, and regulation |
| User holdings/preferences | `docs/investment-llm-wiki/profile.md`, `portfolio.md` | User confirmation for sensitive writes | Local only by default |

## Required Data Fields

For stock conclusions, capture:

- ticker/code, market, currency, latest price, timestamp
- market cap inputs: price, shares, unit
- valuation inputs: EPS, BVPS, PE/PB where available
- financial quality: revenue/profit trend, ROE, leverage, cash flow if available
- source names and retrieval dates

## Cross-Check Rules

- Difference <= 1%: use primary source, cite both if available.
- Difference > 1% and <= 5%: mark as source discrepancy and explain likely unit/accounting/timing cause.
- Difference > 5%: do not rely on the number until the original filing or exchange announcement is checked.

Common failure modes: HKD versus CNY, total shares versus float, shares in units of hand/lot/ten-thousand, fiscal year versus calendar year, GAAP versus adjusted metrics.

## Macro And Policy Web Refresh

When macro or policy conditions could alter the investment conclusion, perform a current web search before finalizing the answer.

Search and cite sources in this priority order:

1. Official policy, central-bank, regulator, exchange, ministry, customs, statistics, or treasury sources.
2. Company or exchange announcements if the macro event has company-specific impact.
3. Major financial news organizations or reputable data providers for interpretation and market reaction.
4. Secondary commentary only as context, not as the source of record.

Refresh these topics when relevant:

- monetary policy, interest-rate changes, liquidity operations, credit policy
- fiscal policy, subsidies, tax, industrial policy, procurement, export controls
- war, sanctions, tariffs, geopolitical conflict, shipping or supply-chain disruption
- exchange rates, commodity prices, energy prices, inflation, PMI, employment, GDP
- sector regulation, antitrust, environmental rules, healthcare/education/internet/finance policy

Record source name, publication date, event date, retrieval date, and whether the source is official or media. If web search is unavailable, state this limitation and avoid high-confidence macro conclusions.

## Public Financial Report Cross-Check

For deep research, first-tier shortlist reviews, and final investment conclusions, do not rely on TuShare alone for financial statement numbers.

Use this workflow:

1. Locate the latest public annual, semiannual, and quarterly reports from CNInfo, SSE/SZSE/BSE disclosure pages, or the company's investor-relations site.
2. Treat the original public filing as the source of record for revenue, operating profit, parent net profit, deducted non-recurring net profit, EPS, total assets, total liabilities, operating cash flow, and business-segment figures.
3. Use TuShare, EastMoney, Sina, or similar normalized sources as cross-checks and history helpers, not as the only evidence for deep reports.
4. Record report period, announcement date, filing title, source name, retrieval time, unit, and currency.
5. If using a report artifact folder, store filing lists, downloaded public reports or extracted tables, and normalized cross-check tables under `outputs/reports/{report_slug}_{YYYYMMDD}/data/`.
6. If the original public report is unavailable in the current run, write that explicitly, downgrade confidence, and avoid making a high-conviction conclusion from normalized database data alone.

Cross-check at least these fields when available:

- revenue
- parent net profit
- deducted non-recurring net profit
- EPS
- gross margin or gross profit inputs
- total assets and total liabilities
- operating cash flow
- major business-segment revenue and margin

## Local Database Store

Use `data/investment_research.sqlite` as the default reusable store for downloaded market data. This keeps repeated runs from creating one-off CSV caches and gives later screening, attribution, and research tasks a stable local data source.

Default tables:

| Table | Key | Fields |
|---|---|---|
| `a_share_daily` | `(trade_date, ts_code)` | `close_qfq`, `volume`, `source`, `retrieved_at` |
| `a_share_daily_basic` | `(trade_date, ts_code)` | `close`, `turnover_rate`, `volume_ratio`, `pe`, `pe_ttm`, `pb`, `ps`, `ps_ttm`, `dv_ratio`, `dv_ttm`, `total_mv`, `circ_mv`, share fields, `source`, `retrieved_at` |
| `a_share_fina_indicator` | `(end_date, ts_code)` | `ann_date`, `roe`, `roe_dt`, `roa`, margins, `netprofit_yoy`, `or_yoy`, `debt_to_assets`, liquidity ratios, `ocf_to_or`, `bps`, `eps`, `source`, `retrieved_at` |
| `a_share_stock_basic` | `ts_code` | `name`, `industry`, `market`, `list_date`, `source`, `retrieved_at` |

Rules:

1. Sync downloaded TuShare price, volume, adjustment, daily_basic, fina_indicator, and stock_basic data into SQLite through `scripts/tushare_sync.py`.
2. Read raw technical inputs through `scripts/technical_screen.py`; read multi-factor screening inputs through `scripts/factor_screen.py`.
3. Treat CSV/XLSX files as final exports or user-provided one-off enrichment files, not as the canonical cache.
4. Keep the database local under `data/`; do not commit it or copy it into wiki pages.
5. If the database is stale for the requested date range, refresh it before analysis or explicitly mark the data as stale.
6. Align financial indicators by `ann_date`; do not use financial rows announced after the screening `as_of` date.
7. 12-1 momentum needs roughly 270 daily rows. Own-history valuation percentile is stronger with 3+ years of `daily_basic`; when history is short, mark the fallback.

## LLM Recalculation Checklist

After drafting any report with financial numbers, the agent must mechanically recompute the key numbers from the data table before treating the report as usable:

| Check | Formula / Rule |
|---|---|
| Market cap | `price × shares`; confirm unit and currency |
| PE | `price / EPS`; mark unavailable if EPS is missing or non-comparable |
| PB | `price / BVPS`; mark unavailable if BVPS is missing |
| Dividend yield | `dividend / price`; confirm annualized dividend basis |

Use `scripts/financial_check.py` for the calculations. The LLM's job is to compare the recomputed result with the memo/report text, catch unit or currency mistakes, and either fix the report or mark the number as unavailable.

## Scripts

Use:

```bash
python3 scripts/tushare_sync.py 20260101 20260131 --db-path data/investment_research.sqlite
python3 scripts/tushare_sync.py 20250101 20260131 --db-path data/investment_research.sqlite --daily-basic --fina-indicator --stock-basic
python3 scripts/technical_screen.py --db-path data/investment_research.sqlite --start-date 20260101 --end-date 20260131 --output outputs/screens/screen.csv
python3 scripts/factor_screen.py --db-path data/investment_research.sqlite --as-of 20260131 --preset balanced --output outputs/screens/factor_screen.csv
python3 scripts/financial_check.py verify-market-cap --price 10 --shares 100000000 --reported 1000000000 --currency CNY
```

`TUSHARE_TOKEN` must come from the environment. Do not hard-code credentials.

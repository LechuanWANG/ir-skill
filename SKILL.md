---
name: local-investment-research
description: Use when the user asks for stock analysis, A-share screening, portfolio review, position sizing, market or price-move attribution, deep investment research, thesis tracking, or maintaining a local investment knowledge base from holdings, market data, filings, reports, and research notes.
---

# Local Investment Research

## Overview

Use this skill as a local investment research workbench. Produce decision memos, not generic research essays: lead with an action, cite evidence, expose uncertainty, and preserve useful conclusions in the local wiki.

This is research assistance only. Do not present outputs as financial advice or an automated trading instruction.

## First Step

Classify the user request, then load only the references needed for that route:

| User Intent | Read These References | Default Depth |
|---|---|---|
| Single-stock research | `references/decision-framework.md`, `references/fundamental-research.md`, `references/industry-macro.md`, `references/data-sources.md` | Deep |
| A-share screening | `references/technical-screening.md`, `references/factor-model.md`, `references/data-sources.md` | Quick |
| A-share first-tier deep dive | `references/deep-research-mode.md`, `references/decision-framework.md`, `references/fundamental-research.md`, `references/industry-macro.md`, `references/data-sources.md`, `references/output-templates.md` | Deep |
| Portfolio review or position sizing | `references/portfolio-thesis.md`, `references/wiki-memory.md`, `references/decision-framework.md` | Quick, deepen if large |
| Price move or news attribution | `references/industry-macro.md`, `references/data-sources.md`, optionally `references/portfolio-thesis.md` | Quick |
| File/report/wiki ingest | `references/wiki-memory.md`, `references/output-templates.md` | Wiki workflow |
| Explicit deep research or large decision | `references/deep-research-mode.md` plus the route-specific references above | Deep |

Do not create or read `references/router.md`; routing belongs in this file so the skill can choose references without a second hop.

## Operating Rules

1. Read the Investment LLM Wiki index at `docs/investment-llm-wiki/index.md` and relevant wiki pages before analysis whenever the request mentions current holdings, preferences, prior decisions, thesis tracking, or local documents.
2. Use the quick output by default. Use deep mode when the user asks for depth, requests four-view analysis, asks about a single-stock investment decision, or the decision materially changes a large position.
3. Treat deep mode as explicit user authorization for four-agent research. When native subagents are available, spawn A1-A4 in parallel and synthesize their findings as team lead; if subagents are unavailable, run the same roles sequentially in the main agent.
4. A 股筛选必须走多因子打分，显式抗追高（估值分位 + 过热惩罚），不得以纯动量排序输出候选。
5. Treat bundled screening scripts as the reproducible baseline, not as the only allowed screening logic. When current market conditions justify custom screening rules, define the market regime, rule changes, and risk controls before ranking results; document them in the output.
6. Use deterministic scripts for fetching, screening, and mechanical calculations. Do not rely on LLM mental arithmetic for market cap, valuation multiples, or technical indicators.
7. Store downloaded market data in the local SQLite database, not ad hoc CSV caches. Use `data/investment_research.sqlite` by default; export CSV/XLSX only as final user-facing outputs.
8. Cross-check key data. Mark source, timestamp, unit, currency, and whether data is unavailable. Differences above 1% need a note; above 5% require original filing or exchange-source review before relying on the number.
9. For financial statement numbers in deep reports or final investment conclusions, cross-check TuShare-normalized data against public annual, semiannual, or quarterly reports from CNInfo, exchange disclosures, or company IR pages. Do not rely on TuShare alone for revenue, profit, EPS, balance-sheet, cash-flow, or segment figures.
10. When macro, policy, war/conflict, rates, liquidity, currency, commodities, or regulation could affect the thesis, run a current web search before concluding. Prefer official sources first and cross-check consequential claims with independent reporting. If web access is unavailable, state that real-time macro verification was not completed and reduce confidence.
11. Build a logic chain: macro environment -> industry cycle -> company quality -> valuation/price -> portfolio impact. Do not conclude from technicals, fundamentals, or news alone.
12. When deep-diving a screened shortlist, do not preserve the raw factor ranking as the final ranking. Re-rank by business quality, financial quality, valuation asymmetry, industry cycle, governance/event risk, and buy-before-verification conditions.
13. When sources conflict, list the contradiction instead of smoothing it away. Use wiki contradiction conventions when writing back.
14. Ask before writing sensitive portfolio, funds, or preference data into wiki pages unless the user has explicitly asked to update the wiki in this turn.

## Scripts

Bundled scripts live in `scripts/`:

- `scripts/market_data_store.py`: create and query the local SQLite market-data database.
- `scripts/tushare_sync.py`: sync TuShare A-share daily price, volume, and adjustment-factor data into `data/investment_research.sqlite` using `TUSHARE_TOKEN`.
- `scripts/technical_screen.py`: compute forward-adjusted technical metrics from the local database and merge optional fundamentals into a screening table.
- `scripts/factor_screen.py`: build the deterministic multi-factor A-share shortlist with gates, factor scores, anti-chasing penalties, presets, concentration control, and optional catalyst reranking.
- `scripts/financial_check.py`: verify market cap and valuation multiples.
- `scripts/wiki_index.py`: lint local wiki pages for broken links, missing frontmatter, and missing sources.

In this workspace, thin wrappers are also available under the top-level `scripts/` directory for local testing and reuse.

## Data Persistence

Use `data/investment_research.sqlite` as the reusable local store for downloaded market data. The `a_share_daily` table keeps `trade_date`, `ts_code`, `close_qfq`, `volume`, `source`, and `retrieved_at`, keyed by `(trade_date, ts_code)` so repeated runs update existing rows instead of creating duplicate files.

Do not create per-run CSV caches for fetched prices or volumes. If a workflow needs a shareable table, export the final screen or report artifact under `outputs/`; keep raw and reusable market data in the database.

## Outputs

Use `references/output-templates.md` for exact shapes.

Quick memos must fit roughly one screen and include: conclusion, action, confidence, why, maximum risk or disconfirming condition, data/source timestamp, and whether deeper work is needed.

Deep reports must include: conclusion/action, bull and bear evidence, business quality, valuation view, maximum uncertainty, disconfirming conditions, portfolio impact, four-view disagreements, data appendix, and wiki write-back plan.

## Memory

Use `references/wiki-memory.md` and the local Investment LLM Wiki protocol in `docs/investment-llm-wiki/`:

- Recall before analysis: read `index.md`, then relevant company, industry, thesis, decision, portfolio, and profile pages.
- Update after analysis: append `log.md`; update entity/analysis/decision pages; add `[[links]]`; record contradictions instead of overwriting.
- Keep raw sources immutable.

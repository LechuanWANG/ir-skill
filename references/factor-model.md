# Factor Model

Use this reference for deterministic A-share factor screening. The factor model narrows the market into a shortlist; it is not a trading signal and not a buy/sell decision.

## Core Contract

Screening must be reproducible:

```text
SQLite data -> hard gates -> factor scores -> penalties -> preset composite -> industry cap -> shortlist
```

AI is used after the shortlist for adversarial review. AI may veto or re-rank finalists with evidence, but it must not replace hard gates, factor calculations, or missing data handling.

Default presets are baselines. When current market conditions require custom screening, define the custom rule set before ranking names, run or retain a baseline preset for comparison, and show why the custom result differs.

## Factor Layers

| Layer | Fields | Direction |
|---|---|---|
| trend | `mom_12_1`, `sharpe_60d`, healthy `vr_60d` | higher is better, but overheat is penalized |
| value | `pe_ttm`, `pb`, `ps_ttm`, `dv_ttm`, `pe_pctl_ind`, `pb_pctl_hist` | cheaper and higher yield are better |
| quality | `roe_dt`, `netprofit_margin`, `grossprofit_margin`, `debt_to_assets`, `ocf_to_or` | profitability/cash higher, leverage lower |
| growth | `netprofit_yoy`, `or_yoy` | higher is better, low quality discounts growth |
| risk | `max_drawdown`, volatility proxy, liquidity | penalty or hard gate |
| catalyst | optional bounded CSV/XLSX input for survivors only | reranks survivors, never restores failures |

Missing numeric factor values are neutralized to `0.5` for the affected score and must be mentioned in `pass_reason`.

## Hard Gates

Default gates:

| Gate | Rule |
|---|---|
| data completeness | `completeness >= 0.98` and `actual_window >= 100` |
| ST/delisting | exclude names containing `ST`, `*ST`, or `退` |
| daily valuation | current `daily_basic` row with `pe_ttm`, `pb`, `total_mv`, `circ_mv` |
| size/liquidity | `total_mv >= 500000` and `circ_mv >= 200000` in TuShare ten-thousand CNY units |
| drawdown | `max_drawdown <= 0.45` |
| financial report | current announced `fina_indicator` with `roe_dt`, `netprofit_yoy`, `debt_to_assets` |
| quality | `roe_dt >= 2` |
| profit trend | `netprofit_yoy >= -20` |
| leverage | `debt_to_assets <= 75` |
| overheat hard band | `bias_60d` in `[-0.20, 0.80]`, `vr_60d` in `[0.40, 4.00]` |
| valuation sanity | `pe_ttm > 0` and `pb > 0` |

Every gate writes a `filter_log` row with before, after, and removed counts.

## Presets

Positive factor weights sum to `1.0`; risk is a penalty, not a positive factor.

| preset | trend | value | quality | growth | overheat | valuation percentile |
|---|---:|---:|---:|---:|---|---|
| balanced | 0.20 | 0.30 | 0.25 | 0.25 | medium | medium |
| value | 0.10 | 0.45 | 0.30 | 0.15 | medium | strong |
| growth | 0.20 | 0.15 | 0.25 | 0.40 | medium | weak but kept |
| prosperity | 0.30 | 0.10 | 0.20 | 0.40 | strong | weak but kept |

`balanced` is the default and is intentionally value-led to avoid pure momentum chasing.

## Custom Rule Overlay

Use a custom overlay when the market regime makes the fixed preset incomplete. Examples:

| Market condition | Possible custom rule |
|---|---|
| Falling rates / liquidity easing | allow higher quality-growth tilt, but keep valuation percentile penalty |
| Tight liquidity / risk-off | raise quality, cash-flow, dividend, and liquidity requirements |
| Commodity upcycle | add commodity-price sensitivity and inventory/cash-flow checks |
| Policy-supported industry | add catalyst evidence, policy date, and beneficiary logic |
| War, sanctions, tariffs, or export controls | exclude or flag exposed supply chains; require source-backed event risk |
| Crowded theme / speculative surge | tighten overheat, valuation percentile, turnover, and drawdown filters |

Custom overlays can adjust:

- factor weights or preset choice
- hard-gate thresholds
- industry caps or industry inclusion/exclusion
- catalyst inputs
- risk penalties and concentration limits

Rules:

- Write the market-regime diagnosis and custom rules before final ranking.
- Keep a baseline `balanced` or relevant preset export for comparison.
- Do not disable anti-chasing controls by default.
- Do not restore stocks that fail safety gates unless the user explicitly asks for distressed or special-situation research.
- Mark custom outputs with the rule name, source timestamp, and bias risk.

## Penalties

- 过热惩罚: positive `bias_60d` beyond the healthy band and excessive `vr_60d`; capped before it dominates the model.
- 估值分位惩罚: high `pe_pctl_ind` or own-history percentile without growth support. Strongest in `value`, weakest in `growth` and `prosperity`, but never disabled.
- 风险惩罚: large drawdown or volatility proxy.

Any overheat or valuation percentile penalty sets `追涨风险 = 是` and records the reason in `disqualify_risk`.

## Catalyst Contract（催化）

`--with-catalyst` is optional and off by default.

Allowed input is a bounded CSV/XLSX for gate survivors or preliminary top names:

```text
ts_code,catalyst_score,catalyst_source,catalyst_time
```

Rules:

- `catalyst_score` is clipped to `[0,1]`.
- catalyst adds a 15% positive component only after gates and penalties.
- catalyst cannot restore eliminated stocks.
- missing catalyst is neutral (`0.5`) when enabled and absent (`0.0`) when disabled.
- AI must cite source and time when it creates catalyst inputs.

## Output Requirements

The shortlist must include factor breakdown, penalties, `composite_score`, `style_preset`, `追涨风险`, `pass_reason`, `disqualify_risk`, and `next_step`.

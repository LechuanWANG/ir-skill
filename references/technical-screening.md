# Technical Screening

Use this reference for A-share screening from the local SQLite market-data store.

## Workflow

1. Confirm or update `data/investment_research.sqlite` with `scripts/tushare_sync.py`.
2. Sync price/volume plus factor inputs: `--daily-basic`, `--fina-indicator`, and `--stock-basic`.
3. Refresh current macro/market context when it could affect screening: policy, rates, liquidity, war/conflict, commodities, sector regulation, market style, and risk appetite.
4. Choose the screening plan before ranking results:
   - default baseline: run `scripts/factor_screen.py` with a preset.
   - custom market-regime overlay: define extra filters, factor tilts, industry inclusions/exclusions, catalyst fields, or risk caps before applying them.
5. Run `scripts/factor_screen.py` for the reproducible baseline. Use `scripts/technical_screen.py` only as the raw technical metric layer or for diagnostics.
6. Apply any pre-registered custom overlay to the baseline export or survivor set; keep the baseline ranking available for comparison.
7. Review the shortlist with AI as a skeptic: explain why momentum exists, whether valuation is stretched, whether the setup can continue, and what would disconfirm it.
8. Convert candidates into research work, not automatic buy instructions.

Example:

```bash
python3 scripts/tushare_sync.py 20250101 20260630 --db-path data/investment_research.sqlite
python3 scripts/tushare_sync.py 20250101 20260630 --db-path data/investment_research.sqlite --daily-basic --fina-indicator --stock-basic
python3 scripts/factor_screen.py \
  --db-path data/investment_research.sqlite \
  --as-of 20260630 \
  --preset balanced \
  --top 50 \
  --industry-cap 0.25 \
  --output outputs/screens/factor_screen_20260630.csv
```

Downloaded market data should stay in SQLite. Use CSV/XLSX only for final screen exports, manually supplied enrichment data, or bounded catalyst inputs.

## Custom Market-Regime Screening

Bundled code is a starting point, not a rigid mandate. The user's reference code and local scripts provide reusable factors; the screening lead may define custom rules when the current market regime makes the default preset incomplete.

Custom rules are allowed for:

- market style: value, dividend, growth, small/mid-cap, large-cap quality, cyclical rebound, defensive cash flow
- macro sensitivity: rates, liquidity, currency, commodities, fiscal policy, industrial policy, geopolitics
- sector focus or exclusion: policy-supported sectors, over-owned themes, sanction/export-control exposure, commodity chains
- risk controls: stricter drawdown, turnover, valuation percentile, leverage, pledge, liquidity, or concentration limits
- catalyst overlays: earnings inflection, buyback, policy approval, order cycle, price-cycle trigger, industry capacity exit

Guardrails:

- Pre-register custom rules before seeing or re-ranking final names.
- Keep hard exclusions for ST/delisting, missing key data, extreme overheat, non-positive valuation metrics, and severe liquidity problems unless the user explicitly asks for special situations.
- Never rank by recent return alone; keep valuation and overheat penalties visible.
- Compare custom results with the baseline preset and explain major differences.
- Output the custom rule set, market-regime rationale, source timestamps, and known bias risks.

## Multi-Factor Pipeline（多因子 + 抗追高）

The screening path is:

```text
full universe
-> hard gates
-> trend/value/quality/growth scores
-> overextension, valuation percentile, and risk penalties
-> preset composite score
-> industry concentration cap
-> shortlist with factor breakdown and 追涨风险 label
-> AI adversarial review
```

The script must not rank final candidates by recent return alone. Momentum is an input; valuation percentile and overheat controls are explicit anti-chasing checks.

## Metrics

The raw technical layer computes:

- forward-adjusted prices
- 60 day bias, annualized Sharpe, and volume ratio for factor screening
- 12-1 momentum in `factor_screen.py`
- max drawdown
- completeness and actual window

The factor layer adds:

- industry-relative valuation percentiles
- quality and growth percentiles
- hard-gate `filter_log`
- `trend_score`, `value_score`, `quality_score`, `growth_score`
- `overext_penalty`, `valuation_pctl_penalty`, `risk_penalty`
- `composite_score`, `style_preset`, and `追涨风险`

## AI Review

After the deterministic shortlist, AI reviews finalists. It may veto or reorder candidates only with reasons:

- why it rose: fundamentals, sentiment, liquidity, or one-off event
- whether valuation is stretched using percentile evidence
- whether the trend can continue
- disconfirming conditions
- whether deeper single-stock research is needed

AI review does not override hard gates and does not invent missing factor data.

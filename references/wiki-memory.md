# Investment LLM Wiki Memory

Use the local Investment LLM Wiki at `docs/investment-llm-wiki/` for persistent investment memory.

## Recall Before

Read `docs/investment-llm-wiki/index.md` first, then relevant pages:

- `profile.md` for preferences, risk tolerance, constraints, and deep-mode thresholds
- `portfolio.md` for current holdings
- company/industry/entity pages
- analysis/thesis pages
- decision pages

## Update After

After analysis, update only useful durable knowledge:

- append `log.md`
- update entity pages for durable facts
- update analysis pages for thesis changes
- create decision pages for buy/sell/add/reduce/wait decisions
- use `contradiction` blocks when new evidence conflicts with old claims

Ask before writing sensitive holdings, funds, or preference details unless the user explicitly requested a wiki update.

## Link Discipline

Use wiki links such as `[[portfolio]]`, `[[0700.HK]]`, and `[[2026-07-01-0700-add]]`. Raw source files stay immutable.

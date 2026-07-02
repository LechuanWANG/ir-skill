# Deep Research Mode

Use deep mode for explicit deep research, single-stock investment decisions, large position changes, or four-view analysis.

## Roles

| Role | Focus | Output |
|---|---|---|
| A1 Business/Moat | Business model, customer value, moat durability | Quality conclusion, key evidence, confidence |
| A2 Financial/Valuation | Statements, valuation, cash conversion, key assumptions | Valuation conclusion, assumptions, confidence |
| A3 Industry/Competition | Cycle, competitors, supply/demand, policy | Industry conclusion, risks, confidence |
| A4 Risk/Management | Bear case, governance, management, disconfirmation | Risk conclusion, kill conditions, confidence |

## Portable Orchestration

Deep mode is a user-authorized four-agent workflow. When the runtime supports native subagents, spawn A1-A4 as parallel native subagents by default, with one bounded task per role. If subagents are unavailable, run the four analyses sequentially in the main agent using the same role prompts and output schema.

Subagent delegation must be scoped:

- A1-A4 each research only their assigned lens.
- Each subagent returns evidence, counter-evidence, confidence, unknowns, and action implication.
- The lead does not outsource the final decision memo; the lead reconciles conflicts and writes the final output.
- Preserve missing or failed subagent work as an explicit caveat instead of silently filling it in.

Each role must return:

```text
Conclusion:
Evidence:
Counter-evidence:
Confidence:
Unknowns:
Implication for action:
```

## Team Lead Duties

The lead must:

1. Reconcile conflicts explicitly.
2. List disagreements rather than blending them away.
3. Preserve missing-role failures as caveats.
4. Produce the final quick/deep template.
5. Propose wiki write-back locations.

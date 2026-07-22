---
name: ir-skill
description: Evidence-led China and cross-asset investment research. Use for A-share, Hong Kong, or US equity research; all-market financial-statement screening; China macro analysis; ETF, fund, index, futures, spot commodity, option, convertible-bond, or foreign-exchange research; technical or catalyst screening; entry or exit analysis; portfolio review; price or news attribution; research planning; decision evaluation; or research-source archival. Use persistent research memory only when the user explicitly asks to read, reuse, save, ingest, or update it.
---

# IR Skill

兼容入口与研究路由器：不重复各持有期的方法，只为当前决策选择必要路径。

## 1. 先设边界

先读取 [`skills/shared/research-discipline.md`](skills/shared/research-discipline.md)。区分事实、推断、情景和未知项，记录来源、`as_of`、口径和反证；未经授权，不读取或写入持仓、跟踪池、历史观点、资料库或 Wiki。

## 2. 按问题路由

- 多年持有、商业/财务质量、治理、资本配置或长期估值：[`skills/ir-long-term-trading/SKILL.md`](skills/ir-long-term-trading/SKILL.md)。
- 3–6 个月盈利、订单、供需、政策、产品或估值催化：[`skills/ir-medium-term-catalyst/SKILL.md`](skills/ir-medium-term-catalyst/SKILL.md)。
- 一个月内事件、技术、动量、因子、入场或价格异动：[`skills/ir-short-term-trading/SKILL.md`](skills/ir-short-term-trading/SKILL.md)。
- 明确要求深度研究、独立审阅或交叉质询：在对应持有期路径上加读 [`skills/ir-deep-review/SKILL.md`](skills/ir-deep-review/SKILL.md)。

结论同时依赖中期催化和短期执行时，调用两个路径并说明各自如何影响行动标签。

## 3. 补齐证据与项目边界

原始披露、政策或网页证据读取 [`skills/shared/external-evidence-sources.md`](skills/shared/external-evidence-sources.md)；TuShare 或 SQLite 读取 [`references/tushare-data.md`](references/tushare-data.md)。持仓、组合或跟踪池读取 [`skills/shared/portfolio-and-watchlist.md`](skills/shared/portfolio-and-watchlist.md)；项目初始化、缓存、`.env` 或数据同步读取 [`skills/shared/project-and-data.md`](skills/shared/project-and-data.md)；保存、复用、复盘、原件归档、任务恢复或 Wiki 读取 [`references/persistence.md`](references/persistence.md)。

脚本、规则和 Research Hub 静态资源属于 Skill 安装目录；用户的 `.env`、SQLite、报告、原始资料、Wiki、持仓和交易记录必须位于明确选择的项目目录。

短线研究的保存与复盘是可选旁路，不是研究选股流程的必经步骤：`screen`/`evidence`/`confirm` 完成推荐后即可结束；推荐只进入项目推荐集合。只有用户随后明确提出复盘，Agent 才能调用 `review` 读取该推荐的历史快照和后续行情。保存推荐不等于执行交易，未提供执行事实时不得推断持仓或账户盈亏。

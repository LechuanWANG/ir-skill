---
name: ir-skill
description: Evidence-led China and cross-asset investment research. Use for A-share, Hong Kong, or US equity research; all-market financial-statement screening; China macro analysis; ETF, fund, index, futures, spot commodity, option, convertible-bond, or foreign-exchange research; technical or catalyst screening; entry or exit analysis; portfolio review; price or news attribution; research planning; decision evaluation; or research-source archival. Use persistent research memory only when the user explicitly asks to read, reuse, save, ingest, or update it.
---

# IR Skill

这是 IR Skill 的兼容入口与路由器。它保留广泛投研任务的触发能力，但不重复加载所有研究方法；根据决策期限和问题性质，只读取必要的子 Skill 与共享材料。

## 共同纪律

所有研究先读取 [`skills/shared/research-discipline.md`](skills/shared/research-discipline.md)。区分事实、推断、情景与未知项；保留来源、`as_of`、口径和反证；未经用户授权，不读取或写入持仓、跟踪池、历史报告、资料库或 Wiki。

## 研究路由

- 多年持有、商业质量、财务质量、治理、资本配置或长期估值：读取 [`skills/ir-long-term-trading/SKILL.md`](skills/ir-long-term-trading/SKILL.md)。
- 约 3–6 个月的盈利、订单、供需、政策、产品或估值催化：读取 [`skills/ir-medium-term-catalyst/SKILL.md`](skills/ir-medium-term-catalyst/SKILL.md)。
- 一个月内的事件、技术面、动量、因子筛选、入场节奏或价格异动：读取 [`skills/ir-short-term-trading/SKILL.md`](skills/ir-short-term-trading/SKILL.md)。
- 明确要求深度研究、独立审阅或交叉质询：在对应持有期子 Skill 的基础上读取 [`skills/ir-deep-review/SKILL.md`](skills/ir-deep-review/SKILL.md)。

需要原始披露、政策或网页证据时读取 [`skills/shared/external-evidence-sources.md`](skills/shared/external-evidence-sources.md)；需要 TuShare 或本地 SQLite 时读取 [`references/tushare-data.md`](references/tushare-data.md)；需要保存、复用、复盘或 Wiki 时读取 [`references/persistence.md`](references/persistence.md)。

## 项目边界

脚本、规则和 Research Hub 静态资源属于 Skill 安装目录；用户的 `.env`、SQLite、报告、原始资料、Wiki、持仓和交易记录必须写入用户明确选择的项目目录。首次初始化或检查时使用 `scripts/ir_project.py`，不在安装目录创建用户研究资产。

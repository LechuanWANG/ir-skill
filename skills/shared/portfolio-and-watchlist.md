# 当前持仓与研究跟踪池

只在共享纪律指定的触发条件下读取。本文件管理项目级当前持仓和研究跟踪池，不授权读取完整交易历史、历史报告或其他记忆。

## 1. 当前持仓

当前持仓保存在所选项目的 `data/research-library/settings/investor-profile.json`。Agent 不直接编辑，统一使用 `scripts/portfolio_context.py`，运行前先执行 `--help`。

- 用户明确陈述当前持仓且不是假设、计划或条件情景时，允许记录；证券代码和数量明确后使用 `upsert`，成本、截至日期或备注缺失时只保存已知事实。写入后复述代码、数量、成本和时点。
- 用户说明已清仓或持仓为零时使用 `remove`；“准备买入”“考虑卖出”“若达到某价格”等计划不改变当前持仓。
- 持仓研究、组合/仓位分析、加减仓、止损、退出或持仓策略开始前使用 `show`；只涉及一个明确标的时，用 `--symbol` 限定读取范围。
- 普通事实查询、宏观研究或不要求结合持仓的通用标的研究不读取持仓。持仓只能改变组合适配、风险和行动结论，不能改变标的事实判断。
- `latest_price` 为空或过期时，只引用数量、成本和备注；需计算当前盈亏、止损或价格风险时另取截至研究 `as_of` 的行情，不把旧价称为实时价格。

```bash
python3 scripts/portfolio_context.py upsert --project-dir <项目目录> --symbol <代码> --quantity <数量> [--name <名称>] [--average-cost <成本>] [--as-of YYYY-MM-DD] [--notes <备注>]
python3 scripts/portfolio_context.py show --project-dir <项目目录> [--symbol <代码>]
python3 scripts/portfolio_context.py remove --project-dir <项目目录> --symbol <代码>
```

## 2. 研究跟踪池

研究跟踪池保存在 `data/research-library/tracking/research-watchlist.json`，只索引值得继续研究的股票及其原研究路径；详细证据仍在正式报告。Agent 不直接编辑，统一使用 `scripts/research_watchlist.py`，运行前先执行 `--help`。

- 对明确标的完成推荐、候选比较或行动研究后，若结论为 `优先行动`、`等待价格` 或 `等待证据` 且值得跟踪，使用 `upsert`；纯提及、筛除、假设、`选择现金`、`退出或回避` 不自动新增，除非用户明确要求。
- 写入实际 `research_path`、行动标签、核心逻辑、跟踪条件、失效条件、置信度、研究日、复核日；已有正式报告时用 `--source-report` 关联项目内报告，不虚构路径。
- 全市场筛选、寻找新机会、重新选股、行业内选股或生成新名单时进入全新发现模式：不读取整个跟踪池，不用历史状态、逻辑或置信度缩小研究范围、提升排序或替代本轮证据。
- 只有用户明确要求查看跟踪池、继续跟踪、复盘、复用历史研究，或点名已跟踪股票并要求沿原路径研究时才读取对应记录；审阅整个跟踪池必须获得明确授权。重新研究时复核价格、披露、催化、风险和时效，保留观点变化。
- 不再值得主动跟踪时设为 `paused` 或 `archived`，保留历史；只有用户明确要求才永久 `remove`。

```bash
python3 scripts/research_watchlist.py upsert --project-dir <项目目录> --symbol <代码> --research-path <long-term|medium-term|short-term|mixed> [--status <状态>] [--action-label <行动标签>] [--thesis <核心逻辑>] [--follow-up <跟踪条件>] [--invalidation <失效条件>] [--next-review-on YYYY-MM-DD] [--source-report <report/...md>]
python3 scripts/research_watchlist.py show --project-dir <项目目录> [--symbol <代码>] [--status <状态>] [--include-archived]
python3 scripts/research_watchlist.py remove --project-dir <项目目录> --symbol <代码>
```

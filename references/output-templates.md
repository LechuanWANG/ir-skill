# Output Templates

## Quick Memo

```text
【结论】一句话说明现在该做什么。
【操作】买 / 等 / 加 / 减 / 卖 / 不碰     【置信度】高 / 中 / 低
【为什么】1-2 句大白话。
【最大风险 / 证伪】出现什么情况说明判断错了。
【数据】关键数字 + 来源 + 取数时间；缺失就写“不可得”。
【下一步】是否需要深度模式；是否写回 wiki。
```

## Deep Report

```text
1. 一句话结论 + 操作 + 置信度
2. 看多 3 条 / 看空 3 条（各带证据与来源）
3. 生意与护城河：靠什么赚钱、能不能持续、对手能不能复制
4. 估值：便宜 / 合理 / 偏贵 / 明显贵 + 关键假设
5. 买入前验证条件：价格/估值区间、财报验证点、必须阅读的公告或事件
6. 最大不确定性 + 证伪条件
7. 对当前持仓/组合的影响：核心 / 卫星 / 观察
8. 四视角分歧点：显式列出，不掩盖
9. 数据附录：关键数字 + 双源核对 + 取数时间
10. Wiki 写回计划：写哪些页，是否需要用户确认
```

## Report Artifacts

For generated reports, create one run folder:

```text
outputs/reports/{report_slug}_{YYYYMMDD}/
├── data/      raw pulls, derived CSVs, source_summary.json
├── tex/       LaTeX source
├── build/     compiler scratch files only
├── pdf/       final user-facing PDF only
└── rendered/  rendered PNG pages for visual QA
```

Rules:

- Put the final PDF only under `pdf/`. If the compiler writes a PDF into `build/`, copy it to `pdf/` and remove the build copy after verification.
- Keep TeX, data, rendered images, and compile scratch files in their own subfolders.
- Keep exact raw data files in `data/`; visible report text can summarize source names instead of printing long local paths.

## LaTeX / PDF QA

Before delivering a LaTeX report:

- Escape generated table text for LaTeX special characters: `%`, `_`, `&`, `#`, `$`.
- Use XeLaTeX for Chinese reports.
- Use landscape pages, smaller font sizes, or narrower columns for wide tables.
- Avoid long raw file paths in visible report text; place exact files in the report-local `data/` folder.
- Compile once, inspect fatal errors and obvious layout warnings, then fix the source.
- Render the PDF to PNG and inspect at least the cover, one wide table, one company detail page, and the final page for clipping, overlap, unreadable glyphs, and misplaced headers/footers.

## Screening Output

```text
候选池摘要：
- 数据范围：
- 风格预设：
- 市场局势判断：
- 自定义筛选规则：若无则写“使用默认 baseline”
- baseline 对比：自定义规则相对默认 preset 增删了什么
- 筛选指标：trend/value/quality/growth + overheat/value/risk penalties
- 前 N 名：
- filter_log：
  - 数据完整度：进入 X，剩余 Y，淘汰 Z
  - ST/退市：进入 X，剩余 Y，淘汰 Z
  - 市值/流动性：进入 X，剩余 Y，淘汰 Z
  - 过热硬阈：进入 X，剩余 Y，淘汰 Z
- AI 复核计划：

候选表：
代码 | 名称 | 行业 | trend_score | value_score | quality_score | growth_score | composite_score | style_preset | 追涨风险 | 通过理由 | 淘汰风险 | 下一步
```

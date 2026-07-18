# 研究持久化、恢复与 Wiki

只在以下情况读取：用户明确要求保存、复用、跟踪、复盘或使用历史记忆；或任务确有多阶段、交接、长命令和上下文压缩风险。普通研究、归因、技术筛选和单次查询不建立持久状态。

## 四类存储

- `report/<domain>/<YYYY-MM-DD>/`：面向用户的正式研究报告和决策备忘录；日期目录按报告 `as_of` 命名。
- `data/research-library/database/`：可重复计算和比较的 SQLite 数据。
- `data/research-library/staging/<task-id>/` 与 `files/`：本轮原始资料、临时工作物和经整理的事实型资料。
- `docs/investment-llm-wiki/wiki/`：仅在用户明确启用时维护的综合研究记忆。

不要用任务状态代替报告，不把脚本查询结果包装成资料文档，也不把原始资料归档自动升级为 Wiki 观点。

## 授权边界

- 只有用户明确要求参考、复用或评估历史决策、偏好、持仓、交易记录或报告时，才读取相关历史内容。
- 用户授权复用 `files/` 资料库时，先读取 `data/research-library/files/INDEX.md`，再选择与当前主题直接相关的摘要和原件；索引仅用于导航，不替代原始来源或本轮时效核验。
- 用户只要求保存新内容时，不读取旧 Wiki；用户只要求归档原始资料时，不初始化或更新 Wiki。
- `profile.md` 和 `portfolio.md` 只在用户提供或明确授权时维护。
- Wiki 和旧报告不是当前事实源；复用时重核原始来源、`as_of` 和时效，并保留历史观点的原时间边界。

## 长链路任务状态

满足任一条件时使用 `scripts/research_task_state.py`：任务跨多个阶段、即将运行长命令或读取大量资料、需要 Agent 交接、可能触发上下文压缩，或用户要求保存过程。简单事实核验、单次行情和短答不建立状态。

```bash
python3 scripts/research_task_state.py init --task <task-id> --title "<标题>"
python3 scripts/research_task_state.py checkpoint --task <task-id>
python3 scripts/research_task_state.py complete --task <task-id>
```

在 `research-state.md` 记录足以完整恢复判断与核验路径的信息：目标与约束、`as_of`、已核验/推断/未知、关键证据位置、当前判断、放弃路径、下一步和完成条件。状态应让后续研究者能辨认哪些结论已被证据支持、哪些仍待验证；上下文或运行时间压力不是省略关键状态的理由。只在范围、证据批次、判断或阶段变化时 checkpoint，不在每次工具调用后更新。

恢复时只选择与当前问题匹配的 active/blocked 任务，核对 `as_of`、文件和 SQLite 最新日期，再加载状态指向的证据；不要扫描或混合全部旧任务，以免混入不适用的时间边界或观点。状态与原始证据冲突时以原始证据为准。

## 原始资料归档

用户要求保存或复用外部资料时：

1. 先放入 `data/research-library/staging/<task-id>/raw/`。
2. Agent 逐一审阅原件并决定：整理为可复用资料、保留待核验，或以明确理由丢弃；不要机械转写 HTML、JSON、CSV、工具日志或线性 PDF 文本。
3. 在 `archive-plan.json` 中写入文档内容、来源和丢弃决定；计划必须覆盖 `raw/` 下每一份文件，重要原件进入文档的 `source_files`，其余文件写入 `discard_files`。字段与最新约束以 `python3 scripts/curate_research_library.py archive --help` 和脚本校验为准。
4. 研究完成时执行 `python3 scripts/research_task_state.py complete --task <task-id>`；它会先应用归档计划，再将任务置为终态并删除整个 `staging/<task-id>/`。正式报告、归档资料和 SQLite 是完成后的持久去向，`staging/` 不是恢复仓库。需要在仍可恢复的 active/blocked 任务中提前整理资料时，才显式运行 `curate_research_library.py archive --apply`。

复杂 PDF 默认保留原件。完成渲染查看并记录页码、表名和关键口径后，`pdf_validations` 只用于说明核验程度；原始 PDF 仍随资料摘要归档至 `files/`，不在完成任务时删除。日线、估值、资金、涨跌停、交易日历和披露日历等日常结构化查询只进入 SQLite 或任务暂存区。

### 显式资料采集

对已知、公开且允许访问的静态 URL，使用 `scripts/research_collect.py` 将有效原件放入任务暂存区，而不是手工把未知响应改名为 PDF：

```bash
python3 scripts/research_task_state.py init --task macro-cpi --title "CPI 原始资料"
python3 scripts/research_collect.py collect \
  --task macro-cpi \
  --url "https://example.gov.cn/release.html" \
  --expected-type html
```

采集器只接受显式 `http(s)` URL，限制响应大小，并记录最终 URL、响应类型、获取时间和 SHA-256。有效 HTML/PDF 分别进入 `raw/`；HTML 另生成 `working/collection-reviews/` 的可读审阅副本，PDF 只生成审阅卡，不自动转写事实或表格。归档器会将采集器记录的最终 URL 写进归档 Markdown 的 `source_urls` frontmatter，故清理临时 HTML 后仍可追溯来源。下载到安全校验 HTML、无效 PDF、HTTP 50x 或其他失败时，采集器只在 `working/collection-failures/` 记录原因，不把错误页写成资料原件。需要查看 PDF 页面时：

```bash
python3 scripts/research_collect.py render-pdf \
  --task macro-cpi \
  --source-file raw/official-report.pdf
```

该命令使用本机 `pdftoppm` 把页面渲染到 `working/pdf-pages/`；原始 PDF 在研究中保留于 `raw/`，完成归档后会随核验摘要迁入 `files/`，而不会长期留在暂存目录。

## 正式报告

需要保存的正式报告按以下布局写入：

```
report/<domain>/<YYYY-MM-DD>/<YYYY-MM-DD>-<完整主题>-<报告类型>.md
```

- `<domain>` 使用 `market`、`company`、`industry`、`macro` 等领域名。
- 日期目录与文件名前缀使用报告 `as_of`，格式为 `YYYY-MM-DD`。
- Markdown 文件名必须写全研究主题和报告类型，使用可读的连字符命名；不得只命名为 `report.md`、`analysis.md`、`memo.md` 或其他缩写。
- 示例：`report/company/2026-07-18/2026-07-18-china-shenhua-short-term-trading-screen.md`。
- 仅对新建报告使用此约定。除非用户明确要求，不重命名或迁移既有报告。

报告仍须包含：

```yaml
---
title: <标题>
domain: company|industry|market|macro
subject: <稳定主题名>
as_of: YYYY-MM-DD
type: <报告类型>
---
```

报告保存结论；资料库保存可追溯事实；任务状态保存运行中的控制信息。

## LLM Wiki

只有用户明确要求跨轮复用、持续跟踪、复盘或维护记忆时启用：

1. 确认主题、`as_of`、写入范围，以及是否授权读取历史内容。
2. 只读取与当前主题直接相关的 schema、页面和日志；不扫描全库。
3. 以本轮原始来源和市场数据为准，保留事实、推断、反证、冲突、未知和时间边界。
4. 更新相关页面、索引和日志；需要时运行 `python3 scripts/wiki_index.py --wiki-dir docs/investment-llm-wiki`。

复盘保留旧快照并追加新信息、解释变化和过程改进；不要改写历史结论使其看起来当时已知。

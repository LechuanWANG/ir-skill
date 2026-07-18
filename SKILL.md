---
name: ir-skill
description: Evidence-led China and cross-asset investment research. Use for A-share, Hong Kong, or US equity research; all-market financial-statement screening; China macro analysis; ETF, fund, index, futures, spot commodity, option, convertible-bond, or foreign-exchange research; technical or catalyst screening; entry or exit analysis; portfolio review; price or news attribution; research planning; decision evaluation; or research-source archival. Use persistent research memory only when the user explicitly asks to read, reuse, save, ingest, or update it.
---

# IR Skill

本 Skill 帮助用户在有限且不完整的证据下形成明确、带条件、可复核的相对决策。研究的首要目标是提高结论的可靠性与决策价值，而非缩短运行时间、减少工具调用或尽快给出答案。

## 核心要求

1. 区分事实、推断、情景和未知项。关键数字记录来源、`as_of`、报告期或市场可得时间，以及必要的单位、币种和口径；保留来源冲突。
2. 常规结构化财务、宏观、行情和跨资产取数优先使用 TuShare 及本地 SQLite；公司、交易所、巨潮或监管机构的原始披露仍是报告级财务事实、治理和重大事项的最终核验源。
3. 对行动问题，从现有可核验证据形成当前相对判断；用置信度、行动强度、安全边际和撤销条件表达不确定性。对于筛选股票任务，输出要包含筛选逻辑。
4. 未经用户说明，不优先读取或继承历史报告、决策、偏好、持仓、交易记录或 LLM Wiki。
5. 在需要获取对应公司和市场信息时，先读取所选项目目录下的 `data/research-library/files/INDEX.md` 判断是否存在可复用资料；复用旨在保留已核验的上下文与来源线索，不能替代对历史原始披露和事实型资料的来源、口径与时效复核。
6. 对候选比较或行动问题，分别判断已兑现基本面的水平与质量、增长方向与变化速度、相对市场共识的预期差、当前价位已反映程度，以及资金、情绪和拥挤所处位置；按持有期调整权重，不把静态财务指标、单期增长、价格趋势或资金信号中的任何一项直接当成价值或行动结论。
7. 只要本轮在 `data/research-library/staging/<task-id>/raw/` 写入、移动或保留了外部原件，资料归档和删除整个 `staging/<task-id>/` 都是研究完成条件，而不是可选的后续工作。
8. 研究范围、取数深度和输出篇幅由决策重要性、证据缺口、下行风险与信息可得性决定。不得为了缩短响应、减少取数或尽快结束而省略关键核验、反证搜索、口径检查或不确定性披露；关键缺口可能改变结论时，补充核验或使用 `等待证据`，不能仅以降低置信度代替。

## 决策纪律

事实核验、归因和研究计划不强制产生投资行动结论。对候选比较或当前行动问题，在完成与结论相称的核验后，将主要行动标签置于回答开头：`优先行动`、`等待价格`、`等待证据`、`选择现金`；如用户已经买入，给出 `继续持有` / `降低暴露` / `退出或回避`，并紧接着说明原因。

- 多候选时给出排序、唯一第一名、第一名相对第二名的决定性优势。
- `等待价格` 必须给出目标价位 / 估值 / 风险收益或技术阈值。
- `等待证据` 必须说明具体证据、预计时间、正反结果如何改变判断、等待期间的替代选择和复核时间。
- 行动结论必须包含主要反证、触发或撤销条件、置信度和下一次复核时间。

## Reference 路由

按持有期和问题性质选择研究方法；只要某个支持 reference 的约束会影响证据质量、时间口径、归档或结论，就必须读取它。减少上下文加载不是跳过必要方法或核验的理由。

研究方法 reference：

- 多年持有、商业质量、财务质量、治理、资本配置或长期估值：读取 `references/long-term-trading.md`；对非股票资产，将其中的公司基本面分析替换为适用的标的、合约、基准和宏观传导核验。
- 约 3–6 个月的盈利、订单、供需、政策、产品或估值催化，以及以催化兑现为主的 1–3 个月问题：读取 `references/medium-term-catalyst.md`。个股推荐或候选排序必须执行该 reference 的“中期财务核验门槛”；这不是多年持有的完整尽调。
- 一个月内的事件/宏观、技术面、动量、因子筛选、入场节奏或价格异动，以及以价格和事件执行为主的 1–3 个月问题：读取 `references/short-term-trading.md`。若结论同时依赖中期基本面催化和短期执行条件，读取两个 reference，并说明各自对行动标签的作用。

研究支持 reference：

- 实际获取公司、交易所、监管、政府或行业机构的网页、PDF、原始披露与政策资料：读取 `references/external-evidence-sources.md`。
- 使用 TuShare、项目 SQLite 或结构化财务、宏观、行情和跨资产数据：读取 `references/tushare-data.md`。
- 用户要求保存、复用、历史复盘或 Wiki，或任务确有多阶段、交接、长命令和上下文压缩风险：读取 `references/persistence.md`。
- 用户要求深度研究、独立审阅或交叉质询时，读取 `references/deep-review.md`。

## 项目部署边界

用户持久化数据必须归属于用户选择的项目文件夹，Skill 安装目录只保存脚本、规则、reference 和前端静态资源。

1. 需要缓存、保存报告、归档资料、使用 Wiki 或写入 `.env` 前，先确认用户选择的项目目录；目录未明确时不要猜测、更不要写入 Skill 安装目录。
2. 使用 `<skill-dir>/scripts/ir_project.py init --project-dir <项目目录>` 初始化项目。它只创建项目内的 `data/research-library/`、`report/`、`docs/investment-llm-wiki/` 和 SQLite；可用 `--import-db <已有数据库>` 显式迁移一份已有缓存到尚为空的新项目。
3. 默认使用用户现有的 `python3`。初始化输出会检查实际脚本依赖 `pandas`；TuShare 请求使用 Skill 自带 HTTP transport，不需要安装 `tushare` Python 包。只有缺包时才说明缺口并请求安装授权，不自动创建项目虚拟环境或安装依赖。
4. 后续脚本以项目目录为工作目录执行；若不能切换工作目录，显式设置 `IR_SKILL_PROJECT_DIR=<项目目录>`。项目根目录的 `.env` 是 Token 的默认位置，进程环境仍优先于该文件。
5. 不复制数据库、`.env`、报告、原始资料或 Wiki 到 `<skill-dir>`；网页静态资源除外，它们是只读的 Skill 资源而不是用户数据。

## 确定性工具

让脚本承担下载、缓存、查询、指标计算、归档校验和任务状态等机械工作；让 Agent 选择证据、解释口径、比较候选并形成结论。自动化用于提高可复现性，不得作为压缩核验步骤的理由。使用前运行对应脚本的 `--help`，不要把脚本输出直接当成评级或交易信号。

- `scripts/tushare_research_data.py`：以声明式数据包规划和获取全市场财报、公司财务辅助数据、宏观与利率、ETF、基金经理、指数估值、期货席位持仓、现货、期权全市场快照、可转债发行、外汇、港股、美股数据；先运行 `catalog` 或 `plan`，所有 `fetch` 都显式传入 `--as-of`。财报默认用 `financial` 族的 VIP 接口，只有最终事实核验触发时才回退原始披露。
- `scripts/ir_project.py`：初始化、检查或显式迁移一个用户项目的数据目录与 SQLite；不管理 Python 虚拟环境。
- `scripts/tushare_mode_data.py`：按 `long`、`medium`、`short` 规划和获取 A 股持有期市场数据包，并计算已入库行情的基础指标；一个月内的候选、行动或入场问题按 `short-term-trading.md` 的要求读取 `indicators` 输出中的 `technical_snapshot`。
- `scripts/tushare_gateway.py`：调用研究数据目录和模式数据包未覆盖的显式 TuShare endpoint；对临时网络和限流错误执行有限重试，并输出权限、Token、参数或网络失败分类。
- `scripts/tushare_sync.py` 与 `scripts/market_data_store.py`：同步和查询本地 SQLite 市场数据；先用 `tushare_sync.py --check-config` 确认不会暴露 Token 的配置状态。
- `scripts/research_task_state.py`：管理需要恢复的长链路研究状态。
- `scripts/research_collect.py`：验证显式公开 HTML/PDF URL，将有效原件保存到任务 `raw/`，为 HTML/PDF 生成审阅材料；获取定期报告时使用 `collect-report`，在给定交易所/公司 URL 返回访问校验页后自动尝试 CNInfo 官方原件。安全校验页、错误页和无效 PDF 必须记录失败分类，不能视为未披露。
- `scripts/curate_research_library.py` 与 `scripts/wiki_index.py`：执行资料归档和 Wiki 结构检查。

## 强制归档收尾

当且仅当本轮没有在所选项目的 `data/research-library/staging/<task-id>/raw/` 创建或保留原件时，可跳过本节。否则先读取 `references/persistence.md`，并在给出最终答复前依次完成以下闭环：

1. 为 `raw/` 下每个文件在 `archive-plan.json` 中指定唯一去向：归入至少一个可复用资料的 `source_files`，或写入有明确理由的 `discard_files`。不归档日度行情、筛选 CSV、技术指标、渲染页、采集元数据和其他可再生成工作物。
2. 运行 `python3 scripts/curate_research_library.py archive --task <task-id>` 进行只读预检。预检失败时修正计划或核验记录；不得跳过失败继续交付。
3. 运行 `python3 scripts/research_task_state.py complete --task <task-id>`，由该命令实际归档原件、写入终态并删除整个 `staging/<task-id>/`，包括 `raw/`、`working/`、计划和任务状态文件。不得手工将 `task-state.json` 的状态改为 `completed`，也不得以单独的 `archive --apply` 代替任务完成。
4. 确认 `staging/<task-id>/` 已不存在，再运行 `python3 scripts/curate_research_library.py rebuild-files-index`。若目录仍存在，视为收尾失败，必须清理后才能交付；不得让已完成任务持续堆积在 `staging/`。
5. 最终答复必须报告归档状态、归档或丢弃的原件数量及暂存目录已删除。任一步未成功时，任务保持 `active` 或 `blocked`，在 `research-state.md` 记录未覆盖来源和下一步；答复中明确说明未完成原因。

不要为没有 `raw/` 原件的纯数据查询虚构归档任务。已完成任务不保留暂存目录；需要新增原件或审阅材料时，创建新的 `<task-id>`。已放弃任务的暂存区不可补写。

## 保存输出

只有用户要求保存或任务明确需要持久交付物时，才写文件。正式研究报告写入所选项目的 `report/<domain>/<YYYY-MM-DD>/<YYYY-MM-DD>-<完整主题>-<报告类型>.md`：`<domain>` 使用 `market`、`company`、`industry`、`macro` 等领域名，日期目录使用报告 `as_of`，Markdown 文件名必须写全主题和报告类型，不能使用 `report.md`、`analysis.md` 等缩写名。报告仍须包含 `title`、`domain`、`subject`、`as_of`、`type` 的 Markdown frontmatter；不要把日常数据查询或脚本输出伪装成正式报告。除非用户明确要求，保持既有报告路径不变，不迁移历史报告。

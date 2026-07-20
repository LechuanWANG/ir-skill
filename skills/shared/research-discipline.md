# IR Skill

本 Skill 帮助用户在有限且不完整的证据下形成明确、带条件、可复核的相对决策。研究的首要目标是提高结论的可靠性与决策价值，而非缩短运行时间、减少工具调用或尽快给出答案。

## 核心要求

1. 区分事实、推断、情景和未知项。关键数字记录来源、`as_of`、报告期或市场可得时间，以及必要的单位、币种和口径；保留来源冲突。
2. 常规结构化财务、宏观、行情和跨资产取数优先使用 TuShare 及本地 SQLite；公司、交易所、巨潮或监管机构的原始披露仍是报告级财务事实、治理和重大事项的最终核验源。
3. 对行动问题，从现有可核验证据形成当前相对判断；用置信度、行动强度、安全边际和撤销条件表达不确定性。对于筛选股票任务，输出要包含筛选逻辑。
4. 当用户要求最终筛出三只股票时，三席均由通过当前模式标准的股票构成。若某席结论为 `选择现金` / `保持现金`，从候补池按同一标准继续筛选并替换；候选池穷尽后仍不足三只时，报告实际数量和缺口原因。
5. 未经用户说明，不优先读取或继承历史报告、决策、偏好、持仓、交易记录或 LLM Wiki。
6. 在需要获取对应公司和市场信息时，先读取所选项目目录下的 `data/research-library/files/INDEX.md` 判断是否存在可复用资料；定期报告统一使用 `research_collect.py collect-report`，由脚本先查询当前任务与项目资料库，返回 `reused` 时直接使用已有摘要和原始 PDF，只对缺失的公司/报告期执行下载。该检查只读取相关公司的资料元数据和定期报告，不授权继承历史投资观点。复用不能替代对来源、口径、修订与时效的复核。
7. 对候选比较或行动问题，分别判断已兑现基本面的水平与质量、增长方向与变化速度、相对市场共识的预期差、当前价位已反映程度，以及资金、情绪和拥挤所处位置；按持有期调整权重，不把静态财务指标、单期增长、价格趋势或资金信号中的任何一项直接当成价值或行动结论。
8. 只要本轮在 `data/research-library/staging/<task-id>/raw/` 写入、移动或保留了外部原件，资料归档和删除整个 `staging/<task-id>/` 都是研究完成条件，而不是可选的后续工作。
9. 研究范围、取数深度和输出篇幅由决策重要性、证据缺口、下行风险与信息可得性决定。不得为了缩短响应、减少取数或尽快结束而省略关键核验、反证搜索、口径检查或不确定性披露；关键缺口可能改变结论时，补充核验或使用 `等待证据`，不能仅以降低置信度代替。

## 决策纪律

事实核验、归因和研究计划不强制产生投资行动结论。对候选比较或当前行动问题，在完成与结论相称的核验后，将主要行动标签置于回答开头：`优先行动`、`等待价格`、`等待证据`、`选择现金`；如用户已经买入，给出 `继续持有` / `降低暴露` / `退出或回避`，并紧接着说明原因。

- 多候选时给出排序、唯一第一名、第一名相对第二名的决定性优势。
- `等待价格` 必须给出目标价位 / 估值 / 风险收益或技术阈值。
- `等待证据` 必须说明具体证据、预计时间、正反结果如何改变判断、等待期间的替代选择和复核时间。
- 行动结论必须包含主要反证、触发或撤销条件、置信度和下一次复核时间。

## 当前持仓上下文

当前持仓保存在所选项目的 `data/research-library/settings/investor-profile.json`。Agent 不直接编辑该文件，统一使用 `scripts/portfolio_context.py`；运行前先执行 `--help`。

- 用户明确陈述自己的当前持仓，且不是假设、计划或条件情景时，将该陈述视为允许记录该持仓。证券代码和数量明确后运行 `upsert`；成本、持仓截至日期或备注缺失时只保存已知事实，不猜测。写入后向用户复述保存的代码、数量、成本和时点。
- 用户说明已经清仓或当前持仓为零时运行 `remove`。用户说“准备买入”“考虑卖出”“如果达到某价格就交易”等计划时，不改变当前持仓。
- 当用户要求针对其持仓研究、组合/仓位分析、加减仓、止损、退出或基于持仓设计交易策略时，研究开始前运行 `show` 读取全部当前持仓。当行动问题只涉及一个明确标的时，可用重复的 `--symbol` 只读取相关持仓。
- 普通事实查询、宏观研究或用户未要求结合持仓的通用标的研究不读取持仓。当前持仓只能改变组合适配、风险和行动结论，不能改变对标的事实与证据的判断。
- `latest_price` 为空或过期时，只引用数量、成本和用户备注；需要当前盈亏、止损或价格风险时另行获取截至研究 `as_of` 的行情并明确时间口径。不得把用户保存的旧价格称为实时价格。

```bash
python3 scripts/portfolio_context.py upsert --project-dir <项目目录> --symbol <代码> --quantity <数量> [--name <名称>] [--average-cost <成本>] [--as-of YYYY-MM-DD] [--notes <备注>]
python3 scripts/portfolio_context.py show --project-dir <项目目录> [--symbol <代码>]
python3 scripts/portfolio_context.py remove --project-dir <项目目录> --symbol <代码>
```

## 研究跟踪池

研究跟踪池保存在所选项目的 `data/research-library/tracking/research-watchlist.json`。它只索引值得继续研究的股票与原研究路径；详细证据仍保存在正式报告中。将跟踪池视为按需研究记忆，不得视为默认选股池、白名单、用户偏好或全市场候选集。Agent 不直接编辑该文件，统一使用 `scripts/research_watchlist.py`；运行前先执行 `--help`。

- 对明确标的完成推荐、候选比较或行动研究后，如结论为 `优先行动`、`等待价格` 或 `等待证据`，且该股票值得继续跟踪，使用 `upsert` 写入或更新。只被提及、已被筛除、纯假设、`选择现金` 或 `退出或回避` 的股票不自动新增；用户明确要求加入跟踪池时除外。
- 写入实际采用的 `research_path`、行动标签、核心逻辑、下一步跟踪条件、失效条件、置信度、研究日期和下一次复核日期。若本轮已保存正式报告，用可重复的 `--source-report` 关联项目内 `report/` 下的 Markdown；不虚构报告路径。
- 用户只要求全市场筛选、寻找新机会、重新选股、行业内选股或生成新的候选名单时，默认进入“全新发现模式”：不运行无 `--symbol` 的 `show`，不预读跟踪池代码，不用历史状态、行动标签或置信度缩小研究范围、提升排序或替代本轮筛选证据。即使前一轮由 Agent 自动写入过标的，后续任务也不因此获得读取授权。
- 只有用户明确要求查看跟踪池、继续跟踪、复盘、复用历史研究，或明确点名一只已跟踪股票并要求沿原路径研究时，才进入“继续跟踪模式”。研究开始前用 `show --symbol` 只读取点名标的；只有用户明确要求审阅整个跟踪池时才读取全部记录。按保存的 `research_path` 调用原研究子 Skill，并按需读取仍存在的关联报告；如果用户改变持有期或问题性质，改用新的研究路径并在结论中说明。
- 跟踪池中的股票可以在全新筛选中凭本轮统一标准再次入选，但不得因已被跟踪获得加分、保底名额或优先核验。先独立完成候选生成和排序；只有用户同时授权复用跟踪池时，才能在排序后检查重合并补充历史上下文。
- 跟踪池中的历史逻辑和行动标签只代表原 `as_of` 下的判断，不能直接当作当前事实或当前推荐。重新研究时复核价格、披露、催化、风险和时效，保留观点变化，并在完成后更新最近研究日、逻辑、条件、状态和关联报告。
- 不再值得主动跟踪时将状态改为 `paused` 或 `archived`，保留历史索引；只有用户明确要求永久删除时才运行 `remove`。

```bash
python3 scripts/research_watchlist.py upsert --project-dir <项目目录> --symbol <代码> --research-path <long-term|medium-term|short-term|mixed> [--status <状态>] [--action-label <行动标签>] [--thesis <核心逻辑>] [--follow-up <跟踪条件>] [--invalidation <失效条件>] [--next-review-on YYYY-MM-DD] [--source-report <report/...md>]
python3 scripts/research_watchlist.py show --project-dir <项目目录> [--symbol <代码>] [--status <状态>] [--include-archived]
python3 scripts/research_watchlist.py remove --project-dir <项目目录> --symbol <代码>
```

## 子 Skill 与 Reference 路由

按持有期和问题性质选择研究方法；只要某个支持 reference 的约束会影响证据质量、时间口径、归档或结论，就必须读取它。减少上下文加载不是跳过必要方法或核验的理由。

按持有期和问题性质调用一个或多个子 Skill。每个子 Skill 都在自身 `SKILL.md` 中包含对应的详细方法，并在需要时路由到共享的外部证据、结构化数据和持久化 reference。

- 多年持有、商业质量、财务质量、治理、资本配置或长期估值：调用 `../ir-long-term-trading/SKILL.md`。对非股票资产，将其中的公司基本面分析替换为适用的标的、合约、基准和宏观传导核验。
- 约 3–6 个月的盈利、订单、供需、政策、产品或估值催化，以及以催化兑现为主的 1–3 个月问题：调用 `../ir-medium-term-catalyst/SKILL.md`。个股推荐或候选排序必须执行其“中期财务核验门槛”；这不是多年持有的完整尽调。
- 一个月内的事件/宏观、技术面、动量、因子筛选、入场节奏或价格异动，以及以价格和事件执行为主的 1–3 个月问题：调用 `../ir-short-term-trading/SKILL.md`。若结论同时依赖中期基本面催化和短期执行条件，调用两个子 Skill，并说明各自对行动标签的作用。

研究支持 reference：

- 实际获取公司、交易所、监管、政府或行业机构的网页、PDF、原始披露与政策资料：读取 `external-evidence-sources.md`。
- 使用 TuShare、项目 SQLite 或结构化财务、宏观、行情和跨资产数据：读取 `../../references/tushare-data.md`。
- 用户要求保存、复用、历史复盘或 Wiki，或任务确有多阶段、交接、长命令和上下文压缩风险：读取 `../../references/persistence.md`。
- 用户要求深度研究、独立审阅或交叉质询时，调用 `../ir-deep-review/SKILL.md`。

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
- `scripts/tushare_mode_data.py`：按 `long`、`medium`、`short` 规划和获取 A 股持有期市场数据包，并计算已入库行情的基础指标；一个月内的候选、行动或入场问题按 [`../ir-short-term-trading/SKILL.md`](../ir-short-term-trading/SKILL.md) 的要求读取 `indicators` 输出中的 `technical_snapshot`，其中包括历史高低点、回撤、长期路径和覆盖区间的 `historical_price_structure`。
- `scripts/tushare_sector_data.py`：以同花顺为默认市场板块口径，规划、获取并规范化板块字典、日线、行业资金流和成分快照；`performance` 从项目 SQLite 输出有效交易日、涨跌排序、5/20 个交易日强度、资金流覆盖和市场宽度，`memberships` 核验个股实际板块归属。申万 2021 继续作为稳定的基本面行业参照，不与同花顺、东财或通达信代码混用。
- `scripts/tushare_gateway.py`：调用研究数据目录和模式数据包未覆盖的显式 TuShare endpoint；对临时网络和限流错误执行有限重试，并输出权限、Token、参数或网络失败分类。
- `scripts/tushare_sync.py` 与 `scripts/market_data_store.py`：同步和查询本地 SQLite 市场数据；先用 `tushare_sync.py --check-config` 确认不会暴露 Token 的配置状态。
- `scripts/research_task_state.py`：管理需要恢复的长链路研究状态。
- `scripts/portfolio_context.py`：原子记录、更新、删除和读取项目级当前持仓，并在价格已提供时计算轻量盈亏上下文；不记录计划交易或推断缺失字段。
- `scripts/research_watchlist.py`：原子维护项目级研究跟踪池，保存股票的研究路径、逻辑、复核条件和正式报告链接；不复制报告证据或把旧结论当成当前事实。
- `scripts/research_collect.py`：验证显式公开 HTML/PDF URL，将有效原件保存到任务 `raw/`，为 HTML/PDF 生成审阅材料；获取定期报告时必须使用 `collect-report`。该命令先按公司、报告类型、报告期与来源 URL 查询任务暂存区和 `data/research-library/files/`，精确命中时返回 `reused` 且不访问下载源；旧归档若把多个报告 PDF 合并在同一摘要目录，只查询 CNInfo 公告元数据以按官方 URL 消除歧义，不重复下载已归档 PDF。真正缺失时才尝试给定交易所/公司 URL，并按报告分类与目标年份查询 CNInfo 官方原件。安全校验页、错误页和无效 PDF 必须记录失败分类，不能视为未披露。
- `scripts/curate_research_library.py` 与 `scripts/wiki_index.py`：执行资料归档和 Wiki 结构检查。

## 强制归档收尾

当且仅当本轮没有在所选项目的 `data/research-library/staging/<task-id>/raw/` 创建或保留原件时，可跳过本节。否则先读取 `../../references/persistence.md`，并在给出最终答复前依次完成以下闭环：

1. 为 `raw/` 下每个文件在 `archive-plan.json` 中指定唯一去向：归入至少一个可复用资料的 `source_files`，或写入有明确理由的 `discard_files`。每份文档的 `as_of` 写市场/证据时点，`archived_on` 写当日归档日期；省略后由脚本按香港时区补为执行当天，显式写入也必须等于当天。资料库路径、附件文件名和索引日期只使用 `archived_on`。不归档日度行情、筛选 CSV、技术指标、渲染页、采集元数据和其他可再生成工作物。
2. 运行 `python3 scripts/curate_research_library.py archive --task <task-id>` 进行只读预检。预检失败时修正计划或核验记录；不得跳过失败继续交付。
3. 运行 `python3 scripts/research_task_state.py complete --task <task-id>`，由该命令实际归档原件、写入终态并删除整个 `staging/<task-id>/`，包括 `raw/`、`working/`、计划和任务状态文件。不得手工将 `task-state.json` 的状态改为 `completed`，也不得以单独的 `archive --apply` 代替任务完成。
4. 确认 `staging/<task-id>/` 已不存在，再运行 `python3 scripts/curate_research_library.py rebuild-files-index`。若目录仍存在，视为收尾失败，必须清理后才能交付；不得让已完成任务持续堆积在 `staging/`。
5. 最终答复必须报告归档状态、归档或丢弃的原件数量及暂存目录已删除。任一步未成功时，任务保持 `active` 或 `blocked`，在 `research-state.md` 记录未覆盖来源和下一步；答复中明确说明未完成原因。

不要为没有 `raw/` 原件的纯数据查询虚构归档任务。已完成任务不保留暂存目录；需要新增原件或审阅材料时，创建新的 `<task-id>`。已放弃任务的暂存区不可补写。

## 保存输出

只有用户要求保存或任务明确需要持久交付物时，才写文件。正式研究报告写入所选项目的 `report/<domain>/<YYYY-MM-DD>/<YYYY-MM-DD>-<完整主题>-<报告类型>.md`：`<domain>` 使用 `market`、`company`、`industry`、`macro` 等领域名，日期目录与文件名前缀使用写入当天（香港时区），Markdown 文件名必须写全主题和报告类型，不能使用 `report.md`、`analysis.md` 等缩写名。报告 frontmatter 必须包含 `title`、`domain`、`subject`、`as_of`、`archived_on`、`type`，其中 `as_of` 只表示市场/证据时点，`archived_on` 必须等于写入当天（香港时区）；不要把日常数据查询或脚本输出伪装成正式报告。除非用户明确要求，保持既有报告路径不变，不迁移历史报告。

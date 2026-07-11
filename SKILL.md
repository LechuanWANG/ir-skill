---
name: local-investment-research
description: Use when the user asks for long-term-first stock analysis, diversified A-share candidate discovery, actionable stock recommendations, watchlist refreshes, TuShare research data planning, current entry assessment, anti-chasing and opportunity-cost checks, portfolio review, position sizing, market or price-move attribution, deep investment research, thesis tracking, decision evaluation, or maintaining a local investment knowledge base. Distinguish discovery, refresh, and decision requests; use technical or multi-factor screening only when explicitly requested.
---

# 本地投资研究

## 概览

把这个技能当作长期优先的本地投资研究工作台。先判断公司未来 3–5 年是否值得持有和持续研究，再用近期事件、宏观、行业、估值、技术面与组合约束判断现在能不能买。输出是带证据、条件和时间戳的决策备忘录，不是泛泛研究文章。

这只提供研究辅助。不要把输出表述成收益承诺、金融建议或自动化交易指令。

## 路由

先识别用户请求，只加载直接需要的 reference：

| 用户意图 | 读取这些参考资料 | 默认深度 |
|---|---|---|
| 单只股票是否值得买/持有 | `references/research-screening.md`, `references/tushare-research.md`, `references/fundamental-research.md`, `references/news-intelligence.md`, `references/industry-macro.md`, `references/technical-screening.md`, `references/decision-framework.md`, `references/data-sources.md`, `references/output-templates.md` | 深度 |
| A 股候选发现/筛选（未明确量化或技术面） | `references/research-screening.md`, `references/tushare-research.md`, `references/fundamental-research.md`, `references/industry-macro.md`, `references/news-intelligence.md`, `references/decision-framework.md`, `references/data-sources.md`, `references/output-templates.md` | `discovery`：输出多样化研究队列，不生成未完成的买入行动 |
| 推荐股票/现在可以买什么/必须给结论 | 上述候选资料，加 `references/technical-screening.md` | `decision`：建池后只深研前 2–3 只，必须给相对结论、现金比较和最接近买入对象 |
| 更新上次标的/观察池复盘 | `references/wiki-memory.md`, `references/research-screening.md`, `references/news-intelligence.md`, `references/output-templates.md`，有实质变化时追加对应资料 | `refresh`：只写新事实、结论差异和到期复核，不重复完整旧报告 |
| 全市场多因子/技术面初筛（用户明确要求） | `references/factor-model.md`, `references/technical-screening.md`, `references/research-screening.md`, `references/tushare-research.md`, `references/output-templates.md` | 量化研究池；不得当作长期结论或买入列表 |
| A 股深度研究/重大决策 | `references/deep-research-mode.md`, `references/research-screening.md`, `references/tushare-research.md`, `references/fundamental-research.md`, `references/news-intelligence.md`, `references/industry-macro.md`, `references/technical-screening.md`, `references/decision-framework.md`, `references/data-sources.md`, `references/output-templates.md` | 深度 |
| 组合复盘或仓位测算 | `references/research-screening.md`, `references/portfolio-thesis.md`, `references/wiki-memory.md`, `references/decision-framework.md`, `references/output-templates.md` | 快速；重大仓位变化时加深 |
| 价格异动或新闻归因 | `references/news-intelligence.md`, `references/industry-macro.md`, `references/data-sources.md`，涉及持仓时加 `references/portfolio-thesis.md` | 快速 |
| 事件后是否能买 | 价格异动路径加 `references/research-screening.md`, `references/tushare-research.md`, `references/fundamental-research.md`, `references/technical-screening.md`, `references/output-templates.md` | 深度 |
| 20/60/120 日决策复盘 | `references/research-evaluation.md`, `references/research-screening.md`, `references/wiki-memory.md`, `references/data-sources.md` | 评估 |
| 文件/报告/Wiki 导入 | `references/wiki-memory.md`, `references/output-templates.md` | Wiki 工作流 |

路由逻辑只放在本文件，不增加第二跳路由文档。`references/research-screening.md` 是阶段、状态和行动枚举的唯一真源，其他文档不得定义冲突版本。

## 运行规则

1. 把当前项目目录作为唯一、长期使用的研究工作区。鼓励用户持续在同一目录中使用本 Skill，使 `docs/investment-llm-wiki/`、`data/investment_research.sqlite`、`outputs/` 和项目本地 `.env` 保持同一份连续记录；不要跨项目自动搜索或合并这些文件。
2. 请求涉及当前持仓、偏好、历史决策、投资假设跟踪或本地文档时，分析前先读该工作区的 `docs/investment-llm-wiki/index.md` 和相关页面。
3. 任何“是否值得买/加仓/持有”的问题都执行双阶段状态机：阶段 L 先给 `long_term_status`，阶段 N 再给 `entry_action` 和 `portfolio_action`。
4. 阶段 L 使用 3–5 年生意、增长、竞争、财务、资本配置、治理和长期隐含预期证据。把未知项分为 `blocking_evidence`、`confidence_limiters` 和 `monitoring_items`；只有可能改变长期状态、回报门槛或重大下行情景的阻断项才生成 `needs_evidence`。流程字段、证据 ID、情景或数据窗口不完整时保持 `research_status=in_progress`，不得伪装成投资结论。`rejected` 必须对应 `avoid`。
5. 不要默认运行固定技术筛选。把“筛选股票”“A 股选股”路由为 `discovery`：先用 `scripts/fundamental_pool.py` 建立 `long_term_status=not_evaluated` 的多样化研究池，再用 `scripts/tushare_research.py staged-plan` 规划 `long-term-quality + risk-review`。把“推荐几个标的”“现在可以买什么”路由为 `decision`：完成候选池后只深研前 2–3 只，直到形成正式行动。研究池对象保持 `research_status=queued/in_progress`，不进入四桶。
6. 使用 `scripts/news_intake.py` 只发现和验证事件、映射 `thesis_id`、提示催化或证伪。未核实新闻不进入最终证据，新闻热度不生成长期排名。
7. 只有用户明确要求“多因子”“量化初筛”“动量”“技术面筛选”或同义方法时，才运行 `factor_screen.py --explicit-quantitative-baseline`。它是可选的研究池基线，不是默认入口；因子和 catalyst 只能改变候选或研究优先级，不能直接生成 `long_term_status` 或 `entry_action`。
8. 技术面判断流动性、拥挤、过热、下行风险、入场节奏和长期机会成本。`scripts/technical_screen.py` 只接受已知的阶段 L 候选；不足 500 个前复权交易日时不得声称长期横盘或趋势，必须输出 `insufficient_history`。长期窗口同时展示价格状态、股东总回报、估值倍数变化和相对基准；技术面可以降低入场状态，不能提高长期准入。
9. 用户要求深度研究、单股投资决策、四视角分析或重大仓位变化时，使用两阶段 four-agent 研究委员会。支持 subagents 时按 `deep-research-mode.md` 并行执行阶段内角色；负责人先裁定阶段 L，再允许阶段 N，两轮质询后独立裁决。
10. 抓取、筛选、估值复算、收益率、ATR 和技术指标使用确定性脚本；不要依赖 LLM 心算。LLM 负责提出假设、解释传导、比较证据和暴露未知。
11. 下载数据写入 `data/investment_research.sqlite`。高频基础数据使用结构化表，异构研究数据使用 `tushare_research_observation`，接口能力使用 `tushare_capability`；CSV/XLSX 只作为输入增强或最终导出。
12. 所有数据受 `as_of` 约束，并记录来源、报告期、发布时间、获取时间、单位、币种和新鲜度。来源差异超过 1% 时备注，超过 5% 时先核查原始披露。
13. 深度报告和最终投资结论中的财务数字必须用巨潮资讯、交易所或公司 IR 原始报告交叉核对；TuShare 是标准化二级来源，不是唯一记录来源。
14. 宏观、政策、战争/冲突、利率、汇率、大宗商品或监管可能改变结论时，最终输出前进行当前网络刷新。优先官方来源并独立核对；无法联网时明确缺口并降低置信度。
15. 分开记录 `research_status`、`long_term_status`、`entry_action` 和 `portfolio_action`。公司质量、研究完成度、当前价格和组合位置不得合并为一个总分。
16. 来源冲突时列出矛盾。写回 Wiki 使用 `contradiction` 约定；写入敏感持仓、资金或偏好前先获得用户确认，除非本轮已明确授权。
17. 每个决策固化 `decision_id`、上一决策、变化原因、是否方法重置、`as_of`、价格区间、证伪条件、价格状态、机会成本和验证日期。无新财报、重大事件、到期复核或约 15% 价格/估值变化时，旧候选只进入沿用区，不重复占用深研名额。按 `research-evaluation.md` 评估 20/60/120 日结果。

## 脚本

随附脚本位于 `scripts/`：

- `scripts/market_data_store.py`：创建并查询本地 SQLite 市场数据数据库。
- `scripts/tushare_sync.py`：使用 `TUSHARE_TOKEN` 同步 A 股日线、成交量、复权和可选基础数据。
- `scripts/tushare_research.py`：探测能力，使用 `staged-plan` 生成长期优先计划，按 profile 采集候选证据并查询缓存。
- `scripts/research_workflow.py`：执行迁移、历史决策快照导入、长期优先计划、研究运行、假设/证据、阶段 L/N 裁定、四桶报告和 20/60/120 日评估。
- `scripts/research_store.py`：迁移并审计研究数据库中的 assessment、claim 和 outcome 记录。
- `scripts/news_intake.py`：按需抓取或导入事件信号，去重后映射到版本化假设与具体 assumption。
- `scripts/fundamental_pool.py`：默认长期基本面研究池；数据覆盖不再充当经营耐久分，按新发现、核心更新和 challenger 分配研究名额。
- `scripts/technical_screen.py`：仅对阶段 L 候选计算短期反追高和 3 年价格状态、股东总回报、估值压缩与机会成本。
- `scripts/factor_screen.py`：仅用于用户明确要求的多因子/技术量化基线，带硬门槛、抗追高和集中度控制。
- `scripts/financial_check.py`：机械复算市值和估值倍数。
- `scripts/wiki_index.py`：检查本地 Wiki 坏链、frontmatter 和来源字段。

顶层 `scripts/` 也有轻量封装，便于本地测试和复用。

## 输出与记忆

具体格式使用 `references/output-templates.md`：

- 快速备忘录明确 `long_term_status`、`entry_action`、`portfolio_action`、置信度、为什么、价格/等待条件、最大风险、证伪条件、时间戳和下一验证日期。
- 深度报告展示长期账本、阶段 N 证据、三情景、三类追高、两轮质询、保留分歧、组合影响和数据附录。
- `discovery` 候选保留在研究队列；只有 `decision_ready` 对象进入 `staged_buy`、`wait_price`、`wait_evidence` 和 `avoid`。
- 决策报告首页先给今天最优行动、现金比较、最接近买入对象、唯一阻断项及与上次结论的变化。

使用 `references/wiki-memory.md` 和 `docs/investment-llm-wiki/`：分析前召回相关 profile、portfolio、entity、thesis 和 decision；分析后追加日志、更新状态、保留矛盾并保持原始来源不可变。

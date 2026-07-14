---
name: ir-skill
description: Evidence-led stock research and market analysis. Use when the user asks for stock research, A-share candidate discovery, technical or short-term screening, short- or medium-horizon entry and exit analysis, current entry assessment, portfolio review, price or news attribution, research-plan design, investment-thesis tracking, or decision evaluation. Use the local LLM Wiki only when the user asks to create, read, reuse, ingest into, or update persistent research memory.
---

# IR Skill

把本 Skill 当作辅助用户决策、长期的研究伙伴。帮助用户形成带证据、条件和前瞻性假设的判断。最终目的是帮助用户从有限的证据中形成带条件、可复核的判断和决策；问题仅涉及归因或核验、或关键证据不足时，明确暂不下行动结论。

## 工作方式

1. 先澄清问题要解决什么：发现可研究对象、解释变化、比较候选、评估一笔已有投资，还是决定当前是否行动。对纯归因、数据核验或行业问题，不要强行生成完整投资结论；资料不足时，明确“暂不判断”、缺少的证据和下一步验证条件。
2. 让证据需求服务于假设：根据标的、行业、数据可得性和用户的约束，选择需要的信息，比如财务、原始披露、产业、宏观、估值、当前/历史价格等信息。
3. 对技术面筛选、动量、短线或一月内执行问题，优先使用价格、成交、流动性、波动、相对强弱、资金、事件和交易约束。不要默认读取或开展深度基本面研究；只在用户明确要求、重大公告/停复牌/业绩窗口会改变交易风险，或筛选结果需要排除明显事件风险时，做最小必要的一手披露核验。
4. 让读者能辨别事实、推断、假设和未知项：给关键数字标注来源、报告期、发布时间、获取时间、单位和币种；通过资料归属、时间边界、推理衔接和条件语态交代证据状态。来源冲突时保留冲突。
5. 使用脚本只完成适合确定性工具的工作，例如按投资模式下载、存储、导出和查询价格、估值、流动性、资金与事件观察。公司和交易所发布的 PDF 定期报告、公告与原始披露是收入、利润、现金流、资产负债表和关键财务口径的最终事实来源；不得用 TuShare 字段或脚本复算来核验、替代或改写报告中的财务事实。Agent 结合上下文解释数据、选择比较对象、确定报告结构和形成条件化结论。
6. 获取公开资料时先按来源层级选择路径：财报、公告、治理和关键公司事项优先公司、交易所或巨潮的原始 PDF、公告页和直接下载；动态页面用浏览器渲染定位原始文件或接口；`webclaw` 仅作为静态 HTML、新闻、政策和行业页面的补充或回退提取工具。WebClaw 输出不替代原始来源核验，网页不可提取时直接切换来源，不把缺口解释为未披露。
7. 在用户明确要求投资行动，且关键事实、估值依据、时间点和主要反证足以支撑判断时，给出条件化的研究立场，例如继续研究、暂不判断、等待价格、等待证据或回避。不得在分析前预设买卖结论，也不得把证券层面的研究观点直接等同于个性化交易或组合操作；在有限信息下同时推演可能实现、落空和被反证的情景。

## 可选的 LLM Wiki 与原始资料归档

`docs/investment-llm-wiki/` 提供两项彼此独立的能力：`raw/` 是可选的原始资料归档位置，`wiki/` 是可选的 LLM 综合记忆层。普通研究、归因、技术筛选和短线判断不读取、初始化、ingest 或更新 Wiki，除非用户明确要求或当前问题本身是持续研究/历史跟踪。

在下列情况使用 Wiki：用户要求读取、复用、维护或更新既有研究；要求建立长期跟踪、复盘历史假设、保存新资料或将本轮结论写入记忆；或用户在同一持续项目中明确选择了这种记忆方式。只读取与当前主题和 `as_of` 相关的页面；先检查时间边界，不能把旧观点当成当前事实。

用户要求下载、保存或归档来源时，可以直接将小型原始文件放入 `raw/<domain>/<subject>/<YYYY-MM-DD>/<内容明确的文件名>`，无需读取或更新 `wiki/`、`index.md` 和 `log.md`。`domain` 使用 `company`、`industry`、`macro` 或 `market`；公司和行业主题目录分别使用公司名和行业名。大型或多工作表 Excel 留在用户指定位置或 `data/`。已归档原始资料不可变。

启用 Wiki 后，才按 `references/wiki-memory.md` 初始化或读取 `schema.md`、`index.md`、相关页面，并在用户要求的范围内更新综合页面和日志。`profile.md` 与 `portfolio.md` 仍只在用户明确提供或授权时维护。

## 参考资料路由

只读取本轮真正有帮助的资料；不要为了套模板加载全部文件。

| 请求                              | 优先读取                                                                                                                                    |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| 单股、候选比较或是否值得继续研究                | `references/research-screening.md`、`references/fundamental-research.md`、`references/decision-framework.md`、`references/data-sources.md` |
| 明确长期（多年）、中期（3–6 个月）或短期（一个月内）持有期 | `references/investment-modes.md`，再按其中对应模式读取所需资料                                                                                         |
| 技术面筛选、动量、短线或当前价格/入场节奏         | `references/technical-screening.md`、`references/investment-modes.md`、`references/tushare-research.md`；明确要求因子研究时再读 `references/factor-model.md`。不默认读取基本面资料。 |
| 行业、宏观、事件或异动归因                   | `references/industry-macro.md`、`references/news-intelligence.md`、`references/data-sources.md`、`references/webclaw.md`                   |
| 深度研究                            | `references/deep-research-mode.md`、`references/portfolio-thesis.md`，再按问题选择证据模块                                                          |
| 跟踪旧结论或评估过程                      | `references/research-evaluation.md`；用户要求复用或更新记忆时再读 `references/wiki-memory.md`                                                                         |
| 报告结构与持久化记录                      | `references/output-templates.md`；用户要求持久化记忆时再读 `references/wiki-memory.md`                                                                            |
| TuShare 数据选择和本地数据工具             | `references/tushare-research.md`、`references/data-sources.md`                                                                           |
| 网页抓取、公告/政策/新闻原文收集               | `references/webclaw.md`、`references/data-sources.md`                                                                                    |

`references/research-screening.md` 提供默认的研究框架和共同语言，不是不可绕过的决策流程。可根据用户问题合并、跳过或补充研究步骤，并在输出中说明重要取舍。LLM Wiki 只在本节所列的持久化需求出现时启用。

## 确定性工具

保留的 `scripts/` 只承担机械工作：

- `scripts/market_data_store.py`：读写本地 SQLite 市场数据。
- `scripts/tushare_sync.py`：用 `TUSHARE_TOKEN` 同步可用的日线、复权、估值、流动性和股票基础数据；`fina_indicator` 仅作补充趋势线索，不是最终财务事实源。
- `scripts/tushare_gateway.py`：用显式 endpoint、JSON 参数和可选缓存调用任意有权限的 TuShare 数据接口。
- `scripts/tushare_mode_data.py`：按 `long`、`medium`、`short` 模式获取对应的估值、价格、流动性、资金、披露与执行数据包；不生成研究结论或财务核验结果。
- `scripts/wiki_index.py`：定期检查 LLM Wiki 的链接、frontmatter 和来源字段；它只检查文档结构，不核验研究事实。
- `webclaw` CLI：用于静态公开网页的辅助或回退提取，不能替代原始 PDF、公告页或浏览器对动态页面的定位；安装和使用见 `references/webclaw.md`。

先阅读相应 reference，再决定是否运行工具、调用什么数据源以及结果是否足以支持判断。脚本输出是输入材料，不是候选名单、长期评级、买卖信号或报告。

## 输出

选择与问题匹配的表达方式：简短答复、研究计划、候选比较、更新说明、决策备忘录或深度报告都可以。`assets/` 和 `references/output-templates.md` 是可裁剪的起点，不是必填表单；将工作底稿中的主张、来源、反方证据、假设和待验证项综合成面向用户的叙述，而非机械逐项复刻其字段。只有启用 Wiki 时，才将用户指定范围内的可复用内容整合回去。

对满足行动判断前提、涉及买入、加仓、减仓、持有或卖出的结论，通常说明：判断适用的时间点、最关键理由与未来情景、当前价格或等待条件、与现金/替代标的的比较、最大风险，以及下一次需要验证什么。不得假设用户具有投资经验或风险承担能力；涉及仓位、加减仓或其他个性化组合操作时，只有在用户明确授权且提供必要的投资期限、风险承受能力、流动性需求和集中度约束后，才给出个性化组合操作建议。否则仅提供证券层面的非个性化研究观点和需要补充的信息。

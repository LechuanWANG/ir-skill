# 投资模式路由

根据用户明确的持有期选择一个主模式。先确认持有期、研究对象、`as_of`、是否需要行动判断和已知约束。持有期未明确时先询问；无法澄清时按长期优先模式，并在输出中说明该假设。用户改变持有期时，重新选择模式，不把另一模式的结论直接迁移。

只读取本轮直接回答问题所需的资料。涉及行动性判断时，继续遵守主 Skill 的证据、反证、用户授权和条件化结论要求。跟踪旧结论时追加读取 `references/research-evaluation.md`；需要特定输出结构时读取 `references/output-templates.md`。

## 长期价值投资（多年持有）

以企业长期价值、资本配置和估值安全边际为核心。不要把“巴菲特式”简化为长期持有、低 PE 或忽略估值。

优先读取：

- `references/research-screening.md`
- `references/fundamental-research.md`
- `references/decision-framework.md`
- `references/data-sources.md`
- `deep-research-mode.md`

按问题追加读取：

- 行业结构、政策或周期改变长期假设时，读取 `references/industry-macro.md`。
- 重大公告、治理事件或新的反证出现时，读取 `references/news-intelligence.md`。
- 用户要求入场节奏时，读取 `references/technical-screening.md`；技术面只影响节奏，不替代企业价值判断。
- 用户提供持仓并授权组合讨论时，读取 `references/portfolio-thesis.md`。

重点检查：

- 说明公司如何创造现金流、护城河如何持续、增长需要多少资本，以及管理层如何配置资本。
- 用原始披露核验跨周期的收入、利润、现金流、资产负债表、治理和稀释风险。
- 将当前价格拆成隐含的增长、利润率和资本回报预期，并给出最强反证与估值敏感变量。
- 把日常价格波动、单条新闻和短期情绪视为验证线索，不把它们升级为长期逻辑。
- 预先写明长期假设失效、估值明显变化或新财报出现时的复核触发器。

## 中期投资（约 3–6 个月）

以可验证的催化、盈利或估值变化和实现节奏为核心。中期判断同时检查基本面变化和价格是否已反映预期。

优先读取：

- `references/research-screening.md`
- `references/fundamental-research.md`
- `references/technical-screening.md`
- `references/news-intelligence.md`
- `references/industry-macro.md`
- `references/decision-framework.md`
- `references/data-sources.md`

按问题追加读取：

- 用户明确要求量化、因子或动量研究时，读取 `references/factor-model.md`；结果只形成研究线索。
- 用户提供持仓并授权组合讨论时，读取 `references/portfolio-thesis.md`。
- 需要价格、财务或公告的结构化数据时，读取 `references/tushare-research.md`。

重点检查：

- 明确盈利、订单、行业供需、政策、产品、估值修复或资金面催化的传导路径、发生窗口和核验来源。
- 将催化发生、公开披露和市场定价的时间顺序分开，避免把已被价格反映的消息当成新增机会。
- 同时检查基本面兑现、估值变化、价格趋势、成交与流动性；单一图形或单条新闻不能支撑中期判断。
- 写明催化未发生、盈利数据不及预期、行业变量反转或价格条件恶化时的失效条件和复核时间。
- 在财报、政策、行业数据或关键事件公布后更新判断，不让过期催化继续支撑结论。

## 短期投资（一个月内）

以可执行的事件、价格、成交、波动和流动性条件为核心。短期交易不自动说明公司长期价值，也不把新闻热度当作交易依据。

短线、技术面或动量请求以本节和 `references/technical-screening.md` 为主路径；不要默认读取 `references/research-screening.md` 或 `references/fundamental-research.md`，更不要把深度基本面研究作为筛选前提。只有用户明确需要基本面判断，或财报、停复牌、治理、重大公告等一手信息会改变短线事件风险时，才做最小必要核验。

优先读取：

- `references/technical-screening.md`
- `references/news-intelligence.md`
- `references/decision-framework.md`
- `references/data-sources.md`
- `references/tushare-research.md`

按问题追加读取：

- 行业、政策、利率、商品或市场环境主导价格时，读取 `references/industry-macro.md`。
- 财报、治理、停复牌或重大公告可能改变事件风险时，读取 `references/fundamental-research.md`。
- 用户明确要求量化、因子或动量研究时，读取 `references/factor-model.md`；结果不直接生成交易指令。

重点检查：

- 记录实时数据的 `as_of`、复权口径、市场状态、成交量、波动、流动性、基准和相关行业表现。
- 核实事件原文、可得时间和传导路径，区分已证实事实、市场传闻和价格反应。
- 在分析前定义触发条件、失效条件、持有时间边界和退出条件；不要以单一技术指标、单条快讯或亏损后的加码代替计划。
- 在 A 股市场纳入 T+1、涨跌停、停牌、成交限制、交易摩擦和隔夜跳空风险。
- 将短期结论写成条件化的执行观察，不把它延伸为长期评级或个性化仓位建议。
- 对于纯技术筛选，基本面只承担重大事件风险过滤，不扩展为商业质量、长期估值或完整财务研究。

## 时间区间重叠

持有期落在 1–3 个月时，先判断决策由催化兑现还是价格与事件执行主导：前者使用中期模式，后者使用短期模式，并在输出中说明选择原因。

## 对应 TuShare 数据

使用 `scripts/tushare_mode_data.py plan <mode>` 先展示数据计划，再使用 `fetch <mode>` 采集本轮真正需要的数据。脚本默认只拉取核心数据；对权限敏感接口显式加入 `--include-optional`。每次 `fetch` 必须给出 `--end-date`，把研究时点固定下来。

| 主模式 | 核心数据 | 用途 |
| --- | --- | --- |
| 长期 | 历史价格、复权、`daily_basic`、股票基础信息、分红 | 观察估值历史、资本回报、流动性和长期治理风险线索；技术面只影响节奏。 |
| 中期 | 价格、复权、估值/流动性、资金流、业绩预告/快报、披露日历 | 检查催化、预期变化、披露窗口与价格是否已经反映。 |
| 短期 | 价格、复权、估值/流动性、资金流、涨跌停价、涨跌停榜、龙虎榜 | 检查事件后的价格、成交、波动、资金和 A 股执行约束。 |

所有模式都把公司和交易所的 PDF 定期报告、公告与原始披露作为财务事实源。TuShare 只提供结构化市场观察、披露时间线和待进一步阅读的线索；脚本不复算或核验财务报表，也不生成买卖指令。

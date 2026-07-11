# 双阶段投研状态机

本文件是“长期准入 -> 当前买点评估”的唯一状态机真源。其他 reference 负责生成某一类证据，不得自行定义另一套阶段、状态或行动枚举。

## 目录

- 运行模式与研究状态
- 候选发现与轮换
- 阶段 L：长期价值准入
- 阶段 N：当前买点评估
- 行动契约与输出校验

## 核心原则

先回答公司未来 3–5 年是否值得持续研究和持有，再回答今天是否值得买。长期看好不等于当前可以买；近期事件、宏观、行业、估值和技术面只能更新假设、赔率与节奏，不能绕过长期准入。

```text
运行模式：discovery / refresh / decision
-> 用户目标与持有周期
-> 候选来源与 as_of
-> research_status：queued / in_progress / decision_ready / stale
-> 阶段 L：长期价值准入
-> 建立长期投资假设账本
-> 阶段 N：近期事件、宏观、行业、估值与交易条件
-> 防追高与组合约束
-> entry_action + portfolio_action
-> 记录验证日期并进入后续评估
```

不得把公司质量、当前价格和组合适配压缩成一个综合投资分。因子分只能用于缩小研究范围。

## 输入契约

开始研究时至少记录：

```text
request_type
run_mode = discovery / refresh / decision
target_symbols / candidate_source
holding_horizon
as_of
portfolio_context_available
portfolio_constraints
known_evidence
missing_inputs
previous_decision_id / previous_as_of
```

- `as_of` 是本次决策可使用信息的截止时间；不得使用该时点后才披露的数据。
- `candidate_source` 可为质量池、行业链、盈利拐点、估值修复、组合缺口、事件线索或全市场因子基线。
- 事件线索和因子排名只能生成研究对象，不能直接生成行动。
- 若用户仅询问历史价格异动原因，可以执行归因而不建立完整长期账本；一旦问题包含“是否值得买、加仓、持有或卖出”，必须进入本状态机。

## 运行模式与研究状态

| `run_mode` | 适用请求 | 必须产出 |
|---|---|---|
| `discovery` | 筛选、发现、建立研究池 | 多样化研究队列；不得给未完成对象生成 `entry_action` |
| `refresh` | 更新上次结论、观察池复盘 | 新事实、结论差异、到期条件；无实质变化时沿用旧结论 |
| `decision` | 推荐、现在可以买什么、单股是否买 | 对少量对象完成 L/N，并给今天最优行动、现金比较和最接近买入对象 |

`research_status` 与投资状态分开：

```text
queued -> in_progress -> decision_ready
                      -> stale（超过复核期或关键数据过期）
```

- `queued`、`in_progress` 和 `stale` 进入研究队列，不进入四桶。
- 缺 evidence ID、情景、验证日期、研究维度或最小历史窗口属于 `process_gaps`，只影响 `research_status`。
- 只有 `decision_ready` 才允许固化 `long_term_status` 和 `entry_action`。

## 候选发现与研究池

用户只说“筛选股票”“A 股选股”或“推荐标的”时，默认含义是发现值得做长期研究的对象，不是技术面初筛，也不是直接生成买入名单。执行顺序固定为：

```text
限定市场、行业和持有期
-> 基本面研究池（估值、财务质量、增长、资产负债表、历史覆盖）
-> long_term_status = not_evaluated
-> 阶段 L：长期价值准入
-> 只有 passed 才进入阶段 N 的事件、宏观、行业、估值与技术/流动性
```

- 默认用 `scripts/fundamental_pool.py` 建立研究池；它不得读取日线、成交量、动量、均线、回撤、量比或技术形态。
- 研究池的分数只安排研究优先级，不代表长期质量结论、目标收益或 `entry_action`。每个对象保持 `long_term_status = not_evaluated`、`next_step = stage_L`。
- 数据覆盖单独记录为 `history_coverage / data_readiness`。不得把“本地已经补过几年数据”直接当作经营耐久分；耐久分必须来自多年盈利、利润率、现金流与资本回报的实际稳定性，并且只有在候选池历史覆盖足够一致时才参与排序。
- 默认研究名额拆为新发现、核心更新和 challenger。五只名单原则上至少三只是最近 45–60 天未完成研究的新对象；无新财报、重大事件、复核到期或约 15% 价格变化的旧对象只进入沿用区。
- 用户明确要求“多因子”“量化初筛”“动量”或“技术面筛选”时，才可使用 `scripts/factor_screen.py --explicit-quantitative-baseline`。该分支同样只产生研究池，不能绕过阶段 L。
- `scripts/technical_screen.py` 只服务于已知的阶段 L 候选或用户明确提出的单独技术诊断；全市场技术面结果不能成为默认选股入口。

## 阶段 L：长期价值准入

### 证据范围

优先使用至少 3–5 年历史数据、公司原始披露、行业结构证据和资本配置记录。上市时间或业务历史不足时，明确缩短口径及其限制，不用更短历史伪装长期稳定性。

阶段 L 必须回答：

1. 生意与长期需求：客户为什么持续付费，需求是否依赖一次性政策、补贴或单一客户。
2. 增长与再投资：行业容量、渗透率、份额、产品扩张和国际化还能支持多久。
3. 竞争优势：成本、品牌、渠道、技术、牌照、网络效应或客户黏性是否可持续。
4. 财务质量：收入、利润、ROIC/ROE、利润率、经营现金流、杠杆和三张表是否相互印证。
5. 资本配置：研发、扩产、并购、分红、回购、融资和股权稀释记录是否理性。
6. 治理与尾部风险：控制人、关联交易、质押、会计、债务、诉讼和监管风险是否可接受。
7. 长期隐含预期：当前估值隐含怎样的增长、利润率和资本回报，兑现要求是否合理。

### 长期投资假设账本

每只进入阶段 L 的公司使用同一结构：

```text
thesis_id
symbol
as_of
holding_horizon
long_term_thesis
return_sources_3_5y
core_assumptions[]
validation_metrics[]
validation_dates[]
supporting_evidence[]
contrary_evidence[]
management_and_capital_allocation
reasonable_value_range
market_implied_expectations
structural_risks[]
falsification_conditions[]
confidence
missing_evidence[]
next_validation_date
```

每条 `core_assumption` 都应有对应指标、支持证据、反方证据和证伪条件。无法说明影响哪条假设、影响量级和持续时间的信息，只进入资讯记录。

### `long_term_status`

阶段 L 只允许三种状态：

| 值 | 用户可见含义 | 进入下一阶段 |
|---|---|---|
| `passed` | 长期准入通过 | 可以进入阶段 N |
| `needs_evidence` | 证据不足，值得继续研究 | 只能输出 `wait_evidence`；可加载有助于补证的阶段 N 数据 |
| `rejected` | 长期逻辑不成立或存在结构性红线 | 直接输出 `avoid`，不得因催化或技术走势破例 |

判断规则：

- 核心收益来源清楚、关键假设可验证、财务和治理证据基本相互印证，且没有阻断项时，可设为 `passed`；允许保留降低置信度或持续监测的未知项。
- 只有缺口的合理最好/最坏答案可能改变 `passed/rejected`、使基准回报跨过最低回报门槛，或显著改变下行情景时，才列入 `blocking_evidence` 并设为 `needs_evidence`。
- 长期经济性恶化、关键假设已被证伪，或出现不可接受的治理、会计、偿债和重大合规风险时，设为 `rejected`。
- 不允许用高热度事件、短期资金、技术突破或单个综合分提升 `long_term_status`。

未知项按物质性分层：

```text
blocking_evidence：可改变长期状态、回报门槛或重大下行情景
confidence_limiters：不改变当前行动，但降低置信度
monitoring_items：日常跟踪，不阻断结论
process_gaps：研究流程未完成，不生成投资决策
```

## 阶段 N：当前买点评估

阶段 N 仅评估 `passed`，或为补齐明确证据而继续研究的 `needs_evidence` 对象。证据按以下顺序加载：

1. 近期事件：是否真实、映射哪条长期假设、影响量级和持续时间、价格是否已反映。
2. 宏观环境：利率、流动性、汇率、政策和风险溢价如何影响收入、成本、现金流或折现率。
3. 行业景气：供需、产能、库存、价格、订单、竞争反应和公司业务分部敏感性。
4. 估值与赔率：基准、上行和下行情景，合理价值区间、安全边际和隐含预期。
5. 技术、流动性与拥挤：是否能以合理价格建立和退出仓位，是否已经过热。
6. 组合约束：行业、风格、相关性、集中度、流动性、现金和替代成本。

阶段 N 必须保留事实、推断、观点和未知项的区别。宏观、行业和事件结论必须落到长期假设或财务传导，不能只描述市场情绪。

阶段 N 同时检查长期机会成本。至少 500 个前复权交易日才允许声称长期横盘或趋势；不足时写 `insufficient_history`。长期价格状态必须同时展示股东总回报、估值倍数变化、相对市场/行业收益以及盈利或现金流变化，不能把“不追高”等同于“值得买”。

## 防追高门

分别检查三种追高，不合并成一句“风险较高”：

| 类型 | 核心检查 | 默认影响 |
|---|---|---|
| 估值追高 | 自身/同行估值分位、隐含增长、盈利预测是否同步上修 | 赔率不足时 `wait_price` |
| 价格追高 | 20/60 日相对涨幅、ATR/趋势偏离、跳空/涨停、成交与融资拥挤 | 过热时 `wait_price` |
| 叙事追高 | 政策、订单、概念或传闻是否核实，能否形成可测量财务传导 | 未核实时 `wait_evidence` |

相对阈值和波动率调整优先于全市场统一固定阈值。触发过热警示不否定公司，但默认等待；只有盈利能力和长期价值区间同步上移，才提高可接受价格。

## 行动契约

### `entry_action`

当前买点只允许四种状态：

| 值 | 用户可见标签 | 必要条件 |
|---|---|---|
| `staged_buy` | 可分批买入 | `passed`，证据充分，赔率合理，不过热，组合可容纳 |
| `wait_price` | 等价格 | 长期通过，但估值、价格或拥挤度不提供足够赔率 |
| `wait_evidence` | 等证据 | 长期或近期关键证据不足、冲突或尚未核实 |
| `avoid` | 回避 | 长期不通过、存在客观红线，或流动性/下行风险不可接受 |

`staged_buy` 不等于一次性满仓。默认说明试探仓、基本面确认仓和后续增配条件；用户未提供风险预算时，不伪造精确仓位比例。

### `portfolio_action`

已有持仓动作与当前买点分开：

```text
portfolio_action = not_applicable / add / hold / reduce / exit
```

- 新候选通常为 `not_applicable`。
- 已持仓公司可以同时为 `entry_action = wait_price`、`portfolio_action = hold`。
- `portfolio_action` 必须考虑集中度、相关性、流动性、税费/摩擦和替代成本。
- `exit` 通常对应假设破裂、客观红线或显著更高的机会成本；说明触发原因。

### 决策矩阵

| `long_term_status` | 当前证据 | 估值/过热 | 默认 `entry_action` |
|---|---|---|---|
| `passed` | 有利且充分 | 合理、不过热 | `staged_buy` |
| `passed` | 有利且充分 | 过热或赔率不足 | `wait_price` |
| `passed` | 不利、冲突或未核实 | 任意 | `wait_evidence`，客观风险不可接受时 `avoid` |
| `needs_evidence` | 任意 | 任意 | `wait_evidence` |
| `rejected` | 任意催化 | 任意 | `avoid` |

## 决策输出最小字段

```text
decision_id
symbol
as_of
holding_horizon
candidate_source
research_status
long_term_status
thesis_id
long_term_thesis
return_sources_3_5y
supporting_evidence[]
contrary_evidence[]
falsification_conditions[]
recent_event_assessment
macro_assessment
industry_assessment
valuation_assessment
technical_liquidity_assessment
anti_chase_flags[]
acceptable_price_range
base_case
downside_case
upside_case
entry_action
entry_triggers[]
waiting_conditions[]
portfolio_action
portfolio_role
confidence
missing_evidence[]
blocking_evidence[]
confidence_limiters[]
monitoring_items[]
process_gaps[]
price_regime
total_shareholder_return_3y
opportunity_cost_assessment
previous_decision_id
decision_change
change_reasons[]
methodology_change
next_validation_date
sources[]
```

- 情景分析是买点判断的必需推理；快速备忘录可以压缩成文字，深度报告应显式展示三情景。
- 证据不足时不伪造精确目标价或概率，使用区间、条件和缺口。
- 所有关键数字带来源、报告期、发布时间、获取时间、单位和币种。
- 每个正式决策带 `previous_decision_id`、`decision_change`、`change_reasons` 和 `methodology_change`。框架升级造成的状态变化必须标记为方法重置，不得伪装成新事实。
- 决策首页必须给 `best_action_today`、`closest_to_buy`、现金比较、唯一阻断项和研究队列数量。没有可买对象可以是结论，但要说明是赔率、风险、阻断证据还是研究未完成。

## 不可绕过的校验

形成结论前逐项检查：

1. `long_term_status` 已明确且有证据。
2. `rejected` 没有出现 `staged_buy`、`wait_price` 或 `wait_evidence` 之外的例外推荐。
3. 事件均有 `thesis_id`；不能映射的事件未进入结论。
4. 技术面没有提高长期准入状态。
5. 过热时没有因“怕错过”取消估值和流动性检查。
6. `entry_action` 与 `portfolio_action` 没有混成一个标签。
7. 价格区间、等待条件、证伪条件和下一验证日期已写明。
8. `as_of`、数据新鲜度、来源冲突和未知项已保留。
9. `process_gaps` 没有被转换成 `wait_evidence`；未完成对象留在研究队列。
10. 长期价格状态有至少 500 个前复权交易日；否则明确为历史不足。
11. 与上次结论不同的对象已说明新事实或方法变化。

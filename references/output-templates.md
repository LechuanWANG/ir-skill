# 输出模板

阶段、状态和行动枚举以 `research-screening.md` 为唯一真源。本文件只定义如何呈现和保存结果。

## 目录

- 通用字段与快速备忘录
- 深度报告与候选发现
- 最终四桶和研究队列
- 决策差异、评估快照与报告产物

## 通用字段

所有投资决策输出至少包含：

```text
decision_id
symbol
as_of
holding_horizon
candidate_source
research_status = queued / in_progress / decision_ready / stale
long_term_status = passed / needs_evidence / rejected
entry_action = staged_buy / wait_price / wait_evidence / avoid
portfolio_action = not_applicable / add / hold / reduce / exit
confidence = high / medium / low
next_validation_date
blocking_evidence[]
confidence_limiters[]
monitoring_items[]
previous_decision_id
decision_change = new / unchanged / changed / methodology_rebase
change_reasons[]
price_regime
opportunity_cost_assessment
```

关键数字附来源、报告期、发布时间、获取时间、单位和币种；缺失写“不可得”，冲突并列记录。不要把三个状态字段压成一个“操作”。

## 快速备忘录

大致控制在一屏内：

```text
【结论】一句话说明长期判断和当前行动。
【长期准入】passed / needs_evidence / rejected
【研究状态】queued / in_progress / decision_ready / stale
【当前行动】staged_buy / wait_price / wait_evidence / avoid
【持仓行动】not_applicable / add / hold / reduce / exit
【置信度】high / medium / low     【as_of】YYYY-MM-DD

【长期为什么】3–5 年收益来源 + 最关键的一条支持/反方证据。
【当前为什么】事件、宏观、行业、估值与交易条件中主导行动的因素。
【防追高】估值追高 / 价格追高 / 叙事追高：逐项正常、警示或不可得。
【价格或等待条件】可接受区间；若等待，写明重新评估触发器。
【最大风险 / 证伪】哪项事实出现说明判断错误。
【数据缺口】仍缺什么、由什么来源确认。
【缺口分层】阻断项 / 置信度限制项 / 持续监测项；流程缺口不得生成投资行动。
【相对上次】新事实、方法重置、结论变化或“无实质变化”。
【长期价格状态】至少 500 个前复权交易日；股东总回报、估值变化与机会成本。
【下一步】下一验证日期；是否进入深研、Wiki 或 evaluation。
```

## 长期投资假设账本

每只进入阶段 L 的公司创建或更新：

```text
thesis_id:
symbol:
as_of:
holding_horizon:
long_term_thesis:
return_sources_3_5y:

core_assumptions:
  - assumption_id:
    claim:
    validation_metric:
    validation_date:
    supporting_evidence:
    contrary_evidence:
    falsification_condition:

management_and_capital_allocation:
reasonable_value_range:
market_implied_expectations:
structural_risks:
confidence:
missing_evidence:
blocking_evidence:
confidence_limiters:
monitoring_items:
price_regime:
total_shareholder_return_3y:
opportunity_cost_assessment:
previous_decision_id:
decision_change:
change_reasons:
methodology_change:
next_validation_date:
long_term_status:
```

账本保存长期判断，不把每条快讯塞入正文。事件通过 `signal_id` 和 `thesis_id` 关联，只有改变核心假设时才更新账本。

## 投资与买入条件卡

```text
decision_id:
symbol:
as_of:
candidate_source:

long_term_status:
long_term_thesis:
return_sources_3_5y:
three_key_evidence:
largest_structural_risk:
falsification_conditions:

recent_event_assessment:
macro_assessment:
industry_assessment:
valuation_assessment:
technical_liquidity_assessment:

anti_chase:
  valuation_chasing:
  price_chasing:
  narrative_chasing:
  metrics_timestamp:

base_case:
upside_case:
downside_case:
reasonable_value_range:
acceptable_price_range:

entry_action:
entry_triggers:
waiting_conditions:
portfolio_action:
portfolio_role:
confidence:
missing_evidence:
next_validation_date:
```

- `staged_buy`：写试探、基本面确认和增配条件；没有风险预算时不伪造精确比例。
- `wait_price`：写价格、估值、时间消化或盈利上修条件，不只写“等回调”。
- `wait_evidence`：写缺失证据、责任来源和最晚复核日期。
- `avoid`：写结构性否决、客观红线或不可接受交易风险。

## 深度报告

```text
1. PM 裁决
   - run_mode：discovery / refresh / decision
   - 今天最优行动、现金比较、最接近买入对象、唯一阻断项
   - 与上次结论的变化及原因
   - long_term_status
   - entry_action
   - portfolio_action
   - 置信度、as_of、下一验证日期

2. 阶段 L：长期投资假设账本
   - 生意与需求
   - 增长与再投资空间
   - 竞争优势
   - 财务质量
   - 资本配置与治理
   - 长期隐含预期
   - 支持、反方和证伪证据

3. 阶段 N：当前环境与买点
   - 已核实事件及 thesis_id
   - 宏观传导
   - 行业景气与竞争反应
   - 当前估值与三情景
   - 技术、流动性和拥挤

4. 防追高
   - 估值追高
   - 价格追高
   - 叙事追高
   - 相对分位、ATR/趋势偏离、成交拥挤和时间戳
   - 3 年价格状态、股东总回报、估值压缩和机会成本

5. 两轮质询
   - Round 1：每个角色点名最薄弱 claim
   - Round 2：证据回应、主张收窄或置信度下调
   - 保留分歧与未解决问题

6. 投资与买入条件卡
   - 可接受价格区间
   - 分批/等待条件
   - 最大风险与证伪
   - 组合角色和替代成本

7. 数据附录
   - 关键数字、双源核对、口径、发布时间和获取时间

8. 写回计划
   - Wiki 页面
   - decision snapshot
   - 20/60/120 evaluation 日期
```

## Claim Ledger

深度模式使用：

```text
claim_id | stage | time_horizon | thesis_id | claim
supporting_evidence | contrary_evidence | source_dates
author | challenger | challenge | response
initial_confidence | final_confidence
status | unresolved_questions | action_implication
```

不要按角色置信度求平均。PM 说明采纳、拒绝或收窄哪些主张。

## 研究数据计划

先输出：

```text
用户目标 / 持有周期 / as_of：
候选来源：质量池 / 行业链 / 盈利拐点 / 估值修复 / 组合缺口 / 事件线索 / 全市场基线
stage：L / N
thesis_id / 初始投资假设：
研究 profile：
必需数据集 / 可选数据集：
required_for_gate：
能力状态：available / empty / unverified / denied / error
数据窗口 / 缓存 / freshness_status：
缺失证据 / 替代来源 / 官方核验要求：
技术面的角色：流动性 / 拥挤 / 风险 / 入场节奏
下一动作 / 允许的状态转换：
```

阶段 L 默认 `long-term-quality + risk-review`。阶段 N 按需追加事件、行业和宏观，`timing-liquidity` 最后。

## 候选发现输出

普通“筛选股票”先使用长期基本面研究池：

```text
候选池摘要：
- 数据范围与 as_of：
- candidate_source = long_term_fundamental_pool
- 基本面覆盖：估值 / 财务质量 / 增长 / 资产负债表 / 年报历史
- filter_log：每个底线门槛的进入、剩余和淘汰数量

研究池：
代码 | 名称 | 行业 | candidate_source | value_signal | quality_signal | growth_signal | durability_signal | durability_applied | history_coverage | data_readiness | selection_sleeve | last_decision_as_of | material_update_reason | research_gaps | research_status=queued | long_term_status=not_evaluated | next_step=stage_L
```

`research_priority_score` 只安排阶段 L 的研究顺序，不能当作长期结论、投资排名或买入信号。历史覆盖不能直接增加吸引力；新发现、核心更新和 challenger 分配独立研究名额。

只有用户明确要求多因子/技术量化基线时，才附加：

```text
候选池摘要：
- 数据范围与 as_of：
- 风格预设：
- 自定义规则及预注册时间：
- 与默认基线的差异：
- filter_log：每个硬门槛的进入、剩余和淘汰数量
- 因子与惩罚：trend/value/quality/growth + overheat/valuation/risk
- research_priority_overlay：来源、验证状态和时间

研究池：
代码 | 名称 | 行业 | candidate_source | 投资假设 | 研究 profile | trend_score | value_score | quality_score | growth_score | composite_score | research_priority_overlay | 追涨风险 | disqualify_risk | long_term_status=not_evaluated | next_step=stage_L
```

`composite_score` 只用于显式量化研究池。催化 overlay 不改写它，最终报告不沿用因子排名作为投资排名。

## 最终四桶名单

只有 `research_status=decision_ready` 的对象进入四桶。`queued / in_progress / stale` 单列为研究队列，不得用 `wait_evidence` 填充：

| 桶 | 必需字段 |
|---|---|
| `staged_buy` | 长期假设、价格区间、分批触发器、三类追高、最大下行 |
| `wait_price` | 长期假设、当前过热/赔率、重新评估价格或时间条件 |
| `wait_evidence` | 缺失证据、获取来源、复核日期 |
| `avoid` | 长期否决或客观风险、是否影响已有持仓 |

每只股票必须显示 `long_term_status` 和 `portfolio_action`。没有对象的桶也保留并写“无”，避免只报告正面结果。

四桶横向表统一带出可接受价格、最大下行情景、流动性/退出能力和组合集中度影响，不能只给行动标签。

报告首页统一输出：

```text
今天最优行动：可分批买入 / 等待与现金优先 / 回避与现金优先 / 研究未完成
已完成决策数量 / 研究队列数量
最接近买入对象 / 当前唯一阻断项 / 下一验证日
与上次比较：新增 / 沿用 / 升级 / 降级 / 方法重置
```

## 决策评估快照

按 `research-evaluation.md` 固化：

```text
decision_id | symbol | decision_as_of | reference_price
long_term_status | entry_action | portfolio_action
acceptable_price_range | overheat_flags | missing_evidence
thesis_id | falsification_conditions | next_validation_date
market_benchmark | industry_benchmark
evaluation_dates = 20d / 60d / 120d
```

## 结果生成与审计入口

- `scripts/research_workflow.py` 是决策输出入口；使用 `report --format md` 或 `report --format json` 从持久化决策生成完整四桶名单，空桶也必须保留。
- `scripts/research_store.py` 是存储审计入口；使用 `assessments`、`claims`、`outcomes` 和 `outcome-summary` 核对阶段裁定、质询记录，并横向比较四类行动的 20/60/120 日结果。
- `scripts/news_intake.py` 是事件信号入口；使用 `parse` 预览、`ingest` 持久化、`query` 联合检查信号卡及其假设映射；`list` 和 `mappings` 保留为单表查询。未验证信号不得直接写成最终证据。

```bash
python3 scripts/research_workflow.py report --format md --output outputs/reports/decision_buckets.md
python3 scripts/research_store.py assessments
python3 scripts/research_store.py outcome-summary
python3 scripts/news_intake.py query --important-only
```

## 报告产物

```text
outputs/reports/{report_slug}_{YYYYMMDD}/
├── data/      原始抓取、派生表、source_summary.json、decision snapshot
├── tex/       LaTeX 源文件
├── build/     仅放编译临时文件
├── pdf/       仅放最终面向用户的 PDF
└── rendered/  用于视觉 QA 的渲染 PNG 页面
```

- 最终 PDF 只放 `pdf/`；编译副本验证后移除。
- TeX、数据、渲染图和临时文件分目录。
- 精确原始数据留在 `data/`；报告正文不打印很长本地路径。

## LaTeX / PDF QA

交付前：

- 转义 `%`, `_`, `&`, `#`, `$`。
- 中文报告使用 XeLaTeX。
- 宽表使用横向页面、更小字号或更窄列。
- 编译并修复致命错误和明显版式警告。
- 渲染 PDF，至少检查封面、宽表、公司详情和最后一页，确认无裁切、重叠、不可读字形和错位页眉/页脚。

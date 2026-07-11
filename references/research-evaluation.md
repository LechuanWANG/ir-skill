# 投研决策评估

本文件定义 20/60/120 个交易日后的复盘协议。评估所有四类 `entry_action`，不只评估推荐买入，避免幸存者偏差和“涨了就是对”的单一评价。

## 评估目标

分开评估两件事：

1. **长期研究质量**：核心假设、收益来源和证伪条件是否被后续事实支持。
2. **当前行动质量**：当时给出的买入、等价格、等证据或回避是否改善赔率并控制追高与回撤。

20/60/120 日价格结果不能证明 3–5 年假设正确或错误；它们只提供买点、拥挤和短期风险控制反馈。

## 必须纳入的决策

记录并评估：

- `staged_buy`
- `wait_price`
- `wait_evidence`
- `avoid`

不得只保存后来表现好的候选。最终名单、观察池和否决池均使用同一 `decision_id` 进入评估。

## 决策快照契约

决策当日固化以下字段，后续不得回写覆盖原始判断：

```text
decision_id
symbol
decision_as_of
evaluation_baseline_date
holding_horizon
candidate_source
long_term_status
entry_action
portfolio_action
reference_price
acceptable_price_range
base_case
downside_case
upside_case
thesis_id
core_assumptions[]
falsification_conditions[]
overheat_flags[]
missing_evidence[]
next_validation_date
market_benchmark
industry_benchmark
source_snapshot[]
```

## 20/60/120 日检查

每个窗口使用可交易日对齐，记录：

```text
evaluation_window = 20d / 60d / 120d
evaluation_date
absolute_return
market_relative_return
industry_relative_return
max_adverse_excursion
max_favorable_excursion
realized_volatility
liquidity_change
valuation_change
earnings_estimate_revision
waiting_condition_status
first_acceptable_price_date
first_acceptable_price
catalyst_status = pending / realized / delayed / rejected / not_applicable
falsification_status = intact / weakened / triggered / unknown
thesis_status = strengthened / unchanged / weakened / broken / too_early
entry_action_review
review_notes
data_sources[]
```

- 收益使用复权价格，记录币种和基准。
- 最大不利/有利波动从决策后第一个可交易价格开始计算。
- 对 `wait_price` 同时记录决策日起表现和首次触发可接受区间后的表现，避免用事后最优买点评价。
- 盈利预期变化必须说明来源和可比口径；不可得时写 `unknown`。
- 催化兑现不等于长期假设成立，价格上涨也不等于事件量级合理。

## 分行动评估

### `staged_buy`

检查：

- 是否在可接受价格区间内开始建仓。
- 分批条件是否被遵守，还是在事件高点追入。
- 最大不利波动是否超出下行情景。
- 盈利或长期价值区间是否如预期上移。

### `wait_price`

检查：

- 后续是否进入可接受价格区间。
- 等待是否避开明显回撤、估值压缩或拥挤消化。
- 若持续上涨，长期价值是否同步上修，还是仅形成错失机会。
- 原等待条件是否过严、模糊或无法执行。

### `wait_evidence`

检查：

- 缺失证据是否按期取得。
- 新证据是否支持、削弱或证伪长期假设。
- 等待期间是否避免了基于传闻或不完整数据的错误行动。
- 下一验证日期和证据责任是否清楚。

### `avoid`

检查：

- 回避原因是结构性质量、治理红线、流动性还是赔率问题。
- 后续事实是否确认红线或显示原判断过度保守。
- 即使股价上涨，也先检查被否决风险是否真的消失，不能只按收益翻案。

## 评估标签

不要只用“正确/错误”。使用：

```text
research_quality = strong / adequate / weak / unrateable
timing_quality = strong / adequate / weak / unrateable
risk_control_quality = strong / adequate / weak / unrateable
process_adherence = passed / deviated / unverified
```

`unrateable` 用于数据不可得、时间不足或事件不可比；不要用弱证据强行评分。

## 防止后见之明

1. 评估只使用决策快照中记录的假设、价格区间和证伪条件。
2. 新信息按实际发布时间进入复盘，不回写成“当时已经知道”。
3. 区分过程质量与结果运气；好过程可能短期亏损，坏过程也可能短期上涨。
4. 同时比较买入与等待建议，避免系统因追逐上涨样本而逐步放松防追高纪律。
5. 修改阈值或规则前，说明样本量、市场环境和预期改善，不因单个案例过拟合。

## 复盘输出

每次评估输出：

```text
原决策摘要
窗口表现与基准比较
长期假设变化
催化与证伪进度
买点和风险控制评价
当时流程是否合规
应保留的规则
需要调整的规则及证据
下一验证日期
Wiki / evaluation store 写回计划
```

## 运行入口

`outcome-record` 写入某个窗口的价格、基准、最大有利/不利波动、盈利修订、等待条件、假设状态和四项质量标签；`outcomes-summary` 按四类 `entry_action` 与 20/60/120 日窗口汇总，不能只查看 `staged_buy`：

```bash
python3 scripts/research_workflow.py outcome-record \
  --decision-id <decision_id> \
  --horizon-days 20 \
  --target-date 2026-08-07 \
  --actual-date 2026-08-07 \
  --price-return 0.03 \
  --benchmark-return 0.01 \
  --max-adverse-excursion -0.04 \
  --research-quality strong \
  --timing-quality adequate \
  --risk-control-quality strong \
  --process-adherence passed \
  --data-source https://example.com/source

python3 scripts/research_workflow.py outcomes-summary
python3 scripts/research_store.py outcome-summary
```

首次创建决策时会生成近似工作日目标日期；在正式评估前使用 `outcomes-reschedule --trade-cal-file <trade_cal>` 替换成交易所实际开市日。

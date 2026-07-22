---
name: ir-short-term-trading
description: Evidence-led short-term trading research for one-month events, technical analysis, momentum, factor screens, entries, price dislocations, and price-led 1-3 month decisions.
---

# 短期事件与交易研究

用于约 5–20 个交易日的 `trade` 和约 20–60 个交易日的 `swing`。先读取 [`../shared/research-discipline.md`](../shared/research-discipline.md)；不评价长期价值。

## 按需读取

- 数据与补全：[`../../references/tushare-data.md`](../../references/tushare-data.md)。
- 公告、政策或事件核验：[`../shared/external-evidence-sources.md`](../shared/external-evidence-sources.md)。
- 仓位、止损和执行：[`../shared/trading-risk-discipline.md`](../shared/trading-risk-discipline.md)。
- 结论依赖 3–6 个月财务兑现：同时使用 [`../ir-medium-term-catalyst/SKILL.md`](../ir-medium-term-catalyst/SKILL.md)。

## 1. 全市场筛选

全市场找机会时先运行本地、时点一致的筛选：

```bash
python3 scripts/short_term_screen.py screen --as-of 20260719 --profile trade --benchmark 000300.SH
```

- 先看 `screen_status`、排除原因、数据缺口和现金比较；`no_edge_found` 时不得补足名单。
- `screen` 只负责时点一致的候选发现；`evidence_ready` 仅表示机械筛选通过，不表示事件、预期差、定价或交易计划已经确认。
- 推荐结果不会在本轮自动复盘，也不会读取历史推荐或用户执行记录。
- 排名只在可投资股票池内使用综合可买性得分；相对强弱只占其中一部分，趋势、参与度、流动性和扣除追高风险后的价格质量保持独立，不重复计算同源指标。
- 先看行业 `classification_source`；仅 `signal=significant` 才限定行业，快照分类不得用于历史归因。
- 用户已给标的时可跳过全市场排名，但仍执行个股确认。
- `screen` 回答“选什么”，不回答“何时买”；候选必须再映射到一个冻结的技术形态，禁止把排名直接当作入场信号。

候选统一分为三类：

- `A类：可执行候选`：机械筛选和追高风险门槛通过，可进入执行检查，但仍须等待原始价格触发、账户约束和可成交性确认。
- `B类：研究合格但等待价格`：研究方向保留，但价格偏离、成交确认、波动或市场环境仍需改善，不追价。
- `C类：强势观察对象`：相对强势仍在，但追高风险或其他硬门槛过高，只观察，不进入买入计划。

计算追高风险时至少使用个股自身 120 日延伸分位、横截面延伸分位、ATR 标准化价格偏离、5 日相对 20 日收益加速度、开盘跳空、最近三日连续上涨、20 日价格位置和成交量异常。先执行硬门槛，再按相对强弱、趋势、成交、价格质量和流动性计算综合可买性；高涨幅不得通过其他分数抵消过度延伸或不可成交风险。

## 2. 技术形态与个股确认

只使用与策略合同匹配、能够历史重放的技术形态：

- `momentum_breakout`：相对强势、趋势支持、不过度延伸，并由下一交易日价格与参与度确认突破。
- `trend_pullback`：趋势支持、回撤仍在结构内，并由下一交易日重新转强确认；不得把下跌本身当作低吸理由。
- `event_continuation`：已核验事件、正向预期差和价格延续共同成立；没有时点一致的事件证据时不得使用。

MACD、RSI、布林带和均线是描述性状态，不是独立买卖信号。每个技术形态必须写明行为或资金假设、相对强弱、趋势结构、成交参与、延伸程度、可观察触发、价格失效、有效期和反证；任一关键项为 `unknown` 时不得输出 `优先行动`。

内部计算与兼容数据可以保留技术形态代码，但用户报告不得出现 `setup`、`setup_type`、`momentum_breakout`、`trend_pullback`、`event_continuation` 等原始字段或代码。报告统一使用“技术形态”以及“动量突破 / 趋势回踩 / 事件延续”等中文名称，并通过 `report` 或 `recommendation.report_card` 输出。

对最终候选运行指标并读取相对基准、价格结构和数据覆盖：

```bash
python3 scripts/tushare_mode_data.py indicators --symbol 000001.SZ --benchmark 000300.SH --end-date 20260719
```

核验事件的预期差、事件前涨幅、可交易时间、剩余驱动和反向情景；`known_event_count` 只是线索。过度延伸、赔率不足、成交未确认或关键数据缺失时移出名单或等待。指标输出会写入 `evidence.technical_snapshot.indicator_snapshot`，`confirm` 不得脱离该时点证据另编技术叙事。

技术计算使用前复权价；报告中的触发、失效和委托价格必须使用当时未复权原始价。`execution_reference_available=false` 时可以继续研究，但 `execution_ready` 必须保持 `false`。

完整的结构化闭环分为三个显式阶段：

```bash
# 1) 先保存筛选证据（仅在需要跨命令继续时）
python3 scripts/short_term_screen.py screen --as-of 20260719 --profile trade --save-run

# 2) 为单个候选生成证据包；不会形成推荐
python3 scripts/short_term_screen.py evidence \
  --screen-run-id <screen-run-id> --symbol 000001.SZ \
  --strategy-contract event_trade --save-run

# 3) 用户或 Agent 提交结构化判断后，确认并写入推荐集合
python3 scripts/short_term_screen.py confirm \
  --evidence-run-id <evidence-run-id> --assessment assessment.json \
  --project-dir <项目目录>
```

`confirm` 的输出是研究推荐，不是订单、持仓或用户已执行事实。非现金推荐会进入项目的 `data/research-library/tracking/research-watchlist.json`，同时在 SQLite 留下一条 `short_confirmation` 记录；这两个动作都不会创建复盘任务。

如果只想保存完整的当时判断，再显式加 `--save-decision`；不加时只保存推荐索引和行动条件。用户没有要求保存时，证据和判断可以只在本次输出中存在。

## 3. 验证与执行

先审计数据是否可执行；`blocked_for_execution` 时只能研究，不能下单：

```bash
python3 scripts/short_term_screen.py quality --as-of 20260719 --profile trade --benchmark 000300.SH
```

修改筛选阈值或将其作为稳定策略前，运行历史回放并保留样本外区间：

```bash
python3 scripts/short_term_screen.py backtest --start-date 20240101 --end-date 20260719 --out-of-sample-start 20260101 --profile trade --save-run
```

先看 `inference.status`：`exploratory`、样本缺失或远期结果未成熟时不得宣称策略有效，也不得在同一留出区间继续调参。回放先产生候选，再重放技术形态触发、未触发、价格失效和时间退出；`trigger_replay.no_trade_is_counted` 必须为真，并分别报告 A/B/C 三类的入选数、触发数、未触发数和成本后表现。日线回放只能把开盘跳空按开盘价处理，把盘中穿越视作预先挂出的触发单，并在 `trigger_replay.execution_assumption` 公开该假设；没有分钟或逐笔数据时不得宣称真实成交。事件、预期差和 Agent 判断没有历史时点证据时不伪造重放。

除均值、胜率和 MAE/MFE 外，检查成本后期望、平均盈亏、赔率、利润因子、5% 尾部收益、最大连续亏损和均值区间；按开发/样本外、候选等级、市场环境、流动性和波动分层。逐层比较“相对强弱基线 → 趋势 → 技术形态触发 → 参与度 → 反追高约束”，没有稳定增量贡献的指标不进入合同。

`优先行动` 还要求 `readiness.personal_investor_controls=pass`：至少记录决策频率、最大持仓数、单笔风险预算、组合 heat 上限、单日新增交易上限、隔夜跳空缓冲和最低流动性倍数；选择现金不要求这些参数。用户提供账户、风险预算、原始入场价、原始失效价和上限后，才运行 `short_term_screen.py risk`。需要时同时提供当前组合热度及上限、持仓数及上限、20 日中位成交额和单笔成交额占比上限；任何组合或流动性硬约束触发时仓位为零。`plan_ready=true` 只表示风险参数形成了合格计划，`execution_ready` 仍为 `false`，直到账户、实时原始价和委托可成交性在执行层另行核验。最终使用 `recommendation.report_card` 输出行动标签、候选等级、技术形态、行为假设、主导驱动、技术确认、已定价程度、原始价触发/失效、赔率、追高风险、最长持有期、仓位状态和复核时间；没有 A 类候选时不得为了填满名单强行行动。

## 4. 推荐集合与可选复盘

查看已保存的推荐只读取索引，不复用旧论点，也不触发复盘：

```bash
python3 scripts/short_term_screen.py recommendations --project-dir <项目目录>
```

只有用户明确要求复盘时才运行：

```bash
python3 scripts/short_term_screen.py review \
  --recommendation-run-id <recommendation-run-id> \
  --review-as-of 20260819 \
  --assessment review.json \
  --save-run
```

复盘分为研究结果和执行结果：没有用户提供真实交易信息时，`execution_status=not_observed`，只计算事件结果、触发/失效、标的远期收益、基准超额收益、MAE/MFE；这些是研究路径结果，不是账户收益。未调用 `review` 时，`review_status` 不会被系统自动生成。

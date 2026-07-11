# 决策框架

买入、持有、卖出、仓位和投资假设决策使用本参考资料。阶段、状态和行动枚举以 `research-screening.md` 为唯一真源。

## 必需逻辑链

按以下顺序评估：

1. **长期公司准入**：3–5 年生意、增长、竞争、财务、资本配置、治理和隐含预期。
2. **近期事件**：新事实影响哪条长期假设，量级、持续性和定价程度如何。
3. **宏观与行业**：当前周期和政策如何传导到收入、成本、现金流、折现率和竞争反应。
4. **估值与交易条件**：三情景赔率、可接受价格、技术过热、流动性和拥挤。
5. **组合**：现有敞口、集中度、相关性、机会成本、现金和退出能力。

行业长期结构可以作为阶段 L 的公司证据；近期宏观、行业景气和价格行为属于阶段 N。不要先被短期叙事锚定，再倒推公司长期逻辑。

## 三轴决策

不要用一个“操作”字段混合不同问题：

| 字段 | 允许值 | 回答的问题 |
|---|---|---|
| `research_status` | `queued / in_progress / decision_ready / stale` | 研究流程是否足以形成正式结论 |
| `long_term_status` | `passed / needs_evidence / rejected` | 公司长期是否通过准入 |
| `entry_action` | `staged_buy / wait_price / wait_evidence / avoid` | 当前是否值得建立或增加风险敞口 |
| `portfolio_action` | `not_applicable / add / hold / reduce / exit` | 已有持仓该如何处理 |

典型组合：

- 长期通过但催化后过热：`passed + wait_price + hold`。
- 长期通过且赔率合理的新候选：`passed + staged_buy + not_applicable`。
- 关键原始披露未取得：`needs_evidence + wait_evidence`。
- 长期证伪或治理红线：`rejected + avoid + exit/reduce`，具体持仓动作结合流动性和事实严重性说明。

## 情景与赔率

买点判断必须推演：

```text
base_case
upside_case
downside_case
scenario_drivers
reasonable_value_range
acceptable_price_range
potential_upside
potential_downside
key_sensitivities
```

- 情景推演是必需的；快速备忘录可用短句和区间表达，深度报告应显式展示三情景。
- 证据不足时不要伪造精确概率、目标价或小数点精度，改用条件区间和敏感性。
- 基准和下行情景都要考虑；仅有上行情景不能支持 `staged_buy`。
- 当前价格已经透支基本面改善时，即使长期通过也使用 `wait_price`。
- 长期价格横盘时拆解 `盈利/自由现金流增长 + 现金分红 + 估值倍数变化`。至少 500 个前复权交易日才判断长期价格状态；否则写历史不足。
- 把长期股东总回报与可配置最低回报门槛、市场和行业基准比较。没有过热但机会成本过高时仍可 `wait_price` 或维持现金优先。

## 买入、等待与退出条件

每个行动说明：

- 可接受价格或估值区间，以及估算口径。
- `staged_buy` 的试探仓、基本面确认仓和后续增配触发器；没有用户风险预算时不输出伪精确比例。
- `wait_price` 需要怎样的回撤、横盘消化、盈利上修或价值区间上移才能复核。
- `wait_evidence` 缺哪项证据、由什么来源验证、最晚何时复核。
- 会触发 `reduce`、`exit` 或 `avoid` 的证伪条件和客观红线。
- 下一验证日期和责任明确的后续动作。

## 证据质量

区分：

- **事实**：有来源、时间和口径的数据或披露。
- **推断**：从事实推导出的传导或比较。
- **观点**：带假设和不确定性的判断。
- **未知**：缺失、冲突、过期或不可得的信息。

来源冲突时并列记录，不做无证据平均。未知项影响核心假设时，默认 `wait_evidence`，不要用听起来完整的回答掩盖缺口。

未知项必须先分层：

- `blocking_evidence`：合理答案可能改变长期状态、回报门槛或重大下行情景，才允许生成 `wait_evidence`。
- `confidence_limiters`：不改变行动，只降低置信度。
- `monitoring_items`：持续跟踪，不阻断结论。
- `process_gaps`：研究流程未完成，保持 `research_status=in_progress`，不生成投资行动。

## 最终检查

1. 先有 `long_term_status`，再有 `entry_action`。
2. 技术面和新闻没有提高长期状态。
3. 三种追高风险分别检查。
4. 当前行动与已有持仓动作分开。
5. 情景、价格/等待条件、证伪和下一验证日期齐全。
6. 组合建议说明集中度、流动性和机会成本。
7. 与上次决策不同的状态说明新事实或 `methodology_rebase`，无实质变化时只输出增量更新。

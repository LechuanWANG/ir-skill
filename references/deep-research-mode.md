# 深度研究模式

用户明确要求深度研究、单股投资决策、四视角分析或重大仓位变化时，使用两阶段研究委员会。阶段和行动状态以 `research-screening.md` 为唯一真源。

## 角色

| 角色 | 阶段 L | 阶段 N |
|---|---|---|
| A1 长期公司研究 | 生意、增长、竞争优势、资本配置和 3–5 年收益来源 | 近期事件是否真正改变长期假设 |
| A2 宏观与行业 | 行业长期结构、价值链和竞争格局 | 当前政策、宏观、景气和竞争反应 |
| A3 财务、估值与交易条件 | 报表质量、现金流、长期隐含预期 | 三情景赔率、流动性、拥挤和过热 |
| A4 空头与治理 | 反方证据、治理、会计、杠杆和证伪 | 催化失效、叙事追高和尾部风险 |
| PM/负责人 | 裁定 `long_term_status` | 裁定 `entry_action` 与 `portfolio_action` |

## 编排原则

深度模式是用户对该研究委员会的授权。支持原生 subagents 时，在同一阶段内并行委派边界清晰的角色；不支持时，由主 agent 按相同输入和输出结构顺序完成。阶段 N 不得在 PM 完成阶段 L 裁定前开始。

Portable execution contract: this is a `user-authorized` workflow. When the runtime supports it, `spawn` `parallel native subagents` for A1-A4 inside the current stage; never parallelize across the stage L gate.

- 每个角色只读取本阶段所需的最小证据包，避免近期价格和叙事污染长期判断。
- 负责人不外包最终裁决，不对角色置信度做简单平均。
- 缺失、失败或超时角色作为 `process_gaps` 保留；关键角色缺失且无法替代时保持 `research_status=in_progress`，不生成伪 `needs_evidence / wait_evidence`。
- 所有角色使用同一个 `as_of`，禁止使用决策时点后信息。

## 阶段 L：长期准入

```text
共同长期证据包
-> A1/A3/A4 并行研究，A2 补充行业长期结构
-> 每个角色提交 claims
-> PM 比较支持与反方证据
-> long_term_status = passed / needs_evidence / rejected
```

共同证据包包括：3–5 年原始财务和业务分部、资本配置、治理与公告、行业长期结构、长期估值隐含预期、来源冲突和缺失项。不要加载近期快讯热度、短期技术排名或催化后的价格表现，除非它们本身是长期证伪所需的已核实原始事实。

- `passed`：进入阶段 N。
- `needs_evidence`：只为补齐明确证据加载必要材料，最终行动最多为 `wait_evidence`。
- `rejected`：停止买点评估并输出 `avoid`；可以继续说明风险和已有持仓退出约束。

## 阶段 N：当前买点与两轮质询

仅对阶段 L 允许继续的对象加载：

```text
已核实事件信号
宏观与行业当前状态
最新估值和三情景
技术、流动性与拥挤度
组合约束
```

### Round 1：点名最薄弱主张

每个角色至少选择一条不是自己提出的关键 claim，说明：

- 它依赖哪个未证实假设。
- 缺什么原始证据或量级测算。
- 哪个反方情景最可能推翻它。
- 对 `entry_action` 的影响。

### Round 2：回应并更新置信度

被质询者只能：

1. 补充可验证证据。
2. 用已有事实反驳。
3. 缩小主张范围。
4. 下调置信度或撤回主张。

不能用角色权威、重复叙事或新增无来源假设维持原结论。

## Claim 契约

阶段 L/N 的关键主张统一记录：

```text
claim_id
stage = L / N
time_horizon
thesis_id
claim
supporting_evidence[]
contrary_evidence[]
source_dates[]
author
challenger
challenge
response
initial_confidence
final_confidence
status = supported / narrowed / unresolved / withdrawn
unresolved_questions[]
action_implication
```

## A4 有限否决权

A4 只有在存在客观、可引用证据时，才可建议一票否决：

- 欺诈或重大会计嫌疑。
- 治理或诚信红线。
- 偿债/流动性危机。
- 重大合规或监管风险。

普通估值分歧、行业周期、价格过热和催化不确定性不属于一票否决；它们影响 `wait_price`、`wait_evidence`、仓位和置信度。最终是否否决仍由 PM 说明证据和适用范围。

## PM 裁决

PM 必须：

1. 先引用阶段 L 证据裁定 `long_term_status`。
2. 将未知项分为阻断证据、置信度限制项、持续监测项和流程缺口；只有阻断证据影响投资行动。
3. 对 decision 模式给今天最优行动、现金比较、最接近买入对象及与上次决策的差异。
4. 说明采纳和拒绝哪些 claim，以及原因。
5. 给出基准、上行、下行情景和收益—下行不对称性。
6. 分别检查估值追高、价格追高和叙事追高。
7. 输出 `entry_action`、价格/等待条件、`portfolio_action`、证伪和下一验证日期。
8. 保留未解决分歧，不用平均分掩盖冲突。
9. 列出失败角色、未核实来源和缺失数据。
10. 生成深度报告并提出 Wiki 与 evaluation 写回位置。

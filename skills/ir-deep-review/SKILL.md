---
name: ir-deep-review
description: Independent investment research cross-examination for explicitly requested deep research, review, or challenge of evidence, assumptions, valuation, competition, governance, and tail risks.
---

# 深度研究与独立质询

只在用户明确要求深度研究、独立审阅或交叉质询时使用。先读取 [`../shared/research-discipline.md`](../shared/research-discipline.md)，再按持有期调用 [`../ir-long-term-trading/SKILL.md`](../ir-long-term-trading/SKILL.md)、[`../ir-medium-term-catalyst/SKILL.md`](../ir-medium-term-catalyst/SKILL.md) 或 [`../ir-short-term-trading/SKILL.md`](../ir-short-term-trading/SKILL.md)。普通研究不得自动升级为多审阅者流程。

## 1. 建立共同证据包

主 Agent 先准备研究对象、决策、持有期、`as_of`、候选和约束、核心假设、原始证据、关键缺口，以及可能改变排序或行动标签的变量。证据包须覆盖已知争议和反方路径；所有审阅者使用同一时间边界，不得引入决策时点之后的信息证明此前判断。

## 2. 独立审阅

工具和并发允许时，最多启动三位互不查看彼此结论的审阅者，主 Agent 保留裁决职责：

1. 商业、财务与估值：商业模式、需求、利润/现金质量、资本回报和价格隐含预期。
2. 竞争与替代解释：竞争者反应、供需周期、扩产降价、技术替代和乐观因果链。
3. 治理与尾部风险：会计、杠杆、流动性、治理、监管、诚信和永久性损失。

并发不足时合并角色；完全不能独立审阅时，主 Agent 做明确标注的对立案例检查，不得伪称多 Agent 复核。每位审阅者提交当前立场、两至四项关键判断、最强正反证据、最可能遗漏变量、证伪条件和置信度；候选比较同时给出排序或行动倾向。

## 3. 交叉质询

只转交可能改变核心假设、估值、排序、主要风险或行动标签的冲突。质询应指出具体主张、未证实假设、证据/时间口径问题及其决策影响；原审阅者以补充证据、量化影响、收窄范围、降低置信度、修改排序或撤回主张回应，并标记为 `支持`、`收窄`、`未解决` 或 `撤回`。

当决策相关分歧已充分检验、没有未处理的高影响证据缺口，且下一轮不再可能改变决策时停止；不为展示讨论延长流程，也不因赶时间保留未检验的关键分歧。

## 4. 主 Agent 裁决

不按票数或平均分决定，而是综合证据强度、因果关系、影响量级、赔率和错误损失，明确独立证据支持的共识、仍会改变决策的分歧及当前证据更支持的一方、未覆盖盲区和已撤回观点。

输出当前排序或单股判断、主要行动标签、现金/替代项比较、两至四个关键变量、最可能推翻结论的证据、触发条件和复核时间。最终只展示真正改变判断、未解决或界定结论边界的质询与修订，不输出完整对话或模型私有推理过程。

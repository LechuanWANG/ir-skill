---
name: ir-long-term-trading
description: Evidence-led long-horizon investment research for multi-year holdings, company quality, financial quality, governance, capital allocation, and long-term valuation.
---

# 长期与基本面研究

适用于多年持有、商业质量、财务质量、治理、资本配置和长期估值。先读取 [`../shared/research-discipline.md`](../shared/research-discipline.md)；非股票资产以标的、合约、基准和宏观传导替代公司分析。3–6 个月催化改用 [`../ir-medium-term-catalyst/SKILL.md`](../ir-medium-term-catalyst/SKILL.md)，一个月内交易改用 [`../ir-short-term-trading/SKILL.md`](../ir-short-term-trading/SKILL.md)。

## 1. 数据与范围

按当前决策选择最能改变排序、估值或下行风险的维度，研究深度与不确定性和行动强度相称，不做固定清单式尽调。

```bash
python3 scripts/tushare_mode_data.py plan long --symbol 000001.SZ --end-date 20260719
python3 scripts/tushare_research_data.py plan financial --symbol 000001.SZ --period 20251231 --as-of 20260719
```

先复用本地数据，再补缺口；价格、估值、公司行为和结构化财务使用 TuShare/SQLite，最终财务、治理和资本配置事实以定期报告和公告为准。记录 `as_of`、数据版本、权限状态和来源冲突。详细数据路由见 [`../../references/tushare-data.md`](../../references/tushare-data.md)，原始来源规则见 [`../shared/external-evidence-sources.md`](../shared/external-evidence-sources.md)。

同行比较以申万 2021 等稳定行业分类为主；同花顺板块表现只在买入时点、估值或风险偏好确有影响时解释定价环境，不改写长期行业边界、竞争优势或现金流判断。

## 2. 生意、竞争与再投资

核验公司卖什么、谁付钱、收入/利润/现金流由哪些分部驱动，以及需求是否来自长期经济价值而非补贴、周期、单一客户或一次性项目。判断行业容量、渗透率、份额、产品扩张和国际化空间，同时区分高增长但边际恶化、低增长但拐点改善、一次性跳升与可持续复利。

评估定价权、客户留存和集中度、单位经济性、成本/品牌/渠道/技术/牌照/网络效应等护城河；再用扩产、降价、技术替代、政策和周期测试其可持续性。将增长所需资本、营运资金、杠杆和边际资本回报纳入判断。

## 3. 财务、治理与估值

从原始披露核验收入、利润率、ROIC/ROE、经营现金流、自由现金流、应收、存货、合同负债和利润现金转化；检查三表勾稽、非经常项目、资本化、收入确认和会计估计。增长须拆回销量、价格、结构、成本、补贴或会计处理，并用订单、价格/销量、客户预算、合同负债和产能利用率等领先指标验证未来路径。

检查研发、扩产、并购、商誉、分红、回购、融资、稀释和管理层兑现记录；关注关联交易、担保、资金占用、减持、质押、诉讼、监管问询、审计意见、更正和审计机构变更，以及欺诈、偿债、流动性和合规导致永久损失的风险。

把当前价格转换为对增长、利润率、资本回报和再投资期的隐含要求，与历史、行业容量、竞争反应、共识和领先指标比较，给出区间或情景敏感性。资金和情绪主要影响时点、安全边际和估值波动，除非改变未来现金流、融资成本或生存能力，否则不改写长期价值。

## 4. 可决策结论

说明两至四个价值变量、关键假设及最强反证、最早的验证指标、会改变排序/估值/行动标签的事实，以及当前价格相对价值、现金和替代项的安全边际。历史不足或关键证据缺失时，缩小主张并降低置信度，不以统一评分或泛泛风险清单代替因果解释。

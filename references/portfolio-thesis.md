# 组合与投资假设

持仓、仓位测算和投资假设跟踪使用本参考资料。长期准入和当前行动枚举以 `research-screening.md` 为唯一真源。

## 先读

给组合建议前，先读：

- `docs/investment-llm-wiki/profile.md`
- `docs/investment-llm-wiki/portfolio.md`
- `docs/investment-llm-wiki/index.md` 中相关的 `decision` 和 `analysis` 页面

如果没有结构化组合，询问用户持仓，或在明确标记假设的前提下继续。写入持仓、资金或风险偏好前获得用户确认，除非本轮已明确授权。

## 组合检查

评估：

- 最大持仓和前三大持仓集中度
- 国家/币种/行业/主题集中度
- 现金水平
- 隐性相关性
- 与当前最强想法相比的机会成本
- 用户是否愿意以当前价格买入每个持仓
- 每个持仓的退出流动性和计划仓位需要多少正常成交日
- 新候选是否增加已有的行业、风格、久期、汇率或事件相关性

## 投资假设健康度

对每个持仓分别记录：

```text
thesis_id
long_term_status = passed / needs_evidence / rejected
entry_action = staged_buy / wait_price / wait_evidence / avoid
portfolio_action = add / hold / reduce / exit
original_thesis
return_sources_3_5y
supporting_evidence[]
contrary_evidence[]
falsification_conditions[]
acceptable_price_range
portfolio_role
concentration_and_correlation_effect
liquidity_and_exit_risk
next_validation_date
```

- `entry_action` 回答当前价格是否值得增加风险；`portfolio_action` 回答已有仓位如何处理，两者可以不同。
- 长期通过但价格过热时，通常 `wait_price + hold`，不因长期看好自动加仓。
- 长期证伪或客观红线时，说明 `reduce/exit` 的执行风险和节奏；不要用技术反弹覆盖长期结论。
- 用户未给风险预算时，不伪造精确仓位。可以给风险预算框架、分批条件和需要补充的输入。

当建议会实质性改变仓位时，在用户确认后更新或创建 decision 页面，并登记 20/60/120 日评估日期。

## 组合输出

组合复盘至少展示：

1. 当前组合的长期状态分布。
2. `staged_buy / wait_price / wait_evidence / avoid` 候选与持仓。
3. `add / hold / reduce / exit` 的已有持仓动作。
4. 行业、风格、相关性、流动性、最大持仓和前三大持仓约束。
5. 现金和替代成本，以及每个动作的触发条件。

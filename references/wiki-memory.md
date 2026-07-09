# Investment LLM Wiki 记忆

使用 `docs/investment-llm-wiki/` 中的本地 Investment LLM Wiki 作为持久投资记忆。

## 分析前召回

先读 `docs/investment-llm-wiki/index.md`，再读相关页面：

- `profile.md`：偏好、风险承受能力、约束和深度模式阈值
- `portfolio.md`：当前持仓
- 公司/行业/entity 页面
- analysis/thesis 页面
- decision 页面

## 分析后更新

分析后，只更新有用且可持久化的知识：

- 追加 `log.md`
- 用持久事实更新 entity 页面
- 用投资假设变化更新 analysis 页面
- 为买/卖/加/减/等决策创建 decision 页面
- 当新证据与旧说法冲突时，使用 `contradiction` 块

写入敏感持仓、资金或偏好细节前必须询问，除非用户明确要求更新 Wiki。

## 链接纪律

使用 `[[portfolio]]`、`[[0700.HK]]`、`[[2026-07-01-0700-add]]` 这样的 Wiki 链接。原始来源文件保持不可变。

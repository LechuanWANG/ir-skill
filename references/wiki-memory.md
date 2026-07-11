# Investment LLM Wiki 记忆

使用 `docs/investment-llm-wiki/` 中的本地 Investment LLM Wiki 作为持久投资记忆。Wiki 保存当时的事实、假设和决策快照，不把后见信息覆盖进旧记录。

## 分析前召回

先读 `docs/investment-llm-wiki/index.md`，再读相关页面：

- `profile.md`：偏好、风险承受能力、约束和深度模式阈值
- `portfolio.md`：当前持仓
- 公司/行业/entity 页面
- analysis/thesis 页面
- decision 页面
- evaluation 页面或 decision 页中的 20/60/120 日评估记录

## 分析后更新

分析后，只更新有用且可持久化的知识：

- 追加 `log.md`
- 用持久事实更新 entity 页面
- 用长期投资假设账本更新 analysis/thesis 页面
- 为 `research_status`、`long_term_status`、`entry_action` 和 `portfolio_action` 创建或更新 decision 页面
- 写入 `previous_decision_id`、`decision_change`、`change_reasons` 和 `methodology_change`，确保 refresh 能区分新事实与框架重置
- `queued / in_progress / stale` 写入 watchlist 或研究队列，不创建伪 `wait_evidence` 决策
- 按 `research-evaluation.md` 追加 20/60/120 日评估，不覆盖决策快照
- 当新证据与旧说法冲突时，使用 `contradiction` 块

写入敏感持仓、资金或偏好细节前必须询问，除非用户明确要求更新 Wiki。

## 页面最小字段

### Thesis / analysis

```text
thesis_id
symbol
as_of
holding_horizon
long_term_thesis
return_sources_3_5y
core_assumptions[]
validation_metrics[]
supporting_evidence[]
contrary_evidence[]
falsification_conditions[]
long_term_status
next_validation_date
```

### Decision

```text
decision_id
previous_decision_id
decision_as_of
reference_price
research_status
long_term_status
entry_action
portfolio_action
decision_change
change_reasons[]
methodology_change
acceptable_price_range
overheat_flags[]
waiting_conditions[]
missing_evidence[]
falsification_conditions[]
next_validation_date
source_snapshot[]
```

### Evaluation

```text
decision_id
evaluation_window = 20d / 60d / 120d
evaluation_date
absolute_return
market_relative_return
industry_relative_return
max_adverse_excursion
earnings_estimate_revision
catalyst_status
falsification_status
thesis_status
process_adherence
```

保留所有四类 `entry_action` 的记录，不只写入最终买入对象。

## 链接纪律

使用 `[[portfolio]]`、`[[0700.HK]]`、`[[thesis-0700-long-term]]`、`[[2026-07-01-0700-wait-price]]` 这样的 Wiki 链接。decision 链接到 thesis 和后续 evaluation；原始来源文件与原决策快照保持不可变。

生成 refresh 或新的 decision 报告前，必须先查询上一条同标的 decision。若没有新财报、重大事件、复核到期或显著价格/估值变化，则只写“沿用上次结论”，不重复生成完整深研。

既有报告若包含 `decision_snapshot.json`，先运行 `scripts/research_workflow.py snapshot-import --input <path>` 将历史结论写入同一 SQLite。导入按 `decision_id` 幂等去重，使下一次候选发现立即应用重复冷却、refresh 分流和结论差异比较。

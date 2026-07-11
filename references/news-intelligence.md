# 事件信号与 `news_intake`

本文件定义按需事件监控和新闻信号卡。格隆汇、财联社等只是来源适配器；`news_intake` 的职责是发现变化并组织待核实线索，不是按新闻热度选股，也不是全文新闻仓库。

## 何时调用

以下情况按需拉取最近 24–72 小时信号：

- 用户询问近期事件、价格异动、政策或行业变化。
- `event-driven`、`industry-signal` 或 `market-context` 研究需要当前信息。
- 已有长期投资假设需要监控催化、证伪或执行进度。
- 持仓出现异常价格、成交、监管或治理风险。

长期质量研究、历史财务比较或纯估值复核没有当前事件依赖时，不必抓取。纯异动归因可以直接生成归因结果；一旦用户进一步问“能不能买”，候选必须回到 `research-screening.md` 的阶段 L。

## 来源与权限

来源分三层：

1. 快讯雷达：格隆汇、财联社、第一财经、路透社、彭博社、财新等，只用于发现线索；付费源仅在拥有合法访问权限时使用。
2. 官方确认：国务院、央行、统计局、部委、证监会、交易所、巨潮资讯、海外监管机构和公司 IR。
3. 独立核对：可靠财经媒体、行业协会、产业数据及上下游公司披露。

格隆汇公开快讯的当前适配器示例：

```bash
webclaw "https://www.gelonghui.com/live" \
  --format json \
  --include '.live-data-item:has(.desc.is-weight)'
```

CSS 选择器属于可变来源配置，不是业务规则。调用前检查页面结构和获取时间；失效时记录 adapter failure 并切换其他雷达或官方检索，不静默返回“无事件”。

项目入口使用参数数组调用 Webclaw，不经过 shell。离线材料先 `parse`，确认结构和去重结果后再 `ingest`；`query` 同时返回信号卡和假设映射：

```bash
python3 scripts/news_intake.py fetch --since-hours 72
python3 scripts/news_intake.py parse --input authorized_webclaw.json --since-hours 72
python3 scripts/news_intake.py ingest --input authorized_webclaw.json --since-hours 72
python3 scripts/news_intake.py query --important-only
```

`news_intake` 可以：

- 按时间、关键词、公司、行业和长期假设检索公开信号。
- 去重、分类、抽取实体和映射长期假设。
- 记录官方核实状态、价格反应和未解决问题。
- 提高研究优先级或触发重跑阶段 L/N。

`news_intake` 不可以：

- 按新闻次数、热度或“重要”标签提高长期质量评价。
- 用单一媒体标题替代原始公告或官方政策。
- 未完成量级和持续性判断就输出“利好/利空”。
- 因近期没有新闻而降低长期公司评价。
- 绕过登录、验证码、付费墙、robots/站点条款或访问频率限制。
- 自动执行交易或把信号直接变成 `staged_buy`。

## 信号卡契约

```text
signal_id
published_at
event_at
retrieved_at
source_name
source_type = radar / official / independent
source_url
headline
normalized_event
entities[]
industries[]
thesis_id
impact_direction = positive / negative / mixed / unknown
financial_driver = revenue / cost / margin / cashflow / WACC / risk / unknown
estimated_magnitude
expected_duration
price_reaction_since_event
priced_in_assessment
verification_status
verification_sources[]
open_questions[]
content_hash
expires_at
```

- `estimated_magnitude` 可以是范围或“不可得”，不能为了完整而伪造精确数字。
- `expected_duration` 至少区分一次性、0–6 个月、6–24 个月和 3–5 年结构性影响。
- 没有 `thesis_id` 的事件只能保存在资讯记录；若它产生新候选，先建立新的阶段 L 任务。
- `price_reaction_since_event` 使用可复算的事件前后价格，并标明基准指数或行业相对表现。

## 去重与状态机

优先使用原始链接、规范化标题、实体、事件时间桶和内容哈希去重。转载同一官方事实的多篇报道只保留一张主信号卡，并把其他来源放入 `verification_sources`。

```text
raw
-> deduplicated
-> pending_verification
-> verified / rejected
-> thesis_mapped
-> active / expired
```

- `pending_verification`：只用于待办和研究优先级，不进入最终证据。
- `verified`：有官方原始来源，或至少两个独立可靠来源相互印证。
- `rejected`：来源错误、重复、失实、与标的无关或无法确认。
- `active`：仍可能影响长期假设或当前买点。
- `expired`：时效已过、影响已兑现、已证伪或不再相关；保留记录，不进入当前上下文。

## 五项验证门

事件只有同时完成以下检查，才可以影响阶段 N；结构性事件还必须触发阶段 L 复核：

1. **真实性**：官方原始来源，或两个独立可靠来源交叉印证。
2. **关联性**：映射到具体 `thesis_id` 和收入、成本、利润、现金流、资本成本或风险假设。
3. **量级**：估计方向和大致量级；无法估计时明确列为关键未知。
4. **持续性**：判断一次性、周期性或结构性，最好能跨越至少一个财报期。
5. **预期差**：检查公告前后价格、卖方预期和市场共识，判断是否已充分定价。

任何一项关键检查未完成时，默认 `entry_action = wait_evidence`，而不是用较弱信号补齐叙事。

## 与双阶段状态机的关系

| 信号类型 | 允许动作 |
|---|---|
| 无法映射长期假设 | 保存为资讯或新建研究任务，不改结论 |
| 已核实的短期催化 | 更新阶段 N、价格和等待条件 |
| 已核实的证伪风险 | 降低置信度，必要时重跑阶段 L |
| 可能改变行业结构或长期现金流 | 重跑阶段 L，不直接升级买入动作 |
| 纯情绪或价格解释 | 只用于归因和拥挤判断 |

事件不能提高 `long_term_status`；只有把事件转化为原始事实证据并重新完成阶段 L，才可能更新长期判断。

## 最小运行记录

每次调用记录：

```text
query_intent
time_window
sources_attempted
sources_succeeded
signals_found
signals_deduplicated
signals_verified
signals_mapped
access_failures
retrieved_at
```

若站点不可访问，使用其他雷达或官方来源降级，不让格隆汇成为单点依赖。只保存结构化信号卡、必要短摘录和原始链接，不建立无边界全文新闻库。

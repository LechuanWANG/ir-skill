# TuShare 研究数据计划

把 TuShare 当作标准化研究数据底座，不要把它缩减成技术筛选器，也不要把 40 多个接口一次性全部拉取。

## 默认流程

```text
识别用户意图、持有周期和 as_of
-> 写出初始可证伪假设
-> 阶段 L：long-term-quality + risk-review
-> 检查接口能力、缓存和数据新鲜度
-> 定向采集并与官方披露交叉核对
-> 裁定 long_term_status
-> 阶段 N：按需 event-driven / industry-signal / market-context
-> 最后 timing-liquidity
-> 形成投资与买入条件卡
```

用户只说“筛选股票”而尚无候选池时，先使用 `fundamental_pool.py` 的长期基本面研究池；只有用户明确要求全市场量化初筛、动量或技术面筛选时，才运行全市场同步与 `factor_screen.py --explicit-quantitative-baseline`。两类研究池都不能直接生成推荐。

## 研究 Profiles

| Profile | 阶段 | 解决的问题 | 核心数据 |
|---|---|---|---|
| `long-term-quality` | L | 是否是可长期持有的好生意 | 三张表、财务指标、业务分部、分红、股东变化 |
| `risk-review` | L | 哪些风险可能让长期假设失效 | 资产负债表、现金流、质押、股东、解禁和融资风险 |
| `earnings-inflection` | L/N | 盈利预期变化是否可持续 | 业绩预告/快报、卖方预测、机构调研、财报和披露窗口 |
| `valuation-repair` | L/N | 是长期误价还是价值陷阱 | 历史估值、三张表、现金流、分红、质押和卖方预期 |
| `event-driven` | N | 已核实催化如何更新长期假设 | 回购、解禁、增减持、机构调研、资金、龙虎榜和停复牌 |
| `industry-signal` | L/N | 行业结构或景气如何传导到公司 | 行业映射、业务分部、卖方预测、指数和宏观数据 |
| `market-context` | N | 当前宏观和市场状态是什么 | 指数、Shibor、CPI、PPI、PMI、货币供应和行业分类 |
| `timing-liquidity` | N 最后 | 长期通过后何时介入 | 行情、复权、估值、资金流、筹码、拥挤和流动性 |

可以组合多个 profile，但单股买入或推荐问题必须先使用 `long-term-quality + risk-review`。事件和行业信号可以先生成候选，不能先生成买入；候选回到阶段 L 后再决定是否追加阶段 N。数据不足时增量采集，不预拉所有接口。

`timing-liquidity` 默认定向采集至少 1,100 个自然日的 `daily + adj_factor + index_daily`，用于形成约 3 年前复权价格状态。少于 500 个有效交易日时只允许短期反追高判断，不允许长期横盘、趋势或机会成本结论。

## 两层数据使用

### 全市场基础层

用于构建可复现候选池：

- `stock_basic`：上市状态、名称、行业和市场。
- `daily` + `adj_factor`：价格、成交量、复权和流动性，仅用于阶段 N 或明确的量化基线。
- `daily_basic`：估值、市值、换手和股本。
- `fina_indicator`：盈利质量、成长、杠杆和现金转化。

这层可以按日或财报期增量同步到结构化表。默认使用 `daily_basic + fina_indicator + stock_basic` 建立长期基本面研究池；仅在用户明确要求量化降维时使用 `factor_screen.py --explicit-quantitative-baseline`。

### 候选股研究层

用于解释“为什么值得研究”：

- 三张表与业务分部：`income`, `balancesheet`, `cashflow`, `fina_mainbz`。
- 盈利预期：`forecast`, `express`, `report_rc`, `disclosure_date`。
- 机构行为：`stk_surv`, `broker_recommend`, `top10_holders`, `top10_floatholders`。
- 公司行动与风险：`dividend`, `repurchase`, `share_float`, `stk_holdertrade`, `pledge_stat`。
- 资金与筹码：`moneyflow`, `cyq_perf`, `cyq_chips`, `top_list`, `top_inst`, `block_trade`, `margin_detail`。
- 行业与宏观：`index_member_all`, `ths_index`, `ths_member`, `index_daily`, `shibor`, `cn_cpi`, `cn_ppi`, `cn_pmi`, `cn_m`。

这些异构数据写入 `tushare_research_observation`。`dataset + row_hash` 负责内容去重，`business_key + revision` 保留同一业务事实的后续修订，`first_seen_at / last_seen_at / available_at` 支持 point-in-time 查询。接口权限与最近探针结果写入 `tushare_capability`。原始观察是证据材料，不等于长期假设、事件验证或买入结论。

## 工具命令

项目根目录 `.env` 中的 `TUSHARE_TOKEN` 会自动加载；环境变量中的同名值优先。

检查当前权限并写入能力表：

```bash
python3 scripts/tushare_research.py doctor \
  --as-of 20260710 \
  --sample-symbol 000001.SZ \
  --endpoints daily_basic income balancesheet cashflow report_rc stk_surv pledge_stat moneyflow
```

只生成长期优先计划，不联网：

```bash
python3 scripts/tushare_research.py staged-plan \
  --symbols 000001.SZ \
  --as-of 20260710 \
  --current-profile event-driven market-context timing-liquidity
```

执行定向采集并写入 SQLite：

```bash
python3 scripts/tushare_research.py collect \
  --profile long-term-quality risk-review \
  --symbols 000001.SZ \
  --as-of 20260710
```

读取缓存证据：

```bash
python3 scripts/tushare_research.py query \
  --dataset report_rc \
  --symbols 000001.SZ \
  --available-as-of 20260710 \
  --limit 50
```

## 当前能力基线

2026-07-11 使用本地 token 做小样本探针，已确认可访问：行情/复权/估值、财务指标与三张表、业务分部、业绩预告/快报、机构调研、卖方盈利预测、分红回购、股东与质押、资金流/龙虎榜/大宗交易/融资融券、筹码分布、行业成分、指数和主要国内宏观数据。

当前未获得 `irm_qa_sh`, `irm_qa_sz`, `anns_d`, `news` 权限；公告和新闻继续使用交易所/巨潮资讯、公司 IR 与 Webclaw。权限会变化，以最新 `doctor` 结果为准；`empty` 表示接口可调用但样本期无数据，不等于无权限。

## 阶段化调用

### 阶段 L

```bash
python3 scripts/tushare_research.py staged-plan \
  --symbols 000001.SZ \
  --as-of 20260710 \
  --current-profile event-driven market-context timing-liquidity
```

先确认三张表、业务分部、资本行动、股东/质押、历史估值和风险证据的权限与新鲜度。原始财务数字回到巨潮资讯、交易所或公司 IR 核对后，才裁定 `long_term_status`。

### 阶段 N

仅对 `passed` 或为补齐明确证据的 `needs_evidence` 对象追加：

```text
event-driven / industry-signal / market-context
-> timing-liquidity
```

TuShare 无新闻与公告权限时，事件由 `news-intelligence.md` 的 `news_intake` 和官方来源补齐；资金、筹码和卖方数据不能替代事件真实性。

## 研究纪律

1. 先写假设，再取数据；不要看到什么字段就讲什么故事。
2. profile 决定取什么数据，`research-screening.md` 决定允许进入哪个阶段，两者不能混用。
3. 全市场基础层与候选研究层分开，避免为每个问题重复下载全市场。
4. 财务数据按 `ann_date`/`f_ann_date` 做公开时点约束；历史重放用 `--available-as-of` 选择当时公开可得的最新 `revision`。需要严格本地回放时追加 `--observed-as-of`，不能使用当时尚未披露或本地尚未观察到的后续修订。
5. 卖方报告、机构调研、资金流和筹码只用于预期差与拥挤判断，不视为事实证明。
6. 技术指标只回答流动性、风险、拥挤和节奏，不回答公司是否值得长期持有。
7. 长期价格状态同时展示股东总回报、分红、估值倍数变化和相对基准，避免把价格横盘误写成零回报。
8. TuShare 是标准化二级来源；最终财务结论仍需回原始年报、公告或公司 IR 核对。
9. 必需接口失败时写入 `process_gaps` 并保持研究未完成；只有经济上会改变结论的未知项进入 `blocking_evidence`。
10. 阶段 N 数据不能反向覆盖阶段 L 的客观红线；结构性新事实只能触发重跑阶段 L。

## 数据计划输出契约

```text
stage｜研究 profile｜thesis_id｜投资假设｜候选范围｜as_of
必需数据集｜可选数据集｜接口权限｜时间窗口｜预计调用数
required_for_gate｜已缓存/需刷新｜freshness_status
缺失输入｜不可用接口｜替代来源｜官方核验要求
技术面的角色｜下一步验证动作｜允许的状态转换
```

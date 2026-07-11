# 数据来源

数字使用确定性数据，解释使用 AI 判断。

## 来源分层

| 数据需求 | 主要来源 | 交叉核对 | 备注 |
|---|---|---|---|
| A 股历史价格/成交量/复权 | 同步进本地 SQLite 的 TuShare 数据 | 数据库新鲜度检查 | 收益率使用前复权价格 |
| 盘中/最新价格/报价 | 当前网络或交易所/公司官方来源 | 最近一次已存储日收盘价 | 当前报价不可得时必须说明 |
| A 股筛选财务指标 | TuShare `fina_indicator` | 公开年报、半年报或季报 | TuShare 可作为标准化筛选输入 |
| 候选股三张表/业务分部 | TuShare `income`, `balancesheet`, `cashflow`, `fina_mainbz` | 交易所/巨潮资讯/公司 IR 原始报告 | 用于研究包和历史比较，最终数字回原文核对 |
| 盈利预期/机构活动 | TuShare `forecast`, `express`, `report_rc`, `stk_surv` | 公司公告、调研纪要、卖方报告原文 | 用于判断预期差，不等于已确认事实 |
| 股东/资本行动/风险 | TuShare 股东、质押、分红、回购、解禁和增减持接口 | 公司及交易所公告 | 事件日期和执行进度必须核验 |
| 资金、筹码与交易事件 | TuShare `moneyflow`, `cyq_*`, 龙虎榜、大宗交易、融资融券 | 交易所数据与价格行为 | 只用于拥挤、流动性和节奏判断 |
| 行业与宏观 | TuShare 行业成分、指数、Shibor、CPI/PPI/PMI/M | 官方统计、央行、部委和交易所 | 标准化历史序列；当前政策仍需联网刷新 |
| A 股深度报告财务报表 | 巨潮资讯、交易所或公司投资者关系页面上的公开年报、半年报或季报 | TuShare、东方财富、新浪或其他标准化数据库 | 最终财务数字以原始公开披露为记录来源 |
| 快讯雷达 | 按需 `scripts/news_intake.py`；格隆汇、财联社等公开快讯源 | 官方原始来源和独立可靠报道 | 只生成待验证信号卡，不按热度生成推荐 |
| 新闻/政策/宏观确认 | 官方网站、交易所、巨潮资讯、公司 IR 和当前网络检索 | 重要结论用独立报道核对 | 政策、战争/冲突、利率、流动性、汇率、大宗商品和监管必须刷新 |
| 用户持仓/偏好 | `docs/investment-llm-wiki/profile.md`, `portfolio.md` | 敏感写入前用户确认 | 默认只保存在本地 |

## 必备数据字段

形成股票结论时，记录：

- 代码/ticker、市场、币种、最新价格、时间戳
- 市值输入：价格、股本、单位
- 估值输入：EPS、BVPS，以及可得时的 PE/PB
- 财务质量：收入/利润趋势、ROE、杠杆，可得时包括现金流
- 来源名称和获取日期
- `as_of`、报告/事件发布时间和数据新鲜度
- `decision_id`、`thesis_id`、`long_term_status`、`entry_action` 和下一验证日期

## 交叉核对规则

- 差异 <= 1%：使用主来源；如果两个来源都可得，两个都引用。
- 差异 > 1% 且 <= 5%：标记为来源差异，并解释可能的单位、会计口径或时间原因。
- 差异 > 5%：在核查原始披露或交易所公告前，不要依赖该数字。

常见失败模式：HKD 与 CNY 混用，总股本与流通股混用，股数单位是手/lot/万，财年与自然年错配，GAAP 指标与调整后指标混用。

## 宏观与政策网络刷新

当宏观或政策条件可能改变投资结论时，在最终回答前执行当前网络检索。

按以下优先级搜索并引用来源：

1. 官方政策、央行、监管机构、交易所、部委、海关、统计或财政来源。
2. 如果宏观事件对公司有特定影响，使用公司或交易所公告。
3. 使用主要财经媒体或可靠数据提供方理解事件解读和市场反应。
4. 二级评论只能作为背景，不能作为记录来源。

相关时刷新这些主题：

- 货币政策、利率变化、流动性操作、信贷政策
- 财政政策、补贴、税收、产业政策、采购、出口管制
- 战争、制裁、关税、地缘冲突、航运或供应链扰动
- 汇率、大宗商品价格、能源价格、通胀、PMI、就业、GDP
- 行业监管、反垄断、环保规则、医疗/教育/互联网/金融政策

记录来源名称、发布日期、事件日期、获取日期，以及来源是官方还是媒体。若网络检索不可用，说明该限制，并避免给出高置信度宏观结论。

## 事件信号来源

快讯雷达与事实确认分开：

1. 按 `news-intelligence.md` 使用 `scripts/news_intake.py` 检索或导入 24–72 小时公开信号。
2. 先去重，再记录 `signal_id`、原始链接、发布时间、抓取时间、公司/行业实体和验证状态。
3. 新闻标题、媒体“重要”标记和转载数量都不是投资证据。
4. 重要事件回到政策原文、交易所、巨潮资讯、公司公告或其他原始来源确认。
5. 至少记录影响的 `thesis_id`、财务传导、量级、持续时间、事件后价格反应和是否已定价。
6. 未通过真实性、关联性、量级、持续性和预期差检查的事件不得进入最终结论。

抓取遵守站点条款、频率和授权，不绕过登录或付费限制。只保留结构化信号卡、必要短摘录和原始链接，不建设无边界全文新闻库。

## 公开财报交叉核对

做深度研究、一流公司短名单复核和最终投资结论时，财务报表数字不得只依赖 TuShare。

使用以下工作流：

1. 从巨潮资讯、SSE/SZSE/BSE 披露页面或公司投资者关系网站，定位最新公开年报、半年报和季报。
2. 将原始公开披露作为收入、营业利润、归母净利润、扣非归母净利润、EPS、总资产、总负债、经营现金流和业务分部数字的记录来源。
3. TuShare、东方财富、新浪或类似标准化来源只能作为交叉核对和历史辅助，不能成为深度报告的唯一证据。
4. 记录报告期、公告日期、披露标题、来源名称、获取时间、单位和币种。
5. 如果使用报告产物文件夹，将披露列表、下载的公开报告或提取表格，以及标准化交叉核对表放在 `outputs/reports/{report_slug}_{YYYYMMDD}/data/`。
6. 如果本次运行无法取得原始公开报告，必须明确写出，降低置信度，并避免只凭标准化数据库数据给出高确信结论。

可得时至少交叉核对这些字段：

- 收入
- 归母净利润
- 扣非归母净利润
- EPS
- 毛利率或毛利输入
- 总资产和总负债
- 经营现金流
- 主要业务分部收入和利润率

## 本地数据库存储

使用 `data/investment_research.sqlite` 作为下载市场数据的默认可复用存储。这样可避免重复运行制造一次性 CSV 缓存，并为后续筛选、归因和研究任务提供稳定的本地数据源。

默认表：

| 表 | 键 | 字段 |
|---|---|---|
| `a_share_daily` | `(trade_date, ts_code)` | `close_qfq`, `volume`, `source`, `retrieved_at` |
| `a_share_daily_basic` | `(trade_date, ts_code)` | `close`, `turnover_rate`, `volume_ratio`, `pe`, `pe_ttm`, `pb`, `ps`, `ps_ttm`, `dv_ratio`, `dv_ttm`, `total_mv`, `circ_mv`, 股本字段, `source`, `retrieved_at` |
| `a_share_fina_indicator` | `(end_date, ts_code)` | `ann_date`, `roe`, `roe_dt`, `roa`, 利润率字段, `netprofit_yoy`, `or_yoy`, `debt_to_assets`, 流动性比率, `ocf_to_or`, `bps`, `eps`, `source`, `retrieved_at` |
| `a_share_stock_basic` | `ts_code` | `name`, `industry`, `market`, `list_date`, `source`, `retrieved_at` |
| `tushare_research_observation` | `(dataset, row_hash)` | `business_key`, `revision`, `is_current`, `ts_code`, `event_date`, `available_at`, `first_seen_at`, `last_seen_at`, 原始 JSON payload, `source`, `retrieved_at` |
| `tushare_capability` | `endpoint` | 接口分类、`available/empty/denied/error`、样本行数、探针时间 |

规则：

1. 通过 `scripts/tushare_sync.py` 增量维护全市场基础层；不要为单股问题重复下载全市场。
2. 用户未限定量化方法的选股请求，先用 `scripts/fundamental_pool.py` 从 `daily_basic`、`fina_indicator` 和 `stock_basic` 建立长期基本面研究池，再用 `scripts/research_workflow.py staged-plan` 或 `scripts/tushare_research.py staged-plan` 对候选股规划阶段 L；裸 `plan` 仅用于单一 profile 诊断。
3. 异构接口原样写入 `tushare_research_observation`，同一 `business_key` 的内容变化追加 `revision`，相同内容只更新 `last_seen_at`；能力探针写入 `tushare_capability`。
4. 通过 `scripts/technical_screen.py` 对已完成阶段 L 的候选读取技术上下文；只有用户明确要求多因子或技术量化初筛时，才运行 `scripts/factor_screen.py --explicit-quantitative-baseline`。
5. CSV/XLSX 文件只作为最终导出或用户提供的一次性增强文件，不作为权威缓存。
6. 数据库保留在本地 `data/` 下；不要提交，也不要复制进 Wiki 页面。
7. 如果数据库对用户请求的日期范围已经过期，分析前刷新，或明确标记数据过期。
8. 按 `ann_date`/`f_ann_date` 对齐财务与事件数据；历史决策查询使用 `--available-as-of` 读取当时公开可得的最新版本。需要严格复现“本地当时实际见过什么”时，再叠加 `--observed-as-of` 约束 `first_seen_at`。
9. 12-1 momentum 大约需要 270 条日线记录。自身历史估值分位在拥有 3 年以上 `daily_basic` 时更可靠；历史较短时必须标记回退口径。
10. 决策快照不得覆盖原记录；同一 `decision_id` 的 20/60/120 日窗口写入 `outcome_snapshot`，并保留评价标签、等待条件、来源和实际评估日期。
11. `wait_price`、`wait_evidence` 和 `avoid` 与 `staged_buy` 同样保存，避免只评估正面样本。

## LLM 复算清单（LLM Recalculation Checklist）

起草任何包含财务数字的报告后，agent 必须先从数据表机械复算关键数字，才能把报告视为可用：

| 检查项 | 公式 / 规则 |
|---|---|
| 市值 | `price × shares`；确认单位和币种 |
| PE | `price / EPS`；EPS 缺失或不可比时标记不可得 |
| PB | `price / BVPS`；BVPS 缺失时标记不可得 |
| 股息率 | `dividend / price`；确认是否为年化股息基准 |
| 事件后价格反应 | 使用事件前最后可交易价和 `as_of` 可得复权价格；同时比较市场/行业基准 |
| 20/60/120 日收益 | 使用决策后首个可交易价格与相应交易日复权价格；记录基准和缺失窗口 |

使用 `scripts/financial_check.py` 执行计算。LLM 的工作是把复算结果与备忘录/报告正文比较，捕捉单位或币种错误，并修正报告或把数字标记为不可得。

## 脚本

使用：

```bash
python3 scripts/tushare_sync.py 20260101 20260131 --db-path data/investment_research.sqlite
python3 scripts/tushare_sync.py 20250101 20260131 --db-path data/investment_research.sqlite --daily-basic --fina-indicator --stock-basic
python3 scripts/tushare_research.py doctor --as-of 20260131 --endpoints daily_basic income cashflow report_rc pledge_stat
python3 scripts/research_workflow.py staged-plan --symbols 000001.SZ --as-of 20260131 --current-profile market-context timing-liquidity
python3 scripts/tushare_research.py collect --profile long-term-quality --symbols 000001.SZ --as-of 20260131
python3 scripts/tushare_research.py query --dataset income --symbols 000001.SZ --available-as-of 20260131
python3 scripts/research_store.py migrate
python3 scripts/research_store.py stats
python3 scripts/news_intake.py fetch --since-hours 72
python3 scripts/news_intake.py parse --input authorized_webclaw.json --since-hours 72
python3 scripts/news_intake.py query --important-only
python3 scripts/fundamental_pool.py --db-path data/investment_research.sqlite --as-of 20260131 --top 30 --output outputs/screens/fundamental_pool.csv
python3 scripts/technical_screen.py --db-path data/investment_research.sqlite --symbols 000001.SZ --start-date 20260101 --end-date 20260131 --output outputs/screens/screen.csv
python3 scripts/factor_screen.py --explicit-quantitative-baseline --db-path data/investment_research.sqlite --as-of 20260131 --preset balanced --output outputs/screens/factor_screen.csv
python3 scripts/financial_check.py verify-market-cap --price 10 --shares 100000000 --reported 1000000000 --currency CNY
```

入口职责保持单一：`scripts/research_workflow.py` 管理研究阶段和四桶决策，`scripts/research_store.py` 管理迁移与审计查询，`scripts/news_intake.py` 管理事件信号及假设映射。格隆汇 `fetch` 依赖 Webclaw；没有网络或抓取工具时，先用 `parse --input <path>` 检查已授权材料，再用 `ingest --input <path>` 持久化；`list/mappings` 保留为单表查询，`query` 同时返回信号与映射。

`TUSHARE_TOKEN` 优先来自环境变量，也可放在项目根目录且已被忽略的 `.env`。不要把凭据写进代码、文档、日志、Wiki 或输出文件。

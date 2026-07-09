# 数据来源

数字使用确定性数据，解释使用 AI 判断。

## 来源分层

| 数据需求 | 主要来源 | 交叉核对 | 备注 |
|---|---|---|---|
| A 股历史价格/成交量/复权 | 同步进本地 SQLite 的 TuShare 数据 | 数据库新鲜度检查 | 收益率使用前复权价格 |
| 盘中/最新价格/报价 | 当前网络或交易所/公司官方来源 | 最近一次已存储日收盘价 | 当前报价不可得时必须说明 |
| A 股筛选财务指标 | TuShare `fina_indicator` | 公开年报、半年报或季报 | TuShare 可作为标准化筛选输入 |
| A 股深度报告财务报表 | 巨潮资讯、交易所或公司投资者关系页面上的公开年报、半年报或季报 | TuShare、东方财富、新浪或其他标准化数据库 | 最终财务数字以原始公开披露为记录来源 |
| 新闻/政策/宏观 | 当前网络检索；官方来源优先 | 重要结论用独立报道核对 | 政策、战争/冲突、利率、流动性、汇率、大宗商品和监管必须刷新 |
| 用户持仓/偏好 | `docs/investment-llm-wiki/profile.md`, `portfolio.md` | 敏感写入前用户确认 | 默认只保存在本地 |

## 必备数据字段

形成股票结论时，记录：

- 代码/ticker、市场、币种、最新价格、时间戳
- 市值输入：价格、股本、单位
- 估值输入：EPS、BVPS，以及可得时的 PE/PB
- 财务质量：收入/利润趋势、ROE、杠杆，可得时包括现金流
- 来源名称和获取日期

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

规则：

1. 通过 `scripts/tushare_sync.py` 将下载的 TuShare 价格、成交量、复权、daily_basic、fina_indicator 和 stock_basic 数据同步进 SQLite。
2. 通过 `scripts/technical_screen.py` 读取原始技术面输入；通过 `scripts/factor_screen.py` 读取多因子筛选输入。
3. CSV/XLSX 文件只作为最终导出或用户提供的一次性增强文件，不作为权威缓存。
4. 数据库保留在本地 `data/` 下；不要提交，也不要复制进 Wiki 页面。
5. 如果数据库对用户请求的日期范围已经过期，分析前刷新，或明确标记数据过期。
6. 按 `ann_date` 对齐财务指标；不要使用筛选 `as_of` 日期之后才公告的财务行。
7. 12-1 momentum 大约需要 270 条日线记录。自身历史估值分位在拥有 3 年以上 `daily_basic` 时更可靠；历史较短时必须标记回退口径。

## LLM 复算清单

起草任何包含财务数字的报告后，agent 必须先从数据表机械复算关键数字，才能把报告视为可用：

| 检查项 | 公式 / 规则 |
|---|---|
| 市值 | `price × shares`；确认单位和币种 |
| PE | `price / EPS`；EPS 缺失或不可比时标记不可得 |
| PB | `price / BVPS`；BVPS 缺失时标记不可得 |
| 股息率 | `dividend / price`；确认是否为年化股息基准 |

使用 `scripts/financial_check.py` 执行计算。LLM 的工作是把复算结果与备忘录/报告正文比较，捕捉单位或币种错误，并修正报告或把数字标记为不可得。

## 脚本

使用：

```bash
python3 scripts/tushare_sync.py 20260101 20260131 --db-path data/investment_research.sqlite
python3 scripts/tushare_sync.py 20250101 20260131 --db-path data/investment_research.sqlite --daily-basic --fina-indicator --stock-basic
python3 scripts/technical_screen.py --db-path data/investment_research.sqlite --start-date 20260101 --end-date 20260131 --output outputs/screens/screen.csv
python3 scripts/factor_screen.py --db-path data/investment_research.sqlite --as-of 20260131 --preset balanced --output outputs/screens/factor_screen.csv
python3 scripts/financial_check.py verify-market-cap --price 10 --shares 100000000 --reported 1000000000 --currency CNY
```

`TUSHARE_TOKEN` 必须来自环境变量。不要硬编码凭据。

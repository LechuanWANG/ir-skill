# 数据层总览（大白话版）

这份文档说明本 Skill 目前会把哪些数据放进 SQLite、每张表里大致有什么字段，以及它们能帮研究回答什么问题。

数据库默认位置是 `data/research-library/database/investment_research.sqlite`，属于本地集中数据层。每次成功采集的数据都先保存；不要只看命令行临时输出。公司财报、公告、回购、分红等最终事实仍要回到公司、交易所或巨潮的原始文件核实。

## 先区分研究状态与数据

`data/research-library/staging/<task-id>/task-state.json` 和 `research-state.md` 是长链路研究的上下文恢复状态。前者只管生命周期，后者由 Agent 根据具体任务自由组织；它们不参与计算、筛选、排名、回测或历史对比，因此不写入 SQLite，也不属于长期研究记忆。

研究结束后，正式结论写入 `report/`，可复用结构化数据留在 SQLite，原始资料按归档规则进入资料库；只有用户明确授权时才把综合记忆写入 Wiki。任务状态默认仅在终态后保留短期恢复窗口，不能替代这些持久层。

## 再理解三层数据

| 层级 | 放在哪里 | 大白话解释 | 适合做什么 |
| --- | --- | --- | --- |
| 个股主表 | `a_share_*` | 经常要按日期、股票做计算的数据，单独整理好，查询快。 | 技术指标、估值历史、基础筛选和时间序列比较。 |
| 市场主表 | `market_*` | 大盘、指数、行业口径和市场资金环境的“公共背景板”。 | 相对表现、市场环境、行业口径、交易日检查。 |
| 通用观察表 | `tushare_research_observation` | 任何接口的原始行都能先放这里，连同首次看到、最后看到和修订版本一起留痕。 | 公司事件、公告线索、少用接口和结果复核。 |

所有表都带有 `source`（来源）和 `retrieved_at`（这次什么时候下载）的字段。看到历史数据时，要分清“数据对应哪一天”和“本地什么时候拿到它”。

## 个股基础与估值

| 表 | 主要字段 | 用大白话说 | 可以帮助回答 |
| --- | --- | --- | --- |
| `a_share_daily` | `trade_date`、`ts_code`、`close_qfq`、`volume` | 某只股票每天的前复权收盘价和成交量。`close_qfq` 把分红、送配等除权影响调平，便于看连续走势。 | 价格趋势、收益率、波动、均线、MACD、RSI、量价关系。 |
| `a_share_daily_basic` | `trade_date`、`ts_code`、`close`、`turnover_rate`、`volume_ratio`、`pe`、`pe_ttm`、`pb`、`ps`、`ps_ttm`、`dv_ratio`、`dv_ttm`、`total_mv`、`circ_mv`、`total_share`、`float_share`、`free_share` | 每日市场给出的估值、换手和股本快照。 | 市场给这只股票多少估值、成交是否拥挤、流通盘和总市值是否变化。 |
| `a_share_fina_indicator` | `end_date`、`ts_code`、`ann_date`、`roe`、`roe_dt`、`roa`、`netprofit_margin`、`grossprofit_margin`、`netprofit_yoy`、`or_yoy`、`debt_to_assets`、`current_ratio`、`quick_ratio`、`ocf_to_or`、`bps`、`eps` | 一组财务质量和趋势线索，含报告期和公告日。 | 盈利能力、利润率、负债压力、现金回收是否在变好或变差。最终数字仍要核对财报原文。 |
| `a_share_stock_basic` | `ts_code`、`name`、`industry`、`market`、`list_date` | 股票的名字、常见行业标签、板块和上市日期。 | 建股票池、做基础过滤、避免把股票代码和名称混淆。 |

`daily_basic` 中常见字段的含义：`pe`/`pe_ttm` 是市盈率，`pb` 是市净率，`ps`/`ps_ttm` 是市销率，`dv_ratio`/`dv_ttm` 是股息率，`total_mv`/`circ_mv` 是总市值/流通市值，`turnover_rate` 是换手率，`volume_ratio` 是当天成交量相对近期常态的比值。字段单位和口径以 TuShare 当次接口为准；跨接口或跨市场比较前要确认单位。

## 大盘、指数、行业与资金环境

| 表                                | 主要字段                                                                                                                                                                                                                                                    | 用大白话说                                              | 可以帮助回答                                |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- | ------------------------------------- |
| `market_trading_calendar`        | `exchange`、`cal_date`、`is_open`、`pretrade_date`                                                                                                                                                                                                         | 哪天开市、哪天休市，以及前一个交易日。                                | 价格没数据是周末、节假日、停牌，还是采集真的漏了？             |
| `market_index_daily`             | `ts_code`、`trade_date`、`open`、`high`、`low`、`close`、`pre_close`、`change`、`pct_chg`、`vol`、`amount`                                                                                                                                                        | 指数每天的开高低收、涨跌、成交量和成交额。                              | 个股上涨到底是自己强，还是大盘/行业一起涨？                |
| `market_index_daily_basic`       | `ts_code`、`trade_date`、`total_mv`、`float_mv`、`total_share`、`float_share`、`free_share`、`turnover_rate`、`turnover_rate_f`、`pe`、`pe_ttm`、`pb`                                                                                                              | 指数每天的市值、换手和整体估值。                                   | 个股估值变化，是公司自身变化，还是整个板块都在重估？            |
| `market_industry_classification` | `src`、`index_code`、`industry_code`、`industry_name`、`level`、`parent_code`、`is_pub`                                                                                                                                                                       | 行业分类字典。当前默认保存申万 2021 一级行业。                         | “电子”“银行”等行业到底按哪套口径统计，行业指数代码是什么？       |
| `market_index_member`            | `index_code`、`con_code`、`in_date`、`out_date`、`is_new`                                                                                                                                                                                                   | 某行业指数里有哪些成分股，何时进、何时出。                              | 做行业比较时，股票池是否已经变化，是否有幸存者偏差？            |
| `market_index_weight`            | `index_code`、`con_code`、`trade_date`、`weight`                                                                                                                                                                                                           | 指数里每只成分股在某个调仓日占多大权重。                               | 指数表现是不是被少数大权重股票带动？某只股票的相对表现是否受权重变化影响？ |
| `market_daily_info`              | `trade_date`、`ts_code`、`ts_name`、`exchange`、`com_count`、`total_share`、`float_share`、`total_mv`、`float_mv`、`amount`、`vol`、`trans_count`、`pe`、`tr`                                                                                                        | 交易所和市场分组的每日总览，例如上海 A 股、深圳 A 股、ETF 等。               | 今天市场整体成交、估值和活跃度是扩张还是收缩？               |
| `market_moneyflow`               | `trade_date`、`close_sh`、`pct_change_sh`、`close_sz`、`pct_change_sz`、`net_amount`、`net_amount_rate`、`buy_elg_amount`、`buy_elg_amount_rate`、`buy_lg_amount`、`buy_lg_amount_rate`、`buy_md_amount`、`buy_md_amount_rate`、`buy_sm_amount`、`buy_sm_amount_rate` | 全市场不同单量资金的净流入流出。`elg`/`lg`/`md`/`sm` 分别是特大/大/中/小单。 | 个股资金流是逆市场走强，还是整个市场都在放量进攻/撤退？          |
| `market_margin`                  | `trade_date`、`exchange_id`、`rzye`、`rzmre`、`rzche`、`rqye`、`rqmcl`、`rzrqye`、`rqyl`                                                                                                                                                                        | 上交所、深交所和北交所的融资融券余额与当天变化。                           | 市场杠杆是在加还是在减，流动性会不会变脆弱？                |

两融字段可这样理解：`rzye` 是融资余额，`rzmre` 是当天新融资买入，`rzche` 是当天融资偿还；`rqye` 是融券余额，`rqmcl` 是当天融券卖出，`rzrqye` 是融资加融券余额，`rqyl` 是融券余量。

## 原始观察、接口能力与少用数据

| 表 | 主要字段 | 用大白话说 | 可以帮助回答 |
| --- | --- | --- | --- |
| `tushare_research_observation` | `dataset`、`row_hash`、`business_key`、`ts_code`、`event_date`、`available_at`、`payload_json`、`source`、`retrieved_at`、`first_seen_at`、`last_seen_at`、`revision`、`is_current` | 万能原始缓存。`payload_json` 保存接口原样字段；其余字段记录它属于什么数据、何时发生、何时公开、本地第几次见到。 | 回看业绩预告、股东变化、调研、质押、筹码、研报、大宗交易、回购等少用或事件型数据。 |
| `tushare_capability` | `endpoint`、`category`、`status`、`rows_seen`、`details_json`、`checked_at` | 本 Token 对某接口上次测试是否能用、当时看到几行。 | 先判断权限或接口是否可用，不把“没有数据”和“没有权限”混为一谈。 |

目前通用观察表中常见的数据集包括：`daily`、`adj_factor`、`moneyflow`、`margin_detail`、`cyq_chips`、`cyq_perf`、`stk_factor_pro`、`stk_holdernumber`、`stk_holdertrade`、`top10_holders`、`top10_floatholders`、`pledge_stat`、`report_rc`、`forecast`、`express`、`disclosure_date`、`dividend`、`block_trade`、`repurchase` 和 `shibor`。它们不一定每天都有数据，也不一定每次研究都需要读。

## 基准与技术指标：最容易混淆的地方

### 基准不是只能用 CSI 300

模式化采集的默认基准是沪深 300（`000300.SH`），只是一个默认值。使用 `plan` 或 `fetch` 时可用 `--benchmark` 换成当前 Token 可以通过 `index_daily` 和 `index_dailybasic` 获取的任一合适指数代码，包括宽基或行业指数。例如：

```bash
python3 scripts/tushare_mode_data.py fetch medium \
  --symbol 000001.SZ --benchmark 801080.SI \
  --start-date 20260701 --end-date 20260714
```

选什么基准取决于问题：大盘股可先看沪深 300，中小盘可用更匹配的宽基，行业驱动很强的公司可用相应行业指数。基准是为了比较机会成本和市场环境，不是给股票打分。

### 目前技术指标不使用任何基准

`scripts/tushare_mode_data.py indicators --symbol <股票代码>` 只从 `a_share_daily` 读取这只股票自己的 `close_qfq` 和 `volume`。因此下面这些指标都只看个股自身：

| 指标 | 目前使用的数据 | 不会使用的数据 |
| --- | --- | --- |
| MACD、RSI、均线、布林带、收益率、波动率 | 个股前复权收盘价 `close_qfq` | CSI 300 或其他指数。 |
| 量比、量价关系、上涨日成交量占比 | 个股成交量 `volume` 加个股价格 | CSI 300 或其他指数。 |

换句话说，`--benchmark` 会下载并保存比较用的指数数据，但不会改变 MACD、RSI、均线或布林带的计算结果。当前还没有内置“个股相对基准收益”“相对强弱曲线”“Alpha/Beta”或“跑赢行业指数多少”的技术指标；需要这些时，应在明确选定合适基准后再新增派生计算，不能默认拿 CSI 300 代替所有股票的基准。

## 一般怎么选数据

| 你的问题 | 先看什么 |
| --- | --- |
| “这只股票今天为什么涨跌？” | 个股日线、个股资金流、市场广度、市场资金流、基准指数和事件原文。 |
| “现在适不适合做短线？” | 个股价格/成交、涨跌停与停牌、市场两融、市场资金流、相关基准；再看事件风险。 |
| “长期估值贵不贵？” | 个股估值历史、基准指数估值、行业口径、财报和公告原文。 |
| “行业里谁更强？” | 行业分类、行业成分、行业指数、个股和行业价格/估值；不要只比较股票代码列表。 |
| “数据库是不是漏数据？” | 交易日历、最新交易日、主键重复、空值比例和下载时间。 |

数据能提供线索和比较背景，不会自动变成买卖结论。涉及财务事实、重大公司事项或行动判断时，仍按主 Skill 的证据、反证和条件化结论要求处理。

# 技术面、流动性与抗追高

本文件支持两个独立任务：全市场可复现多因子降维，以及长期准入后的候选买点检查。技术面不判断公司是否值得长期持有；阶段和行动以 `research-screening.md` 为唯一真源。

## 目录

- 路由与三种追高
- 长期价格状态与机会成本
- 确定性指标契约
- 行动映射与量化基线

## 路由

### 已有候选或持仓

先完成阶段 L，再使用 `timing-liquidity` 数据判断：

```text
长期准入通过
-> 估值追高
-> 价格追高
-> 叙事追高
-> 流动性与退出能力
-> entry_action 建议
```

### 没有候选池

没有候选并不等于先跑技术面。默认先建立长期基本面研究池：

```text
全市场基础数据
-> 估值、财务质量、增长、资产负债表与历史覆盖
-> long_term_status = not_evaluated
-> 逐只阶段 L
-> 只有 passed 才加载技术/流动性
```

使用 `scripts/fundamental_pool.py`，其输入不包含日线、成交量、动量、均线、回撤或量比。它输出的是待做阶段 L 的研究任务，不是买入列表。

### 明确要求全市场量化降维

只有用户明确要求多因子、量化初筛、动量或技术面筛选时，才运行：

```text
全市场基础层
-> 硬风险门槛
-> 可复现因子基线
-> 行业集中度
-> 研究池
-> 逐只阶段 L
```

筛选结果是研究任务，不是买入列表。已有主题、持仓、公司名单或事件线索时，不重复运行全市场技术筛选。

每个幸存候选都要指定后续研究 profile；默认进入 `long-term-quality + risk-review`，而不是沿用技术排名。

## 三种追高检查

### 估值追高

- 当前 PE/PB/PS/FCF 收益率在自身历史和可比公司中的分位。
- 估值扩张是否有盈利预测、ROIC、利润率或长期价值区间同步上修支持。
- 当前价格隐含的增长和利润率是否超过行业容量与公司历史。
- 催化后市值增加是否显著超过可合理估计的利润或现金流增量。

### 价格追高

- 20/60 日绝对收益及相对行业、市场收益分位。
- 价格相对中期趋势的 ATR/波动率调整偏离。
- 跳空、连续涨停、加速斜率和事件后上涨集中度。
- 成交量、换手率、融资余额、龙虎榜、筹码集中度和大宗交易是否进入极端分位。

### 叙事追高

- 政策、订单、产品或行业传闻是否完成官方核实。
- 是否映射具体 `thesis_id`、财务指标、量级和持续时间。
- 公司是直接受益、间接受益还是概念关联。
- 价格是否已先于证据反映最乐观情景。

相对分位和波动率调整是主要判断。统一固定阈值只能作为数据异常、不可交易或极端风险的宽松兜底，不能替代自身历史和横向比较。

## 长期价格状态与机会成本

“没有追高”不等于“值得买”。阶段 N 对长期候选额外判断价格是否把盈利增长转化为股东回报：

```text
至少 500 个前复权交易日
-> 1/3 年价格与股东总回报
-> 相对市场与行业收益
-> 250 日趋势斜率、效率比、区间占用率
-> 突破失败率与估值倍数变化
-> 盈利/现金流增长、分红贡献和机会成本
-> price_regime + opportunity_cost_flag
```

- 少于 500 个前复权交易日时，`price_regime = insufficient_history`，不得声称长期横盘、上升或下降。
- `range_bound` 只是价格事实。盈利与现金流增长、分红提供回报且估值压缩时可解释为 `range_bound_value_candidate`；盈利或现金流恶化时标为 `range_bound_value_trap_risk`。
- 股东总回报优先使用复权价格；同时展示未复权价格变化与已实施现金分红，避免把价格横盘误写成零回报。
- 机会成本以可配置年化回报门槛和相对基准为依据。若长期回报主要依赖分红而缺少重估催化，要在行动卡中明确。

## 确定性指标契约

可得时由脚本计算，缺失时明确标记：

```text
as_of
close_qfq
valuation_percentile_self
valuation_percentile_peer
return_20d
return_60d
relative_return_market_20d
relative_return_market_60d
relative_return_industry_20d
relative_return_industry_60d
atr_14
atr_deviation
bias_60d
turnover_percentile
volume_ratio_percentile
margin_balance_change
crowding_percentile
max_drawdown
realized_volatility
average_daily_turnover
position_liquidity_days
data_completeness
actual_window
long_history_status
price_regime
price_regime_interpretation
annualized_adjusted_return_long
total_shareholder_return_3y
annualized_total_shareholder_return_3y
cash_dividend_per_share_3y
pe_ttm_change_3y
long_efficiency_ratio
long_range_occupancy_15pct
ma250_annualized_slope
breakout_failure_rate
opportunity_cost_flag
opportunity_cost_reason
overheat_flags[]
data_timestamp
```

- `position_liquidity_days` 需要计划仓位；用户未提供时只报告市场流动性，不伪造仓位容量。
- 自身历史估值不足 3 年时，使用行业分位或较短窗口并标记回退口径。
- 长期价格状态不能回退到 60/120 日窗口；不足 500 个前复权交易日时只能输出历史不足。
- 计算使用前复权价格和同一 `as_of`，避免未来数据。
- `research_workflow.py current-assess` 优先使用显式输入；未提供市场/行业横截面、同行估值或候选价格序列时，会从同一 SQLite 的全市场基础层自动生成。缓存仍不足时保留缺失项并输出 `wait_evidence`，不回退成固定技术筛选。

## 行动映射

| 条件 | 默认建议 |
|---|---|
| 长期通过、赔率合理、不过热、流动性充足 | 可以进入 `staged_buy` 综合判断 |
| 估值或价格进入极端分位，盈利未同步上修 | `wait_price` |
| 事件未核实、量级不可测或关键技术数据缺失 | `wait_evidence` |
| 无法以合理价格建立/退出，或下行风险不可接受 | `avoid` |
| 长期不通过但技术突破 | 仍为 `avoid` |

长期区间震荡且年化股东回报低于门槛时，即使没有过热，也要记录 `opportunity_cost_flag`。它不自动否决公司，但必须进入基准情景、现金比较和替代成本。

触发警示后给出可执行复核条件，例如回到合理估值区间、ATR 偏离消化、成交拥挤回落、盈利预测上修或官方证据补齐。不要只说“等回调”。

## 全市场量化基线

只有明确请求该量化方法时：

```bash
python3 scripts/tushare_sync.py 20250101 20260630 --db-path data/investment_research.sqlite
python3 scripts/tushare_sync.py 20250101 20260630 --db-path data/investment_research.sqlite --daily-basic --fina-indicator --stock-basic
python3 scripts/factor_screen.py \
  --explicit-quantitative-baseline \
  --db-path data/investment_research.sqlite \
  --as-of 20260630 \
  --preset balanced \
  --top 50 \
  --industry-cap 0.25 \
  --output outputs/screens/factor_screen_20260630.csv
```

下载数据留在 SQLite；CSV/XLSX 只作为最终导出或有界增强输入。

自定义筛选规则必须在查看最终标的前登记，并保留默认基线用于比较。可以调整市场风格、行业范围、风险门槛和研究优先级，但不能关闭 ST/退市、关键数据缺失、严重流动性和极端风险门槛，也不能只按近期涨幅排序。

## AI 复核边界

AI 可以解释上涨来源、比较估值与拥挤分位、提出证伪条件、调整研究顺序或建议等待。AI 不得：

- 覆盖确定性硬门槛。
- 编造缺失指标。
- 把趋势延续当作长期价值证据。
- 用技术综合分输出 `staged_buy`。
- 在过热时因“怕错过”取消价格和流动性检查。

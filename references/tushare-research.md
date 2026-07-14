# TuShare 研究数据：按投资模式选取

TuShare 是结构化数据来源和本地缓存工具，不是研究流程控制器。先写出待验证的假设和所需字段，再选择接口。公司和交易所发布的 PDF 定期报告、公告与原始披露是最终财务事实来源；TuShare 的财务相关字段只用于发现披露、建立时间线和提出待阅读问题。

## 常见数据需求

| 研究问题    | 可能需要的数据                   | 先问的问题                   |
| ------- | ------------------------- | ----------------------- |
| 估值与市场背景 | 日线、复权、`daily_basic`、股本、指数 | 用哪个交易日、复权口径和基准？         |
| 经营与财务质量 | 公司/交易所 PDF 三张表、附注与公告；TuShare 字段仅作披露线索 | 用报告期还是披露可得日？如何处理季节性和修订？ |
| 公司风险与治理 | 股东、质押、回购、公告、审计意见等         | 哪些风险会改变核心假设，而非只是背景？     |
| 行业与事件   | 指数、行业指标、公告、宏观数据           | 该指标如何传导至公司收入、成本或估值？     |
| 市场范围比较  | 股票基础信息、行业分类、历史价格和财务数据     | 选择范围是否会系统性遗漏或偏向某类公司？    |

接口权限、覆盖时间和返回口径可能不同。开始前确认 token 权限与数据可得性；无法获取时，改用原始披露或明确降低结论的置信度。

## 本地同步

把 `TUSHARE_TOKEN` 放在环境变量或根目录 `.env`，不要写进命令历史、文档或 Wiki。同步基础数据时可使用：

```bash
python3 scripts/tushare_sync.py 20260101 20260131 \
  --db-path data/investment_research.sqlite \
  --daily-basic --stock-basic
```

查看 `--help` 以确认当前支持的表和参数。仅在需要补充趋势线索时显式加入 `--fina-indicator`；它不提供报告最终数字，也不替代 PDF 财报。选择日期、证券范围和可选表时，以研究问题为准；单股分析通常不需要重新同步整个市场，长期监控也不应因为缺一张表而伪造完整性。

`scripts/market_data_store.py` 提供本地 SQLite 的读写和查询能力。缓存改善可复现性和效率，但不保证 point-in-time 完整性：记录数据的获取时间，重要历史判断仍要区分“报告期结束”“公告可得”和“本次研究使用”的时点。

## 模式化采集

先按 `references/investment-modes.md` 选择持有期，再让 `scripts/tushare_mode_data.py` 生成最小数据包。它只获取研究观察，不计算财务报表、不核验财务数字，也不输出交易指令。

```bash
python3 scripts/tushare_mode_data.py plan long --symbol 000001.SZ --end-date 20260131

python3 scripts/tushare_mode_data.py fetch medium --symbol 000001.SZ \
  --start-date 20250801 --end-date 20260131 --cache

python3 scripts/tushare_mode_data.py fetch short --symbol 000001.SZ \
  --start-date 20260101 --end-date 20260131 --dry-run
```

| 模式 | 默认核心数据 | 可选或权限敏感数据 | 使用边界 |
| --- | --- | --- | --- |
| `long` | `daily`、`adj_factor`、`daily_basic`、`stock_basic`、`dividend` | `share_float`、`top10_holders`、`pledge_stat` | 用于估值历史、资本回报与治理风险线索；财务结论回到 PDF 财报与公告。 |
| `medium` | `daily`、`adj_factor`、`daily_basic`、`moneyflow`、`forecast`、`express`、`disclosure_date` | `margin_detail`、`top_list`、`top_inst`、`stk_factor_pro` | 用于催化窗口、披露时点、预期变化和是否已定价；业绩数字回到正式披露。 |
| `short` | `daily`、`adj_factor`、`daily_basic`、`moneyflow`、`stk_limit`、`limit_list_d`、`top_list` | `top_inst`、`margin_detail`、`suspend_d` | 用于价格、成交、资金、涨跌停和可执行性；纳入 T+1、停牌与隔夜风险。 |

`plan` 默认只展示核心接口。加入 `--include-optional` 才会拉取权限敏感接口；也可以用 `--datasets <key> ...` 精确选择计划中的数据集。`fetch` 强制要求 `--end-date`，确保每次研究有明确 `as_of`；`--dry-run` 不读取 token、不请求网络；`--cache` 将原始行与接口可用性写入 SQLite；`--strict` 让不可用接口返回非零状态。接口无权限、返回为空或时间不匹配时，脚本会保留缺口，不能把缺口解释为不存在。

## 通用接口调用

模式化数据包未覆盖的非标准问题，使用 `scripts/tushare_gateway.py`。先根据待验证的假设选择 endpoint 与最小参数集，再明确执行调用；网关不提供模式选择、财务核验、筛选、排名或投资结论。

```bash
python3 scripts/tushare_gateway.py fetch moneyflow \
  --params '{"ts_code":"000001.SZ","start_date":"20250101","end_date":"20251231"}' \
  --fields 'ts_code,trade_date,net_mf_amount'
```

- `fetch <endpoint>`：调用任意有权限的公开 TuShare endpoint。`--params` 或 `--params-file` 必须是一个 JSON 对象；`--fields` 是可选补充。
- `probe <endpoint>`：用用户提供的小请求检查一个 endpoint 是否可用。它不猜测必填参数，也不尝试全量下载。
- `cache`：读取之前通过 `fetch --cache` 保存的原始行，可按 dataset、证券和时间过滤。
- `--dry-run`：验证 endpoint、参数和缓存设置，但不读取 token、不发起网络请求。

`fetch` 和 `probe` 默认不写入 SQLite。只有明确加 `--cache` 时，才保存数据行或权限检查结果；可用 `--dataset` 给缓存指定清晰名称。输出文件仅支持显式指定的 `.csv` 或 `.json` 路径。

示例：先验证一个小请求，再选择性保存原始结果：

```bash
python3 scripts/tushare_gateway.py probe moneyflow \
  --params '{"ts_code":"000001.SZ","start_date":"20250101","end_date":"20250131"}'

python3 scripts/tushare_gateway.py fetch moneyflow \
  --params-file requests/moneyflow.json \
  --cache --dataset company_moneyflow --output outputs/moneyflow_000001.csv

python3 scripts/tushare_gateway.py cache \
  --dataset company_moneyflow --symbols 000001.SZ --limit 50
```

不要把 `TUSHARE_TOKEN` 放进 `--params`、参数文件、命令输出或缓存。网关使用环境变量或项目根目录 `.env` 中的 token，与 `tushare_sync.py` 保持一致。

用户需要保留 TuShare 小型 CSV/JSON 或下载的财报/公告时，可直接归档到 `raw/<domain>/<subject>/<YYYY-MM-DD>/<内容明确的文件名>`，不需要读取或更新 Wiki。只有用户明确要求跨轮复用或维护研究记忆时，才按 `references/wiki-memory.md` 读取并整合到 `wiki/<domain>/<subject>/<内容页面>.md`。大型或多工作表 Excel 留在外部位置或工作区 `data/`。SQLite 缓存用于机械复现；被启用的 Wiki 才承载跨轮次可复用的研究语义。

## 使用边界

- 把 TuShare 视为标准化二级来源。用于报告最终论证的收入、利润、现金流、资产负债表和关键公司行为，必须引用交易所、巨潮资讯或公司 IR 的 PDF/原文；不要用脚本或 TuShare 复算、核验或替代这些事实。
- 使用 `daily_basic` 的 PE、PB、股息率、市值和股本字段时，记录交易日、复权口径、单位、币种和获取时间。把它们作为市场估值观察，不把它们改写为财报事实。
- 不要从缺失、异常或修订字段反推出积极结论。记录数据缺口及其对假设的影响。
- 同一数据可以支持多种解释。Agent 应解释它为什么与当前问题有关，而不是把接口输出直接转写为评级或行动。

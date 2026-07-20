# TuShare 与本地结构化数据

只在需要使用 TuShare、项目 SQLite 或结构化财务、宏观、行情和跨资产数据时读取。先确定要验证的假设，再按证据的可靠性、可复核性、时间口径和对决策的影响规划数据包；工具开销和获取速度从属于结论质量。需要公司、交易所、监管或政府的原始披露、网页或 PDF 时，读取 `../skills/shared/external-evidence-sources.md`。

## 项目目录与解释器

实际取数、缓存、归档或保存前，先让用户选择项目目录。Skill 安装目录不是项目目录，不能保存数据库、Token、报告、原始资料或 Wiki。

1. 推荐先运行 `<skill-dir>/scripts/ir_project.py init --project-dir <项目目录>`。这会在用户目录下创建 `data/research-library/`、`report/`、`docs/investment-llm-wiki/` 和空 SQLite；仅在项目数据库尚不存在时才能以 `--import-db <源数据库>` 显式导入已有缓存。安装 Skill 本身不会写入用户目录；首次带缓存的模式 `fetch` 也会在选定项目目录下补齐目录并初始化 SQLite，`plan`、`--dry-run` 和 `--no-cache` 不会初始化。
2. 后续命令以该项目目录为工作目录运行；不能切换工作目录时设置 `IR_SKILL_PROJECT_DIR=<项目目录>`。SQLite 默认是 `data/research-library/database/investment_research.sqlite`，`.env` 默认是项目根目录 `.env`。
3. 使用用户已有的 `python3`。`ir_project.py status --project-dir <项目目录>` 会报告实际脚本依赖 `pandas` 是否可用；TuShare 请求由 Skill 自带 HTTP transport 发出，无需安装 `tushare` Python 包。缺包时说明包名并请求安装授权，不创建虚拟环境，也不自动安装。
4. Skill 的网页静态资源仍从 `<skill-dir>/web/dist` 读取，但研究中心、浏览器 API 和所有写操作都以选定项目为根目录。

## 本地数据工具

运行对应脚本的 `--help`、`tushare_research_data.py catalog` 或 `plan` 获取最新参数、字段和数据来源边界。

- `scripts/tushare_research_data.py catalog`：列出已产品化的 TuShare 数据族、endpoint、必填输入、权限敏感度、缓存 dataset 和来源边界。目录覆盖 `financial`、`macro`、`etf`、`fund`、`index`、`futures`、`spot`、`options`、`bond`、`forex`、`hk`、`us`，包括基金经理、指数日度估值、期货席位持仓、可转债发行和可选中债国债收益率曲线。
- `scripts/tushare_research_data.py plan <family> --as-of <YYYYMMDD>`：在不读取 Token、不访问网络的情况下生成与问题范围相称的请求计划。代码相关数据传入 `--symbol`，报告期数据传入 `--period`；可用 `--datasets` 精确选择目录项。期权 `opt_daily` 默认按 `--as-of` 请求交易所全市场快照；中债曲线使用 `--curve-type 0|1` 选择到期或即期曲线。计划可收敛无关请求，但不得遗漏判断所需的数据族、时间段或核验字段。
- `scripts/tushare_research_data.py fetch <family> --as-of <YYYYMMDD>`：默认把响应、权限状态和修订感知观测写入 SQLite。具有公告/实际披露日期的记录会先过滤掉晚于 `as_of` 的信息；没有发布日期字段的 endpoint 会明确标为 `historically_unverified`，不能假装成严格的历史时点数据。仅诊断时使用 `--no-cache`，需要任一 endpoint 不可用即失败时加 `--strict`。
- `scripts/tushare_mode_data.py plan/fetch <long|medium|short>`：规划和获取 A 股持有期数据包。显式设置 `--end-date`、`--benchmark`，用 `--datasets` 选择当前问题所需数据。`fetch` 默认先检查项目 SQLite；对 `daily`、`adj_factor`、`daily_basic`、`moneyflow`、`index_daily`、`stk_limit` 和交易日历，只有本地日期覆盖存在缺口才联网，并将请求收窄到缺失日期区间。完整覆盖时结果状态为 `cached` 且 `network_requests=0`，`--output-dir` 从原始响应缓存重建按日期排序的 CSV；如果 SQLite 仅有规范化计算字段而缺少 CSV 所需的原始接口字段，才会为这些原始字段按日期定向回补。需要重新核验修订或强制刷新时使用 `--refresh`。
- `scripts/tushare_mode_data.py indicators`：从已入库的前复权日线、日内高低价和成交量计算基础指标，不发起网络请求；短期研究优先读取输出中的 `technical_snapshot`，其中按趋势、动量、风险/位置和成交参与组织当前状态与近期变化，并用 `historical_price_structure` 提供本地覆盖区间、全可用历史/1 年/3 年的历史高低点、距高点、最大回撤、年化趋势和路径标签。`a_share_daily` 旧库会自动增加 `high_qfq`、`low_qfq`；尚未重新同步的旧行会明确退回前复权收盘价的极值，不能表述为日内历史高低点。
- `scripts/tushare_sector_data.py catalog/plan/fetch/performance/memberships`：板块专用数据链路。同花顺是默认市场板块口径；`fetch` 将 `ths_index`、`ths_daily`、`moneyflow_ind_ths` 和 `ths_member` 分别写入板块字典、板块日线、板块资金流和成分快照，同时保留通用观察缓存。`performance` 和 `memberships` 只读 SQLite，不访问网络；东财与通达信可作为独立 provider 交叉检查，但代码和涨跌幅不得与同花顺直接混表。
- `scripts/tushare_gateway.py fetch/probe/cache`：处理模式包未覆盖的显式 endpoint、权限小样本检查和原始缓存查询；输出权限、Token、参数、限流和网络失败分类。只对限流和临时网络错误重试。
- `scripts/tushare_sync.py --check-config`：在首次请求、变更项目根目录 `.env` 或切换终端入口后，输出不含 Token 明文的生效来源、配置文件绝对路径和指纹。进程环境中的 `TUSHARE_TOKEN` 优先于项目根目录 `.env`；需要指定其他文件时使用 `--env-file`。
- `scripts/tushare_sync.py`：补齐需要重复比较的全市场基础数据；`fina_indicator` 同步按证券保留成功项，并把单证券失败写为可复核的接口能力记录。
- `scripts/market_data_store.py`：读写和查询本地 SQLite。任意 endpoint 都会保留在 `tushare_research_observation`；板块字典、日线、行业资金流和成分分别规范化到 `market_sector_master`、`market_sector_daily`、`market_sector_flow_daily`、`sector_membership_daily`，其他资金流、涨停事件、筹码、因子、机构调研和公司行为继续进入对应规范化表。原始 payload、获取时间、可得时间和修订版本仍以通用观察缓存为准。

模式数据和通用研究数据都会按 `as_of` 过滤具有公告/交易/调研可得日期的记录；某行日期为空或不可解析时不能视为历史可用，必须剔除并报告数据质量缺口。没有可得日期的接口会标为 `historically_unverified`。板块成分接口若不提供生效交易日，只会以实际抓取日作为快照键，不能倒填为研究 `as_of`。15000 积分套餐不能自动推断包含集合竞价成交或 A 股日线 RT 的独立权限，`stk_mins`、RT 和集合竞价接口必须先单独 probe，失败或空返回要逐 endpoint 报告。

TuShare 是价格、估值、成交、资金、市场状态、披露时间线、标准化财务、宏观和跨资产观察的默认来源。正式财务、治理和重大事项结论按 `../skills/shared/external-evidence-sources.md` 核实原始披露。

## 板块数据与分类口径

板块研究使用双口径，不把分类版本名称误当成数据截止日期：申万 2021 保留为财务、估值和长期同行比较的基本面行业参照；同花顺作为行业涨跌、概念、成交、资金轮动和中短期催化的默认市场板块口径。任何输出都记录 `provider`、板块代码、板块类型、有效交易日和获取时间。

先读本地结果；无数据、过期或覆盖不足时再执行 `plan` 和 `fetch`：

```bash
python3 scripts/tushare_sector_data.py performance --provider ths --sector-type I --as-of 20260719 --sort-by return_5d
python3 scripts/tushare_sector_data.py memberships --provider ths --stock-code 000001.SZ --as-of 20260719
python3 scripts/tushare_sector_data.py plan --provider ths --as-of 20260719
python3 scripts/tushare_sector_data.py fetch --provider ths --start-date 20260601 --as-of 20260719 --datasets master daily flow
python3 scripts/tushare_sector_data.py fetch --provider ths --stock-code 000001.SZ --as-of 20260719 --datasets members
python3 scripts/tushare_sector_data.py fetch --provider ths --sector-code 885001.TI --start-date 20260601 --as-of 20260719 --datasets daily members
```

- 全市场板块横截面不传 `--sector-code`；单日按 `trade_date=as_of` 请求，历史范围为避免接口行数上限静默截断而按工作日拆成逐日横截面请求，交易所休市日可能返回空快照。单板块历史显式传 provider 自己的板块代码和日期范围。
- `performance` 只用同一最新有效交易日形成涨跌与宽度；板块缺少 5/20 个交易日历史或资金流时单独报告覆盖，不填充、不把短历史伪装成长窗口。
- 同花顺 `type=I` 是行业、`N` 是概念；`performance` 默认只查 `I`，避免把地域、宽基、风格和“昨日表现”等特色指数混入行业排行。概念、地域或风格研究显式传对应 provider 类型，并单独解释其定义。
- 同花顺 `type=I` 内仍有多个行业层级。`performance --universe auto` 对 `I` 默认只比较当日 `moneyflow_ind_ths` 覆盖的统一行业集合，避免把三级、四级行业和上级行业混排；需要审阅完整层级时显式传 `--universe all`，并解释层级重叠。
- `memberships` 使用实际抓取日标记没有生效日期的成分快照，不能倒填为研究 `as_of`。个股不在已缓存快照中不等于它不属于任何板块，应先检查板块字典和成分快照覆盖。
- 同花顺、东财、通达信的板块定义和代码空间相互独立。跨 provider 只作方向和广度的交叉验证，不直接合并收益率、排名或成分。

## 三种模式的数据地图

全面表示 Agent 能发现并调用这些能力；每次研究仍围绕假设、持有期和数据缺口选择最小充分集。先查 SQLite，再运行 `plan`，最后定向 `fetch`。`catalog` 和脚本 `--help` 是当前 key、参数和 endpoint 的准确信息源。

| 模式 | 常用基础数据 | 按问题扩展 | 财务与原始披露 |
| --- | --- | --- | --- |
| `long` | 日线/复权、基准、指数估值、交易日历、个股估值、公司信息、分红 | 行业分类、基准权重、解禁、十大股东/流通股东、质押、回购、增减持、大宗交易、名称变化、新股发行 | 用 `financial` family 获取三表、指标、审计意见和主营构成；用定期报告与公告确认最终事实 |
| `medium` | 日线/复权、基准、估值、资金、市场广度、杠杆、业绩预告/快报、披露日历 | 融资明细、龙虎榜、机构席位、因子、券商预期、机构调研、行业资金、板块定义/成分；供给事件可调用 long 的公司行为 key | 先建立 TuShare 财务基线；关键数字、订单和执行状态读取最新原始披露 |
| `short` | 本地技术指标、日线/复权、基准、估值流动性、市场广度、资金、杠杆、涨跌停价、涨停榜、龙虎榜 | 连板、涨停题材、KPL 强势股、同花顺/东财/通达信板块、机构席位、筹码、因子、热度、游资、分钟数据 | 常规短线使用 TuShare 与 SQLite；业绩事件核实事件公告，盈利兑现成为主线时切换 `medium` |

常用定向 key：

- `long`：`share_float`、`major_holders`、`float_holders`、`pledge_risk`、`pledge_detail`、`repurchase`、`holder_trade`、`block_trade`、`name_change`、`new_share`。
- `medium`：`earnings_forecast`、`earnings_express`、`disclosure_calendar`、`broker_expectation`、`institutional_research`、`industry_moneyflow`、`sector_index`、`sector_members`、`stock_factor`、`share_float`、`repurchase`、`holder_trade`、`block_trade`。
- `short`：`limit_list`、`limit_step`、`limit_concept`、`kpl_board`、`kpl_concept`、`kpl_stock_rank`、`top_list`、`institutional_seats`、`moneyflow_ths`、`moneyflow_dc`、`concept_daily`、`concept_members`、`dc_index`/`dc_members`/`dc_daily`、`tdx_index`/`tdx_members`/`tdx_daily`、`chip_distribution`、`chip_performance`、`factor_daily`、`factor_basic`、`hot_board`、`hot_board_detail`、`hot_money`、`hot_money_list`、`minute_price`。

示例：

```bash
python3 scripts/tushare_mode_data.py plan short --symbol 000001.SZ --end-date 20260719 --datasets limit_step moneyflow_ths chip_distribution
python3 scripts/tushare_mode_data.py fetch medium --symbol 000001.SZ --end-date 20260719 --datasets earnings_forecast institutional_research industry_moneyflow
python3 scripts/tushare_research_data.py plan financial --symbol 000001.SZ --period 20260331 --as-of 20260719
```

## 中期财务基线

对 3–6 个月个股推荐或候选排序，先建立不含未来信息的结构化财务基线，再使用市场数据决定价格条件：

1. 按研究 `as_of` 选择报告期，先运行 `tushare_research_data.py plan financial --period <YYYYMMDD> --as-of <YYYYMMDD>`，再以相同参数 `fetch` 全市场 VIP 三表与指标。输出会按 `ann_date`/实际公告日过滤未来记录并保存权限状态；Token、权限、参数、空结果、限流和网络错误必须按脚本输出分类处理，不得笼统称为接口不可用。
2. 个股需要业绩预告、快报、分红、披露日、审计意见或主营构成时，在同一请求加 `--symbol <ts_code>`。审计意见和主营构成的 `--period` 是可选过滤条件，年报/半年报之外为空时应改为请求历史，不得将其当作接口故障。使用 `disclosure_date` 确认该报告期在研究时点是否实际可得；不能把预计披露日当作已知财报事实。
3. 只有数据将作为最终财务事实、出现异常或冲突、需要正式引文，或必须确认单位、币种、合并范围、审计意见细节时，才按 `../skills/shared/external-evidence-sources.md` 使用 `research_collect.py collect-report`。该命令先查询项目资料库并以 `reused` 返回已有原件，只下载缺失的公司/报告期；仅在分类后的 CNInfo 查询仍无法解析来源时才使用浏览器定位。标准化值与原文冲突时保留冲突，以原文为最终事实来源。

## 财报、宏观与跨资产路由

| 研究需要 | 默认数据族 | 典型输入 | 原始来源回退条件 |
| --- | --- | --- | --- |
| 同一报告期全市场筛选 | `financial` | `--period 20260331 --as-of 20260718` | 正式引用、口径确认、异常或冲突 |
| 单公司财务事件与业务构成 | `financial` | 加 `--symbol 601088.SH` | 审计/分红/披露细节进入正式结论 |
| 中国宏观及利率 | `macro` | 可选 `--macro-period 202606`；曲线加 `--datasets yc_cb --curve-type 0` | 严格历史发布日期、统计定义、曲线权限或修订确认 |
| ETF/基金/指数/期货/期权/债券/外汇/港美股 | 相应资产族 | 代码相关数据加 `--symbol`；期权日线可仅传 `--as-of` | 币种、复权、合约或市场规则需要确认 |
| 港股/美股单公司财报 | `hk` 或 `us` | `--symbol`、`--include-optional`；已知报告期再加 `--period` | 正式引用、口径确认、异常或冲突 |

```bash
python3 scripts/tushare_research_data.py fetch financial --period 20260331 --as-of 20260718
python3 scripts/tushare_research_data.py fetch financial --symbol 601088.SH --period 20260331 --as-of 20260718
python3 scripts/tushare_research_data.py fetch macro --as-of 20260718 --datasets cn_gdp cn_cpi cn_m
python3 scripts/tushare_research_data.py fetch fund --symbol 110011.OF --as-of 20260718 --datasets fund_manager
python3 scripts/tushare_research_data.py fetch futures --symbol IF --exchange CFFEX --as-of 20260718 --datasets fut_holding
python3 scripts/tushare_research_data.py fetch options --as-of 20260718 --datasets opt_daily
python3 scripts/tushare_research_data.py fetch bond --as-of 20260718 --datasets cb_issue
```

## 持久化与质量检查

- 用于计算、筛选、排名、回测、历史比较或后续复用的结构化数据，先写入 SQLite；一次性事实核验和少量即时行情可以不入库。
- `fetch` 默认缓存原始响应和接口状态。研究中不要使用 `--no-cache`；`--dry-run` 只验证计划，不请求也不写入数据。
- 入库失败、接口空返回、无权限或日期缺口必须作为数据缺口报告；不要把临时输出当成已缓存数据。
- 使用前按问题检查证券代码映射、主键重复、日期连续性、空值、异常值、复权、停牌、单位、币种和最新可用日期。
- 记录数据库路径、使用表或 dataset、行数、`retrieved_at` 和最新日期，保证结果可复现。
- 不用填充、删除或均值替代掩盖异常；先定位来源、定义、修订或时间口径。

## 凭据安全

把 `TUSHARE_TOKEN` 保留在进程环境或项目根目录 `.env`，不写入参数文件、报告、缓存、Wiki 或终端输出。运行 `tushare_sync.py --check-config` 仅确认生效来源、配置路径和指纹，不显示 Token 明文。

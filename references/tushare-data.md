# TuShare 与本地结构化数据

只在需要使用 TuShare、项目 SQLite 或结构化财务、宏观、行情和跨资产数据时读取。先确定要验证的假设，再按证据的可靠性、可复核性、时间口径和对决策的影响规划数据包；工具开销和获取速度从属于结论质量。需要公司、交易所、监管或政府的原始披露、网页或 PDF 时，读取 `external-evidence-sources.md`。

## 项目目录与解释器

实际取数、缓存、归档或保存前，先让用户选择项目目录。Skill 安装目录不是项目目录，不能保存数据库、Token、报告、原始资料或 Wiki。

1. 运行 `<skill-dir>/scripts/ir_project.py init --project-dir <项目目录>`。这会在用户目录下创建 `data/research-library/`、`report/`、`docs/investment-llm-wiki/` 和空 SQLite；仅在项目数据库尚不存在时才能以 `--import-db <源数据库>` 显式导入已有缓存。
2. 后续命令以该项目目录为工作目录运行；不能切换工作目录时设置 `IR_SKILL_PROJECT_DIR=<项目目录>`。SQLite 默认是 `data/research-library/database/investment_research.sqlite`，`.env` 默认是项目根目录 `.env`。
3. 使用用户已有的 `python3`。`ir_project.py status --project-dir <项目目录>` 会报告实际脚本依赖 `pandas` 是否可用；TuShare 请求由 Skill 自带 HTTP transport 发出，无需安装 `tushare` Python 包。缺包时说明包名并请求安装授权，不创建虚拟环境，也不自动安装。
4. Skill 的网页静态资源仍从 `<skill-dir>/web/dist` 读取，但研究中心、浏览器 API 和所有写操作都以选定项目为根目录。

## 本地数据工具

运行对应脚本的 `--help`、`tushare_research_data.py catalog` 或 `plan` 获取最新参数、字段和数据来源边界。

- `scripts/tushare_research_data.py catalog`：列出已产品化的 TuShare 数据族、endpoint、必填输入、权限敏感度、缓存 dataset 和来源边界。目录覆盖 `financial`、`macro`、`etf`、`fund`、`index`、`futures`、`spot`、`options`、`bond`、`forex`、`hk`、`us`，包括基金经理、指数日度估值、期货席位持仓、可转债发行和可选中债国债收益率曲线。
- `scripts/tushare_research_data.py plan <family> --as-of <YYYYMMDD>`：在不读取 Token、不访问网络的情况下生成与问题范围相称的请求计划。代码相关数据传入 `--symbol`，报告期数据传入 `--period`；可用 `--datasets` 精确选择目录项。期权 `opt_daily` 默认按 `--as-of` 请求交易所全市场快照；中债曲线使用 `--curve-type 0|1` 选择到期或即期曲线。计划可收敛无关请求，但不得遗漏判断所需的数据族、时间段或核验字段。
- `scripts/tushare_research_data.py fetch <family> --as-of <YYYYMMDD>`：默认把响应、权限状态和修订感知观测写入 SQLite。具有公告/实际披露日期的记录会先过滤掉晚于 `as_of` 的信息；没有发布日期字段的 endpoint 会明确标为 `historically_unverified`，不能假装成严格的历史时点数据。仅诊断时使用 `--no-cache`，需要任一 endpoint 不可用即失败时加 `--strict`。
- `scripts/tushare_mode_data.py plan/fetch <long|medium|short>`：按持有期规划和获取与问题相称的 A 股市场数据包；显式设置 `--end-date` 和合适的 `--benchmark`。
- `scripts/tushare_mode_data.py indicators`：从已入库的前复权日线和成交量计算基础指标，不发起网络请求；短期研究优先读取输出中的 `technical_snapshot`，其中按趋势、动量、风险/位置和成交参与组织当前状态与近期变化。
- `scripts/tushare_gateway.py fetch/probe/cache`：处理模式包未覆盖的显式 endpoint、权限小样本检查和原始缓存查询；输出权限、Token、参数、限流和网络失败分类。只对限流和临时网络错误重试。
- `scripts/tushare_sync.py --check-config`：在首次请求、变更项目根目录 `.env` 或切换终端入口后，输出不含 Token 明文的生效来源、配置文件绝对路径和指纹。进程环境中的 `TUSHARE_TOKEN` 优先于项目根目录 `.env`；需要指定其他文件时使用 `--env-file`。
- `scripts/tushare_sync.py`：补齐需要重复比较的全市场基础数据；`fina_indicator` 同步按证券保留成功项，并把单证券失败写为可复核的接口能力记录。
- `scripts/market_data_store.py`：读写和查询本地 SQLite。

TuShare 是价格、估值、成交、资金、市场状态、披露时间线、标准化财务、宏观和跨资产观察的默认来源。报告中作为最终事实使用的收入、利润、现金流、资产负债表、审计意见、治理和重大事项，仍需按 `external-evidence-sources.md` 的来源边界核验原始披露。

## 中期财务基线

对 3–6 个月个股推荐或候选排序，先建立不含未来信息的结构化财务基线，再使用市场数据决定价格条件：

1. 按研究 `as_of` 选择报告期，先运行 `tushare_research_data.py plan financial --period <YYYYMMDD> --as-of <YYYYMMDD>`，再以相同参数 `fetch` 全市场 VIP 三表与指标。输出会按 `ann_date`/实际公告日过滤未来记录并保存权限状态；Token、权限、参数、空结果、限流和网络错误必须按脚本输出分类处理，不得笼统称为接口不可用。
2. 个股需要业绩预告、快报、分红、披露日、审计意见或主营构成时，在同一请求加 `--symbol <ts_code>`。审计意见和主营构成的 `--period` 是可选过滤条件，年报/半年报之外为空时应改为请求历史，不得将其当作接口故障。使用 `disclosure_date` 确认该报告期在研究时点是否实际可得；不能把预计披露日当作已知财报事实。
3. 只有数据将作为最终财务事实、出现异常或冲突、需要正式引文，或必须确认单位、币种、合并范围、审计意见细节时，才按 `external-evidence-sources.md` 使用 `research_collect.py collect-report` 或浏览器定位公司、交易所或 CNInfo 原件。标准化值与原文冲突时保留冲突，以原文为最终事实来源。

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

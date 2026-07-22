# 项目与结构化数据

只在初始化项目、使用缓存/SQLite、配置 `.env`、同步数据或保存用户研究资产时读取。

## 1. 项目边界

- 用户数据必须属于明确选择的项目目录；Skill 安装目录只保存脚本、规则、reference 和静态资源。
- 首次使用 `scripts/ir_project.py init --project-dir <项目目录>` 初始化 `data/research-library/`、`report/`、`docs/investment-llm-wiki/` 和 SQLite。只有新库为空时才可用 `--import-db` 显式迁移已有缓存。
- 使用用户现有 `python3`；`ir_project.py status` 检查 `pandas`。TuShare 使用 Skill 自带 HTTP transport，不自动创建虚拟环境或安装依赖。
- 后续命令以项目目录为工作目录；不能切换时设置 `IR_SKILL_PROJECT_DIR=<项目目录>`。项目根 `.env` 是默认配置，进程环境优先。
- 不复制数据库、`.env`、报告、原始资料或 Wiki 到 Skill 安装目录。

## 2. 数据操作

运行任何数据脚本前先执行对应 `--help`；脚本负责下载、缓存、查询和指标计算，Agent 负责选择证据、检查口径并形成判断。详细 endpoint、字段、缓存与历史可得性规则统一见 [`../../references/tushare-data.md`](../../references/tushare-data.md)。

- `tushare_research_data.py`：跨资产、宏观和结构化财务数据，先 `catalog` 或 `plan`，所有 `fetch` 显式传入 `--as-of`。
- `tushare_mode_data.py`：按 long/medium/short 获取 A 股持有期数据包；短线个股读取 `indicators` 的 `technical_snapshot` 和 `historical_price_structure`。
- `short_term_screen.py`：全市场短线股票池、驱动诊断、历史回放和风险预算仓位；只读取本地 SQLite。
- `tushare_sector_data.py`：板块字典、日线、资金流、成分及 `performance`、`rotation`、`memberships`；申万 2021 与同花顺/东财/通达信口径不得混用。
- `tushare_gateway.py`、`tushare_sync.py` 与 `market_data_store.py`：补充显式 endpoint、同步与查询本地市场数据；首次请求或切换项目入口前运行 `tushare_sync.py --check-config`。

数据缺失、过期、空结果、无权限、日期/口径错误或入库失败必须作为证据缺口报告；不以临时输出冒充已缓存数据，也不以填充掩盖异常。

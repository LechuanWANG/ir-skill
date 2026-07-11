# Local Investment Research Skill

本仓库是一个面向股票研究、A 股筛选、组合复盘和本地投资知识库维护的 Codex skill。它把 AI 拉回到可验证、可复现、可沉淀的投研工作流：先判断公司未来 3–5 年是否值得持有，再用近期事件、宏观、行业、估值、技术面和组合约束判断现在能不能买，最后给出条件化行动和下一验证日期。

> 本 skill 只用于投资研究辅助，不构成金融建议，也不是自动交易指令。

## 它解决什么问题

很多 AI 投资分析容易出现几个实际问题：

1. **长期价值和当前买点混在一起**
   “好公司”不等于“现在可以买”。本 skill 分别输出长期准入、当前买点和已有持仓动作，不用一个综合分或单一操作掩盖差异。

2. **取数路径僵化**
   每次默认跑同一套技术或因子脚本，无法根据长期质量、盈利拐点、事件驱动、行业信号和风险审查选择不同证据。

3. **容易追高**  
   纯动量和热门事件会天然偏向近期涨幅最大的标的。本 skill 分别检查估值追高、价格追高和叙事追高，用相对分位、ATR/趋势偏离、拥挤与事件验证避免把“涨得多”误当成“值得买”。

4. **数据口径混乱**  
   市值、PE、PB、EPS、股本单位、币种和公告期经常混在一起。本 skill 要求关键数据标明来源、时间、单位、币种，并用脚本做机械复算。

5. **深度研究缺少准入门和对抗视角**
   单一视角容易只证明自己想证明的东西。深度模式先由研究委员会裁定长期准入，再加载近期证据，并经过两轮点名质询后由 PM 独立裁决。

6. **研究结果无法长期复用**  
   很多结论停留在一次对话里。本 skill 设计了 Investment LLM Wiki 记忆协议，把持久事实、投资假设、决策记录、矛盾证据沉淀到本地知识库。

## 核心亮点

- **长期优先双阶段状态机**：`research-screening.md` 统一定义阶段 L/N、决策矩阵和不可绕过校验。
- **四个状态字段**：分别输出 `research_status`、`long_term_status`、`entry_action` 和 `portfolio_action`，不混合研究完成度、公司质量、当前价格与已有持仓动作。
- **四类当前行动**：明确 `staged_buy / wait_price / wait_evidence / avoid`，允许长期看好但选择等待。
- **决策备忘录优先**：默认输出一屏内的结论、长期准入、当前行动、价格/等待条件、最大风险、时间戳和下一验证日期。
- **路由式参考资料加载**：根据用户意图只读取必要 reference，例如单股研究、A 股筛选、组合复盘、价格异动归因、Wiki 导入和深度研究各有不同路径。
- **本地 SQLite 数据底座**：使用 `data/investment_research.sqlite` 存储可复用市场数据，避免每次运行产生临时 CSV 缓存。
- **Point-in-time 修订记录**：TuShare 异构观察保留 `business_key`、版本、首次/最后可见时间；历史研究只读取当时已知的最新版本，避免后续修订倒灌。
- **TuShare 研究计划器**：先取 `long-term-quality + risk-review` 长期证据，再按需追加事件、行业、宏观与最后的 `timing-liquidity`。
- **能力感知与降级**：先用 `doctor` 记录当前 token 可用接口，再用 `staged-plan` 强制生成长期优先的最小数据包；缺权限时明确替代来源。
- **默认长期基本面研究池**：`scripts/fundamental_pool.py` 先用估值、财务质量、增长和资产负债表生成待研究对象；历史覆盖只决定数据准备度，多年经营稳定性才进入耐久分，并按新发现、核心更新和 challenger 分配名额。
- **三种运行模式**：`discovery` 建研究队列，`refresh` 只写增量变化，`decision` 对少量对象完成双阶段裁定并给现金比较与最接近买入对象。
- **缺口物质性分层**：流程缺口保持研究未完成；只有可能改变长期状态、回报门槛或下行情景的 `blocking_evidence` 才生成 `wait_evidence`。
- **显式量化基线**：`scripts/factor_screen.py` 只在明确要求多因子/技术量化时运行，通过硬门槛、趋势、价值、质量、成长、风险惩罚和行业集中度控制生成研究池。
- **事件信号而非新闻选股**：`news_intake` 按需生成去重、核实、假设映射的信号卡，新闻热度不能提高长期评价。
- **显式抗追高机制**：分别检查估值、价格和叙事追高；相对分位与波动率调整优先，不允许纯动量排序直接变成候选结论。
- **财务数字机械复核**：`scripts/financial_check.py` 用于复算市值、PE、PB、股息率等，降低单位、币种和股本口径错误。
- **两阶段研究委员会**：先裁定长期准入，再评估当前买点；Round 1 点名最薄弱主张，Round 2 补证据、收窄或下调置信度。
- **20/60/120 日闭环**：同时评估买入、等价格、等证据和回避，分开衡量长期研究、买点与风险控制质量。
- **本地投资记忆**：通过 `references/wiki-memory.md` 约定分析前召回、分析后写回、Wiki 链接和矛盾记录。
- **输出模板完整**：内置长期账本、买入条件卡、快速备忘录、深度报告、四桶名单和 LaTeX/PDF QA 要求。

## 适合的场景

- 分析一只股票是否值得买入、加仓、减仓或继续等待。
- 对 A 股市场建立长期基本面研究池，或在明确要求时做可复现的多因子初筛。
- 把筛选短名单进一步升级为一流公司深度研究。
- 解释某只股票、行业或组合近期价格异动。
- 复盘当前持仓、仓位集中度、机会成本和风险暴露。
- 把报告、笔记、投资假设和历史决策写入本地 Investment LLM Wiki。

## 仓库结构

```text
.
├── SKILL.md                         # skill 入口、路由规则和运行原则
├── agents/openai.yaml               # Codex skill 展示与默认提示
├── assets/                          # 快速备忘录、深度报告、决策记录模板
├── references/                      # 双阶段状态机、证据模块、输出契约、评估和 Wiki 说明
└── scripts/                         # 可复现数据、筛选、校验和 Wiki lint 脚本
```

主要脚本：

| 脚本 | 用途 |
|---|---|
| `scripts/market_data_store.py` | 创建和读写本地 SQLite 市场数据表 |
| `scripts/tushare_sync.py` | 从 TuShare 同步 A 股价格、复权、估值、财务指标和股票基础信息 |
| `scripts/tushare_research.py` | 探测权限，使用 `staged-plan` 规划长期优先数据包，按 profile 采集证据并查询缓存 |
| `scripts/research_workflow.py` | 执行长期优先研究状态机、证据/假设记录、阶段裁定、四桶报告和结果评估 |
| `scripts/research_store.py` | 迁移研究数据库并查询 assessment、claim 和 outcome 审计记录 |
| `scripts/news_intake.py` | 按需抓取/导入、去重和查询事件信号，并映射到版本化投资假设 |
| `scripts/fundamental_pool.py` | 默认建立长期基本面研究池，并标记阶段 L 所需证据 |
| `scripts/technical_screen.py` | 对阶段 L 候选计算反追高、三年价格状态、股东总回报、估值变化和机会成本 |
| `scripts/factor_screen.py` | 仅在明确要求时生成技术/多因子量化研究池 |
| `scripts/financial_check.py` | 复算市值和估值指标 |
| `scripts/wiki_index.py` | 检查 Investment LLM Wiki 坏链、frontmatter 和来源字段 |

## 快速开始

把本仓库作为 Codex skill 安装或放入你的 skills 目录后，可以直接这样调用：

```text
Use $local-investment-research to analyze 300308.SZ.
Use $local-investment-research to screen A-shares for long-term research candidates.
Use $local-investment-research to run an explicit balanced multi-factor A-share baseline.
Use $local-investment-research to review my current portfolio and update the local wiki.
```

如果需要同步 TuShare 数据，把 token 放在项目根目录 `.env` 的 `TUSHARE_TOKEN`；环境变量中的同名值优先。脚本会自动加载，不需要把 token 写进命令或文档。

```bash
python3 scripts/tushare_sync.py 20260101 20260131 --db-path data/investment_research.sqlite --daily-basic --fina-indicator --stock-basic

python3 scripts/fundamental_pool.py \
  --db-path data/investment_research.sqlite \
  --as-of 20260131 \
  --top 30 \
  --output outputs/screens/fundamental_pool_20260131.csv
```

先检查当前接口能力，再生成阶段 L 的长期数据计划：

```bash
python3 scripts/tushare_research.py doctor \
  --as-of 20260710 \
  --endpoints daily_basic income balancesheet cashflow report_rc stk_surv pledge_stat moneyflow

python3 scripts/research_workflow.py staged-plan \
  --symbols 000001.SZ \
  --as-of 20260710 \
  --current-profile market-context timing-liquidity
```

`scripts/tushare_research.py staged-plan` 提供等价的数据规划入口。裸 `plan` 只用于明确的单一 profile 诊断，不作为默认研究入口。确认计划后，对候选股定向采集长期证据：

```bash
python3 scripts/tushare_research.py collect \
  --profile long-term-quality risk-review \
  --symbols 000001.SZ \
  --as-of 20260710
```

裁定 `long_term_status` 后，再按问题追加 `event-driven / industry-signal / market-context`，最后使用 `timing-liquidity`。事件线索先通过 `scripts/news_intake.py` 核实，不能直接进入买入结论。

初始化并检查可审计研究存储：

```bash
python3 scripts/research_store.py migrate
python3 scripts/research_store.py stats
```

按需抓取结构化事件信号；`fetch` 需要本机可用的 Webclaw，离线输入先 `parse` 再 `ingest`：

```bash
python3 scripts/news_intake.py fetch --since-hours 72
python3 scripts/news_intake.py parse --input authorized_webclaw.json --since-hours 72
python3 scripts/news_intake.py ingest --input authorized_webclaw.json --since-hours 72
python3 scripts/news_intake.py query --important-only
```

研究运行、长期/当前裁定、四桶输出和 20/60/120 日评估统一从 `scripts/research_workflow.py` 进入；用 `--help` 查看各子命令必需字段：

```bash
python3 scripts/research_workflow.py --help
python3 scripts/research_workflow.py snapshot-import \
  --db-path data/investment_research.sqlite \
  --input outputs/reports/example/data/decision_snapshot.json
python3 scripts/research_workflow.py report \
  --format md \
  --output outputs/reports/decision_buckets.md
python3 scripts/research_workflow.py outcomes-summary
```

生成多因子短名单：

```bash
python3 scripts/factor_screen.py \
  --db-path data/investment_research.sqlite \
  --as-of 20260630 \
  --preset balanced \
  --top 50 \
  --output outputs/screens/a_share_factor_screen_20260630.csv
```

复算市值：

```bash
python3 scripts/financial_check.py verify-market-cap \
  --price 10 \
  --shares 100000000 \
  --reported 1000000000 \
  --currency CNY
```

检查本地 Wiki：

```bash
python3 scripts/wiki_index.py --wiki-dir docs/investment-llm-wiki
```

## 输出风格

快速研究默认输出：

```text
【运行模式】discovery / refresh / decision
【结论】今天最优行动、现金比较、最接近买入对象
【研究状态】queued / in_progress / decision_ready / stale
【长期准入】passed / needs_evidence / rejected
【当前行动】staged_buy / wait_price / wait_evidence / avoid
【持仓行动】not_applicable / add / hold / reduce / exit
【防追高】估值 / 价格 / 叙事
【价格或等待条件】区间 + 重新评估触发器
【最大风险 / 证伪】什么情况说明判断错了
【缺口分层】阻断项 / 置信度限制项 / 持续监测项 / 流程缺口
【长期价格状态】三年股东总回报、估值变化与机会成本
【相对上次】结论差异、新事实或方法重置
【下一步】验证日期、深研、Wiki 与 evaluation
```

深度研究会进一步包含：

- 长期投资假设账本和 3–5 年收益来源。
- 当前事件、宏观、行业、三情景、技术与组合约束。
- 估值、价格和叙事三类追高检查。
- 至少 500 个前复权交易日支持的长期价格状态、股东总回报和机会成本。
- 两轮质询、置信度变化和保留分歧。
- 投资与买入条件卡、数据附录和 20/60/120 日写回计划。

## 设计原则

1. **先长期准入，后当前买点**：长期不通过时，不因催化或技术突破破例。
2. **先假设，后取数**：先明确研究问题，再由脚本生成最小充分数据包。
3. **先核实事件，后讨论影响**：新闻只发现线索，原始来源和量级决定是否进入结论。
4. **先核对，后确信**：关键财务数字不能只依赖单一标准化数据源。
5. **先意图路由，后短名单**：因子模型只在需要全市场降维时使用，不直接给买卖结论。
6. **先检查追高，后决定节奏**：长期看好也可以明确 `wait_price`。
7. **先保存快照，后复盘结果**：保留所有四类行动，区分过程质量和结果运气。
8. **先记录矛盾，后更新结论**：新证据和旧结论冲突时，保留矛盾而不是覆盖历史。

## 数据与隐私

- 默认数据文件为 `data/investment_research.sqlite`，用于本地复用市场数据。
- `TUSHARE_TOKEN` 保存在环境变量或已被 `.gitignore` 忽略的项目 `.env`，不要写进代码、文档、日志或 Wiki。
- 持仓、资金、偏好等敏感信息默认保存在本地 Wiki；写入前应获得用户确认。
- 原始数据和报告产物建议保留在本地工作区，按需导出最终 CSV/XLSX/PDF。

## 免责声明

本项目只提供研究流程、数据处理和决策辅助框架。任何输出都不应被理解为投资建议、收益承诺、交易指令或风险豁免。使用者需要自行核验数据、判断适当性，并承担最终投资决策责任。

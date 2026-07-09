# Local Investment Research Skill

本仓库是一个面向股票研究、A 股筛选、组合复盘和本地投资知识库维护的 Codex skill。它的目标不是生成一篇看起来完整的研究文章，而是把 AI 拉回到可验证、可复现、可沉淀的投资研究工作流里：先给行动建议，再说明证据、风险、数据来源和下一步验证。

> 本 skill 只用于投资研究辅助，不构成金融建议，也不是自动交易指令。

## 它解决什么问题

很多 AI 投资分析容易出现几个实际问题：

1. **结论像文章，不像决策**  
   输出信息很多，但没有明确的买、等、加、减、卖、不碰，也没有置信度、证伪条件和组合影响。

2. **筛选不可复现**  
   只凭叙述或临时规则挑股票，下一次很难复盘为什么某只股票入选、为什么某只股票被淘汰。

3. **容易追高**  
   纯动量筛选会天然偏向近期涨幅最大的标的。本 skill 把估值分位、过热惩罚、回撤和流动性门槛写进筛选流程，避免把“涨得多”误当成“值得买”。

4. **数据口径混乱**  
   市值、PE、PB、EPS、股本单位、币种和公告期经常混在一起。本 skill 要求关键数据标明来源、时间、单位、币种，并用脚本做机械复算。

5. **深度研究缺少对抗视角**  
   单一视角容易只证明自己想证明的东西。深度模式要求从公司质量、行业宏观、估值风控、组合影响等视角显式列出分歧。

6. **研究结果无法长期复用**  
   很多结论停留在一次对话里。本 skill 设计了 Investment LLM Wiki 记忆协议，把持久事实、投资假设、决策记录、矛盾证据沉淀到本地知识库。

## 核心亮点

- **决策备忘录优先**：默认输出一屏内的结论、操作、置信度、理由、最大风险、数据时间戳和下一步，而不是泛泛长文。
- **路由式参考资料加载**：根据用户意图只读取必要 reference，例如单股研究、A 股筛选、组合复盘、价格异动归因、Wiki 导入和深度研究各有不同路径。
- **本地 SQLite 数据底座**：使用 `data/investment_research.sqlite` 存储可复用市场数据，避免每次运行产生临时 CSV 缓存。
- **TuShare 同步脚本**：`scripts/tushare_sync.py` 支持同步 A 股价格、成交量、复权因子、daily_basic、fina_indicator 和 stock_basic。
- **确定性多因子筛选**：`scripts/factor_screen.py` 通过硬门槛、趋势、价值、质量、成长、风险惩罚、行业集中度控制生成短名单。
- **显式抗追高机制**：内置过热硬阈、估值分位惩罚、回撤惩罚和 `追涨风险` 标记，不允许纯动量排序直接变成候选结论。
- **财务数字机械复核**：`scripts/financial_check.py` 用于复算市值、PE、PB、股息率等，降低单位、币种和股本口径错误。
- **深度研究模式**：重大决策或单股深挖时，按四视角进行看多、看空、估值、组合影响和证伪条件梳理。
- **本地投资记忆**：通过 `references/wiki-memory.md` 约定分析前召回、分析后写回、Wiki 链接和矛盾记录。
- **输出模板完整**：内置快速备忘录、深度报告、筛选输出、报告产物目录和 LaTeX/PDF QA 要求。

## 适合的场景

- 分析一只股票是否值得买入、加仓、减仓或继续等待。
- 对 A 股市场做可复现的多因子初筛。
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
├── references/                      # 分析框架、数据源、因子模型、Wiki 记忆等说明
└── scripts/                         # 可复现数据、筛选、校验和 Wiki lint 脚本
```

主要脚本：

| 脚本 | 用途 |
|---|---|
| `scripts/market_data_store.py` | 创建和读写本地 SQLite 市场数据表 |
| `scripts/tushare_sync.py` | 从 TuShare 同步 A 股价格、复权、估值、财务指标和股票基础信息 |
| `scripts/technical_screen.py` | 计算技术面指标、收益率、回撤、Sharpe、量比等 |
| `scripts/factor_screen.py` | 生成确定性多因子 A 股短名单 |
| `scripts/financial_check.py` | 复算市值和估值指标 |
| `scripts/wiki_index.py` | 检查 Investment LLM Wiki 坏链、frontmatter 和来源字段 |

## 快速开始

把本仓库作为 Codex skill 安装或放入你的 skills 目录后，可以直接这样调用：

```text
Use $local-investment-research to analyze 300308.SZ.
Use $local-investment-research to screen A-shares with the balanced preset.
Use $local-investment-research to review my current portfolio and update the local wiki.
```

如果需要同步 TuShare 数据，先在环境变量中提供 token：

```bash
export TUSHARE_TOKEN="your_token"
python3 scripts/tushare_sync.py 20260101 20260131 --db-path data/investment_research.sqlite --daily-basic --fina-indicator --stock-basic
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
【结论】现在该做什么
【操作】买 / 等 / 加 / 减 / 卖 / 不碰     【置信度】高 / 中 / 低
【为什么】1-2 句关键逻辑
【最大风险 / 证伪】什么情况说明判断错了
【数据】关键数字 + 来源 + 取数时间
【下一步】是否需要深度模式；是否写回 Wiki
```

深度研究会进一步包含：

- 看多和看空证据。
- 生意质量、行业周期、估值判断和组合影响。
- 四视角分歧点。
- 买入前验证条件。
- 数据附录和 Wiki 写回计划。

## 设计原则

1. **先决策，后解释**：输出必须服务于行动和风险控制。
2. **先脚本，后判断**：抓取、筛选、估值复算等机械工作由脚本完成。
3. **先核对，后确信**：关键财务数字不能只依赖单一标准化数据源。
4. **先短名单，后深研**：因子模型只负责缩小范围，不直接给买卖结论。
5. **先记录矛盾，后更新结论**：新证据和旧结论冲突时，保留矛盾而不是覆盖历史。

## 数据与隐私

- 默认数据文件为 `data/investment_research.sqlite`，用于本地复用市场数据。
- `TUSHARE_TOKEN` 必须来自环境变量，不要写进代码或文档。
- 持仓、资金、偏好等敏感信息默认保存在本地 Wiki；写入前应获得用户确认。
- 原始数据和报告产物建议保留在本地工作区，按需导出最终 CSV/XLSX/PDF。

## 免责声明

本项目只提供研究流程、数据处理和决策辅助框架。任何输出都不应被理解为投资建议、收益承诺、交易指令或风险豁免。使用者需要自行核验数据、判断适当性，并承担最终投资决策责任。

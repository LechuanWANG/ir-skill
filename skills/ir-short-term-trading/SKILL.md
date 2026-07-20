---
name: ir-short-term-trading
description: Evidence-led short-term trading research for one-month events, technical analysis, momentum, factor screens, entries, price dislocations, and price-led 1-3 month decisions.
---

# 短期事件与交易研究

用于一个月内以技术指标为主要筛选入口的短期交易、事件/宏观验证、动量、因子筛选、入场节奏和价格异动，以及以价格和事件执行为主的 1–3 个月问题。先读取共享的研究纪律与项目边界：[`../shared/research-discipline.md`](../shared/research-discipline.md)。

## 共享支持材料

- 用户需要仓位、入场、止损、盈亏比或情绪执行纪律时，读取 [`../shared/trading-risk-discipline.md`](../shared/trading-risk-discipline.md)。
- 获取公司、交易所、监管、政府或行业机构的网页、PDF、原始披露或政策资料时，读取 [`../shared/external-evidence-sources.md`](../shared/external-evidence-sources.md)。
- 使用 TuShare、项目 SQLite 或结构化财务、宏观、行情和跨资产数据时，读取 [`../../references/tushare-data.md`](../../references/tushare-data.md)。
- 用户要求保存、复用、历史复盘或 Wiki，或任务确有多阶段、交接、长命令和上下文压缩风险时，读取 [`../../references/persistence.md`](../../references/persistence.md)。

若行动结论同时依赖 3–6 个月的基本面催化或财务兑现，同时调用 [`../ir-medium-term-catalyst/SKILL.md`](../ir-medium-term-catalyst/SKILL.md)。

## 研究方法

用于一个月内以技术指标为主要筛选入口的短期交易、事件/宏观验证、动量、因子筛选、入场节奏和价格异动，以及以价格和事件执行为主的 1–3 个月问题。它不自动评价公司的长期价值。若行动结论同时依赖 3–6 个月的基本面催化或财务兑现，读取 [`../ir-medium-term-catalyst/SKILL.md`](../ir-medium-term-catalyst/SKILL.md)。

### TuShare 数据调用包

普通短线研究使用 TuShare 与项目 SQLite。先运行技术指标，再按事件和执行缺口选数：

```bash
python3 scripts/tushare_mode_data.py indicators --symbol 000001.SZ --end-date 20260719
python3 scripts/tushare_mode_data.py plan short --symbol 000001.SZ --end-date 20260719
python3 scripts/tushare_mode_data.py fetch short --symbol 000001.SZ --end-date 20260719 --datasets limit_list limit_step money_flow
python3 scripts/tushare_sector_data.py performance --provider ths --sector-type N --as-of 20260719 --sort-by return_5d
python3 scripts/tushare_sector_data.py memberships --provider ths --stock-code 000001.SZ --as-of 20260719
```

基础包覆盖日线、复权、基准、估值流动性、市场广度、资金、杠杆、涨跌停和龙虎榜。按问题扩展连板、题材板块、机构席位、筹码、因子、热度、游资和分钟数据。完整 key 与 endpoint 见 [`../../references/tushare-data.md`](../../references/tushare-data.md)。

常规短线以 TuShare 与 SQLite 为数据边界。业绩公告直接驱动行情时核实该事件公告；盈利兑现成为 3–6 个月主线时切换中期研究。每次选择最小充分数据集，并记录 endpoint、`as_of`、空结果和错误分类。

短期候选依赖行业、题材、资金扩散或相对板块强弱时，技术指标之后必须分别读取同花顺 `sector-type I` 行业表现、`sector-type N` 概念表现与个股 `memberships`，不能把所有类型混成一张榜。没有本地板块数据时，使用 `tushare_sector_data.py plan/fetch` 补齐同一 `as_of` 的板块字典、日线和必要资金流；不得把单只股票涨跌、涨停标签或过期成分快照替代板块确认。东财和通达信只作为独立口径交叉验证，不与同花顺板块代码合并排序。

### 选择时间路径

- 短期候选筛选先运行技术指标，按趋势、动量、风险/位置、成交确认、相对表现和可执行流动性识别候选。宏观或行业传导链只用于解释技术候选、推断逻辑并验证其业务暴露与交易可行性，不能反过来替代初筛。
- 已排期事件或明确市场状态可形成辅助假设；对技术候选核验行业映射、个股暴露和预期差，再判断其是否增强、削弱或不改变技术判断。
- 1–3 个月重叠区间中，催化兑现主导时改用 [`../ir-medium-term-catalyst/SKILL.md`](../ir-medium-term-catalyst/SKILL.md)；价格与事件执行主导时使用本文件，并说明持有期和关键假设。
- 纯技术/因子筛选可产生研究候选，但不能仅凭指标生成长期评级或个性化交易指令。

### 宏观与行业传导验证

在技术指标筛出的候选中，要用宏观/行业逻辑加以佐证，使用传导链推断其逻辑并验证可行性，例如：

`技术指标筛出的候选 → 已核实/已排期事件或市场状态 → 相对共识的预期差 → 利率/汇率/商品/流动性/风险偏好 → 行业与价值链环节 → 个股实际收入/成本/订单/估值/资金暴露 → 可行性与价格成交确认 → 当前行动标签`

同时写出至少一条反向链。每个关键箭头说明证据、方向、时间窗口和未知项；事件日程可以是事实，事件结果和市场反应只能写成情景。

- 对技术筛出的候选，比较受益、受损和影响不明确的行业，再核验个股实际暴露；不要为既有技术信号倒推故事。
- 无法核验行业映射、关键箭头依赖传闻、公司实际暴露不足，或利好已充分定价时，不把事件链作为行动主因。
- 找不到可靠事件时不要虚构催化；保留价格/流动性筛选，并明确结论仅由技术证据支持，不能宣称已获宏观或行业逻辑验证。

### 市场与技术确认

对一个月内的个股候选比较、行动判断、入场节奏或价格条件问题，只要本地 SQLite 有截至 `as_of` 的可用日线，就必须先运行 `scripts/tushare_mode_data.py indicators --symbol <代码> --end-date <as_of>` 并读取 `technical_snapshot`，将其作为候选筛选的第一步。除当前趋势、动量、风险/位置和成交参与外，必须读取 `historical_price_structure`：先核验本地历史覆盖起点，再检查全可用历史、1 年和 3 年窗口的历史高点、距高点、最大回撤、年化路径和 `price_path_label`。缺少 1 年或 3 年窗口不能把较短缓存误称为对应历史；高低价尚未同步时，`historical_high_basis`/`historical_low_basis` 为收盘价回退，必须如实说明。数据缺失、过期或历史不足时，有限进行补全，并明确技术证据缺口；不得无声跳过。纯事实核验、基本面长期研究或与价格执行无关的问题不强制运行。

读取全部可用维度，但最终只引用会改变行动标签、价格条件、置信度或撤销条件的观察，避免堆叠高度相关指标：

- 趋势：区间收益、价格相对长短均线、均线排列、相对基准表现；
- 动量：MACD 相对信号线的位置、柱体近期方向和最近交叉，RSI 当前区间与近期变化；
- 风险与位置：波动、回撤、布林带位置和带宽，不把触及上下轨单独解释为反转；
- 成交确认：量比、上涨日成交占比、量价相关、换手和可执行流动性；
- 估值分位、行业与基准相对表现；
- 停牌、新股、复权、涨跌停、T+1、交易成本、滑点和隔夜跳空风险。

对近期涨幅大、价格显著偏离均线或处于区间/估值高位的候选，增加“兑现程度”检查：

- 区分绝对股价与价格位置，结合近期涨幅、均线偏离、区间位置、成交变化、估值分位和事件前后表现判断市场已计入多少预期；
- 写出持有期内仍可能推动上涨的可验证变量、兑现窗口和对应价格空间，并与失效位、交易成本及下行风险比较；
- 剩余驱动缺乏证据，或潜在上行无法覆盖下行与成本时，将该候选移出最终名单并继续筛选。

短期输出必须包含一段“技术确认”，记录指标最新交易日和复权口径，说明至少一个支持或确认观察，主动检查反向或未确认观察，并写清它们具体改变了什么；未发现明确反向时如实说明，不为满足格式制造冲突。若各维度冲突，保留冲突并降低行动强度，不做多数投票或综合打分；若技术面未改变结论，也明确写“未改变”及原因。不得只报“MACD 金叉”“RSI 超买/超卖”，必须结合变化方向、成交确认、事件窗口和价格结构解释。

技术筛选成立但价格结构或成交未确认时，可等待价格。技术面走强而宏观/行业传导尚未核验时，不得虚构催化或将其写成行动主因；可保留明确标注为技术驱动的结论，并按未验证风险调整行动强度。若行动结论需要延续至中期催化兑现，且 [`../ir-medium-term-catalyst/SKILL.md`](../ir-medium-term-catalyst/SKILL.md) 的财务核验尚未完成，不得以短期价格走强替代。宏观或行业验证只能增强、削弱或限定技术判断；技术、风险收益和可执行性优于现金或替代项时，才提高行动强度。

### 因子与系统化筛选

计算前明确股票池、`as_of`、数据可得时间、持有期、基准、复权、再平衡和交易约束。检查未来函数、幸存者偏差、参数敏感性、行业暴露、换手成本、样本外表现和极端行情依赖。未通过检查的因子只作研究线索。

本地指标可由 `scripts/tushare_mode_data.py indicators` 从已入库数据计算。优先读取其 `technical_snapshot`，需要核验数值或更长路径时再读取 `latest` 或用 `--output` 导出历史。`historical_price_structure` 的 `price_path_label` 用年化对数趋势与拟合度将路径描述为持续上涨、持续下跌、横盘/震荡或混合状态；它只帮助避免短周期信号掩盖长期价格结构，不是固定阈值、综合评分或自动交易信号。MACD、RSI、布林带、均线、波动和量价指标同样只是观察项。

### 异动归因与输出

价格异动按基本面、估值/情绪、资金/流动性和未知因素组织，说明证据和时间顺序。归因本身不自动回答是否买入；只有用户提出比较或行动问题时，才进入主 Skill 的决策纪律。

行动结论补充明确的触发条件、失效条件、最长观察/持有窗口和复核事件。用户未提供风险预算、持仓和交易成本时，不虚构精确仓位或止损比例。

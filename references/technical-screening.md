# 技术筛选

从本地 SQLite 市场数据存储进行 A 股筛选时，使用本参考资料。

## 工作流

1. 使用 `scripts/tushare_sync.py` 确认或更新 `data/investment_research.sqlite`。
2. 同步价格/成交量和因子输入：`--daily-basic`、`--fina-indicator` 和 `--stock-basic`。
3. 当政策、利率、流动性、战争/冲突、大宗商品、行业监管、市场风格和风险偏好可能影响筛选时，刷新当前宏观/市场背景。
4. 在排序结果前选择筛选方案：
   - 默认基线：用一个预设运行 `scripts/factor_screen.py`。
   - 自定义市场状态叠加层：应用前先定义额外过滤器、因子倾斜、行业纳入/排除、catalyst 字段或风险上限。
5. 运行 `scripts/factor_screen.py` 生成可复现基线。`scripts/technical_screen.py` 只作为原始技术指标层或诊断工具。
6. 将任何预注册自定义叠加层应用于基线导出或幸存标的集合；保留基线排名用于比较。
7. 让 AI 以怀疑者身份复核短名单：解释动量为什么存在、估值是否拉伸、设置是否可持续、什么会证伪。
8. 将候选转化为研究任务，不要转化为自动买入指令。

示例：

```bash
python3 scripts/tushare_sync.py 20250101 20260630 --db-path data/investment_research.sqlite
python3 scripts/tushare_sync.py 20250101 20260630 --db-path data/investment_research.sqlite --daily-basic --fina-indicator --stock-basic
python3 scripts/factor_screen.py \
  --db-path data/investment_research.sqlite \
  --as-of 20260630 \
  --preset balanced \
  --top 50 \
  --industry-cap 0.25 \
  --output outputs/screens/factor_screen_20260630.csv
```

下载的市场数据应保存在 SQLite。CSV/XLSX 只用于最终筛选导出、人工提供的增强数据或有界 catalyst 输入。

## 自定义市场状态筛选

随附代码是起点，不是刚性要求。用户的参考代码和本地脚本提供可复用因子；当当前市场状态让默认预设不完整时，筛选负责人可以定义自定义规则。

自定义规则可用于：

- 市场风格：价值、股息、成长、中小盘、大盘质量、周期反弹、防御性现金流
- 宏观敏感性：利率、流动性、汇率、大宗商品、财政政策、产业政策、地缘政治
- 行业聚焦或排除：政策支持行业、拥挤主题、制裁/出口管制暴露、大宗商品链
- 风险控制：更严格的回撤、换手率、估值分位、杠杆、质押、流动性或集中度限制
- 催化叠加层：盈利拐点、回购、政策批准、订单周期、价格周期触发、行业产能退出

护栏：

- 在查看或重排最终标的前，预先登记自定义规则。
- 除非用户明确要求特殊情景研究，否则保留对 ST/退市、关键数据缺失、极端过热、非正估值指标和严重流动性问题的硬排除。
- 绝不只按近期涨幅排序；保持估值和过热惩罚可见。
- 将自定义结果与基线预设比较，并解释主要差异。
- 输出自定义规则集、市场状态理由、来源时间戳和已知偏差风险。

## 多因子流程（多因子 + 抗追高）

筛选路径是：

```text
全市场股票池
-> 硬门槛
-> trend/value/quality/growth 分数
-> 过热、估值分位和风险惩罚
-> 预设综合分
-> 行业集中度上限
-> 带因子拆解和追涨风险标签的短名单
-> AI 对抗性复核
```

脚本不得只按近期涨幅给最终候选排序。动量只是输入；估值分位和过热控制是明确的抗追高检查。

## 指标

原始技术层计算：

- 前复权价格
- 用于因子筛选的 60 日 bias、年化 Sharpe 和 volume ratio
- `factor_screen.py` 中的 12-1 momentum
- 最大回撤
- 完整度和实际窗口

因子层增加：

- 行业相对估值分位
- 质量和成长分位
- 硬门槛 `filter_log`
- `trend_score`, `value_score`, `quality_score`, `growth_score`
- `overext_penalty`, `valuation_pctl_penalty`, `risk_penalty`
- `composite_score`, `style_preset` 和 `追涨风险`

## AI 复核

在确定性短名单之后，AI 复核入围标的。它只能基于理由否决或重排候选：

- 为什么上涨：基本面、情绪、流动性或一次性事件
- 用分位证据判断估值是否拉伸
- 趋势是否可以延续
- 证伪条件
- 是否需要更深的单只股票研究

AI 复核不能覆盖硬门槛，也不能编造缺失因子数据。

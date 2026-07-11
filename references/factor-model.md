# 因子模型

确定性 A 股因子筛选使用本参考资料。它只在用户明确要求“多因子”“量化初筛”“动量”或“技术面筛选”时使用；普通“筛选股票”默认走 `fundamental_pool.py` 的长期基本面研究池。因子模型只把全市场缩小为研究池；它不生成 `long_term_status`、`entry_action` 或 `portfolio_action`。

## 核心约定

显式量化筛选必须可复现：

```text
SQLite 数据
-> 硬门槛
-> 因子分与惩罚
-> base_factor_score（正向因子加权）
-> composite_score（只扣除确定性风险惩罚的基础研究池排名）
-> 行业上限
-> research_priority_overlay（独立、可选）
-> 研究池
-> 逐只长期准入
```

AI 只在短名单之后用于对抗性复核。AI 可以基于证据否决或重排入围标的，但不能替代硬门槛、因子计算或缺失数据处理。

调用 CLI 时必须传入 `--explicit-quantitative-baseline`，以避免把这个包含趋势、波动和过热数据的分支误当成默认选股入口。

默认预设是基线。当前市场条件需要自定义筛选时，必须在查看最终标的前定义规则集，保留基线对照并说明差异。公司质量、催化优先级、当前买点和组合位置不得合并成一个总投资分。

## 因子层

| 层 | 字段 | 方向 |
|---|---|---|
| trend | `mom_12_1`, `sharpe_60d`, 健康的 `vr_60d` | 越高越好，但过热会被惩罚 |
| value | `pe_ttm`, `pb`, `ps_ttm`, `dv_ttm`, `pe_pctl_ind`, `pb_pctl_hist` | 越便宜、股息率越高越好 |
| quality | `roe_dt`, `netprofit_margin`, `grossprofit_margin`, `debt_to_assets`, `ocf_to_or` | 盈利/现金越高越好，杠杆越低越好 |
| growth | `netprofit_yoy`, `or_yoy` | 越高越好，低质量会折价增长 |
| risk | `max_drawdown`, 波动率代理、流动性 | 惩罚或硬门槛 |
| catalyst | 只针对幸存标的的可选有界 CSV/XLSX 输入 | 只形成独立研究优先级，不改变基础因子分，不恢复淘汰标的 |

缺失的数值型因子在受影响分数中中性化为 `0.5`，并必须在 `pass_reason` 中说明。

## 硬门槛

默认门槛：

| 门槛 | 规则 |
|---|---|
| 数据完整度 | `completeness >= 0.98` 且 `actual_window >= 100` |
| ST/退市 | 排除名称包含 `ST`、`*ST` 或 `退` 的标的 |
| 日频估值 | 当前 `daily_basic` 行包含 `pe_ttm`, `pb`, `total_mv`, `circ_mv` |
| 规模/流动性 | TuShare 万元人民币单位下，`total_mv >= 500000` 且 `circ_mv >= 200000` |
| 回撤 | `max_drawdown <= 0.45` |
| 财报 | 当前已公告 `fina_indicator` 包含 `roe_dt`, `netprofit_yoy`, `debt_to_assets` |
| 质量 | `roe_dt >= 2` |
| 利润趋势 | `netprofit_yoy >= -20` |
| 杠杆 | `debt_to_assets <= 75` |
| 极端交易风险 | 使用宽松绝对兜底排除明显数据异常、不可交易或极端过热；主要追高判断使用自身/行业分位和波动率调整 |
| 估值有效性 | `pe_ttm > 0` 且 `pb > 0` |

每个门槛都写入一行 `filter_log`，包含筛选前、筛选后和移除数量。

## 预设

正向因子权重合计为 `1.0`；风险是惩罚项，不是正向因子。

| 预设 | trend | value | quality | growth | 过热 | 估值分位 |
|---|---:|---:|---:|---:|---|---|
| balanced | 0.20 | 0.30 | 0.25 | 0.25 | 中 | 中 |
| value | 0.10 | 0.45 | 0.30 | 0.15 | 中 | 强 |
| growth | 0.20 | 0.15 | 0.25 | 0.40 | 中 | 弱但保留 |
| prosperity | 0.30 | 0.10 | 0.20 | 0.40 | 强 | 弱但保留 |

`balanced` 是默认预设，并刻意以 value 为主导，以避免纯动量追高。预设只决定基础研究池排名，不表示投资偏好已经通过长期准入。

## 自定义规则叠加层

当市场状态让固定预设不完整时，使用自定义叠加层。示例：

| 市场条件 | 可能的自定义规则 |
|---|---|
| 降息 / 流动性宽松 | 允许更高质量-成长倾斜，但保留估值分位惩罚 |
| 流动性收紧 / 避险 | 提高质量、现金流、股息和流动性要求 |
| 大宗商品上行周期 | 加入商品价格敏感性和库存/现金流检查 |
| 政策支持行业 | 加入催化证据、政策日期和受益逻辑 |
| 战争、制裁、关税或出口管制 | 排除或标记暴露供应链；要求有来源支持的事件风险 |
| 拥挤主题 / 投机性上涨 | 收紧过热、估值分位、换手率和回撤过滤 |

自定义叠加层可以调整：

- 因子权重或预设选择
- 硬门槛阈值
- 行业上限或行业纳入/排除
- 独立的研究优先级输入
- 风险惩罚和集中度限制

规则：

- 在最终排序前写出市场状态诊断和自定义规则。
- 保留 `balanced` 或相关预设的基线导出用于比较。
- 默认不要关闭抗追高控制；固定绝对阈值只作为极端兜底，正常警示优先使用相对分位。
- 除非用户明确要求困境或特殊情景研究，否则不要恢复未通过安全门槛的股票。
- 在自定义输出中标明规则名称、来源时间戳和偏差风险。

## 惩罚项

- 过热惩罚：20/60 日相对涨幅、ATR/趋势偏离、换手和量比处于自身、行业或市场极端分位。
- 估值分位惩罚：`pe_pctl_ind` 较高，或缺乏盈利上修支撑的自身历史分位较高。该惩罚绝不关闭。
- 风险惩罚：大回撤、波动率、流动性不足和数据窗口不可靠。

任何过热或估值分位惩罚都设置 `追涨风险 = 是`，在 `disqualify_risk` 中记录具体维度和数据时间戳。基础脚本暂时只有 bias/量比等代理时，明确回退口径，不把代理描述成完整 ATR/拥挤检查。

## Catalyst 与研究优先级

`--with-catalyst` 是可选项，默认关闭。允许针对门槛幸存标的提供有界输入：

```text
ts_code,catalyst_score,catalyst_source,catalyst_time,catalyst_signal_id
```

规则：

- `catalyst_score` 截断到 `[0,1]` 并作为审计字段保留；它唯一的计算用途是生成 `research_priority_overlay`。
- `base_factor_score` 和 `composite_score` 都保持纯基础因子基线，不因新闻或 catalyst 改写。
- 先按 `composite_score` 完成候选选择和行业上限，再用 overlay 调整幸存标的的研究处理顺序；overlay 不能改变候选集合、`long_term_status` 或 `entry_action`。
- catalyst 不能恢复硬门槛淘汰股票。
- 未核实 catalyst 只可标记待研究，不作为正向证据。
- AI 创建输入时引用 `news-intelligence.md` 的 `signal_id`、来源、状态和时间。

## 输出要求

研究池必须包含：

```text
ts_code
candidate_source = factor_baseline
trend_score
value_score
quality_score
growth_score
overext_penalty
valuation_pctl_penalty
risk_penalty
base_factor_score
composite_score
style_preset
research_priority_overlay
research_priority_rank
priority_reason
追涨风险
pass_reason
disqualify_risk
long_term_status = not_evaluated
next_step = stage_L
as_of
```

最终报告不得沿用 `composite_score` 作为投资排名。进入阶段 L 后按生意、财务、治理、长期预期和证伪条件重新比较。

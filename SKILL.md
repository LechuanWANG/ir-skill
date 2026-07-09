---
name: local-investment-research
description: Use when the user asks for stock analysis, A-share screening, portfolio review, position sizing, market or price-move attribution, deep investment research, thesis tracking, or maintaining a local investment knowledge base from holdings, market data, filings, reports, and research notes.
---

# 本地投资研究

## 概览

把这个技能当作本地投资研究工作台使用。输出应是决策备忘录，而不是泛泛的研究文章：先给行动建议，引用证据，暴露不确定性，并把有长期价值的结论沉淀到本地 Wiki。

这只提供研究辅助。不要把输出表述成金融建议或自动化交易指令。

## 第一步

先判断用户请求类型，然后只加载该路径需要的参考资料：

| 用户意图 | 读取这些参考资料 | 默认深度 |
|---|---|---|
| 单只股票研究 | `references/decision-framework.md`, `references/fundamental-research.md`, `references/industry-macro.md`, `references/data-sources.md` | 深度 |
| A 股筛选 | `references/technical-screening.md`, `references/factor-model.md`, `references/data-sources.md` | 快速 |
| A 股一流公司深度研究 | `references/deep-research-mode.md`, `references/decision-framework.md`, `references/fundamental-research.md`, `references/industry-macro.md`, `references/data-sources.md`, `references/output-templates.md` | 深度 |
| 组合复盘或仓位测算 | `references/portfolio-thesis.md`, `references/wiki-memory.md`, `references/decision-framework.md` | 快速，仓位较大时加深 |
| 价格异动或新闻归因 | `references/industry-macro.md`, `references/data-sources.md`，可选 `references/portfolio-thesis.md` | 快速 |
| 文件/报告/Wiki 导入 | `references/wiki-memory.md`, `references/output-templates.md` | Wiki 工作流 |
| 用户明确要求深度研究或重大决策 | `references/deep-research-mode.md` 加上对应路径的参考资料 | 深度 |

不要创建或读取 `references/router.md`；路由逻辑放在本文件内，这样技能可以直接选择参考资料，不需要第二跳。

## 运行规则

1. 只要请求提到当前持仓、偏好、过往决策、投资假设跟踪或本地文档，分析前必须先读取 `docs/investment-llm-wiki/index.md` 和相关 Wiki 页面。
2. 默认使用快速输出。用户要求深度、要求四视角分析、询问单只股票投资决策，或该决策会实质性改变大仓位时，使用深度模式。
3. 将深度模式视为用户对四代理研究的明确授权。原生子代理（subagents）可用时，并行启动 A1-A4，并以负责人身份综合结论；subagents 不可用时，在主 agent 中按同样角色顺序执行。
4. A 股筛选必须走多因子打分，显式抗追高（估值分位 + 过热惩罚），不得以纯动量排序输出候选。
5. 将随附筛选脚本视为可复现基线，而不是唯一允许的筛选逻辑。当前市场条件支持自定义筛选规则时，必须先定义市场状态、规则变化和风控，再排序结果；并在输出中记录这些内容。
6. 抓取、筛选和机械计算必须使用确定性脚本。不要依赖 LLM 心算市值、估值倍数或技术指标。
7. 下载的市场数据存入本地 SQLite 数据库，不要放进临时 CSV 缓存。默认使用 `data/investment_research.sqlite`；CSV/XLSX 只作为最终面向用户的导出。
8. 关键数据必须交叉核对。标明来源、时间戳、单位、币种，以及数据是否不可得。差异超过 1% 需要备注；超过 5% 时，必须先核查原始公告或交易所来源，才能依赖该数字。
9. 深度报告或最终投资结论中的财务报表数字，必须将 TuShare 标准化数据与巨潮资讯、交易所披露或公司 IR 页面上的公开年报、半年报或季报交叉核对。收入、利润、EPS、资产负债表、现金流或分部数据不得只依赖 TuShare。
10. 当宏观、政策、战争/冲突、利率、流动性、汇率、大宗商品或监管可能影响投资假设时，结论前必须做当前网络检索。优先使用官方来源，并用独立报道核对重要判断。若无法访问网络，说明未完成实时宏观验证，并降低置信度。
11. 建立逻辑链：宏观环境 -> 行业周期 -> 公司质量 -> 估值/价格 -> 组合影响。不要只凭技术面、基本面或新闻单点下结论。
12. 对筛选短名单做深度研究时，不要把原始因子排名直接保留为最终排名。应按生意质量、财务质量、估值不对称性、行业周期、治理/事件风险和买入前验证条件重新排序。
13. 来源冲突时，列出矛盾，不要把矛盾抹平。写回 Wiki 时使用 `contradiction` 约定。
14. 写入敏感组合、资金或偏好数据到 Wiki 页面前必须询问，除非用户在本轮明确要求更新 Wiki。

## 脚本

随附脚本位于 `scripts/`：

- `scripts/market_data_store.py`: 创建并查询本地 SQLite 市场数据数据库。
- `scripts/tushare_sync.py`: 使用 `TUSHARE_TOKEN` 将 TuShare A 股日线价格、成交量和复权因子数据同步到 `data/investment_research.sqlite`。
- `scripts/technical_screen.py`: 从本地数据库计算前复权技术指标，并把可选基本面数据合并进筛选表。
- `scripts/factor_screen.py`: 用硬门槛、因子分、抗追高惩罚、预设、集中度控制和可选催化重排，生成确定性的多因子 A 股短名单。
- `scripts/financial_check.py`: 校验市值和估值倍数。
- `scripts/wiki_index.py`: 检查本地 Wiki 页面是否存在坏链、缺失 frontmatter 和缺失来源。

在本工作区中，顶层 `scripts/` 目录也有轻量封装，便于本地测试和复用。

## 数据持久化

使用 `data/investment_research.sqlite` 作为下载市场数据的可复用本地存储。`a_share_daily` 表保存 `trade_date`、`ts_code`、`close_qfq`、`volume`、`source` 和 `retrieved_at`，以 `(trade_date, ts_code)` 为键，因此重复运行会更新已有行，而不是制造重复文件。

不要为抓取的价格或成交量创建单次运行 CSV 缓存。如果工作流需要可分享表格，把最终筛选或报告产物导出到 `outputs/`；原始、可复用的市场数据留在数据库里。

## 输出

具体格式使用 `references/output-templates.md`。

快速备忘录应大致控制在一屏内，并包括：结论、行动、置信度、为什么、最大风险或证伪条件、数据/来源时间戳，以及是否需要进一步深挖。

深度报告必须包括：结论/行动、看多和看空证据、生意质量、估值观点、最大不确定性、证伪条件、组合影响、四视角分歧、数据附录和 Wiki 写回计划。

## 记忆

使用 `references/wiki-memory.md` 和 `docs/investment-llm-wiki/` 中的本地 Investment LLM Wiki 协议：

- 分析前召回：先读 `index.md`，再读相关公司、行业、thesis、decision、portfolio 和 profile 页面。
- 分析后更新：追加 `log.md`；更新 entity/analysis/decision 页面；添加 `[[links]]`；记录矛盾，不要覆盖旧结论。
- 保持原始来源不可变。

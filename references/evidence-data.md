# 证据获取与结构化数据

只在需要实际获取网页、PDF、行情、TuShare 或本地数据时读取。先确定要验证的假设，再选择最轻量的来源和工具。

## 来源顺序

1. 财报、公告、治理和重大事项：优先公司、交易所、巨潮、监管机构的原始 PDF、公告页或直接下载。
2. 政策、宏观和行业统计：优先政府、监管、官方统计和行业机构原文。
3. 新闻和市场评论：只用于发现线索；关键事实回到原始来源核验。
4. 市场行情和标准化字段：使用 TuShare 或本地 SQLite，并记录交易日、获取时间、复权、基准、单位和币种。

### 常用网站入口

| 类别   | 网站        | 网址                                                               | 主要用途                       |
| ---- | --------- | ---------------------------------------------------------------- | -------------------------- |
| 公司披露 | 巨潮资讯网     | [https://www.cninfo.com.cn/](https://www.cninfo.com.cn/)         | A 股上市公司公告、定期报告、招股书         |
| 监管   | 中国证监会     | [https://www.csrc.gov.cn/](https://www.csrc.gov.cn/)             | 监管政策、行政处罚、审核和规则            |
| 公司官网 | 公司投资者关系页面 | 使用“公司名称 + 投资者关系”搜索                                               | 财报、演示材料、业绩说明会和公司新闻         |
| 市场数据 | TuShare   | 本地 `TUSHARE_TOKEN` 与项目脚本                                         | 股票行情、估值、成交、资金和宏观接口         |
| 市场数据 | 中国货币网     | [https://www.chinamoney.com.cn/](https://www.chinamoney.com.cn/) | 银行间利率、汇率、债券和货币市场数据         |
| 市场数据 | 中国债券信息网   | [https://www.chinabond.com.cn/](https://www.chinabond.com.cn/)   | 国债、信用债、收益率曲线和债券指数          |
| 宏观数据 | 国家统计局     | [https://www.stats.gov.cn/](https://www.stats.gov.cn/)           | GDP、CPI、PPI、工业、消费、投资、地产和就业 |
| 宏观数据 | 国家数据      | [https://data.stats.gov.cn/](https://data.stats.gov.cn/)         | 月度、季度、年度和地区统计数据库           |
| 宏观数据 | 中国人民银行    | [https://www.pbc.gov.cn/](https://www.pbc.gov.cn/)               | 社融、货币供应、信贷、利率和金融统计         |
| 宏观数据 | 财政部       | [https://www.mof.gov.cn/](https://www.mof.gov.cn/)               | 财政收入、支出、政府债务和财政政策          |
| 宏观数据 | 国家外汇管理局   | [https://www.safe.gov.cn/](https://www.safe.gov.cn/)             | 外汇储备、国际收支、跨境资金和结售汇         |
| 行业政策 | 国家发展改革委   | [https://www.ndrc.gov.cn/](https://www.ndrc.gov.cn/)             | 产业政策、价格政策、投资和行业运行          |
| 行业政策 | 工业和信息化部   | [https://www.miit.gov.cn/](https://www.miit.gov.cn/)             | 制造业、通信、汽车和重点工业运行数据         |
| 行业贸易 | 海关总署      | [https://www.customs.gov.cn/](https://www.customs.gov.cn/)       | 进出口、商品贸易和海关政策              |
| 行业资料 | 全国性行业协会官网 | 使用“行业名称 + 协会 + 官网”搜索                                             | 行业产量、价格、库存、政策和企业数据         |
| 新闻线索 | 格隆汇       | [https://www.gelonghui.com/](https://www.gelonghui.com/)         | A 股、港股、美股和行业资讯             |
| 新闻线索 | 财新网       | [https://www.caixin.com/](https://www.caixin.com/)               | 宏观、金融、产业和公司调查报道            |

## 网页与 PDF

- 搜索入口或官方文件地址时使用搜索工具；已知静态 URL 时直接请求或下载。
- 已知、公开的静态 HTML/PDF 可使用 `scripts/research_collect.py collect --task <task-id> --url <url>`；该工具只把通过类型和内容校验的原件写入 `staging/<task-id>/raw/`，并把安全校验页、错误页和无效 PDF 记录为采集失败。
- 页面依赖 JavaScript、筛选、分页或点击下载时，用浏览器定位真实 PDF、文件 URL 或公开接口，再转回直接下载或脚本处理。
- 只在静态 HTML 需要正文清理或有限抓取时使用 `webclaw`。先检查 `command -v webclaw`；不可用时改用其他来源，安装前取得必要授权。
- 网页无法抽取不等于未披露。抓取文本不替代原始文件核验。
- 财务表格或复杂 PDF 先渲染并查看相关页面，记录页码、表名、报告期、公告日、单位和币种；必要时与官方 HTML、Excel、XBRL 交叉核对。

## 本地数据工具

运行对应脚本的 `--help` 获取最新参数；表和字段说明见 `docs/data-layer-overview.md`。

- `scripts/tushare_mode_data.py plan/fetch <long|medium|short>`：按持有期规划和获取最小市场数据包；显式设置 `--end-date` 和合适的 `--benchmark`。
- `scripts/tushare_mode_data.py indicators`：从已入库的前复权日线和成交量计算基础指标，不发起网络请求。
- `scripts/tushare_gateway.py fetch/probe/cache`：处理模式包未覆盖的显式 endpoint、权限小样本检查和原始缓存查询。
- `scripts/tushare_sync.py`：补齐需要重复比较的全市场基础数据。
- `scripts/market_data_store.py`：读写和查询本地 SQLite。

TuShare 用于价格、估值、成交、资金、市场状态、披露时间线和待核验线索。`fina_indicator` 只作趋势线索，不作为报告中的收入、利润、现金流或资产负债表事实。

### 中期财务基线

对 3–6 个月个股推荐或候选排序，先用原始定期报告建立财务事实基线，再使用市场数据决定价格条件。标准化接口只用于快速定位和交叉检查：

1. 先对 `income`、`balancesheet`、`cashflow` 运行 `tushare_gateway.py probe`，用最小 `ts_code`、`period` 和字段集确认权限与数据可得性；可用时再用 `fetch` 缓存对应报告期。
2. 对照最新年报和最新季报、半年报或业绩预告原文，记录收入、利润率、经营现金流、应收/存货或合同负债，以及按行业相关的负债、资本开支或产能。标准化值与原文冲突时保留冲突，以原文为事实来源。
3. 发现公告线索后，优先直接下载公司、交易所、巨潮或监管机构的 PDF；动态页面无法抽取时，定位真实文件 URL 或公开接口。公告元数据无权限、页面加载失败或搜索受阻均为数据缺口，不得视作“未披露”。
4. 任何关键 PDF 无法取得且不同结果可能改变行动标签时，停止把候选升级为 `优先行动`，改为 `等待证据` 并写明待核验报告和复核时间。

## 持久化与质量检查

- 用于计算、筛选、排名、回测、历史比较或后续复用的结构化数据，先写入 SQLite；一次性事实核验和少量即时行情可以不入库。
- `fetch` 默认缓存原始响应和接口状态。研究中不要使用 `--no-cache`；`--dry-run` 只验证计划，不请求也不写入数据。
- 入库失败、接口空返回、无权限或日期缺口必须作为数据缺口报告；不要把临时输出当成已缓存数据。
- 使用前按问题检查证券代码映射、主键重复、日期连续性、空值、异常值、复权、停牌、单位、币种和最新可用日期。
- 记录数据库路径、使用表或 dataset、行数、`retrieved_at` 和最新日期，保证结果可复现。
- 不用填充、删除或均值替代掩盖异常；先定位来源、定义、修订或时间口径。

## 安全与停止条件

把 `TUSHARE_TOKEN`、API key、Cookie 和代理凭据保留在环境变量或本地安全配置中，不写入参数文件、报告、缓存、Wiki 或终端输出。

新增数据若不再改变核心假设、候选排序、行动标签、置信度或触发条件，停止采集并报告剩余缺口。

# WebClaw：静态网页的补充抓取层

WebClaw 用于静态 HTML 的正文清理、限深抓取和归档补充，不是财报、公告或公司关键事项的首选入口。先使用公司、交易所、巨潮或监管机构的原始 PDF、公告页和直接下载；动态页面先用浏览器渲染定位文件或接口。只有当静态网页需要清理正文、补充新闻/行业/宏观资料，或上述路径不适用时，才使用 [WebClaw](https://github.com/0xMassi/webclaw) CLI。

## 使用条件、检查与安装

需要将静态网页转成可读 Markdown/JSON 时，先运行：

```bash
command -v webclaw
webclaw --version
```

若命令不存在，只在 WebClaw 确为合适的补充路径时安装。优先使用与当前平台匹配的官方安装方式：

```bash
# macOS / Homebrew
brew tap 0xMassi/webclaw
brew install webclaw

# 官方 Agent 安装器；会检测并可配置兼容客户端
npx create-webclaw
```

如果这两种方式不可用，使用 [WebClaw Releases](https://github.com/0xMassi/webclaw/releases) 的预编译二进制。安装完成后重新执行 `webclaw --version`；安装失败时说明原因和替代来源，不要假装已经抓到网页内容。

## 抓取策略

1. 先确定权威原始来源。财报、公告和关键公司事项直接下载公司、交易所或巨潮的 PDF/原文；不要先从公司官网的二次页面提取。
2. 动态或受保护页面先用浏览器渲染定位 PDF、公告链接或公开接口。网页正文没有被静态提取，不等于资料不存在。
3. 只有静态页面需要正文清理或需要有限范围的新闻、行业、宏观补充时，使用 Markdown 与主体提取：

   ```bash
   webclaw "https://example.com/source" --format markdown --only-main-content
   ```

4. 只有在问题确实需要多个同域静态页面时再 crawl，并限制范围、深度、页数和频率：

   ```bash
   webclaw "https://example.com" \
     --crawl --depth 1 --max-pages 10 --only-main-content \
     --output-dir docs/investment-llm-wiki/raw/industry/example-site/2026-07-14
   ```

5. 浏览器无法定位公开原文且用户已有 `WEBCLAW_API_KEY` 并授权使用时，才考虑 `--cloud`。不要把 API key、Cookie、代理凭据写进 Wiki、日志或输出文件。
6. 遵守来源站点的访问规则、速率限制和适用条款；不做无边界抓取。

## 可选的归档与 Wiki 衔接

用户要求保存抓取结果时，直接归档到对应领域的不可变资料目录：

```text
raw/company/<公司名>/<YYYY-MM-DD>/<内容明确的文件名>  # 公司 IR、公告、财报页面、公司新闻
raw/industry/<行业名>/<YYYY-MM-DD>/<内容明确的文件名> # 行业统计、协会资料、产业链与竞争资料
raw/market/<市场名>/<YYYY-MM-DD>/<内容明确的文件名>   # 指数、全市场和交易制度资料
raw/macro/<主题名>/<YYYY-MM-DD>/<内容明确的文件名>     # 政策、央行、宏观统计、商品/汇率资料
```

文件名说明网页内容，不使用 URL 片段或无语义编号。归档不要求读取或更新 LLM Wiki；只有用户要求复用或维护持久记忆时，才在 `log.md` 记录来源与口径，并更新相关 `wiki/<domain>/<subject>/<内容页面>.md`、`index.md` 和链接。

## 核验边界

- 抓取成功不等于事实已核实。关键财务、治理、交易和政策事实必须回到公司、交易所、监管或政府原文。
- WebClaw 的 Markdown 是 LLM 可读的资料副本，不能替代原始 PDF、公告或数据文件；重要资料同时保留可追溯的原始来源链接与时间边界。
- 当 WebClaw、原始披露和其他来源冲突时，在 Wiki 页面保留冲突、口径与待验证问题，而不是选择看起来最方便的版本。

# PaperSearch

简体中文 | [English](README.md)

PaperSearch 是一个面向 AI agent 的 Skill + CLI 包，基于独立的 Node.js 命令行工具构建，用于学术文献工作。它为 AI agent、终端用户和脚本提供一个可复现的命令层，并通过 agent 友好的 JSON 输出覆盖文献元数据检索、施引/参考文献扩展、期刊指标检索、PDF 获取/下载和论文正文片段检索。

![Node.js](https://img.shields.io/badge/node.js->=18.0.0-green.svg)
![TypeScript](https://img.shields.io/badge/typescript-^5.5.3-blue.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Platforms](https://img.shields.io/badge/platforms-25-brightgreen.svg)
![Version](https://img.shields.io/badge/version-0.4.0-blue.svg)
[![LinuxDo](https://img.shields.io/badge/LinuxDo-community-1f6feb)](https://linux.do)

[快速开始](#快速开始) | [架构说明](#架构说明) | [配置](#配置) | [Agent Skill](#agent-skill) | [支持平台](#支持平台) | [命令](#命令) | [排障](#排障)

## 核心功能

| 功能           | 主要命令                                                                        | 返回内容                                                                              |
| -------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 文献元数据检索 | `paper-search search`, `paper-search run search_*`                              | 题名、作者、年份、期刊、DOI、PMID/PMCID、URL、摘要和来源元数据              |
| 引文扩展       | `paper-search run get_paper_citations`, `paper-search run get_paper_references` | 已知 Semantic Scholar paper ID、DOI 或 arXiv ID 对应论文的施引文献和参考文献          |
| 期刊指标检索   | `paper-search journal-metrics`, `paper-search run query_journal_metrics`        | 影响因子、5 年 IF、JCR/SSCI 分区、中科院分区、JCI、ESI、预警和等级字段                |
| PDF 获取和下载 | `paper-search download`, `paper-search run download_with_fallback`              | 通过公开原生来源、开放获取、仓储、Unpaywall、启用时的 Sci-Hub 和可选 CARSI 后端获取 PDF |
| 正文片段检索   | `paper-search run search_semantic_snippets`                                     | Semantic Scholar Open Access 正文片段，用于查方法、参数和写法线索                     |

## 架构说明

`paper-search` 不是 MCP Server，而是普通 CLI。AI 工具可以通过随包发布的 Skill 调用它，终端用户和脚本也可以直接调用同一个 `paper-search` 命令。

| 层                        | 负责什么                                                                                                                                                                                                                                                                                                                               |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CLI 本体                  | 执行文献检索、引文扩展、期刊指标检索、PDF 获取/下载、正文片段检索和稳定 JSON 输出                                                                                                                                                                                                                                                      |
| Bundled Skill             | 随包发布 `skills/paper-search`，提供 agent 路由规则和 focused references；不保存密钥、cookie 或账号信息                                                                                                                                                                                                                                |
| Friendly Management Layer | 围绕五个主要能力 `metadata_search`、`citation_expansion`、`journal_metrics`、`pdf_discovery`、`body_snippet_search` 提供 `doctor`、`smoke`、`skills`、`config`、`tools`。`doctor` 健康报告包含脱敏配置、Capability Profile、平台/来源状态、缺失项和降级项；`smoke` 检查命令入口连通性和 live 可用性；`skills` 负责同步随包发布的 Skill |

五个主要能力由 CLI 本体执行，由管理层报告和检查。Capability Profile 也会报告可选的 `entitled_access` tier。CARSI 后端是其唯一可选 Entitled Download Backend，默认关闭。`doctor` 会报告 `disabled`、`absent`、`incompatible` 或 `available`；明确不启动后端的离线 profile 报告 `not_evaluated`。出版商或数据库 key 仍可用于 `metadata_entitled` 元数据或开放获取接口，但不能被解释为本地授权 PDF 后端。某一个能力缺少配置或降级，不会导致其他独立能力不可用。

## 快速开始

要求 Node.js >= 18.0.0 和 npm。

```bash
npm install -g papersearch
paper-search setup
paper-search doctor --pretty
```

`paper-search setup` 会依次问三件事：API key 和邮箱；要把 Skill 装到哪些 AI 工具（Claude Code、Codex、Cursor 等）；要不要安装机构下载扩展。Skill 是教 AI 工具怎么调用 paper-search 的说明文件，用 AI 工具做文献任务时要装。跳过了可以随时补装，`--targets` 换成你用的工具（`claude`、`codex`、`cursor`、`gemini`、`agents`，或 `all`）：

```bash
paper-search skills update --targets claude
```

从旧包 `paper-search-cli` 升级时，先运行 `npm uninstall -g paper-search-cli`，再 `npm install -g papersearch`（两个包提供同一个 `paper-search` 命令，不能同时装）；配置、Skill、学校登录和下载记录都保留。

以后升级（`npm install -g papersearch@latest`）后第一次运行 `paper-search`，它会自动把你装过的 Skill 更新到新版本，见 [Agent Skill](#agent-skill)。

也可以把下面这段话发给你的 AI 工具，让它帮你装：

```text
请帮我安装 PaperSearch：运行 npm install -g papersearch，再运行 paper-search skills update --targets <你自己对应的目标：Claude Code 用 claude，Codex 用 codex，Cursor 用 cursor>，最后运行 paper-search doctor --format text，告诉我哪些功能能用、还缺哪些 key。API key 我会自己在终端运行 paper-search setup 输入，不要让我发到聊天里。
```

尝试五个主要功能：

```bash
paper-search search "machine learning clinical prediction" --platform crossref --max-results 3 --pretty
paper-search search "large language models" --sources no-key --max-results 5 --pretty
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --arg limit=5 --pretty
paper-search journal-metrics "Nature" "BMJ" --pretty
paper-search download PMC11466435 --platform pmc --save-path ./downloads
paper-search run search_semantic_snippets --arg query="propensity score matching" --arg limit=3 --pretty
```

常用检查：

```bash
paper-search tools --pretty
paper-search doctor --format text
paper-search smoke --mock --pretty
paper-search skills status --pretty
```

## 支持平台

平台组表适合快速选来源；下面的能力矩阵用于更清楚地判断每个平台实际能做什么。

### 平台组

| 平台组             | 平台                                                                | 主要用途                                             |
| ------------------ | ------------------------------------------------------------------- | ---------------------------------------------------- |
| 综合学术元数据     | Crossref, OpenAlex, Semantic Scholar, Google Scholar                | 广覆盖发现、DOI 元数据、引用线索、文献初筛           |
| 期刊指标           | EasyScholar                                                         | 影响因子、JCR/SSCI 分区、中科院分区、JCI、ESI、预警  |
| 生物医学和生命科学 | PubMed, PubMed Central, Europe PMC                                  | 生物医学元数据、PMID/PMCID 核验、开放全文            |
| 预印本和会议稿     | bioRxiv, medRxiv, OpenReview, IACR ePrint                           | 预印本、AI/ML 投稿、密码学 ePrint                    |
| 计算机和工程       | DBLP, ACM metadata, IEEE Xplore, USENIX                             | CS 目录、工程元数据、会议论文                        |
| 开放获取和仓储     | CORE, OpenAIRE, Unpaywall                                           | 仓储检索；下载经 PMC 官方渠道与 Unpaywall OA 位置    |
| 引文库和出版商     | Web of Science, Scopus, ScienceDirect, Springer Nature/SpringerLink | key-backed 元数据和出版商记录；不是本地授权 PDF 后端 |
| DOI 定向 fallback  | Sci-Hub                                                             | 启用时作为 DOI 定向 PDF fallback                     |

### 能力矩阵

#### 综合学术元数据

| 平台             | 元数据检索 | PDF 路径    | 正文/全文   | 被引统计 | 配置                                             | 说明                                                        |
| ---------------- | ---------- | ----------- | ----------- | -------- | ------------------------------------------------ | ----------------------------------------------------------- |
| Crossref         | ✅ 支持    | ❌ 不支持   | ❌ 不支持   | ✅ 支持  | ❌ 不需要                                        | 默认广覆盖元数据来源                                        |
| OpenAlex         | ✅ 支持    | 🟡 条件支持 | ❌ 不支持   | ✅ 支持  | ❌ 不需要                                        | 免费元数据；记录含 OA 链接时可帮助 PDF fallback             |
| Semantic Scholar | ✅ 支持    | 🟡 条件支持 | ✅ 正文片段 | ✅ 支持  | 🟡 可选；正文片段需要 `SEMANTIC_SCHOLAR_API_KEY` | 适合 AI/CS、引文扩展和正文片段线索                          |
| Google Scholar   | ✅ 支持    | ❌ 不支持   | ❌ 不支持   | ✅ 支持  | 🟡 可选 `GOOGLE_SCHOLAR_PROXY_URL`               | 基于页面解析的 best-effort 发现；可能触发反爬，建议显式调用 |

#### 期刊指标

| 平台        | 元数据检索    | PDF 路径  | 正文/全文 | 被引统计  | 配置                      | 说明                                                          |
| ----------- | ------------- | --------- | --------- | --------- | ------------------------- | ------------------------------------------------------------- |
| EasyScholar | 🟡 仅期刊指标 | ❌ 不支持 | ❌ 不支持 | ❌ 不支持 | ✅ 必需 `EASYSCHOLAR_KEY` | 影响因子、JCR/SSCI 分区、中科院分区、JCI、ESI、预警和等级字段 |

#### 生物医学和生命科学

| 平台           | 元数据检索 | PDF 路径    | 正文/全文   | 被引统计  | 配置                                                | 说明                            |
| -------------- | ---------- | ----------- | ----------- | --------- | --------------------------------------------------- | ------------------------------- |
| PubMed         | ✅ 支持    | ❌ 不支持   | ❌ 不支持   | ❌ 不支持 | 🟡 可选 `PUBMED_API_KEY`, `NCBI_EMAIL`, `NCBI_TOOL` | NCBI E-utilities 生物医学元数据 |
| PubMed Central | ✅ 支持    | ✅ 支持     | ✅ 支持     | ❌ 不支持 | ❌ 不需要                                           | 生物医学开放全文和 PMC PDF      |
| Europe PMC     | ✅ 支持    | 🟡 条件支持 | 🟡 条件支持 | ❌ 不支持 | ❌ 不需要                                           | 生物医学元数据和开放全文链接    |

#### 预印本和会议稿

| 平台        | 元数据检索 | PDF 路径  | 正文/全文 | 被引统计  | 配置      | 说明                                  |
| ----------- | ---------- | --------- | --------- | --------- | --------- | ------------------------------------- |
| bioRxiv     | ✅ 支持    | ✅ 支持   | ✅ 支持   | ❌ 不支持 | ❌ 不需要 | 生物学预印本                          |
| medRxiv     | ✅ 支持    | ✅ 支持   | ✅ 支持   | ❌ 不支持 | ❌ 不需要 | 医学预印本                            |
| OpenReview  | ✅ 支持    | ❌ 不支持 | ❌ 不支持 | ❌ 不支持 | ❌ 不需要 | 公开 OpenReview notes、评审和投稿记录 |
| IACR ePrint | ✅ 支持    | ✅ 支持   | ✅ 支持   | ❌ 不支持 | ❌ 不需要 | 密码学 ePrint 论文                    |

#### 计算机和工程

| 平台         | 元数据检索 | PDF 路径  | 正文/全文 | 被引统计  | 配置                   | 说明                                                     |
| ------------ | ---------- | --------- | --------- | --------- | ---------------------- | -------------------------------------------------------- |
| DBLP         | ✅ 支持    | ❌ 不支持 | ❌ 不支持 | ❌ 不支持 | ❌ 不需要              | 官方 DBLP 计算机文献目录                                 |
| ACM metadata | ✅ 支持    | ❌ 不支持 | ❌ 不支持 | ✅ 支持   | ❌ 不需要              | 通过 Crossref 的 ACM DOI 前缀元数据检索；不抓取 ACM 页面 |
| USENIX       | ✅ 支持    | ❌ 不支持 | ❌ 不支持 | ❌ 不支持 | ❌ 不需要              | 基于 DBLP 的 USENIX 元数据；不抓取 USENIX 搜索页         |
| IEEE Xplore  | ✅ 支持    | ❌ 不支持 | ❌ 不支持 | ✅ 支持   | ✅ 必需 `IEEE_API_KEY` | 官方 IEEE Xplore Metadata API                            |

#### 开放获取和仓储

| 平台      | 元数据检索     | PDF 路径    | 正文/全文   | 被引统计  | 配置                                                        | 说明                                          |
| --------- | -------------- | ----------- | ----------- | --------- | ----------------------------------------------------------- | --------------------------------------------- |
| CORE      | ✅ 支持        | 🟡 条件支持 | 🟡 条件支持 | ❌ 不支持 | 🟡 可选 `CORE_API_KEY`                                      | 仓储记录可能暴露 PDF 或全文链接               |
| OpenAIRE  | ✅ 支持        | 🟡 条件支持 | ❌ 不支持   | ❌ 不支持 | 🟡 可选 `OPENAIRE_API_KEY`                                  | 公开检索通常不需要 key                        |
| Unpaywall | 🟡 仅 DOI 查询 | 🟡 条件支持 | ❌ 不支持   | ❌ 不支持 | ✅ 必需 `UNPAYWALL_EMAIL` 或 `PAPER_SEARCH_UNPAYWALL_EMAIL` | DOI 开放获取 PDF 定位；需要邮箱，不是 API key |

#### 引文库和出版商

| 平台                           | 元数据检索 | PDF 路径                | 正文/全文 | 被引统计  | 配置                                                              | 说明                                                             |
| ------------------------------ | ---------- | ----------------------- | --------- | --------- | ----------------------------------------------------------------- | ---------------------------------------------------------------- |
| Web of Science                 | ✅ 支持    | ❌ 不支持               | ❌ 不支持 | ✅ 支持   | ✅ 必需 `WOS_API_KEY`                                             | 引文数据库元数据、日期排序、年份范围                             |
| ScienceDirect                  | ✅ 支持    | 🟡 OA / `publisher_api` | ❌ 不支持 | ✅ 支持   | ✅ 必需 `ELSEVIER_API_KEY`                                        | Elsevier 元数据与 `publisher_api` 全文（需机构出口或 insttoken） |
| Springer Nature / SpringerLink | ✅ 支持    | 🟡 仅开放获取           | ❌ 不支持 | ❌ 不支持 | ✅ 必需 `SPRINGER_API_KEY`；🟡 可选 `SPRINGER_OPENACCESS_API_KEY` | `springerlink` 是现有 Springer 集成的别名                        |
| Scopus                         | ✅ 支持    | 🟡 条件元数据           | ❌ 不支持 | ✅ 支持   | ✅ 必需 `ELSEVIER_API_KEY`                                        | 摘要和引文数据库；ScienceDirect 和 Scopus 产品权限需要分别开通   |

#### DOI 定向 fallback

| 平台    | 元数据检索 | PDF 路径 | 正文/全文 | 被引统计  | 配置      | 说明                                                    |
| ------- | ---------- | -------- | --------- | --------- | --------- | ------------------------------------------------------- |
| Sci-Hub | ❌ 不支持  | ✅ 支持  | ❌ 不支持 | ❌ 不支持 | ❌ 不需要 | DOI/URL 定向 fallback；位于 OA 路径之后、可选授权层之前 |

说明：

- 元数据检索指发现和初筛论文，不等于 PDF 下载或正文证据。
- `pdf_discovery` 独立区分开放获取来源、仓储、Unpaywall、Sci-Hub 和可选 CARSI 后端。CARSI 后端是唯一可选 Entitled Download Backend。
- EasyScholar 是期刊指标来源，不是论文检索来源。
- Sci-Hub 不属于 `metadata_search`，只作为 DOI/URL 定向 PDF fallback。
- `🟡 条件支持` 表示只有记录暴露 DOI、开放获取链接或公开 PDF URL 时才可用，不代表授权全文访问。
- API key 只在使用对应 key-backed 来源或工作流时才需要。
- Google Scholar 已从 `--sources all` 中移除，避免多源并发放大反爬限流。需要时请显式使用 `--platform googlescholar` 或 `--sources googlescholar`；如直连反复被拦截，可配置有授权的 HTTP(S) 或 SOCKS 代理到 `GOOGLE_SCHOLAR_PROXY_URL`。
- Scholar 适配器参考了 [bingshuoguo/google-scholar-mcp](https://github.com/bingshuoguo/google-scholar-mcp) 的低流量客户端做法：单个 keep-alive 客户端、默认 `0.5` 请求/秒、有限重试、结果缓存，并立即识别 CAPTCHA/`/sorry` 挑战页。它仍是 best-effort HTML 抓取，不是官方 API。
- `--sources no-key`（别名 `free`、`no_key`）是严格免用户 API key 的替代组合，包含 Crossref、PubMed、Europe PMC 和 OpenReview；结果保留各自的 `source` 标识，不等同于 Google Scholar。Semantic Scholar 需要单独配置 key 才纳入高稳定性检索。

## 配置

多数免费元数据来源无需配置。为了稳定支持 agent 工作流，建议先运行 setup，把凭证写入用户级配置：

```bash
paper-search setup
paper-search config list --pretty
paper-search doctor --pretty
```

默认配置路径：

```text
~/.config/paper-search-cli/config.json
```

配置文件权限会写成 `0600`。`config list`、`doctor` 和相关命令都会脱敏密钥。

### API Key 分级

| 等级                       | 配置项                                                                                               | 用途                                                                       | 什么时候配置                                                                                                        |
| -------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| 多数用户推荐               | `SEMANTIC_SCHOLAR_API_KEY`                                                                           | 正文片段检索，以及更稳定的 Semantic Scholar 请求                           | 需要查方法细节或高频使用 Semantic Scholar 时配置                                                                    |
| 多数用户推荐               | `UNPAYWALL_EMAIL` 或 `PAPER_SEARCH_UNPAYWALL_EMAIL`                                                  | DOI 开放获取 PDF 解析                                                      | setup 时配置；需要的是邮箱，不是 API key                                                                            |
| 多数用户推荐               | `CROSSREF_MAILTO`                                                                                    | Crossref polite pool                                                       | 长任务或高频元数据检索时配置                                                                                        |
| 多数用户推荐               | `CORE_API_KEY`                                                                                       | CORE 仓储检索                                                              | 依赖 CORE 或遇到匿名限流时配置                                                                                      |
| 期刊指标                   | `EASYSCHOLAR_KEY`                                                                                    | EasyScholar 影响因子、JCR/SSCI、中科院分区、JCI、ESI、预警                 | 需要期刊指标时配置；建议用 `paper-search setup EASYSCHOLAR_KEY` 隐藏输入                                            |
| 生物医学高频               | `PUBMED_API_KEY`, `NCBI_EMAIL`, `NCBI_TOOL`                                                          | NCBI E-utilities 稳定性和更高限额                                          | 高频使用 PubMed 时配置                                                                                              |
| Key-backed 元数据和 OA API | `WOS_API_KEY`, `IEEE_API_KEY`, `ELSEVIER_API_KEY`, `SPRINGER_API_KEY`, `SPRINGER_OPENACCESS_API_KEY` | Web of Science、IEEE、Scopus、ScienceDirect、Springer 元数据或开放获取响应 | `ELSEVIER_API_KEY`、`SPRINGER_API_KEY` 同时驱动 `publisher_api` 全文层（权限随网络出口或 key）；其余 key 只做元数据 |
| Elsevier 校外全文          | `ELSEVIER_INSTTOKEN`                                                                                 | 随 `publisher_api` 的 Elsevier 请求发送的机构 token                        | 校外需要全文时配置；校园网出口不需要                                                                                |
| 机构下载扩展开关           | `PAPER_SEARCH_CARSI_ENABLED`                                                                       | 只有有效值精确为 `true` 时才启用机构下载扩展                               | `paper-search carsi install` 会自动设置；它不是 secret                                                     |
| Skill 自动更新             | `PAPER_SEARCH_SKILL_AUTO_UPDATE`                                                                   | 设为 `false` 时，升级后不再自动更新已安装的 Skill                          | 默认开启，不用配置；想自己管理 Skill 时设为 `false`                                                        |
| 通常可选                   | `OPENAIRE_API_KEY`                                                                                   | OpenAIRE 账号或配额场景                                                    | 公开检索通常不需要                                                                                                  |
| Scholar 网络出口           | `GOOGLE_SCHOLAR_PROXY_URL`                                                                           | 为 Google Scholar 指定 HTTP(S)/SOCKS 出口                                  | 直连反复触发反爬时再配置，必须使用有授权的代理                                                                      |
| Scholar 请求调节           | `SCHOLAR_RATE_LIMIT_RPS`, `SCHOLAR_MAX_RETRIES`, `SCHOLAR_TIMEOUT_MS`                                | 参考 bingshuoguo/google-scholar-mcp 的低流量限制                           | 保持保守默认值；这些不是 API key                                                                                    |

常用申请入口：

| 服务             | 链接                                                                                                    |
| ---------------- | ------------------------------------------------------------------------------------------------------- |
| EasyScholar      | [EasyScholar Open API](https://www.easyscholar.cc/console/user/open)                                    |
| Semantic Scholar | [Semantic Scholar API](https://www.semanticscholar.org/product/api)                                     |
| Unpaywall        | [Unpaywall API](https://unpaywall.org/products/api)                                                     |
| CORE             | [CORE API](https://core.ac.uk/services/api)                                                             |
| PubMed           | [NCBI API Keys](https://ncbiinsights.ncbi.nlm.nih.gov/2017/11/02/new-api-keys-for-the-e-utilities/)     |
| Web of Science   | [Clarivate Developer Portal](https://developer.clarivate.com/apis)                                      |
| IEEE Xplore      | [IEEE Xplore Metadata API](https://developer.ieee.org/docs/read/Searching_the_IEEE_Xplore_Metadata_API) |
| Elsevier         | [Elsevier Developer Portal](https://dev.elsevier.com/apikey/manage)                                     |
| Springer Nature  | [Springer Nature Developers](https://dev.springernature.com/)                                           |
| OpenAIRE         | [OpenAIRE APIs](https://develop.openaire.eu/)                                                           |

### 用学校订阅下载 PDF（机构下载扩展）

开放渠道拿不到、而学校订阅了的文章，由机构下载扩展开一个浏览器，用学校的权限取得 PDF。扩展随 PaperSearch 发布，一条命令安装（`paper-search setup` 最后也会问是否安装）：

```bash
paper-search carsi install
paper-search download "<DOI>" --platform crossref --save-path ./downloads
```

- 安装时会问你的学校（在 CARSI 成员学校列表里按中文名、英文名或域名查找），并下载专用浏览器 Camoufox，共需下载约 3 GB（`--browser ego` 改用 ego lite 时约 0.5 GB）。`--skip-school` 可以以后再选学校。
- 第一次需要学校权限时会弹出浏览器窗口。你只需要在学校统一认证页输入账号密码、遇到人机验证时点一下；选学校由程序按配置完成，之后的下载沿用这次登录。
- `paper-search carsi status` 查看状态，`paper-search carsi update` 在 PaperSearch 升级后更新扩展，`paper-search carsi uninstall` 卸载（默认保留浏览器和学校配置）。
- 每个 PDF 都核对首页的 DOI 或标题，不是这篇文章的不保存。失败会写明原因，例如学校没订阅、出版社没有接入 CARSI、需要登录、出版社暂停访问；`paper-search failures --format text` 汇总最近一批。
- Windows：PowerShell 拦住 `npm.ps1` 时改用 `npm.cmd` 或命令提示符；下载要在桌面会话里运行，经 SSH 或系统服务启动时浏览器窗口打不开。

`PAPER_SEARCH_CARSI_ENABLED` 是扩展的开关，安装时自动设为 `true`；请求级 `useEntitledAccess` 默认 `true`，只能关闭这一层，不能越过全局设置。需要传入论文标题或跳过本次 Sci-Hub 时，使用完整工具入口：

```bash
paper-search run download_with_fallback --json-args '{"source":"crossref","paperId":"<DOI>","doi":"<DOI>","title":"<论文标题>","savePath":"./downloads","useSciHub":false,"useEntitledAccess":true}' --pretty
```

`--platform` / `source` 指论文数据源；`useSciHub`、`doi` 和 `title` 属于 `download_with_fallback`，不是简写 `download` 的参数。两种入口共享 `primary -> direct_pdf_url -> repositories -> unpaywall -> publisher_api -> scihub -> entitled_access`，native downloader 只执行一次。前置来源成功就结束；Sci-Hub 失败或本次跳过后才继续可选授权层。

下载按专属 profile 互斥；`profile_busy` 时先等待现有任务。支持实时通知的后端按本次请求报告阶段，CLI 将固定提示写到 stderr，stdout 保持最终 JSON；旧后端无通知时不会猜测阶段。取消当前调用会触发所属子进程清理。最终 `attempts[].code` 区分登录、人工验证、超时、权限和文件问题，原始后端日志不会透传。

浏览器出现 PDF 或后端报告已保存，还需要产品核验文件及首页 DOI、请求提供的标题和正文身份。无法核实时返回 error，并可在 `review.path` 保留待核查文件；声明表或补充材料不算正文成功。`doctor=available` 只表示 executable/MCP 契约兼容，不证明已登录、单篇有权限或文件正确。CARSI 后端调用固定 `legal_only`，并关闭 Sci-Hub/Tor；后端 schema 枚举 `institutional_only` 时改用它，让后端跳过自己的公开来源竞速。成功也不是机构授权证明。

扩展的源码在本仓库 `carsi/`：Python 后端 `paper-search-carsi`，从 scansci-pdf 裁出、只保留机构下载，`doctor` 握手名为 `paper-search-carsi`，PaperSearch 经 MCP 调用它。

```
PaperSearch/
├── src/ tests/ scripts/ docs/ skills/      PaperSearch 本体（TypeScript）
├── acceptance/                             各出版社验收集，scripts/publisher-acceptance.mjs 运行
├── campus-proxy/                           暂存的 WebVPN / EZProxy 代码，未接入 PaperSearch
└── carsi/                                  CARSI 后端：机构下载（Python，MCP 服务）
    ├── bin/paper-search-carsi              启动脚本（PAPER_SEARCH_CARSI_EXECUTABLE 指向它）
    ├── tests/
    └── paper_search_carsi/
        ├── adapters/                       出版社适配器（按出版社和网站类型），没有适配器的出版社走通用流程
        ├── engine/                         通用下载引擎、选学校、PDF 核验、补充材料
        └── browser/                        浏览器后端（Camoufox / ego）
```

Scholar 调节默认值为 `SCHOLAR_RATE_LIMIT_RPS=0.5`、`SCHOLAR_MAX_RETRIES=2`、`SCHOLAR_TIMEOUT_MS=15000`。挑战页不会被盲目重试；应等待后再试，或改用严格 `no-key` 组合。没有自动安装或拉起 Go MCP；当前 Node 适配器复用了相同请求策略，避免新增 Go 运行时依赖。

## Agent Skill

npm 包会随包发布 agent Skill，位置是 `skills/paper-search/SKILL.md`。终端用户可以只用 CLI；AI agent 工作流应安装或同步 Skill，让 agent 正确路由五个主要功能。

```bash
paper-search setup --install-skills agents
paper-search skills status --pretty
paper-search skills diff --targets agents --format text
paper-search skills update --targets agents --pretty
```

支持的 target 包括 `agents`、`codex`、`claude`、`cursor`、`gemini`、`antigravity` 和 `all`。Skill 更新会覆盖 package-managed Skill 文件，同时保留 installed Skill 目录里的 extra files。

升级后自动更新：升级 PaperSearch 后第一次运行 `paper-search`（`skills`、`setup` 除外）时，它发现随包发布的 Skill 变了，就把你已经装过的 Skill 更新到新版本：只更新原来装过的位置，不往新位置装；保留你在 Skill 目录里自己加的文件；被替换的旧文件备份在 `~/.local/share/paper-search-cli/skill-backups/`；并在 stderr 写一行说明。一个 Skill 都没装时，只提示一次怎么装。不想自动更新时运行 `paper-search config set PAPER_SEARCH_SKILL_AUTO_UPDATE false`，之后用 `skills update` 手动同步。`paper-search doctor` 显示 Skill 装在哪里、是否最新。

Skill 只告诉 agent 如何调用 `paper-search` CLI。API key 仍然应通过 `paper-search setup`、`paper-search config`、`.env` 或 shell 环境变量配置。

## 命令

| 命令                           | 用途                                     |
| ------------------------------ | ---------------------------------------- |
| `paper-search search`          | 集成式元数据检索                         |
| `paper-search journal-metrics` | EasyScholar 期刊指标检索                 |
| `paper-search download`        | 对已核验 paper ID 或 DOI 下载 PDF        |
| `paper-search run`             | 用 `--arg` 或 `--json-args` 精确调用工具 |
| `paper-search tools`           | 运行时工具名和 schema                    |
| `paper-search doctor`          | 脱敏配置、Capability Profile 和平台状态  |
| `paper-search smoke`           | mock 或 live 自检                        |
| `paper-search skills`          | Bundled Skill 状态、diff 和同步          |
| `paper-search config`          | 用户级配置管理                           |

完整命令和工具 schema：运行 `paper-search tools --pretty`，或查看 [`skills/paper-search/references/cli-contract.md`](skills/paper-search/references/cli-contract.md)。

## 输出

命令默认返回 JSON。需要格式化 JSON 时使用 `--pretty`；需要可读报告时再使用 `--format text`。

```bash
paper-search search "machine learning" --platform crossref --max-results 1 --pretty
paper-search search "machine learning" --sources no-key --max-results 5 --pretty
paper-search doctor --format text
```

## 排障

| 问题                                              | 首先检查                                                                                                               |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| 找不到命令                                        | 用 `npm install -g papersearch` 重新全局安装                                                                      |
| 能力缺失                                          | 运行 `paper-search doctor --pretty`，再用 `paper-search setup` 配置缺失 key                                            |
| 机构下载扩展为 `disabled`、`absent` 或 `incompatible` | 运行 `paper-search carsi status` 查看原因；没装就运行 `paper-search carsi install`，装过就运行 `paper-search carsi update` |
| 平台限流                                          | 降低 `--max-results`，配置对应 key，或切换来源                                                                         |
| Skill 似乎过期                                    | 运行 `paper-search skills status --pretty`，再运行 `paper-search skills update --targets agents --pretty`              |
| 需要完整 CLI 细节                                 | 运行 `paper-search tools --pretty`                                                                                     |

## 使用边界

部分来源可能受平台条款、机构订阅或本地法律约束。只有在具备相应访问权和授权时才使用受限集成。机构下载扩展是可选的，其结果标签只作诊断，不能作为授权证明。

## 项目来源

本项目感谢 [LinuxDo](https://linux.do) 社区。CLI + Skill 路线和 paper-search 工作流改进来自社区交流与开源分享。

本项目也参考了 [openags/paper-search-mcp](https://github.com/openags/paper-search-mcp) 的思路，并将工作流调整为独立 CLI。

## License

MIT

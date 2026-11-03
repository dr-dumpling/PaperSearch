# PaperSearch 当前架构

本文是 `PaperSearch` 当前架构事实源，描述当前代码已经实现的能力、边界和仍存在的技术债。后续演进方向见 [`ROADMAP.zh.md`](./ROADMAP.zh.md)。

Agent 维护入口与任务路由见 `MAINTENANCE.zh.md`，领域词汇见 `GLOSSARY.zh.md`；与本文冲突时以**已实现代码 + ADR + contracts 测试**为准，并应同步回写 `docs/`。

---

## 1. 项目定位

`PaperSearch` 是一个面向 AI Agent、终端用户和脚本的学术文献工作 CLI。

- 语言 / 运行时：TypeScript + Node.js `>=18`，ESM 模块。
- 入口可执行文件：`paper-search`，由 `package.json` 的 `bin` 指向 `dist/cli.js`。
- 默认输出：JSON，便于 Agent 解析；需要可读报告时显式使用 `--format text` 或 `--pretty`。
- 随包发布：`skills/paper-search/`，作为 Routing Skill，告诉 Agent 何时调用 CLI、如何处理证据、配置和下载边界。

当前 CLI 围绕五个文献主能力工作：

| 能力            | 稳定能力名            | 主要入口                                                                         | 说明                                                                                  |
| --------------- | --------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 文献元数据检索  | `metadata_search`     | `paper-search search` / `paper-search run search_*`                              | 多平台论文元数据检索、DOI/PMID/PMCID 核验、文献初筛                          |
| 引文扩展        | `citation_expansion`  | `paper-search run get_paper_citations` / `paper-search run get_paper_references` | 基于 Semantic Scholar Graph API 查询已知论文的施引文献和参考文献                      |
| 期刊指标        | `journal_metrics`     | `paper-search journal-metrics` / `paper-search run query_journal_metrics`        | EasyScholar 期刊影响因子、JCR/SSCI、中科院分区、JCI、ESI、预警和等级字段              |
| PDF 发现 / 下载 | `pdf_discovery`       | `paper-search download` / `paper-search run download_with_fallback`              | 源生下载、元数据 PDF URL、仓储、Unpaywall、Sci-Hub fallback                           |
| 正文片段检索    | `body_snippet_search` | `paper-search run search_semantic_snippets`                                      | Semantic Scholar Open Access snippet 索引，用于查 Methods、参数、软件、模型和写法线索 |

`doctor`、`smoke`、`config`、`skills`、`tools` 属于 Friendly Management Layer，不是文献任务本身。

---

## 2. 当前顶层目录职责

```text
PaperSearch/
├── src/
│   ├── cli.ts                  # CLI 入口：参数解析、命令分发、输出包装
│   ├── core/                   # 工具定义、schema、工具路由、searchers 初始化和旧路径兼容 re-export
│   ├── capabilities/           # 五个文献主能力的 service、schema、tool、handler
│   ├── registry/               # 平台 metadata、factory、alias、HTTP policy registry
│   ├── infrastructure/         # HTTP、cache、rate-limit、security、PDF 下载与解析
│   ├── management/             # capability profile、diagnostics、smoke、text reports
│   ├── platforms/              # 各数据源 Searcher，继承 PaperSource
│   ├── services/               # 旧能力 service import 路径兼容 re-export
│   ├── config/                 # 配置和密钥管理、结果上限
│   ├── utils/                  # Logger / QuotaManager，以及旧 infrastructure import 路径兼容 re-export
│   ├── skills/                 # Bundled Skill 安装 / diff / update 逻辑
│   └── models/Paper.ts         # 统一论文数据模型
├── skills/paper-search/        # 随包发布的 Routing Skill 与 references
├── docs/                       # 架构、词汇、能力、依赖、契约、维护流程与历史报告
├── tests/                      # Jest 测试，目录结构大体镜像 src/
├── dist/                       # tsc 编译产物，发布用
└── package.json / tsconfig.json / .env.example
```

当前物理目录已经拆出 `capabilities/`、`registry/`、`infrastructure/` 和 `management/`。`core/`、`services/`、`utils/` 中仍保留若干兼容 re-export 和过渡汇总文件，避免破坏旧 import 路径。

---

## 3. 当前架构心智模型

### 3.1 六层代码骨架

```text
① CLI 入口层        src/cli.ts
       │
       ▼
② 契约汇总层        src/core/  (tools, schemas, handleToolCall, searchers, legacy re-exports)
       │
       ▼
③ 能力编排层        src/capabilities/ + src/management/
       │
       ▼
④ 数据源层          src/registry/ + src/platforms/
       │
       ▼
⑤ 基础设施层        src/infrastructure/ + shared src/utils/
       │
       ▼
⑥ 配置与模型        src/config/ + src/models/Paper.ts
```

### 3.2 三条正交轴

```text
       ③ 基础设施轴
       HttpClient · 限流 · 缓存 · 重试 · 超时 · 错误 · UA · 代理
              ▲
              │
① 能力域轴 ───┼────────────────────→ ② 数据源轴
metadata       │                       platformMetadata / platformFactories / aliases
citation       │                       Crossref / PubMed / OpenAlex / ...
journal        │
pdf            │
body snippets  │
management     │
```

判断规则：

- 是“用户可感知的功能”就归入能力域轴。
- 是“论文数据、PDF 候选或平台来源”就归入数据源轴。
- 是“所有常规 HTTP 请求都要共享的横切能力”就归入基础设施轴。

### 3.3 整体运转逻辑：一次下载请求的端到端流程

五个主能力里只有 `pdf_discovery` 会走出本进程；元数据检索、引文扩展、期刊指标和正文片段检索都在 ①→②→③→④ 之间完成并直接返回 JSON。下面以最长的一条路径——需要机构授权的 PDF 下载——串起两个仓库：

```text
用户 / Agent（终端、脚本、随包 Skill）
  │  paper-search download <id> --platform X      或  paper-search run download_with_fallback --json-args '…'
  ▼
① src/cli.ts            dotenv + 用户配置 → env；setupGlobalProxy；parseCli；选择命令
  ▼
② src/core/             TOOLS / inputSchema 校验 → handleToolCall(tool, args, searchers, { carsiBackend? })
                        carsiBackend 只在 PAPER_SEARCH_CARSI_ENABLED 精确为 true 且工具是 download_* 时创建
  ▼
③ capabilities/pdf-discovery/OpenAccessFallbackService.downloadWithFallback
  │   按 DownloadTier 顺序逐层尝试，首个 ok 结束漏斗；每层写一条脱敏 attempt { stage, status, message, code? }
  ├─ 1 primary          平台 Searcher 的源生 downloadPdf()（只走公开 / OA 接口）
  ├─ 2 direct_pdf_url   元数据里的公开 PDF URL
  ├─ 3 repositories     PubMed Central 官方渠道：DOI→PMCID（idconv）→ PMC Article Datasets（S3）→ Europe PMC getPdf
  ├─ 4 unpaywall        Unpaywall 全部 OA 位置；拦截非浏览器的出版社副本标 browser_only，留给第 7 层
  ├─ 5 publisher_api    用用户自己的 ELSEVIER_API_KEY / SPRINGER_API_KEY 直连出版社全文 API（本进程内，不开浏览器；ADR 0007）
  ├─ 6 scihub           PaperSearch 自己的 Sci-Hub（useSciHub:false → skipped；成功即结束，不再启动后端）
  └─ 7 entitled_access  只在前六层都没拿到正文时，经稳定 CarsiBackend port 委托给可选后端 ──────────┐
     每层保存的 PDF 都先过身份核对（DOI/标题），未核实即留待核查并继续下一层
                                                                                                     ▼
④ capabilities/pdf-discovery/carsi/CarsiMcpClient（进程外边界，后端 MCP 变化全部收口在这里）
     获取专属 profile 锁 .paper-search-download.lock
     → spawn `<executable> run`（MCP stdio 子进程；只注入 CARSI_DATA_DIR，不透传其余 env）
     → initialize → tools/list 契约探测（serverInfo.name = paper-search-carsi）
     → carsi_cache_clear(canonical DOI)
     → carsi_download(DOI, output_dir, strategy=institutional_only|legal_only, scihub_enabled=false, use_tor=false)
     → 接收 notifications/progress 固定阶段 → CLI 在 stderr 提示
     → 关闭子进程、释放锁
                                                                                                     │
═══════════════════ 进程边界：paper-search-carsi（Python，CARSI 后端，从 scansci-pdf 裁出，代码在本仓库 carsi/） ═══════════════════
                                                                                                     ▼
⑤ server.py（FastMCP）  progress_reporter.start_task → orchestrator.download_institutional(identifier, output_dir, strategy)
     ├ 只放行 DOI 形状的标识；同一 DOI in-flight 互斥；缓存命中且文件可读则直接返回
     └ engine/bridge.try_institutional(doi, output_path, config)      ← 没有任何机构配置时返回 None
         ├ 选出版社 profile：tier 1 publishers/builtin/*.json（可选 publisher_profiles_file 扩展），按 DOI 前缀或落地页域名；
         │    都对不上时按落地页网站生成 site:<注册域名>（publishers/site.py，只用通用规则）
         ├ 0 外部 instsci 包（仅已安装且非显式 CARSI）
         ├ 1 出版社驱动（唯一的驱动）：session broker（目前没有启动入口，不会运行；显式 CARSI 时也跳过）→ engine/batch.PublisherBatchDownloader
         │    读 tier 1 profile（URL 模板、SSO 选择器、页面标记）+ tier 2 adapters/ 出版社适配器（通用流程判断不了的钩子）→ 可见浏览器 → 出版社机构登录（选 CARSI 联盟和学校）→ 捕获 PDF
         │    配置了学校时自动选校和继续，人机验证与凭证由用户在窗口里完成
         └ DOI 指向的不是能登录的网站（解析失败、PDF 文件、不支持的平台）时什么也不跑，结果为 unsupported_publisher；
              site 规则的文章页上找不到机构入口时结果为 generic_institution_entry_missing（都归暂不支持的网站）
       失败聚合：程序错误 > 内容错误 / 封禁 / 登录结果 / 超时 > 授权缺失（reason_code）> 普通 miss，全部保留在 source_failures
       返回 {success, file, source} 或 {success:false, error_type, reason, action, reason_code?, source_failures}
                                                                                                     │
═══════════════════════════════════════════ MCP tool result 原路返回 ═══════════════════════════════════════════
                                                                                                     ▼
④ CarsiResultNormalizer   严格 JSON 解析；只有 success===true 且 file 非空才是候选成功；错误码映射为本地固定分类并脱敏
                                                                                                     ▼
③ tiers/entitledAccess.ts   isValidPdfFile → verifyPdfIdentity(前三页 DOI 与题目、附件/声明判断；扫描件按来源地址)
                            verified → attempt ok + path；mismatch / unreadable / unverified → attempt error + review.path（不计成功）
  ▼
② 组装 { success, path?, format?, attempts[] } → diagnoseToolResult（补全 remediation）
  ▼
① stdout 只输出一份最终 JSON；stderr 只放实时阶段提示；凭证从不经过任何一层
```

两个仓库的分工：

| 仓库                         | 语言       | 负责                                                                                                                                                | 明确不负责                                                         |
| ---------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `PaperSearch`           | TypeScript | 五个文献能力、下载漏斗顺序、key 型 `publisher_api`、Sci-Hub、后端 readiness 与契约探测、结果规范化、PDF 身份核验、管理层、随包 Skill                | 浏览器、SSO、CARSI、WebVPN、EZProxy 等任何需要登录窗口的路径       |
| `paper-search-carsi` | Python     | 机构阶段本身：出版社浏览器捕获（经 CARSI 等联盟登录）、出版社 profile 三级结构（JSON → 适配器 → 机构入口）、MCP server、本地 setup/login | 公开 / OA / 灰色来源、key 型出版社 API、最终身份核验、Sci-Hub、Tor |

WebVPN、EZProxy（经学校的网关或代理，用学校 IP 访问出版社）不是 CARSI 后端的路线：代码暂存在仓库根目录 `campus-proxy/`，不接入下载流程。

读这张图的两个要点：

1. **单一 owner**：每条路线只在一个仓库里实现。Sci-Hub 和 key 型 API 在 PaperSearch，浏览器型路线在后端；后端里原有的 Elsevier API 路径已于 2026-10-29 删除（ADR 0007）。
2. **边界是两个稳定接口**：进程内是 `CarsiBackend` port（③ 只认识它），进程外是 MCP 工具契约（④ 只认识它）。后端改了工具 schema，先在 ④ 判 `incompatible`，不会穿透到 ③ 以上。

---

## 4. 能力域边界

| 能力域              | 当前实现位置                                                                                                                                        | 依赖                                                              | 边界规则                                                               |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------------- |
| metadata search     | `capabilities/metadata-search/` + `platforms/*`                                                                                                     | `Searchers`、`PaperSource`、`platformMetadata`                    | 负责构建和核验论文元数据列表，不直接承担 PDF 下载策略                  |
| citation expansion  | `capabilities/citation-expansion/`                                                                                                                  | Semantic Scholar Graph API                                        | 不进入普通平台搜索工具生成，不等同于关键词检索                         |
| pdf discovery       | `capabilities/pdf-discovery/`                                                                                                                       | `Searchers`、`DownloadTier`、`PdfDownload`、可选 `CarsiBackend` | 消费已知论文标识，编排下载、核验 PDF 并记录 attempts                   |
| journal metrics     | `capabilities/journal-metrics/`                                                                                                                     | EasyScholar                                                       | 独立于论文平台检索，不进入论文数据源注册表                             |
| body snippet search | `capabilities/body-snippet-search/`                                                                                                                 | Semantic Scholar OA snippet index                                 | 使用 `limit`，不是 `maxResults`；返回 snippet 线索，不代表完整全文解析 |
| management layer    | `management/capability-profile/`、`management/diagnostics/`、`management/smoke/`、`management/reports/`、`management/config/`、`management/skills/` | 读取其它模块状态                                                  | 只能读状态、给诊断和同步 Skill；功能模块不反向依赖管理层               |

关键约束：

1. `metadata_search` 与 `pdf_discovery` 通过 `Paper`、DOI、title、source 解耦。
2. `citation_expansion` 是独立能力，不塞进普通 metadata platform search。
3. `journal_metrics` 只处理期刊，不处理论文元数据。
4. `body_snippet_search` 保持 Semantic Scholar 私有 schema，不被普通平台 schema 泛化。
5. management layer 是友好管理支线，不参与文献任务主流程。

---

## 5. 主要数据流

### 5.1 CLI 启动

```text
cli.ts
  → dotenv.config()
  → loadUserConfigIntoEnv()
  → setupGlobalProxy()
  → parseCli(argv)
  → run(parsed)
```

密钥只来自环境变量、`.env` 或用户配置文件。Skill、README、测试和日志不得写入真实密钥。

### 5.2 `paper-search run <tool>`

```text
cli.ts
  → parseJsonArgs / parseArgFlags / flagsToArgs
  → assertToolName(tool)
  → initializeSearchers()
  → carsiBackendForToolCall(tool, args)
  → handleToolCall(tool, args, searchers, { carsiBackend })
      → parseToolArgs(tool, args)
      → read dependencies.carsiBackend only for public download handlers
      → route to capability or platform searcher
  → extract text / JSON payload
  → diagnoseToolResult()
  → JSON output
```

`handleToolCall(toolNameRaw, rawArgs, searchers, dependencies = {})` 的第 4 个参数是内部依赖注入边界；当前 `ToolCallDependencies` 只包含可选 `carsiBackend?: CarsiBackend`。它不进入公开 tool schema，也不是 provider selector。`TOOLS`、`parseToolArgs()`、`handleToolCall()` 是当前最重要的 CLI 契约三角。后续任何注册表派生都必须保持三者对外输出不变。

### 5.3 metadata search

```text
paper-search search "query"
  → search_papers
  → SearchPapersSchema
  → searchMultipleSources(searchers, query, sources, options)
      → parse source list / alias normalize
      → per-source search with timeout isolation
      → Promise.allSettled
      → dedupe by DOI, title+author, source id
  → { sources_used, source_results, errors, failed_sources, total, papers }
```

特点：多源并发、单源失败不阻塞整体、结果去重、默认 JSON 输出。

### 5.4 citation expansion

```text
paper-search run get_paper_citations / get_paper_references
  → CitationLookupSchema
  → resolveCitationTarget(paperId > doi > arxivId)
  → CitationService.getCitations() / getReferences()
  → Semantic Scholar Graph API
  → { target, relation, provider, total, papers }
```

`doi` 会转换成 `DOI:<doi>`；`arxivId` 会转换成 `ARXIV:<id>`；`limit` 默认为 100，范围 1–100。

### 5.5 PDF fallback

当前 `download_with_fallback` 已经通过 `DownloadTier` 执行默认下载层：

```text
download_with_fallback
  → build DownloadTierContext
  → createDefaultDownloadTiers()
      1. primary
      2. direct_pdf_url
      3. repositories
      4. unpaywall
      5. publisher_api (ELSEVIER_API_KEY / SPRINGER_API_KEY full-text APIs)
      6. scihub
      7. entitled_access (optional CarsiBackend)
  → first ok path returns success
  → otherwise returns error with attempts
```

当前已支持：

- `createDefaultDownloadTiers()` 生成默认下载层。
- `publisher_api` tier 用用户自己的 `ELSEVIER_API_KEY` / `SPRINGER_API_KEY` 走出版社全文 API（ADR 0007）：Elsevier 返回 PDF 并按页数剔除未授权的 1 页预览，Springer TDM 返回 JATS XML 并以 `format: "jats-xml"` 标出；按 DOI 前缀选择，未配置 key 时 skipped。
- `createDefaultDownloadTiers(carsiBackend?)` 只通过稳定 `CarsiBackend` port 注入可选外部后端。
- `insertDownloadTierBefore()` 在指定 stage 前插入扩展 tier。
- `downloadWithFallback(searchers, options, tiers)` 注入自定义 tiers。
- `download_paper` 与 `download_with_fallback` 使用同一漏斗，native download 只由 `primary` tier 执行一次。
- direct metadata fallback 优先使用 `doi || paperId`。
- Unpaywall searcher 缺失时返回 `skipped`。
- 默认 attempts 包含 `entitled_access`；全局关闭、请求关闭或后端 unavailable 时为 `skipped`。旧名 `institutional_access` 不存在。

Entitled Download Backend 只有一个可选实现：`paper-search-carsi`（CARSI 后端：从 scansci-pdf 裁出、只保留机构阶段的 Python 包，代码在本仓库 `carsi/`；握手时 `serverInfo.name` 必须为 `paper-search-carsi`）。它默认关闭，只有 `PAPER_SEARCH_CARSI_ENABLED` 的有效值精确为 `true` 才创建 backend；请求级 `useEntitledAccess` 默认 `true`，只能进一步关闭。下载 tier、readiness 和 management layer 只依赖项目自有稳定 `CarsiBackend` port，MCP tool/schema 变化收口在 adapter/factory。`metadata_entitled` 仍只描述 key-backed 元数据，不等于授权 PDF 获取；开放获取、repository、Unpaywall 和 Sci-Hub 继续独立工作。

用户仍通过 `paper-search config` 配置、`paper-search download` 或 `paper-search run download_with_fallback` 下载。`PAPER_SEARCH_CARSI_EXECUTABLE` 只是可选的安装路径配置；`paper-search-carsi run` 是 adapter 启动 MCP 服务的内部命令。二者不增加主能力、论文数据源或公开下载参数，具体命令风格见 CLI 契约。

授权层在专属 profile 内互斥执行清缓存与下载，并负责取消和子进程清理。支持通知的后端按本次 MCP 请求 token 上报固定阶段；CLI 在 stderr 显示本地提示，stdout 保持最终 JSON。取得文件后还须核验 PDF 首页 DOI、请求提供的标题及正文身份；不确定文件返回 `error + review`，不能因浏览器显示 PDF 就成功。单篇失败不改变全局 readiness。

实际下载浏览器、按配置自动选校、登录会话复用、只读进度及出版社规则扩展属于后端 `paper-search-carsi`（本仓库 `carsi/`，打包进 PaperSearch，用 `paper-search carsi install` 安装，ADR 0013）；它的内部顺序见 3.3 节 ⑤，在契约之外的行为见 CARSI 后端说明，出版社规则见 出版社适配。PaperSearch 与后端的契约见 后端规格。

### 5.6 management layer

```text
doctor/status/smoke/skills/config/tools
  → 读取配置、能力画像、平台状态、Skill 安装状态
  → 输出脱敏 JSON 或显式 text report
```

这条支线的目标是让工具“可被正确使用”，而不是替代文献检索实现。

---

## 6. 核心抽象现状

### 6.1 `PaperSource`

所有平台 Searcher 继承 `PaperSource`，统一暴露：

- `search(query, options)`
- `downloadPdf(paperId, options)`
- `readPaper(paperId, options)`
- `getCapabilities()`
- `getPaperByDoi(doi)` 等公共能力

新增普通平台的算法适配主要写在新的 `platforms/XxxSearcher.ts`。

### 6.2 `platformMetadata`

`registry/platformMetadata.ts` 是当前数据源注册表事实源，记录：

- `id`
- `aliases`
- `displayName`
- `sourceKind`
- `defaultInAll`
- `directTool`
- `toolName`
- `configKeys`
- `optionalConfigKeys`
- `supportedOptions`
- `schemaKind`
- `optionCaps`
- `capabilityGroups`
- `supportsDoiLookup`
- `isRepository`
- `description`

当前已实现的派生辅助：

- `resolvePlatformId()`
- `getDefaultAllSources()`
- `getAliasMap()`
- `getPlatformToolDescriptors()`
- `getGenericPlatformToolDescriptors()`
- `getGenericSearchToolPlatform()`
- `getGenericSearchToolNames()`

当前仍有部分清单尚未完全从 metadata 派生，例如 capability profile source group、DOI lookup source、repository fallback source 等。

### 6.3 `PlatformFactoryRegistry`

`registry/platformFactories.ts` 集中维护平台实例化：

```text
PLATFORM_FACTORIES: Record<string, PlatformFactory>
```

`initializeSearchers()` 当前基于 `PLATFORM_METADATA` 遍历平台，使用 factory 创建 canonical instance，并自动为 `aliases` 写入同一实例。

当前仍保留 `Searchers` 手写接口作为过渡类型，避免一次性改动所有调用方。

### 6.4 `HttpClient` 与 `HttpPolicy`

`infrastructure/http/HttpClient.ts` 当前已经定义最小 scaffold：

- `HttpPolicy`
- `HttpRequestConfig`
- `HttpClient.request<T>()`
- `setupGlobalProxy()`

`registry/httpPolicies.ts` 当前已有少量平台策略示例，例如 Crossref、OpenAlex；`core/httpPolicies.ts` 仅保留旧路径兼容 re-export。

需要注意：当前 `HttpClient` 还不是完整统一请求层。它已经处理 timeout、validateStatus、userAgent 的最小包装，但尚未完整执行 rate limit、cache、retry、统一错误分类和平台迁移。

### 6.5 `DownloadTier`

`DownloadTier` 是当前 PDF fallback 的下载层接口：

```ts
export interface DownloadTier {
  id: string;
  stage: string;
  run(context: DownloadTierContext): Promise<DownloadTierResult>;
}
```

默认下载层顺序已经稳定为 `primary -> direct_pdf_url -> repositories -> unpaywall -> publisher_api -> scihub -> entitled_access`。PaperSearch Sci-Hub 成功会结束漏斗而不启动 CARSI 后端；Sci-Hub 失败或被请求级关闭后才进入可选 `entitled_access`。`DownloadTier` 只把 `entitled_access` 请求委托给可选 CARSI 后端并规范化结果；项目不保留本地 浏览器、WebVPN、CARSI 或 EZProxy fallback。CARSI 后端固定 `legal_only`（后端 schema 显式枚举 `institutional_only` 时改用它，让后端跳过自己的公开来源竞速；无枚举的字符串 schema 保持 `legal_only`）、`scihub_enabled=false`、`use_tor=false`，但 `legal_only` 不等于 `entitled_only`，success 不能作为机构授权证明。

---

## 7. 稳定契约

后续重构必须保持以下契约不变：

- `paper-search tools --pretty` 工具名集合。
- 每个工具的 `inputSchema`、`required`、enum、默认参数语义。
- `paper-search run` 的 unknown tool 错误行为。
- `search_papers`、`get_paper_by_doi`、`download_with_fallback`、`query_journal_metrics` 的 JSON 输出结构。
- `download_with_fallback` attempts 顺序和字段结构。
- alias 解析：如 `wos -> webofscience`、`scholar -> googlescholar`、`springerlink -> springer`。
- Capability Profile 的能力名和状态判定边界。
- Skill / README 明确 CARSI 后端是默认关闭的唯一可选 Entitled Download Backend，且不声称本地机构或出版商授权下载路径存在。

当前已有契约测试覆盖：

- tools schema surface；
- platform alias；
- capability profile；
- fallback attempts；
- Skill Direct Run Tools 与 `TOOLS` 同步。

---

## 8. 当前技术债

| 债务                                                     | 当前表现                                                                                                                                                           | 后续方向                                                                                                                            |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| 数据源事实源未完全收敛                                   | `platformMetadata` 已扩展，但 capability profile、DOI lookup、repository fallback 仍有部分手写清单                                                                 | 继续从 `capabilityGroups`、`supportsDoiLookup`、`isRepository` 派生                                                                 |
| HttpClient 仍是最小 scaffold                             | 已有 `HttpPolicy` / `HttpClient.request()`，但尚未实现完整 rate limit/cache/retry/error 分类，也未迁移所有平台                                                     | 先迁移少量免费稳定平台，再逐步扩展                                                                                                  |
| 旧路径兼容层仍存在                                       | `core/`、`services/`、`utils/` 保留 re-export，部分调用方仍使用旧 import                                                                                           | 后续单独阶段清理旧 import，不与行为改动混做                                                                                         |
| Searchers 类型仍手写                                     | 实例化已由 factory registry 驱动，但 `Searchers` 接口仍显式列出字段                                                                                                | 后续可用更宽的 registry 类型过渡，减少手写字段                                                                                      |
| 后端 `paper-search-carsi` 覆盖验收未完成 | 后端打包进 PaperSearch、一键安装（ADR 0013）；已有规则的出版社都有验收集（见 dev 记录 第 7 节）；冷启动、部分出版社入口和校外访问仍有缺口 | 按 dev 记录 第 6 节推进；不把历史 Nature 失败、单样本成功或 readiness 泛化为全部平台状态 |

---

## 9. 后续路线

后续路线见 [`ROADMAP.zh.md`](./ROADMAP.zh.md)。

# PaperSearch Roadmap

本文记录当前架构之外的后续演进方向。当前事实源是 [`ARCHITECTURE.zh.md`](./ARCHITECTURE.zh.md)。本文不是当前实现说明，也不是立即执行任务书。

---

当前已实现的能力一律见 [`ARCHITECTURE.zh.md`](./ARCHITECTURE.zh.md)，本文只列未完成项。已经开工的主题，目标、进展和待做写在 `dev/`；已完成的归档在 `history/`。

---

## 1. Registry 派生继续完善

当前 registry 已经支持：

- `defaultInAll` 派生 default all sources。
- `doiLookupOrder` 派生 `get_paper_by_doi all` sources。
- `repositoryFallbackOrder` 派生 repository fallback sources。
- `capabilityProfileSources` 派生 capability profile source groups。
- `schemaKind` 区分 generic 与特殊 schema 工具。

后续可继续完善：

- diagnostics 里的 direct tool / platform 映射从 metadata 派生。
- 普通平台工具 schema 进一步由 schema registry/factory 管理。
- Searcher factory context 的特殊依赖关系继续显式化，例如 USENIX 复用 DBLP。
- 新平台 onboarding 继续收敛到 “Searcher + metadata + factory + tests” 四件套。

约束：

- 只有 `schemaKind: 'generic'` 的平台可以走 generic schema。
- `search_core`、`search_google_scholar`、`search_scopus`、`search_semantic_snippets` 等特殊工具必须保留特殊 schema。
- `citation_expansion`、`journal_metrics`、`pdf_discovery`、`body_snippet_search` 不应被当作普通平台搜索源。

---

## 2. HttpClient 落地

当前 `HttpClient` 仍是 scaffold，尚未完整执行 rate limit、cache、retry 和统一错误分类。

后续目标：

- 在 `HttpClient.request()` 中逐步实现：
  - rate limit；
  - cache；
  - retry；
  - timeout；
  - user-agent；
  - validateStatus；
  - proxy；
  - error classification；
  - 脱敏日志。
- 让平台常规 HTTP 请求逐步停止直接 `import axios`。
- 先迁移少量免费、稳定、易 mock 的平台，例如 Crossref、OpenAlex。
- 避免一次性迁移全部平台。

验收方向：

- 迁移平台的测试能 mock `HttpClient`。
- 未迁移平台行为不变。
- `setupGlobalProxy()` 继续兼容现有 CLI 启动流程。

---

## 3. Live smoke 与错误分类

当前 mock smoke 和核心契约测试已经覆盖主要 wiring。后续可以增强 live smoke 的错误分类：

- DBLP / USENIX timeout 明确归类为外部服务或网络 degraded。
- ScienceDirect / Springer metadata API 401 明确归类为 credential 或 API product-permission issue，不解释为 Authorized PDF Retrieval 状态。
- bioRxiv / IACR 原生 PDF 403 明确归类为 native source degraded，并保留 repository fallback。
- doctor/status 输出中继续脱敏 key、token、session、URL 凭据。

约束：

- live smoke 不应成为单元测试依赖。
- live smoke 失败不应让 mock smoke 失败。
- key-backed publisher metadata 不应被描述成 Authorized PDF Retrieval 或 guaranteed full-text access。

---

## 4. DownloadTier 后续增强

当前 PDF fallback 顺序为：

```text
primary -> direct_pdf_url -> repositories -> unpaywall -> publisher_api -> scihub -> entitled_access
```

当前已经支持：

- `createDefaultDownloadTiers()`。
- `insertDownloadTierBefore()`。
- `downloadWithFallback(..., tiers)` 注入自定义 tier。
- 单一顺序 `primary -> direct_pdf_url -> repositories -> unpaywall -> publisher_api -> scihub -> entitled_access`，且 `download_paper` 的 native download 只执行一次。
- 默认 attempts 包含 `entitled_access`，不包含旧名 `institutional_access`。
- repository sources 从 registry 派生。
- CARSI 后端作为默认关闭的唯一可选 Entitled Download Backend；精确 `PAPER_SEARCH_CARSI_ENABLED=true` 才启用，`useEntitledAccess` 只能进一步关闭。
- `doctor`、`setup`、live smoke 报告 `disabled` / `absent` / `incompatible` / `available`；mock/offline snapshot 不 spawn，并报告 `not_evaluated`。
- 工作区已接入可选 executable 配置、专属 profile 下载互斥与取消清理、固定 `attempts[].code`、待核查文件 `review` 和首页 DOI/标题/正文身份校验。
- 产品已处理按 MCP 请求 token 绑定的固定阶段通知，CLI 写 stderr，默认 stdout 保持最终 JSON；旧后端无通知时仍兼容。

浏览器型路线住在本仓库 `carsi/` 目录的 `paper-search-carsi`（从维护者的 scansci-pdf 分叉裁出，MIT，只保留机构阶段），打包进 PaperSearch，用 `paper-search carsi install` 安装（ADR 0013）。后端内的 Elsevier API 路径与旧出版社直连路线已删除，只剩出版社浏览器捕获（经 CARSI 等联盟登录）和 Cookie 快路径，WebVPN、EZProxy 已移到仓库根目录 `campus-proxy/` 暂存、不接入；旧的通用 CARSI 驱动已于 2026-11-02 删除。进度、验收和待办见 `dev/institutional-backend.zh.md`，在契约之外的行为见 CARSI 后端说明。

### 4.1 后端 `paper-search-carsi`（`carsi/`）的待办

这些项在 `carsi/` 里完成，PaperSearch 只需在契约或 README 变化时同步：

- 发布：一键安装阶段 1–6 见 `dev/institutional-installer.zh.md`；随 PaperSearch 的下一个 npm 版本发布（版本号由用户定）。
- 真实验收：各出版社验收集和冷启动验收（`acceptance/cold-start.json`），见 dev 记录第 6、7 节。
- 出版社贡献流程：tier 1 JSON 的贡献指南与 schema 校验、`publisher-check --doi` 作为贡献者自检；清理 `elsevier.json` 里残留的单一学校选择器。
- 可选的 `download_batch` 工具（同一出版社多篇共享一次登录），需要先在契约探测里作为可选工具处理。

### 4.2 PaperSearch 侧可以增强

- Capability Profile 暴露 `publisher_api` 的可用性（哪些出版社 key 已配置），并考虑更多 key 型全文 API 适配器（例如 Wiley TDM）。

- 在既有授权层固定错误码基础上，完善其他 tier 的错误分类与 remediation，不重复新增另一套后端命令。
- 对 native source 403 / 401 / timeout 形成更清晰的 fallback reason。
- 后端的真实产品 MCP 进度链、新用户/其他学校及剩余出版社入口验收由后端仓库完成后，再更新这里的支持矩阵；不以离线测试代替实测。
- 保留补充材料接口，后续扩展正文同一 context 内的全部附件发现、抓取、角色核验和清单交付；当前只验收正文 PDF，不声称附件齐全。
- 浏览器型 Authorized PDF Retrieval 只委托给可选 Entitled Download Backend（CARSI 后端 `paper-search-carsi`）。CLI 保留下载编排、key 型 `publisher_api`、结果规范化和 PDF 校验，但不实现浏览器、WebVPN、CARSI、EZProxy 或其它本地授权 fallback。
- `metadata_entitled`、开放获取来源、repository、Unpaywall 和 Sci-Hub 保持独立；不得因为后端规划而合并或删除。
- 兼容新增可自动接受，可检测破坏保持 `incompatible` 并只修改 adapter/factory；不承诺后端任意改动零修改。
- 历史实施与验证报告见 `history/`；长期后端规格见 `dependencies/carsi-backend.zh.md`；CARSI 后端在契约之外的行为见 `dependencies/carsi-backend-notes.zh.md`。

---

## 5. Skill 与 CLI 契约持续同步

继续保持：

- `skills/paper-search/references/cli-contract.md` 与 `TOOLS` 同步。
- `SkillContract.test.ts` 校验 Direct Run Tools 与源码工具注册表一致。
- README 不声称未来能力已经实现。
- Skill 不保存私密配置值。
- 工具名、inputSchema、JSON 输出和 Capability Profile 改动必须同步 contracts 和 tests。

---

## 6. 机构下载后端（`carsi/`）

进行中：最终目标、已完成、待做见 `dev/institutional-backend.zh.md`。

---

## 非目标

本文不要求立即执行任何代码改造。

除 CARSI 后端相关规格已单独定义的内容外，本文不定义：

- `paper-search carsi install|status|update|uninstall` 之外的后端命令、账号登录流程或 provider selector；
- 新的 top-level citation command；
- 默认启用 Authorized PDF Retrieval；
- 删除 Sci-Hub fallback；
- 改变当前 Agent-facing JSON 输出结构；
- 在用户没有运行 `paper-search carsi install` / `update` 时安装或升级后端；
- 删除旧 re-export 兼容层。

## 已移除的来源

- arXiv（2026-10-31，维护者决定）：不再作为检索或下载来源；Semantic Scholar 返回的 arxiv.org PDF 链接也不使用。引文扩展仍接受 arXiv ID 作为论文标识（经 Semantic Scholar 查询，不访问 arXiv）。

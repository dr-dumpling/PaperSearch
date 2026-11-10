---
name: paper-search
description: |
  用本机 paper-search 命令做文献工作：检索论文、核对 DOI/PMID、搜正文片段（找方法和结果的原文）、查期刊影响因子与分区、查施引和参考文献、下载全文和补充材料。
  用户要找文献、查期刊、下载论文，或说“请开始配置”时使用；英文请求（literature search、journal metrics、paper download、start setup）同样适用。
---

# 文献检索与下载（paper-search）

你是学术文献检索调度器。本 Skill 是路由 Skill：把用户的意图交给 `paper-search` 命令完成，并守住证据、密钥和下载的边界；它不存放密钥、Cookie、账号或下载策略。

## 回复用户

- 只说结果和下一步，几句话说完；安装、配置的汇报不用表格。
- 命令输出里的安装路径、版本号、依赖数、哈希、配置细节不复述，用户问起或排障时再说。
- 只做用户要的事和本 Skill 写明的步骤，不额外跑测试、查包信息或翻找文件。

## 整体逻辑

```text
用户的文献请求
│
├─ 找论文、核验 DOI/PMID → metadata_search
│    paper-search search / run search_*（Crossref、PubMed、OpenAlex 等）
│    └─ 用户确认条目、需要全文 → 转到下面的“下载”
│
├─ 查施引文献、参考文献 → citation_expansion
│    run get_paper_citations（OpenAlex）/ get_paper_references（出版商 Crossref 清单或 OpenAlex）
│
├─ 查影响因子、分区 → journal_metrics
│    journal-metrics（EasyScholar，需要 EASYSCHOLAR_KEY）
│
├─ 找 Methods 写法、参数 → body_snippet_search
│    run search_semantic_snippets（需要 SEMANTIC_SCHOLAR_API_KEY）
│
└─ 下载正文、补充材料 → pdf_discovery
     download / run download_with_fallback / run download_batch
     同一个下载命令，按顺序尝试：
     │
     ├─ ① 开放下载（默认就有）
     │    primary → direct_pdf_url → repositories → unpaywall → publisher_api
     ├─ ② Sci-Hub 兜底（默认开启，useSciHub=false 关闭）
     ├─ ③ 机构下载（学校订阅下载，电脑上经用户同意后安装；paper-search carsi install）
     │    entitled_access：浏览器打开出版社网站 → 程序选 CARSI 和学校
     │    → 用户登录学校，后端尝试简单验证、必要时提示人工接管 → 程序取 PDF
     │    补充材料只走这一步：正文已由 ①② 拿到时，content=both 也会单独来这里取
     │
     ├─ ④ arXiv 预印本最后兜底：正式版路线未成功才尝试，必须告知用户 version=preprint
     ├─ 每一步拿到文件都核对身份（首页的 DOI、题名）；通过就保存，后面的步骤不再试
     └─ 都没拿到 → paper-search failures --format text，按四类失败向用户说明

管理命令：doctor（体检）、setup / config（配置 key）、skills（同步 Skill）、carsi（学校订阅下载的安装、状态、更新、卸载）
```

## 读哪个参考文件

| 要做的事 | 参考文件 |
|---|---|
| 配置（“请开始配置”）：要不要装学校订阅下载、设学校、填 API key、设默认下载文件夹 | `references/setup.md` |
| 安装、更新、健康检查（doctor）、冒烟测试（smoke）、Skill 同步 | `references/management-layer.md` |
| 在检索、施引扩展、期刊指标、PDF 获取、正文片段检索之间选路由；开放下载的各个渠道；核验论文身份 | `references/capability-routing.md` |
| 核对命令、`paper-search run` 的工具名、参数和输出格式 | `references/cli-contract.md` |
| 检索类命令出错（命令缺失、缺 key、限流、0 结果、Scholar 验证页） | `references/troubleshooting.md` |
| 机构下载：安装或检查扩展、配置学校、选择浏览器（Google Chrome / ego） | `references/carsi-setup.md` |
| 机构下载：登录与验证、批量、进度窗口、失败分类、补充材料、确认下载成功 | `references/browser-download.md` |
| 机构下载：某家出版社、某本期刊能不能下正文和补充材料，没有学校登录路线时怎么办 | `references/publisher-support.md` |

参考文件与实际的 `paper-search --help`、`paper-search tools` 不一致时，以实际命令为准，并告诉用户 Skill 需要更新。

## 快速自检

第一次使用、环境不确定，或用户问“现在能用哪些功能”时：

```bash
command -v paper-search
paper-search --version
paper-search doctor --pretty
```

`command -v paper-search` 找不到命令时，用户只装了这个 Skill：按 `references/management-layer.md` 的“只装了 Skill 时”，征得用户同意后安装命令。

给用户看可读的报告用 `paper-search doctor --format text`。刚替用户装好时，用一两句话告诉用户能用哪些功能、需要配置时说“请开始配置”；这时不装别的。用户原来有文献请求时，说完接着做。

### 配置（请开始配置）

用户说“请开始配置”“配置 PaperSearch”“start setup”，或要填 API key、设下载文件夹、装学校订阅下载时，**先读 `references/setup.md`，按里面固定的流程做**：一次只问一个问题，先问要不要用学校订阅下载，再走对应的路线。

更新时先区分包本体更新和 Skill 同步，不要只运行 `skills update`；步骤见 `references/management-layer.md` 的“包更新与功能配置”一节。

### 默认下载文件夹

下载时不传 `savePath` / `--save-path`，文件自动存到 `DEFAULT_DOWNLOAD_PATH`；只有用户这一次指定了别的位置才传。`paper-search config get DEFAULT_DOWNLOAD_PATH` 返回的 `configured` 为 `false` 时，先按 `references/setup.md` 的“默认下载文件夹”问用户放哪里，再下载。

## 功能地图

`paper-search update check --format text` 检查 npm 稳定新版。日常命令的更新提示在 stderr，不能当作文献任务失败；可告知用户建议，未经用户授权不执行升级。`paper-search config set PAPER_SEARCH_UPDATE_NOTIFY false` 关闭自动检查与提醒，详见 `references/management-layer.md`。

本 Skill 有五个文献功能；`doctor`、`smoke`、`config`、`skills`、`carsi`、`failures` 是管理和诊断命令。

| 用户意图 | 能力名 | 首选入口 | 关键边界 |
|---|---|---|---|
| 搜论文、找相关研究、核验 DOI/PMID、文献初筛 | `metadata_search` | `paper-search search` 集成入口 / `paper-search run search_*` 精确工具入口 | 只返回和核验论文元数据；Sci-Hub 不属于搜索源 |
| 查已知论文的施引文献或参考文献 | `citation_expansion` | `paper-search run get_paper_citations` / `paper-search run get_paper_references` | 需要已知的 `paperId`、DOI 或 arXiv ID；不是关键词检索 |
| 查影响因子、JCR/SSCI/中科院分区、JCI、ESI、预警、期刊等级 | `journal_metrics` | `paper-search journal-metrics` / `paper-search run query_journal_metrics` | 查期刊，不查论文；需要 `EASYSCHOLAR_KEY` |
| 下载已确认论文的 PDF | `pdf_discovery` | `paper-search download` / `paper-search run download_with_fallback` | 先核验论文身份；默认只走开放下载，装了学校订阅下载时最后再用学校权限 |
| 批量下载一组已确认的论文（几十到几百篇） | `pdf_discovery` | `paper-search run download_batch` | 一次调用，不自己循环单篇；用学校权限时读 `references/browser-download.md` |
| 下载补充材料（附录、Supporting Information） | `pdf_discovery` | `download_with_fallback` / `download_batch` 设 `content` 为 `supplements` 或 `both` | 只有机构下载能取；只有部分出版社有规则，见 `references/publisher-support.md` |
| 在论文正文片段中找 Methods、参数、写法线索 | `body_snippet_search` | `paper-search run search_semantic_snippets` | 查 Semantic Scholar 开放获取片段索引；需要 `SEMANTIC_SCHOLAR_API_KEY`；不是完整全文解析 |

## 两种下载方式

装好 `paper-search` 就能用开放下载。机构下载（学校订阅下载）要用户同意后才装：按 `references/setup.md` 问过、用户同意后，运行 `paper-search carsi install --yes --skip-school`；本机没有 Google Chrome 时先装 Chrome（问的时候一并说明）。装完会弹出设置窗口的 API key 页，请用户在窗口里填 key、改下载文件夹（见 `references/carsi-setup.md`）。没有图形界面的服务器不装、不问。

两种情况不装、不提，用户自己要求时才装：
- 用户说过不要：`paper-search config get PAPER_SEARCH_CARSI_DECLINED` 为 `true`。用户说不要时，运行 `paper-search config set PAPER_SEARCH_CARSI_DECLINED true` 记下来。
- 这台机器没有图形界面（Linux 上没有 `DISPLAY`、`WAYLAND_DISPLAY`）：学校登录要在看得见的浏览器里完成，装不了。

| | 开放下载 | 机构下载（学校订阅下载） |
|---|---|---|
| 能不能直接用 | 装好 `paper-search` 就能用 | 电脑上经用户同意后安装（`paper-search carsi install`），需要 Google Chrome；服务器上不装 |
| 能拿到什么 | 开放获取的正文 | 用户学校订阅的正文；有规则的出版社还能取补充材料 |
| 怎么拿 | 程序直接下载，通常几秒，不用登录：来源自带的下载、元数据里的 PDF 地址、PMC、Unpaywall、出版社接口（用户自己的 key）；最后是默认开启的 Sci-Hub 兜底（它不是开放获取，`useSciHub=false` 关闭） | 打开浏览器，经 CARSI 登录学校，在出版社网站取 PDF；账号密码由用户输入，后端尝试简单验证，必要时提示人工接管 |
| 补充材料 | 不提供 | 有规则的出版社可以取，见 `references/publisher-support.md` |
| 结果里怎么看 | `attempts[]` 里成功的一步是 `primary`、`direct_pdf_url`、`repositories`、`unpaywall`、`publisher_api` 或 `scihub` | 成功的一步是 `entitled_access` |
| 参考文件 | `references/capability-routing.md` 的“PDF 获取” | `references/carsi-setup.md`、`references/browser-download.md`、`references/publisher-support.md` |

两种方式用同一个下载命令，不需要分开调用：先试开放下载；拿不到时，机构下载已启用才继续用学校权限，它固定是最后一步。

- 交付时告诉用户文件来自哪种方式：开放下载、Sci-Hub，还是机构下载。
- 开放下载没拿到、机构下载又没装时：告诉用户开放渠道没有找到这篇。不主动提安装时（见上），只说出版社 API key 这一种办法；否则说如果学校订阅了它，有两种办法：安装学校订阅下载（CARSI，本机要先装 Google Chrome）；或者在校园网里配出版社 API key，只对 Elsevier（DOI 以 10.1016 开头）和 Springer（10.1007）的论文有效，申请网址和配置命令见下载结果里 `publisher_api` 那一步的提示。安装前先征得用户同意，不擅自安装。
- 用机构下载前，先运行 `paper-search carsi status --format text` 确认扩展可用：显示已安装并启用，或者“PaperSearch 配置”一行显示已启用并给出后端路径。后一种是用户自己维护的后端（例如开发版），第一行写“未安装”是正常的，直接使用，不要再安装或改路径；`paper-search doctor` 里 `entitled_access` 为 `available` 也说明后端能用。
- 扩展自己的命令 `paper-search-carsi` 安装后通常不在 PATH 上：`command -v paper-search-carsi` 找不到时，用 `carsi status` 输出里“PaperSearch 配置”一行“后端”后面的完整路径调用，例如 `<后端路径> issues`、`<后端路径> progress --json`。

## 默认工作流

开放式的文献任务分两步：

1. 先做 `metadata_search`：检索并核验题名、作者、年份、期刊、DOI、PMID/PMCID、网址、摘要线索和相关性。
2. 用户确认条目，或任务明确需要 PDF 后，再做 `pdf_discovery`；失败的条目记下原因，不阻塞其他条目。

直接下载请求（用户给出单个 DOI、PMID、PMCID 或已核验的清单，并明确要求下载）可以跳过广泛检索：先核验目标身份，再下载。

下载前问清要什么：机构下载已启用、用户又没说要不要补充材料时，开始下载前问一次（批量也只问一次），三个选项：

- 只要正文（默认，`content` 为 `main`）；
- 正文加补充材料（`content` 为 `both`）；
- 只要补充材料（`content` 为 `supplements`，正文已有时用）。

问的时候顺带说明：补充材料只有部分出版社支持，见 `references/publisher-support.md`。用户已经说明的不再问。机构下载没启用时只走开放下载、只下正文；用户要补充材料时，告诉用户补充材料要靠学校订阅下载（`references/carsi-setup.md`）；用户说过不装时只说明这一点，不劝装。

几十到几百篇用一次 `download_batch`，不要自己循环调用单篇下载。下载结束后运行 `paper-search failures --format text`，按失败类别向用户说明。需要向维护者报告时用 `paper-search failures --export ./failure-report.zip` 导出副本，先核对包内公开检查清单；详见 `references/browser-download.md`。不自动上传或提交 issue。

## 核心规则

- 不凭模型记忆编造 PMID、DOI、期刊、年份或作者；关键论文输出前按 `references/capability-routing.md` 核验。
- 同一篇论文的 PMID、DOI、题名、第一作者和年份应一致；不一致时标为可疑。
- 学校登录、二次验证及复杂验证码由用户在下载浏览器里完成；后端每次验证等待最多尝试点击可识别的 Turnstile 复选框 3 次，仍需人工时再提示用户。账号密码由用户自己在登录页输入，不要询问用户的账号密码。
- 测试下载时用 `paper-search download` 或 `paper-search run download_batch`，保持默认的等待时间和数据目录。
- 用户想先登录学校、或想试试能不能登录时，运行 `paper-search carsi login --doi <学校订阅的一篇文章的 DOI>`（见 `references/carsi-setup.md`）：只有回复 `success: true` 才算登录成功。下载浏览器和它的资料目录由程序管理；不要翻源码另找登录办法。
- 下载结果以命令的最终返回和实际保存的文件为准；每个文件都要核对身份（首页的 DOI 和题名）才算成功，交付时给出实际文件路径。
- “没有权限”必须有依据，原因不明的不说成没有权限。
- 出版社支持表说明的是程序能不能走通这类网站，不代表用户学校订阅了某本期刊。

## 不属于本 Skill 的事

- 不管理 Zotero、Obsidian 或其他文献库。
- 不写论文正文，不做语言润色。
- 不把 API key、token、Cookie 写入 Skill、README 或回复。

下载结果分在下载文件夹（`savePath`，没传时用 `DEFAULT_DOWNLOAD_PATH`）的 `papers/`，每篇一个文件夹；出过问题的篇目在该文件夹的 `diagnostics/` 里有诊断记录和截图（可能带登录信息，不要发给别人），整批运行记录在 `runs/`。正文按“期刊_年份_标题”命名，附件保留原名；使用结果返回的实际 `path` / `supplements[].file`，不要自行拼 DOI 文件名。过长名称会截短，完整标题见返回结果。

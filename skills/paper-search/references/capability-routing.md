# 功能路由

用这一篇把用户的文献请求对应到 `paper-search` 的五个文献功能之一。

## 功能地图

| 用户意图 | 能力名 | 首选入口 | 边界 |
|---|---|---|---|
| 搜论文、找相关研究、核验 DOI/PMID、文献初筛 | `metadata_search` | `paper-search search` 集成入口 / `paper-search run search_*` 精确工具入口 | 只返回和核验论文元数据；Sci-Hub 不是检索来源 |
| 扩展已知论文的引用网络 | `citation_expansion` | `paper-search run get_paper_citations` / `paper-search run get_paper_references` | 需要已知的 `paperId`、DOI 或 arXiv ID；返回施引文献或参考文献，不是关键词检索 |
| 查影响因子、JCR/SSCI/中科院分区、JCI、ESI、预警、期刊等级 | `journal_metrics` | `paper-search journal-metrics` / `paper-search run query_journal_metrics` | 查期刊，不查论文；需要 `EASYSCHOLAR_KEY` |
| 获取或下载已核验论文的 PDF 和补充材料 | `pdf_discovery` | `paper-search download` / `paper-search run download_with_fallback` / `download_batch` | 下载前先核验身份；开放渠道之后依次是 Sci-Hub（启用时）和学校订阅下载（启用时） |
| 在正文片段里找 Methods 写法、参数、软件、模型或统计表述 | `body_snippet_search` | `paper-search run search_semantic_snippets` | 查 Semantic Scholar 开放获取片段索引；需要 `SEMANTIC_SCHOLAR_API_KEY`；不是全文解析 |

## 工作流边界

开放式的文献任务分两步：

1. 做 `metadata_search`：整理并核验论文清单，包括题名、作者、年份、期刊或来源、DOI、PMID/PMCID、网址、摘要线索和相关性。
2. 用户确认选中的论文，或任务明确需要 PDF 后，才做 `pdf_discovery`。下载失败的条目记下原因，不阻塞其他条目。

用户给出 DOI、PMID、PMCID 或已核验的清单时，可以跳过广泛检索，但下载前仍要核验目标身份。

不凭模型记忆编造 PMID、DOI、题名、作者、期刊或年份。重要引用写明它支持的论点、题名、作者、期刊或来源、年份，有 DOI 或 PMID 时一并给出，再加一个稳定网址。

## 元数据检索

`metadata_search` 用于找论文、扩展关键词、文献初筛和核验 DOI/PMID/PMCID。

`paper-search search` 是集成的元数据检索入口：

- `--platform NAME`：只查一个来源；
- `--sources a,b,c`：明确指定多个来源；
- `--platform all` 或 `--sources all`：只在查全比查准更重要时使用。

它不调用 `citation_expansion`、`journal_metrics`、`pdf_discovery` 或 `body_snippet_search`。

```bash
paper-search search "machine learning" --platform crossref --max-results 5 --pretty
paper-search search "osteoarthritis occupational exposure" --platform pubmed --max-results 10 --pretty
paper-search search "transformer attention mechanism" --sources semantic,crossref,openalex --max-results 5 --pretty
paper-search search "causal inference target trial emulation" --sources all --max-results 5 --pretty
```

精确工具入口：

```bash
paper-search run search_pubmed --arg query="osteoarthritis occupational exposure" --arg maxResults=10 --pretty
paper-search run search_openalex --arg query="causal inference target trial emulation" --arg maxResults=5 --pretty
paper-search run get_paper_by_doi --arg doi="10.xxxx/xxxxx" --pretty
```

不要把 `search_scihub` 当检索来源：它按 DOI 或网址定向查找，不属于 `metadata_search`。

## 施引扩展

`citation_expansion` 用于用户有一篇已知论文，问哪些论文引用了它，或它引用了哪些文献。

```bash
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --pretty
paper-search run get_paper_references --arg doi="10.1038/nature12373" --pretty
```

标识的优先级是 `paperId` > `doi` > `arxivId`。这项功能用 Semantic Scholar Graph API，与按关键词的 `metadata_search` 分开。

## 期刊指标

`journal_metrics` 查期刊层面的指标：影响因子、JCR/SSCI 分区、中科院分区、JCI、ESI、预警和等级。

```bash
paper-search journal-metrics "Nature" "BMJ" --pretty
paper-search journal-metrics --file journals.txt --include-raw --pretty
paper-search run query_journal_metrics --json-args '{"journals":["Nature"],"includeRaw":true}' --pretty
```

需要 `EASYSCHOLAR_KEY`。没有时，把报错里的申请网址告诉用户，请用户在自己的终端配置：

```bash
paper-search setup EASYSCHOLAR_KEY
```

装了学校订阅下载、用户就在这台电脑前时，也可以运行 `paper-search settings EASYSCHOLAR_KEY` 打开设置窗口让用户填。

批量查期刊时，用一次 `journal-metrics` 带多个期刊名或 `--file`；不要并行发 EasyScholar 请求。

## PDF 获取

`pdf_discovery` 用于获取已核验论文的 PDF。开放式的文献任务不要一开始就批量下载。

```bash
paper-search download PMC11466435 --platform pmc --pretty
paper-search run download_paper --arg paperId="10.xxxx/xxxxx" --arg platform=springer --pretty
paper-search run download_with_fallback --json-args '{"source":"crossref","paperId":"10.xxxx/xxxxx","doi":"10.xxxx/xxxxx","title":"Paper title"}' --pretty
```

不传 `savePath` 时存到 `DEFAULT_DOWNLOAD_PATH`（见 SKILL.md 的“默认下载文件夹”）；用户这一次指定了别的文件夹才传 `savePath` / `--save-path`。

下载分两种：第 1–6 步是开放下载（默认就有），第 7 步是机构下载（学校订阅下载，`entitled_access`，电脑上经用户同意后安装）。`download_with_fallback` 的顺序：

1. 来源自带的下载；
2. 元数据里的 PDF 地址；
3. PubMed Central 的官方渠道：DOI → PMCID（NCBI ID 转换）→ PMC Article Datasets 的 PDF（S3），不行再用 Europe PMC 的 `getPdf`；CORE、OpenAIRE 只作检索来源；
4. Unpaywall：所有开放获取位置，出版版本优先；放在拒绝普通 HTTP 下载的网站（Wiley、ScienceDirect、Springer、MDPI、PMC 等）上的副本记为 `browser_only`，留给 `entitled_access`；arXiv 副本留到最后的 `preprint` 阶段；
5. `publisher_api`：用户自己的 `ELSEVIER_API_KEY`（PDF）或 `SPRINGER_API_KEY`（JATS XML 全文），走普通 HTTPS；没有 key 时跳过，网络或 key 没有订阅时为 `not_entitled`；
6. PaperSearch 的 Sci-Hub，除非 `useSciHub=false`；
7. 可选的机构下载后端（`entitled_access`）；
8. arXiv 预印本（`preprint`）：正式版路线均未取得正文时才尝试；成功必须向用户说明 `version: "preprint"`。

固定顺序：`primary -> direct_pdf_url -> repositories -> unpaywall -> publisher_api -> scihub -> entitled_access -> preprint`。`download_paper` 也进入同一个漏斗，来源自带的下载最多试一次。Sci-Hub 成功就不再调用机构下载后端；Sci-Hub 失败或被跳过时，才进入 `entitled_access`。

机构下载后端（CARSI）是唯一可选的授权下载后端。除非 `PAPER_SEARCH_CARSI_ENABLED` 恰好是 `true`，它全局关闭；请求里的 `useEntitledAccess` 默认是 `true`，只能关掉这一层，不能绕过全局关闭。单次请求关掉它：

```bash
paper-search run download_with_fallback --json-args '{"source":"crossref","paperId":"10.xxxx/xxxxx","doi":"10.xxxx/xxxxx","title":"Paper title","useEntitledAccess":false}' --pretty
```

Sci-Hub 兜底默认开启。单次请求跳过 Sci-Hub、直接进入可选的机构下载：

```bash
paper-search run download_with_fallback --json-args '{"source":"crossref","paperId":"10.xxxx/xxxxx","doi":"10.xxxx/xxxxx","title":"Paper title","useSciHub":false}' --pretty
```

补充材料用 `content` 选择（`main`、`supplements`、`both`），只经机构下载后端获取；哪些出版社能取见 `publisher-support.md`，细节见 `browser-download.md`。

PDF 来源分组：

- `open_access_sources`：bioRxiv、medRxiv、PMC、Europe PMC、CORE、OpenAIRE、Unpaywall、OpenAlex 的开放获取元数据、Semantic Scholar 的 openAccessPdf、出版社开放获取模式、IACR；
- `scihub_sources`：Sci-Hub，单独标出，是开放渠道之后、机构下载之前默认开启的一层；它既不是开放获取，也不是机构授权。

`metadata_entitled` 是给带 key 的数据库和出版社的元数据分类，不能当作本机的授权 PDF 后端。机构下载后端只通过 PaperSearch 固定的 `CarsiBackend` 接口调用；它由用户要求时用 `paper-search carsi install` 安装（见 `carsi-setup.md`），自带 MCP stdio 服务，不需要另装 MCP 包、全局 MCP 配置、常驻进程或端口。

调用机构下载后端时固定用 `legal_only`（后端声明支持 `institutional_only` 时用它，跳过后端自己的公开来源竞速），并关闭后端内部的 Sci-Hub 和 Tor。`legal_only` 不等于 `entitled_only`：成功的结果也可能来自开放获取，不能当作学校授权的证明。除机构下载后端外，没有浏览器、WebVPN 或 EZProxy 兜底。

## 核验论文

报告关键论文前先核验：

```bash
paper-search run search_pubmed --arg query="37654321[PMID]" --arg maxResults=1 --pretty
paper-search run get_paper_by_doi --arg doi="10.xxxx/xxxxx" --pretty
paper-search run search_crossref --arg query="full paper title" --arg maxResults=3 --pretty
```

PMID 要由 PubMed 确认；DOI 由 DOI 查询或 Crossref、OpenAlex、Semantic Scholar 的结果确认。同一篇论文的 PMID、DOI、题名、第一作者和年份应一致，不一致时标为可疑。

## 正文片段检索

`body_snippet_search` 用来找 Methods 写法、参数、软件名、模型描述、统计分析表述等正文片段线索。

```bash
paper-search run search_semantic_snippets --arg query="comparative risk assessment methods uncertainty propagation" --arg limit=5 --arg fieldsOfStudy=Medicine --pretty
```

`search_semantic_snippets` 需要 `SEMANTIC_SCHOLAR_API_KEY`，数量参数是 `limit`，不是 `maxResults`。没有 key 时，把报错里的申请网址和 `paper-search setup SEMANTIC_SCHOLAR_API_KEY` 告诉用户（有设置窗口时也可运行 `paper-search settings SEMANTIC_SCHOLAR_API_KEY`）。

只有 `snippetKind="body"` 的结果能作为正文片段证据；来自 `title` 或 `abstract` 的只是线索。引用或依赖某个片段前，核验题名、作者、年份、期刊或来源、DOI 或 PMID。

回答里给出正文片段时，英文原句原样引用（不翻译、不改写、不拼接几句），下一行写出处，直接用这条结果的 `source`（第一作者 et al.、年份、期刊 · 章节 · DOI · 许可证）；要中文解释时另起一段：

```text
> "The primary outcome in the DAPA-HF trial was the composite of … whichever occurred first."
> —— M. Kosiborod et al., 2019, Circulation · Clinical outcomes · DOI 10.1161/CIRCULATIONAHA.119.044138 · CC BY
```

- `title`、`abstract` 命中的结果不用这个样式，列出时标“线索（摘要）”或“线索（题名）”。
- `paper.metadataStatus` 不是 `found` 时，出处里没有年份、期刊和 DOI：写“DOI 待核验”，引用前按上面的核验步骤补查；`lookup_failed` 时命令第一行会写明。

## 选择来源

| 任务 | 首选 | 补充 |
|---|---|---|
| 生物医学、临床、药学、公共卫生 | `pubmed` | `pmc`、`europepmc`、`semantic`、`crossref` |
| Methods、正文片段线索 | `search_semantic_snippets` | 先用 `pubmed`、`semantic` 找题名和同义词 |
| 引用网络扩展 | `get_paper_citations`、`get_paper_references` | 只在已知目标论文标识后使用 |
| 计算机、人工智能、数学、物理 | `semantic`、`dblp` | `crossref`、`openalex`、`openreview` |
| 计算机文献目录和会议元数据 | `dblp` | `acm`、`usenix`、`openreview`；`ieee` 需要 key |
| 跨学科覆盖 | `crossref` | `openalex`、`semantic` |
| 找开放获取全文 | `download_with_fallback` 的各层（PMC 官方渠道、Unpaywall） | `download_with_fallback` |
| 期刊影响因子、分区、等级 | `journal-metrics` | `query_journal_metrics` |
| 密码学 | `iacr` | `dblp` |
| 按被引次数排序 | `semantic`、`crossref`、`openalex` | `webofscience`、`scopus` 需要 key |
| 出版社或付费数据库的元数据 | `webofscience`、`ieee`、`scopus`、`sciencedirect`、`springer` / `springerlink` | 只在配置了对应的元数据 key 时使用；这不授权下载 PDF |

## 构造检索词

- 中文研究问题默认翻译成英文关键词。
- 用 3–8 个核心概念词，不用长句。
- 医学主题需要时加 MeSH 或标准术语。
- 找方法细节时加软件名、参数名、模型名，或 `methods`、`statistical analysis`、`adjusted for`、`bootstrap`、`sensitivity analysis` 这类章节用词。

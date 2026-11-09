# 命令约定

这里记录本 Skill 可以依赖的稳定命令。不要写这里和当前命令都没有的命令、参数或默认值。

## 入口

- `paper-search` 是主命令。
- `paper-search --version`、`paper-search -v`、`paper-search version` 显示已安装的版本。
- `paper-search --help`、`paper-search help` 显示用法。
- `paper-search tools --pretty` 列出 `run` 可直接调用的工具名和参数结构。
- 私有的 API key、email、token 通过 `paper-search setup`、`paper-search config`、`.env` 或 Shell 环境变量配置，不写进 Skill 文件。

## 顶层命令

- `paper-search search <query> [--platform NAME] [--sources CSV] [--max-results N] [--year YEAR] [--pretty]`
- `paper-search run <tool-name> --arg key=value --json-args '{"key":"value"}' [--pretty]`
- `paper-search download <paper-id> --platform NAME [--save-path PATH] [--pretty]`
- `paper-search journal-metrics <journal...> [--file PATH] [--include-raw] [--pretty]`
- `paper-search metrics ...` 是 `journal-metrics` 的别名。
- `paper-search status [--validate] [--pretty]`
- `paper-search doctor [--validate] [--format text] [--pretty]`
- `paper-search failures [--run ID|--since YYYY-MM-DD|--runs N] [--doi DOI] [--export file.zip] [--all] [--format text] [--pretty]`
- `paper-search update check [--format text] [--pretty]`（只检查，不安装）
- `paper-search carsi install [--browser chrome|ego] [--yes] [--force] [--skip-school] [--format text]`
- `paper-search carsi status [--format text] [--pretty]`
- `paper-search carsi update [--force] [--format text] [--pretty]`
- `paper-search carsi login --doi <DOI> [--max-wait <seconds>] [--pretty]`
- `paper-search carsi uninstall [--yes] [--remove-data] [--format text] [--pretty]`
- `paper-search smoke --mock [--pretty]`
- `paper-search smoke --live [--pretty]`
- `paper-search skills status [--targets CSV] [--pretty]`
- `paper-search skills diff [--targets CSV] [--format text] [--pretty]`
- `paper-search skills update [--targets CSV] [--pretty]`
- `paper-search setup [--all] [--keys CSV] [--install-skills CSV] [--skip-skills]`
- `paper-search config test [KEY] [--stdin] [--format text]`：用一次小请求测试 key 能不能用（有效、被拒绝、限流、连不上）；不带 KEY 时测试所有已填的 key。
- `paper-search settings [download|wait|keys|<KEY>] [--format text]`：装了学校订阅下载时打开设置窗口（下载文件夹、等待和提醒、API key）；没装或没有图形界面时返回错误，并给出终端命令。
- `paper-search tools [--pretty]`
- `paper-search diagnostics [--pretty]`
- `paper-search requirements [--pretty]` 是 `diagnostics` 的别名。
- `paper-search config init [--pretty]`
- `paper-search config path [--pretty]`
- `paper-search config keys [--pretty]`
- `paper-search config list [--all] [--pretty]`
- `paper-search config doctor [--pretty]` 是兼容用的配置摘要；完整健康报告用顶层的 `doctor`。
- `paper-search config get KEY [--raw] [--pretty]`
- `paper-search config set KEY VALUE [--pretty]`
- `paper-search config unset KEY [--pretty]`
- `paper-search config delete KEY [--pretty]` 和 `paper-search config remove KEY [--pretty]` 是 `unset` 的别名。
- `paper-search config import-env [file] [--pretty]`

机构下载后端自己的命令 `paper-search-carsi`（`issues`、`progress`、`preview`、`entitlements`、`setup`、`config`）见 `browser-download.md` 和 `carsi-setup.md`；它通常不在 PATH 上，用 `paper-search carsi status --format text` 显示的后端完整路径调用。

## 可直接调用的工具

下面的名字可以用于 `paper-search run <tool-name>`：

- `search_papers`
- `search_arxiv`
- `search_webofscience`
- `search_pubmed`
- `search_biorxiv`
- `search_medrxiv`
- `search_semantic_scholar`
- `search_semantic_snippets`
- `get_paper_citations`
- `get_paper_references`
- `search_iacr`
- `download_paper`
- `search_google_scholar`
- `get_paper_by_doi`
- `search_scihub`
- `check_scihub_mirrors`
- `get_platform_status`
- `query_journal_metrics`
- `search_sciencedirect`
- `search_springer`
- `search_scopus`
- `search_crossref`
- `search_openalex`
- `search_unpaywall`
- `search_pmc`
- `search_europepmc`
- `search_core`
- `search_openaire`
- `download_with_fallback`
- `download_batch`
- `search_dblp`
- `search_ieee`
- `search_acm`
- `search_usenix`
- `search_openreview`
- `search_springerlink`

## 输出格式

- 默认输出 JSON，供 agent 和脚本读取。
- `--pretty` 把 JSON 排版输出。
- `--format text` 用于顶层的 `doctor`、`failures`、`carsi` 和 `skills diff`，在用户明确需要可读报告时使用。
- `--include-text` 在支持的命令里把工具的原始返回文字保留在 JSON 里。
- 做判断时解析 JSON；只有用户需要可读报告时才用文本格式。

## 检索命令

- `paper-search search` 是集成的元数据检索入口。
- `--platform NAME` 只查一个来源，`--sources a,b,c` 明确指定多个来源。
- `--sources no-key`（别名 `free`、`no_key`）展开为 Crossref、PubMed、Europe PMC、arXiv、OpenReview 这一组；不调用 Google Scholar，普通元数据检索不需要用户的 API key。
- `search_google_scholar` 仍是需要明确指定的、尽力而为的网页来源：单一低频客户端（默认 `SCHOLAR_RATE_LIMIT_RPS=0.5`），有限次的临时重试，进程内缓存一小时，能识别验证页；遇到 CAPTCHA 或 `/sorry` 页面时报告，不盲目重试。
- `--platform all` 或 `--sources all` 只在查全比查准更重要时使用。
- `search_papers` 是集成 `search` 命令背后的工具。
- `search_semantic_snippets` 的数量参数是 `limit`，不是 `maxResults`；它查的是正文、题名、摘要片段，不是完整全文。
- `search_unpaywall` 按 DOI 查开放获取元数据，最多返回一条。
- `search_scihub` 按 DOI 或网址定向查找，不是元数据检索来源。
- `CORE_MAX_RESULTS_CAP` 设定 CORE 的结果上限，默认 `100`，最大 `500`；其他来源保留各自的上限。

## 施引扩展

`get_paper_citations` 查引用了目标论文的文献，`get_paper_references` 查目标论文的参考文献。两个都返回全部结果，没有 `limit`，每次结果只来自一个来源，`provider` 写明是哪个。

- 引文：OpenAlex 的全部施引文献，新的在前，结果带 `citedByCount`（OpenAlex 记录的被引次数）。不配 `OPENALEX_API_KEY` 时最多列出最新的 1 万条，配了能全部列出。OpenAlex 没有这篇论文时才用 Semantic Scholar（最多 1000 条），`notes` 会说明。
- 参考文献：出版商在 Crossref 登记了每条参考文献的题名或引文时（如 Elsevier、Springer Nature、Frontiers、Wolters Kluwer），用这份清单，保持原文顺序，能看出原文编号时每条带 `number`，结果带 `numberedTo` 和 `missing`（出版商漏登记的编号）。出版商只登记 DOI 或没登记时（如 Wiley、NEJM），用 OpenAlex 的清单，新的在前。两者都没有时用 Semantic Scholar。`notes` 说明换来源的原因。

- `paperId`、`doi`、`arxivId` 至少给一个。
- 优先级：`paperId`，然后 `doi`，然后 `arxivId`。
- `doi` 转成 `DOI:<doi>`，`arxivId` 转成 `ARXIV:<id>`。

```bash
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --pretty
paper-search run get_paper_references --arg doi="10.1038/nature12373" --pretty
```

## 下载命令

`download_paper` 和 `download_with_fallback` 用同一个下载漏斗；来源自带的下载属于 `primary` 层，最多试一次。

固定顺序是 `primary -> direct_pdf_url -> repositories -> unpaywall -> publisher_api -> scihub -> entitled_access -> preprint`。Sci-Hub 成功就不再调用机构下载后端；Sci-Hub 失败或被跳过时进入可选的机构下载。`publisher_api` 在 Sci-Hub 之前，用用户自己的 `ELSEVIER_API_KEY` / `SPRINGER_API_KEY`；Springer 的结果是 JATS XML，这时顶层结果带 `format: "jats-xml"`。

机构下载后端（CARSI）是唯一可选的授权下载后端，默认关闭，只有 `PAPER_SEARCH_CARSI_ENABLED` 恰好是 `true` 时启用。两个下载工具都有 `useEntitledAccess`，默认 `true`；传 `false` 关掉这一层，传 `true` 不能绕过全局关闭。

```json
{ "useEntitledAccess": false }
```

Sci-Hub 兜底默认开启。用 `download_with_fallback` 时，跳过这一层、继续到可选的机构下载：

```json
{ "useSciHub": false }
```

常用写法：

```bash
# 安装并启用学校订阅下载（安装前会询问）：
paper-search carsi install
# 或者指定别处安装的后端：
paper-search config set PAPER_SEARCH_CARSI_EXECUTABLE /absolute/path/to/paper-search-carsi
paper-search config set PAPER_SEARCH_CARSI_ENABLED true
paper-search doctor --pretty
paper-search download "<DOI>" --platform crossref
paper-search run download_with_fallback --json-args '{"source":"crossref","paperId":"<DOI>","doi":"<DOI>","title":"<paper title>","useSciHub":false,"useEntitledAccess":true}'
```

一组论文（几十到几百篇）用一次按顺序执行的 `download_batch`，不要循环调用单篇下载：

- `"mode"`：默认 `"two_phase"`，先对每篇试开放渠道，再只对仍缺的篇目走机构下载，浏览器登录集中在最后一段；进度窗口按整批计数（k / N），装了学校订阅下载时，5 篇以上的批量从开放渠道那一轮起就显示；`"per_item"` 每篇走完整个漏斗；`"entitled_only"` 跳过开放渠道，每篇直接走机构下载（用于测试学校这条路）。
- 不传 `savePath` 时存到 `DEFAULT_DOWNLOAD_PATH`；整批或每篇都可以带自己的 `savePath`，用户指定了别的文件夹时才传。
- `"content"`：`"main"`（默认，只要正文）、`"supplements"`（只要本文的补充材料，不走正文的各层）、`"both"`。补充材料存在 `<savePath>/papers/<期刊_年份_标题_短标识>/supplements/`，清单与浏览器诊断在 `diagnostics/`，结果的 `supplements` 列出每个文件的状态；只经机构下载后端获取，哪些出版社有规则见 `publisher-support.md`。
- 每次下载都会写一份本地运行记录，结果里的 `runLog` 是它的目录（`run.json`；`items.jsonl`，含每一层的耗时、代码，以及后端的页面事件和截图；`timeline.log`）。排查失败时读它，不要猜。结果列出每一篇和它的各次尝试。

```bash
paper-search run download_batch --json-args '{"items":[{"doi":"<DOI-1>","title":"<title 1>"},{"doi":"<DOI-2>"}],"useSciHub":false}'
```

必须由外部循环逐篇调用 `download_with_fallback` 时，传 `"batch":{"id":"<同一个 id>","index":k,"total":N,"done":…,"succeeded":…,"failed":…}`，可以得到同样的进度窗口。

命令行参数用短横线写法（kebab-case），JSON 参数用工具定义的驼峰写法（camelCase）。`--platform` / `source` 选的是论文元数据来源，不是后端。`useSciHub`、`doi`、`title` 只在 `download_with_fallback` 上有，`download_paper` 和它的简写 `download` 没有。后端路径是可选配置，既不启用机构下载后端，也不改变它的配置；PaperSearch 用 `run` 启动配置的后端（`PAPER_SEARCH_CARSI_EXECUTABLE`），用户不需要每次下载前自己启动服务。

支持的进度通知绑定到当前请求，以固定的文字写到 stderr；stdout 默认只有最终的 JSON，不是逐行进度流。不发通知的旧后端不提供推测的阶段。已保存的 PDF 仍要核对身份；带 `review.path` 的错误不是成功的下载。手动登录、绑定请求的截图预览和补充材料的边界见 `browser-download.md`。

机构下载后端只用 `paper-search carsi install` / `status` / `update` / `uninstall` 安装、查看、更新和卸载；不要编造别的安装命令、账号登录流程或后端选择方式。后端自带 MCP stdio 服务，PaperSearch 不需要另装 MCP、全局 MCP 配置、常驻进程或端口。

命令里别处用到的出版社、数据库 key 不能当作本机的授权 PDF 后端：`ELSEVIER_API_KEY` 和 `SPRINGER_API_KEY` 另外用于 `publisher_api` 层（直接经 HTTPS 调全文接口，权限跟随用户的网络或 key），经浏览器的机构访问只由可选的机构下载后端负责。机构下载适配固定 `strategy=legal_only`（后端声明支持时用 `institutional_only`）、`scihub_enabled=false`、`use_tor=false`，但 `legal_only` 不能证明结果来自学校授权。除机构下载后端外，没有浏览器、WebVPN 或 EZProxy 兜底。

## 配置与密钥边界

配置来源按优先级：

1. Shell 环境变量
2. 当前目录的 `.env`
3. 用户配置文件 `~/.config/paper-search-cli/config.json`
4. 免费来源的内置默认值

常用配置命令：

```bash
paper-search setup
paper-search config set DEFAULT_DOWNLOAD_PATH "~/Documents/Papers"
paper-search config set PAPER_SEARCH_CARSI_ENABLED true
paper-search config set SEMANTIC_SCHOLAR_API_KEY your_key
paper-search setup EASYSCHOLAR_KEY
paper-search settings EASYSCHOLAR_KEY
paper-search config list --pretty
paper-search doctor --pretty
```

不要让用户把密钥贴到聊天里，不要把密钥写进 Skill、README、测试或日志。`doctor` 和 `config` 的输出会把已配置的密钥脱敏。

`PAPER_SEARCH_CARSI_ENABLED` 是不保密的严格开关：只有字符串 `true` 启用；`TRUE`、`1`、`yes` 或前后带空格的写法都算关闭。

用户的学校用 `paper-search-carsi setup --carsi --institution "<学校>"` 配置，数据目录要和下载用的相同，见 `carsi-setup.md`。agent 不得写入维护者的学校，也不得换成记忆里的其他登录方；`doctor=available` 不能说成学校会话有效或对某篇有权限的证明。

### arXiv

`search_arxiv`：`query` 必填，可选 `maxResults`、`category`、`author`、`year`、`sortBy`、`sortOrder`。例如：`paper-search run search_arxiv --arg query="transformer" --arg maxResults=3 --pretty`。

`paper-search download 1706.03762 --platform arxiv` 同样遵守正式版优先策略；返回 `version: "preprint"` 时必须明确说明拿到预印本。`publishedDoi` 是元数据关联，不表示已下载正式版。`entitled_only` 批量模式不尝试预印本。

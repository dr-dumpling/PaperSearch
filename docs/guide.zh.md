# PaperSearch 使用说明

安装、API key 和机构下载的配置见 [README](../README.md)。下面的命令也可以在终端或脚本里直接运行，输出默认是 JSON。

## 命令示例

```bash
# 检索论文（不需要任何 key 的来源组合）
paper-search search "machine learning clinical prediction" --sources no-key --max-results 5 --pretty

# 指定一个来源，例如 PubMed
paper-search search "SGLT2 inhibitor heart failure" --platform pubmed --max-results 10 --pretty

# 核验一个 DOI
paper-search run get_paper_by_doi --arg doi="10.1038/nature12373" --pretty

# 施引文献；参考文献把 get_paper_citations 换成 get_paper_references
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --pretty

# 期刊影响因子和分区（需要 EasyScholar key）
paper-search journal-metrics "Nature" "BMJ" --pretty

# 在正文里找 Methods 写法（需要 Semantic Scholar key）
paper-search run search_semantic_snippets --arg query="propensity score matching" --arg limit=3 --pretty

# 下载一篇
paper-search download "<DOI>" --platform crossref

# 批量下载正文和补充材料（只要正文去掉 content；只要补充材料用 "supplements"）
paper-search run download_batch --json-args '{"items":[{"doi":"<DOI-1>"},{"doi":"<DOI-2>"}],"content":"both"}'

# 没下到的篇目和原因
paper-search failures --format text
```

## 工作方式

```text
用户的文献请求
│
├─ 找论文、核验 DOI/PMID → paper-search search（Crossref、PubMed、OpenAlex 等）
│    └─ 确认条目、需要全文 → 转到下面的“下载”
├─ 查施引文献、参考文献 → paper-search run get_paper_citations / get_paper_references
├─ 查影响因子、分区 → paper-search journal-metrics（需要 EasyScholar key）
├─ 找 Methods 写法、参数 → paper-search run search_semantic_snippets（需要 Semantic Scholar key）
│
└─ 下载正文、补充材料 → paper-search download / run download_with_fallback / run download_batch
     同一个下载命令，按顺序尝试：
     ├─ ① 开放下载（默认就有）：来源自带的下载、PMC、Unpaywall、出版社接口
     ├─ ② Sci-Hub 兜底（默认开启，可关闭）
     ├─ ③ 机构下载（可选扩展）：浏览器经 CARSI 登录你的学校，在出版社网站取 PDF 和补充材料
     ├─ ④ arXiv 预印本：前面都没拿到正式发表版时才用，并标明是预印本
     ├─ 每一步拿到文件都核对首页的 DOI 和题名；通过就保存，后面的步骤不再试
     └─ 都没拿到 → paper-search failures 说明原因
```

### 两种下载方式

|  | 开放下载（默认） | 机构下载（可选扩展） |
|---|---|---|
| 能不能直接用 | 装好就能用 | 要另外安装：`paper-search carsi install` |
| 能拿到什么 | 开放获取的正文 | 你的学校订阅的正文；有规则的出版社还能取补充材料 |
| 怎么拿 | 程序直接下载，通常几秒，不用登录：来源自带的下载、元数据里的 PDF 地址、PubMed Central、Unpaywall、出版社接口（你自己的 Elsevier/Springer key）；最后是默认开启的 Sci-Hub 兜底 | 打开 Chrome，经 CARSI 登录你的学校，在出版社网站上取 PDF |
| 你要做的事 | 无 | 在浏览器里登录学校；程序自动过验证，需要人工接管时再按提示操作 |

两种方式用同一个下载命令：先试开放下载，拿不到时，装了机构下载才继续用学校权限。

- 几十到几百篇用一次 `download_batch`：先对所有篇目试开放渠道，再对没拿到正文的篇目用机构下载。结束后 `paper-search failures` 把没下到的篇目分成四类：没权限（附页面原话等依据）、需要你处理（登录、验证、等待）、暂不支持的网站、原因不明。
- arXiv 论文先找正式发表版，都没拿到才下载预印本；结果里写 `version: "preprint"`，已知时附正式版 DOI。
- 不想用 Sci-Hub 时，在 `download_with_fallback` / `download_batch` 里设 `"useSciHub": false`。
- 每个 PDF 都核对首页的 DOI 和题名；对不上的不算成功，单独留待核查。

### 下载结果

下载目录分两部分：`papers/` 放论文，每篇一个文件夹，正文按“期刊_年份_标题”命名，补充材料在该篇的 `supplements/` 里并保留原文件名；`diagnostics/` 放运行记录、附件清单和截图，查问题时用。文件夹名末尾的短标识用来区分同名论文。缺少期刊或年份时写“未知期刊”“未知年份”。命令返回的 JSON 里写着每个文件的实际位置。

## 检索来源

| 类别 | 来源 | 需要的 API key |
|---|---|---|
| 综合学术元数据 | Crossref、OpenAlex、Semantic Scholar、Google Scholar | 不需要（Semantic Scholar 的正文片段检索需要） |
| 生物医学 | PubMed、PubMed Central、Europe PMC | 不需要（PubMed key 可提高限额） |
| 预印本和会议稿 | arXiv、bioRxiv、medRxiv、OpenReview、IACR ePrint | 不需要 |
| 计算机和工程 | DBLP、ACM、USENIX | 不需要 |
| 开放获取和仓储 | CORE、OpenAIRE、Unpaywall | Unpaywall 填邮箱；CORE、OpenAIRE 可选 |
| 出版社和引文库 | ScienceDirect、Scopus、Springer Nature、IEEE Xplore、Web of Science | 需要各自的 key（ScienceDirect、Scopus 共用 Elsevier key） |
| 期刊指标 | EasyScholar | 需要 |

- 不需要 key 的来源已经收录了各大出版社的论文；配了 key，多的是出版社自己的检索入口。
- 单个来源用 `--platform`，多个用 `--sources a,b,c`；`--sources no-key` 是不需要任何 key 的组合（Crossref、PubMed、Europe PMC、arXiv、OpenReview）。
- Google Scholar 是网页解析，容易触发验证，不在 `--sources all` 里；需要时用 `--platform googlescholar`。
- 多个来源返回同一篇论文时按 DOI 合并；arXiv 预印本和正式发表版有明确 DOI 关联时，保留正式发表记录。
- Sci-Hub 不是检索来源，只在下载时按 DOI 兜底。

## Agent Skill

Skill 随 npm 包发布（`skills/paper-search/`），全中文，开头有整体逻辑图，按需读这些参考文件：功能路由与开放下载的各个渠道、命令约定、机构下载的安装和使用、[出版社支持表](../skills/paper-search/references/publisher-support.md)、排障。它只告诉 AI 怎么调用 `paper-search`，不保存 key、Cookie 或账号。

不经过 AI、自己在终端安装，一行即可（以 Claude Code 为例）：

```bash
npm install -g papersearch && paper-search skills update --targets claude
```

```bash
paper-search skills status --pretty
paper-search skills update --targets claude
```

`--targets` 可选 `codex`、`claude`、`cursor`、`gemini`、`antigravity`、`agents`（共享目录 `~/.agents/skills/`）。其他读取 Skill 文件夹的 AI 工具，把随包 Skill 复制到它的 Skill 目录即可：`npm root -g` 可查看全局 npm 目录，随包 Skill 位于其下的 `papersearch/skills/paper-search/`；复制时保留完整文件夹及 `references/`，更新时从新版本复制。安装后新开 AI 会话即可使用。

- `--targets all` 会同步到所有内置位置。更新会覆盖包里管理的文件，保留你在 Skill 目录里自己加的文件。
- 升级 PaperSearch 后第一次运行时，装过的 Skill 会自动更新，被替换的旧文件备份在 `~/.local/share/paper-search-cli/skill-backups/`。不想自动更新：`paper-search config set PAPER_SEARCH_SKILL_AUTO_UPDATE false`。
- 装了学校订阅下载的，升级后第一次用到它时，扩展也会先自动更新（终端里有一行说明），再接着下载。不想自动更新：`paper-search config set PAPER_SEARCH_CARSI_AUTO_UPDATE false`，之后自己运行 `paper-search carsi update`。
- `paper-search doctor` 显示内置安装目标中的 Skill 位置和版本状态。

## 全部命令

| 命令 | 用途 |
|---|---|
| `paper-search search` | 检索论文元数据 |
| `paper-search journal-metrics` | 期刊指标（EasyScholar） |
| `paper-search download` | 下载已核验论文的 PDF |
| `paper-search run <工具>` | 精确调用某个工具，参数用 `--arg` 或 `--json-args` |
| `paper-search failures` | 汇总下载失败的原因 |
| `paper-search update check` | 检查是否有新版本 |
| `paper-search carsi` | 学校订阅下载（CARSI）的安装、状态、更新、卸载 |
| `paper-search setup` / `config` | 配置 key、Skill 和扩展 |
| `paper-search settings` | 打开设置窗口：下载文件夹、等待和提醒、API key（需装学校订阅下载、有图形界面） |
| `paper-search doctor` | 健康检查：配置、可用功能、Skill 和扩展的状态 |
| `paper-search skills` | Skill 的状态、差异和更新 |
| `paper-search smoke` | 离线或真实的自检 |
| `paper-search tools` | 列出所有工具名和参数 |

命令默认输出 JSON，`--pretty` 排版，`--format text` 输出给人看的报告。完整命令见 `paper-search tools --pretty` 或 [命令约定](../skills/paper-search/references/cli-contract.md)。

## 其他设置

用 `paper-search config set <设置项> <值>` 修改，或运行 `paper-search setup <设置项>`。

| 设置项 | 作用 | 默认 |
|---|---|---|
| `DEFAULT_DOWNLOAD_PATH` | 下载的论文默认存放的文件夹 | 命令当前目录下的 `./downloads`；也可以在进度胶囊的设置里改 |
| `UNPAYWALL_EMAIL`、`CROSSREF_MAILTO` | Unpaywall 按 DOI 找开放获取 PDF、Crossref 优先通道要用的联系邮箱 | `paper-search setup` 留空时自动生成 |
| `GOOGLE_SCHOLAR_PROXY_URL` | Google Scholar 的出口代理；直连反复被拦时，用有授权的代理 | 不设置 |
| `PAPER_SEARCH_SKILL_AUTO_UPDATE` | 设为 `false` 时，升级后不再自动更新已安装的 Skill | 开启 |
| `PAPER_SEARCH_CARSI_AUTO_UPDATE` | 设为 `false` 时，升级后不再自动更新学校订阅下载扩展，改为自己运行 `paper-search carsi update` | 开启 |
| `PAPER_SEARCH_UPDATE_NOTIFY` | 设为 `false` 时，不再提示有新版本 | 开启 |
| `PAPER_SEARCH_CARSI_DECLINED` | 设为 `true` 时，AI 不再主动建议安装学校订阅下载（你说过不装时它会自己设上）；你要装时直接说即可 | 未设置 |
| `PAPER_SEARCH_CARSI_ENABLED` | 学校订阅下载（CARSI）的开关 | `paper-search carsi install` 自动设置 |

## 排障

| 问题 | 怎么办 |
|---|---|
| 找不到 `paper-search` 命令 | `npm install -g papersearch` 重新安装 |
| 安装时报 `EEXIST`，或从旧包 `paper-search-cli` 换过来 | 先 `npm uninstall -g paper-search-cli`，再装 `papersearch`；配置、Skill、学校登录和下载记录都会保留 |
| 某个功能不能用 | `paper-search doctor --format text` 看缺什么，再 `paper-search setup` 配置 |
| 学校订阅的文章下载不到 | `paper-search carsi status --format text` 看学校订阅下载是否装好；`paper-search failures --format text` 看每篇的原因 |
| 来源限流 | 减小 `--max-results`、配置对应 key，或换来源 |
| Google Scholar 出验证页 | 等一会儿再试，或改用 `--sources no-key` |
| AI 读到的 Skill 是旧的 | `paper-search skills status --pretty`，再 `paper-search skills update --targets <工具>`；新开一个 AI 会话 |
| 先登录学校、或试一下能不能登录 | `paper-search carsi login --doi <学校订阅的一篇文章的 DOI>`：弹出下载用的浏览器，在学校登录页登录即可 |
| 更新或卸载学校订阅下载 | `paper-search carsi update`；`paper-search carsi uninstall` |
| Windows 的 PowerShell 拦住 `npm` | 改用 `npm.cmd`，或在命令提示符里运行 |
| 想反馈下载失败 | 用 Issue 里的“下载失败”模板，写明版本、系统、网站和 DOI；`paper-search failures --export ./failure-report.zip` 可以导出失败记录，附上前先检查包里的 `summary.md` 和截图有没有个人信息 |
| 怎么升级 | `npm install -g papersearch@latest`；升级后第一次运行时，装过的 Skill 会自动更新 |

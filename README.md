<p align="center">
  <img src="assets/logo.svg" width="112" alt="PaperSearch 图标">
</p>

<h1 align="center">PaperSearch</h1>

<p align="center"><b>让 AI 帮你查文献、核对引用、下载全文和补充材料。</b></p>

<p align="center">
  <a href="https://www.npmjs.com/package/papersearch"><img src="https://img.shields.io/npm/v/papersearch?style=flat-square" alt="npm"></a>
  <a href="https://github.com/dr-dumpling/PaperSearch/actions/workflows/publish.yml"><img src="https://img.shields.io/github/actions/workflow/status/dr-dumpling/PaperSearch/publish.yml?style=flat-square&amp;label=publish" alt="发布工作流状态"></a>
  <a href="#机构下载扩展"><img src="https://img.shields.io/badge/CARSI-institutional%20downloads-7284CE?style=flat-square" alt="CARSI 机构下载扩展"></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/node/v/papersearch?style=flat-square" alt="Node.js 版本要求"></a>
  <a href="#agent-skill"><img src="https://img.shields.io/badge/Agent%20Skill-bundled-D97757?style=flat-square" alt="随包 Agent Skill"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2F9E44?style=flat-square" alt="MIT 许可证"></a>
  <a href="https://linux.do"><img src="https://img.shields.io/badge/LinuxDo-community-1f6feb?style=flat-square" alt="LinuxDo 社区"></a>
</p>

<p align="center">简体中文 | <a href="README.en.md">English</a></p>

PaperSearch 提供 `paper-search` 命令和一份随包 Skill。装好后，Claude Code、Codex、Cursor、Kimi Code、Qwen Code、CodeBuddy、TRAE 等支持本机命令调用的 AI 工具，就能替你检索 20 多个学术数据源、核对 DOI，把论文的 PDF 和补充材料下载下来并整理好。你也可以在终端或脚本里直接使用，输出默认是 JSON。

- **开放获取直接下载**：PubMed Central、Unpaywall、出版社接口等渠道，装好就能用。
- **学校订阅也能下**：可选的机构下载扩展经 CARSI 登录你的学校，批量获取学校有权限的论文和补充材料；支持自动过验证，放行后继续下载。
- **每一篇都核对过**：逐个核对 PDF 首页的 DOI 和题名，不是这篇文章的不算成功。
- **结果直接能用**：按“期刊_年份_标题”建文件夹，正文和补充材料放在一起；没下到的篇目说明原因。

<p align="center"><img src="assets/overview.png" width="840" alt="PaperSearch 能做的事：检索论文、搜正文片段、查期刊与分区、查引文和参考文献、下载全文和补充材料"></p>

[效果](#效果) | [快速开始](#快速开始) | [常见任务](#常见任务) | [工作方式](#工作方式) | [机构下载扩展](#机构下载扩展) | [检索来源](#检索来源) | [配置](#配置) | [Agent Skill](#agent-skill) | [命令](#命令) | [排障](#排障)

## 效果

对 AI 工具说一句话，例如：

> 找 2020 年以来 SGLT2 抑制剂治疗心力衰竭的随机对照试验，核对 DOI，把全文和补充材料下载到 ./downloads

AI 会调用 PaperSearch 检索、核验、下载，最后告诉你哪些拿到了、哪些没拿到以及原因。下面是一次实际下载的结果：

```text
downloads/
├── papers/
│   ├── Nutrients_2026_α-Ketoglutarate Alleviates the Pathogenesis…_0b6e0203de/
│   │   ├── Nutrients_2026_α-Ketoglutarate Alleviates the Pathogenesis….pdf
│   │   └── supplements/
│   │       └── nutrients-18-03600-s001.zip       补充材料保留原文件名
│   └── arXiv_2017_Attention Is All You Need_a1a0262a54/
│       └── arXiv_2017_Attention Is All You Need.pdf    预印本会标明
└── diagnostics/                                   运行记录、附件清单、截图
```

## 快速开始

首次安装需要 Node.js 18 或更高版本和 npm。下面以 Codex 为例，复制一行即可装好 `paper-search` 和配套 Skill。用其他 AI 工具时，把 `codex` 换成 [Agent Skill](#agent-skill) 里对应的 `--targets` 取值。

**macOS、Linux 或 Windows 命令提示符：**

```sh
npm install -g papersearch && paper-search skills update --targets codex
```

**Windows PowerShell：**

```powershell
npm.cmd install -g papersearch; if ($LASTEXITCODE -eq 0) { paper-search.cmd skills update --targets codex }
```

装好后，新开一个 AI 会话就可以查文献。只在终端使用的话，装 `paper-search` 就够了。需要 API key 或邮箱时，再运行 `paper-search setup`；需要下载学校订阅的论文时，再按 [机构下载扩展](#机构下载扩展) 安装。想检查当前可用功能，运行 `paper-search doctor --format text`。

已装好 `paper-search` 的用户可以单独补装 Skill，`--targets` 的取值见下方 [Agent Skill](#agent-skill)：

```bash
paper-search skills update --targets claude
```

也可以把下面这段话发给你的 AI 工具，让它帮你装：

```text
请帮我安装 PaperSearch：运行 npm install -g papersearch，再按 README 的 Agent Skill 说明为你自己安装随包 Skill，最后运行 paper-search doctor --format text，告诉我哪些功能能用、还缺哪些 key；再问我下载的论文默认放在哪个文件夹，用 paper-search config set DEFAULT_DOWNLOAD_PATH 保存。API key 我会自己在终端运行 paper-search setup 输入，不要让我发到聊天里。
```

**从旧包 `paper-search-cli` 升级**：先运行 `npm uninstall -g paper-search-cli`，再 `npm install -g papersearch`。两个包提供同一个 `paper-search` 命令，不能同时装；配置、Skill、学校登录和下载记录都会保留。

**以后升级**：`npm install -g papersearch@latest`。有新版本时，命令会在终端提示；升级后第一次运行时，装过的 Skill 会自动更新。

## 常见任务

```bash
# 检索论文（不需要任何 key 的来源组合）
paper-search search "machine learning clinical prediction" --sources no-key --max-results 5 --pretty

# 指定一个来源，例如 PubMed
paper-search search "SGLT2 inhibitor heart failure" --platform pubmed --max-results 10 --pretty

# 核验一个 DOI
paper-search run get_paper_by_doi --arg doi="10.1038/nature12373" --pretty

# 施引文献；参考文献把 get_paper_citations 换成 get_paper_references
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --arg limit=5 --pretty

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

## 机构下载扩展

开放渠道拿不到的论文，可以用学校的订阅下载：程序打开 Chrome，经 CARSI（中国高校身份联盟）登录你的学校，在出版社网站上取正文和补充材料。

先装好 [Google Chrome](https://www.google.com/chrome/)，再运行：

```bash
paper-search carsi install                # 安装时选择你的学校
paper-search carsi status --format text   # 查看是否装好
```

装好后照常让 AI 下载论文：

- **第一次需要登录时**，在打开的浏览器里登录学校，之后会记住登录状态。
- **人机验证**由程序自动点击，过不去时再提醒你。
- **进度胶囊**在屏幕角落显示进度；需要你登录或验证时变成琥珀色，点一下就切到浏览器。鼠标指上去可以跳过本篇或终止任务，齿轮里可以改等待时间、默认下载文件夹和系统通知。
- **浏览器在后台工作**，不会跳到前台打扰你。
- **下载结束**后，胶囊列出成功和失败的篇目及原因；更详细的原因用 `paper-search failures --format text` 查看。

<p align="center"><img src="assets/progress-capsule.png" width="840" alt="进度胶囊：下载中、需要你登录、鼠标指上去展开、结束时列出成功失败和原因"></p>

能取哪些出版社的正文和补充材料，见 [出版社支持表](skills/paper-search/references/publisher-support.md)。

更新扩展：`paper-search carsi update`；卸载：`paper-search carsi uninstall`。Windows 的 PowerShell 拦住 `npm` 时，改用 `npm.cmd`。

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

## 配置

PaperSearch 有两套配置，各管各的，都可以不配：

|  | API key | CARSI（机构下载扩展） |
|---|---|---|
| 用来做什么 | 部分来源的检索、期刊指标、正文片段检索；Elsevier、Springer 的 key 还能经出版社接口取全文 | 登录你的学校，按学校订阅下载全文和补充材料 |
| 怎么配 | `paper-search setup`，或 `paper-search config set` | `paper-search carsi install`，安装时选学校 |
| 不配时 | 用免费来源检索；“检索来源”里需要 key 的来源和功能不可用 | 下载只走开放下载渠道（见[两种下载方式](#两种下载方式)） |

### API key 与配置文件

多数免费来源不需要配置。建议先运行 `paper-search setup`，把 key 写入用户配置：

```bash
paper-search setup
paper-search config list --pretty
paper-search config set SEMANTIC_SCHOLAR_API_KEY <你的 key>
```

配置文件在 `~/.config/paper-search-cli/config.json`（权限 `0600`），`config list` 和 `doctor` 会把 key 脱敏显示。

| 配置项 | 用途 | 什么时候配置 |
|---|---|---|
| `DEFAULT_DOWNLOAD_PATH` | 下载的论文默认存放的文件夹；不设置时存到命令当前目录下的 `./downloads` | 第一次配置时；也可以在进度胶囊的设置里改 |
| `SEMANTIC_SCHOLAR_API_KEY` | 正文片段检索，更稳定的 Semantic Scholar 请求 | 要查方法细节，或经常用 Semantic Scholar |
| `UNPAYWALL_EMAIL` | 按 DOI 找开放获取 PDF | 推荐配置；填邮箱即可 |
| `CROSSREF_MAILTO` | Crossref 优先通道 | 长任务或高频检索 |
| `CORE_API_KEY` | CORE 仓储检索 | 经常用 CORE 或遇到限流 |
| `EASYSCHOLAR_KEY` | 期刊指标 | 要查影响因子、分区；用 `paper-search setup EASYSCHOLAR_KEY` 隐藏输入 |
| `PUBMED_API_KEY`、`NCBI_EMAIL` | PubMed 更高限额 | 经常用 PubMed |
| `WOS_API_KEY`、`IEEE_API_KEY`、`ELSEVIER_API_KEY`、`SPRINGER_API_KEY` | 各自的元数据；Elsevier、Springer 的 key 也用于出版社接口取全文（权限跟随你的网络或 key） | 要用对应来源时 |
| `ELSEVIER_INSTTOKEN` | 校外经 Elsevier 接口取全文 | 校外需要全文时；校园网不需要 |
| `GOOGLE_SCHOLAR_PROXY_URL` | Google Scholar 的出口代理 | 直连反复被拦时，用有授权的代理 |
| `PAPER_SEARCH_CARSI_ENABLED` | 机构下载扩展的开关 | `paper-search carsi install` 自动设置 |
| `PAPER_SEARCH_SKILL_AUTO_UPDATE` | 设为 `false` 时，升级后不再自动更新已安装的 Skill | 默认开启，想自己管理 Skill 时设置 |
| `PAPER_SEARCH_UPDATE_NOTIFY` | 设为 `false` 时，不再提示有新版本 | 默认开启，不想看到提示时设置 |

申请入口：[EasyScholar](https://www.easyscholar.cc/console/user/open) · [Semantic Scholar](https://www.semanticscholar.org/product/api) · [Unpaywall](https://unpaywall.org/products/api) · [CORE](https://core.ac.uk/services/api) · [NCBI](https://ncbiinsights.ncbi.nlm.nih.gov/2017/11/02/new-api-keys-for-the-e-utilities/) · [Web of Science](https://developer.clarivate.com/apis) · [IEEE Xplore](https://developer.ieee.org/docs/read/Searching_the_IEEE_Xplore_Metadata_API) · [Elsevier](https://dev.elsevier.com/apikey/manage) · [Springer Nature](https://dev.springernature.com/) · [OpenAIRE](https://develop.openaire.eu/)

### CARSI

安装和使用见 [机构下载扩展](#机构下载扩展)。它不用任何 API key，也不提供检索。

## Agent Skill

Skill 随 npm 包发布（`skills/paper-search/`），全中文，开头有整体逻辑图，按需读这些参考文件：功能路由与开放下载的各个渠道、命令约定、机构下载的安装和使用、[出版社支持表](skills/paper-search/references/publisher-support.md)、排障。它只告诉 AI 怎么调用 `paper-search`，不保存 key、Cookie 或账号。

```bash
paper-search skills status --pretty
paper-search skills update --targets claude
```

`--targets` 可选 `codex`、`claude`、`cursor`、`gemini`、`antigravity`、`agents`（共享目录 `~/.agents/skills/`）。其他读取 Skill 文件夹的 AI 工具，把随包 Skill 复制到它的 Skill 目录即可：`npm root -g` 可查看全局 npm 目录，随包 Skill 位于其下的 `papersearch/skills/paper-search/`；复制时保留完整文件夹及 `references/`，更新时从新版本复制。安装后新开 AI 会话即可使用。

- `--targets all` 会同步到所有内置位置。更新会覆盖包里管理的文件，保留你在 Skill 目录里自己加的文件。
- 升级 PaperSearch 后第一次运行时，装过的 Skill 会自动更新，被替换的旧文件备份在 `~/.local/share/paper-search-cli/skill-backups/`。不想自动更新：`paper-search config set PAPER_SEARCH_SKILL_AUTO_UPDATE false`。
- `paper-search doctor` 显示内置安装目标中的 Skill 位置和版本状态。

## 命令

| 命令 | 用途 |
|---|---|
| `paper-search search` | 检索论文元数据 |
| `paper-search journal-metrics` | 期刊指标（EasyScholar） |
| `paper-search download` | 下载已核验论文的 PDF |
| `paper-search run <工具>` | 精确调用某个工具，参数用 `--arg` 或 `--json-args` |
| `paper-search failures` | 汇总下载失败的原因 |
| `paper-search update check` | 检查是否有新版本 |
| `paper-search carsi` | 机构下载扩展的安装、状态、更新、卸载 |
| `paper-search setup` / `config` | 配置 key、Skill 和扩展 |
| `paper-search doctor` | 健康检查：配置、可用功能、Skill 和扩展的状态 |
| `paper-search skills` | Skill 的状态、差异和更新 |
| `paper-search smoke` | 离线或真实的自检 |
| `paper-search tools` | 列出所有工具名和参数 |

命令默认输出 JSON，`--pretty` 排版，`--format text` 输出给人看的报告。完整命令见 `paper-search tools --pretty` 或 [命令约定](skills/paper-search/references/cli-contract.md)。

## 排障

| 问题 | 怎么办 |
|---|---|
| 找不到 `paper-search` 命令 | `npm install -g papersearch` 重新安装 |
| 安装时报 `EEXIST` | 旧包还在：先 `npm uninstall -g paper-search-cli` |
| 某个功能不能用 | `paper-search doctor --format text` 看缺什么，再 `paper-search setup` 配置 |
| 学校订阅的文章下载不到 | `paper-search carsi status --format text` 看扩展是否装好；`paper-search failures --format text` 看每篇的原因 |
| 来源限流 | 减小 `--max-results`、配置对应 key，或换来源 |
| Google Scholar 出验证页 | 等一会儿再试，或改用 `--sources no-key` |
| AI 读到的 Skill 是旧的 | `paper-search skills status --pretty`，再 `paper-search skills update --targets <工具>`；新开一个 AI 会话 |

## 路线图与参与

- 接下来的重点：批量下载更稳、新电脑安装更顺；在 PDF 之外交付全文包（原始 XML/HTML、Markdown 和正文图片）。详见 [路线图](docs/ROADMAP.zh.md)。
- 想了解原理和代码结构：[架构说明](docs/ARCHITECTURE.zh.md)。
- 下载失败或想要支持某家出版社：使用“下载失败 / 想支持某家出版社”Issue 模板，说明版本、系统、网站和 DOI。可以用 `paper-search failures --export ./failure-report.zip` 导出失败记录，先检查包里的 `summary.md` 和截图有没有个人信息，再附到 Issue。
- 想自己加出版社规则：见 [carsi/CONTRIBUTING.md](carsi/CONTRIBUTING.md)。

## 使用边界

部分来源受平台条款、机构订阅或当地法律约束，只在你有相应访问权时使用。机构下载用的是你自己的学校账号和订阅；结果里的来源标记只用于诊断，不能当作授权证明。

## 项目来源

- 感谢 [LinuxDo](https://linux.do) 社区：命令 + Skill 的路线和工作流改进来自社区交流与开源分享。
- [openags/paper-search-mcp](https://github.com/openags/paper-search-mcp)：本项目参考了它的思路，并改成独立的命令行工具。
- [Rimagination/scansci-pdf](https://github.com/Rimagination/scansci-pdf)（MIT）：机构下载后端（`carsi/`）借鉴了它的架构（CARSI 等联盟登录、出版社网站抓取、会话复用、PDF 捕获）；原项目的版权声明保留在 `carsi/NOTICE`。

## License

MIT

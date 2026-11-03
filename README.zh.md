# PaperSearch

简体中文 | [English](README.md)

PaperSearch 是给 AI 工具和终端用的学术文献命令 `paper-search`，随包附带一份 Skill，教 Claude Code、Codex、Cursor 等 AI 工具怎么调用它。它能检索论文、核验 DOI/PMID、查施引文献和参考文献、查期刊影响因子和分区、在正文片段里找方法学写法，以及下载论文 PDF 和补充材料。输出默认是 JSON，方便 AI 和脚本读取。

默认是开放版本：装好就能检索和下载开放获取的论文。需要用学校订阅下载时，可以另装机构下载扩展。

![Node.js](https://img.shields.io/badge/node.js->=18.0.0-green.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Version](https://img.shields.io/badge/version-0.4.0-blue.svg)
[![LinuxDo](https://img.shields.io/badge/LinuxDo-community-1f6feb)](https://linux.do)

[整体逻辑](#整体逻辑) | [快速开始](#快速开始) | [两种下载方式](#两种下载方式) | [检索来源](#检索来源) | [配置](#配置) | [Agent Skill](#agent-skill) | [命令](#命令) | [排障](#排障)

## 整体逻辑

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
     ├─ 每一步拿到文件都核对首页的 DOI 和题名；通过就保存，后面的步骤不再试
     └─ 都没拿到 → paper-search failures 说明原因
```

## 快速开始

要求 Node.js 18 及以上和 npm。

```bash
npm install -g papersearch
paper-search setup
paper-search doctor --format text
```

`paper-search setup` 会依次问三件事：API key 和邮箱；要把 Skill 装到哪些 AI 工具（Claude Code、Codex、Cursor 等）；要不要安装机构下载扩展。每一步都可以跳过。`doctor` 显示现在能用哪些功能、还缺什么配置。

Skill 是教 AI 工具调用 `paper-search` 的说明文件，用 AI 工具做文献任务时要装。跳过了可以随时补装，`--targets` 换成你用的工具（`claude`、`codex`、`cursor`、`gemini`、`agents`，或 `all`）：

```bash
paper-search skills update --targets claude
```

也可以把下面这段话发给你的 AI 工具，让它帮你装：

```text
请帮我安装 PaperSearch：运行 npm install -g papersearch，再运行 paper-search skills update --targets <你自己对应的目标：Claude Code 用 claude，Codex 用 codex，Cursor 用 cursor>，最后运行 paper-search doctor --format text，告诉我哪些功能能用、还缺哪些 key。API key 我会自己在终端运行 paper-search setup 输入，不要让我发到聊天里。
```

**从旧包 `paper-search-cli` 升级**：先运行 `npm uninstall -g paper-search-cli`，再 `npm install -g papersearch`。两个包提供同一个 `paper-search` 命令，不能同时装；配置、Skill、学校登录和下载记录都会保留。

**以后升级**：`npm install -g papersearch@latest`。升级后第一次运行 `paper-search` 时，它会自动把你装过的 Skill 更新到新版本。

试一下各个功能：

```bash
paper-search search "machine learning clinical prediction" --platform crossref --max-results 3 --pretty
paper-search search "large language models" --sources no-key --max-results 5 --pretty
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --arg limit=5 --pretty
paper-search journal-metrics "Nature" "BMJ" --pretty
paper-search download PMC11466435 --platform pmc --save-path ./downloads
paper-search run search_semantic_snippets --arg query="propensity score matching" --arg limit=3 --pretty
```

## 两种下载方式

|  | 开放下载（默认） | 机构下载（可选扩展） |
|---|---|---|
| 能不能直接用 | 装好就能用 | 要另外安装：`paper-search carsi install` |
| 能拿到什么 | 开放获取的正文 | 你的学校订阅的正文；部分出版社还能取补充材料 |
| 怎么拿 | 程序直接下载，通常几秒，不用登录：来源自带的下载、元数据里的 PDF 地址、PubMed Central、Unpaywall、出版社接口（你自己的 Elsevier/Springer key）；最后是默认开启的 Sci-Hub 兜底 | 打开一个浏览器，经 CARSI 登录你的学校，在出版社网站上取 PDF |
| 你要做的事 | 无 | 第一次在浏览器里输入学校账号密码、遇到人机验证时点一下；选学校由程序完成 |

两种方式用同一个下载命令，不需要分开调用：先试开放下载，拿不到时，装了机构下载才继续用学校权限。

```bash
paper-search download "<DOI>" --platform crossref --save-path ./downloads
paper-search run download_batch --json-args '{"items":[{"doi":"<DOI-1>"},{"doi":"<DOI-2>"}],"savePath":"./downloads"}'
paper-search failures --format text
```

- 几十到几百篇用一次 `download_batch`；结束后 `paper-search failures` 把没下载到的篇目分成四类说明：没权限（附页面原话等依据）、需要你处理（登录、验证、等待）、暂不支持的网站、原因不明。
- 不想用 Sci-Hub 时，在 `download_with_fallback` / `download_batch` 里设 `"useSciHub": false`。
- 每个保存的 PDF 都核对首页的 DOI 和题名，不是这篇文章的不保存。

### 机构下载扩展

```bash
paper-search carsi install
paper-search carsi status --format text
```

- 安装时会问你的学校（CARSI 成员学校，中文名、英文名或域名都可以），并下载专用浏览器 Camoufox，共约 3 GB；macOS 上 `--browser ego` 改用 ego lite，约 0.5 GB。`--skip-school` 可以以后再选学校。
- 目前用 CARSI（中国高校身份联盟）登录学校；出版社的机构列表里没有 CARSI 或你的学校时，程序会立即说明，建议在校园网或学校 VPN 下下载。
- `paper-search carsi update` 在 PaperSearch 升级后更新扩展，`paper-search carsi uninstall` 卸载（默认保留浏览器和学校配置）。
- Windows：PowerShell 拦住 `npm.ps1` 时改用 `npm.cmd` 或命令提示符；下载要在桌面会话里运行，经 SSH 或系统服务启动时浏览器窗口打不开。

### 补充材料

`download_with_fallback` / `download_batch` 的 `content` 选择下载内容：`main`（默认，只要正文）、`both`（正文加补充材料）、`supplements`（只要补充材料）。补充材料只经机构下载取得，存在 `<保存目录>/<DOI>_supplements/`，附 `manifest.json` 写明每个文件的状态。

各出版社能不能下正文、能不能下补充材料，见 [出版社支持表](skills/paper-search/references/publisher-support.md)。正文和补充材料都实测取得的有 Elsevier、Wiley、Springer Nature、OUP、Wolters Kluwer、Taylor & Francis、Sage、ACS、NEJM、ASCE、Dove 等；IEEE、Thieme 等目前只取正文；表里没有的网站按通用规则尝试。

## 检索来源

| 类别 | 来源 | 需要的配置 |
|---|---|---|
| 综合学术元数据 | Crossref、OpenAlex、Semantic Scholar、Google Scholar | 不需要；Semantic Scholar 的正文片段检索需要 key；Google Scholar 要明确指定 |
| 生物医学 | PubMed、PubMed Central、Europe PMC | 可选 PubMed key |
| 预印本和会议稿 | bioRxiv、medRxiv、OpenReview、IACR ePrint | 不需要 |
| 计算机和工程 | DBLP、ACM、USENIX、IEEE Xplore | IEEE 需要 key |
| 开放获取和仓储 | CORE、OpenAIRE、Unpaywall | Unpaywall 需要邮箱；CORE key 可选 |
| 引文库和出版社 | Web of Science、Scopus、ScienceDirect、Springer Nature | 需要各自的 key；只提供元数据（Elsevier、Springer 的 key 也用于出版社接口取全文） |
| 期刊指标 | EasyScholar | 需要 EasyScholar key |

- 单个来源用 `--platform`，多个用 `--sources a,b,c`；`--sources no-key` 是不需要任何 key 的组合（Crossref、PubMed、Europe PMC、OpenReview）。
- Google Scholar 是网页解析，容易触发验证，不在 `--sources all` 里；需要时用 `--platform googlescholar`。
- Sci-Hub 不是检索来源，只在下载时按 DOI 兜底。

## 配置

多数免费来源不需要配置。建议先运行 `paper-search setup`，把 key 写入用户配置：

```bash
paper-search setup
paper-search config list --pretty
paper-search config set SEMANTIC_SCHOLAR_API_KEY <你的 key>
```

配置文件在 `~/.config/paper-search-cli/config.json`（权限 `0600`；文件夹沿用旧名，升级不丢设置），`config list` 和 `doctor` 会把 key 脱敏显示。

| 配置项 | 用途 | 什么时候配置 |
|---|---|---|
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

申请入口：[EasyScholar](https://www.easyscholar.cc/console/user/open) · [Semantic Scholar](https://www.semanticscholar.org/product/api) · [Unpaywall](https://unpaywall.org/products/api) · [CORE](https://core.ac.uk/services/api) · [NCBI](https://ncbiinsights.ncbi.nlm.nih.gov/2017/11/02/new-api-keys-for-the-e-utilities/) · [Web of Science](https://developer.clarivate.com/apis) · [IEEE Xplore](https://developer.ieee.org/docs/read/Searching_the_IEEE_Xplore_Metadata_API) · [Elsevier](https://dev.elsevier.com/apikey/manage) · [Springer Nature](https://dev.springernature.com/) · [OpenAIRE](https://develop.openaire.eu/)

## Agent Skill

Skill 随 npm 包发布（`skills/paper-search/`），全中文，开头有整体逻辑图，按需读这些参考文件：功能路由与开放下载的各个渠道、命令约定、机构下载的安装和使用、[出版社支持表](skills/paper-search/references/publisher-support.md)、排障。它只告诉 AI 怎么调用 `paper-search`，不保存 key、Cookie 或账号。

```bash
paper-search skills status --pretty
paper-search skills update --targets claude
```

- 支持的目标：`agents`、`codex`、`claude`、`cursor`、`gemini`、`antigravity`、`all`。更新会覆盖包里管理的文件，保留你在 Skill 目录里自己加的文件。
- **升级后自动更新**：升级 PaperSearch 后第一次运行 `paper-search`（`skills`、`setup` 除外）时，它把你已经装过的 Skill 更新到新版本：只更新原来装过的位置；被替换的旧文件备份在 `~/.local/share/paper-search-cli/skill-backups/`；并在 stderr 写一行说明。一个都没装时只提示一次怎么装。不想自动更新：`paper-search config set PAPER_SEARCH_SKILL_AUTO_UPDATE false`。
- `paper-search doctor` 显示 Skill 装在哪里、是否最新。

## 命令

| 命令 | 用途 |
|---|---|
| `paper-search search` | 检索论文元数据 |
| `paper-search journal-metrics` | 期刊指标（EasyScholar） |
| `paper-search download` | 下载已核验论文的 PDF |
| `paper-search run <工具>` | 精确调用某个工具，参数用 `--arg` 或 `--json-args` |
| `paper-search failures` | 汇总下载失败的原因 |
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

## 使用边界

部分来源受平台条款、机构订阅或当地法律约束，只在你有相应访问权时使用。机构下载用的是你自己的学校账号和订阅；结果里的来源标记只用于诊断，不能当作授权证明。

## 项目来源

- 感谢 [LinuxDo](https://linux.do) 社区：命令 + Skill 的路线和工作流改进来自社区交流与开源分享。
- [openags/paper-search-mcp](https://github.com/openags/paper-search-mcp)：本项目参考了它的思路，并改成独立的命令行工具。
- [Rimagination/scansci-pdf](https://github.com/Rimagination/scansci-pdf)（MIT）：机构下载后端（`carsi/`）由它裁出，只保留机构访问这一段（CARSI 等联盟登录、出版社网站抓取、会话复用、PDF 捕获），再逐家补充出版社规则；原项目的版权声明保留在 `carsi/NOTICE`。

## License

MIT

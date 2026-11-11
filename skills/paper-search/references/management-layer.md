# 管理层：安装、检查、更新、Skill 同步

用这一篇判断 `paper-search` 是否已安装、已配置、运行正常，以及已安装的 Skill 是否与包内的一致。这些命令只帮助判断能不能用，本身不做文献任务。

## 只装了 Skill 时

用户先装了这个 Skill（例如用 `npx skills add`），`command -v paper-search` 却找不到命令时，直接按下面做。不要到别的目录翻找命令，也不要读 `~/.npmrc`、shell 配置这类文件：里面可能有令牌，会出现在输出里。

1. 运行 `node --version`。没有 Node.js 或版本低于 22 时，请用户先装 Node.js 的 LTS 版（https://nodejs.org），装好后新开终端再继续；不替用户装 Node.js。
2. 先问用户，同意后才装：说明要用 npm 全局安装 PaperSearch 的命令行程序（npm 包 `papersearch`，提供 `paper-search` 命令），命令是 `npm install -g papersearch@latest`。
3. 用户同意后运行它，再运行 `paper-search --version` 确认。报权限错误（`EACCES`）时不加 `sudo`，把命令交给用户在自己的终端运行。Windows 的 PowerShell 拦住 `npm`、`paper-search`（脚本执行策略）时，改用 `npm.cmd`、`paper-search.cmd`，不改执行策略。
4. 不运行 `paper-search skills update`：Skill 已经装好，就是你正在读的这份，再装会多出一份同名 Skill。以后升级 PaperSearch 时，这份 Skill 会自动更新。
5. 运行 `paper-search doctor --format text`，用一句话告诉用户现在能用哪些功能，然后接着做用户原来的请求：是“请开始配置”就按 `setup.md` 往下走；是文献请求就先提一句需要配置时说“请开始配置”，再去做。

## 管理命令

```bash
paper-search doctor --pretty
paper-search doctor --format text
paper-search smoke --mock --pretty
paper-search smoke --live --pretty
paper-search skills status --pretty
paper-search skills diff --format text
paper-search skills update --pretty
paper-search tools --pretty
paper-search config list --pretty
```

| 命令 | 作用 | 何时用 |
|---|---|---|
| `paper-search doctor --pretty` | 完整健康报告：脱敏后的配置、能力概况、各来源状态和缺少的项目 | 第一次使用、环境不确定，或用户问现在能用哪些功能 |
| `paper-search doctor --format text` | 给人看的健康报告 | 需要向用户概括健康状况 |
| `paper-search smoke --mock --pretty` | 离线检查命令接线、能力概况的判断和 Skill 同步状态的判断 | 改过代码或安装之后，或没有网络时 |
| `paper-search smoke --live --pretty` | 小规模真实检查：免费元数据来源、已配置 key 的功能、Sci-Hub 镜像是否可用 | 用户要求本机实测，或怀疑来源、网络有问题 |
| `paper-search skills status --pretty` | 显示已安装的 Skill 是否与包内 Skill 一致 | 安装、更新检查，或排查 agent 读到旧 Skill |
| `paper-search skills diff --format text` | 预览包内 Skill 与已安装 Skill 的差异 | 更新 Skill 之前 |
| `paper-search skills update --pretty` | 把包管理的 Skill 文件同步到用户的 Skill 目录，保留用户自己加的文件 | 用户确认更新 Skill 之后 |
| `paper-search tools --pretty` | 列出 `paper-search run` 的工具名和参数结构 | 不确定工具名或参数时 |
| `paper-search config list --pretty` | 显示脱敏后的配置状态 | 确认 key、email、开关是否已配置 |

## 卸载

用户要卸载 PaperSearch 时：

1. 运行 `paper-search uninstall --dry-run --format text`，把要删和保留的内容告诉用户（学校订阅下载和登录状态、运行记录、配置和 API key、各 AI 工具里的 Skill；下载的论文保留）。
2. 用户同意后运行 `paper-search uninstall --yes --format text`。有文件没删掉时，按输出提示请用户关掉进度窗口和下载用的 Chrome，再运行一次。
3. 最后运行 `npm uninstall -g papersearch`（Windows PowerShell 用 `npm.cmd`）。

只删学校订阅下载用 `paper-search carsi uninstall`（见 `carsi-setup.md`）。

## 健康检查（doctor）

`paper-search doctor` 是主要的健康报告，包含脱敏后的配置、能力概况和各来源状态。

能力概况里的每一项是一种独立的能力：

- `metadata_search`：经已配置或免费的文献来源检索元数据。Sci-Hub 不算检索来源。
- `citation_expansion`：查已知论文的施引文献（OpenAlex）和参考文献（出版商在 Crossref 的清单或 OpenAlex），不需要 key。`OPENALEX_API_KEY` 可选：不配时施引文献最多列出最新的 1 万条，配了能全部列出。
- `body_snippet_search`：Semantic Scholar 开放获取正文片段检索，需要 `SEMANTIC_SCHOLAR_API_KEY`。
- `journal_metrics`：EasyScholar 期刊指标，需要 `EASYSCHOLAR_KEY`。
- `pdf_discovery`：PDF 获取与下载，经来源自带的下载、元数据里的 PDF 地址、开放获取来源、机构库、Unpaywall，以及默认开启的 Sci-Hub 兜底。
- `entitled_access`：可选的机构下载后端（CARSI）。机构下载后端（CARSI）是唯一可选的授权下载后端，默认关闭。`doctor`、交互式 `setup` 和真实冒烟测试会给出它的运行状态：`disabled`（未启用）、`absent`（找不到后端）、`incompatible`（后端版本不兼容）或 `available`（能连上）；离线的能力概况不启动后端，显示 `not_evaluated`。

出版社或数据库的 key（记为 `metadata_entitled`）与 `entitled_access` 无关：它们只开放元数据或开放获取接口，不能当作本机的授权 PDF 后端。除机构下载后端外，没有浏览器、WebVPN 或 EZProxy 兜底。

`PAPER_SEARCH_CARSI_ENABLED` 不是密钥，只有值恰好是 `true` 时才启用机构下载后端。单次请求的 `useEntitledAccess` 默认是 `true`，但只能关掉这一层，不能绕过全局关闭。一次下载失败只影响那一次，不改写全局的可用状态。

agent 做判断时读 JSON 输出；只有用户需要可读报告时才用 `--format text`。

## 冒烟测试（smoke）

`paper-search smoke --mock` 完全离线，没有任何 key 也应通过。它不启动机构下载后端，离线快照里显示 `not_evaluated`。

`paper-search smoke --live` 做小规模的真实检查：

- 免费元数据来源总是检查；
- 默认检查 Sci-Hub 镜像是否可用，不下载 PDF；
- 已配置 key 的功能做轻量检查，未配置的标为 `skipped`；
- 已启用的机构下载后端只做接口兼容检查（`initialize + tools/list`），不清缓存、不登录、不下载 PDF。

真实冒烟测试的严重程度：

- `critical`：命令判为失败。
- `degraded`：已配置或默认开启的功能没按预期工作，必须带修复建议，但不等于整个工具不可用。
- `warning`、`skipped`：仅供参考。

报告结果时，把 `degraded` 项的 `message` 和 `remediation` 一起告诉用户。

## Skill 同步

npm 包在 `skills/paper-search` 下自带一份 Skill（包内 Skill）。安装或更新用户可见的 Skill 文件需要明确执行命令。

支持的目标：`agents`、`codex`、`claude`、`cursor`、`gemini`、`antigravity`。不写 `--targets` 时只针对已经装了 Skill 的位置（链接到同一个文件夹的算一处），不会在别处多装一份；一个都没装时，装到 `~/.agents/skills`，没有这个文件夹时装到 codex、claude、cursor。

包更新后的例行同步：

```bash
paper-search skills status --pretty
paper-search skills diff --format text
paper-search skills update --pretty
```

`skills update` 覆盖包管理的文件，保留用户自己加的文件；`skills diff` 只显示包管理文件的差异，用户自己加的文件只列文件名。

升级后自动同步：升级 PaperSearch 后第一次运行 `paper-search`（`skills`、`setup` 除外）时，它把用户已经装过的 Skill 更新到包内版本：只更新原来装过的位置，保留用户自己加的文件，替换下来的旧文件备份在 `${XDG_DATA_HOME:-~/.local/share}/paper-search-cli/skill-backups/`，并在 stderr 写一行说明；一个都没装时只提示一次怎么装。`paper-search config set PAPER_SEARCH_SKILL_AUTO_UPDATE false` 关闭，之后用 `skills update` 手动同步。`doctor` 的 `skills` 一项列出各位置是否最新。看到 stderr 里的更新说明时，告诉用户新开的 AI 会话才会读到新版本。

## 包更新与功能配置

`skills update` 只把包内 Skill 同步到选定的 Skill 目录，不更新 npm 包、GitHub 检出、编译后的命令文件或数据源配置。

`paper-search setup` 只为当前已安装的命令配置 key、email 和 Skill 安装位置，不更新包本体。

普通用户的更新步骤（从旧包 `paper-search-cli` 升级时，先运行 `npm uninstall -g paper-search-cli`，两个包提供同一个 `paper-search` 命令，不能同时装；配置和 Skill 都保留）：

```bash
npm install -g papersearch@latest
paper-search skills update --pretty
paper-search doctor --pretty
paper-search setup
paper-search smoke --mock --pretty
```

配 key 时，请用户在自己的终端运行 `paper-search setup <KEY>`（输入时不显示），或在设置窗口里填，再用 `paper-search config test <KEY>` 确认。`setup` 前后都可以用 `doctor` 看能力概况。缺少、不可用或降级的能力会写明用户需要配置哪个 key、email、来源或环境项。第一次配置还要问用户下载的论文默认放到哪个文件夹，设到 `DEFAULT_DOWNLOAD_PATH`，见 SKILL.md 的“默认下载文件夹”。

维护者或本地开发版的更新步骤：

```bash
git pull
npm install
npm run build
npm install -g .
paper-search skills update --pretty
paper-search doctor --pretty
paper-search setup
paper-search smoke --mock --pretty
```

`npm install -g .` 把全局命令链接到这个仓库目录，之后仓库重新编译，全局命令随之变化。要装一个固定的版本，先运行 `npm pack`，再 `npm install -g <生成的 .tgz>`。发布前或在本机全局安装本地构建前，用这条路径验证仓库。

学校订阅下载（CARSI 后端）与 PaperSearch 本体分开更新，只在用户要求时安装：

```bash
paper-search carsi status --format text
paper-search carsi install
paper-search doctor --pretty
```

`install` 先检查本机有 Google Chrome，列出要下载的内容和位置，再准备它自己的 Python、安装后端，并启用它（`PAPER_SEARCH_CARSI_ENABLED=true`、`PAPER_SEARCH_CARSI_EXECUTABLE`）。PaperSearch 升级后，第一次用到学校订阅下载时，CLI 先自动更新扩展再下载（stderr 一行说明；另一个下载正在用扩展、或更新没成功时，这次用旧版本继续）；用户关掉自动更新（`PAPER_SEARCH_CARSI_AUTO_UPDATE=false`）时，`status` 会提示何时运行 `paper-search carsi update`。用户在别处维护的后端用 `paper-search config set PAPER_SEARCH_CARSI_EXECUTABLE <路径>` 指定。学校、浏览器（Google Chrome 或 ego）和账号见 `carsi-setup.md`；账号密码只在用户自己的浏览器里输入，不进聊天、配置、命令参数或日志。`doctor` 显示 `available` 只证明后端接口能用，不代表已登录学校或对某篇有权限。日常下载仍用 `paper-search download`、`paper-search run download_with_fallback` 或 `download_batch`，见 `browser-download.md`。

## 配置检查

配置来源按优先级：

1. Shell 环境变量
2. 当前目录的 `.env`
3. 用户配置文件 `~/.config/paper-search-cli/config.json`
4. 免费来源的内置默认值

常用命令：

```bash
paper-search setup
paper-search config list --pretty
paper-search config get SEMANTIC_SCHOLAR_API_KEY --pretty
paper-search config get EASYSCHOLAR_KEY --pretty
paper-search doctor --pretty
```

`doctor` 和 `config` 的输出会把已配置的密钥脱敏。

## CLI 新版提醒

日常在线任务可异步检查 npm `papersearch` 的稳定新版，成功结果缓存 24 小时，失败或未完成请求退避 1 小时。发现新版后，每次日常调用提示一次当前/最新版本和匹配安装渠道的升级命令；提醒在 stderr，stdout JSON 和原任务结果不变。离线管理命令不联网，CI、help/version/config/setup/update 不自动提醒。

`paper-search config set PAPER_SEARCH_UPDATE_NOTIFY false` 关闭自动检查和提醒；`true` 重新开启。此设置与胶囊/系统通知独立。`paper-search update check --format text` 可主动检查，关闭自动提醒后也可用；网络不可用时如实报告无法查询，不猜测最新版本。旧安装缺少该命令时只报告其版本，不伪造检查成功。

看到提醒可以向用户说明有新版；未经授权，不执行提示中的升级命令。更新 CLI 包本体、已安装 Skill 同步、更新扩展（升级后第一次用到时自动进行，或 `paper-search carsi update`）是三个不同步骤。

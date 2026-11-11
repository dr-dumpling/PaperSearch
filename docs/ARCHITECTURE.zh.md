# PaperSearch 架构说明

这份文档写给想了解 PaperSearch 怎么运转、为什么可信，或者想参与改进的人。怎么安装和使用见 [README](../README.md)，接下来做什么见 [路线图](./ROADMAP.zh.md)。

## 设计原则

1. **开放来源优先**：同一个下载命令先试开放获取渠道，拿不到才用机构下载。机构下载是可以单独安装和卸载的扩展，不装也不影响其他功能。
2. **拿到的文件都要核对**：每个 PDF 都核对前几页的 DOI 和题名，对不上的不算成功，单独留给你核查。“浏览器里显示了 PDF”不等于拿到了这篇文章。
3. **账号只在你自己的浏览器里输入**：学校账号密码由你在下载浏览器里输入，程序不读取、不保存密码；API key 存在只有你能读的本机配置文件里，输出和日志里都脱敏。
4. **每次运行都可追溯**：每篇论文试了哪些渠道、各自结果如何、为什么失败，都写进本机的运行记录；`paper-search failures` 按原因汇总。
5. **给 AI 用，也给人用**：所有命令默认输出一份 JSON，进度提示走 stderr，脚本和 AI 都能稳定读取；随包 Skill 教 AI 怎么调用。

## 两个程序

```text
你 / AI 工具（Claude Code、Codex、DeepSeek……）
   │  读随包 Skill，调用 paper-search 命令
   ▼
paper-search（TypeScript，npm 包 papersearch）
   检索、引文、期刊指标、正文片段、下载编排、PDF 核对、运行记录、安装和诊断
   │  需要学校订阅时，作为子进程启动（MCP，标准输入输出）
   ▼
paper-search-carsi（Python，可选，代码在 carsi/，用 paper-search carsi install 安装）
   专用浏览器、经 CARSI 登录学校、出版社网站规则、取 PDF 和补充材料、进度窗口
```

两边只通过一个固定的工具接口通信。机构下载这一侧怎么改，都不会影响检索和开放下载；接口不兼容时，`paper-search doctor` 会直接报告。

## 五项文献能力

| 能力 | 入口 | 说明 |
|---|---|---|
| 检索与核验 | `paper-search search`、`run search_*`、`run get_paper_by_doi` | 20 多个来源并发检索，单个来源失败不影响整体；按 DOI、题名和作者去重。核对 DOI 先查 Crossref，查不到才问其他来源，一次最多核对 100 个 |
| 引文扩展 | `run get_paper_citations`、`run get_paper_references` | 施引文献经 OpenAlex，没有记录时用 Semantic Scholar；参考文献按 Crossref 里出版社登记的清单，保留原序号并标出缺号，没有时再用 OpenAlex、Semantic Scholar |
| 期刊指标 | `paper-search journal-metrics` | 经 EasyScholar 查影响因子、JCR 和中科院分区等 |
| 正文片段 | `run search_semantic_snippets` | 在 Semantic Scholar 的开放获取正文索引里找方法学写法和参数 |
| 下载 | `paper-search download`、`run download_with_fallback`、`run download_batch` | 下面详细说明 |

另有一组管理命令：`setup`、`settings`、`config`、`status`、`doctor`、`diagnostics`、`skills`、`carsi`、`update`、`uninstall`、`failures`、`smoke`、`tools`。它们负责安装、配置、更新、卸载和诊断，不参与文献任务本身。随包 Skill 写明对应的 PaperSearch 版本，较旧的命令不会覆盖已装的较新 Skill。

## 一次下载怎么走

```text
paper-search download <DOI>
  │
  ├─ 1 来源自带的下载        检索来源本身提供的开放 PDF
  ├─ 2 元数据里的 PDF 地址
  ├─ 3 PubMed Central       经官方渠道按 DOI 找 PMC 全文，再试 Europe PMC
  ├─ 4 Unpaywall            试遍所有开放获取位置
  ├─ 5 出版社接口           用你自己的 Elsevier / Springer key
  ├─ 6 Sci-Hub              默认开启，可按请求关闭
  ├─ 7 机构下载             装了扩展才有：启动 paper-search-carsi
  │     ├─ 按 DOI 实际跳转到的网站选出版社规则；没有专门规则的网站用通用规则
  │     ├─ 专用浏览器打开文章页 → 出版社的机构登录 → 选 CARSI 和你的学校
  │     │    （自动选校，学校登录页由你输入账号）
  │     ├─ 遇到 Cloudflare/Turnstile 验证框 → 自动定位并点击 → 网站放行后继续
  │     │    （reCAPTCHA、hCaptcha、滑块等其他验证交给你完成）
  │     ├─ 取正文 PDF；需要时在文章页找补充材料，只收这篇文章的文件
  │     └─ 结果和失败原因原路返回
  └─ 8 arXiv 预印本         前面都没拿到正式发表版时才用，并标明是预印本
  │
  每一层拿到文件都先核对 DOI 和题名：通过就保存并结束，不通过就留待核查、继续下一层
  │
  ▼
stdout 输出一份 JSON：成功与否、文件位置、每一层的尝试记录
```

批量下载（`download_batch`）默认两路同时进行：开放渠道逐篇往下查，没拿到正文的篇目立即交给机构下载，机构下载一次只下一篇；开放渠道拿到正文的篇目要补充材料时，最后再去文章页取。进度窗口里可以跳过一篇或终止整个任务，已经保存的文件都会保留。

## 机构下载这一侧

- **出版社规则从通用到具体分四层**，新差异放在能覆盖它的最通用的一层：
  1. 通用流程（`engine/`）：几乎所有出版社都遵循的步骤，不写任何出版社、平台或学校；
  2. 网站平台（`adapters/platforms/`）：Atypon、Silverchair 等同一套网站系统共有的规则，用这套系统的出版社直接继承；
  3. 出版社（`adapters/<出版社>/`，以及 `publishers/builtin/` 里的配置：域名、DOI 前缀、文章和 PDF 地址模板、登录入口的识别方式）；
  4. 单本期刊：只有它一家特殊时才单独写。
- **机构入口**：CARSI 等联盟的登录流程，由维护者处理。
- **浏览器**：默认用你电脑上的 Google Chrome（下载用单独的浏览器资料，不动日常用的 Chrome），macOS 上可改用 ego lite。登录状态保存在本机，下次下载直接复用。
- **验证框自动交互**：在文章页和 PDF 获取过程中自动定位、点击 Cloudflare/Turnstile 验证框，网站放行后继续下载。每次验证等待最多尝试 3 次，两次至少间隔 3 秒；自动阶段结束后仍未放行时提示人工接管，沿用原等待时限。reCAPTCHA、hCaptcha、DataDome、GeeTest、阿里云等其他验证程序只识别、不操作，直接请你完成；认不出的页面停住一段时间、页面上又有可点的控件时，也会提醒你去看一眼。
- **等待和限速**：停在学校登录页最多等 3 分钟，停在其他页面默认 1 分钟就结束这一篇，浏览器某一步卡死会被中断；每家出版社每小时最多下载的篇数可以设置。这些都能在进度窗口的齿轮里调整。出版社的院校列表里没有你的学校时立即结束；同一批里这家出版社后面的文章仍会打开、能直接取得的 PDF 照常取得，只是不再等登录。
- **失败分类**：没权限、需要你处理、暂不支持的网站、原因不明，每类都附依据（例如页面上的原话），不把“没登录”说成“没权限”。

各出版社的支持情况见 [出版社支持表](../skills/paper-search/references/publisher-support.md)。

## 数据放在哪里

| 内容 | 位置 |
|---|---|
| 下载的论文 | 你指定的目录里每次下载新建的 `<年月日-时分秒>_PaperSearchDownload` 文件夹：PDF 直接放在里面；取到了补充材料的论文单独一个文件夹，正文和 `supplements/` 在其中 |
| 配置和 API key | `~/.config/paper-search-cli/config.json`（权限 `0600`） |
| 运行记录 | `~/.local/share/paper-search-cli/runs/`：每次运行一个目录，含出过问题篇目的诊断记录和截图；保留 30 天 |
| 机构下载的学校设置和登录状态 | `~/.local/share/paper-search-cli/carsi/` |

都只在你的电脑上，不上传到任何地方。

## 代码地图

```text
src/
├── cli.ts              命令入口：解析参数、分发命令、输出 JSON
├── core/               工具清单、参数校验、工具路由
├── capabilities/       五项文献能力，下载编排在 pdf-discovery/
├── platforms/          每个检索来源一个 Searcher
├── registry/           检索来源的登记表和创建方式
├── infrastructure/     HTTP、缓存、限流、PDF 下载与核对、运行记录
├── management/         setup、doctor、skills、carsi 安装等管理功能
└── config/、models/    配置和统一的论文数据模型
carsi/paper_search_carsi/
├── server.py           对 paper-search 提供的工具接口
├── engine/             一篇论文的完整下载流程、等待、补充材料
├── browser/            浏览器启动、登录状态保存、验证识别与点击、卡死保护
├── publishers/         出版社配置（builtin/*.json）和通用网站规则
├── adapters/           出版社适配器
├── progress_capsule.py 进度胶囊（页面在 assets/capsule.html）
└── capsule_window.py   胶囊在 Mac/Windows 上的窗口：位置、屏幕、拖动
skills/paper-search/    随包 Skill 和参考文件
tests/、carsi/tests/    两侧的自动化测试
```

## 怎么扩展

- **加一个检索来源**：在 `src/platforms/` 新增一个 Searcher（继承 `PaperSource`），在 `src/registry/` 的登记表里登记名称、别名、所需配置和能力，再补测试。
- **加一家出版社**：按 [carsi/CONTRIBUTING.md](../carsi/CONTRIBUTING.md) 新增出版社配置，必要时写适配器；验证框识别与自动点击复用通用浏览器模块，学校从配置读取。
- **加一条下载渠道**：实现一个下载层（`DownloadTier`），插到下载顺序里的合适位置；它拿到的文件同样要过身份核对。

## 稳定接口

写脚本或接入其他工具时可以依赖这些，改动会在发布说明里写明：

- `paper-search tools --pretty` 列出的工具名和参数；
- 命令输出的 JSON 结构，包括下载结果里每一层的尝试记录；
- stdout 只有一份最终 JSON，进度提示只在 stderr。

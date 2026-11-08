<p align="center">
  <img src="assets/logo.svg" width="80" alt="PaperSearch 图标">
</p>

<h1 align="center">PaperSearch</h1>

<p align="center"><b>轻量、全自动的 AI 文献全能工具</b><br>
一句话让AI完成文献检索、核对、下载全文和补充材料，后台自动完成。</p>

<p align="center">简体中文 | <a href="README.en.md">English</a></p>

<p align="center">
  <a href="https://www.npmjs.com/package/papersearch"><img src="https://img.shields.io/npm/v/papersearch?style=flat-square" alt="npm"></a>
  <a href="https://github.com/dr-dumpling/PaperSearch/actions/workflows/publish.yml"><img src="https://img.shields.io/github/actions/workflow/status/dr-dumpling/PaperSearch/publish.yml?style=flat-square&amp;label=publish" alt="发布工作流状态"></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/node/v/papersearch?style=flat-square" alt="Node.js 版本要求"></a>
  <a href="#1-学校订阅下载carsi"><img src="https://img.shields.io/badge/CARSI-supported-7284CE?style=flat-square" alt="学校订阅下载 CARSI"></a>
  <a href="docs/guide.zh.md#agent-skill"><img src="https://img.shields.io/badge/Agent%20Skill-bundled-D97757?style=flat-square" alt="随包 Agent Skill"></a>
  <a href="#快速开始"><img src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows-555555?style=flat-square" alt="支持 macOS 和 Windows"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2F9E44?style=flat-square" alt="MIT 许可证"></a>
</p>

<p align="center">
  <a href="#演示视频">演示视频</a> · <a href="#快速开始">快速开始</a> · <a href="#1-学校订阅下载carsi">学校订阅下载</a> · <a href="#2-api-key">API key</a> · <a href="docs/guide.zh.md">使用说明</a> · <a href="docs/ARCHITECTURE.zh.md">架构说明</a> · <a href="docs/ROADMAP.zh.md">路线图</a> · <a href="https://github.com/dr-dumpling/PaperSearch/issues/new/choose">反馈问题</a>
</p>

PaperSearch 提供 `paper-search` 命令和一份随包 Skill。装好后，Claude Code、Codex、Cursor、Kimi Code、Qwen Code、CodeBuddy、TRAE 等支持本机命令调用的 AI 工具，就能替你：

- **检索论文**：一次查 PubMed、Crossref、OpenAlex、Semantic Scholar、arXiv 等 20 多个数据源，按 DOI 合并重复，核对 DOI。
- **搜正文片段**：利用 Semantic Scholar 收录的论文正文，搜原句，找到方法、结果的原文和出处。
- **查期刊 IF 与分区**：利用 EasyScholar，查找 JCR 影响因子、JCR 分区和中科院分区。
- **查引文和参考文献**：顺着一篇论文，找出引用它的研究和它引用的文献。
- **下载全文和补充材料**：
  - OA 文章：直接下载。
  - 非 OA 文章：通过学校订阅下载。可以装上“学校订阅下载（CARSI）”，经学校登录批量下载；也可以填写出版社的 API key 下载。

<p align="center"><img src="assets/overview.png" width="840" alt="PaperSearch 能做的事：检索论文、搜正文片段、查期刊 IF 与分区、查引文和参考文献、下载全文和补充材料"></p>

## 演示视频



https://github.com/user-attachments/assets/7573a2a8-0778-4062-aa3e-4ccffb482b0b



## 快速开始

<p align="center"><img src="assets/quickstart.webp" width="840" alt="安装演示：一行命令装好 PaperSearch 并给 AI 装上 Skill，再运行 paper-search doctor 查看哪些功能已能用"></p>

### 1. 安装

- 自己装：复制一行命令（以 Codex 为例）。用其他 AI 工具时，把 `codex` 换成 `claude`、`cursor`、`gemini`、`antigravity` 或 `agents`（共享目录 `~/.agents/skills/`）。

  ```sh
  npm install -g papersearch && paper-search skills update --targets codex
  ```

- 让 AI 帮你装：把下面这段话发给你的 AI 工具。

  ```text
  请帮我安装 PaperSearch：运行 npm install -g papersearch；
  再运行 paper-search skills update --targets 你的类型，给你自己装上随包 Skill
  （类型可选 codex、claude、cursor、gemini、antigravity、agents）；
  最后运行 paper-search doctor --format text，告诉我哪些功能可用。
  API key 我会自己用 paper-search setup 输入。
  ```

### 2. 对 AI 说一句话

新开一个 AI 会话，说你要做什么，例如：

| 想做什么 | 可以这样说 |
|---|---|
| 检索论文 | 找 2020 年以来 SGLT2 抑制剂治疗心力衰竭的随机对照试验，核对 DOI |
| 搜正文片段 | 这些试验的主要终点，原文是怎么定义的？摘几段原文 |
| 查期刊 IF 与分区 | 它们发表在哪些期刊？影响因子和分区各是多少 |
| 查引文和参考文献 | DAPA-HF 试验发表后，有哪些研究引用了它 |
| 下载全文和补充材料 | 把这些论文的全文和补充材料下载到 ./downloads |

### 3. 拿到结果

- 检索、正文片段、期刊指标和引文，直接在对话里列给你。
- 下载的论文整理成文件夹，没拿到的篇目告诉你原因：

  ```text
  downloads/
  ├── papers/
  │   ├── Nutrients_2026_α-Ketoglutarate Alleviates the Pathogenesis…_0b6e0203de/
  │   │   ├── Nutrients_2026_α-Ketoglutarate Alleviates the Pathogenesis….pdf
  │   │   └── supplements/
  │   │       └── nutrients-18-03600-s001.zip
  │   └── arXiv_2017_Attention Is All You Need_a1a0262a54/
  │       └── arXiv_2017_Attention Is All You Need.pdf
  └── diagnostics/
  ```

### 4. 按需加上配置

**装好就能用**：检索论文、查引文和参考文献、下载开放获取的论文。

**加上配置，还能：**

- **查影响因子和分区**：填入 EasyScholar key，JCR 影响因子、JCR 分区和中科院分区一次查清。
- **在正文里找原句**：填入 Semantic Scholar key，直接搜开放获取论文的正文，找到相关段落的原文和出处。
- **下载学校订阅的论文**，两种方式：
  - 装上学校订阅下载（CARSI）：在 Chrome 里登录学校，开放渠道下不到的全文和补充材料也能批量下载。
  - 填入 Elsevier、Springer 的 API key：在校园网里经出版社接口直接取全文，不用开浏览器；校外下 Elsevier 订阅文章还要填 `ELSEVIER_INSTTOKEN`。

怎么配见下面的 [可选配置](#可选配置)。随时运行 `paper-search doctor --format text`，查看哪些功能已经能用。

## 可选配置

学校订阅下载只管下载；API key 对应各个数据源和服务，管的功能更多：

| 功能 | 学校订阅下载（CARSI） | API key |
|---|---|---|
| 下载学校订阅的全文 | ✓ | ✓ 仅 Elsevier、Springer（一般要在校园网） |
| 下载补充材料 | ✓ | |
| 查影响因子和分区 | | ✓ EasyScholar |
| 搜正文片段 | | ✓ Semantic Scholar |
| 更多检索来源、更高限额 | | ✓ 各来源自己的 key |
| **需要准备** | Google Chrome、学校账号 | 到各家网站申请 key |
| **怎么配置** | `paper-search carsi install` | `paper-search setup` |

### 1. 学校订阅下载（CARSI）

开放渠道下不到的论文，可以借你学校的订阅来下。CARSI 是中国高校身份联盟，国内高校基本都已加入，用学校账号就能登录各家出版社。

<table>
  <tr>
    <td width="50%" valign="top">
      <img src="assets/carsi-capsule.webp" alt="进度胶囊：下载时缩成小胶囊，悬停查看每篇进度，最小化到程序坞照常下载，点一下就回来">
      <p><b>进度胶囊</b><br><sub>下载时缩成屏幕角落的小胶囊；悬停查看每篇进度，最小化到程序坞也照常下载。</sub></p>
    </td>
    <td width="50%" valign="top">
      <img src="assets/carsi-signin.webp" alt="自动登录学校：点胶囊里的题名，浏览器回到前台；自动点机构登录、填好学校，转到学校登录页">
      <p><b>自动登录学校</b><br><sub>点胶囊里的题名，浏览器回到前台；机构登录入口自动点开，学校自动填好。</sub></p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img src="assets/carsi-attention.webp" alt="需要你时提醒：要登录学校时胶囊变黄，点它切到浏览器，也能跳过这一篇">
      <p><b>需要你时提醒</b><br><sub>需要你登录学校时胶囊变黄；点它切到浏览器，也可以跳过这一篇。</sub></p>
    </td>
    <td width="50%" valign="top">
      <img src="assets/carsi-finish.webp" alt="结束清单：跳过不想等的论文；下完列出结果，没下到的写明原因，点题名在自己的浏览器里打开">
      <p><b>结束清单</b><br><sub>不想等的论文可以跳过；下完列出成功和失败，没下到的写明原因，点题名在自己的浏览器里打开。</sub></p>
    </td>
  </tr>
</table>

- **学校账号就能用**：不用另外申请 key；出版社 API key 只覆盖 Elsevier、Springer 两家。
- **深度适配出版社**：深度优化了下载的通用流程，并且针对 30 多家出版社逐家写了专门规则，机构登录入口在哪、PDF 和补充材料怎么取，都按各自出版社的实际情况来，下载更准、更少漏篇。优化的出版社主要有：
  - 综合：Elsevier（含 Cell、Lancet）、Springer Nature（含 Nature、BMC）、Wiley、Oxford Academic、Taylor & Francis、Sage、PNAS、Science
  - 医学：NEJM、JAMA、AHA、ASH、Wolters Kluwer、Karger、Thieme
  - 理工：ACS、IEEE、ACM
  - 完整列表见 [出版社支持表](skills/paper-search/references/publisher-support.md)
  - 需要支持别的出版社，欢迎[提 Issue](https://github.com/dr-dumpling/PaperSearch/issues/new/choose)，附上一篇你有权限的文章 DOI；这些适配规则会持续维护和更新。
- **验证框自动点击**：遇到人机验证，程序自动定位并点击，网站放行后继续下载；过不去才提醒你。
- **后台下载不打扰**：浏览器在后台工作。屏幕角落的进度胶囊显示进度；需要你登录学校或手动验证时变成琥珀色，点一下就切到浏览器，处理完程序接着下载。

电脑上需要已装有 [Google Chrome](https://www.google.com/chrome/)。安装：

```bash
paper-search carsi install                # 安装时选择你的学校
paper-search carsi status --format text   # 查看是否装好
```

### 2. API key

按用途分四类，需要哪类就申请对应的 key，再用 `paper-search setup <KEY>` 填入（输入时不显示）。

#### 查期刊、搜正文

| 功能 | 要填的 key | 去哪里申请 |
|---|---|---|
| 查影响因子和分区 | `EASYSCHOLAR_KEY` | [EasyScholar](https://www.easyscholar.cc/console/user/open) |
| 搜正文片段 | `SEMANTIC_SCHOLAR_API_KEY` | [Semantic Scholar](https://www.semanticscholar.org/product/api) |

#### 下载订阅全文（出版社接口）

| 出版社 | 要填的 key | 去哪里申请 |
|---|---|---|
| Elsevier | `ELSEVIER_API_KEY`；校外下订阅文章还要 `ELSEVIER_INSTTOKEN` | [Elsevier](https://dev.elsevier.com/apikey/manage) |
| Springer | `SPRINGER_API_KEY` | [Springer Nature](https://dev.springernature.com/) |

#### 增加检索来源

| 来源 | 要填的 key | 去哪里申请 |
|---|---|---|
| Web of Science | `WOS_API_KEY` | [Clarivate](https://developer.clarivate.com/apis) |
| IEEE Xplore | `IEEE_API_KEY` | [IEEE](https://developer.ieee.org/docs/read/Searching_the_IEEE_Xplore_Metadata_API) |
| ScienceDirect、Scopus | `ELSEVIER_API_KEY`（和上面同一个） | [Elsevier](https://dev.elsevier.com/apikey/manage) |
| Springer | `SPRINGER_API_KEY`（和上面同一个） | [Springer Nature](https://dev.springernature.com/) |

#### 提高限额、更稳定

| 来源 | 要填的 key | 去哪里申请 |
|---|---|---|
| PubMed | `PUBMED_API_KEY` | [NCBI](https://ncbiinsights.ncbi.nlm.nih.gov/2017/11/02/new-api-keys-for-the-e-utilities/) |
| CORE | `CORE_API_KEY` | [CORE](https://core.ac.uk/services/api) |
| OpenAIRE | `OPENAIRE_API_KEY` | [OpenAIRE](https://develop.openaire.eu/) |

常用命令：

```bash
paper-search setup                    # 逐项填写常用的几项
paper-search setup EASYSCHOLAR_KEY    # 只填某一项
paper-search config list --pretty     # 查看已配置的项，key 脱敏显示
```

配置保存在 `~/.config/paper-search-cli/config.json`，只有你自己能读。下载文件夹、联系邮箱、代理和自动更新等其他设置，见 [使用说明 · 其他设置](docs/guide.zh.md#其他设置)。

## 更多文档

[使用说明](docs/guide.zh.md)：[命令示例](docs/guide.zh.md#命令示例)、[工作方式](docs/guide.zh.md#工作方式)、[检索来源](docs/guide.zh.md#检索来源)、[Agent Skill](docs/guide.zh.md#agent-skill)、[全部命令](docs/guide.zh.md#全部命令)、[排障](docs/guide.zh.md#排障)。也可以在终端运行 `paper-search tools --pretty` 查看全部工具和参数。

## 路线图

接下来计划做这几件事：

1. **进度胶囊优化**：提醒时机更准，学校登录页能自动放行时不提前打扰；减少 Windows 上浏览器启动、换页时短暂跳到前台的情况，优化显示效果。
2. **并行下载**：不同出版社之间并行下载，同时处理多篇，缩短几十上百篇的总耗时；每家出版社仍遵守下载上限。
3. **Markdown 全文包**：除了 PDF，再交付原始 XML/HTML、Markdown 阅读副本和正文图片，图号、图注和正文引用一一对应，方便直接交给 AI 阅读和引用。
4. **更多学校访问方式**：除了中国的 CARSI，支持其他国家的学术身份联盟（如美国 InCommon、英国 UK federation）；有条件的话再接入 WebVPN、EZProxy 等访问方式。
5. **检索论文、搜正文片段再优化**：参考同类工具的做法，进一步提升检索论文和搜正文片段的效果。

完整计划见 [路线图](docs/ROADMAP.zh.md)，原理和代码结构见 [架构说明](docs/ARCHITECTURE.zh.md)。还想要什么功能，欢迎提 [Issue](https://github.com/dr-dumpling/PaperSearch/issues/new/choose) 和 PR；下载失败或想支持某家出版社，请用对应的 Issue 模板，想自己加出版社规则见 [carsi/CONTRIBUTING.md](carsi/CONTRIBUTING.md)。

## 致谢

- 感谢 LinuxDo 社区：命令 + Skill 的路线和工作流改进来自社区交流与开源分享。
- [openags/paper-search-mcp](https://github.com/openags/paper-search-mcp)：本项目参考了它的思路，并改成独立的命令行工具。
- [Dianel555/paper-search-mcp-nodejs](https://github.com/Dianel555/paper-search-mcp-nodejs)（MIT）：命令行版最初由它的 Node.js 实现改编而来。
- [Rimagination/scansci-pdf](https://github.com/Rimagination/scansci-pdf)（MIT）：机构下载后端（`carsi/`）借鉴了它的架构（CARSI 等联盟登录、出版社网站抓取、会话复用、PDF 捕获）。

## License

MIT

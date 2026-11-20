# download：下载论文

一篇或一批论文的三样内容都在这里下载：**PDF**、**补充材料**、**Markdown**。分三层：

- **入口**（这一层的几个文件）：下载命令、参数、结果的格式，以及下到的文件叫什么、放在哪。
- **`content/`：三样内容各自怎么拿**，对应下载参数 `content` 的三个值 `pdf`、`supplements`、`markdown`。
- **`batch/`：多篇一起下的调度**，它按每篇要的内容去调用 `content/` 里的三样。

学校订阅下载后端的客户端不在这里，在 `src/infrastructure/school/`：下载、设置窗口、学校登录、自动更新、导出失败报告都经它和后端打交道（其他代码只经它的 `index.ts` 用）。

```
download/
├── handler.ts、tools.ts、schemas.ts、types.ts、index.ts   下载命令的入口、参数和结果的格式
├── outputLayout.ts                文件叫什么、放在哪（三样共用）
├── content/                       三样内容各自怎么拿
│   ├── pdf/                       PDF
│   │   ├── OpenAccessFallbackService.ts   一篇的 PDF 按顺序试各个来源（漏斗）
│   │   ├── DownloadTier.ts                每个来源的接口
│   │   ├── open/                          开放来源：tiers/（Unpaywall、预印本、仓储、出版社 API、直链、Sci-Hub），
│   │   │                                  publisherApi/（Elsevier、Springer 的 API），pmcCloud.ts，oaHosts.ts
│   │   ├── school.ts                      经学校订阅下载拿 PDF（交给后端）
│   │   ├── identity.ts                    核对下到的 PDF 是不是这一篇
│   │   └── arxiv.ts                       arXiv 编号先换成正式发表的 DOI
│   ├── supplements/               补充材料
│   │   ├── fetch.ts                       向后端要补充材料、放进论文的文件夹、批量中补补充材料、断网后重补
│   │   └── shortfall.ts                   缺了哪些、为什么
│   └── markdown/                  Markdown：这里只管放在哪、什么时候取，转换由 PaperSearch Pro 完成（不在开源仓库）
│       ├── step.ts                        在下载流程里取 Markdown：交给 Pro，安排文件夹和运行记录
│       ├── pro.ts                         加载 Pro（PaperSearch 数据目录下的 pro/，或 PAPER_SEARCH_PRO_PATH）和与它的接口；
│       │                                  没装 Pro 或 Pro 暂不可用时，Markdown 写明原因，PDF 和补充材料照常
│       ├── types.ts                       和 Pro 之间传递的请求、结果和全文包的文件夹名
│       ├── pageVisit.ts                   只为 Markdown 打开文章页（PDF 已从开放来源拿到时）
│       └── shortfall.ts                   没生成的原因
└── batch/                         多篇一起下的调度
    ├── batch.ts                       调度：开放来源和学校订阅下载两条线、暂停、接着下
    ├── resume.ts                      接着下：上一批缺什么
    ├── batchFolder.ts                 批量文件夹里的 _run/ 和清单
    ├── batchSummary.ts、batchPapers.ts   结束卡片和进度窗口上的论文清单
    └── networkLoss.ts                 断网时等网络
```

## 学校订阅下载后端那一半

在出版社网页上登录、找 PDF、找补充材料、存下网页，都由 Python 写的后端在浏览器里完成，代码在仓库的 `school/paper_search_school/`：

- 每家出版社的网页规则（PDF、补充材料在页面哪里、怎么登录）：`adapters/<出版社>/`，几家共用的网页系统在 `adapters/platforms/`。
- 补充材料的通用流程：`engine/supplements.py`、`engine/page_supplements.py`、`engine/supplement_transfer.py`。
- 给 Markdown 存网页：`engine/fulltext_page.py`（存下的网页交给 PaperSearch Pro 转换）。

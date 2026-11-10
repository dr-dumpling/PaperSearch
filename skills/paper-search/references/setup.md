# 配置：请开始配置

用户说“请开始配置”（或“配置 PaperSearch”“start setup”）时，按下面固定的流程做。一次只问一个问题，等用户回答了再往下走；不要把所有配置项一起列出来让用户填。

1. 运行 `paper-search doctor --format text`，先看清哪些已经配好；这一步不用问用户。找不到 `paper-search` 命令时，先按 `management-layer.md` 的“只装了 Skill 时”征得同意装好，再运行它。
2. 只问一个问题：要不要用学校订阅下载（机构配置）。问的时候说明它用学校账号下载非 OA 文章的全文和补充材料，需要 Google Chrome（没有时一起装），下载约 0.5 GB。以下情况不问：已经装好（`doctor` 的 `entitled_access` 是 `available`）直接走 A；这台机器没有图形界面，或用户说过不要（`PAPER_SEARCH_CARSI_DECLINED` 为 `true`），直接走 B。用户说不要时运行 `paper-search config set PAPER_SEARCH_CARSI_DECLINED true` 记下来，再走 B。

A. 机构配置（用户同意用学校订阅下载）

1. 没装时安装（见 `carsi-setup.md`）：`paper-search carsi install --yes --skip-school`，没有 Chrome 时先装 Chrome。
2. 直接问用户的学校并设好：运行 `paper-search-carsi setup --carsi --institution "学校名"`（见 `carsi-setup.md` 的“学校”一节）。只有用户主动说跳过时才跳过，那样第一次下载时在选校页选。
3. 其余配置都在设置窗口里做：装完设置窗口会自己打开；没打开或早已装好时，直接运行 `paper-search settings` 打开设置窗口。告诉用户在窗口里填要用的 API key、改下载文件夹和等待时间，每个 key 可以点“测试”，填完点右上角 × 关闭。推荐先填 EasyScholar（影响因子和分区）和 Semantic Scholar（正文片段），其余 key 非必须。不在对话里逐项问 key 或下载文件夹。
4. 用户说填好了，运行 `paper-search doctor --format text`，告诉用户现在能用哪些功能。

B. 不用机构配置

1. 只推荐两个 key：`EASYSCHOLAR_KEY`（影响因子和分区）、`SEMANTIC_SCHOLAR_API_KEY`（正文片段），给出申请入口（`doctor` 的 To enable 一行）；其余 key 都非必须，用户问起再说。用户说都不需要就跳到第 4 步。
2. 请用户在自己的终端运行 `paper-search setup --skip-carsi` 填 key（输入时不显示），填完告诉你。
3. 用户说填好了，对填了的每个 key 运行 `paper-search config test <KEY>` 确认能用。
4. 设好默认下载文件夹（见下面“默认下载文件夹”）。
5. 运行 `paper-search doctor --format text`，告诉用户现在能用哪些功能。

不在“请开始配置”里时：用户第一次要下订阅文章、学校订阅下载还没装、用户没说过不要、这台机器有图形界面，也问一次要不要装（说明同第 2 步），同意后按 A 的 1–3 做。用户只问某个功能缺什么时，只提这个功能要的 key 和申请入口，填法按 A 的第 3 步（设置窗口）或 B 的第 2 步（终端）。

## 默认下载文件夹

配置时，或第一次要下载而还没设过时，先看有没有设好：

```bash
paper-search config get DEFAULT_DOWNLOAD_PATH
```

没有设置（返回的 `configured` 为 `false`）时问用户：“下载的论文默认放到哪个文件夹？”用户给出位置后保存为完整路径（`~` 表示用户目录）：

```bash
paper-search config set DEFAULT_DOWNLOAD_PATH "~/Documents/Papers"
```

之后下载不传 `savePath` / `--save-path`，文件自动存到这个文件夹；只有用户这一次指定了别的位置才传。没有设置时，文件会存到命令当前所在目录下的 `./downloads`，位置不固定，用户很难找到。用户也可以在进度胶囊的设置里改这个文件夹。

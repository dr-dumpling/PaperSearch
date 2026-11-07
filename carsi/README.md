# paper-search-carsi

PaperSearch 的机构授权下载后端，负责 CARSI 等联盟登录、出版社页面交互、会话复用、正文 PDF 与补充材料获取。公开来源、检索和批量编排由 PaperSearch CLI 负责。WebVPN、EZProxy（经学校的网关或代理用学校 IP）也不在这里：代码暂存在仓库根目录 `campus-proxy/`，未接入。

状态：**MCP server、编排和 CLI 已接通，PaperSearch `doctor` 握手通过；真实机构下载尚待逐出版社验收。**

## 安装与浏览器后端

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[ego,dev]"   # 含驱动 Patchright；浏览器用本机的 Google Chrome，不另下载
```

`bin/paper-search-carsi` 优先使用仓库内的 `.venv`（可用 `CARSI_PYTHON` 指定其他解释器）。

浏览器后端二选一，配置键 `browser_backend`：

- `chrome`（默认）：本机安装的 Google Chrome，由 Patchright 启动，全部浏览器路线都用它。用自己的浏览器资料（原目录旁的 `-chrome` 兄弟目录），不碰日常 Chrome 的资料；首次使用需要登录一次机构。没装 Chrome 时从 https://www.google.com/chrome/ 安装；装在别处时用 `chrome_executable` 指定程序路径。`setup --check` 显示 Chrome 的路径、版本和驱动版本，低于测试过的版本（156.0.8078.80）时提示先更新。
- `ego`（需要 agent 接手你正在用的浏览器时选用）：直接使用你日常运行的 ego-lite（Chromium 内核），Patchright 经 CDP 接管，沿用其中已有的登录；规则与适配器和 chrome 同一套。在 ego 里打开 `chrome://inspect/#remote-debugging` 勾选 "Allow remote debugging for this browser instance"，勾选一次即保存在 ego 设置中，重启后仍有效；程序只操作并关闭自己开的标签页，不关闭浏览器，也不写入 Cookie。ego 的数据目录可用 `ego_user_data_dir` 指定；未安装 ego-lite 时自动回到 chrome。

旧值 `camoufox`、`patchright`、`cloakbrowser` 会记一条警告并按 `chrome` 处理。

## 使用

遇到 Cloudflare/Turnstile 验证框时，程序先等待网站自动检查，再自动定位并点击复选框，网站放行后继续下载。每次验证等待最多尝试 3 次，两次至少间隔 3 秒，复用当前浏览器和原等待时限；自动阶段结束后仍未放行时提示人工接管。学校登录及二次验证由本人在浏览器完成；学校认证页的信息发送同意和使用条款、出版社登录途中的条款确认页由程序代点同意，每篇各最多两次。浏览器兼容设置随学校订阅下载一起安装，在新电脑上同样生效。

等待用户操作：停在学校登录页（以及没配置学校时的选校页）每篇最多 3 分钟（配置键 `browser_login_timeout`，秒，默认 180）；停在其他页面（人机验证、出版社页面、选机构页、取 PDF 时等待处理）连续超过 1 分钟就结束这一篇（`browser_page_wait_timeout`，默认 60）。两项和每家出版社每小时最多下载篇数都能在进度窗口右上角的设置（齿轮）里改。浏览器某一步 90 秒没有响应时，这一篇以 `browser_unresponsive` 结束。进度窗口的按钮：跳过本篇、本刊无权限、出版社无权限、终止任务（整批停下，剩余篇目记为 `batch_stopped`）、⚑ 报告问题。

浏览器调用超过 4 分钟没有返回时，后端会取消它并把这一篇记为 `browser_unresponsive`（日志里记下是哪个调用、从哪里调用），批量继续下一篇。后端一直停着不动（CPU 为 0、进度不再更新）时，`kill -USR1 <后端进程号>` 会把它所有线程的 Python 调用栈追加到 `<数据目录>/logs/stacks-<日期>.txt`，用来看它在等哪个浏览器调用；进程不会因此退出。

```bash
# 1. 选择机构入口：用 --institution 配置自己的学校（CARSI 成员学校的中文名、英文名或域名，在 CARSI 学校列表里查找后保存中英文名和 entityID），之后各出版社的选校页由程序自动选中（只点与它对应的那一项）；不配置则在登录窗口里手选
paper-search-carsi setup --carsi            # 或 --carsi --institution "学校名"
paper-search-carsi setup --list-carsi-schools 关键词   # 查 CARSI 成员学校
paper-search-carsi setup --check            # 环境检查：数据目录、浏览器（Chrome 路径和版本）、入口是否配置

# 2. 在弹出的浏览器窗口完成一次机构登录（凭证只在窗口里输入，CLI 不经手）
paper-search-carsi login --doi 10.1016/...           # 打开这篇文章的出版社页面，在出版社的机构登录里选学校（CARSI）
paper-search-carsi login --publisher elsevier        # 没有 DOI 时打开出版社首页

# 3. 让 PaperSearch 用它（专属数据目录与上面保持一致）
paper-search config set PAPER_SEARCH_CARSI_EXECUTABLE /path/to/paper-search-carsi
paper-search config set PAPER_SEARCH_CARSI_ENABLED true
paper-search doctor --pretty

# 另一个终端里查看当前任务进度（只读）
paper-search-carsi progress --json --watch

# 贡献者自检：跑一篇受限 DOI 并输出脱敏报告
paper-search-carsi publisher-check --doi 10.1016/...
```

`CARSI_DATA_DIR` 决定数据目录；PaperSearch 默认用 `$XDG_DATA_HOME/paper-search-cli/carsi`，运行上面的 setup/login 时要导出同一个值。

## 三级结构

目录保留两层外壳：`carsi/` 是后端构建根（安装声明、测试和工具），`paper_search_carsi/` 是可导入、可安装的 Python 包。出版社各自保留独立文件夹，便于增加网站类型和专有规则；不因暂时只有一个 `__init__.py` 就改成单文件。目录是否精简按实际职责和明确扩展用途判断，核对记录见 `目录层级核对`。

```text
paper_search_carsi/
├── publishers/      tier 1  声明式出版社规则：builtin/*.json + schema.json + 用户 publisher_profiles_file
├── adapters/        tier 2  出版社适配器（Python）：一家一个目录，只写通用流程判断不了的钩子；platforms/ 是网站平台的共同规则（Atypon、Silverchair），出版社继承它；base.py 是基类与默认值
├── engine/          tier 3  机构入口：bridge（调度）/ batch（出版社浏览器抓取，含 CARSI 选校）/ router
├── browser/                 浏览器引擎、后端选择、登录等待、Cookie、预览
├── extractors/              PDF 响应提取
├── server.py                MCP stdio：download / cache_clear / list_publishers
└── cli.py                   setup / login / publisher-check
```

谁可以贡献什么：

| 层 | 需要会什么 | 合并条件 |
| --- | --- | --- |
| tier 1 `publishers/builtin/<name>.json` | 不需要写代码 | 通过 `schema.json` 校验；附脱敏页面快照到 `tests/fixtures/publishers/<name>/` |
| tier 2 `adapters/<name>/` | Python，`PublisherAdapter` 子类 | 离线夹具测试；`publisher-check` 报告贴在 PR |
| tier 3 `engine/` | 熟悉学校认证流程 | 维护者审核 |

详见 CONTRIBUTING.md。后端在契约之外的行为（浏览器预览、出版社规则扩展文件）见仓库的 `docs/dependencies/carsi-backend-notes.zh.md`。当前模块职责见同一后端说明中的“浏览器内部模块边界”。

PaperSearch 调用后端时可以传入独立的 `diagnostics_dir`：浏览器记录、截图和附件清单放在该目录；正文及 `supplements/` 附件仍写入 `output_dir`。期刊、年份、标题命名由 CLI 的统一输出模块完成。

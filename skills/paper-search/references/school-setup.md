# 机构下载：安装扩展、配置学校、选择浏览器

学校订阅下载（经学校所属的学术身份联盟或 OpenAthens 登录）让 PaperSearch 用用户学校的权限，在浏览器里下载需要订阅的论文。在有图形界面的电脑上，用户同意后才装：用户说“请开始配置”或第一次要下订阅文章时问一次；用户说过不要（`PAPER_SEARCH_SCHOOL_DECLINED=true`）或没有图形界面的服务器上不装、不问。检索和开放下载不需要它。

## 查看与安装

```bash
paper-search school status --format text
```

显示是否已装、安装目录、所用浏览器（Google Chrome 的路径和版本、驱动版本）、学校、PaperSearch 是否已启用它。Chrome 低于测试过的版本时会提示先更新 Chrome。

用户同意后运行（Agent 代装时加 `--yes --skip-school`）：

```bash
paper-search school install
```

- 需要图形界面：学校登录要在看得见的浏览器里完成。没有图形界面的 Linux（服务器，没有 `DISPLAY` 或 `WAYLAND_DISPLAY`）上安装会在第一步停下，`paper-search setup` 也不再问是否安装；这类机器用 `paper-search setup <KEY>` 配 key，检索和开放获取下载照常可用。
- 需要本机已装 Google Chrome；没有时安装会停下。这时告诉用户要先装 Chrome，用户同意后替用户装：macOS 有 Homebrew 时运行 `brew install --cask google-chrome`，Windows 运行 `winget install -e --id Google.Chrome`；装好后再运行同一条 `school install`。没有 Homebrew 或 winget、或安装失败时，请用户从 https://www.google.com/chrome/ 下载安装。`--browser ego` 改用用户自己的 ego lite（仅 macOS）。
- 安装前会列出安装位置和下载量（约 0.5 GB，不另下载浏览器），用户确认后才开始。`--yes` 跳过确认，只在用户已经同意后使用。
- 用户不需要先装 Python；中途失败时，处理提示的问题后再运行同一命令，会从失败的那一步接着装。
- 装完会打开设置窗口的 API key 页，用户填好或不需要时点右上角 × 关闭。
- 装完会自动启用（`PAPER_SEARCH_SCHOOL_ENABLED=true`、`PAPER_SEARCH_SCHOOL_EXECUTABLE` 指向新装的后端）。原来配置了别的后端时，会先问用户是否替换。
- 安装时会问学校；`--skip-school` 跳过，之后再配置。
- 首次配置扩展时会询问是否开启系统通知。新配置默认关闭，回车保留当前选择；`--yes` 不代表同意开启通知。Agent 代为配置时先问用户要开启还是关闭，再通过同一后端的 `config set progress_notify true` 或 `false` 保存，已有明确选择不重复询问。以后可在胶囊齿轮 → 等待和提醒里点“系统通知”开关立即修改；关闭不影响琥珀色呼吸和点击唤回浏览器。
- 进度窗口的设置（下载文件夹、等待和提醒、API key）：点胶囊齿轮，或运行 `paper-search settings [download|wait|keys|<KEY>]`。没有下载时它单独打开窗口，关掉设置窗口就消失。
- `paper-search setup` 最后也会问是否安装扩展；`--skip-school` 不问，`--install-school` 直接安装。

用户自己维护的后端（例如仓库里的开发版）用 `paper-search config set PAPER_SEARCH_SCHOOL_EXECUTABLE <路径>` 指定；不要擅自改用户已配置的路径。

## 先登录学校（可选）

```bash
paper-search school login --doi <学校订阅的一篇文章的 DOI>
```

- 用在用户想在批量下载前先登录、或想试试登录是否正常时；平时不需要，下载遇到登录会自己停下等用户。
- 它打开下载用的浏览器，自动过网站验证、选学校，停在学校登录页等用户登录（最多等 `browser_login_timeout` 秒，`--max-wait <秒>` 只改这一次）；登录后核对这篇文章能看全文，不下载 PDF，登录状态留给之后的下载。
- 只有 `success: true`（`state: signed_in`）才算登录成功。`access_without_login`：这篇不用登录就能看（开放获取或校园网），换一篇需要订阅的文章再试；`login_timeout`、`browser_closed`、`institution_pdf_entitlement_missing` 等按回复里的 `message` 告诉用户。
- 下载浏览器和它的资料目录由程序管理，登录用这条命令或直接下载；不要翻源码另找登录办法。没装学校订阅下载或没配置学校时，按回复里的提示处理。

## 更新与卸载

- PaperSearch 升级后，第一次用到学校订阅下载时会自动做同样的更新（stderr 一行说明）；用户关掉了自动更新（`PAPER_SEARCH_SCHOOL_AUTO_UPDATE=false`）或自动更新没成功时，`status` 提示扩展落后，运行 `paper-search school update`：重装后端和依赖，检查 Chrome；学校配置、登录会话、Chrome 和 ego lite 不动。以前用 Camoufox 的安装会改用 Chrome，并写明旧 Camoufox 浏览器所在的目录，由用户决定是否手动删除。已是最新时不做任何事；`--force` 强制重装。
- 卸载：`paper-search school uninstall`。先列出要删和保留的内容，用户确认后删除安装目录；PaperSearch 配置指向这次安装的后端时，关闭机构下载并清除后端路径，指向别处时不改。学校配置和登录会话默认保留，会询问；`--yes` 时保留，除非另加 `--remove-data`。Google Chrome 和 ego lite 不受影响。

## 学校

用户的学校写在后端配置里，由用户提供，不预设、不替换。用户只需说出学校名，所属联盟由后端判断，不要问用户是哪个联盟：

```bash
paper-search-school setup --institution "用户说的校名" [--also-name "学校的英文正式名称"]
```

- 目前支持中国内地和澳门（CARSI）、香港（HKAF）、新加坡（SGAF）、日本（GakuNin）、韩国（KAFE）、马来西亚（SIFULAN）、印度（INFED）、土耳其（YETKİM）、斯里兰卡（LIAF）、孟加拉（TIGERfed）、巴基斯坦（PKIFED）、阿曼（OMREN）、中国内地科研机构（CSTCloud）、沙特阿拉伯（Maeen）、塞浦路斯（CyNet）、以色列（IUCC）、伊朗（IRFED）、阿塞拜疆（AzScienceNet）、英国（UK federation）、爱尔兰（Edugate）、法国（RENATER）、荷兰（SURFconext）、比利时（Belnet）、卢森堡（eduID Luxembourg）、北欧、中欧、南欧和东欧各国，以及美洲、大洋洲和非洲各国（各联盟见 `federation-support.md`）的学术身份联盟，以及只经 OpenAthens 登录的学校。`--institution` 可以是校名（任何语言）、学校域名或 entityID；后端在各联盟的学校名单里查，确定是哪一所才保存，并保存它所属的联盟。
- 联盟名单里的校名是当地语言和英文（中国内地、澳门有中文，日本有日文，土耳其有土耳其文，欧洲和拉丁美洲各国多有当地语言名，香港、韩国、新加坡、马来西亚、南亚、北美洲、大洋洲和非洲多只有英文）。用户说的校名不是英文时，加 `--also-name` 给出学校的英文正式名称（出版社多按英文名列学校）；不确定英文名就不加。
- 有些学校经多校共用的登录入口登录（如以色列、挪威、克罗地亚的大学，中国内地的科研院所，巴基斯坦、拉脱维亚的部分学校），联盟名单里只有它们的域名：按校名查不到时，用 `--institution <校名> --also-name <学校官网域名>` 再查一次，程序会按域名找到入口，并按所给校名在出版社搜索。
- 返回 `school_ambiguous` 时，把 `candidates`（含学校名、联盟、域名）列给用户选，再用所选学校的 `entity_id` 作为 `--institution` 重新运行；只有一个候选也要问，那是名字不完全一致的学校。`school_not_found` 时请用户换成学校正式名称、英文名或学校域名，仍找不到就按回复里的 `reasons` 如实说明：这所学校可能没有接入学术身份联盟或 OpenAthens，学校订阅下载无法为它登录；`federation_not_supported` 是找到了学校但它所属的联盟还不支持，如实告诉用户；`school_list_unavailable` 是名单取不到，稍后重试。需要请用户反馈时，见 `federation-support.md`“学校登录不上时”。
- `--carsi --institution` 只在 CARSI 名单里查（错误码 `carsi_school_*`）；查 CARSI 名单：`paper-search-school setup --list-carsi-schools 关键词`。
- `setup --check` 的 `school` 项为 `missing` 时，说明只存了学校名，按提示重新运行上面的命令。
- 配置后，选联盟、选学校、点继续由程序完成；用户只在学校登录页输入账号密码、完成人机验证。
- 没有配置学校时（`setup --carsi`），CARSI 照样开启，由用户在选校页自己选。
- 出版社列表里找不到用户的学校时，报告找不到，不改选别的学校。
- 后端命令要和下载使用同一个数据目录（PaperSearch 默认 `${XDG_DATA_HOME:-~/.local/share}/paper-search-cli/school`）；需要时在命令前加 `SCHOOL_DATA_DIR=<该目录>`。登录状态保存在这个目录的下载浏览器里。

## 浏览器

后端配置键 `browser_backend` 二选一：

- `chrome`（默认）：用户本机的 Google Chrome，由后端用单独的浏览器资料启动，不动用户日常 Chrome 的资料和标签页。第一次下载时用户在它的窗口里登录一次学校，之后保留。日常和批量下载用它。Chrome 装在别处时：`paper-search-school config set chrome_executable <Chrome 程序路径>`。旧值 `camoufox` 按 `chrome` 处理。
- `ego`：需要沿用用户 ego lite 里已有的登录时选用（Chromium 内核，用户和 agent 看的是同一个浏览器，仅 macOS）。用户须在 ego 打开 `chrome://inspect/#remote-debugging`，勾选一次 “Allow remote debugging for this browser instance”。每次连接（例如 ego 重启后）ego 会弹出一次“允许连接”，由用户确认；ego 窗口在后台时常被直接拒绝，下载会立即报错并写明原因，请用户把 ego 放到前台、点“允许”后重试。

查看或切换：

```bash
paper-search-school config get browser_backend
paper-search-school config set browser_backend chrome
```

两套浏览器资料互不影响，切换不会删除另一套。用户没有要求时不擅自切换；也可以用 `paper-search school install --browser ego` 切换安装。

## 边界

- 账号、密码、验证码只由用户在浏览器里输入；不在聊天、命令参数、配置或日志里出现。
- `doctor` 显示 `entitled_access` 为 `available`，只说明后端能连上，不代表已登录或对某篇有权限。

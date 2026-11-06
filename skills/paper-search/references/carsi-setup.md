# 机构下载：安装扩展、配置学校、选择浏览器

机构下载扩展让 PaperSearch 用用户学校的权限，在浏览器里下载需要订阅的论文。它默认没有安装、没有启用：PaperSearch 默认是开放版本，检索和开放下载不需要它；用户需要下载学校订阅的文章或补充材料时才安装。

## 查看与安装

```bash
paper-search carsi status --format text
```

显示是否已装、安装目录、所用浏览器及版本、学校、PaperSearch 是否已启用它。

没有安装、而用户需要用学校权限下载时，先征得用户同意，再运行：

```bash
paper-search carsi install
```

- 安装前会列出安装位置和下载量（默认约 3 GB；`--browser ego` 只用用户自己的 ego lite，约 0.5 GB，仅 macOS），用户确认后才开始。`--yes` 跳过确认，只在用户明确同意后使用。
- 用户不需要先装 Python；中途失败时，处理提示的问题后再运行同一命令，会从失败的那一步接着装。
- 装完会自动启用（`PAPER_SEARCH_CARSI_ENABLED=true`、`PAPER_SEARCH_CARSI_EXECUTABLE` 指向新装的后端）。原来配置了别的后端时，会先问用户是否替换。
- 安装时会问学校；`--skip-school` 跳过，之后再配置。
- 首次配置扩展时会询问是否开启系统通知。新配置默认关闭，回车保留当前选择；`--yes` 不代表同意开启通知。Agent 代为配置时先问用户要开启还是关闭，再通过同一后端的 `config set progress_notify true` 或 `false` 保存，已有明确选择不重复询问。以后可点胶囊齿轮里的“系统通知”开关立即修改；关闭不影响琥珀色呼吸和点击唤回浏览器。
- `paper-search setup` 最后也会问是否安装扩展；`--skip-carsi` 不问，`--install-carsi` 直接安装。

用户自己维护的后端（例如仓库里的开发版）用 `paper-search config set PAPER_SEARCH_CARSI_EXECUTABLE <路径>` 指定；不要擅自改用户已配置的路径。

## 更新与卸载

- PaperSearch 升级后，`status` 提示扩展落后时运行 `paper-search carsi update`：重装后端和依赖，锁定的浏览器版本变了才下载新版；学校配置、登录会话和 ego lite 不动。已是最新时不做任何事；`--force` 强制重装。
- 卸载：`paper-search carsi uninstall`。先列出要删和保留的内容，用户确认后删除安装目录；PaperSearch 配置指向这次安装的后端时，关闭机构下载并清除后端路径，指向别处时不改。Camoufox 浏览器（本机其他程序可能也在用）和学校配置、登录会话默认保留，会分别询问；`--yes` 时都保留，除非另加 `--remove-browser`、`--remove-data`。ego lite 不受影响。

## 学校

用户的学校写在后端配置里，由用户提供，不预设、不替换：

```bash
paper-search-carsi setup --carsi --institution "学校名"
```

- `--institution` 可以是 CARSI 成员学校的中文名、英文名、拼音、域名或 entityID。后端在 CARSI 学校列表里找到唯一一所才保存（中文名、英文名、entityID 都用列表原文）。
- 返回 `carsi_school_ambiguous` 时，把 `candidates` 列给用户选，再用所选学校的 `entity_id` 重新运行；`carsi_school_not_found` 时请用户换个写法；`carsi_school_list_unavailable` 是取不到列表，稍后重试。
- 查列表：`paper-search-carsi setup --list-carsi-schools 关键词`。
- `setup --check` 的 `carsi_school` 项为 `missing` 时，说明只存了学校名，按提示重新运行上面的命令。
- 配置后，选联盟、选学校、点继续由程序完成；用户只在学校登录页输入账号密码、完成人机验证。
- 没有配置学校时，CARSI 照样开启，由用户在选校页自己选。
- 出版社列表里找不到用户的学校时，报告找不到，不改选别的学校。
- 后端命令要和下载使用同一个数据目录（PaperSearch 默认 `${XDG_DATA_HOME:-~/.local/share}/paper-search-cli/carsi`）；需要时在命令前加 `CARSI_DATA_DIR=<该目录>`。不要复制其他浏览器的会话。

## 浏览器

后端配置键 `browser_backend` 二选一：

- `camoufox`（默认）：后端自己启动的独立浏览器（Firefox 内核），有单独的浏览器资料，不占用用户日常浏览器。第一次下载时用户在它的窗口里登录一次学校，之后保留。日常和批量下载用它。
- `ego`：需要沿用用户 ego lite 里已有的登录时选用（Chromium 内核，用户和 agent 看的是同一个浏览器，仅 macOS）。用户须在 ego 打开 `chrome://inspect/#remote-debugging`，勾选一次 “Allow remote debugging for this browser instance”。每次连接（例如 ego 重启后）ego 会弹出一次“允许连接”，由用户确认；ego 窗口在后台时常被直接拒绝，下载会立即报错并写明原因，请用户把 ego 放到前台、点“允许”后重试。

查看或切换：

```bash
paper-search-carsi config get browser_backend
paper-search-carsi config set browser_backend camoufox
```

两套浏览器资料互不影响，切换不会删除另一套。用户没有要求时不擅自切换；也可以用 `paper-search carsi install --browser ego` 切换安装。

## 边界

- 账号、密码、验证码只由用户在浏览器里输入；不在聊天、命令参数、配置或日志里出现。
- `doctor` 显示 `entitled_access` 为 `available`，只说明后端能连上，不代表已登录或对某篇有权限。
- 不要把维护者的后端路径、学校配置、浏览器资料或下载诊断写进 Skill、README，或打包发布。

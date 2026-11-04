# 机构下载：用学校权限下载 PDF

机构下载是可选扩展，默认没有安装；只用开放下载时不需要读这一篇。本篇适用于目标论文已确认、需要学校订阅，或用户报告登录后没反应、不断跳转、PDF 已打开却没保存。安装、学校、浏览器的设置见 `carsi-setup.md`。

## 调用前

- 核验目标 DOI 和标题；不要用虚构 DOI 做下载探测。
- 目标出版社能不能走通、能不能取补充材料，先看 `publisher-support.md`；表里没有的网站按通用规则尝试。
- 用户没说要不要补充材料时，开始前问一次：只要正文（`main`）、正文加补充材料（`both`）、只要补充材料（`supplements`）；批量也只问一次。
- `paper-search carsi status --format text` 确认扩展已安装并启用，或“PaperSearch 配置”一行已启用并给出后端路径（用户自己维护的后端，第一行显示“未安装”是正常的）；都没有时按 `carsi-setup.md` 处理。本文的 `paper-search-carsi` 命令不在 PATH 上时，用这里“后端”后面的完整路径调用。
- 开始前运行 `paper-search-carsi issues`，看有没有之前没处理的问题报告；看完用 `issues resolve <ID> --note "结论"` 记下结论。

## 一次调用，等待明确结果

单篇用 `paper-search download` 或 `paper-search run download_with_fallback`，多篇用一次 `paper-search run download_batch`，参数见 `cli-contract.md`。下载顺序固定为 `primary → direct_pdf_url → repositories → unpaywall → publisher_api → scihub → entitled_access → preprint`。机构下载失败后才尝试 DOI 明确关联的 arXiv 预印本。

- 只用开放来源和学校权限（不用 Sci-Hub）：`download_with_fallback` / `download_batch` 设 `useSciHub=false`。只有明确只测学校权限这一步时，`download_batch` 才设 `"mode":"entitled_only"`；它会跳过可用的公开副本，普通下载保留默认 `two_phase`。
- 同一个数据目录同时只跑一个下载。命令没结束时，不因窗口看似停住而重新下载或登录。
- 批量按顺序逐篇进行。遇到学校登录或验证时停在这一篇；出现人工处理提示后，提醒用户到下载浏览器操作。等待时限：停在学校登录页（以及没配置学校、要用户自己选学校的页面）最多 3 分钟（后端配置 `browser_login_timeout`，秒）；停在其他页面（人机验证、出版社页面、选机构页、取 PDF 时等待处理）连续超过 1 分钟就结束这一篇（`browser_page_wait_timeout`）。两项都能在进度窗口右上角的设置（齿轮）里改，从下一篇起生效。学校统一认证登录一次后，其余篇目通常自动通过。一篇等满时限后（日志写“这一篇等你登录或验证已到时限”），后面每篇只等 60 秒；用户在登录框输入时照常等。
- 每个出版社每小时最多打开 100 篇（后端配置 `publisher_hourly_limit`，0 为不限）。到上限时批量等到可以继续再下这一篇（日志写明时间）；单篇返回 `rate_limited`，稍后再试。
- 出版社网站拦截了当前网络（`access_blocked`，如 Cloudflare 拦截页）时这一篇结束；同一期刊 30 分钟内的其他文章直接跳过（`journal_blocked_earlier`），其他期刊照常继续。告诉用户可能是当前网络被网站防护拦截，也可能是下载过多被暂停：可换网络或稍后再试，后者请联系学校图书馆。
- 后端会先短暂等待自动验证，每次验证等待对可识别的 Turnstile 复选框最多尝试点击 3 次，两次至少间隔 3 秒；程序提示人工处理时，再提醒用户到下载浏览器接管，不因 `checking_access` 就要求用户操作。学校登录、二次验证和复杂验证码由用户完成；不索取账号、密码或验证码，agent 不另开浏览器代操作。
- 阶段以本次调用的结构化通知为准（命令写在 stderr，stdout 只有最终 JSON）；不凭等待时间猜阶段。
- PDF 在新标签页打开不等于已保存；以命令的最终结果为准，网页地址不是本地文件。
- 需要取消时中止当前调用；旧浏览器仍占用数据目录时不启动下一次下载，不自动删除占用锁。

## 进度窗口和问题报告

- 进度窗口是屏幕角落的小胶囊（macOS 右上、Windows 右下）：显示完成数/总数、正在下正文还是附录、出版社；需要用户登录或验证时变成琥珀色并显示倒计时，同时发一条系统通知。鼠标指上去展开，看当前论文、步骤、成功/失败/剩余和下面的按钮；右上角“–”最小化到程序坞或任务栏。全部成功时结束 8 秒后自动关，有失败或终止时留着，等用户点 × 关闭。pywebview 或网页引擎用不了时自动换成旧版窗口，按钮相同。
- 默认 Camoufox 下载浏览器保持运行，但启动、跳转及等待人工处理时不主动抢前台。需要操作时看胶囊提示，再自行切换到下载浏览器；胶囊首次显示也不占用键盘焦点。
- 胶囊齿轮可修改默认下载文件夹（输入绝对路径或选择文件夹），与 `paper-search config set DEFAULT_DOWNLOAD_PATH "/完整路径/论文"` 共用配置。新任务自动采用它；显式 `savePath` / `--save-path` 优先，运行中批次不改目录。
- “终止”（旧版窗口里叫“终止任务”）：确认后当前这一篇立即结束，整批停下，剩下的篇目记为 `batch_stopped`（未下载）。用户想停下整批时让他点这个，不要另外中止命令。
- 当前源码（未发布修复）：`browser_operation_timeout` 表示自动页面操作耗尽共享预算，不是无权限，也不是等待用户登录。不要因此反复登录；先检查是否误用了 `entitled_only`。附件阶段终止同样停止后续篇目，保留已保存的正文。
- 展开后写明正在下哪部分和哪一步：正文有五段步骤条（打开文章、权限、取 PDF、核对、附录），附录显示“附录 2/5”。
- 右上角齿轮（设置）：手动输入学校登录页、其他页面的最长等待（秒）和每家出版社每小时最多下载篇数，保存后从下一篇起生效；还可以关掉需要处理时的系统通知。
- “跳过”：只结束当前这一篇。“⋯”里的“本刊无权限”“出版社无权限”：结束这一篇并记住，以后自动跳过；查看或撤销用 `paper-search-carsi entitlements`（`list` / `clear <key>`）。点击后 1–2 秒内生效。
- “⋯”里的“报告问题”：用户选择看到的问题后，后端截下页面并处理（读取已打开的 PDF、回到文章、刷新、停止自动选校），窗口显示处理结果。
- 发起机构下载时同时监听用户的报告（与下载相同的 `CARSI_DATA_DIR`）：
  - 能后台运行命令并在结束时收到通知：后台运行 `paper-search-carsi issues watch --since <开始下载的时间戳>`，用户报告后它返回报告 JSON（网址、标题、正文片段、截图路径、处理结果）并退出。
  - 只能逐条执行命令：下载期间定时运行 `paper-search-carsi issues watch --since <时间戳> --timeout 30`；没有新报告时返回 `{"timeout": true}`（退出码 3）。
  - 收到报告立即看截图（不能读图时看网址、标题、正文片段），告诉用户页面停在哪里、是什么问题、现在可以怎么做。继续监听时把返回的 `reported_ts` 作为下一次的 `--since`。

## 实时状态和浏览器画面

读取与进度窗口相同的状态，不启动窗口、浏览器或新下载：

```bash
CARSI_DATA_DIR="<数据目录>" paper-search-carsi progress --json
CARSI_DATA_DIR="<数据目录>" paper-search-carsi progress --json --watch \
  --run-id "<本次 run_id>" --identifier "<目标 DOI>" --timeout 30
```

开始下载前读一次，记下旧 `run_id`；发起下载后确认 `identifier` 是目标 DOI 且 `run_id` 已变，再用 `--watch` 绑定本次任务。每次监控不超过 60 秒，原任务仍在运行就继续监控同一 `run_id`，不重新下载。长时间没有更新只表示暂无新进度，不推断没有权限。

| `stage`                                                | 行动                                                             |
| ------------------------------------------------------ | ---------------------------------------------------------------- |
| `waiting_login`                                        | 提醒用户在下载浏览器登录，继续监控。                             |
| `waiting_verification`                                 | 提醒用户完成人机验证，继续监控。                                 |
| `opening_article` / `checking_access` / `fetching_pdf` | 等待，不重复要求登录。                                           |
| `pdf_captured`                                         | 已读到 PDF，仍需等待保存。                                       |
| `saved_pending_verification`                           | 已保存，等原调用最终结果和身份核验。                             |
| `route_failed`                                         | 这条路失败，原任务可能继续；等最终结果，不重新发起下载。         |
| `failed` / `cancelled` / `interrupted` / `unknown`     | 核查原调用结果，不据此报告成功或没有权限。                       |

看下载浏览器的最新截图（只读）：

```bash
CARSI_DATA_DIR="<数据目录>" paper-search-carsi preview --run-id "<本次 run_id>" --doi "<目标 DOI>"
```

返回截图路径的 JSON。截图可能是几秒前的画面，判断当前状态以进度为准；选校、登录、验证仍在实际下载窗口完成。

## 结果和失败分类

读 `attempts[]` 里 `entitled_access` 的 `code` 和提示，不展示原始日志、带签名的下载地址或会话内容。批量或单篇结束后运行：

```bash
paper-search failures --format text
```

（默认最近一批；`--since YYYY-MM-DD`、`--runs N`、`--all`）。它把失败分成四类；向用户说明时按类别说：

| 类别 | 常见 code | 怎么说、怎么做 |
| --- | --- | --- |
| 没权限（有依据） | `entitlement_missing`、`institution_federation_unavailable`、`institution_not_registered`、`no_entitlement` | 附上汇总里的依据（页面原话或决定性的一步）。只说本篇、当前学校没有权限，不推断整个平台。出版社没有学校所在联盟的登录路线时，建议在校园网或学校 VPN 下下载。 |
| 用户或外部原因 | `login_timeout`（停在学校登录页）、`login_page_closed`、`login_credentials_rejected`、`captcha_required`、`idp_login_error`、`user_skipped`、`cancelled`、`access_blocked`、`cloudflare_blocked`、`publisher_content_error`、`rate_limited`、`batch_stopped`、`profile_busy` | 说明需要用户做什么（登录、验证、等待、联系图书馆），原调用结束、资源释放后再决定是否重试；不连续重新提交登录。 |
| 暂不支持的网站 | `unsupported_platform`（如只在 ClinicalKey 上的内容）、`unsupported_publisher`（DOI 没有指向能登录的出版社网站，没有打开浏览器）、`generic_institution_entry_missing`（这家出版社还没有专门的规则，按通用规则没找到机构登录入口） | 说明这类网站还不支持，不说成没有权限；后者可以建议用户把这篇报告给维护者补规则，或在校园网下下载。 |
| 原因不明（需排查） | `download_failed`、`download_timeout`、`login_not_reached`（程序没进入学校登录页）、`login_required`、`source_exception`、`browser_unresponsive`、`pdf_identity_unverified`、`pdf_identity_mismatch`、`pdf_wrong_article` 等 | 不说成没有权限；说明原因待查，给出汇总里的“停在哪一步”和诊断文件位置。 |

`pdf_identity_unverified` / `pdf_identity_mismatch`：不能报成功，`review.path` 只是待核查的文件。

## 补充材料

- `download_with_fallback` / `download_batch` 的 `content`：`main`（默认，只要正文）、`supplements`（只要补充材料，不走正文的各层）、`both`（正文和补充材料）。
- 补充材料只经机构下载扩展的浏览器取得：正文由开放渠道拿到时，`both` 会再请扩展单独取补充材料；扩展没装或没启用时，这一步记为 `skipped`，写明没有可用的后端。
- 哪些出版社有补充材料规则见 `publisher-support.md`。完成检查但页面未列出附件时返回空 `supplements`，attempt 为 `skipped/no_supplements`；只取补充材料时整体 `status=ok`，表示检查完成，不表示保存了文件。没有发现规则（`supplements_not_supported`）、登录未完成（`login_required`）与下载失败分别报告，只取补充材料时仍为 `error`，不影响已保存正文。
- 文件存在 `<savePath>/papers/<期刊_年份_标题_短标识>/supplements/`，诊断目录的 `manifest.json` 记录每个文件的状态（`saved`、`failed`、`skipped`）和原因；结果里的 `supplements` 给出实际文件路径。
- 上限：每篇最多 50 个文件，每个不超过 200 MB，一篇总共 3 分钟；超出的记 `skipped`（原因 `file_limit`、`too_large`、`time_budget`）。`html_page` 表示链接打开的是网页而不是文件，`http_403` 一类是网站拒绝。
- 只收本文的文件：别的文章的文件、本文的插图、参考文献里的链接都不收。Figshare 公开 article/collection 链接按原文 DOI 关联后解析文件；其他外部附件平台仍需适配。
- 补充材料、利益冲突声明里也可能印着目标标题和 DOI；不要把补充材料 PDF 当正文交付，正文成功也不代表补充材料齐全。
- 个别网站（目前 Taylor & Francis）拒绝程序直接下载补充材料时，改由浏览器自己下载，清单里写 `via: browser_download`；浏览器下载列表里会出现以一串编号命名、没有扩展名的记录，文件已按真实文件名保存在 `_supplements` 目录，这些记录可在浏览器下载页清除。

## 确认下载成功

以命令的最终成功、实际保存的文件和 PDF 首页的身份核验为准：首页 DOI 和题名对得上目标。参考文献里提到目标 DOI 不算；`review.path`、浏览器里显示 PDF、进程退出码为零都不能单独证明成功。浏览器下载列表里的随机文件名、无扩展名或失败记录来自临时下载，不能代替正式输出文件，也不能仅凭名称判断内容错误。交付时给出实际文件路径、目标 DOI 和本次结果。

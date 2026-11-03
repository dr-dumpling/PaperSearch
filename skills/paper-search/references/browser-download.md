# 机构下载：用学校权限下载 PDF

机构下载是可选扩展，默认没有安装；只用开放下载时不需要读这一篇。本篇适用于目标论文已确认、需要学校订阅，或用户报告登录后没反应、不断跳转、PDF 已打开却没保存。安装、学校、浏览器的设置见 `carsi-setup.md`。

## 调用前

- 核验目标 DOI 和标题；不要用虚构 DOI 做下载探测。
- 目标出版社能不能走通、能不能取补充材料，先看 `publisher-support.md`；表里没有的网站按通用规则尝试。
- 用户没说要不要补充材料时，开始前问一次：只要正文（`main`）、正文加补充材料（`both`）、只要补充材料（`supplements`）；批量也只问一次。
- `paper-search carsi status --format text` 确认扩展已安装并启用，或“PaperSearch 配置”一行已启用并给出后端路径（用户自己维护的后端，第一行显示“未安装”是正常的）；都没有时按 `carsi-setup.md` 处理。本文的 `paper-search-carsi` 命令不在 PATH 上时，用这里“后端”后面的完整路径调用。
- 开始前运行 `paper-search-carsi issues`，看有没有之前没处理的问题报告；看完用 `issues resolve <ID> --note "结论"` 记下结论。

## 一次调用，等待明确结果

单篇用 `paper-search download` 或 `paper-search run download_with_fallback`，多篇用一次 `paper-search run download_batch`，参数见 `cli-contract.md`。下载顺序固定为 `primary → direct_pdf_url → repositories → unpaywall → publisher_api → scihub → entitled_access`，机构下载在最后。

- 只用开放来源和学校权限（不用 Sci-Hub）：`download_with_fallback` / `download_batch` 设 `useSciHub=false`。只测学校权限这一步：`download_batch` 设 `"mode":"entitled_only"`。
- 同一个数据目录同时只跑一个下载。命令没结束时，不因窗口看似停住而重新下载或登录。
- 批量按顺序逐篇进行。遇到学校登录或人机验证时停在这一篇，提醒用户到下载浏览器操作；每篇最多等 3 分钟（后端配置 `browser_login_timeout`，秒）。学校统一认证登录一次后，其余篇目通常自动通过。一篇等满时限后（日志写“这一篇等你登录或验证已到时限”），后面每篇只等 60 秒；用户在登录框输入时照常等。
- 每个出版社每小时最多打开 100 篇（后端配置 `publisher_hourly_limit`，0 为不限）。到上限时批量等到可以继续再下这一篇（日志写明时间）；单篇返回 `rate_limited`，稍后再试。
- 出版社网站拦截了当前网络（`access_blocked`，如 Cloudflare 拦截页）时这一篇结束；同一期刊 30 分钟内的其他文章直接跳过（`journal_blocked_earlier`），其他期刊照常继续。告诉用户可能是当前网络被网站防护拦截，也可能是下载过多被暂停：可换网络或稍后再试，后者请联系学校图书馆。
- 登录和人机验证只由用户在下载浏览器里完成；不索取账号、密码、验证码，不代替用户通过验证。
- 阶段以本次调用的结构化通知为准（命令写在 stderr，stdout 只有最终 JSON）；不凭等待时间猜阶段。
- PDF 在新标签页打开不等于已保存；以命令的最终结果为准，网页地址不是本地文件。
- 需要取消时中止当前调用；旧浏览器仍占用数据目录时不启动下一次下载，不自动删除占用锁。

## 进度窗口和问题报告

- “跳过本篇”：只结束当前这一篇。“本刊无权限”“出版社无权限”：结束这一篇并记住，以后自动跳过；查看或撤销用 `paper-search-carsi entitlements`（`list` / `clear <key>`）。点击后 1–2 秒内生效。
- ⚑ 报告问题：用户选择看到的问题后，后端截下页面并处理（读取已打开的 PDF、回到文章、刷新、停止自动选校），窗口显示处理结果。
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
- 哪些出版社有补充材料规则见 `publisher-support.md`。没有规则的网站返回 `supplements_not_supported`；页面没列出补充材料时为 `no_supplements`。两者都不影响正文；只取补充材料时整体状态是 `error`，意思是没有可取的文件，不是程序故障。
- 文件存在 `<savePath>/<DOI>_supplements/`，带 `manifest.json`，每个文件有状态（`saved`、`failed`、`skipped`）和原因；结果里的 `supplements` 列出同样内容。
- 上限：每篇最多 50 个文件，每个不超过 200 MB，一篇总共 3 分钟；超出的记 `skipped`（原因 `file_limit`、`too_large`、`time_budget`）。`html_page` 表示链接打开的是网页而不是文件，`http_403` 一类是网站拒绝。
- 只收本文的文件：别的文章的文件、本文的插图、参考文献里的链接都不收。放在 Figshare 等外部网站上的补充材料暂不支持。
- 补充材料、利益冲突声明里也可能印着目标标题和 DOI；不要把补充材料 PDF 当正文交付，正文成功也不代表补充材料齐全。
- 个别网站（目前 Taylor & Francis）拒绝程序直接下载补充材料时，改由浏览器自己下载，清单里写 `via: browser_download`；浏览器下载列表里会出现以一串编号命名、没有扩展名的记录，文件已按真实文件名保存在 `_supplements` 目录，这些记录可在浏览器下载页清除。

## 确认下载成功

以命令的最终成功、实际保存的文件和 PDF 首页的身份核验为准：首页 DOI 和题名对得上目标。参考文献里提到目标 DOI 不算；`review.path`、浏览器里显示 PDF、进程退出码为零都不能单独证明成功。浏览器下载列表里的随机文件名、无扩展名或失败记录来自临时下载，不能代替正式输出文件，也不能仅凭名称判断内容错误。交付时给出实际文件路径、目标 DOI 和本次结果。

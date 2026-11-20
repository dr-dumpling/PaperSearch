# Contributing

## 加一家出版社（tier 1）

1. 复制 `paper_search_school/publishers/builtin/wiley.json`，改成 `<key>.json`。文件名就是注册键：小写、连字符分隔，例如 `annual-reviews.json`。
2. 填域名、DOI 前缀（只写 `10.xxxx` 注册前缀）、文章/PDF URL 模板、成功/认证/SSO 标记、机构选校 selector。字段含义见 `schema.json`；不要写任何学校专属的 selector 或凭证。
3. `"platform"` 是小写的平台标签，`list-publishers` 输出里的 platforms 汇总各 profile 的这一项，下载不读它；没有就写 `"generic"` 或省略。
4. 跑 `pytest tests/test_builtin_profiles.py`：它会校验 schema、键/别名/DOI 前缀不与其他出版社冲突。这是合并的最低门槛。
5. 当前源码新增（待发布）：下载失败后运行 `paper-search failures --export ./failure-report.zip --doi <DOI>`，从包内取核对过的 HTML 结构快照，放进 `tests/fixtures/publishers/<key>/`。先检查学校、姓名、邮箱、学号等信息；`href/action` 为避免执行已改为 `data-href/data-action`，编写真实页面 selector 时还原属性名。旧记录缺少 HTML 时不会补造，需另行记录一次授权测试。不得放入原始诊断、Cookie 或论文全文。
6. 本机运行 `paper-search-school publisher-check --doi <受限 DOI>`，把脱敏报告贴进 PR。

## 加一个出版社适配器（tier 2）

通用流程判断不了的出版社专用行为写成适配器钩子：`adapters/<name>/__init__.py` 里继承 `PublisherAdapter`（出版社在某个网站平台上时继承 `adapters/platforms/<平台>/` 的适配器，只写自己不同的），`@register`，再在 `adapters/__init__.py` 里导入。钩子和默认值见 `adapters/base.py`，规则加在哪一层见 [架构说明](../docs/ARCHITECTURE.zh.md#机构下载这一侧)。

## 验证框自动交互

支持通过浏览器自动定位并点击 Cloudflare/Turnstile 验证复选框，网站放行后继续下载。新适配器复用 `browser/challenge/detection.py` 的验证识别和 `browser/challenge/interaction.py` 的原生点击，由 `engine/batch_waits.py` 统一调度：每次验证等待最多尝试 3 次，两次至少间隔 3 秒，沿用原等待时限；自动阶段结束后仍未放行时提示人工接管。

点击前的指针接近路径与按压时长在 `browser/challenge/pointer.py`：先沿一条曲线把指针移进控件、停一下，再用 `mouse.down()` → 停 50-120 ms → `mouse.up()` 完成按压。按压前先问主文档 `elementFromPoint` 该点是不是控件所在的 iframe，被弹层挡住就退回 Playwright 自带的命中检查，不硬点。`PAPER_SEARCH_POINTER_PATH=off` 回到只用 `click()`。

Cloudflare 之外的确认控件在 `browser/challenge/prompt.py`（用户 2026-11-18 定：这些确认控件也由程序按一次）：reCAPTCHA v2 的 “I'm not a robot”、hCaptcha 的 `#checkbox`、AWS WAF 的 “Verify you are human”。只按确认控件，不猜图、不拖滑块；谜题出现仍交人工。`PAPER_SEARCH_AUTO_CONFIRM=0` 关闭。

站点首次访问前先开一次它的首页（`browser/challenge/warmup.py`，由 `engine/batch.py` 的 `_warm_session` 调用）：让站点在文章地址之前先读到第一方文档。每个站点每个进程一次，独立标签页，开完就关；失败只记录，不影响这一篇。`browser_session_warmup: false` 关闭。

浏览器可以接管用户自己启动的 Chrome（`browser_backend: attach` + `browser_attach_url`，如 `http://127.0.0.1:9222`）：用它已有的登录态和 clearance 下载，程序只关闭自己打开的标签页，不关闭浏览器。Chrome 136 起远程调试必须配非默认 `--user-data-dir`，不能用日常的 Chrome 数据目录；用 `chrome --remote-debugging-port=9222 --user-data-dir="<专用目录>"` 启动一次，在这个目录里登录学校、过一次验证，之后长期复用。`attach` 不能与 `launch` 同时用同一个目录（Chrome 有锁）。

验证是否通过以网站实际放行为依据，点击后继续检查页面状态；取得 PDF 后照常核对论文身份。相关改动需覆盖控件定位、重试次数、等待时限和验证后继续下载的测试。

## 不接受的改动

- 伪造验证通过状态或绕过论文访问权限的代码。
- 把维护者或任何人的学校、IdP、账号写进规则。
- 灰色来源。

## 机构入口（tier 3）

由维护者处理；issue 里描述你的联盟和入口页面即可。

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

支持通过浏览器自动定位并点击 Cloudflare/Turnstile 验证复选框，网站放行后继续下载。新适配器复用 `browser/challenges.py` 的验证识别和 `browser/challenge_interaction.py` 的原生点击，由 `engine/batch_waits.py` 统一调度：每次验证等待最多尝试 3 次，两次至少间隔 3 秒，沿用原等待时限；自动阶段结束后仍未放行时提示人工接管。

验证是否通过以网站实际放行为依据，点击后继续检查页面状态；取得 PDF 后照常核对论文身份。相关改动需覆盖控件定位、重试次数、等待时限和验证后继续下载的测试。

## 不接受的改动

- 伪造验证通过状态或绕过论文访问权限的代码。
- 把维护者或任何人的学校、IdP、账号写进规则。
- 灰色来源。

## 机构入口（tier 3）

由维护者处理；issue 里描述你的联盟和入口页面即可。

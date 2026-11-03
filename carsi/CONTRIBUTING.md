# Contributing

## 加一家出版社（tier 1）

1. 复制 `paper_search_carsi/publishers/builtin/wiley.json`，改成 `<key>.json`。文件名就是注册键：小写、连字符分隔，例如 `annual-reviews.json`。
2. 填域名、DOI 前缀（只写 `10.xxxx` 注册前缀）、文章/PDF URL 模板、成功/认证/SSO 标记、机构选校 selector。字段含义见 `schema.json`；不要写任何学校专属的 selector 或凭证。
3. `"platform"` 是小写的平台标签，`list-publishers` 输出里的 platforms 汇总各 profile 的这一项，下载不读它；没有就写 `"generic"` 或省略。
4. 跑 `pytest tests/test_builtin_profiles.py`：它会校验 schema、键/别名/DOI 前缀不与其他出版社冲突。这是合并的最低门槛。
5. 在 `tests/fixtures/publishers/<key>/` 放脱敏后的文章页、认证页 HTML 快照（去掉 cookie、token、个人信息）。
6. 本机运行 `paper-search-carsi publisher-check --doi <受限 DOI>`，把脱敏报告贴进 PR。

## 加一个出版社适配器（tier 2）

通用流程判断不了的出版社专用行为写成适配器钩子：`adapters/<name>/__init__.py` 里继承 `PublisherAdapter`（出版社在某个网站平台上时继承 `adapters/platforms/<平台>/` 的适配器，只写自己不同的），`@register`，再在 `adapters/__init__.py` 里导入。钩子和默认值见 `adapters/base.py`，规则加在哪一层见仓库的 `docs/dependencies/institutional-publisher-adapters.zh.md`。

## 不接受的改动

- 任何绕过网站安全验证的代码。
- 把维护者或任何人的学校、IdP、账号写进规则。
- 灰色来源。

## 机构入口（tier 3）

由维护者处理；issue 里描述你的联盟和入口页面即可。

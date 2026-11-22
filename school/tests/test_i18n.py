"""The progress window in English: every text it can show has a short English
one in assets/capsule_en.json, and the language setting switches it."""
import json
import os
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from paper_search_school import api_keys, i18n, progress_view as pv, user_settings
from paper_search_school.issues import ISSUE_KINDS
from paper_search_school.progress_capsule import Api, page_html

HAN = re.compile(r"[一-鿿]")
PACKAGE = Path(pv.__file__).resolve().parent
REPO = PACKAGE.parent.parent  # PaperSearch, whose summaries the window shows


def english(text: str) -> str:
    return i18n.translate(text, "en")


def untranslated(texts) -> list[str]:
    return sorted({text for text in texts if HAN.search(english(text))})


def engine_texts() -> list[str]:
    """The download's own prompts, phases and click answers (not f-strings)."""
    found = []
    for path in PACKAGE.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        found += re.findall(r'(?:phase=|set_attention\([^,]+,\s*|_tell_user\(|"phase":\s*)"([^"]*[一-鿿][^"]*)"', source)
        # The answers to a click on the card (2026-11-21: those set as `text = "..."` and shown by _tell_user were
        # missed), and a notice written across lines.
        found += re.findall(r'\btext(?:, action)? = f?"([^"{]*[一-鿿][^"{]*)"', source)
        found += ["".join(re.findall(r'"([^"]*)"', block)) for block in re.findall(r'_NOTICE = \(((?:\s*"[^"]*")+)\s*\)', source)]
        for pair in re.findall(r'message = \(\s*"([^"]+)"\s+if[^\n]*\n\s*else\s+"([^"]+)"', source):
            found += list(pair)
    return found


#: Where the windows' texts come from: every Chinese text in these
#: files is one the progress or settings window may show, unless NOT_SHOWN says why not (user, 2026-11-21: all the
#: capsule shows in the tables).
WINDOW_SOURCES = ("progress_view.py", "progress_capsule.py", "progress_reporter.py", "pro_status.py", "school_login.py",
                  "user_settings.py", "issues.py", "api_keys.py", "entitlements.py", "engine/batch.py", "engine/batch_login.py",
                  "engine/batch_waits.py", "engine/batch_user.py", "engine/batch_runs.py", "engine/bridge.py",
                  "school_test.py", "updates.py", "orchestrator.py", "server.py")
#: Chinese in those files the windows never show, each with why.
NOT_SHOWN = {
    "进度窗口没能启动": "raised when the window could not start",
    "进度胶囊需要 pywebview，当前环境里没有（\x00）；请运行 paper-search school update": "said in the terminal",
    "正在进行安全验证": "looked for on a page", "不支持的请求": "looked for on a page", "人机验证": "looked for on a page",
    "登录成功": "looked for in a page's title",
    "无进展": "looked for in a prompt", "没有进展": "looked for in a prompt", "选择学校": "looked for in a prompt",
    "登录": "looked for in a prompt", "验证": "looked for in a prompt",
    "Markdown 全文：": "the title of an issue on GitHub",
    "出版商下载 · \x00": "a task's name, not shown",
    "此论文需要机构登录。请让用户在弹出的下载浏览器窗口里完成登录或人工验证后重试；不要索取账号、密码或验证码。": "a hint for the AI tool",
}
#: Parts the windows show joined to others, each with a whole text it makes, which the table says.
JOINED = {
    " 等": "Spine、Cell 等",
    "\x00 \x00 篇": "PDF 12 篇",
    "；报告已导出：\x00": "打开 issue 页面失败：没有找到默认浏览器；报告已导出：/tmp/report.md",
    "第 \x00/\x00 篇\x00，等待下一篇": "第 3/10 篇已保存，等待下一篇",
    "已检查": "第 3/10 篇已检查，等待下一篇",
    "未完成": "第 3/10 篇未完成，等待下一篇",
}
#: A page's script, a selector on it or a regular expression: words looked for, not said.
CODE = re.compile(r"=>|has-text\(|\(\?:|\|")


def window_texts() -> list[tuple[str, str]]:
    """Each Chinese text of WINDOW_SOURCES as (where, text), an f-string's values as \\x00; docstrings left out."""
    import ast

    found = []
    for name in WINDOW_SOURCES:
        tree = ast.parse((PACKAGE / name).read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        inner = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                text = "".join(v.value if isinstance(v, ast.Constant) else "\x00" for v in node.values)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs | inner:
                text = node.value
            else:
                continue
            if HAN.search(text) and not CODE.search(text) and text not in NOT_SHOWN:
                found.append((f"{name}:{node.lineno}", text))
    return found


def said(text: str, lang: str = "en") -> bool:
    """Whether the table says ``text``, its values (\\x00) a number, a time or a name, whichever its pattern takes."""
    from itertools import product

    holes = text.count("\x00")
    for values in product(("12", "14:05", "Wiley"), repeat=min(holes, 4)):
        filled = text
        for value in values:
            filled = filled.replace("\x00", value, 1)
        if not HAN.search(i18n.translate(filled, lang)):
            return True
    return False


class EnglishTableTests(unittest.TestCase):
    def test_the_windows_own_texts(self):
        texts = [*pv.CONTENT_LABELS.values(), *pv.STAGE_TEXT.values(), *pv.STEPS, *pv.ACTION_FEEDBACK.values(),
                 *(label for _, label in pv.STAGE_STEP.values()), *ISSUE_KINDS.values(),
                 *(f.label for f in user_settings.FIELDS), *(f.unit for f in user_settings.FIELDS)]
        for group in api_keys.groups():
            texts.append(group["title"])
            texts += [s.get("use", "") for s in group["services"]] + [s.get("guide_label", "") for s in group["services"]]
        self.assertEqual(untranslated(texts), [])

    def test_the_downloads_prompts_and_phases(self):
        texts = engine_texts()
        self.assertGreater(len(texts), 10)
        self.assertEqual(untranslated(texts), [])
        for formatted in ("第 3/10 篇已保存，等待下一篇", "第 3/10 篇：进入机构访问", "已完成 2/9 篇，等待下一篇",
                          "这篇文章只在 Ovid 平台提供，暂不支持，当前路径已停止", "批量下载结束：成功 3，失败 1",
                          "补充材料已保存 4 个", "请输入 30 到 1800 之间的整数", "已收到：选错了学校，正在处理",
                          "已记录页面；处理时出错（TimeoutError）"):
            self.assertFalse(HAN.search(english(formatted)), formatted)

    @unittest.skipUnless((REPO / "src/infrastructure/school/SchoolAttempt.ts").is_file(), "PaperSearch's source is not beside this backend")
    def test_paper_searchs_failure_reasons_and_key_tests(self):
        attempt = (REPO / "src/infrastructure/school/SchoolAttempt.ts").read_text(encoding="utf-8")
        reasons = re.findall(r':\s*"([^"]+)"', re.search(r"SHORT_REASONS[^{]*\{([\s\S]*?)\n\};", attempt).group(1))
        # The batch's finished card and its reasons for the supplementary files and the Markdown.
        summary = "".join((REPO / "src/capabilities/download" / part).read_text(encoding="utf-8")
                          for part in ("batch/batchSummary.ts", "content/supplements/shortfall.ts", "content/markdown/shortfall.ts"))
        literals = re.findall(r'"([^"\n]*[\u4e00-\u9fff][^"\n]*)"', summary)
        key_test = (REPO / "src/config/apiKeyTest.ts").read_text(encoding="utf-8")
        messages = re.findall(r'"([^"\n]*[\u4e00-\u9fff][^"\n]*)"', key_test)
        self.assertGreater(len(reasons), 30)
        self.assertEqual(untranslated(reasons + literals + [m for m in messages]), [])
        for status in ("被拒绝：key 不对，或已失效（HTTP 401）", "服务器限流，稍后再试；key 本身可能没问题（HTTP 429）",
                       "没连上服务器，没法判断；检查网络或代理后再试（ECONNRESET）", "附录 2 个已保存", "机构订阅 3 · 开放获取 1"):
            self.assertFalse(HAN.search(english(status)), status)
        # The two ways of downloading, as the batch's line and its finished card name them (2026-11-10).
        self.assertEqual(english("开放下载 15 篇 · 机构下载 9 篇"), "Open download 15 · School download 9")
        self.assertEqual(english("机构下载 30 · 开放下载 18（出版社 API 3、Sci-Hub 1、预印本 1）"),
                         "School download 30 · Open download 18 (Publisher API 3, Sci-Hub 1, Preprint 1)")

    def test_what_the_progress_card_shows(self):
        now = 1_000_000.0
        running = dict(status="running", run_id="r", total=40, done=12, success=10, failed=1, content="both", part="main",
                       stage="fetching_pdf", publisher="Wiley", journal="Spine", current="10.1/x", title="A study",
                       started_at="2026-11-08T10:00:00", phase="浏览器下载")
        states = [running, {**running, "part": "supplements", "supplements_total": 5, "supplements_saved": 2},
                  {**running, "attention": {"login": {"message": "请在浏览器窗口完成机构登录", "since": 1}}},
                  {**running, "status": "done", "results": {"content": "both", "main": 3, "supplements": 2,
                   "sources": [["机构订阅", 2], ["开放获取", 1]],
                   "failures": [{"cls": "no_access", "reason": "学校没有订阅", "journal": "Spine", "title": "B", "doi": "10.1/y"}]}}]

        def strings(value, key=""):
            if isinstance(value, str):
                return [] if key in ("title", "current", "doi", "run_id") else [value]
            if isinstance(value, dict):
                return [s for k, v in value.items() for s in strings(v, k)]
            if isinstance(value, list):
                return [s for v in value for s in strings(v, key)]
            return []

        shown = [s for state in states for s in strings(pv.view(state, now))]
        self.assertEqual(untranslated(shown), [])

    def test_every_text_the_windows_show_is_in_the_table(self):
        """User, 2026-11-21: all the capsule may show is in the tables. A text added to a window's source and not to
        assets/capsule_en.json fails here; a text that is not shown goes into NOT_SHOWN with why."""
        left = [(where, text) for where, text in window_texts() if not said(JOINED.get(text, text))]
        self.assertEqual(left, [])

    @unittest.skipUnless((REPO / "src/infrastructure/school/SchoolAttempt.ts").is_file(), "PaperSearch's source is not beside this backend")
    def test_what_paper_search_sends_the_window_is_in_the_table(self):
        """PaperSearch's own texts for the window: the batch's line and its lanes, the network's notice, Pro's
        activation and install (the settings page says their messages)."""
        def literals(path, only=None):
            source = (REPO / path).read_text(encoding="utf-8")
            texts = re.findall(r'"([^"\n]*[\u4e00-\u9fff][^"\n]*)"|`([^`\n]*[\u4e00-\u9fff][^`\n]*)`', source)
            out = [re.sub(r"\$\{[^}]*\}", "\x00", a or b) for a, b in texts]
            return [t for t in out if (only is None or only.search(t)) and not t.startswith("[批量]")]
        texts = (literals("src/capabilities/download/batch/networkLoss.ts")
                 + literals("src/management/pro/activate.ts") + literals("src/management/pro/install.ts")
                 # 更新 (updates.py): what PaperSearch's own update says.
                 + literals("src/management/updates/selfUpdate.ts"))
        batch = (REPO / "src/capabilities/download/batch/batch.ts").read_text(encoding="utf-8")
        channel = re.search(r'const OPEN_CHANNEL = "([^"]+)"', batch).group(1)
        texts += [channel] + [re.sub(r"\$\{[^}]*\}", "\x00", t.replace("${OPEN_CHANNEL}", channel))
                              for t in re.findall(r"phase: `([^`]+)`", batch)]
        self.assertGreater(len(texts), 10)
        self.assertEqual([t for t in texts if not said(t)], [])

    def test_every_english_text_is_short(self):
        # The capsule is 330 px wide: English as long as the Chinese it replaces, roughly.
        long = [(zh, en) for zh, en in i18n.table()["exact"].items() if len(en) > max(24, 2.6 * len(zh))]
        self.assertEqual(long, [])

    def test_the_schools_places_in_english(self):
        # 支持哪些学校 in English (user, 2026-11-20): the provinces and the countries the lists name.
        exact = i18n.table()["exact"]
        self.assertEqual((exact["广东"], exact["日本"], exact["英国"]), ("Guangdong", "Japan", "United Kingdom"))

    def test_the_page_carries_the_table(self):
        page = page_html()
        for mark in ("CAPSULE_EN", "CAPSULE_ZH_HANT", "CAPSULE_JA", "CAPSULE_KO", "CAPSULE_FR"):
            self.assertNotIn(f"/*{mark}*/null", page)
        self.assertIn('"exact"', page)
        self.assertIn('"chars"', page)


# Characters only simplified Chinese writes: a Japanese text with one is Chinese left untranslated.
SIMPLIFIED_ONLY = set("设载这们么个从为间开关页门题无还让该应网击查找进务错误说请轻见单时长发变选认样储读删钮译显图码复择优试权")


class OtherLanguagesTests(unittest.TestCase):
    """日本語, 한국어, Français (user, 2026-11-21: "中文、英文、日语、韩文，还有法语这些比较常见的语种都需要支持"):
    a table each, of the English table's texts; what one does not know is said in English, not in Chinese."""

    LANGS = ("ja", "ko", "fr")

    def test_each_says_every_text_the_english_table_says(self):
        english = i18n.table("en")
        for lang in self.LANGS:
            with self.subTest(lang=lang):
                table = i18n.table(lang)
                self.assertEqual(list(table["exact"]), list(english["exact"]))
                self.assertEqual([p[0] for p in table["patterns"]], [p[0] for p in english["patterns"]])
                for (source, said), (_, en) in zip(table["patterns"], english["patterns"]):
                    self.assertEqual(sorted(re.findall(r"\$\d", said)), sorted(re.findall(r"\$\d", en)), source)
                self.assertEqual([zh for zh, said in table["exact"].items() if not said.strip()], [])

    def test_in_their_own_writing_and_short(self):
        for lang in self.LANGS:
            with self.subTest(lang=lang):
                said = list(i18n.table(lang)["exact"].items()) + [(p[0], p[1]) for p in i18n.table(lang)["patterns"]]
                if lang == "ja":
                    self.assertEqual([t for _, t in said if SIMPLIFIED_ONLY & set(t)], [])
                else:
                    self.assertEqual([t for _, t in said if re.search(r"[\u4e00-\u9fff]", t)], [])
                self.assertEqual([(zh, t) for zh, t in i18n.table(lang)["exact"].items() if len(t) > max(24, 2.6 * len(zh))], [])

    def test_a_text_their_table_does_not_know_is_said_in_english(self):
        english = i18n.table("en")["exact"]
        text = next(iter(english))
        for lang in self.LANGS:
            with self.subTest(lang=lang), patch.dict(i18n.table(lang)["exact"], clear=False) as table:
                table.pop(text)
                self.assertEqual(i18n.translate(text, lang), english[text])
        self.assertEqual(i18n.translate("Nature Medicine", "fr"), "Nature Medicine")
        self.assertEqual(i18n.translate("设置", "ja"), i18n.table("ja")["exact"]["设置"])

    def test_what_a_numbered_text_names_is_said_too(self):
        # "更新学校订阅下载扩展出错" showed "Updating 学校订阅下载扩展 failed"; a school's name, in Traditional Chinese
        # characters (the French table's translator saw it, 2026-11-21).
        self.assertEqual(i18n.translate("更新学校订阅下载扩展出错", "en"), f"Updating {i18n.table('en')['exact']['学校订阅下载扩展']} failed")
        self.assertEqual(i18n.translate("没权限，换红木兰大学", "zh-Hant"), "沒權限，換紅木蘭大學")
        self.assertEqual(i18n.translate("没权限，换Hongmulan University", "en"), "No access, trying Hongmulan University")

    def test_they_can_be_chosen(self):
        self.assertEqual(i18n.LANGUAGES, ("zh", "zh-Hant", "en", "ja", "ko", "fr"))


class TraditionalChineseTests(unittest.TestCase):
    """繁體中文 (user, 2026-11-21): assets/capsule_zh-Hant.json, made from the English table's texts by
    school/tools/zh_hant_table.py: Taiwan's wording for a program's words, then the characters."""

    def test_the_windows_texts_in_taiwans_wording(self):
        hant = lambda text: i18n.translate(text, "zh-Hant")
        self.assertEqual(hant("设置"), "設定")
        self.assertEqual(hant("默认下载文件夹"), "預設下載資料夾")
        self.assertEqual(hant("学校自动登录"), "學校自動登入")
        self.assertEqual(hant("登录页 180 秒 · 系统通知开"), "登入頁 180 秒 · 系統通知開")  # a numbered text, then an exact one
        self.assertEqual(hant("已达设置的每小时 500 篇，14:05 重新计数"), "已達設定的每小時 500 篇，14:05 重新計數")

    def test_a_text_the_table_does_not_know_keeps_its_words_in_its_characters(self):
        # A school's or a journal's name: its words are its own (信息 stays, not 資訊).
        self.assertEqual(i18n.translate("南岭军工信息学院", "zh-Hant"), "南嶺軍工信息學院")
        self.assertEqual(i18n.translate("Nature Medicine", "zh-Hant"), "Nature Medicine")

    def test_every_text_of_the_windows_is_turned(self):
        # Made from the English table: a text added there and not made again here would show in simplified characters.
        chars = i18n.table("zh-Hant")["chars"]
        exact = i18n.table("zh-Hant")["exact"]
        left = [text for text in i18n.table()["exact"] if text not in exact and any(c in chars for c in text)]
        self.assertEqual(left, [], "run school/tools/zh_hant_table.py")
        for text, said in exact.items():
            self.assertFalse([c for c in said if c in chars], said)


class LanguageSettingTests(unittest.TestCase):
    def test_the_switch_saves_and_the_window_follows_it(self):
        from paper_search_school import config
        # The backend's config path is fixed when it is imported: point it at a scratch file.
        with TemporaryDirectory() as tmp, patch.object(config, "DATA_DIR", Path(tmp)), \
             patch.object(config, "CONFIG_FILE", Path(tmp) / "config.json"):
            self.assertEqual(user_settings.language(), "zh")
            a = Api(MagicMock(), MagicMock(), MagicMock())
            with patch("paper_search_school.progress_capsule.read_state", return_value=None), \
                 patch("paper_search_school.progress_capsule.take_settings_request", return_value=None):
                self.assertEqual(a.state()["lang"], "zh")
                self.assertEqual(a.set_language("en"), {"ok": True, "language": "en"})
                self.assertEqual(a.state()["lang"], "en")
            self.assertEqual(user_settings.language(), "en")
            self.assertEqual(a.set_language("zh-Hant"), {"ok": True, "language": "zh-Hant"})
            self.assertEqual(user_settings.language(), "zh-Hant")
            self.assertEqual(a.set_language("fr"), {"ok": True, "language": "fr"})  # Français too (user, 2026-11-21)
            self.assertEqual(a.set_language("en"), {"ok": True, "language": "en"})
            self.assertFalse(a.set_language("de")["ok"])  # not one of the window's languages yet
            self.assertEqual(Api(MagicMock(), MagicMock(), MagicMock()).settings()["language"], "en")

    def test_a_notification_speaks_the_windows_language(self):
        from paper_search_school.progress_capsule import Notifier
        sent = []
        notifier = Notifier(send=lambda title, body, state: sent.append(body))
        state = {"status": "running", "run_id": "r", "current": "10.1/x",
                 "attention": {"login": {"message": "请在浏览器窗口完成机构登录", "since": 1}}}
        with patch.object(user_settings, "notify_enabled", return_value=True), \
             patch.object(user_settings, "language", return_value="en"), \
             patch("threading.Thread", side_effect=lambda target, args, daemon: MagicMock(start=lambda: target(*args))):
            notifier.observe(state)
        self.assertEqual(sent, ["Sign in to school in the browser"])
        with patch.object(user_settings, "notify_enabled", return_value=True), \
             patch.object(user_settings, "language", return_value="zh-Hant"), \
             patch("threading.Thread", side_effect=lambda target, args, daemon: MagicMock(start=lambda: target(*args))):
            Notifier(send=lambda title, body, state: sent.append(body)).observe(state)
        self.assertEqual(sent[-1], i18n.translate("请在浏览器窗口完成机构登录", "zh-Hant"))
        self.assertNotIn("录", sent[-1])


if __name__ == "__main__":
    unittest.main()

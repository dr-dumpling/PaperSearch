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
        for pair in re.findall(r'message = \(\s*"([^"]+)"\s+if[^\n]*\n\s*else\s+"([^"]+)"', source):
            found += list(pair)
    return found


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
                          "补充材料已保存 4 个", "请输入 30 到 1800 之间的整数", "已收到：选错了学校，正在处理"):
            self.assertFalse(HAN.search(english(formatted)), formatted)

    @unittest.skipUnless((REPO / "src").is_dir(), "PaperSearch's source is not beside this backend")
    def test_paper_searchs_failure_reasons_and_key_tests(self):
        attempt = (REPO / "src/capabilities/pdf-discovery/school/SchoolAttempt.ts").read_text(encoding="utf-8")
        reasons = re.findall(r':\s*"([^"]+)"', re.search(r"SHORT_REASONS[^{]*\{([\s\S]*?)\n\};", attempt).group(1))
        summary = (REPO / "src/capabilities/pdf-discovery/batchSummary.ts").read_text(encoding="utf-8")
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

    def test_every_english_text_is_short(self):
        # The capsule is 330 px wide: English as long as the Chinese it replaces, roughly.
        long = [(zh, en) for zh, en in i18n.table()["exact"].items() if len(en) > max(24, 2.6 * len(zh))]
        self.assertEqual(long, [])

    def test_the_page_carries_the_table(self):
        page = page_html()
        self.assertNotIn("/*CAPSULE_EN*/null", page)
        self.assertIn('"exact"', page)


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
            self.assertFalse(a.set_language("fr")["ok"])
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


if __name__ == "__main__":
    unittest.main()

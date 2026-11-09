"""The capsule page in the real window: pywebview and the system web engine
(WebKit on macOS, WebView2 on Windows), with pywebview's own scripts beside the
page's. The Chrome page tests do not see a clash with those: a page-level
`let keys` left the macOS window blank (2026-11-08)."""
import os
import subprocess
import sys
import unittest

PROBE = r'''
import sys, time, webview
from paper_search_carsi.progress_capsule import page_html
LANG = sys.argv[1]
class Bridge:
    def platform(self): return "test"
    def state(self, hovering=False): return {"mode": "idle", "lang": LANG}
    def hover_state(self): return {"x": -1, "y": -1, "inside": False}
    def begin_layout(self, *args): return {}
    def resize(self, *args): return None
    def finish_layout(self, *args): return None
def probe(window):
    window.events.loaded.wait(15)
    time.sleep(2)
    print("render:", window.evaluate_js("typeof render"))
    print("root:", window.evaluate_js("document.getElementById('root').innerText"))
    window.destroy()
webview.start(probe, webview.create_window("capsule page test", html=page_html(), js_api=Bridge(),
                                           width=360, height=200))
'''


@unittest.skipUnless(os.environ.get("CARSI_WEBVIEW_TESTS") == "1", "opt-in: opens a real window (needs the desktop session)")
class CapsulePageWebviewTests(unittest.TestCase):
    def test_the_page_runs_beside_pywebviews_scripts_in_both_languages(self):
        for lang, idle in (("zh", "暂无下载任务"), ("en", "No downloads")):
            with self.subTest(lang=lang):
                done = subprocess.run([sys.executable, "-c", PROBE, lang], capture_output=True, text=True, timeout=90,
                                      cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                self.assertIn("render: function", done.stdout, done.stderr[-2000:])
                self.assertIn(idle, done.stdout)


if __name__ == "__main__":
    unittest.main()

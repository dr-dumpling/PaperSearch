"""The readiness probe finds document text without reading the whole rendered page."""
import os
import unittest

from paper_search_carsi.engine.batch import PublisherBatchDownloader
from paper_search_carsi.engine.batch_common import _DOCUMENT_STATE_JS


@unittest.skipUnless(os.environ.get("CARSI_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class PageTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)

    def test_readiness_does_not_force_a_full_document_layout(self):
        self.page.set_content("<body><h1>Article title</h1><p>Article text</p></body>")
        self.page.evaluate("""() => Object.defineProperty(document.body, 'innerText', {
            get() { throw new Error('full document layout is too expensive'); }
        })""")
        self.assertGreater(self.page.evaluate(PublisherBatchDownloader._PAGE_TEXT_JS), 0)
        self.assertEqual(self.page.evaluate(_DOCUMENT_STATE_JS)[0], "complete")

    def test_scripts_and_hidden_loading_content_do_not_make_a_blank_document_ready(self):
        self.page.set_content('''<body><script type="application/json">{"title":"Article"}</script>
            <style>body { color: black; }</style><div hidden>Article text</div>
            <div style="visibility:hidden">Loading</div><div style="display:none">Menu</div></body>''')
        self.assertEqual(self.page.evaluate(PublisherBatchDownloader._PAGE_TEXT_JS), 0)

    def test_a_document_that_later_renders_text_becomes_ready(self):
        self.page.set_content("<body></body>")
        self.assertEqual(self.page.evaluate(PublisherBatchDownloader._PAGE_TEXT_JS), 0)
        self.page.evaluate("document.body.innerHTML = '<main><p>Article text</p></main>'")
        self.assertGreater(self.page.evaluate(PublisherBatchDownloader._PAGE_TEXT_JS), 0)

    def test_supplement_labels_do_not_force_the_article_layout_or_change_its_urls(self):
        from paper_search_carsi.adapters.platforms.atypon import _SUPPLEMENT_ROWS_JS
        self.page.set_content('''<base href="https://publisher.example/">
            <a href="/doi/suppl/10.1234/example/suppl_file/data"><span>Data</span> supplement</a>
            <a href="/doi/suppl/10.1234/example/suppl_file/table.pdf" title="Table"> </a>''')
        self.page.evaluate("""() => document.querySelectorAll('a').forEach(a => {
            Object.defineProperty(a, 'innerText', {get() {throw new Error('unnecessary layout');}});
        })""")
        rows = self.page.evaluate(_SUPPLEMENT_ROWS_JS)
        self.assertEqual(rows, [
            {'href': 'https://publisher.example/doi/suppl/10.1234/example/suppl_file/data', 'label': 'Data supplement'},
            {'href': 'https://publisher.example/doi/suppl/10.1234/example/suppl_file/table.pdf', 'label': 'Table'}])

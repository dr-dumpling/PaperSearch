"""Two MCP download calls share the real Playwright thread, context and tab."""
import asyncio
import json
import os
from pathlib import Path

import pytest
import pymupdf

from paper_search_school import server
from paper_search_school.browser.backend import launch_persistent_context
from paper_search_school.browser.batch_session import BatchBrowser
from paper_search_school.browser.preview import ensure_enabled, observe_page
from paper_search_school.engine import bridge
from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.publishers.profiles import SPRINGER_PROFILE
from test_pdf_after_check import article_pdf


@pytest.mark.skipif(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") != "1",
                    reason="local browser fixture opt-in")
def test_serial_downloads_reuse_browser_until_the_batch_closes(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHOOL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SCHOOL_PROGRESS_BAR", "0")
    monkeypatch.setattr(server, "_batch_browser", BatchBrowser())
    launches, pages, popups = [], [], []
    preview_dir = tmp_path / "previews"
    config = {"browser_preview_dir": str(preview_dir)}

    def launch(downloader, **_):
        context = launch_persistent_context(str(tmp_path / "profile"), headless=True, humanize=False)
        launches.append(context)
        context.route("**/*", lambda route: route.fulfill(
            content_type="text/html", body="<title>Fixture article</title>"))
        downloader.browser = {"backend": "chrome"}
        ensure_enabled(context, config)
        return context

    def fetch(_downloader, page, record, run_dir):
        if popups:
            assert popups[-1].is_closed()
        pages.append(page)
        page.goto("https://link.springer.com/article/" + record.doi)
        assert page.title() == "Fixture article"
        observe_page(page, force=True)
        preview_file, = preview_dir.glob("*/current.json")
        preview = json.loads(preview_file.read_text(encoding="utf-8"))
        assert preview["identifier"] == record.doi
        assert preview["pages"][0]["screenshot_status"] == "available"
        popups.append(page.context.new_page())
        pdf = run_dir / "fixture.pdf"
        pdf.write_bytes(article_pdf(record.doi))
        return DownloadResult(doi=record.doi, status="success", state="pdf_saved", final_url=page.url,
                              pdf_path=str(pdf), verified_match=True, size_bytes=pdf.stat().st_size)

    def download(doi, output_dir, **_):
        path = Path(output_dir) / (doi.rsplit("/", 1)[-1] + ".pdf")
        return bridge._try_browser_batch_download(doi, path, config, SPRINGER_PROFILE)

    monkeypatch.setattr(PublisherBatchDownloader, "_launch_context", launch)
    monkeypatch.setattr(PublisherBatchDownloader, "fetch_one", fetch)
    monkeypatch.setattr(server, "download", download)

    async def exercise():
        try:
            for index, doi in enumerate(("10.1007/first", "10.1007/second"), start=1):
                answer = await server._school_download_with_progress(
                    doi, str(tmp_path), batch_id="fixture", batch_index=index, batch_total=2,
                    batch_done=index - 1, batch_succeeded=index - 1, batch_failed=0, keep_browser=True)
                result = json.loads(answer)
                assert result["success"], result
                with pymupdf.open(result["file"]) as pdf:
                    assert doi in pdf[0].get_text()
            assert len(launches) == 1
            assert pages[0] is pages[1] and not pages[1].is_closed()
            # While the batch waits (the hourly limit), the last article page is loaded again.
            # (Playwright calls belong to the batch's worker thread.)
            await asyncio.get_running_loop().run_in_executor(server._batch_worker, lambda: pages[0].goto("about:blank"))
            assert json.loads(await server.school_keep_session()) == {"kept": True}
            assert pages[0].url == "https://link.springer.com/article/10.1007/second"
        finally:
            await server.school_close_batch_browser()
        assert pages[0].is_closed()
        assert all(popup.is_closed() for popup in popups)

    asyncio.run(exercise())


class _Page:
    def __init__(self, fail=False, check=None, lands=()):
        # check: the Cloudflare check the article page meets ("clears" after a click, or "stays");
        # lands: where the article page goes instead, one page per wait (the last one stays).
        self.visited, self.fail, self.closed, self.check, self.url = [], fail, False, check, ""
        self.lands, self.clock = list(lands), None

    def is_closed(self):
        return self.closed

    def goto(self, url, **_):
        if self.fail and url != "about:blank":
            raise TimeoutError("slow")
        self.visited.append(url)
        self.url = url + "?__cf_chl_rt_tk=x" if self.check and url != "about:blank" else url
        if self.lands and url != "about:blank":
            self.url = self.lands[0]

    def title(self):
        return "Just a moment..." if "__cf_chl" in self.url else "An article"

    def wait_for_timeout(self, ms):
        if self.clock is not None:
            self.clock[0] += ms / 1000
        if len(self.lands) > 1:
            self.lands.pop(0)
            self.url = self.lands[0]


def test_keep_session_loads_only_the_last_saved_papers_article_page():
    """A wait of the batch keeps the publisher's session with the last paper that saved its
    PDF; after one that did not (a school's login page in the tab), the tab is left alone."""
    batch = BatchBrowser()
    assert batch.keep_session() == {"kept": False, "reason": "no_publisher_page"}  # no browser
    batch.context, batch.page = object(), _Page()
    assert batch.keep_session() == {"kept": False, "reason": "no_publisher_page"}  # no saved paper yet
    batch.article_url = "https://journals.example/doi/10.1000/a"
    assert batch.keep_session() == {"kept": True}
    assert batch.page.visited == ["https://journals.example/doi/10.1000/a"]
    batch.page = _Page(fail=True)  # a load that hangs: the tab is left blank
    assert batch.keep_session() == {"kept": False, "reason": "TimeoutError"}
    assert batch.page.visited == ["about:blank"] and batch.article_url == ""
    batch.page.closed = True
    assert batch.keep_session() == {"kept": False, "reason": "no_publisher_page"}


def test_keep_session_clears_a_cloudflare_check_or_leaves_it(monkeypatch):
    """The article page loaded again met a Cloudflare check, and the tab sat on it,
    spinning, for the rest of the wait (Elsevier, Windows, 2026-11-13). Its checkbox is
    clicked as in a download; one that does not clear leaves the tab blank, and no
    keep-alive runs again until a paper saves."""
    from types import SimpleNamespace

    from paper_search_school.browser import batch_session, challenge_interaction

    clicks = []

    def click(page, **_):
        clicks.append(page.url)
        if page.check == "clears":
            page.url = page.url.split("?")[0]
        return "clicked"

    monkeypatch.setattr(challenge_interaction, "click_checkbox", click)
    clock = [0.0]
    monkeypatch.setattr(batch_session, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    batch = BatchBrowser()
    batch.context, batch.page = object(), _Page(check="clears")
    batch.article_url = "https://journals.example/article/a"
    assert batch.keep_session() == {"kept": True}
    assert batch.page.url == "https://journals.example/article/a" and len(clicks) == 1

    page = _Page(check="stays")
    page.clock = clock
    batch.page = page
    assert batch.keep_session() == {"kept": False, "reason": "verification"}
    assert len(clicks) == 1 + 3  # three clicks, three seconds apart, then left
    assert page.visited[-1] == "about:blank" and batch.article_url == ""
    assert batch.keep_session() == {"kept": False, "reason": "no_publisher_page"}  # until a paper saves


def test_keep_session_waits_out_the_publishers_own_sign_in_or_leaves_it(monkeypatch):
    """Loaded again, the article page went to Elsevier's sign-in (id.elsevier.com), which
    never loaded; the tab sat on it, spinning, for the rest of the wait (Windows,
    2026-11-13). A sign-in the publisher runs by itself and that comes back to the
    article's site keeps the session; one that does not is left, the tab blank."""
    from types import SimpleNamespace

    from paper_search_school.browser import batch_session

    clock = [0.0]
    monkeypatch.setattr(batch_session, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    article = "https://www.journal.example/article/S1/fulltext"
    sign_in = "https://id.publisher.example/as/authorization.oauth2?client=journal"

    batch = BatchBrowser()
    batch.context, batch.article_url = object(), article
    batch.page = _Page(lands=[sign_in, sign_in, "https://journal.example/article/S1/fulltext"])
    batch.page.clock = clock
    assert batch.keep_session() == {"kept": True}  # back on the article's site (with or without www)

    clock[0] = 0.0
    batch.page = _Page(lands=[sign_in])
    batch.page.clock = clock
    assert batch.keep_session() == {"kept": False, "reason": "signin"}
    assert batch.page.visited == [article, "about:blank"] and batch.article_url == ""

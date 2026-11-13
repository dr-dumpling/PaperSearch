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
    def __init__(self, fail=False):
        self.visited, self.fail, self.closed = [], fail, False

    def is_closed(self):
        return self.closed

    def goto(self, url, **_):
        if self.fail:
            raise TimeoutError("slow")
        self.visited.append(url)


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
    batch.page = _Page(fail=True)
    assert batch.keep_session() == {"kept": False, "reason": "TimeoutError"}
    batch.page.closed = True
    assert batch.keep_session() == {"kept": False, "reason": "no_publisher_page"}

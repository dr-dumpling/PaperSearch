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
        return DownloadResult(doi=record.doi, status="success", state="pdf_saved",
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
        finally:
            await server.school_close_batch_browser()
        assert pages[0].is_closed()
        assert all(popup.is_closed() for popup in popups)

    asyncio.run(exercise())

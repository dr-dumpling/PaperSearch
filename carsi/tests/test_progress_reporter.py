from __future__ import annotations

import pytest

from paper_search_carsi import progress_reporter


def test_manual_attention_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("CARSI_DATA_DIR", str(tmp_path))

    progress_reporter.start_task("文献下载", total=3)
    assert progress_reporter.read_state()["attention"] == {}

    progress_reporter.set_attention("publisher:a", "请在浏览器窗口完成安全验证", current="10.1000/a", phase="人工验证")
    progress_reporter.set_attention("publisher:b", "请在浏览器窗口完成安全验证", current="10.1000/b", phase="人工验证")
    state = progress_reporter.read_state()
    assert set(state["attention"]) == {"publisher:a", "publisher:b"}
    assert state["attention"]["publisher:b"]["current"] == "10.1000/b"

    progress_reporter.advance(True, current="10.1000/c")
    assert progress_reporter.read_state()["done"] == 1

    progress_reporter.clear_attention("publisher:a")
    assert set(progress_reporter.read_state()["attention"]) == {"publisher:b"}
    progress_reporter.finish()
    state = progress_reporter.read_state()
    assert state["status"] == "done"
    assert state["attention"] == {}


@pytest.mark.parametrize("waits, reminder, handoff, spent", [
    (1, False, False, 0), (22, False, False, 0), (59, False, False, 0), (10, False, False, 55)])
def test_widget_absence_stays_automatic_and_obeys_the_original_operation_budget(
        tmp_path, monkeypatch, waits, reminder, handoff, spent):
    """The reminder delay and the existing automation budget are independent."""
    monkeypatch.setenv("CARSI_DATA_DIR", str(tmp_path))
    progress_reporter.start_task("出版商下载", total=1)

    from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
    from paper_search_carsi.engine import batch_waits
    from paper_search_carsi.browser import watchdog
    clock = [1000.0]
    monkeypatch.setattr(batch_waits.time, "time", lambda: clock[0])
    monkeypatch.setattr(watchdog.time, "monotonic", lambda: clock[0])

    downloader = PublisherBatchDownloader.__new__(PublisherBatchDownloader)
    downloader.config = {}
    events = []
    downloader.login_timeout_sec = 60
    downloader._event = lambda result, kind, detail: events.append(kind)
    downloader._raise_on_publisher_access_blocked = lambda page: None
    downloader._title = lambda page: ""

    class FakePage:
        title = lambda self: ""
        url = "https://example.test/article"
        frames = []
        evaluate = lambda *args: False  # no visible image-puzzle controls
        on = lambda *args: None
        remove_listener = lambda *args: None

        def __init__(self):
            self.calls = 0
            self.attention_seen = False
            self.waited_ms = []

        def wait_for_timeout(self, ms):
            budgets = getattr(watchdog._local, "budgets", [])
            if budgets and clock[0] >= min(b[0] for b in budgets):
                raise watchdog.BrowserOperationTimeout("article preparation exhausted")
            self.waited_ms.append(ms)
            clock[0] += ms / 1000

    page = FakePage()

    def is_challenge(_page):
        page.calls += 1
        page.attention_seen |= bool(progress_reporter.read_state()["attention"])
        return page.calls <= waits

    downloader._is_challenge_page = is_challenge
    result = DownloadResult(doi="10.1000/a", status="failed", state="pdf_response_captured")
    with watchdog.operation(60, "article preparation"):
        clock[0] += spent
        if spent:
            with pytest.raises(watchdog.BrowserOperationTimeout):
                downloader._wait_for_challenge(page, result)
            assert not page.attention_seen
            assert "challenge_manual_wait" not in events
            assert "challenge_resolved" not in events
            return
        assert downloader._wait_for_challenge(page, result)
    # A completed verification leaves no timeout state behind (the supplements visit ran after it).
    assert result.state == "pdf_response_captured"

    assert page.attention_seen is reminder
    assert page.waited_ms == [1000] * waits  # checked every second
    assert ("challenge_manual_wait" in events) is handoff
    assert "challenge_resolved" in events
    assert progress_reporter.read_state()["attention"] == {}

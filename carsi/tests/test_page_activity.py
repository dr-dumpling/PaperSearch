"""A generic idle reminder, independent of publisher and verification widgets."""
from collections import defaultdict
import time
from types import SimpleNamespace

import pytest

from paper_search_carsi import config, progress_reporter, user_settings
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.engine.page_activity import PageActivity


class Page:
    def __init__(self):
        self.main_frame = object()
        self.handlers = defaultdict(list)

    def on(self, event, handler):
        self.handlers[event].append(handler)

    def remove_listener(self, event, handler):
        self.handlers[event].remove(handler)

    def emit(self, event, *args):
        for handler in list(self.handlers[event]):
            handler(*args)


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("CARSI_DATA_DIR", str(tmp_path))
    progress_reporter.start_task("fixture", total=1)
    now = [0.0]
    page = Page()
    activity = PageActivity("10.1234/fixture", {}, clock=lambda: now[0])
    activity.observe(page)
    yield SimpleNamespace(activity=activity, now=now, page=page)
    activity.close()


def attention():
    return progress_reporter.read_state()["attention"]


def test_default_and_custom_thresholds_use_seconds(case):
    a, now = case.activity, case.now
    for when in (0, 10, 29.99):
        now[0] = when
        a.check()
        assert attention() == {}
    now[0] = 30
    a.check()
    reminder = next(iter(attention().values()))
    assert reminder["phase"] == "需要人工处理"
    assert "继续按钮" not in reminder["message"]
    original = dict(attention())
    now[0] = 50
    a.check()
    assert attention() == original
    a.close()
    custom = PageActivity("10.1234/fixture", {"browser_stall_notify_after": 45}, clock=lambda: now[0])
    now[0] = 94
    custom.check()
    assert not attention()
    now[0] = 95
    custom.check()
    assert attention()
    custom.close()


def test_progress_clears_reminder_and_restarts_timer(case):
    a, now = case.activity, case.now
    now[0] = 30
    a.check()
    assert attention()
    now[0] = 35
    a.progress()
    assert not attention()
    now[0] = 64
    a.check()
    assert not attention()
    now[0] = 65
    a.check()
    assert attention()


def test_navigation_and_popup_update_target_but_subframes_do_not(case):
    a, now, page = case.activity, case.now, case.page
    now[0] = 20
    page.emit("framenavigated", object())
    now[0] = 30
    a.check()
    assert attention()
    page.emit("framenavigated", page.main_frame)
    assert not attention()
    now[0] = 40
    popup = Page()
    page.emit("popup", popup)
    assert a.page is popup
    now[0] = 60
    a.check()
    assert not attention()
    popup.emit("close")
    assert a.page is page
    a.close()
    assert all(not handlers for handlers in page.handlers.values())
    now[0] = 100
    a.check()
    assert not attention()


def test_school_login_has_priority_and_restarts_quiet_interval(case):
    a, now = case.activity, case.now
    progress_reporter.set_attention("school", "请登录学校", current="10.1234/fixture")
    now[0] = 100
    a.check()
    assert list(attention()) == ["school"]
    progress_reporter.clear_attention("school")
    now[0] = 129
    a.check()
    assert not attention()
    now[0] = 130
    a.check()
    assert attention()


def navigation(page, *, previous=None):
    return SimpleNamespace(is_navigation_request=lambda: True,
                           frame=page.main_frame, redirected_from=previous)


def test_slow_main_navigation_does_not_prompt_just_before_it_finishes(case):
    a, now, page = case.activity, case.now, case.page
    request = navigation(page)
    page.emit("request", request)
    now[0] = 30
    a.check()
    assert not attention()  # Old code notified during this pending login redirect.
    now[0] = 33
    page.emit("response", SimpleNamespace(request=request))
    page.emit("framenavigated", page.main_frame)
    page.emit("domcontentloaded")
    a.check()
    assert not attention()
    now[0] = 62
    a.check()
    assert not attention()
    now[0] = 63
    a.check()
    assert attention()  # A loaded page that subsequently stalls still notifies.


def test_a_navigation_cannot_suppress_stall_reminders_forever(case):
    a, now, page = case.activity, case.now, case.page
    request = navigation(page)
    page.emit("request", request)
    now[0] = 20
    redirected = navigation(page, previous=request)
    page.emit("request", redirected)
    now[0] = 59
    a.check()
    assert not attention()
    now[0] = 60
    a.check()
    assert attention()  # Redirects keep the original loading bound.


def test_failed_navigation_clears_loading_and_background_traffic_is_not_progress(case):
    a, now, page = case.activity, case.now, case.page
    request = navigation(page)
    page.emit("request", request)
    now[0] = 5
    page.emit("requestfailed", request)
    for second in range(10, 36, 5):
        now[0] = second
        page.emit("request", SimpleNamespace(is_navigation_request=lambda: False))
        page.emit("request", navigation(Page()))
        page.emit("response", SimpleNamespace(request=object()))
        a.check()
    assert attention()  # Failure ended the grace; ads and XHR did not renew it.


def test_loading_bound_uses_existing_page_wait_setting(case):
    a = PageActivity("10.1234/fixture", {"browser_stall_notify_after": 5,
                     "browser_page_wait_timeout": 15}, clock=lambda: case.now[0])
    a.observe(case.page)
    try:
        case.page.emit("request", navigation(case.page))
        case.now[0] = 14
        a.check()
        assert not attention()
        case.now[0] = 15
        a.check()
        assert attention()
    finally:
        a.close()


def test_download_bytes_and_browser_file_transfers_do_not_look_stalled(case):
    a, now = case.activity, case.now
    for second in range(0, 201, 20):
        now[0] = second
        a.check()
        assert not attention()
        a.progress()  # each received chunk
    with a.transfer():
        now[0] = 400
        a.check()
        assert not attention()
    now[0] = 429
    a.check()
    assert not attention()
    now[0] = 430
    a.check()
    assert attention()


def test_polling_logs_and_countdowns_do_not_count_as_workflow_progress(case):
    result = DownloadResult(doi="10.1234/fixture", status="failed")
    result._page_activity = case.activity
    d = PublisherBatchDownloader({})
    d._phase(result, "open")
    for second in range(31):
        case.now[0] = second
        d._phase(result, "open")
        d._event(result, "challenge_wait", f"automatic {second}")
        progress_reporter.update(phase="自动检查", deadline=1000 - second)
        case.activity.check()
    assert attention()
    d._event(result, "article_access_ready")
    assert not attention()


def test_setting_round_trip_and_invalid_value_do_not_modify_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    assert user_settings.current()["stalled"] == 30
    user_settings.save({"stalled": 45})
    assert config.load_config()["browser_stall_notify_after"] == 45
    assert user_settings.current()["stalled"] == 45
    for invalid in (-1, 0, 601, "abc", "1.5"):
        with pytest.raises(ValueError):
            user_settings.save({"stalled": invalid})
        assert user_settings.current()["stalled"] == 45


def test_request_watcher_reminds_without_a_browser_rpc_and_cleans_up(case):
    case.activity.close()
    d = PublisherBatchDownloader({"browser_stall_notify_after": 1})
    result = DownloadResult(doi="10.1234/fixture", status="failed")
    stop = d._start_user_watch(case.page, result)
    try:
        end = time.monotonic() + 3
        while not attention() and time.monotonic() < end:
            time.sleep(0.05)
        assert attention()
        assert result._page_activity.page is case.page
    finally:
        stop.set()
    assert result._page_activity.closed
    assert not attention()
    assert all(not handlers for handlers in case.page.handlers.values())


def test_streaming_collector_reports_byte_progress_before_finishing_a_file(case, tmp_path):
    from paper_search_carsi.adapters import SupplementLink
    from paper_search_carsi.engine import supplements

    a, now = case.activity, case.now
    data = b"file bytes" * 100

    def chunks():
        for _ in range(6):
            now[0] += 20
            a.check()
            assert not attention()
            yield data

    response = SimpleNamespace(status=200, ok=True, headers={}, chunks=chunks)
    request = SimpleNamespace(get=lambda *args, **kwargs: response)
    files = supplements.collect(request, [SupplementLink("https://fixture.example/data.zip")],
                                tmp_path, "10.1234/fixture", clock=lambda: now[0], activity=a.progress)
    assert now[0] == 120  # well beyond the reminder threshold, with actual bytes received
    assert files[0]["status"] == "saved"
    from pathlib import Path
    assert Path(files[0]["file"]).read_bytes() == data * 6
    assert not attention()

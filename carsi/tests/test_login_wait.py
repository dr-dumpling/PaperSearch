"""Human takeover preserves the remaining login budget, without reading inputs."""
from unittest.mock import Mock

import pytest

from paper_search_carsi import progress_reporter, progress_view
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.engine.login_wait import LoginWait


def test_one_input_preserves_budget_through_a_long_pause_then_resumes():
    clock = [1000.0]
    frame = Mock(evaluate=Mock(return_value=0))
    page = Mock(frames=[frame])
    wait = LoginWait(1180, lambda: clock[0])
    wait.observe(page, True)
    clock[0] += 10
    frame.evaluate.return_value = 1
    wait.observe(page, True)
    assert wait.paused
    clock[0] += 400  # no further typing is necessary
    assert wait.deadline - clock[0] == 170
    wait.observe(page, False)
    assert not wait.paused
    clock[0] += 169
    assert wait.deadline > clock[0]
    clock[0] += 1
    assert wait.deadline == clock[0]
    wait.close()


def test_an_untouched_login_still_expires_and_automatic_pages_cannot_take_over():
    clock = [1000.0]
    page = Mock(frames=[Mock(evaluate=Mock(return_value=0))])
    wait = LoginWait(1180, lambda: clock[0])
    wait.observe(page, True)
    clock[0] = 1180
    assert not wait.paused and wait.deadline == clock[0]
    wait.observe(page, False)
    wait.take_over()
    assert not wait.paused
    wait.close()


@pytest.mark.parametrize("ending", ["success", "exception"])
def test_capsule_takeover_removes_countdown_without_repeating_notification(tmp_path, monkeypatch, ending):
    from paper_search_carsi.browser import foreground
    monkeypatch.setenv("CARSI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(foreground, "show", Mock())
    progress_reporter.start_task("论文下载", total=1)
    clock = [1000.0]
    page = Mock(frames=[Mock(evaluate=Mock(return_value=0))])
    page.is_closed.return_value = False
    d = PublisherBatchDownloader({})
    result = DownloadResult(doi="10.1000/login", status="failed")
    try:
        with d._login_wait_budget(result, "_school_login_deadline", 1180, lambda: clock[0]) as wait:
            wait.observe(page, True)
            d._set_login_attention(result, "请在浏览器窗口完成机构登录", 1180, page=page)
            before = next(iter(progress_reporter.read_state()["attention"].values()))
            clock[0] += 10
            d._show_download_browser(page, result)
            assert wait.paused
            clock[0] += 100  # within the idle limit (the login wait, 180 s) the countdown stays off
            d._set_login_attention(result, result._login_attention, wait.deadline, page=page)
            state = progress_reporter.read_state()
            after = next(iter(state["attention"].values()))
            assert after["since"] == before["since"]
            assert "deadline" not in after
            assert progress_view.view(state, clock[0])["attention"]["remaining"] == ""
            assert wait.deadline - clock[0] == 170
            if ending == "exception":
                raise ValueError("fixture ended login")
    except ValueError as exc:
        assert ending == "exception" and str(exc) == "fixture ended login"
    assert result._login_wait is None and result._attention_page is None
    assert result._school_login_deadline == 1280
    assert progress_reporter.read_state()["attention"] == {}
    # The next login in this article inherits only the time used.
    assert d._school_login_deadline(result) == 1280


def test_a_stray_input_holds_the_login_only_for_the_idle_limit():
    # The user, 2026-11-11: a click on the login page and nobody there must not wait forever.
    clock = [1000.0]
    frame = Mock(evaluate=Mock(return_value=0))
    page = Mock(frames=[frame])
    wait = LoginWait(1180, lambda: clock[0], idle_limit=180)
    wait.observe(page, True)
    clock[0] += 10
    frame.evaluate.return_value = 1  # one click, then nothing
    wait.observe(page, True)
    assert wait.paused
    clock[0] += 179
    wait.observe(page, True)
    assert wait.paused  # still within the idle limit
    clock[0] += 1
    wait.observe(page, True)
    assert not wait.paused
    # The time since the click counts again: 170 s were left, 180 s have passed.
    assert wait.deadline <= clock[0]
    wait.close()


def test_typing_keeps_the_stop_going():
    clock = [1000.0]
    frame = Mock(evaluate=Mock(return_value=0))
    page = Mock(frames=[frame])
    wait = LoginWait(1180, lambda: clock[0], idle_limit=180)
    wait.observe(page, True)
    for typed in range(1, 6):  # an input every 100 s for 500 s
        clock[0] += 100
        frame.evaluate.return_value = typed
        wait.observe(page, True)
        assert wait.paused
    clock[0] += 179
    wait.observe(page, True)
    assert wait.paused and wait.deadline > clock[0]
    clock[0] += 1
    wait.observe(page, True)
    assert not wait.paused
    # Left when the stop began (80 s) minus the idle time since the last input (180 s).
    assert wait.deadline == clock[0] - 100
    wait.close()

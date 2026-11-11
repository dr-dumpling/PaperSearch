"""A quiet page is looked at before anyone is asked; only that look reminds the user."""
import logging
from collections import defaultdict
from types import SimpleNamespace

import pytest

from paper_search_carsi import progress_reporter
from paper_search_carsi.engine.page_activity import PageActivity


class Page:
    def __init__(self):
        self.main_frame = object()
        self.handlers = defaultdict(list)

    def on(self, event, handler):
        self.handlers[event].append(handler)

    def remove_listener(self, event, handler):
        self.handlers[event].remove(handler)


@pytest.fixture
def case(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="paper_search_carsi.engine.page_activity")
    monkeypatch.setenv("CARSI_DATA_DIR", str(tmp_path))
    progress_reporter.start_task("fixture", total=1)
    now = [0.0]
    activity = PageActivity("10.1234/fixture", {}, clock=lambda: now[0])
    activity.observe(Page())
    looks = []
    activity.on_idle = lambda: looks.append(now[0])
    yield SimpleNamespace(activity=activity, now=now, looks=looks)
    activity.close()


def attention():
    return progress_reporter.read_state()["attention"]


def test_a_quiet_interval_asks_for_one_look_and_reminds_nobody_by_itself(case):
    a, now = case.activity, case.now
    now[0] = 29
    a.check()
    assert not a.stalled() and case.looks == []
    now[0] = 30
    a.check()
    a.check()
    assert a.stalled() and case.looks == [30]
    assert not attention()  # the look decides


def test_the_look_reminds_once_and_progress_or_the_end_clears_it(case):
    a, now = case.activity, case.now
    now[0] = 30
    a.check()
    a.remind("页面可能需要你处理，请查看浏览器窗口")
    a.remind("页面可能需要你处理，请查看浏览器窗口")
    assert list(attention()) == [a.key]
    assert attention()[a.key]["message"] == "页面可能需要你处理，请查看浏览器窗口"
    now[0] = 40
    a.check()  # its own reminder is not another one's: the page is still quiet
    assert a.stalled() and list(attention()) == [a.key]
    a.progress()  # the page moved
    assert not attention() and not a.stalled()
    now[0] = 80
    a.check()
    a.remind("页面可能需要你处理，请查看浏览器窗口")
    assert list(attention()) == [a.key]
    a.close()
    assert not attention()


def test_another_reminder_for_the_paper_comes_first(case):
    a, now = case.activity, case.now
    progress_reporter.set_attention("school", "请登录学校", current="10.1234/fixture")
    now[0] = 100
    a.check()
    assert case.looks == []  # the school's login is the user's step already
    progress_reporter.clear_attention("school")
    now[0] = 130
    a.check()
    assert case.looks == [130]

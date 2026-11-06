"""A real login wait drives the capsule's needs-you state and clears it on exit."""
from unittest.mock import Mock

import pytest

from paper_search_carsi import progress_reporter, progress_view
from paper_search_carsi.engine import batch_login
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE


@pytest.mark.parametrize("user_step", ["school_login", "school_choice", "automatic"])
@pytest.mark.parametrize("ending", ["success", "timeout", "exception"])
def test_login_loop_attention_lifecycle(tmp_path, monkeypatch, user_step, ending):
    monkeypatch.setenv("CARSI_DATA_DIR", str(tmp_path))
    progress_reporter.start_task("论文下载", total=1)
    clock = [1000.0]
    monkeypatch.setattr(batch_login.time, "time", lambda: clock[0])
    monkeypatch.setattr(batch_login.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(batch_login, "settle", lambda *a: None)
    d = PublisherBatchDownloader({}, profile=ELSEVIER_PROFILE, login_timeout_sec=5)
    result = DownloadResult(doi="10.1016/fixture", status="failed")
    page = Mock(url="https://cas.school.example/login")
    page.frames = []
    for name in ("_dismiss_cookie_banners", "_click_sso_entry", "_click_openathens_entry", "_select_institution",
                 "_institution_pdf_entitlement_missing", "_challenge_shell", "_on_publisher_host",
                 "_is_idp_host", "_is_auth_page", "_is_challenge_page", "_return_from_login_site",
                 "_follow_federated_login_option", "_return_to_record_article_if_needed",
                 "_has_publisher_institution_session", "_looks_logged_out", "_is_success_article_url",
                 "_click_optional_continue", "_is_human_login_page"):
        setattr(d, name, Mock(return_value=False))
    d._title = Mock(return_value="School login")
    d._page_wait_over = Mock(side_effect=lambda page, since: (False, since))
    d._login_block_reason = Mock(return_value="")
    d._stuck_on_school_site = Mock(return_value="")
    d._idp_confirmation = Mock(return_value="")
    d._return_to_article_after_login = Mock()
    d._users_login_step = Mock(return_value=user_step != "automatic")
    d._login_wait_page = Mock(return_value=user_step)
    d._article_access_available = Mock(side_effect=lambda page: ending == "success" and clock[0] >= 1003)
    seen = []

    def observe(*args):
        if clock[0] >= 1002:
            seen.append(progress_reporter.read_state())
        if ending == "exception" and clock[0] >= 1003:
            raise RuntimeError("fixture cancelled the login")

    d._check_user_decision = observe
    if ending == "exception":
        with pytest.raises(RuntimeError, match="fixture cancelled"):
            d._complete_login_from_current_page(page, result)
    else:
        assert d._complete_login_from_current_page(page, result) is (ending == "success")
    assert seen
    for state in seen:
        view = progress_view.view(state, clock[0])
        if user_step == "automatic":
            assert state["attention"] == {}
        else:
            assert (view["mode"], view["tone"]) == ("attention", "warn")
            assert view["attention"]["remaining"]
    if user_step != "automatic":
        # Polling the same wait keeps its identity, so Notifier sends once.
        prompts = [next(iter(s["attention"].values())) for s in seen]
        assert len({p["since"] for p in prompts}) == 1
        assert all(p["deadline"] == 1005 for p in prompts)
    assert progress_reporter.read_state()["attention"] == {}

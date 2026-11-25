"""The PDF step's verification: not passed by the program's own steps, it ends without the wait on the user.

ba77bb4e (the user, 2026-11-25): the PDF step goes to the school login without the manual wait. The parameter went
with Bright Data in ead266c9 while the PDF step kept passing it, and every verification there ended as an unexpected
error (TypeError), found by the release candidate's browser tests."""
import time
from unittest.mock import Mock

from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader


def downloader(monkeypatch, clock):
    monkeypatch.setattr(time, "time", lambda: clock[0])
    d = PublisherBatchDownloader({})
    d._check_user_decision = Mock(return_value=False)
    d._automatic_challenge_step = Mock(return_value=False)
    d._snapshot = Mock()
    d._verification_attention = Mock()
    d._raise_on_publisher_access_blocked = Mock()
    d._challenge_shell = lambda _: True
    d._is_challenge_page = lambda _: True
    d._challenge_continues = lambda _: True
    return d


def page(clock):
    p = Mock(url="https://journal.example/doi/pdf/10.1000/test?__cf_chl_tk=1", frames=[])
    p.title.return_value = "Just a moment..."
    p.wait_for_timeout.side_effect = lambda ms: clock.__setitem__(0, clock[0] + ms / 1000)
    return p


def test_the_pdf_steps_verification_ends_where_the_wait_on_the_user_would_begin(monkeypatch):
    clock = [1000.0]
    d = downloader(monkeypatch, clock)
    p = page(clock)
    result = DownloadResult(doi="10.1000/test", status="failed")
    assert d._wait_for_challenge(p, result, deadline=1060, hand_over_only=True) is False
    states = [e["state"] for e in result.events]
    assert "challenge_manual_wait" not in states
    assert clock[0] < 1002  # no minute on the user
    assert result.challenge_type == "cloudflare"


def test_elsewhere_the_wait_on_the_user_begins_as_before(monkeypatch):
    clock = [1000.0]
    d = downloader(monkeypatch, clock)
    result = DownloadResult(doi="10.1000/test", status="failed")
    assert d._wait_for_challenge(page(clock), result, deadline=1005) is False
    assert "challenge_manual_wait" in [e["state"] for e in result.events]

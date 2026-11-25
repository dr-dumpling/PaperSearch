"""AWS WAF 的图片选择题模块：离线测试，不碰真浏览器与真服务。"""
from types import SimpleNamespace
from unittest.mock import Mock
import time

from paper_search_school.browser.challenge.handlers import aws_waf as awswaf
from paper_search_school.browser.challenge.services import solver

CONFIG = {"captcha_service": "yescaptcha", "captcha_key": "key-fixture",
          "captcha_service_url": "https://cn.yescaptcha.com"}


def page(grid=None, question="Choose all the buckets", screenshot=b"grid-png"):
    fake = Mock()
    fake.evaluate = Mock(return_value={"aws": True, "grid": grid, "question": question})
    fake.screenshot = Mock(return_value=screenshot)
    fake.mouse = Mock()
    fake._papersearch_grid_budget = None
    fake.locator.return_value.first.count.return_value = 1
    fake.locator.return_value.first.is_visible.return_value = True
    fake.locator.return_value.first.is_enabled.return_value = True
    return fake


def test_an_aws_waf_page_is_recognised_by_its_own_button(monkeypatch):
    fake = page()
    fake.evaluate = Mock(return_value={"aws": True})
    assert awswaf.find(fake) is True
    fake.evaluate = Mock(return_value={"aws": False})
    assert awswaf.find(fake) is False


def test_without_a_service_nothing_is_pressed(monkeypatch):
    fake = page()
    assert awswaf.solve(fake, {"captcha_service": "none"}) is False
    fake.locator.return_value.first.click.assert_not_called()


def test_the_picture_and_the_question_are_answered_with_clicks(monkeypatch):
    grid = {"x": 100.0, "y": 200.0, "width": 300.0, "height": 300.0}
    fake = page(grid=grid)
    cells = [Mock() for _ in range(9)]
    for cell in cells:
        cell.get_attribute.side_effect = lambda _name, cell=cell: "true" if cell.click.called else "false"
    confirm = fake.locator.return_value.first
    fake.locator = Mock(side_effect=lambda selector: SimpleNamespace(
        all=Mock(return_value=cells), first=confirm))
    # The page leaves the puzzle once the answer has been clicked and confirmed.
    fake.evaluate = Mock(side_effect=lambda _js: {
        "aws": not (any(cell.click.called for cell in cells) and confirm.click.called), "ready": True,
        "grid": grid, "question": "Choose all the buckets", "title": "Let's confirm you are human"})
    asked = []

    def solve_grid(image, question, config, **kwargs):
        asked.append((image, question))
        return [(0.0, 1.0), (2.0, 2.0)]

    monkeypatch.setattr(solver, "solve_grid", solve_grid)
    assert awswaf.solve(fake, CONFIG) is True
    assert asked == [(b"grid-png", "Choose all the buckets")]
    assert cells[3].click.call_count == 1  # column 0, row 1
    assert cells[8].click.call_count == 1  # column 2, row 2
    assert confirm.click.call_count == 1
    fake.locator.assert_any_call("#amzn-btn-verify-internal")


def test_invalid_image_coordinates_do_not_click_a_clamped_edge_cell():
    fake = page()
    cells = [Mock() for _ in range(9)]
    fake.locator.return_value.all.return_value = cells
    assert not awswaf._click_points(fake, {"x": 0, "y": 0, "width": 320, "height": 320},
                                    [(53, 53), (532, 532)])
    assert not any(cell.click.called for cell in cells)


def test_the_engine_never_sends_an_idp_puzzle_to_the_service(monkeypatch):
    from paper_search_school.browser.challenge.local import interaction
    from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader

    downloader = PublisherBatchDownloader({**CONFIG, "idp_domains": ["school.example"]})
    fake = page()
    fake.url = "https://cas.school.example/login"
    monkeypatch.setattr(interaction, "needs_manual_verification", lambda _: True)
    monkeypatch.setattr(interaction, "verification_widget", lambda *a, **k: "AWS WAF")
    monkeypatch.setattr(interaction, "challenge_kind", lambda _: "awswaf")
    solve = Mock()
    monkeypatch.setattr(awswaf, "solve", solve)
    result = DownloadResult(doi="10.1000/example", status="failed")
    assert downloader._automatic_challenge_step(fake, result, {}, time.time() + 60) is False
    solve.assert_not_called()

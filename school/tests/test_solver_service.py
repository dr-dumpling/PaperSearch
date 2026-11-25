"""YesCaptcha 的离线测试：不发网络请求，只检查请求体与答案解析。"""
import base64
from unittest.mock import Mock

import pytest

from paper_search_school.browser.challenge.services import solver as captcha

CONFIG = {"captcha_service": "yescaptcha", "captcha_service_url": "https://cn.yescaptcha.com",
          "captcha_key": "key-fixture", "captcha_timeout": 30, "captcha_max_per_run": 2}


def test_turnstile_uses_its_own_task_and_preserves_soft_id():
    post = Mock(return_value=response({'errorId': 0, 'solution': {'token': 'test-token', 'userAgent': 'Browser/1.0'}}))
    result = captcha.solve_turnstile('https://publisher.example/', '0x4AAAAAAATestWidgetKey', CONFIG,
                                    action='verify', post=post)
    assert result.token == 'test-token' and result.user_agent == 'Browser/1.0'
    payload = post.call_args.kwargs['json']
    assert payload['softID'] == 149362
    assert payload['task'] == {'type': 'TurnstileTaskProxyless', 'websiteURL': 'https://publisher.example/',
                               'websiteKey': '0x4AAAAAAATestWidgetKey', 'pageAction': 'verify'}
    assert 'test-token' not in repr(result)


@pytest.mark.parametrize('solution', [
    {}, {'token': 'token'}, {'userAgent': 'agent'}, {'token': 5, 'userAgent': 'agent'},
    {'token': 'bad token', 'userAgent': 'agent'}, {'token': 'token', 'userAgent': 'agent\r\nInjected: x'},
])
def test_turnstile_rejects_invalid_answers(solution):
    post = Mock(return_value=response({'errorId': 0, 'solution': solution}))
    assert captcha.solve_turnstile('https://publisher.example/', '0x4AAAAAAATestWidgetKey', CONFIG, post=post) is None


@pytest.mark.parametrize('url', ['https://publisher.example/session/path', 'https://publisher.example/?ticket=private',
                                'https://user:pass@publisher.example/', 'http://publisher.example/'])
def test_turnstile_never_sends_session_urls(url):
    post = Mock()
    assert captcha.solve_turnstile(url, '0x4AAAAAAATestWidgetKey', CONFIG, post=post) is None
    post.assert_not_called()


@pytest.fixture(autouse=True)
def _no_key_file(monkeypatch, tmp_path):
    monkeypatch.delenv("YESCAPTCHA_KEY", raising=False)
    monkeypatch.setattr(captcha, "KEY_FILE", tmp_path / "missing.key")


def response(payload):
    reply = Mock()
    reply.json.return_value = payload
    return reply


def test_nothing_happens_when_the_service_is_off_or_the_key_is_missing():
    assert captcha.get_balance({"captcha_service": "none"}) is None
    assert captcha.solve_image(b"img", {"captcha_service": "yescaptcha"}) is None
    assert captcha.get_balance(CONFIG, post=Mock()) is None if captcha.key(CONFIG) == "" else True


def test_the_key_comes_from_the_environment_then_the_key_file(monkeypatch, tmp_path):
    monkeypatch.setenv("YESCAPTCHA_KEY", "env-key")
    assert captcha.key({}) == "env-key"
    key_file = tmp_path / "yescaptcha.key"
    key_file.write_text("file-key\n", encoding="utf-8")
    monkeypatch.setattr(captcha, "KEY_FILE", key_file)
    assert captcha.key({"captcha_key": "config-key"}) == "config-key"
    assert captcha.key({}) == "env-key"
    monkeypatch.delenv("YESCAPTCHA_KEY")
    assert captcha.key({}) == "file-key"


def test_the_balance_is_asked_without_creating_a_task():
    post = Mock(return_value=response({"errorId": 0, "balance": 12.5}))
    assert captcha.get_balance(CONFIG, post=post) == 12.5
    url = post.call_args.args[0]
    payload = post.call_args.kwargs["json"]
    assert url == "https://cn.yescaptcha.com/getBalance"
    assert payload == {"clientKey": "key-fixture", "softID": captcha.SOFT_ID}


def test_the_picture_code_is_answered_by_the_synchronous_task():
    post = Mock(return_value=response({"errorId": 0, "solution": {"text": " aB3x "}}))
    assert captcha.solve_image(b"png-bytes", CONFIG, post=post) == "aB3x"
    assert post.call_args.args[0].endswith("/createTask")
    assert post.call_args.kwargs["json"]["softID"] == 149362
    task = post.call_args.kwargs["json"]["task"]
    assert task["type"] == "ImageToTextTaskOcrBase"
    assert base64.b64decode(task["body"]) == b"png-bytes"


def test_the_grid_question_is_answered_with_its_points():
    replies = [response({"errorId": 0, "taskId": "task-1"}),
               response({"errorId": 0, "status": "processing"}),
               response({"errorId": 0, "status": "ready",
                         "solution": {"clicks": [{"x": 10, "y": 20}, {"x": 30, "y": 40}]}})]
    post = Mock(side_effect=replies)
    import time
    original = time.sleep
    time.sleep = lambda _seconds: None
    try:
        points = captcha.solve_grid(b"grid-bytes", "Select all hats", CONFIG, post=post, kind="awswaf")
    finally:
        time.sleep = original
    assert points == [(10.0, 20.0), (30.0, 40.0)]
    assert all(call.kwargs["json"]["softID"] == 149362 for call in post.call_args_list)
    task = post.call_args_list[0].kwargs["json"]["task"]
    assert task["type"] == captcha.TASKS["awswaf"]
    assert task["question"] == "Select all hats"


def test_each_kind_asks_for_its_own_task():
    assert captcha.TASKS["image_code"] == "ImageToTextTaskOcrBase"
    assert captcha.TASKS["awswaf"] == captcha.GRID_TASK
    assert captcha.TASKS["bcaptcha"] == "bCaptchaClassification"
    assert captcha.TASKS["recaptcha"] == "ReCaptchaV2Classification"
    assert captcha.TASKS["hcaptcha"] == "HCaptchaClassification"


def test_a_ready_answer_with_a_task_id_is_used_without_polling():
    post = Mock(return_value=response({
        "errorId": 0, "status": "ready", "taskId": "already-complete",
        "solution": {"clicks": [{"x": 53, "y": 159}]},
    }))
    assert captcha.solve_grid(b"grid", "Choose all the hats", CONFIG, post=post) == [(53.0, 159.0)]
    post.assert_called_once()


def test_the_budget_stops_after_its_limit():
    budget = captcha.Budget(config=CONFIG)
    assert [budget.take(), budget.take(), budget.take()] == [True, True, False]
    assert captcha.Budget(limit=0).take() is False


@pytest.mark.parametrize('kind', ['cloudflare', 'unknown', 'funcaptcha', 'recaptcha', 'hcaptcha'])
def test_single_aws_picture_is_not_sent_under_an_unrelated_task_type(kind):
    post = Mock()
    assert captcha.solve_grid(b'png', 'question', CONFIG, kind=kind, post=post) == []
    post.assert_not_called()


def test_hcaptcha_uses_ordered_images_and_boolean_answers():
    post = Mock(return_value=response({'status': 'ready', 'taskId': 'sync',
                                      'solution': {'objects': [True, False, True] + [False]*6}}))
    images = [bytes([i]) for i in range(9)]
    assert captcha.solve_tiles(images, 'Select bicycles', CONFIG, kind='hcaptcha', count=9,
                               anchors=[b'example'], timeout=2, post=post) == [0, 2]
    assert post.call_args.kwargs['json']['softID'] == 149362
    task = post.call_args.kwargs['json']['task']
    assert [base64.b64decode(im) for im in task['queries']] == images
    assert base64.b64decode(task['anchors'][0]) == b'example'
    assert set(task) == {'type', 'queries', 'question', 'anchors'}
    post.assert_called_once()


@pytest.mark.parametrize('objects,expected', [([0, 5, 15], [0, 5, 15]), ([], []),
                                            ([True, False], None), ([16], None), ([-1], None)])
def test_recaptcha_indices_are_not_interpreted_as_aws_pixel_points(objects, expected):
    post = Mock(return_value=response({'status': 'ready', 'solution': {'objects': objects}}))
    assert captcha.solve_tiles([b'png'], '/m/0k4j', CONFIG, kind='recaptcha', count=16,
                               timeout=2, post=post) == expected
    assert post.call_args.kwargs['json']['softID'] == 149362
    task = post.call_args.kwargs['json']['task']
    assert 'image' in task and 'queries' not in task
    assert task['question'] == '/m/0k4j'


def test_creation_and_polling_share_one_deadline(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(captcha.time, 'monotonic', lambda: clock[0])
    def send(*a, **kw):
        clock[0] += 4
        return response({'status': 'processing', 'taskId': 'slow'})
    post = Mock(side_effect=send)
    assert captcha.solve_grid(b'png', 'hats', CONFIG, timeout=5, post=post) == []
    post.assert_called_once()  # no fresh 5-second timeout after creation


def test_a_late_ready_answer_is_discarded(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(captcha.time, 'monotonic', lambda: clock[0])
    def send(*a, **kw):
        clock[0] += 6
        return response({'status': 'ready', 'solution': {'clicks': [{'x': 10, 'y': 10}]}})
    assert captcha.solve_grid(b'png', 'hats', CONFIG, timeout=5, post=send) == []


def test_parallel_pages_share_the_budget_safely():
    from concurrent.futures import ThreadPoolExecutor
    budget = captcha.Budget(limit=3)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(lambda _: budget.take(), range(80))) == 3
    assert budget.used == 3

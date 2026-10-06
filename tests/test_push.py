import httpx

from app import service
from engine import push, report


def _clear(monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FEISHU_WEBHOOK", "FEISHU_SECRET", "WECOM_WEBHOOK"):
        monkeypatch.delenv(k, raising=False)


def test_digest_is_short_numberlocked_and_says_read_only():
    rv = service.review("B")
    md = report.build(rv)["markdown"]
    t = push.summary_text(rv, md, "https://example.invalid/loop", "en")
    assert len(t) < 3800 and "Read-only" in t and "Priority finding" in t and "https://example.invalid/loop" in t
    z = push.summary_text(rv, report.build(rv, None, "zh")["markdown"], None, "zh")
    assert "只读" in z


def test_no_channel_configured_is_a_dry_run(monkeypatch):
    _clear(monkeypatch)
    assert push.send_weekly("hello") == {"none": "no channel configured (dry run)"}


def test_each_channel_posts_the_right_shape_and_never_leaks_the_secret(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("FEISHU_WEBHOOK", "https://open.feishu.cn/hook/abc")
    monkeypatch.setenv("FEISHU_SECRET", "sek")
    monkeypatch.setenv("WECOM_WEBHOOK", "https://qyapi.weixin.qq.com/hook/xyz")
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen[str(req.url.host)] = req.read().decode()
        return httpx.Response(200, json={"ok": True, "code": 0, "errcode": 0})
    out = push.send_weekly("digest text", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert out == {"telegram": "sent", "feishu": "sent", "wecom": "sent"}
    assert '"chat_id":"42"' in seen["api.telegram.org"].replace(" ", "") and '"msg_type":"text"' in seen["open.feishu.cn"].replace(" ", "")
    assert '"sign"' in seen["open.feishu.cn"] and '"msgtype":"markdown"' in seen["qyapi.weixin.qq.com"].replace(" ", "")
    assert "sek" not in seen["open.feishu.cn"]            # the signing secret itself is never sent


def test_errors_are_reported_without_the_url(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-secret")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")

    def handler(req):
        return httpx.Response(500)
    out = push.send_weekly("x", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert out["telegram"].startswith("error") and "tok-secret" not in out["telegram"]

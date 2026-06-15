"""Tests for the SMS layer (whitelist + sending)."""

from __future__ import annotations

from types import SimpleNamespace

from app import sms


def test_normalize_strips_formatting_to_last_ten_digits():
    assert sms.normalize_number("+1 (206) 555-0123") == "2065550123"
    assert sms.normalize_number("206.555.0123") == "2065550123"
    assert sms.normalize_number("12065550123") == "2065550123"


def test_numbers_match_across_formats():
    assert sms.numbers_match("+12065550123", "(206) 555-0123")
    assert not sms.numbers_match("+12065550123", "+12065559999")


class FakeTwilio:
    def __init__(self):
        self.sent = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, body, from_, to, media_url=None):
        self.sent.append({"body": body, "from_": from_, "to": to, "media_url": media_url})
        return SimpleNamespace(sid="SM123")


def make_client():
    fake = FakeTwilio()
    client = sms.SmsClient(
        account_sid="AC",
        auth_token="tok",
        from_number="+12065550123",
        my_number="+12065559876",
        client=fake,
    )
    return client, fake


def test_only_my_number_is_allowed():
    client, _ = make_client()
    assert client.is_allowed("+1 (206) 555-9876")
    assert not client.is_allowed("+12065550000")


def test_send_uses_from_and_my_number():
    client, fake = make_client()
    client.send("hey, hw4 is due tue 11:59pm")
    assert fake.sent == [
        {
            "body": "hey, hw4 is due tue 11:59pm",
            "from_": "+12065550123",
            "to": "+12065559876",
            "media_url": None,
        }
    ]


def test_whatsapp_channel_prefixes_from_and_to():
    fake = FakeTwilio()
    client = sms.SmsClient(
        account_sid="AC",
        auth_token="tok",
        from_number="+12065550123",
        my_number="+12065559876",
        client=fake,
        channel="whatsapp",
        whatsapp_from="whatsapp:+14155238886",
    )
    client.send("hey, hw4 is due tue 11:59pm")
    assert fake.sent == [
        {
            "body": "hey, hw4 is due tue 11:59pm",
            "from_": "whatsapp:+14155238886",
            "to": "whatsapp:+12065559876",
            "media_url": None,
        }
    ]
    # The whitelist still recognizes a "whatsapp:"-prefixed inbound number.
    assert client.is_allowed("whatsapp:+12065559876")


def test_send_attaches_media_url_to_first_message():
    client, fake = make_client()
    client.send("here's your file:", media_url=["https://example.com/file/abc"])
    assert fake.sent == [
        {
            "body": "here's your file:",
            "from_": "+12065550123",
            "to": "+12065559876",
            "media_url": ["https://example.com/file/abc"],
        }
    ]


def _whatsapp_client():
    fake = FakeTwilio()
    return sms.SmsClient(
        account_sid="AC", auth_token="tok", from_number="+12065550123",
        my_number="+12065559876", client=fake, channel="whatsapp",
        whatsapp_from="whatsapp:+14155238886",
    )


def test_send_typing_posts_the_indicator(monkeypatch):
    captured = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"success": True}

    def fake_post(url, auth=None, data=None, timeout=None):
        captured.update(url=url, auth=auth, data=data)
        return Resp()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    assert _whatsapp_client().send_typing("SMabc") is True
    assert captured["url"].endswith("/Indicators/Typing.json")
    assert captured["auth"] == ("AC", "tok")
    assert captured["data"] == {"messageId": "SMabc", "channel": "whatsapp"}


def test_send_typing_is_a_noop_off_whatsapp():
    client, _ = make_client()  # channel defaults to "sms"
    assert client.send_typing("SMabc") is False


def test_send_typing_swallows_errors(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    import httpx
    monkeypatch.setattr(httpx, "post", boom)
    assert _whatsapp_client().send_typing("SMabc") is False


def test_send_splits_overlong_messages():
    client, fake = make_client()
    long_text = "x" * 700  # > one SMS segment limit we set
    client.send(long_text)
    # Sent as more than one message, each within the limit.
    assert len(fake.sent) > 1
    assert all(len(m["body"]) <= sms.MAX_SMS_LEN for m in fake.sent)
    assert "".join(m["body"] for m in fake.sent) == long_text

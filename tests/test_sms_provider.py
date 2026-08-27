"""پاسخ‌خوانیِ پنل کاوه‌نگار — بدون تماس شبکه.

پیش از این، تنها تابعی که پول واقعی خرج می‌کرد `# pragma: no cover` داشت و صفر
تست. مهم‌ترین تستِ این فایل
`test_http_200_with_an_error_body_is_a_failure` است: کاوه‌نگار خطاهای واقعی را
با HTTP ۲۰۰ برمی‌گرداند، و قاعده‌ی قدیمی (`status_code == 200`) آن‌ها را «موفق»
می‌شمرد.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.execution.audience import RenderedMessage  # noqa: E402
from mktcore.execution.providers import (  # noqa: E402
    KavenegarProvider,
    parse_kavenegar_response,
)

_OK_BODY = {
    "return": {"status": 200, "message": "تایید شد"},
    "entries": [{
        "messageid": 8792343, "status": 1, "statustext": "در صف ارسال",
        "receptor": "09121234567", "cost": 120,
    }],
}
_ERR_BODY = {"return": {"status": 411, "message": "دریافت کننده نامعتبر است"},
             "entries": None}
_CREDIT_BODY = {"return": {"status": 418, "message": "اعتبار شما کافی نیست"},
                "entries": None}


# ═══════════════════════════════════════════ پارس کردن پاسخ
def test_successful_response_is_recognised():
    ok, note, message_id = parse_kavenegar_response(200, _OK_BODY)
    assert ok is True
    assert message_id == "8792343"
    assert "صف" in note


def test_http_200_with_an_error_body_is_a_failure():
    """قاعده‌ی قدیمی این را «ارسال شد» می‌شمرد. مهم‌ترین تستِ این فایل."""
    ok, note, message_id = parse_kavenegar_response(200, _ERR_BODY)
    assert ok is False, "HTTP ۲۰۰ با خطای داخلی نباید موفق شمرده شود"
    assert message_id is None
    assert "411" in note
    assert "دریافت کننده نامعتبر" in note


def test_insufficient_credit_is_a_failure_with_a_readable_reason():
    ok, note, _mid = parse_kavenegar_response(200, _CREDIT_BODY)
    assert ok is False
    assert "اعتبار" in note


def test_non_200_http_is_a_failure():
    ok, note, _mid = parse_kavenegar_response(503, None)
    assert ok is False
    assert "503" in note


def test_unparsable_body_is_a_failure():
    ok, note, _mid = parse_kavenegar_response(200, "not json")
    assert ok is False
    assert "قابل خواندن" in note


def test_ok_status_without_entries_is_a_failure():
    """وضعیت موفق ولی بدون entry یعنی چیزی در صف نرفته."""
    ok, note, _mid = parse_kavenegar_response(
        200, {"return": {"status": 200, "message": "ok"}, "entries": []},
    )
    assert ok is False
    assert "ثبت نکرد" in note


def test_missing_message_id_still_counts_as_sent():
    """نبودِ شناسه نباید ارسالِ موفق را ناموفق کند — فقط پیگیری را سخت می‌کند."""
    ok, _note, message_id = parse_kavenegar_response(
        200, {"return": {"status": 200}, "entries": [{"statustext": "ارسال شد"}]},
    )
    assert ok is True
    assert message_id is None


# ═══════════════════════════════════ ارسال با کلاینت ساختگی
def _provider(handler) -> KavenegarProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return KavenegarProvider("test-key", "10008", client=client)


def _messages(n: int = 2) -> list[RenderedMessage]:
    return [
        RenderedMessage(customer_id=f"C{i}", phone=f"+98912000000{i}", text="سلام")
        for i in range(n)
    ]


def test_send_counts_success_from_the_body_not_the_status_code():
    provider = _provider(lambda _req: httpx.Response(200, json=_ERR_BODY))
    result = provider.send(_messages(2))
    assert result.sent == 0
    assert result.failed == 2
    assert all("خطا" in d["وضعیت"] for d in result.details)


def test_send_records_the_message_id_on_success():
    provider = _provider(lambda _req: httpx.Response(200, json=_OK_BODY))
    result = provider.send(_messages(1))
    assert result.sent == 1
    assert result.details[0]["شناسه_پیام"] == "8792343"


def test_send_posts_receptor_sender_and_message():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json=_OK_BODY)

    _provider(handler).send([
        RenderedMessage(customer_id="C1", phone="+989121234567", text="متن آزمایشی"),
    ])
    assert seen[0]["receptor"] == "+989121234567"
    assert seen[0]["message"] == "متن آزمایشی"
    assert seen[0]["sender"] == "10008"


def test_a_network_error_fails_only_that_message():
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("شبکه قطع است")
        return httpx.Response(200, json=_OK_BODY)

    result = _provider(handler).send(_messages(2))
    assert result.sent == 1
    assert result.failed == 1
    assert result.total == 2


def test_message_without_a_phone_is_failed_and_reported():
    provider = _provider(lambda _req: httpx.Response(200, json=_OK_BODY))
    result = provider.send([RenderedMessage(customer_id="C1", phone=None, text="س")])
    assert result.sent == 0
    assert result.failed == 1
    assert len(result.details) == 1, "شمارش و جزئیات نباید از هم بیفتند"


def test_result_is_never_marked_dry_run():
    provider = _provider(lambda _req: httpx.Response(200, json=_OK_BODY))
    assert provider.send(_messages(1)).dry_run is False


@pytest.mark.parametrize("body", [_ERR_BODY, _CREDIT_BODY])
def test_failed_sends_carry_no_message_id(body):
    provider = _provider(lambda _req: httpx.Response(200, json=body))
    result = provider.send(_messages(1))
    assert result.details[0]["شناسه_پیام"] is None

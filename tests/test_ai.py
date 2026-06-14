"""تست لایه‌ی هوش مصنوعی بدون فراخوانی شبکه (کلاینت ماک‌شده)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from mktcore.ai.metrics_payload import build_payload, payload_to_json
from mktcore.ai.schemas import Recommendation, StrategyReport
from mktcore.ai.strategist import generate_strategy
from mktcore.ingest.cleaning import clean_frame
from mktcore.ingest.mapper import SchemaMapper
from mktcore.pipeline import run_analysis


def _bundle(raw_sales):
    mapper = SchemaMapper()
    std = mapper.apply(raw_sales, mapper.auto_detect(raw_sales).mapping)
    return run_analysis(clean_frame(std), horizon=4)


def test_payload_is_compact_and_deterministic(raw_sales):
    bundle = _bundle(raw_sales)
    payload = build_payload(bundle)
    js = payload_to_json(payload)

    # قطعی بودن: سریال‌سازی دوباره یکسان است
    assert js == payload_to_json(build_payload(bundle))
    # کلیدهای مرتب
    assert json.dumps(json.loads(js), ensure_ascii=False, sort_keys=True) == js
    # بدون DataFrame خام — همه‌ی مقادیر JSON-سریال‌پذیرند و فشرده‌اند
    assert "kpi" in payload
    assert "پیش‌بینی" in payload
    assert "تارگت" in payload
    # حجم معقول (نه داده‌ی خام)
    assert len(js) < 20000


class _FakeMessages:
    def __init__(self, report: StrategyReport):
        self._report = report
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self._report, content=[])


class _FakeClient:
    def __init__(self, report: StrategyReport):
        self.messages = _FakeMessages(report)


def test_strategist_with_mock(raw_sales):
    bundle = _bundle(raw_sales)
    canned = StrategyReport(
        executive_summary="فروش در مسیر رشد است.",
        target_rationale="سناریوی متعادل توصیه می‌شود.",
        recommendations=[
            Recommendation(
                title="تقویت کانال وب‌سایت",
                priority="بالا",
                rationale="بیشترین سهم درآمد.",
                expected_impact="افزایش ۱۰٪ فروش",
                effort="متوسط",
            )
        ],
        risks=["وابستگی به یک کانال"],
    )
    fake = _FakeClient(canned)
    report = generate_strategy(bundle, client=fake, model="claude-opus-4-8")

    assert isinstance(report, StrategyReport)
    assert report.recommendations[0].title == "تقویت کانال وب‌سایت"

    # بررسی پارامترهای فراخوانی مدل
    call = fake.messages.calls[0]
    assert call["model"] == "claude-opus-4-8"
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"]["effort"]
    assert call["output_format"] is StrategyReport
    # پرامپت سیستم با cache_control علامت خورده
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}

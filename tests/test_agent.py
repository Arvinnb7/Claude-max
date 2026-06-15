"""تست لایه‌ی کمپین (مدل ماک) و اجرای پیامکی (dry-run، بدون شبکه)."""

from __future__ import annotations

from types import SimpleNamespace

from mktcore.ai.campaign import generate_campaigns
from mktcore.ai.metrics_payload import build_payload, payload_to_json
from mktcore.ai.schemas import AudienceCampaign, CampaignPlan, ChannelMessage, WeeklyAction
from mktcore.execution import build_audience, render_messages, send_campaign
from mktcore.execution.audience import render_template
from mktcore.ingest.cleaning import clean_frame
from mktcore.ingest.mapper import SchemaMapper
from mktcore.pipeline import run_analysis


def _bundle_and_df(raw):
    mapper = SchemaMapper()
    std = mapper.apply(raw, mapper.auto_detect(raw).mapping)
    clean = clean_frame(std)
    return run_analysis(clean, horizon=4), clean


def test_payload_includes_advanced(raw_sales):
    bundle, _ = _bundle_and_df(raw_sales)
    payload = build_payload(bundle)
    # تحلیل‌های جدید باید در payload باشند
    assert "محصولات" in payload
    assert "محصولات_مکمل" in payload
    assert "عملکرد" in payload
    assert "تأمین_کالا" in payload
    js = payload_to_json(payload)
    assert js == payload_to_json(build_payload(bundle))  # قطعی


class _FakeMessages:
    def __init__(self, plan):
        self.plan = plan
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self.plan, content=[])


class _FakeClient:
    def __init__(self, plan):
        self.messages = _FakeMessages(plan)


def test_generate_campaigns_with_mock(raw_sales):
    bundle, _ = _bundle_and_df(raw_sales)
    plan = CampaignPlan(
        summary="کمپین فعال‌سازی مجدد",
        audiences=[
            AudienceCampaign(
                segment_name="در معرض ریزش",
                audience_definition="مشتریانی که بیش از ۹۰ روز خرید نکرده‌اند",
                objective="فعال‌سازی مجدد",
                offer="۲۰٪ تخفیف",
                channels=[
                    ChannelMessage(channel="پیامک", body="سلام {نام}، {تخفیف} تخفیف ویژه!",
                                   timing="پنجشنبه عصر", personalization_vars=["نام", "تخفیف"]),
                    ChannelMessage(channel="تماس تلفنی", body="تماس فعال‌سازی",
                                   call_script="سلام، از طرف ...", timing="صبح"),
                ],
                success_kpi="نرخ بازگشت",
            )
        ],
        weekly_actions=[WeeklyAction(day="شنبه", focus="آماده‌سازی", actions=["تهیه لیست"])],
    )
    report = generate_campaigns(bundle, client=_FakeClient(plan), model="claude-opus-4-8")
    assert isinstance(report, CampaignPlan)
    assert report.audiences[0].channels[0].channel == "پیامک"


def test_render_template():
    out = render_template("سلام {نام}، {محصول} با {تخفیف}", {"نام": "علی", "محصول": "پرو"})
    assert "علی" in out and "پرو" in out
    # متغیر ناموجود دست‌نخورده می‌ماند
    assert "{تخفیف}" in out


def test_build_audience_and_dry_run(raw_sales):
    bundle, df = _bundle_and_df(raw_sales)
    recips = build_audience(bundle, "سررسیدشده", df=df, limit=20)
    assert len(recips) > 0
    # تلفن از داده استخراج شده
    assert any(r.phone for r in recips)

    msgs = render_messages("سلام {نام}، پیشنهاد ما: {سبد_پیشنهادی}", recips)
    assert all("سلام" in m.text for m in msgs)

    result = send_campaign(msgs, dry_run=True)
    assert result.dry_run is True
    assert result.total == len(msgs)
    assert result.sent >= 1  # حداقل یک گیرنده‌ی دارای تلفن

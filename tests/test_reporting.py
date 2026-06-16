"""تست تولید گزارش Markdown و HTML/PDF."""

from __future__ import annotations

import pytest

from mktcore.ai.schemas import Recommendation, StrategyReport
from mktcore.ingest.cleaning import clean_frame
from mktcore.ingest.mapper import SchemaMapper
from mktcore.pipeline import run_analysis
from mktcore.reporting.markdown_report import build_markdown
from mktcore.reporting.pdf_report import render_html, weasyprint_available


@pytest.fixture
def bundle(raw_sales):
    mapper = SchemaMapper()
    std = mapper.apply(raw_sales, mapper.auto_detect(raw_sales).mapping)
    return run_analysis(clean_frame(std), horizon=4)


@pytest.fixture
def strategy():
    return StrategyReport(
        executive_summary="فروش رو به رشد است.",
        target_rationale="سناریوی متعادل پیشنهاد می‌شود.",
        recommendations=[
            Recommendation(title="کمپین وفاداری", priority="بالا",
                           rationale="نرخ تکرار پایین.", expected_impact="رشد ۸٪", effort="متوسط")
        ],
        risks=["تمرکز فروش روی یک منطقه"],
    )


def test_markdown_has_persian_sections(bundle, strategy):
    md = build_markdown(bundle, strategy)
    assert "# گزارش جامع تحلیل فروش و استراتژی مارکتینگ" in md
    assert "## شاخص‌های کلیدی عملکرد" in md
    assert "## تارگت پیشنهادی" in md
    assert "## استراتژی مارکتینگ" in md
    assert "کمپین وفاداری" in md
    # بخش‌های پیشرفته‌ی جدید
    assert "## محصولات پرفروش و تحلیل ABC" in md
    assert "## چرخه‌ی خرید محصولات" in md


def test_markdown_without_strategy(bundle):
    md = build_markdown(bundle)
    assert "## شاخص‌های کلیدی عملکرد" in md
    assert "استراتژی مارکتینگ (تحلیل مدیر مارکتینگ)" not in md


def test_render_html(bundle, strategy):
    html = render_html(bundle, strategy)
    assert 'dir="rtl"' in html
    assert "استراتژی مارکتینگ" in html
    assert "کمپین وفاداری" in html


def test_pdf_when_available(bundle, strategy):
    if not weasyprint_available():
        pytest.skip("WeasyPrint نصب نیست")
    from mktcore.ai.schemas import AudienceCampaign, CampaignPlan, ChannelMessage
    from mktcore.reporting.pdf_report import build_pdf

    campaign = CampaignPlan(
        summary="کمپین آزمایشی",
        audiences=[AudienceCampaign(
            segment_name="تست", audience_definition="—", objective="—", offer="—",
            success_kpi="—",
            channels=[ChannelMessage(channel="پیامک", body="سلام {نام}", timing="عصر")],
        )],
    )
    pdf = build_pdf(bundle, strategy, campaign)
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000
    assert pdf[:4] == b"%PDF"

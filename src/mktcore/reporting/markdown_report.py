"""تولید گزارش Markdown فارسی از متریک‌ها و استراتژی هوش مصنوعی."""

from __future__ import annotations

import datetime as _dt
from typing import TYPE_CHECKING

from ..config import get_settings
from ..locale_fa import format_number_fa, to_jalali

if TYPE_CHECKING:
    from ..ai.schemas import StrategyReport
    from ..pipeline import MetricsBundle


def _fmt(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{format_number_fa(value)}{suffix}"


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}٪"


def build_markdown(bundle: MetricsBundle, strategy: StrategyReport | None = None) -> str:
    """ساخت گزارش کامل Markdown (فارسی، RTL با راهنمای جهت)."""
    s = get_settings()
    cur = s.mkt_currency
    k = bundle.kpis
    lines: list[str] = []

    lines.append("# گزارش تحلیل فروش و استراتژی مارکتینگ\n")
    lines.append(f"تاریخ تولید گزارش: {to_jalali(_dt.date.today())}\n")

    # خلاصه‌ی KPI
    lines.append("## شاخص‌های کلیدی عملکرد\n")
    lines.append("| شاخص | مقدار |")
    lines.append("|---|---|")
    lines.append(f"| درآمد کل | {_fmt(k.total_revenue)} {cur} |")
    lines.append(f"| تعداد سفارش | {_fmt(k.n_orders)} |")
    lines.append(f"| تعداد مشتری | {_fmt(k.n_customers)} |")
    lines.append(f"| میانگین ارزش سفارش | {_fmt(k.aov)} {cur} |")
    lines.append(f"| رشد ماهانه | {_pct(k.mom_growth)} |")
    lines.append(f"| رشد سالانه | {_pct(k.yoy_growth)} |")
    lines.append(f"| نرخ مشتری تکراری | {_pct(k.repeat_rate)} |")
    lines.append(f"| حاشیه‌ی سود ناخالص | {_pct(k.gross_margin)} |\n")

    # تارگت
    if bundle.targets is not None:
        lines.append("## تارگت پیشنهادی\n")
        lines.append(f"مجموع پیش‌بینی برای {bundle.targets.horizon} دوره‌ی آینده: "
                     f"**{_fmt(bundle.targets.forecast_total)} {cur}**\n")
        lines.append("| سناریو | مجموع هدف | رشد نسبت به پیش‌بینی |")
        lines.append("|---|---|---|")
        for sc in bundle.targets.scenarios.values():
            lines.append(f"| {sc.name_fa} | {_fmt(sc.total)} {cur} | {sc.uplift_vs_forecast*100:.1f}٪ |")
        lines.append("")

    # سگمنت‌بندی
    if bundle.segmentation.segment_sizes:
        lines.append("## سگمنت‌بندی مشتریان (RFM)\n")
        lines.append("| سگمنت | تعداد مشتری | درآمد |")
        lines.append("|---|---|---|")
        for seg, size in sorted(bundle.segmentation.segment_sizes.items(), key=lambda x: -x[1]):
            rev = bundle.segmentation.segment_revenue.get(seg, 0)
            lines.append(f"| {seg} | {_fmt(size)} | {_fmt(rev)} {cur} |")
        lines.append("")

    # ناهنجاری‌ها
    if bundle.anomalies.anomalies:
        lines.append("## ناهنجاری‌های فروش\n")
        lines.append("| تاریخ | مقدار | مورد انتظار | نوع |")
        lines.append("|---|---|---|---|")
        for a in bundle.anomalies.compact():
            lines.append(f"| {a['تاریخ']} | {format_number_fa(a['مقدار'])} | "
                         f"{format_number_fa(a['مورد_انتظار'])} | {a['نوع']} |")
        lines.append("")

    # کیفیت داده
    if bundle.quality.warnings:
        lines.append("## نکات کیفیت داده\n")
        for w in bundle.quality.warnings:
            lines.append(f"- {w}")
        lines.append("")

    # استراتژی هوش مصنوعی
    if strategy is not None:
        lines.append("## استراتژی مارکتینگ (تحلیل مدیر مارکتینگ)\n")
        lines.append("### خلاصه‌ی مدیریتی\n")
        lines.append(strategy.executive_summary + "\n")

        if strategy.factor_analysis:
            lines.append("### تحلیل عوامل مؤثر بر فروش\n")
            for f in strategy.factor_analysis:
                lines.append(f"- **{f.factor}:** {f.finding} _(تأثیر: {f.impact})_")
            lines.append("")

        lines.append("### توجیه تارگت\n")
        lines.append(strategy.target_rationale + "\n")

        if strategy.recommendations:
            lines.append("### توصیه‌های عملیاتی\n")
            lines.append("| عنوان | اولویت | اثر مورد انتظار | تلاش |")
            lines.append("|---|---|---|---|")
            for r in strategy.recommendations:
                lines.append(f"| {r.title} | {r.priority} | {r.expected_impact} | {r.effort} |")
            lines.append("")
            for r in strategy.recommendations:
                lines.append(f"- **{r.title}** — {r.rationale}")
            lines.append("")

        if strategy.risks:
            lines.append("### ریسک‌ها و نکات احتیاطی\n")
            for risk in strategy.risks:
                lines.append(f"- {risk}")
            lines.append("")

    return "\n".join(lines)


__all__ = ["build_markdown"]

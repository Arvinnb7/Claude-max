"""تولید گزارش Markdown فارسی از متریک‌ها، استراتژی و کمپین هوش مصنوعی."""

from __future__ import annotations

import datetime as _dt
from typing import TYPE_CHECKING

from ..config import get_settings
from ..locale_fa import format_number_fa, to_jalali

if TYPE_CHECKING:
    from ..ai.schemas import CampaignPlan, StrategyReport
    from ..pipeline import MetricsBundle


def _fmt(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{format_number_fa(value)}{suffix}"


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}٪"


def build_markdown(
    bundle: MetricsBundle,
    strategy: StrategyReport | None = None,
    campaign: CampaignPlan | None = None,
) -> str:
    """ساخت گزارش کامل Markdown (فارسی) شامل تحلیل، تارگت، استراتژی و کمپین."""
    s = get_settings()
    cur = bundle.meta.get("currency") or s.mkt_currency
    k = bundle.kpis
    lines: list[str] = []

    lines.append("# گزارش جامع تحلیل فروش و استراتژی مارکتینگ\n")
    lines.append(f"تاریخ تولید گزارش: {to_jalali(_dt.date.today())}\n")
    if bundle.quality.date_min:
        lines.append(f"بازه‌ی داده: {bundle.quality.date_min} تا {bundle.quality.date_max}\n")

    # وضعیت و دامنه (دروازه‌ی انتشار)
    validation = getattr(bundle, "validation", None)
    if validation is not None:
        fa = {"PASS": "معتبر (همه‌ی کنترل‌ها پاس)",
              "PASS_WITH_WARNINGS": "معتبر با هشدار",
              "FAIL": "تحلیل اکتشافی — دست‌کم یک کنترل بحرانی رد شد"}
        lines.append("## وضعیت و دامنه\n")
        lines.append(f"**وضعیت صحت گزارش: {fa.get(validation.status, validation.status)}**\n")
        lines.append(f"- تعداد رکورد معتبر: {_fmt(bundle.quality.n_rows)}")
        if getattr(k, "returns_count", 0):
            lines.append(f"- ردیف‌های برگشت از فروش: {_fmt(k.returns_count)}")
        pm = getattr(bundle.trends, "partial_month", None)
        if pm:
            lines.append(f"- ماه جاری ناقص است ({pm['days_covered']} از {pm['days_in_month']} روز)")
        bad = [c for c in validation.checks if c.status != "PASS"]
        for c in bad[:8]:
            mark = "⛔" if c.status == "FAIL" else "⚠️"
            lines.append(f"- {mark} {c.title}" + (f" — {c.detail}" if c.detail else ""))
        lines.append("")

    # KPI
    lines.append("## شاخص‌های کلیدی عملکرد\n")
    lines.append("| شاخص | مقدار |")
    lines.append("|---|---|")
    lines.append(f"| درآمد کل | {_fmt(k.total_revenue)} {cur} |")
    if getattr(k, "returns_count", 0):
        lines.append(f"| فروش ناخالص | {_fmt(k.gross_sales)} {cur} |")
        lines.append(f"| برگشت از فروش | {_fmt(k.returns_total)} {cur} ({_pct(k.return_rate)}) |")
        lines.append(f"| فروش خالص | {_fmt(k.net_sales)} {cur} |")
    lines.append(f"| تعداد سفارش | {_fmt(k.n_orders)} |")
    lines.append(f"| تعداد مشتری | {_fmt(k.n_customers)} |")
    lines.append(f"| میانگین ارزش سفارش | {_fmt(k.aov)} {cur} |")
    lines.append(f"| رشد ماهانه | {_pct(k.mom_growth)} |")
    lines.append(f"| رشد سالانه | {_pct(k.yoy_growth)} |")
    lines.append(f"| نرخ مشتری تکراری | {_pct(k.repeat_rate)} |")
    lines.append(f"| حاشیه‌ی سود ناخالص | {_pct(k.gross_margin)} |\n")

    # فرصت‌های ارزش‌دار (اعداد از موتور تصمیم، نه از مدل زبانی)
    ap = getattr(bundle, "actions", None)
    if ap is not None and getattr(ap, "available", False):
        lines.append("## فرصت‌های ارزش‌دار (فهرست اقدام)\n")
        lines.append(f"جمع ارزش فرصت‌های شناسایی‌شده: **{_fmt(ap.total_value)} {cur}** "
                     f"در {_fmt(len(ap.actions))} اقدام\n")
        lines.append("| نوع اقدام | تعداد | جمع ارزش |")
        lines.append("|---|---:|---:|")
        for s in ap.summary:
            lines.append(f"| {s['نوع اقدام']} | {_fmt(s['تعداد'])} | {_fmt(s['جمع ارزش'])} {cur} |")
        lines.append("")
        lines.append("**۵ اقدام با بالاترین ارزش:**\n")
        for a in ap.top(5):
            lines.append(f"- {a.action_fa} — مشتری {a.customer_id} — "
                         f"{_fmt(a.value_rial)} {cur} ({a.value_kind}، اتکا: {a.confidence})")
        lines.append("")
        cal = getattr(bundle, "probability_calibration", None)
        if cal is not None:
            verdict = "قابل اتکا" if cal.beats_baseline else "کم‌اعتماد"
            lines.append(f"دقت احتمال‌های خرید ({verdict}): خطای مدل {cal.brier} در برابر "
                         f"{cal.baseline_brier} برای حدس ساده — آزمون روی {_fmt(cal.n_eval)} "
                         f"مشتری با پنهان‌کردن {cal.window_days} روز آخر داده.\n")

    # محصولات
    if bundle.products.available:
        lines.append("## محصولات پرفروش و تحلیل ABC\n")
        lines.append("| محصول | درآمد | سهم | کلاس | رشد |")
        lines.append("|---|---|---|---|---|")
        for p in bundle.products.top(10):
            lines.append(f"| {p.product} | {_fmt(p.revenue)} {cur} | {_pct(p.share)} | "
                         f"{p.abc_class} | {_pct(p.growth)} |")
        lines.append("")

    # چرخه‌ی خرید و طبقه‌بندی مصرفی/تک‌خریدی
    if bundle.purchase_cycle.available:
        lines.append("## چرخه‌ی خرید محصولات\n")
        lines.append("| محصول | نوع | نرخ بازخرید | چرخه (روز) |")
        lines.append("|---|---|---|---|")
        for c in bundle.purchase_cycle.product_cycles[:25]:
            cyc = "—" if c.median_cycle_days is None else format_number_fa(round(c.median_cycle_days))
            lines.append(f"| {c.product} | {c.product_type} | {_pct(c.repurchase_rate)} | {cyc} |")
        lines.append("")
        overdue = bundle.purchase_cycle.overdue(10)
        if overdue:
            lines.append("**اعلان‌های چرخه (نمونه):**\n")
            for n in overdue[:8]:
                lines.append(f"- {n.message()}")
            lines.append("")

    # محصولات مکمل
    if bundle.basket.available:
        lines.append("## محصولات مکمل (تحلیل سبد)\n")
        lines.append("| اگر خرید | آنگاه | اطمینان | lift |")
        lines.append("|---|---|---|---|")
        for r in bundle.basket.top(8):
            lines.append(f"| {r.antecedent} | {r.consequent} | {_pct(r.confidence)} | {r.lift:.2f} |")
        lines.append("")

    # پیش‌بینی + تارگت
    if bundle.targets is not None:
        lines.append("## تارگت پیشنهادی\n")
        lines.append(f"مجموع پیش‌بینی برای {bundle.targets.horizon} دوره‌ی آینده: "
                     f"**{_fmt(bundle.targets.forecast_total)} {cur}**\n")
        lines.append("| سناریو | مجموع هدف | رشد نسبت به پیش‌بینی |")
        lines.append("|---|---|---|")
        for sc in bundle.targets.scenarios.values():
            lines.append(f"| {sc.name_fa} | {_fmt(sc.total)} {cur} | {sc.uplift_vs_forecast*100:.1f}٪ |")
        lines.append("")

    # عملکرد و تخصیص تارگت
    for alloc, perf_items, title in (
        (bundle.branch_targets, bundle.performance.by_branch, "شعب"),
        (bundle.salesperson_targets, bundle.performance.by_salesperson, "فروشندگان"),
    ):
        if alloc is not None and perf_items:
            target_map = {e.name: e.target for e in alloc.entities}
            lines.append(f"## عملکرد و تارگت {title}\n")
            lines.append("| نام | درآمد | سهم | رشد | تارگت دوره‌ی بعد |")
            lines.append("|---|---|---|---|---|")
            for e in perf_items:
                lines.append(f"| {e.name} | {_fmt(e.revenue)} {cur} | {_pct(e.share)} | "
                             f"{_pct(e.growth)} | {_fmt(target_map.get(e.name))} {cur} |")
            lines.append("")

    # pacing
    if bundle.pacing is not None:
        p = bundle.pacing
        lines.append("## پیشروی به‌سمت تارگت ماهانه\n")
        lines.append(f"- تارگت ماه: {_fmt(p.monthly_target)} {cur}")
        lines.append(f"- محقق‌شده: {_fmt(p.achieved)} {cur}")
        lines.append(f"- نرخ روزانه‌ی لازم: {_fmt(p.required_daily)} {cur}")
        lines.append(f"- وضعیت: {'در مسیر' if p.on_track else 'عقب از برنامه'}\n")

    # تشخیص افت
    if bundle.diagnostics.period_label and bundle.diagnostics.drivers:
        lines.append("## تشخیص دلایل تغییر فروش\n")
        lines.append(f"تغییر کلی فروش ({bundle.diagnostics.period_label}): "
                     f"{_pct(bundle.diagnostics.overall_pct)}\n")
        lines.append("| بُعد | مورد | تغییر | سهم از افت |")
        lines.append("|---|---|---|---|")
        for d in bundle.diagnostics.drivers[:8]:
            lines.append(f"| {d.dimension} | {d.label} | {_pct(d.pct_change)} | "
                         f"{_pct(d.contribution_to_decline)} |")
        lines.append("")

    # تأمین کالا
    if bundle.inventory.available:
        lines.append("## پیشنهاد تأمین کالا\n")
        lines.append("| محصول | توصیه | دلیل |")
        lines.append("|---|---|---|")
        for it in bundle.inventory.items[:25]:
            lines.append(f"| {it.product} | {it.recommendation} | {it.reason} |")
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

    # نکات کیفیت داده
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
            for r in strategy.recommendations:
                lines.append(f"- **{r.title}** (اولویت: {r.priority}، تلاش: {r.effort}) — {r.rationale} "
                             f"_اثر مورد انتظار: {r.expected_impact}_")
            lines.append("")
        if strategy.risks:
            lines.append("### ریسک‌ها و نکات احتیاطی\n")
            for risk in strategy.risks:
                lines.append(f"- {risk}")
            lines.append("")

    # کمپین و پیام‌ها
    if campaign is not None:
        lines.append("## برنامه‌ی کمپین و پیام‌ها\n")
        lines.append(campaign.summary + "\n")
        for a in campaign.audiences:
            lines.append(f"### کمپین: {a.segment_name}\n")
            lines.append(f"- مخاطب: {a.audience_definition}")
            lines.append(f"- هدف: {a.objective} — پیشنهاد: {a.offer} — شاخص: {a.success_kpi}\n")
            for ch in a.channels:
                lines.append(f"**{ch.channel}** (زمان: {ch.timing})")
                if ch.subject:
                    lines.append(f"- موضوع: {ch.subject}")
                lines.append(f"- متن: {ch.body}")
                if ch.call_script:
                    lines.append(f"- اسکریپت تماس: {ch.call_script}")
                lines.append("")
        if campaign.weekly_actions:
            lines.append("### برنامه‌ی اجرایی هفته\n")
            for w in campaign.weekly_actions:
                acts = "؛ ".join(w.actions)
                lines.append(f"- **{w.day}** ({w.focus}): {acts}")
            lines.append("")

    return "\n".join(lines)


__all__ = ["build_markdown"]

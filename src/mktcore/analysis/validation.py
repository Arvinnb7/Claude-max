"""دروازه‌ی انتشار: کنترل‌های آشتی و کیفیت روی نتیجه‌ی تحلیل.

خروجی هر گزارش یک وضعیت رسمی می‌گیرد:
- PASS: همه‌ی کنترل‌های بحرانی پاس شدند.
- PASS_WITH_WARNINGS: محاسبات اصلی درست است اما محدودیت غیربحرانی وجود دارد.
- FAIL: دست‌کم یک کنترل بحرانی رد شد؛ خروجی «تحلیل اکتشافی» است.

هیچ کنترلی داده را اصلاح نمی‌کند — فقط گزارش می‌دهد.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..ingest.cleaning import get_returns
from ..ingest.schema import ColumnRole, standard_column

_REVENUE = standard_column(ColumnRole.REVENUE)
_PRODUCT = standard_column(ColumnRole.PRODUCT)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)

PASS = "PASS"
WARN = "PASS_WITH_WARNINGS"
FAIL = "FAIL"

_TOL_ABS = 1.0
_TOL_REL = 1e-6


@dataclass
class CheckResult:
    check_id: str
    title: str  # فارسی، برای نمایش
    status: str  # PASS / WARN / FAIL
    detail: str = ""


@dataclass
class ValidationReport:
    status: str = PASS
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, check_id: str, title: str, ok: bool, detail: str = "",
            *, critical: bool = True) -> None:
        st = PASS if ok else (FAIL if critical else WARN)
        self.checks.append(CheckResult(check_id, title, st, detail))

    def finalize(self) -> None:
        if any(c.status == FAIL for c in self.checks):
            self.status = FAIL
        elif any(c.status == WARN for c in self.checks):
            self.status = WARN
        else:
            self.status = PASS


# ---------------------------------------------------------------- گاردِ ثبت
# §۸.۵: «خطاهای مالیِ خطرناک — واحدِ پولِ نامعلوم، علامتِ وارونه، جمعِ ناممکن —
# باید ثبت در دفتر کل را تا رفع متوقف کنند.» فقط همین سه؛ بقیه‌ی کنترل‌ها
# هشدار می‌مانند (تصمیمِ کاربر: «فقط خطاهای مالیِ خطرناک»).
POSTING_BLOCKERS: frozenset[str] = frozenset({"C04", "C05"})
KNOWN_MONEY_UNITS: frozenset[str] = frozenset({"ریال", "تومان"})
UNKNOWN_MONEY_UNIT_ID = "C00"


def posting_block_reasons(
    report: ValidationReport | None, *, file_currency: str | None,
) -> list[dict]:
    """دلایلی که ثبت در دفتر کل را متوقف می‌کنند؛ خالی یعنی ثبت مجاز است.

    تابعِ خالص است و خودِ `run_validation` را دست نمی‌زند: کنترل‌ها همچنان فقط
    گزارش می‌دهند؛ این تابع می‌گوید کدام گزارش‌ها «مسدودکننده»اند. هر دلیل
    `check_id`، `title` و `detail` دارد تا اپراتور بداند چه چیزی را درست کند.
    """
    reasons: list[dict] = []
    if file_currency is not None and file_currency not in KNOWN_MONEY_UNITS:
        reasons.append({
            "check_id": UNKNOWN_MONEY_UNIT_ID,
            "title": "واحد پول فایل مشخص است",
            "detail": f"واحدِ «{file_currency}» شناخته نیست؛ مبالغ بدون واحدِ معلوم ثبت نمی‌شوند.",
        })
    if report is not None:
        for check in report.checks:
            if check.check_id in POSTING_BLOCKERS and check.status == FAIL:
                reasons.append({
                    "check_id": check.check_id,
                    "title": check.title,
                    "detail": check.detail,
                })
    return reasons


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(_TOL_ABS, _TOL_REL * max(abs(a), abs(b)))


def run_validation(bundle, df: pd.DataFrame) -> ValidationReport:
    """اجرای کنترل‌های C/W روی bundle و فریم پاک‌شده."""
    rep = ValidationReport()
    k = bundle.kpis
    returns = get_returns(df)

    # C04 — قرارداد علامت مبالغ
    ambiguous = bool(df.attrs.get("ambiguous_sign"))
    rep.add("C04", "قرارداد علامت فروش/برگشت مشخص است", not ambiguous,
            "سهم ردیف‌های منفی بین ۴۰٪ تا ۶۰٪ است؛ تفکیک فروش/برگشت قابل اتکا نیست."
            if ambiguous else
            ("علامت ستون‌های حسابداری اصلاح شد." if df.attrs.get("sign_flipped") else ""))

    matrix = (df.attrs.get("validation") or {}).get("doc_sign_matrix")
    if matrix:
        n_bad = matrix["sale_rows_marked_return"] + matrix["return_rows_marked_sale"]
        n_all = max(len(df) + len(returns), 1)
        rep.add("C04b", "نوع سند با علامت مبلغ سازگار است", n_bad / n_all <= 0.02,
                f"{n_bad} ردیف ناسازگار بین «نوع سند» و علامت مبلغ.",
                critical=n_bad / n_all > 0.10)

    # C05 — فروش خالص = ناخالص − برگشت
    gross = getattr(k, "gross_sales", k.total_revenue)
    rets = getattr(k, "returns_total", 0.0)
    net = getattr(k, "net_sales", k.total_revenue)
    rep.add("C05", "فروش خالص = فروش ناخالص − برگشت", _close(net, gross - rets),
            f"خالص={net:,.0f}، ناخالص={gross:,.0f}، برگشت={rets:,.0f}")

    # C06 — آشتی شعب با کل (شامل سطل «بدون شعبه»)
    if bundle.performance.has_branch:
        branch_sum = sum(e.revenue for e in bundle.performance.by_branch)
        rep.add("C06", "جمع فروش شعب با فروش کل آشتی می‌کند",
                _close(branch_sum, gross),
                f"جمع شعب={branch_sum:,.0f} در برابر ناخالص={gross:,.0f}")

    # C07 — آشتی محصولات با کل (+ سطل بدون نام کالا)
    if _PRODUCT in df.columns:
        named = float(df.loc[df[_PRODUCT].notna(), _REVENUE].sum())
        unnamed = float(df.loc[df[_PRODUCT].isna(), _REVENUE].sum())
        rep.add("C07", "جمع فروش محصولات (+بدون نام) با کل آشتی می‌کند",
                _close(named + unnamed, gross),
                f"با نام={named:,.0f}، بدون نام={unnamed:,.0f}" +
                (f" — {unnamed / gross:.1%} فروش بدون نام کالاست" if gross and unnamed else ""))

    # C08 — AOV و شمارش سفارش از یک جمعیت
    if k.n_orders:
        rep.add("C08", "AOV از همان جمعیت شمارش سفارش است",
                _close(k.aov * k.n_orders, net),
                f"AOV×سفارش={k.aov * k.n_orders:,.0f} در برابر خالص={net:,.0f}")

    # C09/C10 — آشتی RFM
    seg = bundle.segmentation
    if seg.segment_sizes:
        total_seg = sum(seg.segment_sizes.values())
        rep.add("C09", "هر مشتری دقیقاً در یک سگمنت RFM است",
                total_seg == k.n_customers,
                f"جمع سگمنت‌ها={total_seg} در برابر مشتریان={k.n_customers}")
        if _CUSTOMER in df.columns:
            eligible = float(df.loc[df[_CUSTOMER].notna(), _REVENUE].sum())
            seg_rev = sum(seg.segment_revenue.values())
            rep.add("C10", "جمع فروش سگمنت‌ها با فروش مشتری‌دار آشتی می‌کند",
                    _close(seg_rev, eligible),
                    f"سگمنت‌ها={seg_rev:,.0f} در برابر مشتری‌دار={eligible:,.0f}")

    # C11 — ماه ناقص با ماه کامل مقایسه نشده (ساختاری؛ همیشه برقرار)
    pm = getattr(bundle.trends, "partial_month", None)
    rep.add("C11", "ماه ناقص از رشد ماهانه جدا شده است", True,
            f"ماه جاری {pm['label']} ناقص است ({pm['days_covered']}/{pm['days_in_month']} روز)"
            if pm else "همه‌ی ماه‌ها کامل‌اند.")

    # C12 — افق سناریو = افق پیش‌بینی
    if bundle.targets is not None and bundle.forecast is not None:
        same = all(len(sc.per_period) == bundle.forecast.horizon
                   for sc in bundle.targets.scenarios.values())
        rep.add("C12", "افق سناریوها با افق پیش‌بینی برابر است", same,
                f"افق پیش‌بینی={bundle.forecast.horizon}")

    # --- هشدارهای غیربحرانی ---
    inv = df.attrs.get("dropped_invalid_rows", 0)
    n_all = max(len(df) + inv, 1)
    rep.add("W06", "سهم ردیف‌های قرنطینه‌شده کم است", inv / n_all <= 0.05,
            f"{inv} ردیف نامعتبر ({inv / n_all:.1%}).", critical=False)

    if bundle.performance.has_branch:
        from .performance import UNASSIGNED_BRANCH
        un = next((e for e in bundle.performance.by_branch
                   if e.name == UNASSIGNED_BRANCH), None)
        rep.add("W03", "سهم فروش «بدون شعبه» کم است",
                un is None or un.share <= 0.10,
                f"{un.share:.1%} فروش بدون شعبه است." if un else "", critical=False)

    recon = (df.attrs.get("validation") or {}).get("amount_reconciliation")
    if recon:
        rep.add("W08", "آشتی ردیفی ناخالص−تخفیف−پرداختی برقرار است",
                recon["violating_share"] <= 0.05,
                f"{recon['violating_share']:.1%} ردیف‌ها ناسازگارند.", critical=False)

    rep.finalize()
    return rep


__all__ = ["ValidationReport", "CheckResult", "run_validation", "PASS", "WARN", "FAIL"]

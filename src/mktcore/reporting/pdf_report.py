"""تولید گزارش PDF فارسی (RTL) با Jinja2 + WeasyPrint.

WeasyPrint جهت RTL را بومی مدیریت می‌کند؛ نیازی به reshaping دستی نیست. این
ماژول نیازمند نصب گروه اختیاری `pdf` و کتابخانه‌های سیستمی (pango/cairo) است.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import get_settings
from ..locale_fa import format_number_fa, to_jalali

if TYPE_CHECKING:
    from ..ai.schemas import StrategyReport
    from ..pipeline import MetricsBundle

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401

        return True
    except Exception:
        return False


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.1f}٪"


def _build_context(bundle: MetricsBundle, strategy: StrategyReport | None) -> dict:
    s = get_settings()
    cur = s.mkt_currency
    k = bundle.kpis
    ctx: dict = {
        "currency": cur,
        "generated_at": to_jalali(_dt.date.today()),
        "kpis": [
            ("درآمد کل", f"{format_number_fa(k.total_revenue)} {cur}"),
            ("تعداد سفارش", format_number_fa(k.n_orders)),
            ("تعداد مشتری", format_number_fa(k.n_customers)),
            ("میانگین ارزش سفارش", f"{format_number_fa(k.aov)} {cur}"),
            ("رشد ماهانه", _pct(k.mom_growth)),
            ("رشد سالانه", _pct(k.yoy_growth)),
            ("نرخ مشتری تکراری", _pct(k.repeat_rate)),
            ("حاشیه‌ی سود ناخالص", _pct(k.gross_margin)),
        ],
        "strategy": strategy,
    }

    if bundle.targets is not None:
        ctx["targets"] = {
            "horizon": bundle.targets.horizon,
            "forecast_total": format_number_fa(bundle.targets.forecast_total),
            "scenarios": [
                {"name_fa": sc.name_fa, "total": format_number_fa(sc.total),
                 "uplift": f"{sc.uplift_vs_forecast * 100:.1f}"}
                for sc in bundle.targets.scenarios.values()
            ],
        }

    if bundle.segmentation.segment_sizes:
        ctx["segments"] = [
            {"name": seg, "size": format_number_fa(size),
             "revenue": format_number_fa(bundle.segmentation.segment_revenue.get(seg, 0))}
            for seg, size in sorted(bundle.segmentation.segment_sizes.items(), key=lambda x: -x[1])
        ]

    return ctx


def render_html(bundle: MetricsBundle, strategy: StrategyReport | None = None) -> str:
    """رندر HTML گزارش (مستقل از WeasyPrint — برای پیش‌نمایش هم مفید است)."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("report.html.j2")
    css = (_TEMPLATE_DIR / "report.css").read_text(encoding="utf-8")
    ctx = _build_context(bundle, strategy)
    ctx["css"] = css
    return template.render(**ctx)


def build_pdf(
    bundle: MetricsBundle,
    strategy: StrategyReport | None = None,
    *,
    output_path: str | Path | None = None,
) -> bytes:
    """تولید بایت‌های PDF گزارش.

    Raises:
        RuntimeError: اگر WeasyPrint در دسترس نباشد.
    """
    if not weasyprint_available():
        raise RuntimeError(
            "WeasyPrint نصب نیست. برای خروجی PDF: pip install '.[pdf]' و نصب "
            "کتابخانه‌های سیستمی pango/cairo."
        )
    from weasyprint import HTML

    html = render_html(bundle, strategy)
    pdf_bytes = HTML(string=html).write_pdf()
    if output_path is not None:
        Path(output_path).write_bytes(pdf_bytes)
    return pdf_bytes


__all__ = ["build_pdf", "render_html", "weasyprint_available"]

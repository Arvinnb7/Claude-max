"""تولید گزارش PDF فارسی (RTL) از گزارش Markdown با WeasyPrint.

گزارش Markdown منبع واحد است؛ اینجا به HTML تبدیل و با CSS راست‌به‌چپ و فونت
فارسی به PDF رندر می‌شود. WeasyPrint جهت RTL را بومی مدیریت می‌کند.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .markdown_report import build_markdown

if TYPE_CHECKING:
    from ..ai.schemas import CampaignPlan, StrategyReport
    from ..pipeline import MetricsBundle

_PDF_CSS = """
@page { size: A4; margin: 1.8cm 1.5cm; }
* { box-sizing: border-box; }
body {
  direction: rtl; text-align: right;
  font-family: "Vazirmatn", "Tahoma", "DejaVu Sans", sans-serif;
  color: #1f2933; line-height: 1.8; font-size: 11.5px;
}
h1 { color: #1d4ed8; font-size: 22px; border-bottom: 3px solid #2563eb; padding-bottom: 8px; }
h2 { color: #1e40af; font-size: 16px; border-right: 4px solid #2563eb; padding-right: 8px; margin-top: 22px; }
h3 { color: #334155; font-size: 13px; margin-top: 14px; }
table { width: 100%; border-collapse: collapse; margin: 8px 0; }
th, td { border: 1px solid #cbd5e1; padding: 5px 8px; text-align: right; }
th { background: #eff6ff; color: #1e40af; }
tr:nth-child(even) td { background: #f8fafc; }
ul { padding-right: 18px; }
strong { color: #0f172a; }
code { background: #f1f5f9; padding: 1px 4px; border-radius: 4px; }
"""

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<style>@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;600;700&display=swap');
{css}</style></head><body>{body}</body></html>"""


def weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401

        return True
    except Exception:
        return False


def _markdown_to_html(md_text: str) -> str:
    import markdown

    return markdown.markdown(md_text, extensions=["tables", "sane_lists"])


def render_html(
    bundle: MetricsBundle,
    strategy: StrategyReport | None = None,
    campaign: CampaignPlan | None = None,
) -> str:
    """رندر HTML کامل گزارش (مستقل از WeasyPrint — برای پیش‌نمایش هم مفید است)."""
    md_text = build_markdown(bundle, strategy, campaign)
    body = _markdown_to_html(md_text)
    return _HTML_TEMPLATE.format(css=_PDF_CSS, body=body)


def build_pdf(
    bundle: MetricsBundle,
    strategy: StrategyReport | None = None,
    campaign: CampaignPlan | None = None,
    *,
    output_path: str | Path | None = None,
) -> bytes:
    """تولید بایت‌های PDF گزارش جامع.

    Raises:
        RuntimeError: اگر WeasyPrint در دسترس نباشد.
    """
    if not weasyprint_available():
        raise RuntimeError(
            "WeasyPrint نصب نیست. برای خروجی PDF: pip install '.[pdf]' و نصب "
            "کتابخانه‌های سیستمی pango/cairo."
        )
    from weasyprint import HTML

    html = render_html(bundle, strategy, campaign)
    pdf_bytes = HTML(string=html).write_pdf()
    if output_path is not None:
        Path(output_path).write_bytes(pdf_bytes)
    return pdf_bytes


__all__ = ["build_pdf", "render_html", "weasyprint_available"]

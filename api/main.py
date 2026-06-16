"""برنامه‌ی FastAPI — API تحلیل و استراتژی مارکتینگ برای فرانت‌اند Next.js."""

from __future__ import annotations

import sys
from pathlib import Path

# دسترسی به mktcore بدون نصب
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from fastapi import Body, FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from mktcore.ai.client import api_key_available  # noqa: E402
from mktcore.config import get_settings  # noqa: E402
from mktcore.connectors import ExcelCsvConnector  # noqa: E402
from mktcore.execution import build_audience, render_messages, send_campaign  # noqa: E402
from mktcore.execution.audience import AUDIENCE_KINDS  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.profiler import profile_frame  # noqa: E402
from mktcore.ingest.schema import REQUIRED_ROLES, ColumnRole  # noqa: E402
from mktcore.locale_fa import ROLE_LABELS_FA  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402
from mktcore.synthetic import generate_synthetic_sales  # noqa: E402

from .serialize import bundle_to_dict, campaign_to_dict, strategy_to_dict  # noqa: E402
from .store import store  # noqa: E402

app = FastAPI(title="Marketing Analytics API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _columns_payload(df) -> dict:
    """نگاشت پیشنهادی + پیش‌نمایش + فهرست نقش‌ها."""
    mapper = SchemaMapper()
    suggestion = mapper.auto_detect(df)
    roles = [
        {"role": r.value, "label": ROLE_LABELS_FA.get(r.value, r.value),
         "required": r in REQUIRED_ROLES,
         "suggested": suggestion.mapping.get(r)}
        for r in ColumnRole
    ]
    preview = df.head(15).astype(str).to_dict(orient="records")
    return {
        "columns": [str(c) for c in df.columns],
        "roles": roles,
        "preview": preview,
        "n_rows": int(len(df)),
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "ai_available": api_key_available(),
            "model": get_settings().mkt_model, "currency": get_settings().mkt_currency}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    try:
        connector = ExcelCsvConnector(content=content, filename=file.filename or "uploaded")
        sheets = connector.list_sources()
        result = connector.read(sheets[0])
        df = result.dataframe
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"خطا در خواندن فایل: {e}") from e
    sid = store.create(df)
    return {"session_id": sid, "sheets": sheets, **_columns_payload(df)}


@app.post("/api/sample")
def sample() -> dict:
    df = generate_synthetic_sales()
    sid = store.create(df)
    return {"session_id": sid, "sheets": ["نمونه"], **_columns_payload(df)}


class AnalyzeRequest(BaseModel):
    session_id: str
    mapping: dict[str, str]  # role -> column name
    horizon: int = 6
    balanced_uplift: float = 0.10


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    session = store.get(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="نشست یافت نشد یا منقضی شده است.")

    # تبدیل نگاشت به ColumnRole
    try:
        mapping = {ColumnRole(role): col for role, col in req.mapping.items()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"نقش نامعتبر: {e}") from e

    missing = [ROLE_LABELS_FA[r.value] for r in REQUIRED_ROLES if r not in mapping]
    if missing:
        raise HTTPException(status_code=400, detail=f"نگاشت ناقص: {', '.join(missing)}")

    try:
        std = SchemaMapper().apply(session.raw_df, mapping)
        clean = clean_frame(std)
        bundle = run_analysis(clean, horizon=req.horizon, balanced_uplift=req.balanced_uplift)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"خطا در تحلیل: {e}") from e

    session.clean_df = clean
    session.bundle = bundle
    profile = profile_frame(clean)
    payload = bundle_to_dict(bundle, currency=get_settings().mkt_currency)
    payload["quality"]["warnings"] = profile.warnings
    return payload


class StrategyRequest(BaseModel):
    session_id: str


@app.post("/api/strategy")
def strategy(req: StrategyRequest = Body(...)) -> dict:
    session = store.get(req.session_id)
    if session is None or session.bundle is None:
        raise HTTPException(status_code=404, detail="ابتدا تحلیل را اجرا کنید.")
    if not api_key_available():
        raise HTTPException(status_code=503, detail="کلید ANTHROPIC_API_KEY تنظیم نشده است.")
    try:
        from mktcore.ai.strategist import generate_strategy

        report = generate_strategy(session.bundle)
        session.strategy = report
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"خطا در تولید استراتژی: {e}") from e
    return strategy_to_dict(report)


@app.post("/api/campaign")
def campaign(req: StrategyRequest = Body(...)) -> dict:
    """تولید برنامه‌ی کمپین و پیام‌های شخصی‌سازی‌شده‌ی چندکاناله."""
    session = store.get(req.session_id)
    if session is None or session.bundle is None:
        raise HTTPException(status_code=404, detail="ابتدا تحلیل را اجرا کنید.")
    if not api_key_available():
        raise HTTPException(status_code=503, detail="کلید ANTHROPIC_API_KEY تنظیم نشده است.")
    try:
        from mktcore.ai.campaign import generate_campaigns

        plan = generate_campaigns(session.bundle)
        session.campaign = plan
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"خطا در تولید کمپین: {e}") from e
    return campaign_to_dict(plan)


@app.get("/api/audience-kinds")
def audience_kinds() -> dict:
    return {"kinds": [{"key": k, "label": v} for k, v in AUDIENCE_KINDS.items()]}


@app.get("/api/report")
def report(session_id: str, fmt: str = "pdf"):
    """خروجی گزارش جامع (تحلیل + استراتژی + کمپین) به‌صورت PDF یا HTML.

    استراتژی/کمپین اگر قبلاً تولید شده باشند در گزارش گنجانده می‌شوند.
    """
    session = store.get(session_id)
    if session is None or session.bundle is None:
        raise HTTPException(status_code=404, detail="ابتدا تحلیل را اجرا کنید.")
    strategy = getattr(session, "strategy", None)
    campaign = getattr(session, "campaign", None)

    from mktcore.reporting.pdf_report import build_pdf, render_html, weasyprint_available

    if fmt == "html" or not weasyprint_available():
        html = render_html(session.bundle, strategy, campaign)
        return HTMLResponse(content=html)
    pdf = build_pdf(session.bundle, strategy, campaign)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=marketing_report.pdf"},
    )


class SMSRequest(BaseModel):
    session_id: str
    kind: str  # نوع مخاطب (از /api/audience-kinds)
    template: str  # قالب پیام با متغیرهای {نام} و …
    limit: int = 100
    dry_run: bool = True  # امن: پیش‌فرض فقط پیش‌نمایش


@app.post("/api/sms/send")
def sms_send(req: SMSRequest) -> dict:
    """ساخت مخاطب، شخصی‌سازی پیام و ارسال (پیش‌فرض dry-run؛ بدون ارسال واقعی)."""
    session = store.get(req.session_id)
    if session is None or session.bundle is None or session.clean_df is None:
        raise HTTPException(status_code=404, detail="ابتدا تحلیل را اجرا کنید.")
    if req.kind not in AUDIENCE_KINDS:
        raise HTTPException(status_code=400, detail="نوع مخاطب نامعتبر است.")

    recipients = build_audience(session.bundle, req.kind, df=session.clean_df, limit=req.limit)
    messages = render_messages(req.template, recipients)
    # ارسال واقعی نیازمند کلید پنل است؛ این endpoint فقط dry-run را پشتیبانی می‌کند.
    result = send_campaign(messages, dry_run=True)
    return {"audience_size": len(recipients), **result.to_dict()}


__all__ = ["app"]

"""برنامه‌ی FastAPI — API تحلیل و استراتژی مارکتینگ (نشست ماندگار + job پس‌زمینه)."""

from __future__ import annotations

import hashlib
import logging
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

# نسخه‌ی pipeline برای manifest بازتولیدپذیری (با هر تغییر منطق محاسبات به‌روز شود)
PIPELINE_VERSION = "2.0.0"

# دسترسی به mktcore بدون نصب
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("mktcore.api")

from fastapi import Body, FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from mktcore.ai.client import api_key_available  # noqa: E402
from mktcore.config import get_settings  # noqa: E402
from mktcore.connectors import ExcelCsvConnector  # noqa: E402
from mktcore.contact.permission import DEFAULT_FATIGUE_WINDOW_DAYS  # noqa: E402
from mktcore.contact.register import load_gate  # noqa: E402
from mktcore.db.migrations import ensure_schema as ensure_canonical_schema  # noqa: E402
from mktcore.execution import build_audience, render_messages, send_campaign  # noqa: E402
from mktcore.execution.audience import AUDIENCE_KINDS  # noqa: E402
from mktcore.ingest.cleaning import clean_frame, get_exclusions, get_returns  # noqa: E402
from mktcore.ingest.currency import (  # noqa: E402
    CURRENCIES,
    conversion_factor,
    convert_monetary_columns,
)
from mktcore.ingest.mapper import SchemaMapper, header_signature  # noqa: E402
from mktcore.ingest.profiler import profile_frame  # noqa: E402
from mktcore.ingest.schema import REQUIRED_ROLES, ColumnRole, standard_column  # noqa: E402
from mktcore.locale_fa import ROLE_LABELS_FA, format_number_fa  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402
from mktcore.synthetic import generate_synthetic_sales  # noqa: E402

from .campaigns_api import router as campaigns_router  # noqa: E402
from .canonical_hook import canonical_enabled, record_analysis  # noqa: E402
from .export import EXPORT_FA_NAMES, EXPORT_SECTIONS, EmptySection, build_export  # noqa: E402
from .jobs import JobError, submit_job  # noqa: E402
from .persistence import store  # noqa: E402
from .scheduler import (  # noqa: E402
    catch_up_missed_scan,
    run_cycle_scan,
    scheduler_status,
    start_scheduler,
    stop_scheduler,
)
from .serialize import bundle_to_dict, campaign_to_dict, strategy_to_dict  # noqa: E402
from .v1 import router as v1_router  # noqa: E402


def _catch_up_scheduler() -> None:
    """اجرای جبرانی، ایزوله از بالا آمدن API."""
    try:
        result = catch_up_missed_scan()
        if result.get("status") == "ok":
            logger.info("اسکن جبرانی چرخه انجام شد: %s", result)
    except Exception:
        logger.exception("اسکن جبرانی چرخه ناموفق بود")


@asynccontextmanager
async def lifespan(app: FastAPI):
    recovered = store.recover_stale_jobs()
    if recovered:
        logger.warning("recovered %d stale jobs after restart", recovered)
    # هیچ‌کدام از کارهای startup نباید بتوانند بالا آمدن API را متوقف کنند
    try:
        pruned = store.run_retention()
        logger.info("سیاست نگه‌داری اجرا شد: %s", pruned)
    except Exception:
        logger.exception("پاکسازی نشست‌های منقضی ناموفق بود؛ API ادامه می‌دهد")
    try:
        start_scheduler()
    except Exception:
        logger.exception("زمان‌بند اجرا نشد؛ API بدون زمان‌بند ادامه می‌دهد")
    # جبران نوبتِ ازدست‌رفته: زمان‌بند در حافظه است، پس خاموشیِ سرور در ساعت
    # اجرا آن نوبت را بی‌صدا حذف می‌کرد. در thread جدا تا بالا آمدن API را
    # معطل نکند.
    try:
        threading.Thread(target=_catch_up_scheduler, name="cycle-catch-up",
                         daemon=True).start()
    except Exception:
        logger.exception("اجرای جبرانی زمان‌بند شروع نشد؛ API ادامه می‌دهد")
    # طرح‌واره‌ی دفتر کل — تنبل هم ساخته می‌شود، این فقط زودتر انجامش می‌دهد
    try:
        if canonical_enabled():
            ensure_canonical_schema()
    except Exception:
        logger.exception("آماده‌سازی دفتر کل ناموفق بود؛ API بدون آن ادامه می‌دهد")
    yield
    stop_scheduler()


app = FastAPI(title="Marketing Analytics API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

# مسیرهای دفتر کل و کمپین — **افزودنی**؛ هیچ endpoint موجودی جابه‌جا نمی‌شود.
app.include_router(v1_router)
app.include_router(campaigns_router)


def _columns_payload(df) -> dict:
    """نگاشت پیشنهادی + اطمینان + دلیل + پیش‌نمایش + فهرست نقش‌ها."""
    mapper = SchemaMapper()
    suggestion = mapper.auto_detect(df)
    roles = []
    for r in ColumnRole:
        g = suggestion.guesses.get(r)
        roles.append({
            "role": r.value,
            "label": ROLE_LABELS_FA.get(r.value, r.value),
            "required": r in REQUIRED_ROLES,
            "suggested": suggestion.mapping.get(r),
            "confidence": round(g.confidence, 2) if g else 0.0,
            "reason": g.reason if g else "",
            "low_confidence": bool(g and not g.auto and g.confidence > 0),
        })
    preview = df.head(15).astype(str).to_dict(orient="records")
    columns = [str(c) for c in df.columns]
    payload = {
        "columns": columns,
        "roles": roles,
        "preview": preview,
        "n_rows": int(len(df)),
        "missing_required": [ROLE_LABELS_FA[r.value] for r in suggestion.missing_required],
        "header_signature": header_signature(columns),
    }

    # حافظه‌ی نگاشت: اگر فایلی با همین ساختار سرستون قبلاً تحلیل شده، نگاشت و
    # واحد پول همان بار برگردانده می‌شود تا کاربر دوباره دستی وارد نکند.
    prof = store.get_mapping_profile(payload["header_signature"])
    if prof:
        kept = {r: c for r, c in prof["mapping"].items() if c in columns}
        payload["saved_mapping"] = kept
        payload["saved_dropped_roles"] = [
            ROLE_LABELS_FA.get(r, r) for r in prof["mapping"] if r not in kept
        ]
        payload["saved_file_currency"] = prof["file_currency"]
        payload["saved_display_currency"] = prof["display_currency"]
        payload["saved_use_count"] = prof["use_count"]
    return payload


@app.get("/api/health")
def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "ai_available": api_key_available(),
        "model": s.mkt_model,
        "currency": s.mkt_currency,
        "sms_enabled": s.sms_configured,
        "scheduler": scheduler_status()["running"],
        "data_dir": str(store.data_dir.resolve()),
        "retention": s.retention_policy,
    }


# ---------------------------------------------------------------- آپلود (job)
@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    settings = get_settings()
    max_bytes = settings.mkt_max_upload_mb * 1024 * 1024

    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"حجم فایل از سقف مجاز ({settings.mkt_max_upload_mb} مگابایت) بیشتر است.",
            )
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        raise HTTPException(status_code=400, detail="فایل خالی است.")

    filename = file.filename or "uploaded"
    sid = store.create_session(filename)

    def _job(progress) -> dict:
        progress(5, "خواندن فایل")

        # progress زنده‌ی خواندن: نگاشت ۱۵→۶۵٪ + throttle (حداکثر ~۲ نوشتن در ثانیه)
        last_write = [0.0]

        def _read_progress(done: int, total_rows: int | None) -> None:
            now = time.monotonic()
            if now - last_write[0] < 0.5:
                return
            last_write[0] = now
            if total_rows and total_rows > 0:
                pct = 15.0 + 50.0 * min(done / total_rows, 1.0)
                progress(pct, f"خواندن فایل — {format_number_fa(done)} از حدود "
                              f"{format_number_fa(total_rows)} ردیف")
            else:
                progress(20.0, f"خواندن فایل — {format_number_fa(done)} ردیف خوانده شد")

        try:
            connector = ExcelCsvConnector(content=content, filename=filename)
            sheets = connector.list_sources()
            progress(15, "خواندن اکسل")
            result = connector.read(sheets[0], progress=_read_progress)
            df = result.dataframe
        except Exception as e:
            raise JobError(f"خطا در خواندن فایل: {e}") from e
        progress(70, "ذخیره‌ی داده")
        store.save_raw(sid, df)
        progress(85, "تشخیص هوشمند ستون‌ها")
        payload = _columns_payload(df)
        payload["session_id"] = sid
        payload["sheets"] = sheets
        payload["warnings"] = result.meta.get("warnings", [])
        payload["file_sha256"] = hashlib.sha256(content).hexdigest()
        payload["file_size"] = len(content)
        store.set_columns_payload(sid, payload)
        return payload

    job_id = submit_job("upload", _job, session_id=sid)
    return {"job_id": job_id, "session_id": sid}


@app.post("/api/sample")
def sample() -> dict:
    """داده‌ی نمونه (سریع؛ بدون job) — همان قرارداد نتیجه‌ی آپلود."""
    df = generate_synthetic_sales()
    sid = store.create_session("داده‌ی نمونه")
    store.save_raw(sid, df)
    payload = _columns_payload(df)
    payload["session_id"] = sid
    payload["sheets"] = ["نمونه"]
    store.set_columns_payload(sid, payload)
    return payload


# ---------------------------------------------------------------- تحلیل (job)
class AnalyzeRequest(BaseModel):
    session_id: str
    mapping: dict[str, str]  # role -> column name
    horizon: int = 6
    balanced_uplift: float = 0.10
    file_currency: str = "تومان"
    display_currency: str = "تومان"


def _validate_clean(clean) -> str | None:
    date_col = standard_column(ColumnRole.DATE)
    rev_col = standard_column(ColumnRole.REVENUE)
    if clean is None or len(clean) == 0:
        return ("بعد از پاک‌سازی داده‌ها هیچ ردیف معتبری باقی نمانده است. لطفاً ستون‌های "
                "تاریخ، مبلغ، محصول و مشتری/موبایل را بررسی کنید.")
    if date_col not in clean.columns or clean[date_col].notna().sum() == 0:
        return "ستون اجباری «تاریخ» پیدا نشد یا داده‌ی معتبر (قابل‌تبدیل به تاریخ) ندارد."
    if rev_col not in clean.columns or clean[rev_col].notna().sum() == 0:
        return "ستون اجباری «مبلغ/درآمد» پیدا نشد یا داده‌ی عددی معتبر ندارد."
    return None


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    session = store.get_session(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="نشست یافت نشد یا منقضی شده است.")
    logger.info("analyze: session=%s mapping=%s horizon=%s",
                req.session_id, req.mapping, req.horizon)

    try:
        mapping = {ColumnRole(role): col for role, col in req.mapping.items() if col}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"نقش نامعتبر در نگاشت: {e}") from e

    if req.file_currency not in CURRENCIES or req.display_currency not in CURRENCIES:
        raise HTTPException(
            status_code=400,
            detail="واحد پول نامعتبر است؛ فقط «تومان» یا «ریال» مجاز است.",
        )

    missing = [ROLE_LABELS_FA[r.value] for r in REQUIRED_ROLES if r not in mapping]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"نگاشت ناقص: ستون‌های اجباری انتخاب نشده‌اند: {', '.join(missing)}",
        )

    columns = (session.columns_payload or {}).get("columns")
    if columns is None:
        raise HTTPException(status_code=409, detail="پردازش فایل هنوز کامل نشده است؛ کمی صبر کنید.")
    for role, col in mapping.items():
        if col not in columns:
            raise HTTPException(
                status_code=400,
                detail=f"ستون «{col}» برای نقش «{ROLE_LABELS_FA.get(role.value, role.value)}» در فایل وجود ندارد.",
            )

    sid = req.session_id

    def _job(progress) -> dict:
        raw = store.load_raw(sid)
        if raw is None:
            raise JobError("داده‌ی خام نشست یافت نشد؛ لطفاً فایل را دوباره بارگذاری کنید.")

        progress(8, "اعمال نگاشت ستون‌ها")
        try:
            std = SchemaMapper().apply(raw, mapping)
        except Exception as e:
            raise JobError(f"خطا در اعمال نگاشت ستون‌ها: {e}") from e

        progress(18, "پاک‌سازی و استانداردسازی داده")
        try:
            clean = clean_frame(std)
        except Exception as e:
            raise JobError(f"خطا در پاک‌سازی داده‌ها: {e}") from e
        logger.info("analyze job: clean -> %d rows", len(clean))

        err = _validate_clean(clean)
        if err:
            raise JobError(err)

        # تبدیل واحد پول (بعد از اعتبارسنجی تا پیام‌ها درباره‌ی داده‌ی خام باشند)
        factor = conversion_factor(req.file_currency, req.display_currency)
        clean = convert_monetary_columns(clean, factor)

        progress(30, "تحلیل جامع (KPI، سگمنت، چرخه، پیش‌بینی…)")
        try:
            bundle = run_analysis(clean, horizon=req.horizon,
                                  balanced_uplift=req.balanced_uplift)
        except Exception as e:
            raise JobError(f"خطا در مرحله‌ی تحلیل ({type(e).__name__}): {e}") from e

        bundle.meta["currency"] = req.display_currency
        bundle.meta["file_currency"] = req.file_currency
        bundle.meta["currency_factor"] = factor

        progress(90, "ذخیره‌ی نتایج")
        store.save_clean(sid, clean)
        store.save_side_frame(sid, "returns", get_returns(clean))
        store.save_side_frame(sid, "exclusions", get_exclusions(clean))
        store.save_bundle(sid, bundle)
        store.set_mapping(sid, {r.value: c for r, c in mapping.items()})
        sig = (store.get_session(sid).columns_payload or {}).get("header_signature")
        if sig:
            store.upsert_mapping_profile(
                sig, columns=(store.get_session(sid).columns_payload or {}).get("columns", []),
                mapping={r.value: c for r, c in mapping.items()},
                file_currency=req.file_currency, display_currency=req.display_currency,
            )

        payload = bundle_to_dict(bundle, currency=req.display_currency)
        payload["quality"]["warnings"] = profile_frame(clean).warnings
        cp = store.get_session(sid).columns_payload or {}

        # ثبت در دفتر کل canonical — بعد از ذخیره‌ی نتیجه و با جداسازی کامل خطا،
        # پس هیچ شکستی در این مسیر به تحلیل و داشبورد سرایت نمی‌کند.
        progress(94, "ثبت در دفتر کل")
        canonical = record_analysis(
            clean, bundle,
            session_id=sid,
            filename=store.get_session(sid).filename,
            dataset_key=cp.get("file_sha256"),
            sheet_name=(cp.get("sheets") or [""])[0] or "",
            display_currency=req.display_currency,
            file_currency=req.file_currency,
        )
        if canonical is not None:
            payload["canonical"] = canonical

        payload["manifest"] = {
            "source_file": store.get_session(sid).filename,
            "file_sha256": cp.get("file_sha256"),
            "file_size": cp.get("file_size"),
            "sheet": (cp.get("sheets") or [None])[0],
            "raw_rows": cp.get("n_rows"),
            "clean_rows": int(len(clean)),
            "returns_rows": int(clean.attrs.get("n_returns", 0)),
            "excluded_rows": int(clean.attrs.get("dropped_invalid_rows", 0))
            + int(clean.attrs.get("dropped_duplicate_rows", 0)),
            "file_currency": req.file_currency,
            "display_currency": req.display_currency,
            "pipeline_version": PIPELINE_VERSION,
            "analyzed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        store.set_analysis(sid, payload)
        return payload

    job_id = submit_job("analyze", _job, session_id=sid)
    return {"job_id": job_id}


# ---------------------------------------------------------- job و بازیابی نشست
# watchdog: اگر job زنده این‌قدر ثانیه بدون ضربان بماند → خطای شفاف به‌جای انتظار ابدی.
# strategy/campaign یک فراخوانی AI تک‌مرحله‌ای چنددقیقه‌ای دارند و analyze در طول
# run_analysis ساکت است؛ upload با progress استریمی هر ≤۰٫۵ ثانیه ضربان دارد.
_STALE_BY_KIND = {"analyze": 900, "strategy": 900, "campaign": 900}
_STALE_ERROR_FA = (
    "پردازش پاسخ نمی‌دهد؛ احتمالاً حافظه‌ی سرور پر شده یا سرور ری‌استارت شده است. "
    "سرور را بررسی کنید و دوباره تلاش کنید."
)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job یافت نشد.")
    if job.status in ("queued", "running"):
        stale_after = _STALE_BY_KIND.get(job.kind, get_settings().mkt_job_stale_seconds)
        if time.time() - job.updated_at > stale_after:
            if store.mark_stale_job(job.id, _STALE_ERROR_FA):
                logger.warning("watchdog: job %s(%s) بدون ضربان بود و خطا علامت خورد",
                               job.kind, job.id)
            job = store.get_job(job.id) or job
    out: dict = {
        "id": job.id, "kind": job.kind, "status": job.status,
        "progress": round(job.progress, 1), "stage": job.stage,
    }
    if job.status == "error":
        out["error"] = job.error or "خطای نامشخص"
    if job.status == "done":
        out["result"] = job.result
    return out


@app.get("/api/sessions")
def list_sessions(limit: int = 20, offset: int = 0, analyzed: bool = False) -> dict:
    """فهرست تحلیل‌های ذخیره‌شده (سبک — بدون پارس کردن نتیجه‌ی کامل تحلیل)."""
    items, total = store.list_sessions(
        limit=max(1, min(limit, 100)), offset=max(0, offset), analyzed_only=analyzed)
    return {
        "items": items,
        "total": total,
        "latest_analyzed_id": store.latest_session_with_analysis(),
        "retention": get_settings().retention_policy,
    }


@app.get("/api/session/{session_id}")
def session_info(session_id: str) -> dict:
    """بازیابی وضعیت نشست برای فرانت (بعد از reload/ری‌استارت/بستن تب)."""
    session = store.get_session(session_id)
    if session is None:
        return {"exists": False}
    if session.has_analysis:
        store.touch_opened(session_id)
    return {
        "exists": True,
        "created_at": session.created_at,
        "filename": session.filename,
        "label": getattr(session, "label", None),
        "archived": store.is_archived(session_id),
        "files": store.session_files(session_id),
        "mapping": session.mapping,
        "columns_payload": session.columns_payload,
        "analysis": session.analysis,
        "strategy": session.strategy,
        "campaign": session.campaign,
    }


@app.delete("/api/session/{session_id}")
def delete_session(session_id: str) -> dict:
    """حذف کامل و دائمی یک تحلیل (تنها راه حذف — سیستم خودش حذف نمی‌کند)."""
    if not store.delete_session(session_id):
        raise HTTPException(status_code=404,
                            detail="این نشست پیدا نشد؛ ممکن است قبلاً حذف شده باشد.")
    return {"deleted": True}


class SessionLabelRequest(BaseModel):
    label: str | None = None


@app.patch("/api/session/{session_id}")
def rename_session(session_id: str, req: SessionLabelRequest = Body(...)) -> dict:
    """نام دلخواه برای تحلیل (مثلاً «فروش شهریور ۱۴۰۴»)."""
    label = (req.label or "").strip() or None
    if label is not None and len(label) > 80:
        raise HTTPException(status_code=400, detail="نام انتخابی طولانی است (حداکثر ۸۰ نویسه).")
    if not store.set_label(session_id, label):
        raise HTTPException(status_code=404, detail="این نشست پیدا نشد.")
    items, _ = store.list_sessions(limit=100)
    item = next((i for i in items if i["id"] == session_id), None)
    return item or {"id": session_id, "label": label}


@app.get("/api/storage")
def storage_info() -> dict:
    """محل واقعی «حافظه»ی سیستم و مصرف فضا (برای رفع ابهام مسیر داده)."""
    s = get_settings()
    items, total = store.list_sessions(limit=1)
    sessions_bytes = 0
    for p in store.sessions_dir.rglob("*"):
        if p.is_file():
            sessions_bytes += p.stat().st_size
    db_size = store.db_path.stat().st_size if store.db_path.exists() else 0
    return {
        "data_dir": str(store.data_dir.resolve()),
        "db_path": str(store.db_path.resolve()),
        "db_size": db_size,
        "sessions_total": total,
        "sessions_bytes": sessions_bytes,
        "sessions_mb": round(sessions_bytes / 1024 / 1024, 1),
        "retention": s.retention_policy,
    }


# ------------------------------------------------------------- هوش مصنوعی (job)
class StrategyRequest(BaseModel):
    session_id: str


_ARCHIVED_FA = (
    "داده‌های سنگین این تحلیل برای آزاد کردن فضا بایگانی شده‌اند. داشبورد و اعداد "
    "کامل‌اند، اما برای گزارش PDF، خروجی اکسل، استراتژی هوش مصنوعی و پیامک باید "
    "همان فایل را دوباره بارگذاری و تحلیل کنید."
)


def _require_analyzed(session_id: str):
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="این نشست پیدا نشد؛ ممکن است حذف شده باشد. فایل را دوباره بارگذاری کنید.",
        )
    if not session.has_analysis:
        raise HTTPException(status_code=404, detail="ابتدا تحلیل را اجرا کنید.")
    return session


def _require_heavy(session_id: str) -> None:
    """گارد فایل‌های سنگین: پیام روشن به‌جای «تحلیل را دوباره اجرا کنید»."""
    if store.is_archived(session_id) or not store.session_files(session_id)["heavy"]:
        raise HTTPException(status_code=410, detail=_ARCHIVED_FA)


def _require_publishable(session_id: str) -> None:
    """در وضعیت FAIL، تولید استراتژی/کمپین AI مجاز نیست (تحلیل اکتشافی است)."""
    session = store.get_session(session_id)
    status = ((session.analysis or {}).get("validation") or {}).get("status") if session else None
    if status == "FAIL":
        raise HTTPException(
            status_code=409,
            detail="کنترل‌های صحت داده FAIL شده‌اند؛ پیش از تولید استراتژی، هشدارهای کیفیت را برطرف کنید.",
        )


@app.post("/api/strategy")
def strategy(req: StrategyRequest = Body(...)) -> dict:
    _require_analyzed(req.session_id)
    _require_heavy(req.session_id)
    _require_publishable(req.session_id)
    if not api_key_available():
        raise HTTPException(status_code=503, detail="کلید ANTHROPIC_API_KEY تنظیم نشده است.")
    sid = req.session_id

    def _job(progress) -> dict:
        bundle = store.load_bundle(sid)
        if bundle is None:
            raise JobError("نتیجه‌ی تحلیل یافت نشد؛ تحلیل را دوباره اجرا کنید.")
        progress(15, "تحلیل مدیر مارکتینگ در حال نگارش استراتژی…")
        from mktcore.ai.strategist import generate_strategy

        try:
            report = generate_strategy(bundle)
        except Exception as e:
            raise JobError(f"خطا در تولید استراتژی: {e}") from e
        result = strategy_to_dict(report)
        store.set_strategy(sid, result)
        return result

    return {"job_id": submit_job("strategy", _job, session_id=sid)}


@app.post("/api/campaign")
def campaign(req: StrategyRequest = Body(...)) -> dict:
    _require_analyzed(req.session_id)
    if not api_key_available():
        raise HTTPException(status_code=503, detail="کلید ANTHROPIC_API_KEY تنظیم نشده است.")
    sid = req.session_id

    def _job(progress) -> dict:
        bundle = store.load_bundle(sid)
        if bundle is None:
            raise JobError("نتیجه‌ی تحلیل یافت نشد؛ تحلیل را دوباره اجرا کنید.")
        progress(15, "طراحی کمپین و نگارش پیام‌های شخصی‌سازی‌شده…")
        from mktcore.ai.campaign import generate_campaigns

        try:
            plan = generate_campaigns(bundle)
        except Exception as e:
            raise JobError(f"خطا در تولید کمپین: {e}") from e
        result = campaign_to_dict(plan)
        store.set_campaign(sid, result)
        return result

    return {"job_id": submit_job("campaign", _job, session_id=sid)}


# ------------------------------------------------------------------- گزارش PDF
@app.get("/api/report")
def report(session_id: str, fmt: str = "pdf"):
    session = _require_analyzed(session_id)
    _require_heavy(session_id)
    bundle = store.load_bundle(session_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="نتیجه‌ی تحلیل یافت نشد؛ تحلیل را دوباره اجرا کنید.")

    strategy_obj = campaign_obj = None
    if session.strategy:
        from mktcore.ai.schemas import StrategyReport

        strategy_obj = StrategyReport.model_validate(session.strategy)
    if session.campaign:
        from mktcore.ai.schemas import CampaignPlan

        campaign_obj = CampaignPlan.model_validate(session.campaign)

    from mktcore.reporting.pdf_report import build_pdf, render_html, weasyprint_available

    if fmt == "html" or not weasyprint_available():
        return HTMLResponse(content=render_html(bundle, strategy_obj, campaign_obj))
    pdf = build_pdf(bundle, strategy_obj, campaign_obj)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=marketing_report.pdf"},
    )


# ------------------------------------------------------------- خروجی اکسل
@app.get("/api/export")
def export_excel(session_id: str, section: str):
    """خروجی اکسل یک بخش داشبورد (سگمنت‌ها/پیش‌بینی خرید/محصولات/تشخیص و تأمین)."""
    if section not in EXPORT_SECTIONS:
        raise HTTPException(status_code=400, detail="بخش نامعتبر برای خروجی اکسل.")
    _require_analyzed(session_id)
    _require_heavy(session_id)
    bundle = store.load_bundle(session_id)
    clean = store.load_clean(session_id)
    if bundle is None or clean is None:
        raise HTTPException(
            status_code=404,
            detail="داده‌ی تحلیل نشست یافت نشد؛ تحلیل را دوباره اجرا کنید.",
        )
    try:
        extras = None
        if section == "audit":
            extras = {
                "exclusions": store.load_side_frame(session_id, "exclusions"),
                "returns": store.load_side_frame(session_id, "returns"),
            }
        content = build_export(section, bundle, clean, extras)
    except EmptySection as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    fa_name = quote(f"{EXPORT_FA_NAMES[section]}.xlsx")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition":
                f'attachment; filename="{section}.xlsx"; filename*=UTF-8\'\'{fa_name}',
        },
    )


# ------------------------------------------------------------- اجرای پیامکی
@app.get("/api/audience-kinds")
def audience_kinds() -> dict:
    return {"kinds": [{"key": k, "label": v} for k, v in AUDIENCE_KINDS.items()]}


class SMSRequest(BaseModel):
    session_id: str
    kind: str
    template: str
    limit: int = 100
    dry_run: bool = True
    confirm: bool = False  # برای ارسال واقعی، تأیید صریح لازم است


@app.post("/api/sms/send")
def sms_send(req: SMSRequest) -> dict:
    """ساخت مخاطب، شخصی‌سازی پیام و ارسال.

    ارسال واقعی فقط وقتی انجام می‌شود که پنل پیامکی در env فعال/پیکربندی شده
    باشد (MKT_SMS_ENABLE=1 + KAVENEGAR_API_KEY) و درخواست dry_run=false و
    confirm=true بدهد؛ در غیر این صورت پیش‌نمایش امن برگردانده می‌شود.
    """
    _require_analyzed(req.session_id)
    if req.kind not in AUDIENCE_KINDS:
        raise HTTPException(status_code=400, detail="نوع مخاطب نامعتبر است.")

    bundle = store.load_bundle(req.session_id)
    clean = store.load_clean(req.session_id)
    if bundle is None or clean is None:
        raise HTTPException(status_code=404, detail="داده‌ی تحلیل نشست یافت نشد.")

    recipients = build_audience(bundle, req.kind, df=clean, limit=req.limit)

    # دروازه‌ی مجوز تماس. پیش از این، این مسیر **هیچ** بررسی‌ای نداشت: می‌توانست
    # به عضوِ گروه کنترلِ یک آزمایشِ فعال پیام بدهد و نتیجه‌ی آن آزمایش را بی‌صدا
    # نابود کند — بی‌صدا، چون هیچ‌جا ثبت نمی‌شد که با کنترل تماس گرفته شده.
    gate = load_gate(
        recently_contacted=store.recent_contact_customer_ids(DEFAULT_FATIGUE_WINDOW_DAYS),
        fatigue_window_days=DEFAULT_FATIGUE_WINDOW_DAYS,
    )
    screened = gate.partition(
        recipients, key=lambda r: r.customer_id, phone=lambda r: r.phone,
    )
    recipients = screened.allowed
    messages = render_messages(req.template, recipients)

    settings = get_settings()
    wants_real = not req.dry_run
    real_send = wants_real and req.confirm and settings.sms_configured
    note = None
    if wants_real and not real_send:
        if not settings.sms_configured:
            note = ("ارسال واقعی غیرفعال است: MKT_SMS_ENABLE=1 و KAVENEGAR_API_KEY را در "
                    "تنظیمات سرور قرار دهید. نتیجه به‌صورت آزمایشی برگردانده شد.")
        elif not req.confirm:
            note = "برای ارسال واقعی، تأیید صریح (confirm=true) لازم است. نتیجه آزمایشی است."

    result = send_campaign(
        messages,
        provider=settings.mkt_sms_provider,
        api_key=settings.kavenegar_api_key if real_send else None,
        sender=settings.mkt_sms_sender,
        dry_run=not real_send,
    )

    status_of = {d.get("مشتری"): d.get("وضعیت", "") for d in result.details}
    for m in messages:
        store.add_outbox(
            kind="campaign_sms", session_id=req.session_id, audience=req.kind,
            customer_id=m.customer_id, phone=m.phone, message=m.text,
            status=status_of.get(m.customer_id, "نامشخص"),
            provider=result.provider, dry_run=result.dry_run,
        )

    out = {"audience_size": len(recipients), **result.to_dict(), **screened.to_dict()}
    if note:
        out["توضیح"] = note
    # حذفِ بی‌صدا ممنوع: اگر کسی از فهرست کنار گذاشته شد، گفته می‌شود چند نفر و چرا.
    suppression_note = screened.note_fa()
    if suppression_note:
        out["یادداشت_مجوز_تماس"] = suppression_note
    return out


# --------------------------------------------------------- زمان‌بند و outbox
@app.get("/api/outbox")
def outbox(limit: int = 50) -> dict:
    return {"items": store.list_outbox(limit=min(limit, 200))}


@app.get("/api/scheduler/status")
def get_scheduler_status() -> dict:
    return scheduler_status()


@app.post("/api/scheduler/run-now")
def scheduler_run_now() -> dict:
    """اجرای دستی اسکن چرخه (برای تست/راه‌اندازی)."""
    return run_cycle_scan()


__all__ = ["app"]

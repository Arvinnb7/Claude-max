"""مسیرهای رجیستری مدل — §۲۶.۴ سند.

```
GET  /api/v1/models                    فهرست اجراها
GET  /api/v1/models/{id}               جزئیات یک اجرا
POST /api/v1/models/train              آموزش (توکن)
POST /api/v1/models/{id}/validate      اعتبارسنجی (توکن)
POST /api/v1/models/{id}/promote       فعال‌سازی (توکن)
POST /api/v1/models/{id}/rollback      بازگشت (توکن)
GET  /api/v1/models/{id}/metrics       سنجه‌ها
GET  /api/v1/models/{id}/drift         انحراف
```

**چرا «داده کافی نبود» با کد ۲۰۰ برمی‌گردد.** درخواست معتبر بوده و پاسخْ یک
جوابِ درست است: «با این داده نمی‌شود مدلِ بامعنا ساخت». خطای ۴xx یعنی کاربر
اشتباه کرده، که اینجا درست نیست. در عوض `trained: false` و دلیل و جدولِ «لازم
در برابر موجود» برمی‌گردد.

**چرا promote توکن می‌خواهد.** §۲۶.۴: «Promotion must require validation status
and authorization». همان توکنی که جلوی ارسال واقعی پیامک را می‌گیرد.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from mktcore.db.engine import session_scope  # noqa: E402
from mktcore.db.lookup import active_business_id  # noqa: E402
from mktcore.db.migrations import ensure_schema  # noqa: E402
from mktcore.db.models import ModelRun  # noqa: E402
from mktcore.ml.registry import (  # noqa: E402
    MODEL_KEYS,
    list_runs,
    promote_run,
    promoted_run,
    rollback_run,
    run_to_dict,
)
from mktcore.ml.train import available_trainers, train_model  # noqa: E402
from mktcore.security import require_token  # noqa: E402

router = APIRouter(prefix="/api/v1/models", tags=["models"])

_DEFAULT_SLUG = "default"


def _business_id(session) -> int | None:
    return active_business_id(session, fallback_slug=_DEFAULT_SLUG)


def _no_ledger_yet() -> dict:
    return {
        "available": False,
        "note_fa": (
            "هنوز تحلیلی در دفتر کل ثبت نشده است؛ بدون داده، مدلی هم وجود ندارد."
        ),
    }


def _run_or_404(session, run_id: int) -> ModelRun:
    run = session.get(ModelRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="این اجرای مدل یافت نشد.")
    return run


class TrainRequest(BaseModel):
    model_key: str = Field(min_length=1, max_length=64)
    # پارامترهای دلخواه (پنجره‌ها، صدک، آستانه‌ها). خالی یعنی پیش‌فرضِ محافظه‌کار.
    params: dict | None = None


@router.get("")
def list_model_runs(
    model_key: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """فهرست اجراها + اینکه هر نوع مدل الان چه چیزی فعال دارد."""
    ensure_schema()
    with session_scope() as session:
        business_id = _business_id(session)
        if business_id is None:
            return {**_no_ledger_yet(), "items": [], "active": {}}
        runs = list_runs(
            session, business_id, model_key=model_key, status=status, limit=limit,
        )
        items = [run_to_dict(run) for run in runs]
        active = {
            key: (run_to_dict(run) if run else None)
            for key in MODEL_KEYS
            for run in [promoted_run(session, business_id, key)]
        }
    return {
        "available": True,
        "items": items,
        "active": active,
        "trainable": list(available_trainers()),
        "note_fa": (
            "مدلی که «فعال» نباشد هیچ اثری بر رفتار سیستم ندارد؛ رتبه‌بندی و "
            "امتیازها تا لحظه‌ی فعال‌سازی دقیقاً مثل قبل می‌مانند."
        ),
    }


@router.get("/{run_id}")
def get_model_run(run_id: int) -> dict:
    ensure_schema()
    with session_scope() as session:
        run = _run_or_404(session, run_id)
        return run_to_dict(run, with_model=True)


@router.post("/train", dependencies=[Depends(require_token)])
def train(payload: TrainRequest) -> dict:
    """آموزش یک مدل. «داده کافی نبود» هم یک پاسخِ موفق است، نه خطا."""
    ensure_schema()
    try:
        result = train_model(payload.model_key, params=payload.params)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result


@router.post("/{run_id}/validate", dependencies=[Depends(require_token)])
def validate(run_id: int) -> dict:
    """گزارشِ اینکه این اجرا دروازه‌ی پذیرش را رد کرده یا نه.

    خودِ اعتبارسنجی در لحظه‌ی آموزش انجام می‌شود (چون به دادهٔ همان لحظه گره
    خورده)؛ این مسیر همان حکم را برمی‌گرداند و وضعیت را صریح می‌کند.
    """
    ensure_schema()
    with session_scope() as session:
        run = _run_or_404(session, run_id)
        payload = run_to_dict(run)
    payload["validated"] = payload["status"] in (
        ModelRun.STATUS_VALIDATED, ModelRun.STATUS_PROMOTED,
    )
    payload["note_fa"] = (
        "این اجرا خط پایه را برده و آماده‌ی فعال‌سازی است."
        if payload["validated"] else
        payload.get("blocked_reason_fa")
        or "این اجرا اعتبارسنجی را نگذرانده است؛ فعال‌سازی‌اش مجاز نیست."
    )
    return payload


@router.post("/{run_id}/promote", dependencies=[Depends(require_token)])
def promote(run_id: int, actor: str | None = Query(default=None)) -> dict:
    ensure_schema()
    try:
        return promote_run(run_id, actor=actor)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{run_id}/rollback", dependencies=[Depends(require_token)])
def rollback(run_id: int, actor: str | None = Query(default=None)) -> dict:
    ensure_schema()
    try:
        return rollback_run(run_id, actor=actor)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{run_id}/metrics")
def metrics(run_id: int) -> dict:
    ensure_schema()
    with session_scope() as session:
        run = _run_or_404(session, run_id)
        payload = run_to_dict(run, with_model=True)
    return {
        "id": payload["id"],
        "model_key": payload["model_key"],
        "status": payload["status"],
        "metrics": payload["metrics"],
        "calibration": payload.get("calibration"),
        "train_window": payload["train_window"],
        "validate_window": payload["validate_window"],
        "blocked_reason_fa": payload["blocked_reason_fa"],
    }


@router.get("/{run_id}/drift")
def drift(run_id: int) -> dict:
    """انحرافِ توزیع نسبت به لحظه‌ی آموزش (§۲۹.۷).

    تا وقتی سنجش drift پیاده نشده، این مسیر **صریح می‌گوید نسنجیده**؛ برگرداندن
    «پایدار» بدون سنجش، دقیقاً همان دروغی است که این پروژه ممنوع کرده.
    """
    ensure_schema()
    with session_scope() as session:
        run = _run_or_404(session, run_id)
        payload = run_to_dict(run, with_model=True)
    return {
        "id": payload["id"],
        "model_key": payload["model_key"],
        "measured": False,
        "baseline_recorded": payload.get("drift_baseline") is not None,
        "note_fa": (
            "خط‌پایه‌ی انحراف در لحظه‌ی آموزش ثبت شده، ولی سنجشِ انحراف هنوز "
            "اجرا نمی‌شود. تا آن زمان این مسیر «پایدار» گزارش نمی‌کند — نسنجیده "
            "را پایدار نامیدن، همان اشتباهی است که سنجه را بی‌اعتبار می‌کند."
        ),
    }


__all__ = ["router"]

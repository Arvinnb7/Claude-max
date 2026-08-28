"""چرخه‌ی عمرِ اجراهای مدل — ثبت، اعتبارسنجی، promote، بازگشت.

§۲۶.۴ می‌گوید «Promotion must require validation status and authorization».
اینجا نیمه‌ی اولش اجرا می‌شود (وضعیت)؛ نیمه‌ی دومش (توکن) در لایه‌ی API.

**قاعده‌ی قهرمان/مدعی.** هر اجرا تا وقتی promote نشده هیچ اثری بر رفتار سیستم
ندارد. یعنی افزودن یک مدلِ تازه به این پروژه **به‌خودی‌خود بی‌خطر است**؛ خطر
فقط در لحظه‌ی promote است و آن لحظه دروازه‌ی صریح دارد.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from mktcore.db.base import now_ts
from mktcore.db.engine import session_scope, write_lock
from mktcore.db.lookup import resolve_business_id
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import ModelRun

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

logger = logging.getLogger("mktcore.ml.registry")

MODEL_KEYS: tuple[str, ...] = ("whale", "churn", "replenish", "nbp_rank")

MODEL_LABELS_FA = {
    "whale": "نهنگ آینده",
    "churn": "ریسک ریزش",
    "replenish": "تکرار خرید",
    "nbp_rank": "رتبه‌بندی پیشنهاد کالا",
}

STATUS_LABELS_FA = {
    ModelRun.STATUS_INSUFFICIENT: "داده کافی نبود",
    ModelRun.STATUS_TRAINED: "آموزش‌دیده",
    ModelRun.STATUS_VALIDATED: "اعتبارسنجی‌شده",
    ModelRun.STATUS_REJECTED: "رد شد (خط پایه را نبرد)",
    ModelRun.STATUS_PROMOTED: "فعال",
    ModelRun.STATUS_ROLLED_BACK: "بازگردانده‌شده",
    ModelRun.STATUS_SUPERSEDED: "جایگزین‌شده",
}


def code_version() -> str:
    """نسخه‌ی کدِ آموزش‌دهنده (§۷.۶).

    از متادیتای پکیج خوانده می‌شود؛ نبودش نباید آموزش را بخواباند، پس مقدار
    صریحِ «نامعلوم» برمی‌گردد نه رشته‌ی خالی.
    """
    try:
        from importlib.metadata import version

        return f"mktcore {version('mktcore')}"
    except Exception:  # noqa: BLE001 - نصبِ غیرپکیجی (اجرا از سورس)
        return "mktcore (source)"


def compute_data_hash(
    *,
    business_id: int,
    model_key: str,
    train_start: str | None,
    train_end: str | None,
    n_lines: int,
    sum_revenue_rial: int,
    sum_gross_profit_rial: int | None,
) -> str:
    """هشِ **آنچه روی آن آموزش دیدیم** — نه بایت‌های فایل.

    فایل‌ها دوباره وارد می‌شوند و `revision` بالا می‌رود بی‌آنکه داده عوض شود؛
    هشِ بایت هر بار بی‌دلیل تغییر می‌کرد. در عوض جمعِ سود هم در هش هست: ورودِ
    دوباره‌ی فایل بها درآمد را عوض نمی‌کند ولی سود را عوض می‌کند، و مدلی که
    برچسبش سودمحور است باید با آن باطل شود.
    """
    raw = (
        f"{business_id}|{model_key}|{train_start}|{train_end}|{n_lines}|"
        f"{sum_revenue_rial}|{sum_gross_profit_rial if sum_gross_profit_rial is not None else 'none'}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:48]


def _next_version(session: Session, business_id: int, model_key: str) -> int:
    current = session.scalar(
        select(func.max(ModelRun.model_version)).where(
            ModelRun.business_id == business_id, ModelRun.model_key == model_key,
        )
    )
    return int(current or 0) + 1


def record_run(
    *,
    business_slug: str = "default",
    model_key: str,
    status: str,
    model_kind: str = "logistic_l2",
    db_path: Path | None = None,
    **fields: Any,
) -> dict:
    """ثبتِ یک اجرا — چه موفق، چه «داده کافی نبود».

    ثبتِ امتناع عمدی است: §۲۹.۶ حالتِ صریحِ داده‌ی ناکافی می‌خواهد و یک استثنا
    فردا نامرئی است.
    """
    if model_key not in MODEL_KEYS:
        raise ValueError(f"کلید مدل ناشناخته: {model_key}")
    ensure_schema(db_path)
    with write_lock, session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            raise ValueError("کسب‌وکاری ثبت نشده است؛ اول یک فایل فروش تحلیل کنید.")

        run = ModelRun(
            business_id=business_id,
            model_key=model_key,
            model_kind=model_kind,
            model_version=_next_version(session, business_id, model_key),
            code_version=fields.pop("code_version", None) or code_version(),
            status=status,
            **{k: _as_json(v) for k, v in fields.items()},
        )
        session.add(run)
        session.flush()
        payload = run_to_dict(run)
    logger.info("اجرای مدل ثبت شد: %s نسخه %s (%s)", model_key, payload["model_version"], status)
    return payload


def _as_json(value: Any) -> Any:
    """دیکشنری/فهرست را به JSON تبدیل می‌کند؛ بقیه دست‌نخورده می‌مانند."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def list_runs(
    session: Session,
    business_id: int,
    *,
    model_key: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[ModelRun]:
    stmt = select(ModelRun).where(ModelRun.business_id == business_id)
    if model_key:
        stmt = stmt.where(ModelRun.model_key == model_key)
    if status:
        stmt = stmt.where(ModelRun.status == status)
    return list(session.scalars(stmt.order_by(ModelRun.id.desc()).limit(limit)).all())


def latest_run(session: Session, business_id: int, model_key: str) -> ModelRun | None:
    return session.scalar(
        select(ModelRun)
        .where(ModelRun.business_id == business_id, ModelRun.model_key == model_key)
        .order_by(ModelRun.id.desc())
        .limit(1)
    )


def promoted_run(session: Session, business_id: int, model_key: str) -> ModelRun | None:
    """مدلِ فعال. `None` یعنی هیچ مدلی promote نشده — و آن‌وقت امتیازی نوشته نمی‌شود."""
    return session.scalar(
        select(ModelRun)
        .where(
            ModelRun.business_id == business_id,
            ModelRun.model_key == model_key,
            ModelRun.promoted.is_(True),
        )
        .order_by(ModelRun.promoted_at.desc())
        .limit(1)
    )


def promote_run(run_id: int, *, actor: str | None = None, db_path: Path | None = None) -> dict:
    """فعال‌کردنِ یک اجرا. فقط اجرای **اعتبارسنجی‌شده** promote می‌شود."""
    ensure_schema(db_path)
    with write_lock, session_scope(db_path) as session:
        run = session.get(ModelRun, run_id)
        if run is None:
            raise LookupError("این اجرای مدل یافت نشد.")
        if run.status not in (ModelRun.STATUS_VALIDATED, ModelRun.STATUS_ROLLED_BACK):
            raise PermissionError(
                f"فقط اجرای اعتبارسنجی‌شده promote می‌شود؛ وضعیت این اجرا "
                f"«{STATUS_LABELS_FA.get(run.status, run.status)}» است."
            )
        if not run.coefficients_json:
            raise PermissionError(
                "این اجرا مدلی ندارد (ضرایبش خالی است)، پس چیزی برای فعال‌کردن نیست."
            )
        _demote_others(session, run)
        run.promoted = True
        run.promoted_at = now_ts()
        run.promoted_by = actor
        run.status = ModelRun.STATUS_PROMOTED
        session.flush()
        payload = run_to_dict(run)
    return payload


def rollback_run(run_id: int, *, actor: str | None = None, db_path: Path | None = None) -> dict:
    """بازگشت به نسخه‌ی قبلی — همان چیزی که §۲۶.۴ می‌خواهد.

    چون مدل در همان ردیف ذخیره شده، بازگشت یعنی فعال‌کردنِ ردیفِ قبلی؛ هیچ فایل
    یا آرتیفکتی جابه‌جا نمی‌شود.
    """
    ensure_schema(db_path)
    with write_lock, session_scope(db_path) as session:
        run = session.get(ModelRun, run_id)
        if run is None:
            raise LookupError("این اجرای مدل یافت نشد.")
        previous = session.scalar(
            select(ModelRun)
            .where(
                ModelRun.business_id == run.business_id,
                ModelRun.model_key == run.model_key,
                ModelRun.id != run.id,
                ModelRun.promoted_at.isnot(None),
                ModelRun.coefficients_json.isnot(None),
            )
            .order_by(ModelRun.promoted_at.desc())
            .limit(1)
        )
        if previous is None:
            raise LookupError(
                "هیچ نسخه‌ی قبلیِ فعال‌شده‌ای برای بازگشت وجود ندارد؛ این نخستین "
                "مدلِ این نوع است."
            )
        run.promoted = False
        run.status = ModelRun.STATUS_ROLLED_BACK
        run.rolled_back_at = now_ts()
        previous.promoted = True
        previous.promoted_at = now_ts()
        previous.promoted_by = actor
        previous.status = ModelRun.STATUS_PROMOTED
        previous.rollback_of_run_id = run.id
        session.flush()
        payload = run_to_dict(previous)
    return payload


def mark_scored(
    session: Session, run_id: int, *, n_scored: int,
) -> None:
    """ثبتِ «آخرین بار کِی امتیاز داد» — قلمِ §۲۷.۷ در صفحه‌ی سلامت مدل."""
    run = session.get(ModelRun, run_id)
    if run is None:
        return
    run.last_scored_at = now_ts()
    run.n_scored = int(n_scored)


def _demote_others(session: Session, run: ModelRun) -> None:
    others = session.scalars(
        select(ModelRun).where(
            ModelRun.business_id == run.business_id,
            ModelRun.model_key == run.model_key,
            ModelRun.promoted.is_(True),
            ModelRun.id != run.id,
        )
    ).all()
    for other in others:
        other.promoted = False
        other.status = ModelRun.STATUS_SUPERSEDED


def run_to_dict(run: ModelRun, *, with_model: bool = False) -> dict:
    """شکلِ پاسخِ API. ضرایب فقط وقتی می‌آیند که صریحاً خواسته شوند."""
    payload = {
        "id": run.id,
        "model_key": run.model_key,
        "model_label_fa": MODEL_LABELS_FA.get(run.model_key, run.model_key),
        "model_kind": run.model_kind,
        "model_version": run.model_version,
        "code_version": run.code_version,
        "feature_schema_version": run.feature_schema_version,
        "status": run.status,
        "status_label_fa": STATUS_LABELS_FA.get(run.status, run.status),
        "blocked_reason_code": run.blocked_reason_code,
        "blocked_reason_fa": run.blocked_reason_fa,
        "label_basis": run.label_basis,
        "train_window": [run.train_start, run.train_end],
        "validate_window": [run.validate_start, run.validate_end],
        "data_hash": run.data_hash,
        "n_train": run.n_train,
        "n_validate": run.n_validate,
        "n_train_positives": run.n_train_positives,
        "n_validate_positives": run.n_validate_positives,
        "metrics": _load_json(run.metrics_json),
        "promoted": bool(run.promoted),
        "promoted_at": run.promoted_at,
        "promoted_by": run.promoted_by,
        "rolled_back_at": run.rolled_back_at,
        "last_scored_at": run.last_scored_at,
        "n_scored": run.n_scored,
        "note_fa": run.note_fa,
        "created_at": run.created_at,
    }
    if with_model:
        payload["params"] = _load_json(run.params_json)
        payload["feature_schema"] = _load_json(run.feature_schema_json)
        payload["calibration"] = _load_json(run.calibration_json)
        payload["coefficients"] = _load_json(run.coefficients_json)
        payload["drift_baseline"] = _load_json(run.drift_baseline_json)
    return payload


def _load_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


__all__ = [
    "MODEL_KEYS",
    "MODEL_LABELS_FA",
    "STATUS_LABELS_FA",
    "code_version",
    "compute_data_hash",
    "latest_run",
    "list_runs",
    "mark_scored",
    "promote_run",
    "promoted_run",
    "record_run",
    "rollback_run",
    "run_to_dict",
]

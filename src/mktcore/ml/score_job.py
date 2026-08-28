"""نوشتنِ امتیازِ مدل‌های **فعال** روی تازه‌ترین عکسِ ویژگی.

یک تابع برای همه‌ی مدل‌ها، چون قاعده‌شان یکی است و باید یکی بماند:

* بدون مدلِ **فعال**، هیچ ستونی لمس نمی‌شود و `NULL` می‌ماند. `NULL` یعنی
  «مدلی نداریم»، نه «احتمال صفر» — و این تفاوت، تفاوتِ صداقت است.
* ویژگی‌ها در لحظه‌ی امتیازدهی از دفتر کل بازسازی می‌شوند، با همان گاردِ
  زمانی‌ای که در آموزش بود.
* شناسه‌ی اجرا و زمانِ امتیازدهی کنار عدد ذخیره می‌شوند، وگرنه فردا معلوم
  نیست این عدد از کدام مدل آمده (§۱۹ همین را برای CLV هم می‌خواهد).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import pandas as pd
from sqlalchemy import func, select

from mktcore.db.base import now_ts
from mktcore.db.engine import session_scope, write_lock
from mktcore.db.lookup import resolve_business_id
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import CustomerFeature
from mktcore.features.ledger_frame import load_line_frame
from mktcore.features.point_in_time import PointInTimeSpec, compute_point_in_time_features
from mktcore.ml.registry import mark_scored, promoted_run
from mktcore.ml.scoring import score_from_json, to_basis_points

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("mktcore.ml.score_job")


def write_customer_scores(
    *,
    model_key: str,
    probability_column: str,
    run_column: str,
    observation_days: int | None = None,
    business_slug: str = "default",
    db_path: Path | None = None,
) -> dict:
    """امتیازِ یک مدل را روی عکسِ ویژگیِ جاری می‌نویسد."""
    ensure_schema(db_path)
    with write_lock, session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            return {"scored": 0, "note_fa": "کسب‌وکاری ثبت نشده است."}

        run = promoted_run(session, business_id, model_key)
        if run is None or not run.coefficients_json:
            return {
                "scored": 0,
                "note_fa": (
                    f"هیچ مدلِ فعالی برای «{model_key}» وجود ندارد؛ امتیازی نوشته "
                    "نشد و ستون‌ها خالی ماندند."
                ),
            }

        lines = load_line_frame(session, business_id)
        if lines.empty:
            return {"scored": 0, "note_fa": "دفتر کل خالی است."}

        exclusive_end = (
            pd.Timestamp(str(lines["line_date"].max())) + pd.Timedelta(days=1)
        ).date().isoformat()
        features = compute_point_in_time_features(
            lines[lines["line_date"] < exclusive_end],
            PointInTimeSpec(
                as_of=exclusive_end, observation_days=observation_days,
                require_complete_window=True,
            ),
        )
        if features.empty:
            return {
                "scored": 0,
                "note_fa": "هیچ مشتری‌ای ویژگیِ کاملی برای امتیازدهی ندارد.",
            }

        probabilities = score_from_json(
            json.loads(run.coefficients_json),
            json.loads(run.calibration_json) if run.calibration_json else None,
            features,
        )
        by_customer = dict(
            zip(features.index, to_basis_points(probabilities), strict=False)
        )

        latest_as_of = session.scalar(
            select(func.max(CustomerFeature.as_of_date)).where(
                CustomerFeature.business_id == business_id
            )
        )
        if not latest_as_of:
            return {"scored": 0, "note_fa": "هنوز عکسِ ویژگی‌ای ثبت نشده است."}

        rows = session.scalars(
            select(CustomerFeature).where(
                CustomerFeature.business_id == business_id,
                CustomerFeature.as_of_date == latest_as_of,
            )
        ).all()
        stamp = now_ts()
        written = 0
        for row in rows:
            value = by_customer.get(row.customer_id)
            if value is None:
                continue
            setattr(row, probability_column, int(value))
            setattr(row, run_column, run.id)
            row.scored_at = stamp
            written += 1
        mark_scored(session, run.id, n_scored=written)
        session.flush()
        run_id = run.id

    logger.info("امتیاز «%s» روی %s مشتری نوشته شد (اجرای %s)", model_key, written, run_id)
    return {
        "scored": written,
        "model_run_id": run_id,
        "as_of": latest_as_of,
        "note_fa": f"امتیاز «{model_key}» برای {written} مشتری به‌روز شد.",
    }


__all__ = ["write_customer_scores"]

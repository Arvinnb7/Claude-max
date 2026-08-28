"""لایه‌ی مدل‌های پیش‌بین — رجیستری، آموزش، امتیازدهی.

عمداً `ml` نام گرفته و نه `models`، چون `db/models.py` از قبل وجود دارد و دو
`models` در یک پروژه، هر importی را مبهم می‌کند.

## قاعده‌ی حاکم بر کلِ این لایه

آنچه امروز کار می‌کند **قهرمان** است و مدلِ تازه **مدعی**. مدعی جای قهرمان را
نمی‌گیرد مگر روی holdoutِ زمانی و با سنجه‌ی اقتصادی از او جلو بزند (§۲۹.۳).
تا آن لحظه، رفتار سیستم بیت‌به‌بیت همان است که بود — و اگر مدعی هرگز نبرد،
هیچ‌چیز عوض نمی‌شود. رجیستری دقیقاً همین قاعده را اجرا می‌کند.
"""

from .registry import (
    MODEL_KEYS,
    latest_run,
    list_runs,
    promote_run,
    promoted_run,
    record_run,
    rollback_run,
)
from .scoring import score_from_json
from .serialize import calibration_to_json, linear_model_to_json

__all__ = [
    "MODEL_KEYS",
    "calibration_to_json",
    "latest_run",
    "linear_model_to_json",
    "list_runs",
    "promote_run",
    "promoted_run",
    "record_run",
    "rollback_run",
    "score_from_json",
]

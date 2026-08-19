"""طراحِ آزمایش: کدام گروه را بعد آزمایش کنیم، و با چه اندازه‌ای.

دو لایه، مثل `uplift/` و `contact/`:

* `design.py` — اولویت‌بندی و ریاضیِ اندازه‌ی نمونه، به‌صورت تابع خالص.
* `plan.py`   — خواندن عرضه‌ی واقعی از دفتر کل.
"""

from .design import (
    DEFAULT_HOLDOUT_PCT,
    DEFAULT_TARGET_EFFECT,
    CellSupply,
    ExperimentPlan,
    ExperimentSuggestion,
    build_plan,
)
from .plan import build_experiment_plan

__all__ = [
    "DEFAULT_HOLDOUT_PCT",
    "DEFAULT_TARGET_EFFECT",
    "CellSupply",
    "ExperimentPlan",
    "ExperimentSuggestion",
    "build_experiment_plan",
    "build_plan",
]

"""ویژگی‌های «نقطه‌ی زمانی» — آنچه در تاریخ T واقعاً می‌دانستیم.

سه ماژول با مرز روشن:

* `ledger_frame` — تنها جایی که به دیتابیس دست می‌زند، و **تنها جایی که گاردِ
  `as_of` زندگی می‌کند**.
* `point_in_time` — خالص: فریمِ خطوط می‌گیرد و ویژگی می‌دهد.
* `cohorts` — خالص: می‌گوید داده برای آموزش بالغ هست یا نه، و اگر نیست چرا.
"""

from .cohorts import CohortMaturity, MaturitySpec, assess_cohort_maturity
from .ledger_frame import load_line_frame
from .point_in_time import (
    PIT_FEATURE_SCHEMA,
    PIT_SCHEMA_VERSION,
    LeakageError,
    PointInTimeSpec,
    compute_outcome_window,
    compute_point_in_time_features,
)

__all__ = [
    "PIT_FEATURE_SCHEMA",
    "PIT_SCHEMA_VERSION",
    "CohortMaturity",
    "LeakageError",
    "MaturitySpec",
    "PointInTimeSpec",
    "assess_cohort_maturity",
    "compute_outcome_window",
    "compute_point_in_time_features",
    "load_line_frame",
]

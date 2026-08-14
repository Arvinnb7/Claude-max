"""ماشین حالت چرخه‌ی عمر مشتری.

یک مشتری همیشه دقیقاً **یک** حالت اصلی دارد، با قاعده‌ای شفاف و قابل توضیح.
سند صریحاً قاعده‌ی سراسری ۳۰/۶۰/۹۰ روز را رد می‌کند: «۴۵ روز بی‌خریدی» برای
مشتری‌ای که هر ماه می‌خرد یعنی عقب‌افتادگی، و برای مشتری‌ای که هر فصل می‌خرد
یعنی هیچ. پس آستانه‌ها **مضربی از آهنگ خرید خودِ مشتری‌اند**.
"""

from .states import (
    LIFECYCLE_STATES,
    STATE_LABELS_FA,
    LifecycleInput,
    LifecycleVerdict,
    classify_lifecycle,
)

__all__ = [
    "LIFECYCLE_STATES",
    "STATE_LABELS_FA",
    "LifecycleInput",
    "LifecycleVerdict",
    "classify_lifecycle",
]

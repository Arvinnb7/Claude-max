"""تخصیص تارگت اختصاصی به شعب و فروشنده‌ها همراه با طرح پاداش.

تارگت کل بر اساس سهم تاریخی هر واحد تخصیص می‌یابد، با کمی تعدیل به‌سمت واحدهای
پرشتاب‌تر (رشد بالاتر سهم بیشتری از کشش رشد می‌گیرند). برای هر واحد، پله‌های
پاداش (۱۰۰٪، ۱۲۰٪) تعریف می‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..analysis.performance import EntityPerformance


@dataclass
class EntityTarget:
    name: str
    baseline: float  # عملکرد دوره‌ی مبنا (سالانه‌سازی‌شده به دوره‌ی هدف)
    target: float
    growth_required: float  # درصد رشد لازم نسبت به مبنا
    reward_tiers: list[dict] = field(default_factory=list)


@dataclass
class TargetAllocation:
    dimension: str  # "شعبه" یا "فروشنده"
    total_target: float
    entities: list[EntityTarget] = field(default_factory=list)

    def compact(self) -> dict:
        return {
            "بُعد": self.dimension,
            "تارگت_کل": round(self.total_target),
            "تخصیص": [
                {"نام": e.name, "تارگت": round(e.target),
                 "رشد_لازم": round(e.growth_required * 100, 1),
                 "پاداش": e.reward_tiers}
                for e in self.entities
            ],
        }


def allocate_targets(
    entities: list[EntityPerformance],
    total_target: float,
    *,
    dimension: str,
    baseline_total: float,
    growth_tilt: float = 0.3,
) -> TargetAllocation:
    """تخصیص تارگت به واحدها بر اساس سهم + تعدیل رشد، و تعریف پله‌های پاداش.

    Args:
        entities: عملکرد واحدها (از analyze_performance).
        total_target: تارگت کل دوره‌ی هدف.
        dimension: برچسب بُعد ("شعبه"/"فروشنده").
        baseline_total: مجموع درآمد مبنا (برای محاسبه‌ی رشد لازم هر واحد).
        growth_tilt: وزن تعدیل به‌سمت واحدهای پرشتاب (۰=صرفاً سهم).
    """
    alloc = TargetAllocation(dimension=dimension, total_target=total_target)
    if not entities:
        return alloc

    # وزن ترکیبی: سهم پایه + تمایل به رشد مثبت
    weights = []
    for e in entities:
        g = e.growth if (e.growth is not None and e.growth > 0) else 0.0
        w = e.share * (1 + growth_tilt * g)
        weights.append(max(w, 0.0))
    wsum = sum(weights) or 1.0

    # مبنای هر واحد متناسب با سهمش از دوره‌ی مبنا
    for e, w in zip(entities, weights, strict=True):
        share_target = (w / wsum) * total_target
        baseline = e.share * baseline_total
        growth_required = (share_target - baseline) / baseline if baseline > 0 else 0.0
        reward = [
            {"آستانه": "۱۰۰٪ تارگت", "پاداش": "پاداش پایه"},
            {"آستانه": "۱۱۰٪ تارگت", "پاداش": "۱.۵ برابر پاداش پایه"},
            {"آستانه": "۱۲۵٪ تارگت", "پاداش": "۲ برابر پاداش پایه + جایزه‌ی ویژه"},
        ]
        alloc.entities.append(EntityTarget(
            name=e.name, baseline=baseline, target=share_target,
            growth_required=growth_required, reward_tiers=reward,
        ))

    alloc.entities.sort(key=lambda x: -x.target)
    return alloc


__all__ = ["TargetAllocation", "EntityTarget", "allocate_targets"]

"""دیسپچرِ آموزش — هر نوع مدل، آموزش‌دهنده‌ی خودش را ثبت می‌کند.

جدا نگه‌داشتنِ دیسپچر از خودِ آموزش‌دهنده‌ها دو فایده دارد: لایه‌ی API به هیچ
مدلِ خاصی وابسته نیست، و افزودن مدلِ بعدی هیچ خطی از API را عوض نمی‌کند.

نکته‌ی طراحی: آموزش **هرگز** در `run_analysis` صدا زده نمی‌شود. قرارداد
`PRESERVE_CONTRACT.md` §۸ می‌گوید این ارتقا هیچ گامی به `run_analysis` اضافه
نکرده و همان‌طور می‌ماند؛ آموزش کارِ صریحِ کاربر (یا زمان‌بند) است.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("mktcore.ml.train")


class Trainer(Protocol):
    """امضای مشترک آموزش‌دهنده‌ها."""

    def __call__(
        self,
        *,
        business_slug: str,
        params: dict[str, Any] | None,
        db_path: Path | None,
    ) -> dict: ...


_TRAINERS: dict[str, Trainer] = {}


def register_trainer(model_key: str, trainer: Trainer) -> None:
    _TRAINERS[model_key] = trainer


def available_trainers() -> tuple[str, ...]:
    return tuple(sorted(_TRAINERS))


def train_model(
    model_key: str,
    *,
    business_slug: str = "default",
    params: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict:
    """آموزشِ یک مدل. کلیدِ ناشناخته ⇒ خطای صریح، نه اجرای بی‌صدا."""
    trainer = _TRAINERS.get(model_key)
    if trainer is None:
        raise LookupError(
            f"برای «{model_key}» آموزش‌دهنده‌ای ثبت نشده است. "
            f"مدل‌های قابل آموزش: {'، '.join(available_trainers()) or 'هیچ‌کدام'}."
        )
    return trainer(business_slug=business_slug, params=params, db_path=db_path)


def _load_builtin_trainers() -> None:
    """ثبتِ آموزش‌دهنده‌های داخلی. نبودِ یکی نباید بقیه را از کار بیندازد."""
    try:
        from mktcore.ml import whale  # noqa: F401 - ثبت با import
    except Exception:  # noqa: BLE001 - مثلاً نبودِ scikit-learn
        logger.debug("آموزش‌دهنده‌ی نهنگ در دسترس نبود", exc_info=True)


_load_builtin_trainers()

__all__ = ["Trainer", "available_trainers", "register_trainer", "train_model"]

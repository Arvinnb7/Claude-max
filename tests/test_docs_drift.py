"""اسناد نباید بی‌صدا از کد عقب بمانند.

این تست از یک اتفاق واقعی آمده: `ROLLBACK.md` می‌گفت «حذفِ این جدول‌ها بی‌خطر
است» در حالی که هشت جدول تازه اصلاً در فهرستش نبودند — و یکی از آن‌ها
(`contact_suppressions`) فهرستِ کسانی است که گفته‌اند «پیام نفرست». سندِ غلط در
لحظه‌ی بازیابیِ اضطراری خوانده می‌شود؛ دقیقاً بدترین لحظه برای اشتباه‌بودن.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.db import Base, models  # noqa: E402, F401  - models: ثبت در metadata

_ROLLBACK = _ROOT / "docs" / "revenue-intelligence" / "ROLLBACK.md"

# جدولِ نسخه‌ی مهاجرت در `Base.metadata` نیست ولی در سند باید باشد
_EXTRA_DOCUMENTED = {"schema_migrations"}


def _documented_tables() -> set[str]:
    text = _ROLLBACK.read_text(encoding="utf-8")
    # نام جدول‌ها هم در بلوک کد می‌آیند هم در ستون اولِ جدول مارک‌داون
    names = set(re.findall(r"[a-z_][a-z0-9_]{3,}", text))
    return {n for n in names if n in _all_tables() | _EXTRA_DOCUMENTED}


def _all_tables() -> set[str]:
    return set(Base.metadata.tables.keys())


def test_rollback_doc_lists_every_canonical_table():
    """هر جدولِ تازه باید در سند بازگشت ثبت شود."""
    missing = _all_tables() - _documented_tables()
    assert not missing, (
        "این جدول‌ها در ROLLBACK.md نیستند؛ سند بازگشت ناقص است: "
        f"{sorted(missing)}"
    )


def test_rollback_doc_separates_rebuildable_from_irreversible():
    """تفکیک باید صریح باشد، وگرنه خواننده همه را بازساختنی فرض می‌کند."""
    text = _ROLLBACK.read_text(encoding="utf-8")
    assert "بازساختنی" in text
    assert "برگشت‌ناپذیر" in text


def test_the_opt_out_register_is_marked_irreversible():
    """مهم‌ترین ادعای این سند: حذف دفترِ انصراف برگشت‌ناپذیر است."""
    text = _ROLLBACK.read_text(encoding="utf-8")
    head, _, tail = text.partition("### برگشت‌ناپذیر")
    assert "contact_suppressions" in tail, (
        "دفترِ انصراف باید در بخشِ «برگشت‌ناپذیر» باشد، نه بازساختنی"
    )
    assert "contact_suppressions" not in head.split("### بازساختنی")[-1].split("###")[0]


def test_learned_effect_tables_are_marked_irreversible():
    text = _ROLLBACK.read_text(encoding="utf-8")
    _head, _, tail = text.partition("### برگشت‌ناپذیر")
    for table in ("campaign_outcomes", "uplift_snapshots", "campaign_sends"):
        assert table in tail, f"{table} از تحلیل بازساختنی نیست"


def test_doc_no_longer_claims_dropping_is_always_safe():
    """جمله‌ی قدیمی («حذفشان بی‌خطر است») حالا مشروط است، نه مطلق."""
    text = _ROLLBACK.read_text(encoding="utf-8")
    assert "حذف نکنید" in text


# ═══════════════════════════════════ اسناد مدل‌ها (فاز ۴)
_MODEL_CARDS = _ROOT / "docs" / "revenue-intelligence" / "MODEL_CARDS.md"
_FEATURE_CATALOG = _ROOT / "docs" / "revenue-intelligence" / "FEATURE_CATALOG.md"


def test_model_cards_document_every_trainable_model():
    """مدلی که آموزش‌دهنده دارد ولی کارت ندارد، جعبه‌ی سیاه است."""
    from mktcore.ml.train import available_trainers

    text = _MODEL_CARDS.read_text(encoding="utf-8")
    missing = [key for key in available_trainers() if f"`{key}`" not in text]
    assert not missing, f"این مدل‌ها کارت ندارند: {missing}"


def test_model_cards_state_the_champion_challenger_rule():
    """قاعده‌ای که کلِ ایمنیِ این لایه رویش بنا شده باید نوشته باشد."""
    text = _MODEL_CARDS.read_text(encoding="utf-8")
    assert "قهرمان" in text and "مدعی" in text
    assert "promote" in text or "فعال‌سازی" in text


def test_feature_catalog_covers_every_column_in_the_schema():
    """ستونی که در طرح‌واره هست ولی در سند نیست، بعداً بی‌معنا تفسیر می‌شود."""
    from mktcore.features.point_in_time import PIT_FEATURE_SCHEMA

    text = _FEATURE_CATALOG.read_text(encoding="utf-8")
    missing = [name for name in PIT_FEATURE_SCHEMA if name not in text]
    assert not missing, f"این ستون‌ها در فهرست ویژگی‌ها نیستند: {missing}"


def test_feature_catalog_states_the_nan_rule():
    """قاعده‌ی «NaN یعنی نمی‌دانیم، نه صفر» باید صریح نوشته باشد."""
    text = _FEATURE_CATALOG.read_text(encoding="utf-8")
    assert "NaN" in text
    assert "نه صفر" in text

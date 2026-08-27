"""جستجوهای مشترک هویت — تنها مسیر درستِ «کلید خام → شناسه».

چرا ماژول جدا؟ چون یک اشتباه ظریف دو بار تکرار شده بود: جستجو با
`customers.canonical_key`. آن ستون فقط **اولین** کلیدی است که مشتری با آن
ساخته شده؛ کلیدهای بعدی که به همان مشتری وصل شده‌اند در `customer_keys`
می‌نشینند. نتیجه‌ی جستجوی غلط این بود که پس از ادغام هویت، داده‌ی کلیدهای
دیگر بی‌صدا کنار گذاشته می‌شد — بدون هیچ خطایی.

`customer_keys` مرجع است، چون `repo_import` برای **هر** کلید خام (از جمله
کلیدِ ساخت) یک ردیف در آن می‌نویسد.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from .models import Business, CustomerKey, ImportBatch, ProductAlias

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.orm import Session

# `IN (...)` با فهرست خیلی بلند در هیچ دیتابیسی خوش‌رفتار نیست
CHUNK = 2000


def active_business_id(session: Session, *, fallback_slug: str = "default") -> int | None:
    """کسب‌وکارِ **آخرین بارگذاری** — همان چیزی که کاربر همین حالا تحلیل کرده.

    چرا نه همیشه `default`: داده‌ی نمونه عمداً در کسب‌وکارِ جدا نوشته می‌شود تا
    مشتریانِ مصنوعی با واقعی قاطی نشوند. ولی اگر خواندن همیشه روی `default`
    بماند، کاربری که دمو را اجرا می‌کند صندوقِ **خالی** می‌بیند و فکر می‌کند
    سیستم خراب است.

    با این قاعده هر دو خواسته برآورده می‌شود: بعد از تحلیلِ نمونه، نمونه دیده
    می‌شود؛ بعد از تحلیلِ فایل واقعی، فقط واقعی — و هیچ‌وقت مخلوطِ این دو.
    """
    latest = session.scalar(
        select(ImportBatch.business_id).order_by(ImportBatch.created_at.desc()).limit(1)
    )
    if latest is not None:
        return int(latest)
    return session.scalar(select(Business.id).where(Business.slug == fallback_slug))


def resolve_business_id(session: Session, business_slug: str = "default") -> int | None:
    """شناسه‌ی کسب‌وکارِ کاری که کاربر **همین حالا** رویش کار می‌کند.

    این سیستم تک‌مستأجره است، پس `default` عملاً یعنی «فضای کاری جاری». تنها
    استثناء داده‌ی نمونه است که عمداً در کسب‌وکارِ جدا می‌نشیند تا با داده‌ی واقعی
    قاطی نشود. اگر این تابع کورکورانه `default` را نگاه می‌کرد، همه‌ی مسیرهای
    پایین‌دستی (دروازه‌ی تماس، جدول اثر، برنامه‌ی آزمایش، نتیجه‌ی کمپین) روی
    کسب‌وکارِ اشتباه کار می‌کردند و بی‌صدا خالی برمی‌گشتند.

    اسلاگِ صریحِ **غیر از** پیش‌فرض همان‌طور که هست جستجو می‌شود.
    """
    if business_slug != "default":
        return session.scalar(
            select(Business.id).where(Business.slug == business_slug)
        )
    return active_business_id(session)


def customer_ids_by_raw_key(
    session: Session, business_id: int, keys: Iterable[str],
) -> dict[str, int]:
    """کلید خامِ فایل → شناسه‌ی مشتری پایدار (از راه `customer_keys`)."""
    wanted = sorted({str(k) for k in keys if str(k)})
    out: dict[str, int] = {}
    for start in range(0, len(wanted), CHUNK):
        rows = session.execute(
            select(CustomerKey.key_value, CustomerKey.customer_id).where(
                CustomerKey.business_id == business_id,
                CustomerKey.key_type == "raw_key",
                CustomerKey.key_value.in_(wanted[start:start + CHUNK]),
            )
        ).all()
        out.update(dict(rows))
    return out


def product_ids_by_raw_name(
    session: Session, business_id: int, names: Iterable[str],
) -> dict[str, int]:
    """نام خامِ کالا → شناسه‌ی محصول (از راه نامِ نرمال‌شده در `product_aliases`)."""
    from mktcore.catalog import normalize_product_name

    raw_names = [str(n) for n in names if n]
    norm_of = {name: normalize_product_name(name) for name in raw_names}
    norms = sorted({n for n in norm_of.values() if n})

    by_norm: dict[str, int] = {}
    for start in range(0, len(norms), CHUNK):
        rows = session.execute(
            select(ProductAlias.alias_norm, ProductAlias.product_id).where(
                ProductAlias.business_id == business_id,
                ProductAlias.alias_norm.in_(norms[start:start + CHUNK]),
            )
        ).all()
        by_norm.update(dict(rows))

    return {
        name: by_norm[norm]
        for name, norm in norm_of.items()
        if norm and norm in by_norm
    }


__all__ = [
    "active_business_id",
    "customer_ids_by_raw_key",
    "product_ids_by_raw_name",
    "resolve_business_id",
]

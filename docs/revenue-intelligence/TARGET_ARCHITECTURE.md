# معماری هدف و تصمیم‌های ثبت‌شده

> سند §۳۹ می‌خواهد این تصمیم‌ها با بازرسی مخزن گرفته و مستند شوند.

## اصل حاکم
**Preserve what works. Extend what can be extended. Refactor only what blocks the
upgrade. Build only what is missing.**

## معماری هم‌زیستی

```
فایل اکسل → connectors (استریمی) → mapper (امضای سرستون) → cleaning
      ↓
   clean DataFrame (float64، attrs: returns/exclusions/validation)
      ↓                                        ↓
 pipeline.run_analysis                  canonical_hook (موازی، غیرمخرب)
      ↓                                        ↓
  MetricsBundle → serialize → UI      دفتر کل رابطه‌ای (ریال صحیح)
                                               ↓
                                     هویت / کاتالوگ / فرصت‌ها → /api/v1
```

**خط لوله‌ی تحلیل دست‌نخورده است.** لایه‌ی canonical موازی نوشته می‌شود و هدفش
چیزهایی است که DataFrame نمی‌تواند بدهد: هویت پایدار بین بارگذاری‌ها، فرصت‌های
ماندگار با چرخه‌ی حیات، و حلقه‌ی بسته‌ی اندازه‌گیری.

## تصمیم‌ها

| # | موضوع | تصمیم | دلیل |
|---|---|---|---|
| ۱ | دیتابیس | **SQLite بماند** + لایه‌ی canonical با **SQLAlchemy 2.0 ORM** | استقرار تک‌کاربره ویندوز/داکر با یک worker؛ ORM سوئیچ به Postgres را به تغییر URL تبدیل می‌کند |
| ۲ | مهاجرت | runner گام‌به‌گام با جدول `schema_migrations`؛ **بدون Alembic** | Alembic مکانیزم سوم نسخه‌بندی در یک فایل می‌شد + گام عملیاتی `upgrade head` که کاربر غیرفنی رد می‌کند؛ SQLite هم `batch_alter_table` می‌خواهد |
| ۳ | صف job | **ThreadPool فعلی** | هیچ Redis/Celery در مخزن نیست؛ کار CPU-محور تک‌پروسه است |
| ۴ | محل feature | همان `analysis/*` + snapshot ماندگار | بازنویسی به SQL = ریسک رگرسیون بدون منفعت |
| ۵ | حفظ گزارش‌ها | pandas → bundle → serialize بدون تغییر | صفر-رگرسیون؛ `clean.attrs` معناهایی دارد که canonical مدل نمی‌کند |
| ۶ | پول در canonical | عدد صحیح **ریال** (`BigInteger`، نام `*_rial`) | ریال خودش کوچک‌ترین واحد است؛ float ممنوع (§۳.۴) |
| ۷ | چندمستأجری | `business_id` روی همه‌ی جداول canonical | §۳۳؛ ارزان و آینده‌نگر |
| ۸ | احراز هویت | **فعلاً نه** | افزودنش همه‌ی fetchهای فرانت و ۱۵۰ تست را می‌شکند؛ `business_id` راه را باز می‌گذارد |
| ۹ | لایه‌ی دامنه | **عمومی و داده‌محور** (اندازه/واحد بسته + قواعد قابل‌تنظیم) | کسب‌وکار چنددامنه است؛ هیچ فرض گونه‌ی حیوان hardcode نمی‌شود |
| ۱۰ | سود ناخالص | زیرساخت ساخته می‌شود، مقدار **NULL** می‌ماند | بهای خرید در داده نیست؛ هیچ عدد درآمدی «سود» نامیده نمی‌شود |

## قواعد غیرقابل‌مذاکره‌ی پیاده‌سازی

1. هوک canonical **هرگز raise نمی‌کند** و تحلیل را نمی‌شکند (`MKT_CANONICAL_ENABLE=0`
   خاموشش می‌کند).
2. نتایج آشتی **هرگز** به `bundle.validation.checks` اضافه نمی‌شود (وگرنه گیت
   `_require_publishable` تولید استراتژی AI را می‌بندد).
3. `Base.metadata` فقط جداول جدید را می‌شناسد؛ `drop_all` ممنوع.
4. `PRAGMA user_version` در ۲ می‌ماند؛ مالکش `persistence.py` است.
5. `analysis/actions.py` تغییر نمی‌کند؛ موتور فرصت‌ها همان تابع را با پارامتر
   وسیع‌تر بار دوم صدا می‌زند.
6. احتمال دوباره در ارزش ضرب نمی‌شود (`actions.py` از قبل ضرب کرده).
7. فیلدهای علّی تا وجود شواهد آزمایشی **NULL** می‌مانند.
8. پول در API همیشه `{rial: int, display_text: str}` است، هرگز float.

## واگذاری‌های عامدانه
Alembic · Postgres · Celery/Redis · auth/RBAC · کشش قیمت · مدل‌های uplift ·
سود ناخالص · ingestion موجودی · کانکتورهای SQL/CRM · embedding محصول ·
تطبیق فازی نام مشتری · خواندن تحلیل‌ها از canonical.

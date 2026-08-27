# پشتیبان‌گیری و بازگشت

## پشتیبان‌گیری (قبل از ارتقا — الزامی)

دیتابیس در حالت WAL است؛ **کپی کردن تنها `app.db` کافی نیست** (فایل `app.db-wal`
هم داده دارد). از API پشتیبان SQLite استفاده کنید:

```bash
python -c "import sqlite3; s=sqlite3.connect('data/app.db'); d=sqlite3.connect('data/app.db.bak'); s.backup(d); d.close(); s.close()"
cp -r data/sessions data/sessions.bak      # ویندوز: xcopy /E /I data\sessions data\sessions.bak
```

## بازگشت

جداول قدیمی (`sessions`, `jobs`, `outbox`, `mapping_profiles`) در این ارتقا
**دست نمی‌خورند** و `PRAGMA user_version` در ۲ می‌ماند. بنابراین:

1. **کد قدیمی روی دیتابیس جدید درست کار می‌کند** — جداول canonical فقط بی‌استفاده
   می‌مانند. بازگشت = `git checkout <commit قبلی>` و ری‌استارت سرور.
2. بازگردانی پشتیبان **اختیاری** است، نه الزامی.
3. خاموش کردن فوری لایه‌ی جدید بدون تغییر کد:
   ```bash
   MKT_CANONICAL_ENABLE=0
   ```
   تحلیل، داشبورد، گزارش و اکسل کامل کار می‌کنند؛ فقط تب «صندوق فرصت‌ها» و
   endpointهای `/api/v1` داده‌ی تازه نمی‌گیرند.

## بازگردانی کامل

```bash
cp data/app.db.bak data/app.db
rm -f data/app.db-wal data/app.db-shm
rm -rf data/sessions && mv data/sessions.bak data/sessions
```

## جدول‌های لایه‌ی canonical — و اینکه کدام‌شان بازساختنی است

⚠️ **نسخه‌ی قبلی این سند می‌گفت «حذفشان با `DROP TABLE` بی‌خطر است».** آن جمله
برای جداول فاز ۱ درست بود (از تحلیل بازساخته می‌شوند) ولی حالا **خطرناک** است:
ده جدول بعداً اضافه شده‌اند و پنج‌تایشان از هیچ تحلیلی بازساخته نمی‌شوند.

### بازساختنی — حذفشان بی‌خطر است

با اجرای تحلیل بعدی دوباره ساخته و پر می‌شوند:

```
businesses · import_batches · import_reconciliation · customers · customer_keys
products · product_aliases · orders · order_lines · customer_features
opportunities · opportunity_factors · opportunity_events · opportunity_runs
customer_lifecycle_events · schema_migrations
```

### بازساختنی — ولی **نه از تحلیل**

از فایل فروش ساخته نمی‌شوند؛ از ورودیِ خودِ کاربر دوباره پر می‌شوند. یعنی
داده از بین نمی‌رود، ولی خودبه‌خود هم برنمی‌گردد:

| جدول | چطور برمی‌گردد |
|---|---|
| `product_cost_history` | با ورودِ دوباره‌ی فایل بها (`POST /api/v1/costs`). تا آن لحظه پوششِ بها صفر است و سود ناخالص و «سود افزوده‌ی کمپین» گزارش نمی‌شوند — نه اینکه صفر گزارش شوند |
| `app_settings` | با تعیین دوباره‌ی کف حاشیه (`PUT /api/v1/margin-floor`). تا آن لحظه `filter_margin_floor` صادقانه «بررسی نشد» ثبت می‌کند و هیچ پیشنهادی را رد نمی‌کند |

ستون `order_lines.gross_profit_rial` هم در همین دسته است: با
`POST /api/v1/costs` (که خودش انتساب را اجرا می‌کند) دوباره پر می‌شود.

### برگشت‌ناپذیر — **حذف نکنید**

| جدول | با حذفش چه از دست می‌رود |
|---|---|
| `contact_suppressions` | **فهرست کسانی که گفته‌اند «پیام نفرست».** حذفش یعنی همه‌شان بی‌صدا به فهرست تماس برگردند. از هیچ تحلیلی بازساختنی نیست و پیامدش حقوقی و اخلاقی است، نه فنی |
| `campaign_outcomes` | مشاهده‌ی آزمایشیِ یک پنجره‌ی زمانیِ **گذشته**. با حذفش، هرچه سیستم درباره‌ی اثر تماس یاد گرفته از بین می‌رود و بازیابی‌اش فقط با اجرای دوباره‌ی همان کمپین ممکن است |
| `uplift_snapshots` | تاریخچه‌ی جدول اثر؛ پاسخِ «چرا آن روز این ترتیب بود؟» و امکان rollback رتبه‌بندی |
| `campaign_sends` | دفترِ هزینه و شناسه‌ی پیام نزد پنل. با حذفش «هزینه به‌ازای سفارش افزوده» دوباره مسدود می‌شود |
| `campaigns` · `campaign_members` · `campaign_opportunities` | تخصیص تصادفیِ بازوها. بدون آن‌ها، `campaign_outcomes` بی‌معنا می‌شود |

**پیش از هر حذفی از این گروه، پشتیبان بگیرید.** فهرست انصراف را می‌توان از
`GET /api/v1/contact-suppressions` هم بیرون کشید و جدا نگه داشت.

**جدول `app_meta` را حذف نکنید** — متعلق به لایه‌ی قدیمی است و «آخرین اجرای
زمان‌بند» را نگه می‌دارد.

> این فهرست با تستِ `test_rollback_doc_lists_every_canonical_table` به
> `Base.metadata` گره خورده است، پس افزودن جدول تازه بدون به‌روزرسانی این سند
> باعث شکست تست می‌شود. دلیلش همین دریفتی است که یک‌بار اتفاق افتاد.

## چیزی که این ارتقا **تغییر نداد**

برای اطمینان‌خاطر، این‌ها با تست پین شده‌اند:
- `PRAGMA user_version` همچنان **۲** است (`test_canonical_migration_does_not_bump_user_version`).
- چهار جدول قدیمی دست‌نخورده‌اند و `Base.metadata` اصلاً آن‌ها را نمی‌شناسد
  (`test_metadata_never_knows_legacy_tables`).
- خروجی `/api/analyze` همان قرارداد قبلی است؛ `canonical` فقط یک کلید **افزوده**
  است (`test_analyze_endpoint_still_returns_the_same_contract`).
- `bundle.actions` (کارت داشبورد و شیت اکسل) با اجرای موتور فرصت‌ها تغییر
  نمی‌کند (`test_bundle_actions_are_not_mutated_by_the_engine`).

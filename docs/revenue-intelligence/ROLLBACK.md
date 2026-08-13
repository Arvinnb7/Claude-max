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

## جدول‌های افزوده‌شده در این ارتقا

اگر بخواهید فقط لایه‌ی جدید را از دیتابیس پاک کنید (بدون بازگردانی پشتیبان)،
این جدول‌ها متعلق به لایه‌ی canonical‌اند و هیچ‌کدام از جداول قدیمی به آن‌ها
ارجاع نمی‌دهند:

```
businesses · import_batches · import_reconciliation · customers · customer_keys
products · product_aliases · orders · order_lines · customer_features
opportunities · opportunity_factors · opportunity_events · opportunity_runs
schema_migrations
```

حذفشان با `DROP TABLE` بی‌خطر است؛ در اجرای بعدی دوباره ساخته می‌شوند و از
تحلیل‌های موجود پر می‌شوند. **جدول `app_meta` را حذف نکنید** — متعلق به لایه‌ی
قدیمی است و «آخرین اجرای زمان‌بند» را نگه می‌دارد.

## چیزی که این ارتقا **تغییر نداد**

برای اطمینان‌خاطر، این‌ها با تست پین شده‌اند:
- `PRAGMA user_version` همچنان **۲** است (`test_canonical_migration_does_not_bump_user_version`).
- چهار جدول قدیمی دست‌نخورده‌اند و `Base.metadata` اصلاً آن‌ها را نمی‌شناسد
  (`test_metadata_never_knows_legacy_tables`).
- خروجی `/api/analyze` همان قرارداد قبلی است؛ `canonical` فقط یک کلید **افزوده**
  است (`test_analyze_endpoint_still_returns_the_same_contract`).
- `bundle.actions` (کارت داشبورد و شیت اکسل) با اجرای موتور فرصت‌ها تغییر
  نمی‌کند (`test_bundle_actions_are_not_mutated_by_the_engine`).

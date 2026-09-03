# حسابرسی شکاف در برابر سند

> ⚠️ **این سند عکسِ لحظه‌ی حسابرسی است (پیش از دورِ «نقص‌ها + فاز ۶»).** ردیف‌هایی
> که از آن زمان بسته شده‌اند با ✅ و شماره‌ی گام علامت خورده‌اند؛ متنِ اصلی
> **پاک نشده** تا معلوم بماند چه چیزی کجا بود. برای وضعیتِ امروز،
> `RELEASE_NOTES.md` مرجع است.

> مرجع: `MASTER_SPEC.md` (همان متنی که کاربر داد، دست‌نخورده در همین پوشه).
> ارجاع بندها به شماره‌ی بخش‌های همان فایل است.
>
> **این سند برای دفاع نوشته نشده.** جایی که ادعای قبلی من غلط بوده، همان‌جا
> نوشته شده که غلط بوده.

## چهار وضعیت

| وضعیت | معنی |
|---|---|
| `done` | پیاده شده، با شاهد کد و تستی که **وجودش راستی‌آزمایی شده** |
| `partial` | بخشی پیاده شده — بخشِ نشده صریح گفته می‌شود |
| `missing` | ساخته نشده و تصمیمی هم درباره‌اش ثبت نشده بود |
| `declined` | عمداً ساخته نشد؛ با دلیل، و با تفکیک نوعِ مانع |

و برای هر مانع، تفکیکِ صریح:

* **`blocked_by_data`** — داده‌اش وجود ندارد؛ تصمیم من نبود.
* **`my_judgement`** — داده بود یا شدنی بود؛ **من** تصمیم گرفتم نسازم.

این دو را در گزارش‌های قبلی گاهی یکی نشان داده بودم. تفکیکشان مهم است، چون
دومی قابل بازبینی است و اولی نه.

---

## جمع‌بندی فازها (§۳۵)

| فاز | عنوان سند | ادعای قبلی من | واقعیت |
|---|---|---|---|
| ۰ | Audit and safety foundation | ✅ کامل | ✅ **کامل** — هر ۶ قلم |
| ۱ | Canonical data and trustworthy Customer 360 | ✅ کامل | 🔶 **~۶۰٪** — «margin/gross profit» بسته شد |
| ۲ | Actionable deterministic opportunity engine | ✅ کامل | 🔶 **~۸۰٪** — `filter_margin_floor` از «همیشه skip» درآمد (۱۰ از ۱۱ فیلتر) |
| ۳ | Closed-loop campaigns and experiments | ✅ کامل | ✅ **دروازه‌ی پذیرش پاس شد** — سود افزوده گزارش می‌شود (۱۰ از ۱۳ سنجه) |
| ۴ | Predictive models | ✅ | ✅ **دروازه‌ی پذیرش پاس شد** — دو مدل promote‌شدنی با holdout زمانی |
| ۵ | Causal offer optimization and pricing | ❌ صفر | 🔶 **~۲۰٪** |
| ۶ | Operational optimization | ❌ شروع نشده | 🔶 **~۲۰٪** |

### دو خطای بزرگ در ادعاهای قبلی

**۱. «رتبه‌بندی مبتنی بر اثر» فاز ۴ نیست، فاز ۵ است.**
سند مدل‌های uplift/treatment-effect را صریحاً زیر
«Phase 5 — Causal offer optimization and pricing intelligence» گذاشته. من آن را
«فاز ۴» نامیدم. نتیجه‌ی این جابه‌جایی: فاز ۴ عملاً دست‌نخورده ماند در حالی که
«✅» خورده بود، و فاز ۵ «صفر» اعلام شد در حالی که اولین قلمش ساخته شده بود.

**۲. فاز ۱ و ۲ «کامل» نبودند.** جدول‌های پایین نشان می‌دهند چه چیزی کم است.

---

## فاز ۰ — Audit and safety foundation

| قلم سند | وضعیت | شاهد |
|---|---|---|
| Current-system audit | `done` | `CURRENT_SYSTEM_AUDIT.md` |
| Target architecture document | `done` | `TARGET_ARCHITECTURE.md` |
| Schema migration plan | `done` | `db/migrations.py` (۷ مهاجرت، جدول `schema_migrations`) |
| Implementation status checklist | `done` | `IMPLEMENTATION_STATUS.md` |
| Baseline test suite around current imports | `done` | `tests/test_baseline_imports.py` |
| Backup/rollback instructions | `done` | `ROLLBACK.md` |

**دروازه‌ی پذیرش:** ندارد. ✅ کامل.

---

## فاز ۱ — Canonical data and trustworthy Customer 360

| قلم سند | وضعیت | شاهد / آنچه کم است |
|---|---|---|
| canonical orders/order_lines/customers/products | `done` | `db/models.py` — گرینِ خط سفارش، یکتا بر `line_uid` |
| identity and product resolution | `partial` | ترتیبِ قطعی (تلفن → کلید خام) هست؛ ولی `merged_into_customer_id`، تاریخچه‌ی ادغام و صف بازبینی **نیست**، و `confidence_bp` همه‌جا ۱۰۰۰۰ هاردکد است — یعنی «اطمینان» عملاً متغیر نیست |
| returns | `done` | خطوط برگشتی با `is_return` ماندگارند — `test_returns_are_in_the_ledger_not_dropped` |
| discounts | `done` | `discount_rial` / `discount_rate_bp` |
| cost | `done` | ستون فایل فروش **یا** مسیر ورودِ جدا (`POST /api/v1/costs` → `product_cost_history`). انتساب بر پایه‌ی **تاریخ خط** با سه سطح اطمینان `from_file`/`history_exact`/`history_imputed` (§۳.۴) |
| **margin / gross profit** | `done` | `order_lines.gross_profit_rial` در دفتر کل می‌نشیند (بها `NULL` ⇒ سود `NULL`، هرگز صفر). حاشیه‌ی هر کالا از همان‌جا: `costs/register.py::margin_lookup` — `test_gross_profit_loop.py` |
| reconciliation | `done` | `ImportReconciliation`، کنترل‌های L01–L07 — `test_reconciliation_rows_are_persisted` |
| Customer 360 feature snapshots | `partial` | `as_of_date` و `feature_version` هست؛ **watermark منبع** و **نسخه‌ی کد** (§۱۰.۴) نیست — ۲ از ۴ |
| Immutable imports (`import_rows_raw` §۷.۱) | ✅ **بسته شد (S4)** | تا سقفِ `MKT_RAW_ROWS_CAP` ذخیره می‌شود؛ بالاتر از سقف صریحاً «ذخیره نشد» ثبت می‌شود |
| Quarantine (`import_quarantine` §۷.۱) | ✅ **بسته شد (S4)** | جدولِ `import_quarantine` در دفتر کل، با کدِ دلیل و راهِ اصلاح؛ تستی که بقایش را بعد از هرس اثبات می‌کند |
| Versioned per-source mappings (§۸.۲) | `missing` | `mapping_profiles` با هشِ سرستون کلید می‌خورد، بدون `version` و بدون `source_system` |
| data-quality UI/API (§۸.۵ — ۹ بُعد) | ✅ **بسته شد (S5)** | هر نُه بُعد؛ بُعدی که مبنایش نیست `None` («سنجیده نشد») می‌گیرد، نه صفر |

### جدول‌های §۷.۱/§۷.۵ که اصلاً وجود ندارند

`branches` · `source_systems` · `promotions` · `price_history` ·
`inventory_snapshots` — پنج‌تا `missing`.

`supplier_cost_history` **جایگزین دارد**: `product_cost_history` ساخته شد و عمداً نامِ
«supplier» نگرفت، چون بُعدِ تأمین‌کننده در داده وجود ندارد و نامی که آن را وعده
بدهد گمراه‌کننده است. `supplier` و `quantity tier` و `freight` که §۷.۵ می‌خواهد
همچنان `blocked_by_data`.

نوع مانع: `branches` و `promotions` و `price_history` → **`blocked_by_data`**
(داده‌شان در فایل فروش نیست). `source_systems` → **`my_judgement`** (با یک منبع،
لازم ندیدم).

**دروازه‌ی پذیرش فاز ۱** («بارگذاری دوباره idempotent و آشتی با مجموع مبدأ»):
✅ **می‌گذرد** — `test_reimport_is_idempotent` + کنترل‌های L01–L07.
یعنی دروازه پاس می‌شود ولی نیمی از اقلامِ تحویلی ساخته نشده.

---

## فاز ۲ — Actionable deterministic opportunity engine

| قلم سند | وضعیت | شاهد / آنچه کم است |
|---|---|---|
| Lifecycle states (§۱۱ — ۱۲ حالت) | `done` | **هر ۱۲ حالت** در `lifecycle/states.py` پیاده و قابل‌دسترسی‌اند؛ گذارها با دلیل در `CustomerLifecycleEvent` ثبت می‌شوند |
| Rule-based replenishment (§۱۳) | `partial` | میانه‌ی **ساده**ی فاصله‌ها استفاده می‌شود، نه میانه‌ی وزنیِ مقاوم + MAD (§۱۳.۳). تعدیل بر پایه‌ی مقدار/اندازه‌ی بسته (§۱۳.۴) **نیست**. سلسله‌مراتب ۵ سطحیِ شواهد (§۱۳.۲) **نیست** |
| Rule-based churn/slipping (§۱۶.۱) | `done` | آستانه‌ها مضربِ آهنگ خودِ مشتری‌اند، نه ۹۰ روزِ ثابت |
| Association / sequential NBP baseline (§۱۴) | `partial` | الگوهای توالی کاملاً به فرصت وصل‌اند (`KIND_SEQUENCE`)؛ قواعد انجمنی وجود دارند ولی بیشتر به‌عنوان سیگنالِ **پشتیبان** در توصیه‌گر، نه مولدِ درجه‌یک |
| Basket-building baseline (§۱۵) | `missing` | attach rate، ارزش افزوده‌ی سبد، تغییر سود، هزینه‌ی تخفیف بسته و کانیبالیزیشن — هیچ‌کدام. نوع مانع: بخشی `blocked_by_data` (سود لازم دارد) و بخشی `my_judgement` |
| Expansion-gap baseline (§۱۷) | `done` | `analysis/expansion_gap.py` + مولد اختصاصی. ⚠️ سند «gross profit» می‌خواهد، ما **درآمد**محور ساخته‌ایم (در خود فایل مستند شده) |
| Opportunity common contract (§۱۲) | `done` | `opportunities/contract.py` |
| Filters (§۱۲ — ۱۱ مرحله) | `partial` | **۱۰ از ۱۱** فیلتر. `filter_margin_floor` که تا دیروز همیشه `skip` می‌داد حالا واقعاً کار می‌کند: حاشیه از دفتر کل، کف **از کاربر** (`PUT /api/v1/margin-floor`). بدون کفِ تعیین‌شده همچنان `skip` ثبت می‌شود — نبودِ تصمیمِ کاربر «قبول» نیست |
| Conflict suppression · expiry · EV ranking | `done` | `filter_conflict`، `_expire_overdue`، مرتب‌سازی نزولی بر ارزش |
| Opportunity Inbox + Customer 360 UI | `done` | `OpportunityInbox.tsx`، `Customer360.tsx` |

**دروازه‌ی پذیرش فاز ۲** («هر فرصت شواهد دارد و بازتولیدپذیر است»): ✅ می‌گذرد.

---

## فاز ۳ — Closed-loop campaigns and experiments

| قلم سند | وضعیت | شاهد |
|---|---|---|
| action/exposure/outcome events | `done` | `CampaignMember.exposure_*`، `CampaignOutcome`، `OpportunityEvent` |
| campaign audience builder | `done` | `POST /api/v1/campaigns` |
| treatment/control randomization | `done` | هشِ قطعی، طبقه‌بندی‌شده، در سطح **مشتری** (§۲۲.۱) |
| attribution reporting | `done` | `analyze_campaign` — حکمِ `attribution_only` وقتی کنترل نیست |
| incremental analysis | `done` | `test_injected_lift_is_recovered_with_the_right_magnitude` |
| exports/connectors | `done` | خروجی اکسل + ارسال مستقیم کاوه‌نگار |
| operator feedback | `done` | **۷ دلیل رد** دقیقاً مطابق §۳۰ — `test_dismiss_reasons_are_a_closed_vocabulary` |
| §۲۲.۲ — ۱۳ سنجه | `partial` | **۱۰ از ۱۳**. غایب: Delivered و Viewed/clicked (`blocked_by_data` — webhook پنل وصل نیست)، و Cost per incremental order فقط برای ارسالِ درون‌سیستمی کار می‌کند نه کمپینِ اکسلی |

### ✅ دروازه‌ی پذیرش فاز ۳ — حالا پاس می‌شود

سند: *«a test campaign can be run end-to-end with treatment/control and
**incremental gross profit** reporting.»*

`test_campaign_reports_incremental_gross_profit_with_full_coverage` همین را
سرتاسر اجرا می‌کند: تحلیل → ورودِ بها → کمپین با گروه کنترل → خروجی (لحظه‌ی
تماس) → خواندن نتیجه از دفتر کل → **سود افزوده**، و عدد را با تفاضلِ سودِ سرانه
تطبیق می‌دهد.

گاردش هم تست دارد: با برداشتن بهای **یک** خط از پنجره‌ی گروه آزمایش، عدد
گزارش نمی‌شود و `incremental_gross_profit` به `blocked_metrics` برمی‌گردد
(`test_incomplete_cost_coverage_blocks_the_number`).

⚠️ آنچه هنوز جای کار دارد: بهای واردشده بهای **واحد** است و سربار را در بر
نمی‌گیرد؛ و اگر فایل بها تاریخ اثر نداشته باشد همه‌ی خطوطِ تاریخی
`history_imputed` می‌شوند — که صریحاً برچسب می‌خورد، ولی برچسب جای دقت را
نمی‌گیرد.

---

## فاز ۴ — Predictive models

| قلم سند | وضعیت | شاهد / آنچه کم است |
|---|---|---|
| Calibrated churn/survival model | `done` | مدلِ خطرِ گسسته روی جدولِ «مشتری × دوره» با سانسور و holdout زمانی؛ خط پایه همان دامپینگ هندسیِ فعلی است — `ml/churn.py`، `test_churn_model.py` |
| Advanced replenishment model (§۱۳.۵) | `done` | همان مدلِ خطر: احتمالِ خرید در افق مکملِ احتمالِ ریزش است. ضمناً میانه‌ی وزنی، MAD و تعدیلِ اندازه‌ی بسته (§۱۳.۳ و §۱۳.۴) اضافه شدند — `analysis/cadence_robust.py` |
| CLV (§۱۹) | `done` | سودمحور، افق ۹۰/۱۸۰/۳۶۵، با بازه‌ی عدم‌قطعیت و نسخه/تاریخ — `analysis/clv.py`. نسخه‌ی درآمدیِ قبلی دست‌نخورده ماند |
| Future-whale model (§۱۸) | `done` | برچسبِ صدکِ سودِ آینده درونِ کوهورت، ویژگی فقط از پنجره‌ی اولیه، دروازه‌ی بلوغ، و اقدامِ رابطه‌ای بدون عدد ریالی — `ml/whale.py`، `test_whale_model.py` |
| Hybrid next-best-product ranking (§۱۴.۴ — ۹ سیگنال) | `partial` | همچنان **۴ از ۹** در امتیازِ توصیه‌گر. سودِ کالا حالا در دسترس است ولی وارد رتبه‌بندی نشد؛ دلیلش پایین‌تر |
| Model registry / promotion / rollback / drift (§۲۶.۴، §۲۹.۷) | `done` | جدول `model_runs` + هشت مسیر §۲۶.۴ + PSI/نرخ هدف/افت کالیبراسیون + تبِ «سلامت مدل» |

### ✅ دروازه‌ی پذیرش فاز ۴ — حالا پاس می‌شود

سند: *«promoted models beat deterministic baselines on temporal holdout and
top-K economic metrics.»*

دو مدل با همین قاعده سنجیده و ثبت می‌شوند و **فقط در صورت بردن** فعال می‌شوند:

| مدل | خط پایه‌ی قطعی | نتیجه روی داده‌ی کوهورت‌دار |
|---|---|---|
| نهنگ | سودِ ۹۰ روز اول به‌ازای روز | Brier ۰٫۰۴۳ در برابر ۰٫۰۹۱ · سودِ K تای اول ۶٪ بالاتر با بازه‌ی مثبت |
| ریزش | دامپینگ هندسی π=۰٫۸۵ | Brier ۰٫۰۵۶ در برابر ۰٫۱۷۸ · سودِ در معرض خطرِ K تای اول ۵۲٪ بالاتر |

روی داده‌ی نمونه‌ی فعلی هر دو صادقانه `insufficient_data` می‌دهند — و آن هم یک
تستِ سبز است، نه شکست.

### ⚠️ آنچه هنوز جای کار دارد

* **رتبه‌بندی ۹ سیگنالی (§۱۴.۴).** سه سیگنال (موجودی، سازگاری، آفر) داده ندارند
  و سه‌تای دیگر (تکرار، اطمینان، خستگی) امروز به‌عنوان **فیلتر** عمل می‌کنند نه
  ورودیِ امتیاز. افزودنشان به امتیاز، ترتیبِ صندوق را عوض می‌کند و طبق همان
  قاعده‌ی قهرمان/مدعی باید با holdout سنجیده شود؛ عمداً به گامِ بعد موکول شد تا
  تغییرِ نسنجیده وارد رتبه‌بندی نشود.
* **شکاف توسعه (§۱۷.۳) هنوز درآمدمحور است.** دیگر محدودیتِ داده نیست — بها
  موجود است — ولی عوض‌کردنش رتبه‌بندی را جابه‌جا می‌کند و همان دروازه را
  می‌خواهد.

---

## فاز ۵ — Causal offer optimization and pricing intelligence

| قلم سند | وضعیت | شاهد / آنچه کم است |
|---|---|---|
| uplift / treatment-effect models (§۲۰.۴) | `partial` | تفاضل نرخ تبدیل در سلولِ (نوع × چرخه‌ی عمر) با انقباض به والد و بازه‌ی اطمینان. این یک تخمین‌گرِ **طبقه‌بندی‌شده‌ی ساده** است — نه T/S/X-learner، نه causal forest، نه هیچ ویژگیِ سطحِ مشتری. `test_small_cell_is_pulled_toward_the_parent` |
| minimum effective incentive policy (§۲۰) | `missing` | `filter_offer_policy` عملاً no-op است و سیستم **هرگز تخفیف تولید نمی‌کند** — `test_no_offer_or_discount_is_ever_generated`. هیچ فیلدی برای سطح آفر وجود ندارد. نوع مانع: `blocked_by_data` (داده‌ی آزمایشیِ آفر نداریم) |
| price elasticity and simulation (§۲۱) | `missing` | هیچ ماژولی نیست. `unit_price_rial` نوشته می‌شود ولی **هیچ‌جا خوانده نمی‌شود**. نوع مانع: `blocked_by_data` (تنوع قیمتِ عامدانه وجود ندارد) |
| next-best-action optimization (§۲۵ — ~۱۴ نوع اقدام) | `partial` | **۶ نوع فرصت** و **یک کانال** (پیامک). «بدون اقدام»، «اعلان موجودی»، تفکیک تماس/واتساپ/ایمیل/پرامپت فروشگاهی: هیچ‌کدام |

---

## فاز ۶ — Operational optimization

| قلم سند | وضعیت | شاهد / آنچه کم است |
|---|---|---|
| operator assignment / capacity | 🔶 **نیمه‌بسته (S3)** | فیلترِ ظرفیتِ روزانه اضافه شد (تنظیم‌نشده ⇒ «بررسی نشد»). نوبت‌دهی و بارِ هر مسئول همچنان نیست |
| branch-aware fulfillment (§۲۴.۵) | 🔶 **نیمه‌بسته (S3)** | «شعبه‌ی محتملِ مشتری» با سهم و درجه‌ی اتکا در پرونده‌ی مشتری. تخصیصِ موجودیِ شعبه‌ای همچنان بدونِ داده‌ی موجودی ممکن نیست |
| notification and scheduled workflows | `done` | APScheduler، اسکن روزانه، جبران اجرای ازدست‌رفته، گاردِ مجوز تماس |
| performance tuning (§۳۳) | `partial` | ایندکس‌ها و صفحه‌بندی هست؛ تنظیم عامدانه‌ی کارایی انجام نشده |
| advanced monitoring (§۳۲) | ✅ **بسته شد (S2)** | `X-Request-Id` (با انتقال به jobها)، لاگِ ساختاریافته، `/api/v1/ops/metrics`، و healthی که واقعاً دیتابیس را می‌زند |
| documented deployment/runbook | `missing` | `OPERATIONS_RUNBOOK.md` ساخته نشده |

---

## اسناد الزامی (§۳۶): ۱۰ از ۱۵

| موجود | غایب |
|---|---|
| `CURRENT_SYSTEM_AUDIT` · `TARGET_ARCHITECTURE` · `FINANCIAL_CALCULATION_RULES` · `IMPLEMENTATION_STATUS` · `MODEL_CARDS` · `FEATURE_CATALOG` · `EXPERIMENTATION_GUIDE` · `OPERATIONS_RUNBOOK` · `SECURITY_AND_PRIVACY` · `RELEASE_NOTES` | `DATA_DICTIONARY` · `SOURCE_MAPPING_GUIDE` · `IDENTITY_RESOLUTION` · `OPPORTUNITY_ENGINE` · `API_GUIDE` |

`PRESERVE_CONTRACT.md` و `ROLLBACK.md` و همین فایل، **افزون بر** فهرست سندند.

---

## امنیت (§۳۱)

| قلم | وضعیت |
|---|---|
| Authentication | `partial` — توکنِ مشترک روی مسیرهای نوشتنی؛ احراز هویتِ هر کاربر نیست |
| Business/tenant scoping | `done` — `business_id` روی همه‌ی جداول و در همه‌ی پرس‌وجوها |
| RBAC (۵ نقش) | `missing` — `my_judgement` (برای تک‌کاربره سربار دانستم) |
| PII masking in logs | `partial` — `mask_phone` در پاسخ API هست، در لاگ **نیست** |
| Audit logs | `partial` — فقط `OpportunityEvent`؛ برای ادغام هویت، promotion و export **نیست** |
| Contact consent / do-not-contact | `done` — دفترِ انصراف و دروازه‌ی مجوز تماس |

---

## نتیجه

سیستم در **عمق** جاهایی که ساخته شده قوی است (دفتر کل idempotent با آشتی
خودحسابرس، حلقه‌ی بسته‌ی آزمایش با گروه کنترل واقعی، گاردهای تماس)، ولی در
**پهنا** حدود نیمی از سند را پوشش می‌دهد.

دو موضوع بارها تکرار می‌شوند و ریشه‌ی مشترک دارند:

۱. ~~**سود ناخالص.**~~ **بسته شد.** سود روی خط می‌نشیند، سود افزوده‌ی کمپین
   گزارش می‌شود، کفِ حاشیه کار می‌کند، و شمالِ‌ستاره‌ی §۴ محاسبه‌شدنی است.
   آنچه از این ریشه **باقی مانده**: CLV سودمحور (فاز ۴) و شکاف توسعه‌ی
   سودمحور (فاز ۲) — هر دو حالا فقط عوض‌کردنِ مبنا از درآمد به سودند، نه
   ساختِ زیرساخت. نسخه‌ی درآمدی حذف نمی‌شود؛ نسخه‌ی سودی کنارش می‌آید.

۲. ~~**ماندگاریِ ردیف خام و قرنطینه.**~~ **بسته شد (S4).** ردیفِ ردشده حالا در
   دفتر کل می‌نشیند — با کدِ دلیل، راهِ اصلاح، و بقای اثبات‌شده در برابر سیاست
   نگه‌داری. این همان چیزی بود که واقعاً از بین می‌رفت، نه فقط «بازبینی‌ناپذیر»
   بود.

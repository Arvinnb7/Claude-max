"use client";

import { KeyRound, ShieldAlert, ShieldCheck } from "lucide-react";
import { useState, useSyncExternalStore } from "react";

import { clearToken, getToken, setToken, subscribeToken } from "@/lib/token";

/**
 * ورودیِ توکنِ دسترسی در نوار بالای صفحه.
 *
 * ## چرا این کنترل لازم شد
 *
 * مسیرهای پرخرجِ سرور با هدرِ `X-API-Token` بسته شده‌اند، ولی هیچ راهی نبود که
 * کاربر آن توکن را به رابط کاربری بدهد. نتیجه‌اش این بود که روشن‌کردنِ امنیت،
 * خودِ برنامه را از کار می‌انداخت — یعنی عملاً کسی روشنش نمی‌کرد.
 *
 * ## چرا وقتی سرور باز است هم چیزی نشان می‌دهد
 *
 * سکوت در برابر «هیچ گاردی نیست» همان اشتباهی است که این فاز برای رفعش ساخته
 * شد. اگر سرور توکن نمی‌خواهد، همین‌جا با یک نشانِ کهربایی گفته می‌شود.
 */
export function ApiTokenControl({ tokenRequired }: { tokenRequired?: boolean }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");

  // `localStorage` در رندرِ سمتِ سرور وجود ندارد، پس عکسِ سرور همیشه «ندارد»
  // است و بعد از hydration مقدارِ واقعی می‌نشیند. `useSyncExternalStore` دقیقاً
  // برای همین حالت است: حالتی که منبعش بیرونِ React است.
  const saved = useSyncExternalStore(
    subscribeToken,
    () => getToken().length > 0,
    () => false,
  );

  if (tokenRequired === false) {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800 dark:bg-amber-500/15 dark:text-amber-200"
        title="سرور بدون توکن است: هر کسی که به این آدرس دسترسی داشته باشد می‌تواند پیامک واقعی بفرستد. برای بستنش MKT_API_TOKEN را روی سرور تنظیم کنید."
      >
        <ShieldAlert size={14} /> بدون توکن
      </span>
    );
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => {
          setValue(getToken());
          setOpen((v) => !v);
        }}
        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
          saved
            ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
            : "bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-200"
        }`}
        aria-expanded={open}
      >
        {saved ? <ShieldCheck size={14} /> : <KeyRound size={14} />}
        {saved ? "توکن ثبت شده" : "توکن لازم است"}
      </button>

      {open && (
        <div
          className="absolute end-0 top-full z-50 mt-2 w-80 rounded-xl border bg-white p-3 text-sm shadow-lg dark:bg-ink-900"
          style={{ borderColor: "var(--border)" }}
        >
          <label className="mb-1 block text-xs" style={{ color: "var(--muted)" }}>
            توکنِ دسترسی سرور (`MKT_API_TOKEN`)
          </label>
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="مقدار توکن را اینجا بگذارید"
            className="w-full rounded-lg border px-3 py-2 text-sm"
            style={{ borderColor: "var(--border)", background: "transparent" }}
            dir="ltr"
          />
          <p className="mt-2 text-xs" style={{ color: "var(--muted)" }}>
            توکن در همین مرورگر ذخیره می‌شود و فقط روی درخواست‌های همین برنامه
            فرستاده می‌شود.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => {
                setToken(value);
                setOpen(false);
              }}
              className="rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-700"
            >
              ذخیره
            </button>
            <button
              type="button"
              onClick={() => {
                clearToken();
                setValue("");
              }}
              className="rounded-lg px-3 py-1.5 text-xs font-semibold text-ink-600 hover:bg-ink-100 dark:text-ink-300 dark:hover:bg-ink-800"
            >
              پاک‌کردن
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

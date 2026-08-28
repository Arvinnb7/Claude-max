"use client";

import { ReactNode, useState } from "react";

import { toFa } from "@/lib/format";
import { UnauthorizedError, downloadWithToken } from "@/lib/token";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`card p-5 ${className}`}>{children}</div>;
}

export function StatCard({
  label,
  value,
  hint,
  icon,
  tone = "brand",
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: ReactNode;
  tone?: "brand" | "accent" | "green" | "rose";
}) {
  const toneMap: Record<string, string> = {
    brand: "bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300",
    accent: "bg-orange-50 text-accent-600 dark:bg-accent-500/15 dark:text-accent-400",
    green: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300",
    rose: "bg-rose-50 text-rose-600 dark:bg-rose-500/15 dark:text-rose-300",
  };
  return (
    <div className="card p-5 animate-fade-up">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm" style={{ color: "var(--muted)" }}>
          {label}
        </span>
        {icon && (
          <span className={`grid h-9 w-9 place-items-center rounded-xl ${toneMap[tone]}`}>
            {icon}
          </span>
        )}
      </div>
      <div className="mt-2 text-2xl font-bold tnum">{value}</div>
      {hint && (
        <div className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
          {hint}
        </div>
      )}
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  className = "",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "outline";
  disabled?: boolean;
  className?: string;
  type?: "button" | "submit";
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed";
  const styles: Record<string, string> = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm",
    ghost: "text-brand-600 hover:bg-brand-50 dark:hover:bg-brand-500/10",
    outline:
      "border border-ink-200 text-ink-700 hover:bg-ink-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${styles[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

export function Badge({
  children,
  tone = "brand",
}: {
  children: ReactNode;
  tone?: "brand" | "accent" | "green" | "rose" | "gray";
}) {
  const map: Record<string, string> = {
    brand: "bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300",
    accent: "bg-orange-50 text-accent-600 dark:bg-accent-500/15 dark:text-accent-400",
    green: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    rose: "bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
    gray: "bg-ink-100 text-ink-600 dark:bg-ink-700 dark:text-ink-300",
  };
  return (
    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${map[tone]}`}>
      {children}
    </span>
  );
}

export function SectionTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-lg font-bold">{title}</h2>
      {subtitle && (
        <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          {subtitle}
        </p>
      )}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-10">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
      {label && (
        <span className="text-sm" style={{ color: "var(--muted)" }}>
          {label}
        </span>
      )}
    </div>
  );
}

export function ProgressBar({
  pct,
  stage,
  label,
}: {
  pct: number;
  stage?: string;
  label?: string;
}) {
  return (
    <div className="mx-auto max-w-md py-10 text-center">
      {label && <p className="mb-3 text-sm font-semibold">{label}</p>}
      <div className="h-2 w-full overflow-hidden rounded-full bg-ink-100 dark:bg-ink-800">
        <div
          className="h-full rounded-full bg-brand-600 transition-all duration-500"
          style={{ width: `${Math.min(100, Math.max(4, pct))}%` }}
        />
      </div>
      <p className="mt-3 text-sm tnum" style={{ color: "var(--muted)" }}>
        {stage || "در حال پردازش…"} — {toFa(Math.round(pct))}٪
      </p>
    </div>
  );
}

export function Alert({
  children,
  tone = "info",
}: {
  children: ReactNode;
  tone?: "info" | "warn" | "error";
}) {
  const map: Record<string, string> = {
    info: "bg-brand-50 text-brand-800 border-brand-200 dark:bg-brand-500/10 dark:text-brand-200 dark:border-brand-500/30",
    warn: "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-500/10 dark:text-amber-200 dark:border-amber-500/30",
    error: "bg-rose-50 text-rose-800 border-rose-200 dark:bg-rose-500/10 dark:text-rose-200 dark:border-rose-500/30",
  };
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm ${map[tone]}`}>{children}</div>
  );
}

/**
 * لینکِ دانلود که **هدرِ توکن** را هم می‌فرستد.
 *
 * `<a href>` ساده نمی‌تواند هدر بفرستد؛ یعنی به‌محضِ بستنِ مسیرهای خروجی، همه‌ی
 * دکمه‌های دانلود با ۴۰۱ برمی‌گشتند و — چون مرورگر خودش پیمایش می‌کرد — کاربر
 * فقط یک صفحه‌ی خالی می‌دید بدون هیچ توضیحی. اینجا فایل با `fetch` گرفته
 * می‌شود و از روی `blob` ذخیره می‌شود، و خطا **دیده** می‌شود.
 *
 * `href` سرِ جایش می‌ماند تا «باز کردن در تبِ جدید» و منویِ راست‌کلیک مثل قبل
 * کار کند.
 */
export function DownloadLink({
  href,
  filename,
  className = "",
  children,
}: {
  href: string;
  /** نامِ جایگزین، اگر سرور `Content-Disposition` نفرستد */
  filename: string;
  className?: string;
  children: ReactNode;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <>
      <a
        href={href}
        className={className}
        aria-busy={busy}
        onClick={(event) => {
          // کلیدهای ترکیبی یعنی «خودم می‌خواهم بازش کنم» — دست نمی‌زنیم
          if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          event.preventDefault();
          setError(null);
          setBusy(true);
          downloadWithToken(href, filename)
            .catch((e: unknown) => {
              setError(
                e instanceof UnauthorizedError
                  ? `${e.message} توکن را در نوار بالای صفحه وارد کنید.`
                  : e instanceof Error
                    ? e.message
                    : "دانلود انجام نشد.",
              );
            })
            .finally(() => setBusy(false));
        }}
      >
        {children}
      </a>
      {error && (
        <div className="fixed inset-x-4 bottom-4 z-50 mx-auto max-w-2xl" role="alert">
          <div className="flex items-start justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 shadow-lg dark:border-rose-500/30 dark:bg-ink-900 dark:text-rose-200">
            <span>{error}</span>
            <button
              type="button"
              onClick={() => setError(null)}
              className="shrink-0 rounded-lg px-2 hover:bg-rose-100 dark:hover:bg-ink-800"
              aria-label="بستن"
            >
              ×
            </button>
          </div>
        </div>
      )}
    </>
  );
}

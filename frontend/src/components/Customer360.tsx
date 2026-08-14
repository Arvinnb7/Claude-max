"use client";

import { useCallback, useEffect, useState } from "react";

import { getCustomer, type CustomerProfile } from "@/lib/apiV1";
import { toFa } from "@/lib/format";

import { Alert, Badge, Card, SectionTitle, Spinner, StatCard } from "./ui";

/** رنگ حالت: سبز = رابطه‌ی سالم، نارنجی = هشدار، قرمز = در حال از دست رفتن. */
function lifecycleTone(
  state: string | null,
): "brand" | "green" | "accent" | "rose" | "gray" {
  switch (state) {
    case "vip":
    case "loyal":
    case "growing":
    case "reactivated":
      return "green";
    case "slipping":
      return "accent";
    case "at_risk":
    case "dormant":
    case "lost":
      return "rose";
    case "new":
    case "activated":
    case "established":
      return "brand";
    default:
      return "gray";
  }
}

/**
 * پرونده‌ی مشتری — هرچه از این مشتری می‌دانیم، در طول **همه‌ی** بارگذاری‌ها.
 *
 * این چیزی است که داشبورد فعلی نمی‌توانست بدهد: داشبورد یک فایل را می‌بیند،
 * این پرونده هویت پایدار را می‌بیند.
 */
export default function Customer360({
  customerId,
  fallbackName,
}: {
  customerId: number;
  fallbackName?: string;
}) {
  const [data, setData] = useState<CustomerProfile | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await getCustomer(customerId));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در خواندن پرونده‌ی مشتری");
    }
  }, [customerId]);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  if (error) {
    return (
      <Card>
        <Alert tone="warn">{error}</Alert>
      </Card>
    );
  }
  if (!data) {
    return (
      <Card>
        <Spinner label={`در حال خواندن پرونده‌ی ${fallbackName ?? "مشتری"}…`} />
      </Card>
    );
  }

  const c = data.customer;
  const f = c.features;

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle
          title={c.name ?? c.key}
          subtitle={`شناسایی‌شده با ${
            c.resolution_method === "phone" ? "شماره‌ی موبایل" : "کلید فایل"
          } — از ${c.first_order_date ?? "—"} تا ${c.last_order_date ?? "—"}`}
        />

        <div className="mb-3 flex flex-wrap items-center gap-2">
          {f?.lifecycle_label && (
            <Badge tone={lifecycleTone(f.lifecycle_state)}>{f.lifecycle_label}</Badge>
          )}
          {f?.segment && <Badge tone="brand">{f.segment}</Badge>}
          {f?.cycle_status && <Badge tone="accent">چرخه: {f.cycle_status}</Badge>}
          {c.phone_masked ? (
            <Badge tone="gray">{toFa(c.phone_masked)}</Badge>
          ) : (
            <Badge tone="gray">بدون شماره</Badge>
          )}
        </div>

        {f ? (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard label="جمع خرید" value={toFa(f.monetary.display_text)} />
            <StatCard label="میانگین سفارش" value={toFa(f.aov.display_text)} />
            <StatCard
              label="تعداد سفارش"
              value={toFa(String(f.n_orders ?? 0))}
            />
            <StatCard
              label="روز از آخرین خرید"
              value={toFa(String(f.recency_days ?? "—"))}
            />
            <StatCard
              label="فاصله‌ی معمول خرید"
              value={f.avg_gap_days ? `${toFa(String(Math.round(f.avg_gap_days)))} روز` : "—"}
            />
            <StatCard
              label="تأخیر از چرخه"
              value={
                f.overdue_days != null ? `${toFa(String(Math.round(f.overdue_days)))} روز` : "—"
              }
            />
            <StatCard
              label="احتمال فعال‌بودن"
              value={f.p_alive != null ? `${toFa(String(Math.round(f.p_alive * 100)))}٪` : "—"}
            />
            <StatCard label="ارزش ۱۲ ماه آینده" value={toFa(f.clv_12m.display_text)} />
          </div>
        ) : (
          <Alert tone="info">
            هنوز عکسی از ویژگی‌های این مشتری ثبت نشده است؛ با تحلیل بعدی ساخته می‌شود.
          </Alert>
        )}

        <p className="mt-3 text-xs" style={{ color: "var(--muted)" }}>
          {data.economics_note_fa}
        </p>
      </Card>

      {data.lifecycle_timeline.length > 0 && (
        <Card>
          <SectionTitle
            title="مسیر رابطه"
            subtitle="هر تغییر حالت با دلیلش — لحظه‌ی گذار، همان لحظه‌ی اقدام است."
          />
          <ol className="space-y-3">
            {data.lifecycle_timeline.map((t, i) => (
              <li key={`${t.as_of}-${t.to}-${i}`} className="flex gap-3 text-sm">
                <div className="mt-1 shrink-0">
                  <span
                    className="block h-2.5 w-2.5 rounded-full"
                    style={{ background: "var(--muted)" }}
                  />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="tnum text-xs" style={{ color: "var(--muted)" }}>
                      {t.as_of}
                    </span>
                    {t.from_label && (
                      <>
                        <Badge tone="gray">{t.from_label}</Badge>
                        <span style={{ color: "var(--muted)" }}>←</span>
                      </>
                    )}
                    <Badge tone={lifecycleTone(t.to)}>{t.to_label}</Badge>
                  </div>
                  {t.reason && <p className="mt-1">{t.reason}</p>}
                  {t.basis_label && (
                    <p className="mt-0.5 text-xs" style={{ color: "var(--muted)" }}>
                      {t.basis_label}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </Card>
      )}

      {data.feature_history.length > 1 && (
        <Card>
          <SectionTitle
            title="روند ویژگی‌ها"
            subtitle="هر ردیف یک عکس در زمان است — مبنای سنجش صادقانه‌ی تغییر."
          />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ color: "var(--muted)" }}>
                  <th className="p-2 text-start font-medium">تا تاریخ</th>
                  <th className="p-2 text-start font-medium">جمع خرید</th>
                  <th className="p-2 text-start font-medium">سفارش</th>
                  <th className="p-2 text-start font-medium">روز از آخرین خرید</th>
                  <th className="p-2 text-start font-medium">سگمنت</th>
                </tr>
              </thead>
              <tbody>
                {data.feature_history.map((h) => (
                  <tr key={h.as_of} className="border-t border-ink-100 dark:border-ink-800">
                    <td className="p-2 tnum">{h.as_of}</td>
                    <td className="p-2 tnum">{toFa(h.monetary.display_text)}</td>
                    <td className="p-2 tnum">{toFa(String(h.n_orders ?? 0))}</td>
                    <td className="p-2 tnum">{toFa(String(h.recency_days ?? "—"))}</td>
                    <td className="p-2">{h.segment ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card>
        <SectionTitle
          title="تاریخچه‌ی خرید"
          subtitle="از دفتر کل — با ارجاع به ردیف و شیتِ فایل منبع."
        />
        {!data.lines.length ? (
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            خطی ثبت نشده است.
          </p>
        ) : (
          <div className="max-h-96 overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-[var(--card)]">
                <tr style={{ color: "var(--muted)" }}>
                  <th className="p-2 text-start font-medium">تاریخ</th>
                  <th className="p-2 text-start font-medium">کالا</th>
                  <th className="p-2 text-start font-medium">تعداد</th>
                  <th className="p-2 text-start font-medium">مبلغ</th>
                  <th className="p-2 text-start font-medium">منبع</th>
                </tr>
              </thead>
              <tbody>
                {data.lines.map((ln, i) => (
                  <tr
                    key={`${ln.date}-${i}`}
                    className="border-t border-ink-100 dark:border-ink-800"
                  >
                    <td className="p-2 tnum">{ln.date}</td>
                    <td className="p-2">
                      {ln.product ?? "—"}
                      {ln.is_return && (
                        <span className="ms-2">
                          <Badge tone="rose">برگشت</Badge>
                        </span>
                      )}
                    </td>
                    <td className="p-2 tnum">
                      {ln.quantity != null ? toFa(String(ln.quantity)) : "—"}
                    </td>
                    <td className="p-2 tnum">{toFa(ln.revenue.display_text)}</td>
                    <td className="p-2 text-xs tnum" style={{ color: "var(--muted)" }}>
                      {ln.sheet ? `${ln.sheet} · ` : ""}
                      {ln.source_row != null ? `ردیف ${toFa(String(ln.source_row + 2))}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

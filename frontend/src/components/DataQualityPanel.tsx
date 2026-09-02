"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import {
  getDataQuality,
  getImport,
  getQuarantine,
  listImports,
  resolveQuarantineRow,
  type DataQuality,
  type ImportBatch,
  type QuarantineResponse,
  type ReconcileCheck,
} from "@/lib/apiV1";
import { toFa } from "@/lib/format";
import { UnauthorizedError } from "@/lib/token";

import { Alert, Badge, Button, Card, SectionTitle, Spinner, StatCard } from "./ui";

const SEVERITY_TONE: Record<string, "green" | "accent" | "rose" | "gray"> = {
  ok: "green",
  partial: "accent",
  warning: "accent",
  blocking_for_profit_metrics: "rose",
  known_limitation: "gray",
};

const SEVERITY_LABEL: Record<string, string> = {
  ok: "کامل",
  partial: "ناقص",
  warning: "هشدار",
  blocking: "جدی",
  blocking_for_profit_metrics: "مانع محاسبه‌ی سود",
  known_limitation: "محدودیت شناخته‌شده",
  not_measured: "سنجیده نشد",
};

const DIMENSION_TONE: Record<string, "green" | "accent" | "rose" | "gray"> = {
  ok: "green",
  warning: "accent",
  blocking: "rose",
  not_measured: "gray",
  known_limitation: "gray",
};

const CHECK_TONE: Record<ReconcileCheck["status"], "green" | "accent" | "rose"> = {
  OK: "green",
  WARN: "accent",
  MISMATCH: "rose",
};

const CHECK_LABEL: Record<ReconcileCheck["status"], string> = {
  OK: "آشتی",
  WARN: "بدون مرجع مقایسه",
  MISMATCH: "اختلاف",
};

export default function DataQualityPanel() {
  const [quality, setQuality] = useState<DataQuality | null>(null);
  const [quarantine, setQuarantine] = useState<QuarantineResponse | null>(null);
  const [quarantineLocked, setQuarantineLocked] = useState(false);
  const [batches, setBatches] = useState<ImportBatch[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [checks, setChecks] = useState<ReconcileCheck[] | null>(null);

  const load = useCallback(async () => {
    try {
      const [q, list, quarantined] = await Promise.all([
        getDataQuality(),
        listImports(30),
        // قرنطینه نباید بقیه‌ی پنل را زمین بزند: نصبِ قدیمی هنوز این مسیر را
        // ندارد و آن‌وقت کلِ صفحه‌ی کیفیت خالی می‌شد. ولی «بسته با توکن» با
        // «وجود ندارد» فرق دارد و باید گفته شود، نه پنهان.
        getQuarantine(50).catch((e: unknown) =>
          e instanceof UnauthorizedError ? ("locked" as const) : null,
        ),
      ]);
      setQuality(q);
      setBatches(list.items ?? []);
      setQuarantineLocked(quarantined === "locked");
      setQuarantine(quarantined === "locked" ? null : quarantined);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در خواندن وضعیت کیفیت داده");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function toggle(batchId: number) {
    if (openId === batchId) {
      setOpenId(null);
      setChecks(null);
      return;
    }
    setOpenId(batchId);
    setChecks(null);
    try {
      const detail = await getImport(batchId);
      setChecks(detail.checks);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در خواندن شواهد آشتی");
    }
  }

  if (error) {
    return (
      <Card>
        <Alert tone="warn">{error}</Alert>
      </Card>
    );
  }
  if (!quality) {
    return (
      <Card>
        <Spinner label="در حال خواندن وضعیت دفتر کل…" />
      </Card>
    );
  }
  if (!quality.available) {
    return (
      <Card>
        <SectionTitle title="کیفیت داده و دفتر کل" />
        <Alert tone="info">{quality.note_fa}</Alert>
      </Card>
    );
  }

  const counts = quality.counts ?? {};
  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle
          title="دفتر کل"
          subtitle="آنچه بین همه‌ی بارگذاری‌ها انباشته شده است."
        />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <StatCard label="مشتری" value={toFa(String(counts.customers ?? 0))} />
          <StatCard label="کالا" value={toFa(String(counts.products ?? 0))} />
          <StatCard label="فاکتور" value={toFa(String(counts.orders ?? 0))} />
          <StatCard label="قلم فروش" value={toFa(String(counts.lines ?? 0))} />
          <StatCard label="بارگذاری" value={toFa(String(counts.batches ?? 0))} />
        </div>
      </Card>

      {!!quality.dimensions?.length && (
        <Card>
          <SectionTitle
            title="ابعاد کیفیت داده"
            subtitle="نُه بُعدِ استاندارد. «سنجیده نشد» یعنی مبنایش وجود ندارد — نه اینکه صفر است."
          />
          {quality.quality_summary && (
            <p className="mb-3 text-xs" style={{ color: "var(--muted)" }}>
              {quality.quality_summary.note_fa}
            </p>
          )}
          <ul className="grid gap-2 md:grid-cols-2">
            {quality.dimensions.map((d) => (
              <li
                key={d.id}
                className="rounded-xl border border-ink-200 p-3 text-sm dark:border-ink-700"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <b>{d.label_fa}</b>
                  <div className="flex items-center gap-2">
                    <span className="text-xs tnum" style={{ color: "var(--muted)" }}>
                      {d.value === null
                        ? "—"
                        : `${toFa(String(Math.round(d.value * 100)))}٪`}
                    </span>
                    <Badge tone={DIMENSION_TONE[d.severity] ?? "gray"}>
                      {SEVERITY_LABEL[d.severity] ?? d.severity}
                    </Badge>
                  </div>
                </div>
                <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
                  {d.note_fa}
                </p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {quarantineLocked && (
        <Card>
          <SectionTitle
            title="ردیف‌های واردنشده"
            subtitle="ردیفِ خامِ فایل فروش داده‌ی شخصی است؛ دیدنش توکن API می‌خواهد. توکن را در نوار بالای صفحه وارد کنید."
          />
        </Card>
      )}
      {!!quarantine?.total && (
        <Card>
          <SectionTitle
            title={`ردیف‌های واردنشده (${toFa(String(quarantine.total))})`}
            subtitle="این ردیف‌ها در فایل بودند و وارد دفتر کل نشدند. تا اصلاح نشوند، در هیچ عددی شمرده نمی‌شوند."
          />
          <p className="mb-3 text-xs" style={{ color: "var(--muted)" }}>
            {quarantine.note_fa}
          </p>
          <ul className="space-y-2">
            {quarantine.rows.map((row) => (
              <li
                key={row.id}
                className="rounded-xl border border-ink-200 p-3 text-sm dark:border-ink-700"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <b>
                    ردیف {row.row_number === null ? "—" : toFa(String(row.row_number))}
                    {" · "}
                    {row.reason_fa}
                  </b>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      void resolveQuarantineRow(row.id)
                        .then(load)
                        .catch((e: unknown) =>
                          setError(
                            e instanceof Error ? e.message : "ثبت رسیدگی انجام نشد",
                          ),
                        );
                    }}
                  >
                    رسیدگی شد
                  </Button>
                </div>
                {row.suggested_resolution_fa && (
                  <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
                    {row.suggested_resolution_fa}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <SectionTitle
          title="شکاف‌های داده"
          subtitle="آنچه در دست نیست، صریح گفته می‌شود — نبودِ داده هرگز «تأیید» تفسیر نمی‌شود."
        />
        <ul className="space-y-2">
          {(quality.gaps ?? []).map((g) => (
            <li
              key={g.id}
              className="rounded-xl border border-ink-200 p-3 text-sm dark:border-ink-700"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <b>{g.label_fa}</b>
                <div className="flex items-center gap-2">
                  <span className="text-xs tnum" style={{ color: "var(--muted)" }}>
                    پوشش: {toFa(String(Math.round(g.coverage * 100)))}٪
                  </span>
                  <Badge tone={SEVERITY_TONE[g.severity] ?? "gray"}>
                    {SEVERITY_LABEL[g.severity] ?? g.severity}
                  </Badge>
                </div>
              </div>
              <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
                {g.impact_fa}
              </p>
            </li>
          ))}
        </ul>
        {quality.economics_note_fa && (
          <p className="mt-3 text-xs" style={{ color: "var(--muted)" }}>
            {quality.economics_note_fa}
          </p>
        )}
      </Card>

      <Card>
        <SectionTitle
          title="بارگذاری‌ها و آشتی"
          subtitle="هر بارگذاری با شواهدی که نشان می‌دهد اعداد دفتر با گزارش می‌خوانند."
        />
        {!batches.length ? (
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            بارگذاری‌ای ثبت نشده است.
          </p>
        ) : (
          <ul className="space-y-2">
            {batches.map((b) => (
              <li
                key={b.id}
                className="rounded-xl border border-ink-200 p-3 text-sm dark:border-ink-700"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <b className="truncate">{b.filename ?? "بدون نام"}</b>
                      {b.revision > 1 && <Badge tone="gray">نسخه {toFa(String(b.revision))}</Badge>}
                      <Badge tone={b.reconcile_status === "MISMATCH" ? "rose" : "green"}>
                        {b.reconcile_status === "MISMATCH" ? "اختلاف در آشتی" : "آشتی‌شده"}
                      </Badge>
                      {b.validation_status === "FAIL" && (
                        <Badge tone="rose">کنترل‌های کیفیت رد شده</Badge>
                      )}
                    </div>
                    <div
                      className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs tnum"
                      style={{ color: "var(--muted)" }}
                    >
                      <span>
                        {b.date_min} تا {b.date_max}
                      </span>
                      <span>{toFa(String(b.rows.clean ?? 0))} ردیف سالم</span>
                      {!!b.rows.returns && <span>{toFa(String(b.rows.returns))} برگشت</span>}
                      {!!b.rows.invalid && <span>{toFa(String(b.rows.invalid))} نامعتبر</span>}
                      {!!b.rows.duplicate && <span>{toFa(String(b.rows.duplicate))} تکراری</span>}
                      <span>فروش خالص: {toFa(b.net_sales.display_text)}</span>
                    </div>
                  </div>
                  <Button variant="ghost" onClick={() => void toggle(b.id)}>
                    {openId === b.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    شواهد آشتی
                  </Button>
                </div>

                {openId === b.id && (
                  <div className="mt-3 border-t border-ink-200 pt-3 dark:border-ink-700">
                    {checks === null ? (
                      <Spinner label="در حال خواندن شواهد…" />
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr style={{ color: "var(--muted)" }}>
                              <th className="p-1.5 text-start font-medium">کنترل</th>
                              <th className="p-1.5 text-start font-medium">انتظار</th>
                              <th className="p-1.5 text-start font-medium">واقعی</th>
                              <th className="p-1.5 text-start font-medium">تلرانس</th>
                              <th className="p-1.5 text-start font-medium">نتیجه</th>
                            </tr>
                          </thead>
                          <tbody>
                            {checks.map((c) => (
                              <tr
                                key={c.id}
                                className="border-t border-ink-100 dark:border-ink-800"
                              >
                                <td className="p-1.5">
                                  {c.label}
                                  {c.detail && (
                                    <div style={{ color: "var(--muted)" }}>{c.detail}</div>
                                  )}
                                </td>
                                <td className="p-1.5 tnum">{c.expected ?? "—"}</td>
                                <td className="p-1.5 tnum">{c.actual ?? "—"}</td>
                                <td className="p-1.5 tnum">{c.tolerance ?? "—"}</td>
                                <td className="p-1.5">
                                  <Badge tone={CHECK_TONE[c.status]}>{CHECK_LABEL[c.status]}</Badge>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

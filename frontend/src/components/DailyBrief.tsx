"use client";

import { AlertTriangle, ClipboardList, Copy } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { getDailyBrief, type DailyBrief as Brief, type Money } from "@/lib/apiV1";
import { jalali, toFa } from "@/lib/format";

import { Alert, Badge, Button, Card, SectionTitle, Spinner } from "./ui";

/**
 * اتاق فرمانِ روزانه (§۳۸).
 *
 * قاعده‌ی رندر: «پیش‌بینی» و «اثبات‌شده» دو ردیفِ جدا با برچسبِ خودشان‌اند و هیچ
 * جمعِ کلی‌ای از آن دو نشان داده نمی‌شود. مبلغی که `rial === null` دارد
 * «بررسی نشد» است، نه صفر — و یادداشتش کنارش می‌آید.
 */
function money(m: Money): string {
  return m.rial === null ? "بررسی نشد" : m.display_text;
}

function Row({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string | null;
  tone: "brand" | "green" | "gray";
}) {
  return (
    <li className="flex flex-wrap items-start justify-between gap-2 py-2">
      <div className="min-w-0">
        <Badge tone={tone}>{label}</Badge>
        {note && (
          <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
            {note}
          </p>
        )}
      </div>
      <b className="tnum">{value}</b>
    </li>
  );
}

export default function DailyBrief() {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      setBrief(await getDailyBrief());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در خواندن خروجیِ روزانه");
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

  if (error) return <Alert tone="error">{error}</Alert>;
  if (!brief) return <Spinner label="در حال ساختنِ خروجیِ روزانه…" />;
  if (!brief.available) {
    return (
      <Card>
        <SectionTitle title="اتاق فرمانِ روزانه" />
        <Alert tone="info">{brief.reason_fa}</Alert>
      </Card>
    );
  }

  const u = brief.urgent;
  const urgent: { text: string; tone: "rose" | "accent" | "gray" }[] = [
    {
      text: `${toFa(u.expiring_today)} فرصت امروز منقضی می‌شود (${toFa(u.expiring_soon)} تا ${toFa(u.expiring_soon_days)} روز)`,
      tone: u.expiring_today > 0 ? "rose" : "gray",
    },
    {
      text: `${toFa(u.vip_entered_at_risk)} مشتری: ${u.vip_entered_at_risk_label_fa}`,
      tone: u.vip_entered_at_risk > 0 ? "rose" : "gray",
    },
    { text: `سرکوب به‌خاطر موجودی: ${u.suppressed_by_stock_note_fa}`, tone: "gray" },
    {
      text:
        `${toFa(u.quarantine_open_rows)} ردیفِ قرنطینه‌ی باز` +
        (u.financial_unit_review_needed
          ? ` — آخرین بارگذاری به‌خاطر واحدِ مالی مسدود است (${u.latest_import_blocked_by.join("، ")})`
          : ""),
      tone: u.financial_unit_review_needed ? "rose" : u.quarantine_open_rows > 0 ? "accent" : "gray",
    },
    {
      text: `${toFa(u.dead_letter_runs)} کارِ زمان‌بندی‌شده در صفِ مرده`,
      tone: u.dead_letter_runs > 0 ? "rose" : "gray",
    },
  ];

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <SectionTitle
          title="اتاق فرمانِ روزانه"
          subtitle={`تاریخِ مرجع ${jalali(brief.as_of)} · داده تا ${brief.data_through ? jalali(brief.data_through) : "نامشخص"}`}
        />
        <Button
          variant="ghost"
          onClick={() => {
            void navigator.clipboard?.writeText(brief.text_fa).then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            });
          }}
        >
          <Copy size={14} /> {copied ? "کپی شد" : "کپیِ متن"}
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <p className="mb-1 text-sm font-semibold">
            <ClipboardList size={14} className="ms-0 me-1 inline" />
            {toFa(brief.valid_opportunities)} فرصتِ زنده‌ی ریالی
            {brief.forecast.relationship_count > 0 &&
              ` · ${toFa(brief.forecast.relationship_count)} اقدامِ رابطه‌ای (بدون عدد)`}
          </p>
          <ul className="divide-y divide-ink-200 dark:divide-ink-700">
            <Row
              label="پیش‌بینی (غیرعلّی)"
              value={money(brief.forecast.revenue)}
              note={brief.forecast.label_fa}
              tone="brand"
            />
            <Row
              label="پیش‌بینیِ سود ناخالص"
              value={money(brief.forecast.gross_profit)}
              note={brief.forecast.gross_profit_note_fa}
              tone="brand"
            />
            <Row
              label="افزوده‌ی اثبات‌شده"
              value={money(brief.proven.incremental_revenue)}
              note={brief.proven.label_fa}
              tone="green"
            />
            <Row
              label="سودِ افزوده‌ی اثبات‌شده"
              value={money(brief.proven.incremental_gross_profit)}
              note={brief.proven.gross_profit_note_fa}
              tone="green"
            />
            <Row
              label="هنوز سنجیده‌نشده"
              value={money(brief.not_validated.revenue)}
              note={brief.not_validated.label_fa}
              tone="gray"
            />
          </ul>
          <p className="mt-2 text-xs" style={{ color: "var(--muted)" }}>
            {brief.separation_note_fa}
          </p>
        </div>

        <div>
          <p className="mb-1 text-sm font-semibold">گروه‌های پرارزش</p>
          <ol className="space-y-1 text-sm">
            {brief.groups.map((g, i) => (
              <li key={g.kind} className="flex flex-wrap justify-between gap-2">
                <span>
                  {toFa(i + 1)}. {g.kind} — {toFa(g.customers)} مشتری
                </span>
                <b className="tnum">
                  {g.value_kind === brief.forecast.relationship_value_kind
                    ? "بدون عدد ریالی"
                    : money(g.forecast_revenue)}
                </b>
              </li>
            ))}
            {brief.groups.length === 0 && (
              <li style={{ color: "var(--muted)" }}>فرصتِ زنده‌ای نیست.</li>
            )}
          </ol>

          <p className="mb-1 mt-4 text-sm font-semibold">
            <AlertTriangle size={14} className="me-1 inline" />
            فوری
          </p>
          <ul className="space-y-1 text-sm">
            {urgent.map((item) => (
              <li key={item.text} className="flex items-start gap-2">
                <Badge tone={item.tone}>{item.tone === "gray" ? "—" : "!"}</Badge>
                <span>{item.text}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}

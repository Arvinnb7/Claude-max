"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowRight, Search } from "lucide-react";

import { listCustomers, type CustomerList, type CustomerRow } from "@/lib/apiV1";
import { toFa } from "@/lib/format";

import Customer360 from "./Customer360";
import { Alert, Badge, Button, Card, SectionTitle, Spinner } from "./ui";

const ORDERS = [
  { id: "monetary", label: "بیشترین خرید" },
  { id: "recency", label: "تازه‌ترین خرید" },
  { id: "orders", label: "بیشترین تعداد سفارش" },
  { id: "name", label: "نام" },
] as const;

type OrderBy = (typeof ORDERS)[number]["id"];

const PAGE = 25;

/** رنگ حالت چرخه‌ی عمر — همان قرارداد رنگی `Customer360`. */
function lifecycleTone(
  state: string | null,
): "brand" | "green" | "accent" | "rose" | "gray" {
  if (["vip", "loyal", "growing", "reactivated"].includes(state ?? "")) return "green";
  if (state === "slipping") return "accent";
  if (["at_risk", "dormant", "lost"].includes(state ?? "")) return "rose";
  if (["new", "activated", "established"].includes(state ?? "")) return "brand";
  return "gray";
}

function segmentTone(segment: string | null): "brand" | "green" | "accent" | "gray" | "rose" {
  if (!segment) return "gray";
  if (segment.includes("قهرمان") || segment.includes("وفادار")) return "green";
  if (segment.includes("خطر") || segment.includes("ازدست")) return "rose";
  if (segment.includes("نیازمند") || segment.includes("خواب")) return "accent";
  return "brand";
}

export default function CustomerDirectory() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [orderBy, setOrderBy] = useState<OrderBy>("monetary");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<CustomerList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<CustomerRow | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await listCustomers({ q: submitted || undefined, orderBy, limit: PAGE, offset }));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در خواندن فهرست مشتریان");
      setData(null);
    }
  }, [submitted, orderBy, offset]);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  if (selected) {
    return (
      <div className="space-y-3">
        <Button variant="ghost" onClick={() => setSelected(null)}>
          <ArrowRight size={14} /> بازگشت به فهرست مشتریان
        </Button>
        <Customer360 customerId={selected.id} fallbackName={selected.name ?? selected.key} />
      </div>
    );
  }

  if (data === null && error === null) {
    return (
      <Card>
        <Spinner label="در حال خواندن فهرست مشتریان…" />
      </Card>
    );
  }

  if (data && !data.available) {
    return (
      <Card>
        <SectionTitle title="مشتریان" />
        <Alert tone="info">{data.note_fa}</Alert>
      </Card>
    );
  }

  const total = data?.total ?? 0;
  return (
    <Card>
      <SectionTitle
        title="مشتریان"
        subtitle={
          data?.as_of
            ? `ویژگی‌ها بر مبنای داده تا ${data.as_of} — بین همه‌ی بارگذاری‌ها`
            : "هویت پایدار مشتری در طول همه‌ی بارگذاری‌ها"
        }
      />

      {error && (
        <div className="mb-3">
          <Alert tone="warn">{error}</Alert>
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex min-w-56 flex-1 items-center gap-2 rounded-lg border border-ink-200 px-3 dark:border-ink-700">
          <Search size={14} />
          <input
            className="w-full bg-transparent py-2 text-sm outline-none"
            placeholder="جستجو در نام، کد یا شماره…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                setOffset(0);
                setSubmitted(query.trim());
              }
            }}
          />
        </div>
        <Button
          variant="outline"
          onClick={() => {
            setOffset(0);
            setSubmitted(query.trim());
          }}
        >
          جستجو
        </Button>
        <select
          className="rounded-lg border border-ink-200 bg-transparent px-3 py-2 text-sm dark:border-ink-700"
          value={orderBy}
          onChange={(e) => {
            setOffset(0);
            setOrderBy(e.target.value as OrderBy);
          }}
        >
          {ORDERS.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <p className="mb-2 text-xs tnum" style={{ color: "var(--muted)" }}>
        {toFa(String(total))} مشتری
      </p>

      {!data?.items.length ? (
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          مشتری‌ای یافت نشد.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-start" style={{ color: "var(--muted)" }}>
                <th className="p-2 text-start font-medium">مشتری</th>
                <th className="p-2 text-start font-medium">حالت</th>
                <th className="p-2 text-start font-medium">سگمنت</th>
                <th className="p-2 text-start font-medium">جمع خرید</th>
                <th className="p-2 text-start font-medium">سفارش</th>
                <th className="p-2 text-start font-medium">آخرین خرید</th>
                <th className="p-2 text-start font-medium" />
              </tr>
            </thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id} className="border-t border-ink-100 dark:border-ink-800">
                  <td className="p-2">
                    <div className="font-medium">{c.name ?? c.key}</div>
                    {c.phone_masked && (
                      <div className="text-xs tnum" style={{ color: "var(--muted)" }}>
                        {toFa(c.phone_masked)}
                      </div>
                    )}
                  </td>
                  <td className="p-2">
                    {c.features?.lifecycle_label ? (
                      <Badge tone={lifecycleTone(c.features.lifecycle_state)}>
                        {c.features.lifecycle_label}
                      </Badge>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="p-2">
                    {c.features?.segment ? (
                      <Badge tone={segmentTone(c.features.segment)}>{c.features.segment}</Badge>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="p-2 tnum">
                    {c.features ? toFa(c.features.monetary.display_text) : "—"}
                  </td>
                  <td className="p-2 tnum">
                    {c.features?.n_orders != null ? toFa(String(c.features.n_orders)) : "—"}
                  </td>
                  <td className="p-2 tnum">{c.last_order_date ?? "—"}</td>
                  <td className="p-2 text-end">
                    <Button variant="ghost" onClick={() => setSelected(c)}>
                      پرونده
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-3 flex items-center justify-between gap-2">
        <Button
          variant="outline"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE))}
        >
          قبلی
        </Button>
        <span className="text-xs tnum" style={{ color: "var(--muted)" }}>
          {toFa(String(Math.floor(offset / PAGE) + 1))} از{" "}
          {toFa(String(Math.max(1, Math.ceil(total / PAGE))))}
        </span>
        <Button
          variant="outline"
          disabled={offset + PAGE >= total}
          onClick={() => setOffset(offset + PAGE)}
        >
          بعدی
        </Button>
      </div>

      {data?.economics_note_fa && (
        <p className="mt-3 text-xs" style={{ color: "var(--muted)" }}>
          {data.economics_note_fa}
        </p>
      )}
    </Card>
  );
}

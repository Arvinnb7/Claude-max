"use client";

import { useCallback, useEffect, useState } from "react";
import { Clock, FolderOpen, Pencil, Trash2 } from "lucide-react";

import { deleteSession, listSessions, renameSession } from "@/lib/api";
import { compact, num, toFa } from "@/lib/format";
import type { SessionListItem } from "@/lib/types";

import { Alert, Badge, Button, Card, SectionTitle, Spinner } from "./ui";

/** تاریخ و ساعت جلالی از timestamp یونیکس (ثانیه). */
function jalaliDateTime(ts: number): string {
  try {
    return toFa(
      new Intl.DateTimeFormat("fa-IR", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(ts * 1000)),
    );
  } catch {
    return "—";
  }
}

export default function RecentSessions({
  activeId,
  onOpen,
  onDeleted,
}: {
  activeId?: string | null;
  onOpen: (sessionId: string) => void;
  onDeleted?: (sessionId: string) => void;
}) {
  const [items, setItems] = useState<SessionListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [policy, setPolicy] = useState<string>("");
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await listSessions(20);
      setItems(res.items);
      setPolicy(res.retention.policy_fa);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در خواندن فهرست تحلیل‌ها");
      setItems([]);
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

  async function handleDelete(id: string) {
    try {
      await deleteSession(id);
      setConfirmId(null);
      await load();
      onDeleted?.(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "حذف ناموفق بود");
    }
  }

  async function handleRename(id: string) {
    try {
      await renameSession(id, renameValue.trim() || null);
      setRenameId(null);
      setRenameValue("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "تغییر نام ناموفق بود");
    }
  }

  if (items === null) {
    return (
      <Card>
        <Spinner label="در حال خواندن تحلیل‌های ذخیره‌شده…" />
      </Card>
    );
  }

  return (
    <Card>
      <SectionTitle
        title="تحلیل‌های اخیر"
        subtitle={policy || "تحلیل‌ها تا وقتی خودتان حذف نکنید باقی می‌مانند."}
      />

      {error && (
        <div className="mb-3">
          <Alert tone="warn">{error}</Alert>
        </div>
      )}

      {items.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          هنوز تحلیلی ذخیره نشده است.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((s) => (
            <li
              key={s.id}
              className={`rounded-xl border p-3 text-sm ${
                s.id === activeId
                  ? "border-brand-400 bg-brand-50/50 dark:border-brand-500/40 dark:bg-brand-500/5"
                  : "border-ink-200 dark:border-ink-700"
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <b className="truncate">{s.title}</b>
                    {s.id === activeId && <Badge tone="brand">در حال نمایش</Badge>}
                    {!s.has_analysis && <Badge tone="accent">ناتمام</Badge>}
                    {s.archived && <Badge tone="gray">بایگانی‌شده</Badge>}
                    {s.validation_status === "PASS_WITH_WARNINGS" && (
                      <Badge tone="accent">هشدار کیفیت</Badge>
                    )}
                    {s.validation_status === "FAIL" && <Badge tone="rose">کنترل‌ها رد شده</Badge>}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs tnum"
                       style={{ color: "var(--muted)" }}>
                    <span className="inline-flex items-center gap-1">
                      <Clock size={12} /> {jalaliDateTime(s.created_at)}
                    </span>
                    {s.n_rows != null && <span>{toFa(num(s.n_rows))} رکورد</span>}
                    {s.date_min && s.date_max && (
                      <span>
                        {s.date_min} تا {s.date_max}
                      </span>
                    )}
                    {s.total_revenue != null && (
                      <span>
                        فروش: {compact(s.total_revenue)} {s.currency ?? ""}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex shrink-0 gap-2">
                  {s.has_analysis && (
                    <Button variant="outline" onClick={() => onOpen(s.id)}>
                      <FolderOpen size={14} /> باز کردن
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setRenameId(s.id);
                      setRenameValue(s.label ?? "");
                    }}
                  >
                    <Pencil size={14} /> تغییر نام
                  </Button>
                  <Button variant="ghost" onClick={() => setConfirmId(s.id)}>
                    <Trash2 size={14} /> حذف
                  </Button>
                </div>
              </div>

              {renameId === s.id && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <input
                    className="min-w-48 flex-1 rounded-lg border border-ink-200 bg-transparent px-3 py-1.5 text-sm dark:border-ink-700"
                    placeholder="مثلاً فروش شهریور ۱۴۰۴"
                    value={renameValue}
                    maxLength={80}
                    onChange={(e) => setRenameValue(e.target.value)}
                  />
                  <Button variant="primary" onClick={() => void handleRename(s.id)}>
                    ذخیره
                  </Button>
                  <Button variant="ghost" onClick={() => setRenameId(null)}>
                    انصراف
                  </Button>
                </div>
              )}

              {confirmId === s.id && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <span className="text-xs" style={{ color: "var(--muted)" }}>
                    این تحلیل برای همیشه حذف شود؟
                  </span>
                  <Button variant="primary" onClick={() => void handleDelete(s.id)}>
                    بله، حذف کن
                  </Button>
                  <Button variant="ghost" onClick={() => setConfirmId(null)}>
                    انصراف
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

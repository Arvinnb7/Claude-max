"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { compact, jalaliShort, toFa } from "@/lib/format";
import type { BreakdownRow, Point } from "@/lib/types";

const BRAND = "#2563eb";
const ACCENT = "#f97316";
// خاکستری نیمه‌شفاف تا روی تم روشن و تاریک خوانا بماند
const GRID = "rgba(148, 163, 184, 0.22)";
const AXIS = "#94a3b8";

const axisProps = {
  tick: { fontSize: 11, fill: AXIS, fontFamily: "var(--font-vazir)" },
  tickLine: false,
  axisLine: { stroke: GRID },
};

function compactAxis(v: number) {
  return compact(v);
}

function TooltipBox({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number; color?: string }[];
  label?: string;
  unit?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="card px-3 py-2 text-xs" style={{ direction: "rtl" }}>
      <div className="mb-1 font-semibold">{label}</div>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span style={{ color: "var(--muted)" }}>{p.name}:</span>
          <span className="tnum font-medium">
            {compact(p.value ?? 0)} {unit}
          </span>
        </div>
      ))}
    </div>
  );
}

export function RevenueTrend({
  daily,
  ma30,
  unit,
}: {
  daily: Point[];
  ma30: Point[];
  unit: string;
}) {
  const data = daily.map((d, i) => ({
    date: jalaliShort(d.date),
    روزانه: d.value,
    "میانگین ۳۰ روزه": ma30[i]?.value ?? null,
  }));
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ top: 10, right: 12, left: 12, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="date" {...axisProps} minTickGap={40} />
        <YAxis {...axisProps} tickFormatter={compactAxis} width={56} />
        <Tooltip content={<TooltipBox unit={unit} />} />
        <Legend wrapperStyle={{ fontSize: 12, fontFamily: "var(--font-vazir)" }} />
        <Line type="monotone" dataKey="روزانه" stroke="#cbd5e1" dot={false} strokeWidth={1} />
        <Line
          type="monotone"
          dataKey="میانگین ۳۰ روزه"
          stroke={BRAND}
          dot={false}
          strokeWidth={3}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function MonthlyBars({ monthly, unit }: { monthly: Point[]; unit: string }) {
  const data = monthly.map((d) => ({ date: jalaliShort(d.date), درآمد: d.value }));
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 10, right: 12, left: 12, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="date" {...axisProps} minTickGap={20} />
        <YAxis {...axisProps} tickFormatter={compactAxis} width={56} />
        <Tooltip content={<TooltipBox unit={unit} />} cursor={{ fill: "rgba(37,99,235,0.06)" }} />
        <Bar dataKey="درآمد" fill={BRAND} radius={[6, 6, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ForecastChart({
  history,
  yhat,
  lower,
  upper,
  unit,
}: {
  history: Point[];
  yhat: Point[];
  lower: Point[];
  upper: Point[];
  unit: string;
}) {
  const hist = history.map((d) => ({
    date: jalaliShort(d.date),
    تاریخی: d.value,
  }));
  const fut = yhat.map((d, i) => ({
    date: jalaliShort(d.date),
    "پیش‌بینی": d.value,
    range: [lower[i]?.value ?? null, upper[i]?.value ?? null],
  }));
  const data = [...hist, ...fut];
  return (
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={data} margin={{ top: 10, right: 12, left: 12, bottom: 0 }}>
        <defs>
          <linearGradient id="band" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={BRAND} stopOpacity={0.18} />
            <stop offset="100%" stopColor={BRAND} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="date" {...axisProps} minTickGap={20} />
        <YAxis {...axisProps} tickFormatter={compactAxis} width={56} />
        <Tooltip content={<TooltipBox unit={unit} />} />
        <Legend wrapperStyle={{ fontSize: 12, fontFamily: "var(--font-vazir)" }} />
        <Area
          dataKey="range"
          stroke="none"
          fill="url(#band)"
          name="بازه‌ی اطمینان"
          isAnimationActive={false}
        />
        <Area
          type="monotone"
          dataKey="تاریخی"
          stroke={BRAND}
          fill="transparent"
          strokeWidth={2.5}
        />
        <Area
          type="monotone"
          dataKey="پیش‌بینی"
          stroke={ACCENT}
          fill="transparent"
          strokeWidth={2.5}
          strokeDasharray="6 4"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function BreakdownBars({ rows, unit }: { rows: BreakdownRow[]; unit: string }) {
  const data = rows.map((r) => ({ label: r.label, درآمد: r.revenue }));
  return (
    <ResponsiveContainer width="100%" height={Math.max(220, data.length * 38)}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 5, right: 16, left: 8, bottom: 5 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} horizontal={false} />
        <XAxis type="number" {...axisProps} tickFormatter={compactAxis} />
        <YAxis
          type="category"
          dataKey="label"
          {...axisProps}
          width={90}
          orientation="right"
        />
        <Tooltip content={<TooltipBox unit={unit} />} cursor={{ fill: "rgba(37,99,235,0.06)" }} />
        <Bar dataKey="درآمد" fill={BRAND} radius={[0, 6, 6, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

const PIE = ["#2563eb", "#f97316", "#10b981", "#8b5cf6", "#ef4444", "#0ea5e9", "#eab308", "#64748b"];

export function SegmentBars({
  segments,
  unit,
}: {
  segments: { name: string; revenue: number }[];
  unit: string;
}) {
  const data = segments.map((s) => ({ name: s.name, درآمد: s.revenue }));
  return (
    <ResponsiveContainer width="100%" height={Math.max(220, data.length * 36)}>
      <BarChart data={data} layout="vertical" margin={{ top: 5, right: 16, left: 8, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} horizontal={false} />
        <XAxis type="number" {...axisProps} tickFormatter={compactAxis} />
        <YAxis type="category" dataKey="name" {...axisProps} width={90} orientation="right" />
        <Tooltip content={<TooltipBox unit={unit} />} cursor={{ fill: "rgba(37,99,235,0.06)" }} />
        <Bar dataKey="درآمد" radius={[0, 6, 6, 0]}>
          {data.map((_, i) => (
            <Cell key={i} fill={PIE[i % PIE.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function WeekdayChart({ index }: { index: Record<string, number> }) {
  const data = Object.entries(index).map(([day, v]) => ({ day, شاخص: Number(v.toFixed(2)) }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="day" {...axisProps} />
        <YAxis {...axisProps} tickFormatter={(v) => toFa(v.toFixed(1))} width={40} />
        <Tooltip
          formatter={(v) => [toFa(Number(v).toFixed(2)), "شاخص فروش"]}
          contentStyle={{
            fontFamily: "var(--font-vazir)",
            direction: "rtl",
            fontSize: 12,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 12,
            color: "var(--text)",
          }}
        />
        <Bar dataKey="شاخص" fill={ACCENT} radius={[6, 6, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

import type { ReactNode } from "react";
import { Icon } from "@iconify/react";

export const fmtDate = (ts: number | null | undefined) =>
  ts ? new Date(ts * 1000).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }) : "—";

export const fmtTokens = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `${(n / 1_000).toFixed(1)}k` : String(n);

export const STAGE_LABELS: Record<string, string> = {
  brief_scope: "Brief & Scope", background_research: "Background Research", search_strategy: "Search Strategy",
  matching_label: "Matching label", data_set: "Data set", dataset: "Data set", deliverables: "Deliverables",
};

/** Country name with its circular flag (ISO alpha-2 code). */
export function CountryFlag({ code }: { code: string | null }) {
  if (!code) return <span className="text-slate-400">—</span>;
  const name = new Intl.DisplayNames(undefined, { type: "region" }).of(code.toUpperCase()) ?? code.toUpperCase();
  return (
    <span className="inline-flex items-center gap-1.5">
      <Icon icon={`circle-flags:${code.toLowerCase()}`} width={16} aria-hidden="true" />
      {name}
    </span>
  );
}

export function OrgLogo({ name, logo }: { name: string; logo: string | null }) {
  if (logo) return <img src={logo} alt="" className="h-8 w-8 rounded-lg object-contain border border-slate-100 bg-white" />;
  return (
    <span className="h-8 w-8 rounded-lg bg-[#5B2C9D10] text-[#5B2C9D] text-sm font-bold flex items-center justify-center">
      {name.slice(0, 1).toUpperCase()}
    </span>
  );
}

export function Tile({ label, value, sub, tone = "default" }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: "default" | "warn" | "bad";
}) {
  const ring = tone === "bad" ? "border-red-200 bg-red-50/60" : tone === "warn" ? "border-amber-200 bg-amber-50/60"
    : "border-slate-200 bg-white";
  return (
    <div className={`rounded-xl border px-4 py-3 ${ring}`}>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-bold text-slate-900 tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

/** used / allowed with a thin bar that turns amber at 80% and red when full. */
export function Meter({ used, max }: { used: number; max: number }) {
  const pct = max ? Math.min(100, Math.round((used / max) * 100)) : 0;
  const bar = pct >= 100 ? "bg-red-500" : pct >= 80 ? "bg-amber-500" : "bg-[#5B2C9D]";
  return (
    <div className="min-w-[84px]">
      <div className="text-xs tabular-nums text-slate-700">{used} / {max || "—"}</div>
      <div className="mt-1 h-1 rounded-full bg-slate-100"><div className={`h-1 rounded-full ${bar}`} style={{ width: `${pct}%` }} /></div>
    </div>
  );
}

export function Modal({ title, onClose, children, wide = false }: {
  title: string; onClose: () => void; children: ReactNode; wide?: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-6" role="dialog" aria-modal="true" aria-label={title}>
      <div className={`w-full ${wide ? "max-w-4xl" : "max-w-xl"} rounded-2xl bg-white shadow-xl`}>
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <h2 className="text-base font-semibold text-slate-900">{title}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-xl leading-none" aria-label="Close">×</button>
        </div>
        <div className="p-6">{children}</div>
      </div>
    </div>
  );
}

export const inputCls = "w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-[#5B2C9D] focus:outline-none";
export const labelCls = "block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1";
export const primaryBtn = "rounded-lg bg-[#5B2C9D] text-white font-semibold px-4 py-2 text-sm hover:bg-[#4a2380] disabled:opacity-50";
export const ghostBtn = "rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50";

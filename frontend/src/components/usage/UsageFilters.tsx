import { useState, type ReactNode } from "react";
import { Icon } from "@iconify/react";

export type Preset = "today" | "7d" | "30d" | "month" | "custom";

export interface UsageFilterState {
  preset: Preset;
  from: string;
  to: string;
  org: number | null;
  project: number | null;
  stage: string;
  model: string;
}

const PRESETS: { id: Preset; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "7d", label: "Last 7 days" },
  { id: "30d", label: "Last 30 days" },
  { id: "month", label: "This month" },
  { id: "custom", label: "Custom" },
];

const DAY_MS = 86_400_000;
const isoDay = (ms: number): string => new Date(ms).toISOString().slice(0, 10);

/** The [from, to] of a preset in UTC days, the same days the API filters on. */
export function presetRange(preset: Preset, now = Date.now()): { from: string; to: string } {
  const today = isoDay(now);
  if (preset === "today") return { from: today, to: today };
  if (preset === "7d") return { from: isoDay(now - 6 * DAY_MS), to: today };
  if (preset === "month") return { from: `${today.slice(0, 8)}01`, to: today };
  return { from: isoDay(now - 29 * DAY_MS), to: today };
}

export interface SelectOption { value: string; label: string; icon?: ReactNode }

/** A listbox dropdown whose options carry a logo or icon (a native <select> cannot show images). */
export function LogoSelect({ label, value, options, onChange, allLabel }:
  { label: string; value: string; options: SelectOption[]; onChange: (v: string) => void; allLabel: string }) {
  const [open, setOpen] = useState(false);
  const all: SelectOption = { value: "", label: allLabel, icon: <Icon icon="lucide:layers" width={16} aria-hidden className="text-slate-400" /> };
  const list = [all, ...options];
  const current = list.find((o) => o.value === value) ?? { value, label: value };
  const pick = (v: string) => { setOpen(false); onChange(v); };
  return (
    <div className="relative">
      <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</span>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`${label}: ${current.label}`}
        onClick={() => setOpen((o) => !o)}
        className="flex h-10 w-56 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-left text-sm text-slate-800 shadow-sm hover:border-violet-300 focus:outline-none focus:ring-2 focus:ring-violet-500/20"
      >
        <span className="flex min-w-0 flex-1 items-center gap-2">{current.icon}<span className="truncate">{current.label}</span></span>
        <Icon icon="lucide:chevron-down" width={16} aria-hidden className="shrink-0 text-slate-400" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <ul
            role="listbox"
            aria-label={label}
            onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}
            className="absolute z-50 mt-1 max-h-80 w-72 overflow-auto rounded-2xl border border-slate-100 bg-white p-1.5 shadow-xl"
          >
            {list.map((o) => (
              <li key={o.value || "__all"} role="option" aria-selected={o.value === value}>
                <button
                  type="button"
                  autoFocus={o.value === value}
                  onClick={() => pick(o.value)}
                  className={`flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm ${
                    o.value === value ? "bg-[#5B2C9D]/10 font-semibold text-[#5B2C9D]" : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  {o.icon}<span className="truncate">{o.label}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

interface Props {
  value: UsageFilterState;
  onChange: (next: UsageFilterState) => void;
  orgOptions: SelectOption[] | null;   // null hides the Org selector (not a super_admin)
  projectOptions: SelectOption[];
  stageOptions: SelectOption[];
  modelOptions: SelectOption[];
}

/** Date range with presets, then Org (super_admin), Project, Stage and Model. */
export function UsageFilters({ value, onChange, orgOptions, projectOptions, stageOptions, modelOptions }: Props) {
  const set = (patch: Partial<UsageFilterState>) => onChange({ ...value, ...patch });
  const setDate = (key: "from" | "to", v: string) => { if (v) set({ preset: "custom", [key]: v }); };
  return (
    <div className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-900/5">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Date range presets">
        {PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            aria-pressed={value.preset === p.id}
            onClick={() => set(p.id === "custom" ? { preset: "custom" } : { preset: p.id, ...presetRange(p.id) })}
            className={`rounded-full px-3.5 py-1.5 text-sm font-semibold transition-colors ${
              value.preset === p.id ? "bg-[#5B2C9D] text-white shadow-sm" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            {p.label}
          </button>
        ))}
        <span className="ml-auto text-xs text-slate-500">Days are UTC calendar days, From and To inclusive.</span>
      </div>
      <div className="mt-4 flex flex-wrap items-end gap-4">
        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">From</span>
          <input type="date" value={value.from} max={value.to} onChange={(e) => setDate("from", e.target.value)}
            className="h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-800 shadow-sm focus:border-violet-300 focus:outline-none focus:ring-2 focus:ring-violet-500/20" />
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">To</span>
          <input type="date" value={value.to} min={value.from} onChange={(e) => setDate("to", e.target.value)}
            className="h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-800 shadow-sm focus:border-violet-300 focus:outline-none focus:ring-2 focus:ring-violet-500/20" />
        </label>
        {orgOptions && (
          <LogoSelect label="Org" allLabel="All organisations" value={value.org === null ? "" : String(value.org)}
            options={orgOptions} onChange={(v) => set({ org: v ? Number(v) : null, project: null })} />
        )}
        <LogoSelect label="Project" allLabel="All projects" value={value.project === null ? "" : String(value.project)}
          options={projectOptions} onChange={(v) => set({ project: v ? Number(v) : null })} />
        <LogoSelect label="Stage" allLabel="All stages" value={value.stage} options={stageOptions} onChange={(v) => set({ stage: v })} />
        <LogoSelect label="Model" allLabel="All models" value={value.model} options={modelOptions} onChange={(v) => set({ model: v })} />
      </div>
    </div>
  );
}

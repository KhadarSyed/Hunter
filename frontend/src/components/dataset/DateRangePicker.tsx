import { useEffect, useRef, useState } from "react";
import { Icon } from "@iconify/react";

/** A date range picked from a dropdown calendar showing two months side by side. Dates are ISO days (YYYY-MM-DD);
 * min / max bound the selectable days (the uploaded data's range). */
export function DateRangePicker({ from, to, min, max, onApply }: {
  from: string; to: string; min: string; max: string; onApply: (from: string, to: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<{ from: string; to: string | null }>({ from, to });
  const [month, setMonth] = useState(() => startMonth(to || max));
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  const toggle = () => { setDraft({ from, to }); setMonth(startMonth(to || max)); setOpen((o) => !o); };
  const pick = (iso: string) => setDraft((d) => (d.to === null && iso >= d.from ? { from: d.from, to: iso } : { from: iso, to: null }));
  const next = addMonths(month, 1);

  return (
    <div className="relative" ref={box}>
      <button type="button" onClick={toggle} aria-haspopup="dialog" aria-expanded={open}
        className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">
        <Icon icon="lucide:calendar" width={15} aria-hidden />
        {from ? fmt(from) : "Any date"} – {to ? fmt(to) : "Any date"}
      </button>
      {open && (
        <div role="dialog" aria-label="Choose a date range" className="absolute left-0 top-full z-30 mt-2 w-max max-w-[calc(100vw-32px)] space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-xl">
          <div className="flex items-center justify-between gap-2">
            <button type="button" aria-label="Previous month" onClick={() => setMonth(addMonths(month, -1))} className="rounded-md border border-slate-200 px-2 py-1 text-sm">‹</button>
            <span className="text-xs text-slate-500">{draft.to ? `${fmt(draft.from)} – ${fmt(draft.to)}` : `From ${fmt(draft.from)}: pick the end date`}</span>
            <button type="button" aria-label="Next month" onClick={() => setMonth(addMonths(month, 1))} className="rounded-md border border-slate-200 px-2 py-1 text-sm">›</button>
          </div>
          <div className="grid gap-6 sm:grid-cols-2">
            <Month ym={month} draft={draft} min={min} max={max} onPick={pick} />
            <Month ym={next} draft={draft} min={min} max={max} onPick={pick} />
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" onClick={() => setDraft({ from: min, to: max })} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600">Uploaded data range</button>
            <button type="button" onClick={() => setOpen(false)} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600">Cancel</button>
            <button type="button" disabled={!draft.to} onClick={() => { if (draft.to) { onApply(draft.from, draft.to); setOpen(false); } }}
              className="rounded-lg bg-[#5B2C9D] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40">Apply</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Month({ ym, draft, min, max, onPick }: {
  ym: [number, number]; draft: { from: string; to: string | null }; min: string; max: string; onPick: (iso: string) => void;
}) {
  const [y, m] = ym;
  const first = new Date(y, m, 1);
  const days = new Date(y, m + 1, 0).getDate();
  const end = draft.to ?? draft.from;
  return (
    <div>
      <p className="mb-2 text-center text-sm font-semibold text-slate-800">{first.toLocaleDateString("en-US", { month: "long", year: "numeric" })}</p>
      <div className="grid grid-cols-7 gap-0.5 text-center">
        {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map((d) => <span key={d} className="text-[11px] font-semibold text-slate-400">{d}</span>)}
        {Array.from({ length: first.getDay() }, (_, i) => <span key={`b${i}`} />)}
        {Array.from({ length: days }, (_, i) => {
          const iso = `${y}-${String(m + 1).padStart(2, "0")}-${String(i + 1).padStart(2, "0")}`;
          const off = (min && iso < min) || (max && iso > max);
          const edge = iso === draft.from || iso === end;
          const inside = iso > draft.from && iso < end;
          return (
            <button key={iso} type="button" disabled={Boolean(off)} onClick={() => onPick(iso)} aria-label={fmt(iso)} aria-pressed={edge}
              className={`h-8 w-8 rounded-md text-xs ${edge ? "bg-[#5B2C9D] font-semibold text-white" : inside ? "bg-violet-100 text-slate-800" : "text-slate-700 hover:bg-slate-100"} disabled:cursor-default disabled:text-slate-300 disabled:hover:bg-transparent`}>
              {i + 1}
            </button>
          );
        })}
      </div>
    </div>
  );
}

const fmt = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

function startMonth(iso: string): [number, number] {
  const d = iso ? new Date(`${iso.slice(0, 10)}T00:00:00`) : new Date();
  return addMonths([d.getFullYear(), d.getMonth()], -1);        // the end date shows in the right-hand month
}

function addMonths([y, m]: [number, number], n: number): [number, number] {
  const t = y * 12 + m + n;
  return [Math.floor(t / 12), ((t % 12) + 12) % 12];
}

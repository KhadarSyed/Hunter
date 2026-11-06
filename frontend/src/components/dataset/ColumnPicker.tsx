import { useState } from "react";

export const COLUMN_GROUPS = [
  { id: "details", label: "Details" },
  { id: "author", label: "Author (social)" },
  { id: "sentiment", label: "Sentiment & brands" },
  { id: "themes", label: "Themes" },
  { id: "other", label: "Signals, entities, category, group" },
  { id: "rq", label: "Research questions" },
] as const;
export type GroupId = (typeof COLUMN_GROUPS)[number]["id"];

const KEY = "hunter.dataset.hiddenGroups";

export function loadHidden(): GroupId[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v : [];
  } catch { return []; }
}

export function saveHidden(hidden: GroupId[]) {
  try { window.localStorage.setItem(KEY, JSON.stringify(hidden)); } catch { /* storage unavailable */ }
}

export function ColumnPicker({ hidden, onChange }: { hidden: GroupId[]; onChange: (h: GroupId[]) => void }) {
  const [open, setOpen] = useState(false);
  const toggle = (id: GroupId) => onChange(hidden.includes(id) ? hidden.filter((g) => g !== id) : [...hidden, id]);
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="text-xs font-medium px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50">Columns</button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-60 rounded-lg border border-slate-200 bg-white p-2 shadow-lg">
          {COLUMN_GROUPS.map((g) => (
            <label key={g.id} className="flex items-center gap-2 px-2 py-1 text-xs text-slate-700">
              <input type="checkbox" className="accent-[#5B2C9D]" checked={!hidden.includes(g.id)} onChange={() => toggle(g.id)} />
              {g.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

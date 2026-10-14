import { useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { Icon } from "@iconify/react";

export type TabItem<T extends string> = { id: T; label: string; icon: string; badge?: ReactNode };

type Props<T extends string> = {
  tabs: TabItem<T>[];
  active: T;
  onChange: (id: T) => void;
  label: string;
  size?: "md" | "sm";
};

/** An accessible tab strip: arrow keys, Home and End move between tabs; the active one is the only one in the
 * tab order. */
export function Tabs<T extends string>({ tabs, active, onChange, label, size = "md" }: Props<T>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const move = (e: KeyboardEvent, index: number) => {
    const last = tabs.length - 1;
    const next = e.key === "ArrowRight" ? (index === last ? 0 : index + 1)
      : e.key === "ArrowLeft" ? (index === 0 ? last : index - 1)
      : e.key === "Home" ? 0 : e.key === "End" ? last : -1;
    if (next < 0) return;
    e.preventDefault();
    onChange(tabs[next].id);
    refs.current[next]?.focus();
  };
  const pad = size === "md" ? "px-4 py-2.5 text-sm" : "px-3 py-1.5 text-xs";
  return (
    <div role="tablist" aria-label={label}
      className={size === "md" ? "flex gap-1 overflow-x-auto border-b border-slate-200" : "flex flex-wrap gap-2"}>
      {tabs.map((t, i) => {
        const isActive = t.id === active;
        const look = size === "md"
          ? `-mb-px border-b-2 ${isActive ? "border-[#5B2C9D] text-[#5B2C9D]" : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700"}`
          : `rounded-full border ${isActive ? "border-[#5B2C9D] bg-[#5B2C9D] text-white" : "border-slate-200 bg-white text-slate-600 hover:border-violet-300"}`;
        return (
          <button key={t.id} ref={(el) => { refs.current[i] = el; }} type="button" role="tab" id={`tab-${t.id}`}
            aria-selected={isActive} aria-controls={`panel-${t.id}`} tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(t.id)} onKeyDown={(e) => move(e, i)}
            className={`inline-flex shrink-0 items-center gap-2 whitespace-nowrap font-medium transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5B2C9D] ${pad} ${look}`}>
            <Icon icon={t.icon} width={size === "md" ? 16 : 13} />
            {t.label}
            {t.badge}
          </button>
        );
      })}
    </div>
  );
}

/** The content of one tab, labelled by its tab. */
export function TabPanel({ id, children }: { id: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`} tabIndex={0} className="space-y-6 focus:outline-none">
      {children}
    </div>
  );
}

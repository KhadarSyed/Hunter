import { useState } from "react";
import type { ArticleRow } from "../../types/dataset";

const POPOVER_W = 384;
const POPOVER_H = 256;

/** 3-line clamp; hover or keyboard focus opens a scrollable popover with the full text. */
export function ContentCell({ row }: { row: ArticleRow }) {
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const text = row.content || row.summary || "";
  if (!text) return <span className="text-slate-300 text-xs">—</span>;
  const isSummary = row.content_status !== "full_text";
  const open = (el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    const below = r.bottom + POPOVER_H < window.innerHeight;
    setPos({ left: Math.max(8, Math.min(r.left, window.innerWidth - POPOVER_W - 8)), top: below ? r.bottom - 2 : r.top - POPOVER_H + 2 });
  };
  return (
    <div tabIndex={0} aria-label="Article content" className="outline-none focus-visible:ring-2 ring-violet-300 rounded"
      onMouseEnter={(e) => open(e.currentTarget)} onFocus={(e) => open(e.currentTarget)}
      onMouseLeave={() => setPos(null)} onBlur={() => setPos(null)} onKeyDown={(e) => e.key === "Escape" && setPos(null)}>
      {isSummary && <span className="text-[9px] font-semibold uppercase tracking-wide text-amber-600">Summary </span>}
      <span className="text-xs text-slate-700" style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
        {text}
      </span>
      {pos && (
        <div role="tooltip" style={{ position: "fixed", left: pos.left, top: pos.top, width: POPOVER_W, maxHeight: POPOVER_H }}
          className="z-50 overflow-y-auto rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-700 shadow-xl whitespace-pre-wrap">
          {isSummary && <p className="mb-1 text-[10px] font-semibold uppercase text-amber-600">Summary (full text unavailable)</p>}
          {text}
        </div>
      )}
    </div>
  );
}

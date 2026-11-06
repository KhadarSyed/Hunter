import { useRef } from "react";
import { tokenizeBooleanQuery } from "../../pages/SearchStrategy";

const TONE: Record<string, string> = { operator: "text-[#5B2C9D] font-bold", quote: "text-emerald-700", paren: "text-amber-600 font-bold",
  near: "text-sky-700 font-bold", text: "text-slate-800" };

/** Monospace Boolean editor: AND / OR / NOT, quotes and brackets highlighted by a <pre> under a transparent textarea. */
export function QueryEditor({ value, onChange, invalid }: { value: string; onChange: (v: string) => void; invalid?: boolean }) {
  const pre = useRef<HTMLPreElement>(null);
  const cls = "m-0 w-full whitespace-pre-wrap break-words px-3 py-2 font-mono text-xs leading-5";
  return (
    <div className={`relative rounded-lg border bg-white ${invalid ? "border-red-300" : "border-slate-200"} focus-within:ring-2 focus-within:ring-[#5B2C9D]/30`}>
      <pre ref={pre} aria-hidden className={`${cls} pointer-events-none absolute inset-0 overflow-hidden`}>
        {tokenizeBooleanQuery(value).map((t, i) => <span key={i} className={TONE[t.type]}>{t.text}</span>)}{"\n"}
      </pre>
      <textarea value={value} onChange={(e) => onChange(e.target.value)} spellCheck={false} rows={6} aria-label="Boolean query"
        onScroll={(e) => { if (pre.current) pre.current.scrollTop = e.currentTarget.scrollTop; }}
        className={`${cls} relative block min-h-[8rem] resize-y bg-transparent text-transparent caret-slate-900 outline-none`} />
    </div>
  );
}

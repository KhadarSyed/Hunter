import type { ReactNode } from "react";
import type { EnrichedRecord } from "../services/intel-api";

const humanize = (name: string) => name.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** A query term as a pattern: a trailing * matches word endings (cream* -> creams). */
const termPattern = (t: string) => escape(t.replace(/\*$/, "")).replace(/\s+/g, "\\s+") + (t.endsWith("*") ? "\\w*" : "");

/** The article's text with its question keywords (amber) and the tags' quoted evidence (green) highlighted. */
export function HighlightedText({ text, keywords, evidence }: { text: string; keywords: string[]; evidence: string[] }) {
  const parts = [...evidence.filter(Boolean).map(escape), ...keywords.filter(Boolean).map(termPattern)];
  if (!text || parts.length === 0) return <>{text}</>;
  const re = new RegExp(`(${parts.join("|")})`, "gi");
  const quotes = new Set(evidence.map((e) => e.toLowerCase()));
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    const i = m.index ?? 0;
    if (i > last) out.push(text.slice(last, i));
    const isQuote = quotes.has(m[0].toLowerCase());
    out.push(<mark key={i} className={isQuote ? "bg-emerald-100 text-emerald-900 rounded px-0.5" : "bg-amber-100 text-amber-900 rounded px-0.5"}>{m[0]}</mark>);
    last = i + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}

/** Drill-down for one article: what it says about its research question, each question tag with the quote that
 * supports it, the search keywords it matched, and the full text with both highlighted. */
export function QuestionDrillDown({ record }: { record: EnrichedRecord }) {
  const tags = Object.entries(record.dynamic_tags || {});
  const keywords = record.keyword_matches || [];
  const evidence = Object.values(record.tag_evidence || {});
  if (!tags.length && !keywords.length && !record.question_summary) return null;
  return (
    <div className="rounded-xl border border-indigo-100 bg-indigo-50/30 p-3 mb-4 space-y-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-indigo-800">
        {record.tag_schema_question || record.research_question_id || "Question"} · question drill-down
      </div>
      {record.question_summary && (
        <div>
          <div className="text-[10px] font-semibold text-slate-500 mb-0.5">Summary for the question</div>
          <p className="text-xs text-slate-700">{record.question_summary}</p>
        </div>
      )}
      {tags.length > 0 && (
        <div>
          <div className="text-[10px] font-semibold text-slate-500 mb-1">Question tags</div>
          <div className="space-y-1.5">
            {tags.map(([name, value]) => {
              const conf = record.tag_confidence?.[name];
              const quote = record.tag_evidence?.[name];
              return (
                <div key={name} className="text-xs">
                  <span className="font-medium text-slate-700">{humanize(name)}:</span>{" "}
                  <span className="text-indigo-700">{Array.isArray(value) ? value.join(", ") : value}</span>
                  {conf != null && <span className="text-slate-400"> · {Math.round(conf * 100)}%</span>}
                  {quote
                    ? <div className="mt-0.5 border-l-2 border-emerald-300 pl-2 text-[11px] italic text-slate-600">"{quote}"</div>
                    : <div className="mt-0.5 text-[10px] text-slate-400">No quote from the article supports this value</div>}
                </div>
              );
            })}
          </div>
        </div>
      )}
      {keywords.length > 0 && (
        <div>
          <div className="text-[10px] font-semibold text-slate-500 mb-1">Keyword matches</div>
          <div className="flex flex-wrap gap-1">
            {keywords.map((k) => <span key={k} className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-800">{k}</span>)}
          </div>
        </div>
      )}
      {record.content && (
        <div>
          <div className="text-[10px] font-semibold text-slate-500 mb-1">Content (keywords in amber, evidence in green)</div>
          <p className="text-xs leading-relaxed text-slate-700 whitespace-pre-wrap">
            <HighlightedText text={record.content} keywords={keywords} evidence={evidence} />
          </p>
        </div>
      )}
    </div>
  );
}

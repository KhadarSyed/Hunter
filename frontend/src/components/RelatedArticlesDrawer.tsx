import { formatDate as formatDateUS } from "../utils/format";
import type { ResearchItem } from "../services/intel-api";

export type RelationKind = "syndicated" | "similar";

const HEADINGS: Record<RelationKind, { title: string; note: string }> = {
  syndicated: {
    title: "Syndicated",
    note: "The same article, published by other publishers or vendors.",
  },
  similar: {
    title: "Similar",
    note: "Other articles with the same theme, content, motive or context — closest first.",
  },
};

type Props = {
  kind: RelationKind;
  source: ResearchItem;
  related: ResearchItem[];
  onClose: () => void;
};

function formatDate(ts: number): string {
  try {
    return formatDateUS(ts * 1000);
  } catch {
    return "";
  }
}

export function AccessBadge({ access }: { access: ResearchItem["access"] }) {
  if (!access) return <span className="text-slate-300">—</span>;
  const isPaid = access === "paid";
  return (
    <span
      title={isPaid ? "The site refuses readers or puts this behind a subscription" : "Opens without a subscription"}
      className={`px-1.5 py-0.5 rounded text-[10px] font-medium whitespace-nowrap ${
        isPaid ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"
      }`}
    >
      {isPaid ? "Paid" : "Free"}
    </span>
  );
}

/** Right-side drawer listing the articles behind a Syndicated / Similar count in the All Articles table. */
export function RelatedArticlesDrawer({ kind, source, related, onClose }: Props) {
  const heading = HEADINGS[kind];
  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${heading.title} articles`}
        className="relative w-full max-w-xl h-full bg-white shadow-2xl overflow-y-auto p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 mb-1">
          <h3 className="text-base font-semibold text-slate-800">
            {heading.title} · {related.length}
          </h3>
          <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-slate-600 shrink-0">
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <p className="text-xs text-slate-500 mb-3">{heading.note}</p>
        <div className="rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 mb-4">
          <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-0.5">For</div>
          <div className="text-xs font-medium text-slate-700">{source.title || "(untitled)"}</div>
          <div className="text-[11px] text-slate-400">{source.publication || source.domain}</div>
        </div>
        <ol className="space-y-3">
          {related.map((item) => (
            <li key={item.id} className="border-b border-slate-100 pb-3">
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-[#5B2C9D] hover:underline font-medium"
              >
                {item.title || "(untitled)"}
              </a>
              <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-500 flex-wrap">
                <span>{item.publication || item.domain || "Unknown"}</span>
                <span>• {formatDate(item.published_date)}</span>
                <AccessBadge access={item.access} />
              </div>
              {item.content && <p className="text-xs text-slate-500 mt-1 line-clamp-2">{item.content}</p>}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

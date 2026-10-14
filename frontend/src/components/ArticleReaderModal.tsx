import { useEffect, useState } from "react";
import { intelApi, type ArticleFullTextResponse } from "../services/intel-api";

interface Props {
  itemId: number;
  sourceUrl: string;
  onClose: () => void;
}

/** Full-article reader popup for the "All Articles" tab — fetches the normalized,
 * structured extraction (domains/research/article_extractor.py) and renders it as a
 * scrollable reading view: headings and paragraphs in order, images full-width between
 * paragraphs exactly where they appeared on the source page. */
export function ArticleReaderModal({ itemId, sourceUrl, onClose }: Props) {
  const [result, setResult] = useState<ArticleFullTextResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);

  const load = (force = false) => {
    setLoading(true);
    intelApi.getArticleFullText(itemId, force)
      .then(setResult)
      .catch(() => setResult({ status: "failed", title: null, blocks: [], error: "Request failed", platform: null, embed_url: null, cached: false }))
      .finally(() => { setLoading(false); setRetrying(false); });
  };

  useEffect(() => { load(); }, [itemId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleRetry = () => { setRetrying(true); load(true); };

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/50" onClick={onClose} />
      <div className="relative w-full max-w-2xl max-h-[85vh] bg-white rounded-2xl shadow-2xl flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100 shrink-0">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-slate-900 truncate">
              {result?.title || "Reading article..."}
            </h2>
            <a href={sourceUrl} target="_blank" rel="noopener noreferrer"
               className="text-xs text-[#5B2C9D] hover:underline truncate block">
              {sourceUrl}
            </a>
          </div>
          <button onClick={onClose} className="shrink-0 ml-3 text-slate-400 hover:text-slate-600 text-lg leading-none">✕</button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Fetching and extracting the full article...
            </div>
          ) : result?.status === "ok" ? (
            <article className="prose-sm max-w-none space-y-4">
              {result.blocks.map((b, i) => {
                if (b.type === "heading") {
                  return <h3 key={i} className="text-base font-semibold text-slate-900 mt-2">{b.text}</h3>;
                }
                if (b.type === "image" && b.src) {
                  return (
                    <img key={i} src={b.src} alt={b.alt || ""} loading="lazy"
                         className="w-full rounded-lg object-cover"
                         onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
                  );
                }
                return <p key={i} className="text-sm leading-relaxed text-slate-700">{b.text}</p>;
              })}
            </article>
          ) : result?.status === "video" && result.embed_url ? (
            <div className="aspect-video w-full rounded-lg overflow-hidden bg-slate-900">
              <iframe src={result.embed_url} className="w-full h-full" allow="autoplay; encrypted-media"
                      allowFullScreen title={result.platform || "Video"} />
            </div>
          ) : result?.status === "social_media" ? (
            <div className="flex flex-col items-center text-center py-10">
              <p className="text-sm text-slate-600">
                This is a {result.platform} post — not an article, so there's no body text to
                show here. Open it directly to view the real post, images, and comments.
              </p>
              <a href={sourceUrl} target="_blank" rel="noopener noreferrer"
                 className="mt-4 rounded-lg bg-[#5B2C9D] px-4 py-2 text-sm font-semibold text-white hover:bg-[#4A2380]">
                Open on {result.platform}
              </a>
            </div>
          ) : (
            <div className="flex flex-col items-center text-center py-10">
              <p className="text-sm text-slate-600">
                {result?.status === "paywalled"
                  ? "This article is behind a paywall — only the headline could be read."
                  : `Couldn't extract the full article${result?.error ? ` (${result.error})` : ""}.`}
              </p>
              <div className="mt-4 flex items-center gap-2">
                <button onClick={handleRetry} disabled={retrying}
                        className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40">
                  {retrying ? "Retrying..." : "Retry"}
                </button>
                <a href={sourceUrl} target="_blank" rel="noopener noreferrer"
                   className="rounded-lg bg-[#5B2C9D] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#4A2380]">
                  Open original
                </a>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { intelApi, type ResearchItem } from "../services/intel-api";

function faviconUrl(domain: string | null): string | null {
  if (!domain) return null;
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=32`;
}

function sourceLabel(sourceApi: string): string {
  switch (sourceApi) {
    case "google_news_rss":
      return "Google RSS";
    case "tavily":
      return "Tavily";
    case "serpapi":
      return "SerpAPI";
    default:
      return sourceApi;
  }
}

function formatDate(ts: number): string {
  try {
    return new Date(ts * 1000).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return "";
  }
}

interface ResearchItemsTableProps {
  projectId: number;
}

/** All articles/posts collected across every Boolean query and source for the project's
 * latest research run — the full underlying item set, not the already-filtered news_items
 * the composed Brief draws from. Shows roughly 20 rows before scrolling for the rest. */
export function ResearchItemsTable({ projectId }: ResearchItemsTableProps) {
  const [items, setItems] = useState<ResearchItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setError(null);
    intelApi
      .getResearchItems(projectId)
      .then((res) => {
        if (!cancelled) setItems(res.items);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load research articles.");
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (error) {
    return <div className="text-sm text-red-500">{error}</div>;
  }

  if (!items) {
    return <div className="text-sm text-slate-400 italic">Loading articles…</div>;
  }

  if (items.length === 0) {
    return <div className="text-sm text-slate-400 italic">No articles found for this run.</div>;
  }

  return (
    <div className="max-w-6xl">
      <div className="text-xs text-slate-500 mb-3">
        {items.length} article{items.length === 1 ? "" : "s"} collected across every query and source for this run
      </div>
      <div className="border border-slate-200 rounded-lg overflow-hidden">
        <div className="max-h-[640px] overflow-y-auto">
          <table className="w-full text-xs border-collapse">
            <thead className="bg-slate-50 border-b border-slate-200 sticky top-0 z-10">
              <tr>
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-40">Publisher</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-24">Source</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500">Title</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500">Content</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-28">Author</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-24">Published</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-40">Keywords Matched</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-20">Relevant</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {items.map((item) => {
                const favicon = faviconUrl(item.domain);
                return (
                  <tr key={item.id} className="align-top hover:bg-slate-50/70">
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-1.5">
                        {favicon && (
                          <img
                            src={favicon}
                            alt=""
                            className="w-4 h-4 rounded-sm shrink-0"
                            onError={(e) => {
                              (e.currentTarget as HTMLImageElement).style.display = "none";
                            }}
                          />
                        )}
                        <span className="text-slate-700 truncate">
                          {item.publication || item.domain || "Unknown"}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className="px-1.5 py-0.5 bg-slate-50 text-slate-600 rounded text-[10px] whitespace-nowrap">
                        {sourceLabel(item.source_api)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 max-w-xs">
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[#5B2C9D] hover:underline font-medium line-clamp-2"
                      >
                        {item.title || "(untitled)"}
                      </a>
                    </td>
                    <td className="px-3 py-2.5 max-w-sm">
                      <span className="text-slate-600 line-clamp-2">{item.content || "—"}</span>
                    </td>
                    <td className="px-3 py-2.5 text-slate-500">{item.author || "—"}</td>
                    <td className="px-3 py-2.5 text-slate-500 whitespace-nowrap">
                      {formatDate(item.published_date)}
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {item.keywords_matched.length > 0 ? (
                          item.keywords_matched.map((kw) => (
                            <span
                              key={kw}
                              className="px-1.5 py-0.5 bg-violet-50 text-violet-700 rounded text-[10px]"
                            >
                              {kw}
                            </span>
                          ))
                        ) : (
                          <span className="text-slate-300">—</span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                          item.relevant
                            ? "bg-emerald-50 text-emerald-700"
                            : "bg-slate-100 text-slate-400"
                        }`}
                      >
                        {item.relevant ? "Yes" : "No"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

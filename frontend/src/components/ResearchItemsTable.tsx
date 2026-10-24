import { formatDate as formatDateUS } from "../utils/format";
import { useEffect, useState } from "react";
import {
  intelApi,
  type ItemClassification,
  type ItemRelations,
  type ResearchItem,
} from "../services/intel-api";
import { ArticleReaderModal } from "./ArticleReaderModal";
import { AccessBadge, RelatedArticlesDrawer, type RelationKind } from "./RelatedArticlesDrawer";

function faviconUrl(domain: string | null): string | null {
  if (!domain) return null;
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=32`;
}

function singleSourceLabel(sourceApi: string): string {
  switch (sourceApi) {
    case "google_news_rss":
      return "Google RSS";
    case "tavily":
      return "Tavily";
    case "serpapi":
      return "SerpAPI";
    case "youtube":
      return "YouTube";
    case "bluesky":
      return "Bluesky";
    case "searxng":
      return "SearXNG";
    default:
      return sourceApi;
  }
}

/** source_api accumulates every source that reported this same article's URL as a
 * comma-joined string (see repository.py's upsert_research_item) — e.g. a row found by
 * both SerpAPI and Google News RSS shows "SerpAPI + Google RSS" instead of just one. */
function sourceLabel(sourceApi: string): string {
  return sourceApi.split(",").filter(Boolean).map(singleSourceLabel).join(" + ");
}

function formatDate(ts: number): string {
  try {
    return formatDateUS(ts * 1000);
  } catch {
    return "";
  }
}

const ABOUT_BRAND_MIN = 0.5; // matches backend classify.ABOUT_BRAND_MIN

const SENTIMENT_STYLE: Record<NonNullable<ItemClassification["sentiment"]>, string> = {
  positive: "bg-emerald-50 text-emerald-700",
  neutral: "bg-slate-100 text-slate-600",
  negative: "bg-rose-50 text-rose-700",
};

interface ResearchItemsTableProps {
  projectId: number;
}

/** All articles/posts collected across every Boolean query and source for the project's
 * latest research run — the full underlying item set, not the already-filtered news_items
 * the composed Brief draws from. Shows roughly 20 rows before scrolling for the rest. */
export function ResearchItemsTable({ projectId }: ResearchItemsTableProps) {
  const [items, setItems] = useState<ResearchItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [readingItem, setReadingItem] = useState<ResearchItem | null>(null);
  // undefined = still loading, null = failed to load
  const [relations, setRelations] = useState<Record<string, ItemRelations> | null | undefined>(undefined);
  const [openRelation, setOpenRelation] = useState<{ kind: RelationKind; item: ResearchItem } | null>(null);
  const [classified, setClassified] = useState<Record<string, ItemClassification>>({});

  // Jev's relevance + sentiment, loaded after the table; absent (no key, or failed) = the rule-based Relevant.
  useEffect(() => {
    let cancelled = false;
    setClassified({});
    intelApi
      .getResearchItemClassification(projectId)
      .then((res) => {
        if (!cancelled) setClassified(res.classifications);
      })
      .catch(() => {
        /* the rule-based Relevant column stays */
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

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

  // Loaded separately so the table shows at once; the first load of a project embeds its articles.
  useEffect(() => {
    let cancelled = false;
    setRelations(undefined);
    intelApi
      .getResearchItemRelations(projectId)
      .then((res) => {
        if (!cancelled) setRelations(res.relations);
      })
      .catch(() => {
        if (!cancelled) setRelations(null);
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

  const byId = new Map(items.map((item) => [item.id, item]));
  const relatedItems = (item: ResearchItem, kind: RelationKind): ResearchItem[] =>
    (relations?.[String(item.id)]?.[kind] ?? [])
      .map((id) => byId.get(id))
      .filter((found): found is ResearchItem => Boolean(found));

  const relevantCell = (item: ResearchItem) => {
    const about = classified[String(item.id)]?.about_brand;
    const isRelevant = about == null ? item.relevant : about >= ABOUT_BRAND_MIN;
    const label = isRelevant ? "Yes" : "No";
    return (
      <span
        title={about == null ? "Rule-based check" : "Jev: probability this is about the brand"}
        className={`px-1.5 py-0.5 rounded text-[10px] font-medium whitespace-nowrap ${
          isRelevant ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-400"
        }`}
      >
        {about == null ? label : `${label} ${Math.round(about * 100)}%`}
      </span>
    );
  };

  const sentimentCell = (item: ResearchItem) => {
    const found = classified[String(item.id)];
    if (!found?.sentiment) return <span className="text-slate-300">—</span>;
    const style = SENTIMENT_STYLE[found.sentiment];
    const confidence = found.sentiment_confidence == null ? "" : ` (${Math.round(found.sentiment_confidence * 100)}% sure)`;
    return (
      <span
        title={`Tone toward the brand${confidence}`}
        className={`px-1.5 py-0.5 rounded text-[10px] font-medium capitalize ${style}`}
      >
        {found.sentiment}
      </span>
    );
  };

  const relationCell = (item: ResearchItem, kind: RelationKind) => {
    if (relations === undefined) return <span className="text-slate-300">…</span>;
    if (relations === null) return <span className="text-slate-300" title="Could not load">—</span>;
    const count = relatedItems(item, kind).length;
    if (count === 0) return <span className="text-slate-300">0</span>;
    return (
      <button
        onClick={() => setOpenRelation({ kind, item })}
        className="px-1.5 py-0.5 rounded bg-violet-50 text-[#5B2C9D] font-semibold hover:bg-violet-100 hover:underline"
        aria-label={`${count} ${kind} article${count === 1 ? "" : "s"}`}
      >
        {count}
      </button>
    );
  };

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
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-14">Thumb</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-40">Publisher</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-24">Source</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500">Title</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500">Content</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-28">Author</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-24">Published</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-16">Access</th>
                <th
                  className="text-left px-3 py-2 font-medium text-slate-500 w-20"
                  title="The same article published by other publishers or vendors"
                >
                  Syndicated
                </th>
                <th
                  className="text-left px-3 py-2 font-medium text-slate-500 w-16"
                  title="Other articles with the same theme, content, motive or context"
                >
                  Similar
                </th>
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-40">Keywords Matched</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-20">Relevant</th>
                <th className="text-left px-3 py-2 font-medium text-slate-500 w-20">Sentiment</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {items.map((item) => {
                const favicon = faviconUrl(item.domain);
                return (
                  <tr key={item.id} className="align-top hover:bg-slate-50/70">
                    <td className="px-3 py-2.5">
                      {item.thumbnail_url ? (
                        <img
                          src={item.thumbnail_url}
                          alt=""
                          className="w-10 h-10 rounded object-cover shrink-0"
                          onError={(e) => {
                            (e.currentTarget as HTMLImageElement).style.display = "none";
                          }}
                        />
                      ) : (
                        <div className="w-10 h-10 rounded bg-slate-100" aria-hidden="true" />
                      )}
                    </td>
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
                      <button
                        onClick={() => setReadingItem(item)}
                        className="block mt-1 text-[10px] font-medium text-slate-400 hover:text-[#5B2C9D] hover:underline"
                      >
                        Read full article
                      </button>
                    </td>
                    <td className="px-3 py-2.5 max-w-sm">
                      <span className="text-slate-600 line-clamp-2">{item.content || "—"}</span>
                    </td>
                    <td className="px-3 py-2.5 text-slate-500">{item.author || "—"}</td>
                    <td className="px-3 py-2.5 text-slate-500 whitespace-nowrap">
                      {formatDate(item.published_date)}
                    </td>
                    <td className="px-3 py-2.5">
                      <AccessBadge access={item.access} />
                    </td>
                    <td className="px-3 py-2.5">{relationCell(item, "syndicated")}</td>
                    <td className="px-3 py-2.5">{relationCell(item, "similar")}</td>
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
                    <td className="px-3 py-2.5">{relevantCell(item)}</td>
                    <td className="px-3 py-2.5">{sentimentCell(item)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      {readingItem && (
        <ArticleReaderModal
          itemId={readingItem.id}
          sourceUrl={readingItem.url}
          onClose={() => setReadingItem(null)}
        />
      )}
      {openRelation && (
        <RelatedArticlesDrawer
          kind={openRelation.kind}
          source={openRelation.item}
          related={relatedItems(openRelation.item, openRelation.kind)}
          onClose={() => setOpenRelation(null)}
        />
      )}
    </div>
  );
}

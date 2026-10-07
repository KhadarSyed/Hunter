import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { createPortal } from "react-dom";
import { intelApi, type BriefResult, type BriefData, type BriefSection, type JobStatus, type SourceRef } from "../services/intel-api";
import { useDemoState } from "../context/demo-state";
import { useProject, useActiveProjectId } from "../context/project-context";
import { useJobStatus } from "../hooks/useJobStatus";
import { useAgentSocket } from "../hooks/useAgentSocket";
import type { WsMessage } from "../services/ws";
import { BrandLogo } from "../components/BrandLogo";
import { CountryFlag } from "../components/CountryFlag";
import { ResearchItemsTable } from "../components/ResearchItemsTable";

type PageState = "idle" | "researching" | "composing" | "ready" | "failed";

const SECTION_ICONS: Record<string, string> = {
  company_introduction: "M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4",
  executive_summary: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2",
  brand_developments: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6",
  brand_narrative: "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z",
  competitor_developments: "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z",
  industry_context: "M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  key_issues: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z",
  source_register: "M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10",
  methodology: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z",
};

const SECTION_SHORT_LABELS: Record<string, string> = {
  company_introduction: "Introduction",
  executive_summary: "Exec Summary",
  brand_developments: "Brand Developments",
  brand_narrative: "Brand Narrative",
  competitor_developments: "Competitors",
  industry_context: "Industry Context",
  key_issues: "Key Issues",
  source_register: "Sources",
  methodology: "Methodology",
};

/** What "Tier 1/2/3" actually means — mirrors web_research.py's TIER_1_DOMAINS /
 * TIER_2_DOMAINS / TIER_3_DOMAINS classification (source credibility, not article
 * importance), so a reader isn't left guessing what the T1/T2/T3 counts stand for. */
const SOURCE_TIER_LABELS = {
  tier_1: "Top-tier wire services, financial press & government sources (Reuters, AP, Bloomberg, WSJ, FT, NYT, BBC, .gov/.edu)",
  tier_2: "Reputable business, trade & industry press (Forbes, CNBC, TechCrunch, Ad Age, McKinsey, Gartner, trade publications)",
  tier_3: "General web, lifestyle & blog sources (Medium, Substack, consumer/lifestyle sites) — lower source credibility, used for color/context",
};

interface ProgressLogEntry {
  message: string;
  pct: number;
  at: number;
}

function ProgressBar({
  pct, message, startedAt, geography, timePeriod, log, showLog, onToggleLog,
}: {
  pct: number;
  message: string;
  startedAt: number | null;
  geography?: string;
  timePeriod?: string;
  log: ProgressLogEntry[];
  showLog: boolean;
  onToggleLog: () => void;
}) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startedAt) return;
    const tick = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(tick);
  }, [startedAt]);

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  const timeStr = mins > 0 ? `${mins}m ${secs.toString().padStart(2, "0")}s` : `${secs}s`;

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-4">
      {geography && (
        <div className="flex items-center gap-2 text-xs text-slate-500 pb-3 border-b border-slate-100">
          <span className="text-slate-400 uppercase tracking-wide text-[10px] font-semibold">Scope</span>
          <CountryFlag country={geography} size={14} showLabel />
          {timePeriod && <span className="text-slate-300">·</span>}
          {timePeriod && <span>{timePeriod}</span>}
        </div>
      )}
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center gap-2.5">
          <div className="relative w-5 h-5 shrink-0">
            <div className="absolute inset-0 rounded-full border-2 border-[#5B2C9D]/20" />
            <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-[#5B2C9D] animate-spin" />
          </div>
          <span className="text-slate-700 font-medium">{message || "Processing..."}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400 tabular-nums">{timeStr}</span>
          <span className="text-slate-500 font-semibold tabular-nums">{pct}%</span>
        </div>
      </div>
      <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: "linear-gradient(90deg, #5B2C9D, #7C4DFF)" }} />
      </div>
      {log.length > 0 && (
        <div className="pt-1 border-t border-slate-100">
          <button
            type="button"
            onClick={onToggleLog}
            className="flex items-center gap-1.5 text-[11px] font-medium text-slate-400 hover:text-slate-600 transition-colors"
          >
            <svg className={`w-3 h-3 transition-transform ${showLog ? "rotate-180" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="6 9 12 15 18 9" />
            </svg>
            {showLog ? "Hide" : "Show"} search log ({log.length})
          </button>
          {showLog && (
            <div className="mt-2 max-h-40 overflow-y-auto space-y-1">
              {log.map((entry, i) => (
                <div key={i} className="text-[11px] text-slate-500 flex items-start gap-2">
                  <span className="text-slate-300 tabular-nums shrink-0 w-8">{entry.pct}%</span>
                  <span>{entry.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

type SourceLookup = Record<string, SourceRef>;

/** Publisher favicon as a circular badge, falling back to the publisher's initial (SourceInitial)
 * if the URL can't be parsed or the favicon fails to load. */
function CitationLink({ refId, sources }: { refId: string; sources: SourceLookup }) {
  const src = sources[refId];
  const [faviconFailed, setFaviconFailed] = useState(false);
  if (!src || !src.url) {
    return <span className="font-bold text-[#5B2C9D] text-[10px]">[{refId}]</span>;
  }
  const title = `${src.headline} — ${src.publisher}${src.date ? ` (${src.date})` : ""}`;
  let domain = "";
  try {
    domain = new URL(src.url).hostname;
  } catch {
    // leave domain empty — falls back to the text badge below
  }

  return (
    <a
      href={src.url}
      target="_blank"
      rel="noopener noreferrer"
      title={title}
      className="inline-flex items-center justify-center align-middle mx-0.5 hover:scale-110 transition-transform cursor-pointer"
    >
      {domain && !faviconFailed ? (
        <img
          src={`https://www.google.com/s2/favicons?domain=${domain}&sz=32`}
          alt={src.publisher}
          onError={() => setFaviconFailed(true)}
          className="w-3.5 h-3.5 rounded-full ring-1 ring-slate-200 bg-white"
        />
      ) : (
        <SourceInitial label={src.publisher || domain} />
      )}
    </a>
  );
}

/** Icon-style fallback when a favicon can't load: the publisher's initial in a small circle (never "S#"). */
function SourceInitial({ label }: { label: string }) {
  const letter = (label.replace(/^www\./, "").trim()[0] || "?").toUpperCase();
  return (
    <span className="inline-flex w-3.5 h-3.5 items-center justify-center rounded-full bg-[#5B2C9D]/10 text-[#5B2C9D] text-[8px] font-bold ring-1 ring-slate-200">
      {letter}
    </span>
  );
}

/** Per-section source list: one icon chip per cited source; flags a section left without any. */
function SectionSources({ section, sources }: { section: BriefSection; sources: SourceLookup }) {
  if (section.unsourced) {
    return (
      <div className="mt-6 inline-flex items-center gap-1.5 rounded-md bg-amber-50 px-2.5 py-1 text-[11px] font-medium text-amber-700">
        No supporting source was found for this section — treat it as unverified.
      </div>
    );
  }
  const refs = (section.sources || []).filter((r) => sources[r]);
  if (refs.length === 0) return null;
  return (
    <div className="mt-6 border-t border-slate-100 pt-3">
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Sources</div>
      <div className="flex flex-wrap gap-1.5">
        {refs.map((r) => {
          const src = sources[r];
          return (
            <a key={r} href={src.url} target="_blank" rel="noopener noreferrer"
              title={`${src.headline}${src.date ? ` (${src.date})` : ""}`}
              className="inline-flex max-w-[16rem] items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600 hover:border-[#5B2C9D]/40 hover:text-[#5B2C9D]">
              <CitationIcon url={src.url} label={src.publisher} />
              <span className="truncate">{src.publisher || src.headline}</span>
            </a>
          );
        })}
      </div>
    </div>
  );
}

function CitationIcon({ url, label }: { url: string; label: string }) {
  const [failed, setFailed] = useState(false);
  let domain = "";
  try { domain = new URL(url).hostname; } catch { /* fall back to initial */ }
  return domain && !failed ? (
    <img src={`https://www.google.com/s2/favicons?domain=${domain}&sz=32`} alt="" onError={() => setFailed(true)}
      className="w-3.5 h-3.5 rounded-full ring-1 ring-slate-200 bg-white" />
  ) : <SourceInitial label={label || domain} />;
}

function renderContent(content: string, sources: SourceLookup = {}, sectionKey = "") {
  if (!content) return null;
  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      elements.push(<div key={i} className="h-4" />);
      continue;
    }

    if (trimmed.startsWith("**") && trimmed.endsWith("**")) {
      elements.push(
        <div key={i} className="font-semibold text-[#5B2C9D] mt-3 mb-1">
          {trimmed.replace(/\*\*/g, "")}
        </div>
      );
      continue;
    }

    if (trimmed.match(/^\*\*[^*]+:\*\*/)) {
      const match = trimmed.match(/^\*\*([^*]+):\*\*\s*(.*)/);
      if (match) {
        elements.push(
          <div key={i} className="mt-1">
            <span className="font-semibold text-slate-800">{match[1]}:</span>{" "}
            <span>{renderInlineBold(match[2], sources)}</span>
          </div>
        );
        continue;
      }
    }

    if (trimmed.startsWith("- [") && trimmed.includes("](")) {
      const match = trimmed.match(/^- \[([^\]]+)\]\(([^)]+)\)$/);
      if (match) {
        elements.push(
          <div key={i} className="flex items-start gap-2 ml-3 my-0.5">
            <span className="w-1.5 h-1.5 rounded-full bg-[#5B2C9D] mt-2 shrink-0" />
            <a href={match[2]} target="_blank" rel="noopener noreferrer" className="text-[#5B2C9D] hover:underline">{match[1]}</a>
          </div>
        );
        continue;
      }
    }

    if (trimmed.startsWith("- ")) {
      elements.push(
        <div key={i} className="flex items-start gap-2.5 ml-3 my-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-slate-400 mt-[9px] shrink-0" />
          <span>{renderInlineBold(trimmed.slice(2), sources)}</span>
        </div>
      );
      continue;
    }

    if (trimmed.startsWith("Source: ")) {
      elements.push(
        <div key={i} className="text-xs text-slate-400 italic ml-3">{trimmed}</div>
      );
      continue;
    }

    if (trimmed.startsWith("## ")) {
      const headingText = trimmed.slice(3);
      // Competitor Developments headings are bare competitor/brand names (no
      // "|" separator, unlike the dated headings used elsewhere) — show a logo.
      const isCompetitorHeading = sectionKey === "competitor_developments" && !headingText.includes("|");
      elements.push(
        <div key={i} className="flex items-center gap-2 font-bold text-[15px] text-[#5B2C9D] mt-7 mb-3 pb-1.5 border-b border-[#5B2C9D]/15">
          {isCompetitorHeading && <BrandLogo brandName={headingText} size={20} />}
          {headingText}
        </div>
      );
      continue;
    }

    if (trimmed.startsWith("### ")) {
      elements.push(
        <div key={i} className="font-semibold text-sm text-[#5B2C9D] mt-6 mb-2 border-b border-slate-100 pb-1.5">
          {trimmed.slice(4)}
        </div>
      );
      continue;
    }

    if (trimmed.startsWith("Strategic tags:")) {
      elements.push(
        <div key={i} className="text-xs text-purple-500 italic mt-0.5 mb-2">{trimmed}</div>
      );
      continue;
    }

    if (trimmed.match(/^\[S\d+\]/)) {
      const match = trimmed.match(/^\[(S\d+)\]\s*\|?\s*(.*)/);
      if (match) {
        elements.push(
          <div key={i} className="text-xs text-slate-600 my-0.5 flex items-start gap-1.5">
            <CitationLink refId={match[1]} sources={sources} />
            <span>{match[2]}</span>
          </div>
        );
        continue;
      }
    }

    elements.push(<div key={i} className="my-1">{renderInlineBold(trimmed, sources)}</div>);
  }

  return <>{elements}</>;
}

/** One competitor's row: a 30%-width logo column (brand mark only — no stock background,
 * which previously buried the logo under irrelevant Pexels imagery) beside a 70%-width
 * column split into two clearly bordered sub-rows — Introduction (the intro paragraph
 * before the first dated entry) and Development Summary (the "### Date | Headline"
 * entries). */
/** True once a rendered YouTube embed reports a playback error (video removed/privated/
 * region-locked after being cached, embedding disabled, etc.) — distinct from "no video
 * found at lookup time", which the Pexels-fallback effects above already handle. YouTube's
 * embedded player posts these as window `message` events once the embed URL carries
 * `enablejsapi=1`; no need to load the full iframe_api script just to observe them. Callers
 * treat a failure exactly like "no video", falling through to their Pexels tier. */
function useYouTubeEmbedFailure(embedUrl: string | null): boolean {
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setFailed(false);
    if (!embedUrl) return;
    const handler = (event: MessageEvent) => {
      if (typeof event.data !== "string") return;
      let data: unknown;
      try { data = JSON.parse(event.data); } catch { return; }
      if (data && typeof data === "object" && (data as Record<string, unknown>).event === "onError") {
        setFailed(true);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [embedUrl]);
  return failed;
}

function withJsApi(embedUrl: string): string {
  return embedUrl.includes("enablejsapi=1") ? embedUrl : `${embedUrl}&enablejsapi=1`;
}

function CompetitorRow({
  name, introLines, devLines, sources,
}: {
  name: string;
  introLines: string[];
  devLines: string[];
  sources: SourceLookup;
}) {
  const hasIntro = introLines.some((l) => l.trim());
  const hasDev = devLines.some((l) => l.trim());

  // Same official-channel-verified lookup as the section header banners (video_search.py) —
  // "<name> official" ranked against YouTube oEmbed's author_name, so this never shows an
  // unaffiliated fan/reaction channel's video, only the competitor's own channel. When no
  // verified channel video exists (common — not every competitor ranks well there), falls
  // back to a generic Pexels brand video/image instead of leaving the card empty.
  const [videoEmbedUrl, setVideoEmbedUrl] = useState<string | null>(null);
  const [pexelsImage, setPexelsImage] = useState<string | null>(null);
  const [pexelsVideo, setPexelsVideo] = useState<string | null>(null);
  useEffect(() => {
    setVideoEmbedUrl(null);
    setPexelsImage(null);
    setPexelsVideo(null);
    if (!name.trim()) return;
    let cancelled = false;
    intelApi.getSectionVideo(name, name).then((res) => {
      if (cancelled) return;
      if (res.embed_url) {
        setVideoEmbedUrl(res.embed_url);
        return;
      }
      // "company" disambiguates a competitor name that's also a common word (e.g. "Apple",
      // "Target", "Dove") away from Pexels' literal stock photos for that word — see
      // BriefScopeReview.tsx's identical fix for the project-level banner.
      intelApi.getPexelsImage(`${name} company`).then((pres) => {
        if (!cancelled) { setPexelsImage(pres.image_url); setPexelsVideo(pres.video_url); }
      }).catch(() => {});
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [name]);

  const videoFailed = useYouTubeEmbedFailure(videoEmbedUrl);
  useEffect(() => {
    if (!videoFailed || pexelsImage || pexelsVideo) return;
    let cancelled = false;
    intelApi.getPexelsImage(`${name} company`).then((pres) => {
      if (!cancelled) { setPexelsImage(pres.image_url); setPexelsVideo(pres.video_url); }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [videoFailed, name, pexelsImage, pexelsVideo]);

  return (
    <div className="flex gap-8 py-8 first:pt-0 animate-fade-in">
      <div className="w-[30%] shrink-0 self-start flex flex-col gap-3">
        <div className="rounded-xl border border-slate-200 bg-slate-50 flex flex-col items-center justify-center gap-3 py-8 px-4" style={{ minHeight: 220 }}>
          <BrandLogo brandName={name} size={100} rounded="lg" />
          <div className="font-bold text-sm text-slate-700 text-center">{name}</div>
        </div>
        {videoEmbedUrl && !videoFailed ? (
          <div className="rounded-xl overflow-hidden border border-slate-200 bg-slate-900 aspect-video">
            <iframe
              src={withJsApi(videoEmbedUrl)}
              className="w-full h-full pointer-events-none"
              allow="autoplay; encrypted-media"
              title={`${name} video`}
            />
          </div>
        ) : pexelsVideo ? (
          <div className="rounded-xl overflow-hidden border border-slate-200 bg-slate-900 aspect-video">
            <video src={pexelsVideo} poster={pexelsImage || undefined} autoPlay muted loop playsInline
                   className="w-full h-full object-cover" aria-hidden="true" />
          </div>
        ) : pexelsImage ? (
          <div className="rounded-xl overflow-hidden border border-slate-200 bg-slate-900 aspect-video">
            <img src={pexelsImage} alt="" className="w-full h-full object-cover" />
          </div>
        ) : null}
      </div>
      <div className="w-[70%] min-w-0 flex flex-col gap-4">
        {hasIntro && (
          <div className="rounded-lg border border-slate-200 p-4">
            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Introduction</div>
            {renderContent(introLines.join("\n"), sources, "competitor_developments_body")}
          </div>
        )}
        {hasDev && (
          <div className="rounded-lg border border-slate-200 p-4">
            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Development Summary</div>
            {renderContent(devLines.join("\n"), sources, "competitor_developments_body")}
          </div>
        )}
      </div>
    </div>
  );
}

/** The Competitors tab gets a distinct layout: one row per competitor, a 30%-width logo
 * column beside a 70%-width data column, instead of the generic markdown flow every other
 * section uses. Splits on bare "## CompetitorName" headings (no "|", unlike dated headings
 * used elsewhere) — the same convention renderContent's inline-logo special case already
 * relied on — so each competitor's intro + developments render inside its own row. */
/** Per-section query used to find a topically-matched YouTube background video — deliberately
 * distinct per section (not one video reused everywhere) so Introduction gets a company
 * overview while Brand Developments gets something about recent news, etc. Competitors
 * already has its own per-competitor Pexels imagery (see CompetitorRow) so it's excluded here
 * to avoid stacking two different video/image backgrounds; Methodology and Source Register
 * are administrative sections with no natural video angle. */
/** Joins only the non-empty parts with single spaces — category is sometimes empty, and
 * naively interpolating it into a template string left a literal double space in the query
 * ("Tesla  industry overview"), which also read as a slightly worse search. */
function buildVideoQuery(...parts: (string | undefined)[]): string {
  return parts.filter((p) => p && p.trim()).join(" ");
}

const SECTION_VIDEO_QUERIES: Record<string, (brand: string, category: string) => string> = {
  company_introduction: (brand) => buildVideoQuery(brand, "company overview"),
  executive_summary: (brand, category) => buildVideoQuery(brand, category, "industry overview"),
  brand_developments: (brand) => buildVideoQuery(brand, "latest news"),
  brand_narrative: (brand) => buildVideoQuery(brand, "brand story"),
  industry_context: (_brand, category) => buildVideoQuery(category, "industry trends"),
  key_issues: (_brand, category) => buildVideoQuery(category, "industry challenges"),
};

/** Sections whose video should prefer a specific product over the generic per-section topic
 * when one is actually named in that section's own text — "company overview" is a fine
 * search for Introduction in general, but if the brief's Introduction or Brand Developments
 * copy calls out "$5 Meal Deal" by name, that's a much more specific, relevant video to show
 * than a generic corporate-overview search would surface. */
const PRODUCT_AWARE_SECTIONS = new Set(["company_introduction", "brand_developments"]);

/** First known product/product_group entity name (from the project spec's validated_entities)
 * that actually appears in `sectionContent` — case-insensitive substring match, longest name
 * first so e.g. "MyMcDonald's Rewards" wins over a shorter name it happens to contain. Null
 * when no product is mentioned in this section's own text, or none were extracted at all. */
function findMentionedProduct(sectionContent: string, productNames: string[]): string | null {
  if (!sectionContent || productNames.length === 0) return null;
  const haystack = sectionContent.toLowerCase();
  const sorted = [...productNames].sort((a, b) => b.length - a.length);
  for (const name of sorted) {
    if (name.trim() && haystack.includes(name.toLowerCase())) return name;
  }
  return null;
}

/** A bounded hero banner (not a full-page background) above the section header — the
 * earlier full-pane video-behind-scrolling-text design made body text illegible regardless
 * of overlay strength once a busy/bright video was behind it. Keeping the video confined to
 * its own strip, with the brand logo overlaid on it, means the actual reading content below
 * always sits on plain white — zero readability trade-off. Three-tier fallback so the
 * section never collapses to an empty gap: official-channel video, then Pexels stock
 * video/image for the same query, then the brand's own logo on a plain banner — and a
 * playback-time failure (video removed/privated after being cached) degrades the same way
 * via `useYouTubeEmbedFailure`, not just a lookup-time miss. */
function SectionVideoBanner({ activeTab, brandName, category, sectionContent, productNames }: {
  activeTab: string; brandName: string; category: string; sectionContent: string; productNames: string[];
}) {
  const [embedUrl, setEmbedUrl] = useState<string | null>(null);
  const [pexelsImage, setPexelsImage] = useState<string | null>(null);
  const [pexelsVideo, setPexelsVideo] = useState<string | null>(null);
  const lastQueryRef = useRef<string>("");

  useEffect(() => {
    const queryFn = SECTION_VIDEO_QUERIES[activeTab];
    setEmbedUrl(null);
    setPexelsImage(null);
    setPexelsVideo(null);
    if (!queryFn || !brandName.trim()) return;
    let cancelled = false;

    // Prefer a specific product named in this section's own text (e.g. "$5 Meal Deal")
    // over the generic per-section topic — see findMentionedProduct's doc comment.
    const product = PRODUCT_AWARE_SECTIONS.has(activeTab) ? findMentionedProduct(sectionContent, productNames) : null;
    const query = product ? buildVideoQuery(brandName, product) : queryFn(brandName, category);
    lastQueryRef.current = query;

    intelApi.getSectionVideo(query, brandName).then((res) => {
      if (cancelled) return;
      if (res.embed_url) { setEmbedUrl(res.embed_url); return; }
      // No official-channel video for this query at all (including its own fallbacks) —
      // degrade to generic Pexels stock footage/imagery rather than showing nothing, same
      // three-tier pattern CompetitorRow already uses below.
      intelApi.getPexelsImage(query).then((pres) => {
        if (!cancelled) { setPexelsImage(pres.image_url); setPexelsVideo(pres.video_url); }
      }).catch(() => {});
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [activeTab, brandName, category, sectionContent, productNames]);

  const videoFailed = useYouTubeEmbedFailure(embedUrl);
  useEffect(() => {
    if (!videoFailed || pexelsImage || pexelsVideo || !lastQueryRef.current) return;
    let cancelled = false;
    intelApi.getPexelsImage(lastQueryRef.current).then((pres) => {
      if (!cancelled) { setPexelsImage(pres.image_url); setPexelsVideo(pres.video_url); }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [videoFailed, pexelsImage, pexelsVideo]);

  const hasMedia = (embedUrl && !videoFailed) || pexelsVideo || pexelsImage;

  return (
    <div className="relative h-48 shrink-0 overflow-hidden bg-slate-900 border-b border-slate-200">
      {embedUrl && !videoFailed ? (
        <iframe
          src={withJsApi(embedUrl)}
          className="absolute inset-0 w-full h-full pointer-events-none"
          allow="autoplay; encrypted-media"
          title="Section background video"
        />
      ) : pexelsVideo ? (
        <video src={pexelsVideo} poster={pexelsImage || undefined} autoPlay muted loop playsInline
          className="absolute inset-0 w-full h-full object-cover" />
      ) : pexelsImage ? (
        <img src={pexelsImage} alt="" className="absolute inset-0 w-full h-full object-cover" />
      ) : (
        // Final tier — no official video and no Pexels result either: the brand's own
        // logo on a plain dark banner, so a section never collapses to an empty gap.
        <div className="absolute inset-0 flex items-center justify-center">
          <BrandLogo brandName={brandName} size={56} rounded="lg" className="opacity-90" />
        </div>
      )}
      {hasMedia && <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />}
      {brandName && hasMedia && (
        <div className="absolute bottom-3 left-4 flex items-center gap-2">
          <BrandLogo brandName={brandName} size={28} rounded="lg" className="shadow-lg" />
          <span className="text-white text-xs font-semibold" style={{ textShadow: "0 1px 3px rgba(0,0,0,0.6)" }}>
            {brandName}
          </span>
        </div>
      )}
    </div>
  );
}

function renderCompetitorSection(content: string, sources: SourceLookup): React.ReactNode {
  if (!content) return null;
  const lines = content.split("\n");
  const blocks: { name: string; bodyLines: string[] }[] = [];

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith("## ") && !trimmed.slice(3).includes("|")) {
      blocks.push({ name: trimmed.slice(3).trim(), bodyLines: [] });
      continue;
    }
    if (blocks.length > 0) {
      blocks[blocks.length - 1].bodyLines.push(line);
    }
  }

  if (blocks.length === 0) {
    return <div className="max-w-3xl">{renderContent(content, sources, "competitor_developments")}</div>;
  }

  return (
    <div className="divide-y divide-slate-100">
      {blocks.map((block, i) => {
        const firstDevIdx = block.bodyLines.findIndex((l) => l.trim().startsWith("### "));
        const introLines = firstDevIdx === -1 ? block.bodyLines : block.bodyLines.slice(0, firstDevIdx);
        const devLines = firstDevIdx === -1 ? [] : block.bodyLines.slice(firstDevIdx);
        return (
          <CompetitorRow
            key={i}
            name={block.name}
            introLines={introLines}
            devLines={devLines}
            sources={sources}
          />
        );
      })}
    </div>
  );
}

function renderInlineBold(text: string, sources: SourceLookup = {}): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|\[S\d+\])/);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <span key={i} className="font-semibold">{part.slice(2, -2)}</span>;
    }
    const citMatch = part.match(/^\[(S\d+)\]$/);
    if (citMatch) {
      return <CitationLink key={i} refId={citMatch[1]} sources={sources} />;
    }
    return <span key={i}>{part}</span>;
  });
}

interface Props {
  onNavigate: (page: string) => void;
}

export function BackgroundResearch({ onNavigate }: Props) {
  const { activeProject, setActiveProject } = useProject();
  const projectId = activeProject?.id ?? null;
  const demo = useDemoState();

  const [pageState, setPageState] = useState<PageState>("idle");
  const [progress, setProgress] = useState({ pct: 0, message: "" });
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [briefResult, setBriefResult] = useState<BriefResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);
  const [editingSection, setEditingSection] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [downloading, setDownloading] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [diagnosticsPos, setDiagnosticsPos] = useState({ bottom: 0, left: 0, maxHeight: 400 });
  const diagnosticsButtonRef = useRef<HTMLButtonElement>(null);
  const [activeTab, setActiveTab] = useState<string>("");
  const [researchJobId, setResearchJobId] = useState<string | null>(null);
  const [searchDegraded, setSearchDegraded] = useState(false);
  const [progressLog, setProgressLog] = useState<ProgressLogEntry[]>([]);
  const [showProgressLog, setShowProgressLog] = useState(false);
  const [scopeGeography, setScopeGeography] = useState("");
  const [scopeTimePeriod, setScopeTimePeriod] = useState("");
  const [productNames, setProductNames] = useState<string[]>([]);
  const [revisionPanelOpen, setRevisionPanelOpen] = useState(false);
  const [leftPanelOpen, setLeftPanelOpen] = useState(true);
  const [revisionNotes, setRevisionNotes] = useState("");
  const [submittingRevision, setSubmittingRevision] = useState(false);

  const contentRef = useRef<HTMLDivElement>(null);

  const fetchResearchStatus = useMemo(
    () => (researchJobId ? () => intelApi.getResearchStatus(researchJobId) : null),
    [researchJobId]
  );
  const { status: researchStatus, error: researchPollError } = useJobStatus<JobStatus>(fetchResearchStatus);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    intelApi.getProject(projectId).then((project) => {
      if (cancelled) return;
      const spec = project.spec as Record<string, unknown> | undefined;
      if (spec && typeof spec.geography === "string") setScopeGeography(spec.geography);
      if (spec && typeof spec.time_period === "string") setScopeTimePeriod(spec.time_period);
      const entities = spec && Array.isArray(spec.validated_entities) ? spec.validated_entities as Array<Record<string, unknown>> : [];
      setProductNames(
        entities
          .filter((e) => e.type === "product" || e.type === "product_group")
          .map((e) => (typeof e.name === "string" ? e.name : ""))
          .filter(Boolean)
      );
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [projectId]);

  const handleResearchProgress = useCallback((msg: WsMessage) => {
    if (msg.type !== "intel_job_update" || !researchJobId || msg.job_id !== researchJobId) return;
    const message = typeof msg.message === "string" ? msg.message : "";
    const pct = typeof msg.progress_pct === "number" ? msg.progress_pct : 0;
    if (message) {
      setProgressLog((prev) => [...prev, { message, pct, at: Date.now() }].slice(-50));
    }
  }, [researchJobId]);

  useAgentSocket(handleResearchProgress);

  const proceedToComposing = useCallback(async () => {
    if (!projectId) return;
    setPageState("composing");
    setProgress({ pct: 92, message: "Synthesizing analytical brief with AI — this may take up to 2 minutes..." });
    try {
      try {
        const research = await intelApi.getResearch(projectId);
        setSearchDegraded(Boolean(research?.research?.search_degraded));
      } catch {
        // Non-critical — the banner just won't show if this lookup fails.
      }
      const briefResponse = await intelApi.generateBrief(projectId);
      setBriefResult({
        brief_id: briefResponse.brief_id,
        version: 1,
        approval_status: "pending",
        brief: briefResponse.brief,
        docx_path: null,
        docx_generated_at: null,
        research_approved: false,
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
      });
      setPageState("ready");
      if (briefResponse.brief?.section_order?.length) {
        setActiveTab(briefResponse.brief.section_order[0]);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Generation failed";
      setError(msg);
      setPageState("failed");
    }
  }, [projectId]);

  useEffect(() => {
    if (!researchStatus) return;
    setProgress({ pct: Math.min(researchStatus.progress_pct, 90), message: researchStatus.progress_message });
    if (researchStatus.status === "completed") {
      setResearchJobId(null);
      void proceedToComposing();
    } else if (researchStatus.status === "failed") {
      setResearchJobId(null);
      setError(researchStatus.error || "Research failed");
      setPageState("failed");
    }
  }, [researchStatus, proceedToComposing]);

  useEffect(() => {
    if (researchPollError) {
      setResearchJobId(null);
      setError("Lost connection to server");
      setPageState("failed");
    }
  }, [researchPollError]);

  useEffect(() => {
    if (projectId && pageState === "idle" && !briefResult) {
      intelApi.getBrief(projectId)
        .then((r) => {
          setBriefResult(r);
          setApproved(r.approval_status === "approved");
          setPageState("ready");
          if (r.brief?.section_order?.length) {
            setActiveTab(r.brief.section_order[0]);
          }
        })
        .catch(() => {});
    }
  }, [projectId, pageState, briefResult]);

  /** Fetches the project's spec and starts a brand-new web research job — always a fresh
   * fetch, no hasResearch check. Shared by first-time generation and Request Revision,
   * which must restart research, not just re-synthesize the same already-fetched items. */
  const triggerFreshResearch = async (): Promise<boolean> => {
    if (!projectId) {
      setError("No active project. Please create a project first.");
      return false;
    }
    let spec: Record<string, unknown> | null = null;
    try {
      const project = await intelApi.getProject(projectId);
      if (project.spec) spec = project.spec;
    } catch {}
    if (!spec) {
      setError("No project specification found. Complete Brief & Scope first.");
      setPageState("failed");
      return false;
    }

    const result = await intelApi.startResearch(spec, projectId);
    setActiveProject({ id: result.project_id, name: activeProject?.name ?? "Research Project", project_type: activeProject?.project_type ?? "research", brand: activeProject?.brand });

    // Hand off to useJobStatus: the effect watching `researchStatus` /
    // `researchPollError` drives the rest of the flow (progress updates,
    // then proceedToComposing()) once the research job reaches a
    // terminal state.
    setResearchJobId(result.job_id);
    return true;
  };

  const startGeneration = async () => {
    if (!projectId) {
      setError("No active project. Please create a project first.");
      return;
    }

    setError(null);
    setPageState("researching");
    setProgress({ pct: 0, message: "Starting web research..." });
    setStartedAt(Date.now());
    setProgressLog([]);
    setShowProgressLog(false);

    try {
      let hasResearch = false;
      try {
        const existing = await intelApi.getResearch(projectId);
        if (existing && existing.research?.web_search_executed) {
          hasResearch = true;
        }
      } catch {}

      if (!hasResearch) {
        await triggerFreshResearch();
        return;
      }

      await proceedToComposing();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Generation failed";
      setError(msg);
      setPageState("failed");
    }
  };

  const handleApprove = async () => {
    if (!briefResult) return;
    try {
      await intelApi.approveBrief(briefResult.brief_id);
      setApproved(true);
      demo.setBackgroundApproved(true);
      setTimeout(() => onNavigate("search-strategy"), 800);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    }
  };

  const handleSubmitRevision = async () => {
    if (!briefResult) return;     // notes are optional guidance
    setSubmittingRevision(true);
    try {
      await intelApi.rejectBrief(briefResult.brief_id, revisionNotes.trim());
      setRevisionPanelOpen(false);
      setRevisionNotes("");
      setBriefResult(null);
      setApproved(false);
      setError(null);
      setPageState("researching");
      setProgress({ pct: 0, message: "Restarting web research with your revision notes..." });
      setStartedAt(Date.now());
      setProgressLog([]);
      setShowProgressLog(false);
      await triggerFreshResearch();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Revision request failed");
      setPageState("ready");
    } finally {
      setSubmittingRevision(false);
    }
  };

  const handleEditSection = (key: string) => {
    if (!briefResult) return;
    const section = briefResult.brief.sections[key];
    if (!section) return;
    setEditingSection(key);
    setEditContent(section.content);
  };

  const handleSaveSection = async () => {
    if (!briefResult || !editingSection) return;
    try {
      await intelApi.updateBriefSection(briefResult.brief_id, editingSection, editContent);
      setBriefResult((prev) => {
        if (!prev) return prev;
        const updated = { ...prev };
        updated.brief = { ...updated.brief };
        updated.brief.sections = { ...updated.brief.sections };
        updated.brief.sections[editingSection] = {
          ...updated.brief.sections[editingSection],
          content: editContent,
          edited: true,
        };
        return updated;
      });
      setEditingSection(null);
      setEditContent("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    }
  };

  const handleDownload = async () => {
    if (!briefResult) return;
    setDownloading(true);
    try {
      setRendering(true);
      await intelApi.renderBriefDocx(briefResult.brief_id);
      setRendering(false);

      const blob = await intelApi.downloadBriefDocx(briefResult.brief_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Analyst_Brief_${briefResult.brief.research_subject.replace(/\s+/g, "_")}.docx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed");
    } finally {
      setDownloading(false);
      setRendering(false);
    }
  };

  const handleTabChange = (key: string) => {
    setActiveTab(key);
    setEditingSection(null);
    setEditContent("");
    if (contentRef.current) {
      contentRef.current.scrollTop = 0;
    }
  };

  const brief = briefResult?.brief;
  const currentSection = brief?.sections?.[activeTab];
  const sectionOrder = brief?.section_order ?? [];

  const sourceLookup: SourceLookup = {};
  if (brief?.source_register) {
    for (const src of brief.source_register) {
      sourceLookup[src.ref] = src;
    }
  }

  return (
    <div className="h-full flex flex-col animate-fade-in">
      {/* Compact Header */}
      <div className="shrink-0 px-6 py-4 border-b border-slate-200 bg-white">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div>
              <h1 className="text-lg font-semibold text-slate-900">Competitive News Brief</h1>
              <p className="text-xs text-slate-500 mt-0.5">
                {activeProject?.name ?? "Research Project"}
              </p>
            </div>
            {brief && brief.enrichment_status && (
              <span className={`text-[10px] font-medium px-2.5 py-1 rounded-full border ${
                brief.enrichment_status === "llm_synthesized" || brief.enrichment_status === "enriched"
                  ? "text-emerald-700 bg-emerald-50 border-emerald-200"
                  : "text-amber-700 bg-amber-50 border-amber-200"
              }`}>
                {brief.enrichment_status === "llm_synthesized" ? "LLM Synthesized" : brief.enrichment_status === "enriched" ? "LLM Enriched" : "Web Research Only"}
              </span>
            )}
            {approved && (
              <span className="text-[10px] font-medium text-emerald-700 bg-emerald-50 border border-emerald-100 px-2.5 py-1 rounded-full">
                Approved
              </span>
            )}
          </div>
          {pageState === "ready" && brief && (
            <div className="flex items-center gap-2">
              {/* Compact stats */}
              <div className="flex items-center gap-3 mr-3">
                <div className="text-center">
                  <div className="text-sm font-bold text-[#5B2C9D] tabular-nums">{brief.source_count}</div>
                  <div className="text-[9px] text-slate-400">Sources</div>
                </div>
                <div className="w-px h-6 bg-slate-200" />
                <div className="text-center" title={
                  `Tier 1 (${brief.metadata.tier_1_count}) — ${SOURCE_TIER_LABELS.tier_1}\n` +
                  `Tier 2 (${brief.metadata.tier_2_count}) — ${SOURCE_TIER_LABELS.tier_2}\n` +
                  `Tier 3 (${brief.metadata.tier_3_count}) — ${SOURCE_TIER_LABELS.tier_3}`
                }>
                  <div className="text-sm font-bold tabular-nums">
                    <span className="text-emerald-600">{brief.metadata.tier_1_count}</span>
                    <span className="text-slate-300 mx-px">/</span>
                    <span className="text-sky-600">{brief.metadata.tier_2_count}</span>
                    <span className="text-slate-300 mx-px">/</span>
                    <span className="text-slate-500">{brief.metadata.tier_3_count}</span>
                  </div>
                  <div className="text-[9px] text-slate-400">T1 / T2 / T3</div>
                </div>
                <div className="w-px h-6 bg-slate-200" />
                <div className="text-center">
                  <div className="text-sm font-bold text-slate-700 tabular-nums">{sectionOrder.length}</div>
                  <div className="text-[9px] text-slate-400">Sections</div>
                </div>
                {brief.research_gaps.length > 0 && (
                  <>
                    <div className="w-px h-6 bg-slate-200" />
                    <div className="text-center">
                      <div className="text-sm font-bold text-amber-600 tabular-nums">{brief.research_gaps.length}</div>
                      <div className="text-[9px] text-slate-400">Gaps</div>
                    </div>
                  </>
                )}
              </div>
              <button
                onClick={handleDownload}
                disabled={downloading}
                className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium text-white rounded-lg shadow-sm transition-all hover:shadow-md disabled:opacity-50"
                style={{ background: "linear-gradient(135deg, #5B2C9D, #7C4DFF)" }}
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                {rendering ? "Rendering..." : downloading ? "Downloading..." : "Download .docx"}
              </button>
              <button
                onClick={startGeneration}
                className="px-3 py-2 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
              >
                Regenerate
              </button>
            </div>
          )}
        </div>
      </div>

      {searchDegraded && (
        <div className="shrink-0 px-6 py-2.5 bg-amber-50 border-b border-amber-200 flex items-center gap-2.5">
          <svg className="w-4 h-4 text-amber-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span className="text-xs text-amber-800">
            Primary search sources unavailable — showing results from Google News RSS only, coverage may be reduced.
          </span>
          <button
            onClick={() => setSearchDegraded(false)}
            className="ml-auto text-amber-500 hover:text-amber-700"
            aria-label="Dismiss"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M6 18L18 6" />
            </svg>
          </button>
        </div>
      )}

      {/* Idle State */}
      {pageState === "idle" && !briefResult && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="bg-white border-2 border-dashed border-[#5B2C9D]/20 rounded-xl p-10 text-center space-y-5 max-w-lg">
            <div className="text-[#5B2C9D]/40">
              <svg className="w-14 h-14 mx-auto" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-800 mb-1.5">Generate Competitive News Brief</h3>
              <p className="text-sm text-slate-500 leading-relaxed">
                Run live web research, validate sources, then compose a competitive news brief with company overview,
                brand developments, competitor activity, industry context, and source register.
              </p>
            </div>
            <button
              onClick={startGeneration}
              className="px-6 py-3 text-sm font-medium text-white rounded-lg shadow-sm transition-all hover:shadow-md"
              style={{ background: "linear-gradient(135deg, #5B2C9D, #7C4DFF)" }}
            >
              Generate Brief
            </button>
            <p className="text-[11px] text-slate-400">
              The primary output is a downloadable Microsoft Word document.
            </p>
          </div>
        </div>
      )}

      {/* Running State */}
      {(pageState === "researching" || pageState === "composing") && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="w-full max-w-lg space-y-5">
            {/* Stage steps */}
            <div className="flex items-center justify-center gap-3">
              {[
                { key: "researching", label: "Web Research" },
                { key: "composing", label: "AI Synthesis" },
                { key: "ready", label: "Complete" },
              ].map((stage, i) => {
                const done = stage.key === "researching" ? pageState === "composing" :
                             stage.key === "composing" ? false :
                             false;
                const active = stage.key === pageState;
                return (
                  <div key={stage.key} className="flex items-center gap-3">
                    {i > 0 && (
                      <div className={`w-8 h-px ${done ? "bg-[#5B2C9D]" : "bg-slate-200"}`} />
                    )}
                    <div className="flex items-center gap-2">
                      <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold transition-all ${
                        done ? "bg-[#5B2C9D] text-white" :
                        active ? "border-2 border-[#5B2C9D] text-[#5B2C9D]" :
                        "border-2 border-slate-200 text-slate-300"
                      }`}>
                        {done ? (
                          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        ) : (
                          i + 1
                        )}
                      </div>
                      <span className={`text-xs font-medium ${active ? "text-[#5B2C9D]" : done ? "text-slate-700" : "text-slate-400"}`}>
                        {stage.label}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>

            <ProgressBar
              pct={progress.pct}
              message={progress.message}
              startedAt={startedAt}
              geography={scopeGeography}
              timePeriod={scopeTimePeriod}
              log={progressLog}
              showLog={showProgressLog}
              onToggleLog={() => setShowProgressLog((v) => !v)}
            />

            <p className="text-center text-xs text-slate-400">
              {pageState === "composing"
                ? "The AI model is generating each section — this typically takes 1–2 minutes on CPU."
                : "Searching the web for recent news, articles, and competitive intelligence."}
            </p>
          </div>
        </div>
      )}

      {/* Error State */}
      {pageState === "failed" && error && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="bg-white border border-red-200 rounded-xl p-6 shadow-sm max-w-lg w-full">
            <div className="flex items-start gap-3">
              <svg className="w-5 h-5 text-red-500 mt-0.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
              </svg>
              <div className="flex-1">
                <h3 className="text-sm font-semibold text-red-700">Generation Failed</h3>
                <p className="text-xs text-red-600 mt-1">{error}</p>
                {error.includes("LIVE_WEB_RESEARCH_UNAVAILABLE") && (
                  <p className="text-xs text-red-500 mt-2 font-medium">
                    Live web research could not execute. Approval is blocked until web search succeeds.
                  </p>
                )}
              </div>
              <button
                onClick={() => { setPageState("idle"); setError(null); }}
                className="px-3 py-1.5 text-xs font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100 transition-colors"
              >
                Retry
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tabbed Content Layout */}
      {pageState === "ready" && brief && (
        <div className="flex-1 flex min-h-0">
          {/* Section Tabs — Left Rail (slide-out drawer) */}
          <div className={`shrink-0 border-r border-slate-200 bg-white overflow-hidden transition-[width] duration-200 ${leftPanelOpen ? "w-56" : "w-0 border-r-0"}`}>
            <div className="w-56 h-full overflow-y-auto">
            <div className="py-2">
              {sectionOrder.map((key) => {
                const section = brief.sections[key];
                if (!section) return null;
                const isActive = activeTab === key;
                const iconPath = SECTION_ICONS[key] || "M4 6h16M4 12h16M4 18h16";
                const label = SECTION_SHORT_LABELS[key] || section.title;
                const hasContent = section.content && section.content.trim().length > 0;
                return (
                  <button
                    key={key}
                    onClick={() => handleTabChange(key)}
                    className={`w-full flex items-center gap-2.5 px-4 py-2.5 text-left text-xs font-medium transition-all ${
                      isActive
                        ? "bg-[#5B2C9D]/8 text-[#5B2C9D] border-r-2 border-[#5B2C9D]"
                        : "text-slate-600 hover:bg-slate-50 hover:text-slate-800"
                    }`}
                  >
                    <svg className={`w-4 h-4 shrink-0 ${isActive ? "text-[#5B2C9D]" : "text-slate-400"}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d={iconPath} strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    <span className="truncate">{label}</span>
                    {section.edited && (
                      <span className="ml-auto w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                    )}
                    {!hasContent && (
                      <span className="ml-auto w-1.5 h-1.5 rounded-full bg-slate-300 shrink-0" />
                    )}
                  </button>
                );
              })}
              <button
                onClick={() => handleTabChange("all_articles")}
                className={`w-full flex items-center gap-2.5 px-4 py-2.5 text-left text-xs font-medium transition-all ${
                  activeTab === "all_articles"
                    ? "bg-[#5B2C9D]/8 text-[#5B2C9D] border-r-2 border-[#5B2C9D]"
                    : "text-slate-600 hover:bg-slate-50 hover:text-slate-800"
                }`}
              >
                <svg
                  className={`w-4 h-4 shrink-0 ${activeTab === "all_articles" ? "text-[#5B2C9D]" : "text-slate-400"}`}
                  viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
                >
                  <path d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span className="truncate">All Articles</span>
              </button>
            </div>

            {/* Research Gaps */}
            {brief.research_gaps.length > 0 && (
              <div className="border-t border-slate-200 px-4 py-3">
                <div className="text-[10px] font-semibold text-amber-700 uppercase tracking-wide mb-2">Research Gaps</div>
                <div className="space-y-1">
                  {brief.research_gaps.map((g, i) => (
                    <div key={i} className="text-[10px] text-amber-600 leading-tight flex items-start gap-1">
                      <svg className="w-3 h-3 mt-0.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                        <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
                      </svg>
                      <span>{g.replace("No results found for search family: ", "")}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Diagnostics — icon trigger opens a floating popup (matches ProjectCard's
                kebab-menu pattern: createPortal to document.body, positioned from the
                trigger's rect) instead of expanding inline, since this left panel scrolls
                and a tall inline expansion used to get clipped/push other content around. */}
            <div className="border-t border-slate-200">
              <button
                ref={diagnosticsButtonRef}
                onClick={() => {
                  const rect = diagnosticsButtonRef.current?.getBoundingClientRect();
                  if (rect) {
                    // Anchor to the bottom of the trigger (grows upward) so the popup
                    // never runs off the bottom edge regardless of where in the scrollable
                    // left panel the button sits; max-height leaves a margin top and bottom.
                    const bottom = Math.max(16, window.innerHeight - rect.bottom);
                    setDiagnosticsPos({ bottom, left: rect.right + 8, maxHeight: window.innerHeight - bottom - 16 });
                  }
                  setShowDiagnostics((v) => !v);
                }}
                title="Diagnostics"
                className="w-full px-4 py-2.5 flex items-center justify-between text-[10px] font-semibold text-slate-400 uppercase tracking-wide hover:bg-slate-50 transition-colors"
              >
                <span className="flex items-center gap-1.5">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
                  </svg>
                  Diagnostics
                </span>
              </button>
            </div>
            </div>
          </div>

          {showDiagnostics && createPortal(
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowDiagnostics(false)} />
              <div
                style={{
                  position: "fixed", bottom: diagnosticsPos.bottom, left: diagnosticsPos.left,
                  maxHeight: diagnosticsPos.maxHeight,
                }}
                className="z-50 w-80 rounded-xl border border-slate-200 bg-white shadow-xl p-3 text-[10px] overflow-y-auto"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide">Diagnostics</span>
                  <button onClick={() => setShowDiagnostics(false)} className="text-slate-400 hover:text-slate-600">✕</button>
                </div>
                <div className="space-y-1">
                  <div><span className="text-slate-400">Reviewed:</span> <span className="text-slate-600">{brief.metadata.sources_reviewed}</span></div>
                  <div><span className="text-slate-400">Retained:</span> <span className="text-slate-600">{brief.metadata.sources_retained}</span></div>
                  <div><span className="text-slate-400">Rejected:</span> <span className="text-slate-600">{brief.metadata.sources_rejected}</span></div>
                  <div className="pt-1.5 mt-1 border-t border-slate-100">
                    <div className="text-slate-400 mb-1">Source credibility tiers:</div>
                    <div className="space-y-1.5">
                      <div>
                        <span className="text-emerald-600 font-semibold">Tier 1 ({brief.metadata.tier_1_count})</span>
                        <div className="text-slate-500">{SOURCE_TIER_LABELS.tier_1}</div>
                      </div>
                      <div>
                        <span className="text-sky-600 font-semibold">Tier 2 ({brief.metadata.tier_2_count})</span>
                        <div className="text-slate-500">{SOURCE_TIER_LABELS.tier_2}</div>
                      </div>
                      <div>
                        <span className="text-slate-500 font-semibold">Tier 3 ({brief.metadata.tier_3_count})</span>
                        <div className="text-slate-500">{SOURCE_TIER_LABELS.tier_3}</div>
                      </div>
                    </div>
                  </div>
                  <div className="pt-1.5 mt-1 border-t border-slate-100"><span className="text-slate-400">Range:</span> <span className="text-slate-600">{brief.metadata.date_range_start} to {brief.metadata.date_range_end}</span></div>
                  <div className="text-slate-400 pt-1">Generated: {brief.generated_at}</div>
                  {brief.search_log.length > 0 && (
                    <div className="pt-2 mt-1 border-t border-slate-100">
                      <div className="text-slate-400 mb-1">
                        Queries run ({brief.metadata.search_queries_executed || brief.search_log.length}):
                      </div>
                      <div className="space-y-2">
                        {brief.search_log.map((entry, i) => (
                          <div key={i} className="text-slate-700">
                            <div className="text-slate-400">{entry.topic}:</div>
                            <div className="font-bold break-words">{entry.query}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </>,
            document.body
          )}

          <button
            onClick={() => setLeftPanelOpen((v) => !v)}
            title={leftPanelOpen ? "Hide section list" : "Show section list"}
            className="shrink-0 w-5 flex items-center justify-center border-r border-slate-200 bg-white hover:bg-slate-50 transition-colors"
          >
            <svg className={`w-3.5 h-3.5 text-slate-400 transition-transform ${leftPanelOpen ? "" : "rotate-180"}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>

          {/* Content Pane — Right */}
          <div className="flex-1 flex flex-col min-w-0">
            <SectionVideoBanner
              activeTab={activeTab}
              brandName={brief.brand_name}
              category={brief.category}
              sectionContent={currentSection?.content ?? ""}
              productNames={productNames}
            />
            {/* Section Header */}
            {activeTab === "all_articles" ? (
              <div className="shrink-0 px-6 py-3 border-b border-slate-100 bg-white flex items-center justify-between">
                <h2 className="text-sm font-semibold text-[#5B2C9D] uppercase tracking-wide">All Articles</h2>
              </div>
            ) : currentSection && (
              <div className="shrink-0 px-6 py-3 border-b border-slate-100 bg-white flex items-center justify-between">
                <h2 className="text-sm font-semibold text-[#5B2C9D] uppercase tracking-wide">{currentSection.title}</h2>
                <div className="flex items-center gap-2">
                  {currentSection.edited && (
                    <span className="text-[10px] font-medium text-amber-600 bg-amber-50 px-2 py-0.5 rounded">Edited</span>
                  )}
                  {editingSection === activeTab ? (
                    <button onClick={handleSaveSection} className="text-[10px] font-medium text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded hover:bg-emerald-100 transition-colors">
                      Save
                    </button>
                  ) : (
                    <button onClick={() => handleEditSection(activeTab)} className="text-[10px] font-medium text-slate-500 bg-slate-50 px-2.5 py-1 rounded hover:bg-slate-100 transition-colors">
                      Edit
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* Scrollable Content */}
            <div ref={contentRef} className="flex-1 overflow-y-auto px-8 py-6">
              {activeTab === "all_articles" ? (
                projectId ? (
                  <ResearchItemsTable projectId={projectId} />
                ) : (
                  <div className="text-sm text-slate-400 italic">No active project.</div>
                )
              ) : currentSection ? (
                editingSection === activeTab ? (
                  <textarea
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    className="w-full h-full min-h-[400px] text-sm text-slate-700 leading-relaxed border border-slate-200 rounded-lg p-4 focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40 font-mono resize-y"
                  />
                ) : (
                  <div className={`text-[13.5px] text-slate-700 leading-[1.85] font-reading ${activeTab === "competitor_developments" ? "" : "max-w-3xl"}`}>
                    {activeTab === "competitor_developments"
                      ? renderCompetitorSection(currentSection.content, sourceLookup)
                      : renderContent(currentSection.content, sourceLookup, activeTab)}
                    <SectionSources section={currentSection} sources={sourceLookup} />
                  </div>
                )
              ) : (
                <div className="text-sm text-slate-400 italic">Select a section from the left to view its content.</div>
              )}
            </div>

            {/* Bottom Bar: Approval + Navigation */}
            <div className="shrink-0 px-6 py-3 border-t border-slate-200 bg-white flex items-center justify-between">
              <button
                onClick={() => onNavigate("brief-scope-review")}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6" /></svg>
                Brief & Scope
              </button>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setRevisionPanelOpen(true)}
                  className="px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
                >
                  Request Revision
                </button>
                <button
                  onClick={handleApprove}
                  className={`px-4 py-1.5 text-xs font-medium rounded-lg transition-all shadow-sm ${
                    approved
                      ? "bg-emerald-600 text-white"
                      : "text-white hover:shadow-md"
                  }`}
                  style={approved ? {} : { background: "linear-gradient(135deg, #5B2C9D, #7C4DFF)" }}
                >
                  {approved ? "Approved" : "Approve & Continue"}
                </button>
                <button
                  onClick={() => onNavigate("search-strategy")}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white rounded-lg transition-all hover:shadow-md"
                  style={{ background: "linear-gradient(135deg, #5B2C9D, #7C4DFF)" }}
                >
                  Search Strategy
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6" /></svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Non-ready states: bottom nav */}
      {pageState !== "ready" && (
        <div className="shrink-0 px-6 py-3 border-t border-slate-200 bg-white flex items-center justify-between">
          <button
            onClick={() => onNavigate("brief-scope-review")}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6" /></svg>
            Brief & Scope
          </button>
          <button
            onClick={() => onNavigate("search-strategy")}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white rounded-lg transition-all hover:shadow-md"
            style={{ background: "linear-gradient(135deg, #5B2C9D, #7C4DFF)" }}
          >
            Search Strategy
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6" /></svg>
          </button>
        </div>
      )}

      {/* Request Revision panel */}
      {revisionPanelOpen && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => !submittingRevision && setRevisionPanelOpen(false)} />
          <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-2xl border border-slate-200 animate-fade-in">
            <div className="px-5 pt-5 pb-3 border-b border-slate-100">
              <h2 className="text-sm font-semibold text-slate-900">Request a revision</h2>
              <p className="text-xs text-slate-500 mt-1">
                What should be improved? (Optional.) This restarts web research from scratch and
                regenerates the brief, feeding any feedback you add directly into the synthesis.
              </p>
            </div>
            <div className="px-5 py-4">
              <textarea
                value={revisionNotes}
                onChange={(e) => setRevisionNotes(e.target.value)}
                rows={6}
                placeholder="e.g. Add more detail on pricing strategy; the competitor section reads too generic; missing recent regulatory news..."
                className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm text-slate-800 bg-white focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40 resize-y"
              />
            </div>
            <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-slate-100">
              <button
                onClick={() => setRevisionPanelOpen(false)}
                disabled={submittingRevision}
                className="px-4 py-2 text-sm font-medium text-slate-500 hover:text-slate-700 transition-colors disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmitRevision}
                disabled={submittingRevision}
                className="px-4 py-2 text-sm font-medium text-white rounded-lg shadow-sm transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                style={{ backgroundColor: "#5B2C9D" }}
              >
                {submittingRevision ? "Restarting..." : "Restart with revisions"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

import { useState, useEffect, useCallback, useRef } from "react";
import type { ReactNode } from "react";
import { Icon } from "@iconify/react";
import { useProject, useActiveProjectId, type ProjectType } from "../context/project-context";
import { intelApi, type SpecResult, type SpecReadiness, type SpecClarification, type JobStatus } from "../services/intel-api";
import { BrandLogo } from "../components/BrandLogo";
import { CountryFlag } from "../components/CountryFlag";
import { useAgentSocket } from "../hooks/useAgentSocket";
import type { WsMessage } from "../services/ws";

const SPEC_JOB_TYPE = "spec_generation";
const LOGO_SIZE = 36;
const HEADER_LOGO_SIZE = 56;

interface SpecEntity {
  name: string;
  type: string;
  confidence?: string;
  reasoning?: string;
  /** brand/competitor only — messaging/positioning terms for message-congruence tracking. */
  keywords?: string[];
}

/** Entity types shown with a brand-style logo/monogram (BrandLogo attempts Brandfetch/Google
 * for these — including events, e.g. "Boston Marathon" resolves a real logo); "geography"
 * gets a country flag instead (see FLAG_ENTITY_TYPES); the rest (person, audience, category,
 * topic, campaign) render as plain lettered chips. */
const LOGO_ENTITY_TYPES = new Set(["brand", "company", "competitor", "product", "product_group", "executive", "event"]);
const FLAG_ENTITY_TYPES = new Set(["geography"]);

const ENTITY_GROUP_ORDER: { type: string; label: string }[] = [
  { type: "brand", label: "Brand" },
  { type: "company", label: "Companies" },
  { type: "competitor", label: "Competitors" },
  { type: "product", label: "Products" },
  { type: "product_group", label: "Product Groups" },
  { type: "person", label: "People" },
  { type: "executive", label: "Executives" },
  { type: "event", label: "Events" },
  { type: "audience", label: "Audiences" },
  { type: "category", label: "Categories" },
  { type: "topic", label: "Topics" },
  { type: "campaign", label: "Campaigns" },
  { type: "geography", label: "Geography" },
];

/** Iconify slugs for common research platforms, matched by keyword against the platform
 * text rather than requiring an exact match — GPT often groups several platforms into one
 * descriptive phrase, e.g. "Social media (Twitter/X, Instagram, Facebook)" or "Online
 * running forums (Reddit, Let's Run, etc.)". Ordered longest-keyword-first so e.g.
 * "review sites" matches before the bare "review". */
const PLATFORM_ICON_RULES: { keywords: string[]; icon: string }[] = [
  { keywords: ["twitter", "x.com", " x/", "(x)", "/x,", "x,"], icon: "mdi:twitter" },
  { keywords: ["instagram", "ig"], icon: "mdi:instagram" },
  { keywords: ["facebook", "fb"], icon: "mdi:facebook" },
  { keywords: ["reddit"], icon: "mdi:reddit" },
  { keywords: ["youtube"], icon: "mdi:youtube" },
  { keywords: ["tiktok"], icon: "mdi:music-note" },
  { keywords: ["linkedin"], icon: "mdi:linkedin" },
  { keywords: ["pinterest"], icon: "mdi:pinterest" },
  { keywords: ["review site", "reviews", "trustpilot", "yelp"], icon: "mdi:star-outline" },
  { keywords: ["forum", "community", "communities"], icon: "mdi:forum" },
  { keywords: ["blog"], icon: "mdi:post" },
  { keywords: ["news", "press", "media outlet"], icon: "mdi:newspaper-variant" },
  { keywords: ["podcast"], icon: "mdi:podcast" },
  { keywords: ["social media", "social network"], icon: "mdi:account-group" },
];

/** All platform icons whose keyword appears in `text` (deduped, in rule order); falls
 * back to a generic globe when nothing recognizable is found. */
function platformIcons(text: string): string[] {
  const lower = text.toLowerCase();
  const matched = PLATFORM_ICON_RULES.filter((rule) => rule.keywords.some((kw) => lower.includes(kw))).map((r) => r.icon);
  const unique = Array.from(new Set(matched));
  return unique.length > 0 ? unique : ["mdi:web"];
}

interface JobProgressEntry {
  message: string;
  pct: number | null;
  at: number;
}

/** Mirrors domains/spec/repository.py::MANDATORY_SECTIONS — for the "Required" badge
 * in the rules-checklist drawer only; the backend remains the source of truth for
 * readiness computation itself. */
const MANDATORY_SECTIONS = [
  "project_understanding",
  "business_objective",
  "research_objectives",
  "research_questions",
  "scope_dimensions",
  "entities",
  "methodology",
  "data_requirements",
  "deliverables",
  "success_criteria",
];

// Mouse-tracked radial spotlight, adapted from reactbits' SpotlightCard
// (components/SpotlightCard) for this app's light theme and violet brand
// accent — the dark-theme original tracks the same pointer math but painted
// a white glow over a neutral-900 card; here it's a faint violet wash over
// the existing slate-50 card background.
function SpotlightPanel({ children, className = "" }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [opacity, setOpacity] = useState(0);

  return (
    <div
      ref={ref}
      onMouseMove={(e) => {
        if (!ref.current) return;
        const rect = ref.current.getBoundingClientRect();
        setPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
      }}
      onMouseEnter={() => setOpacity(1)}
      onMouseLeave={() => setOpacity(0)}
      className={`relative overflow-hidden ${className}`}
    >
      <div
        className="pointer-events-none absolute inset-0 transition-opacity duration-500 ease-out"
        style={{
          opacity,
          background: `radial-gradient(420px circle at ${pos.x}px ${pos.y}px, rgba(91,44,157,0.07), transparent 70%)`,
        }}
      />
      <div className="relative">{children}</div>
    </div>
  );
}

/** Live progress for a running spec_generation job (initial Analyze Brief or a
 * Reanalyze) — a spinner + progress bar plus a scrolling log of stage messages
 * streamed over /ws as `intel_job_update` messages. */
function JobProgressCard({ job, log }: { job: JobStatus; log: JobProgressEntry[] }) {
  const pct = job.progress_pct ?? 0;
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-center gap-3">
        <svg className="animate-spin h-5 w-5 text-[#5B2C9D] shrink-0" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-slate-900">
            {job.progress_message || "Generating your specification..."}
          </div>
          <div className="text-xs text-slate-400 mt-0.5">{pct}% complete</div>
        </div>
      </div>
      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full transition-all duration-500 ease-out" style={{ width: `${pct}%`, backgroundColor: "#5B2C9D" }} />
      </div>
      {log.length > 0 && (
        <div className="mt-5 border-t border-slate-100 pt-4 space-y-2 max-h-56 overflow-y-auto">
          {log.slice().reverse().map((entry, i) => (
            <div key={entry.at} className={`flex items-start gap-2 text-xs ${i === 0 ? "text-slate-700" : "text-slate-400"}`}>
              <span className={`mt-1 w-1.5 h-1.5 rounded-full shrink-0 ${i === 0 ? "bg-[#5B2C9D] animate-pulse-dot" : "bg-slate-300"}`} />
              <span>{entry.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function BriefScopeReview({ onNavigate }: { onNavigate: (page: string) => void }) {
  const { activeProject, setActiveProject } = useProject();
  const activeProjectId = useActiveProjectId();
  const [spec, setSpec] = useState<SpecResult | null>(null);
  const [readiness, setReadiness] = useState<SpecReadiness | null>(null);
  const [clarifications, setClarifications] = useState<SpecClarification[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [submitting, setSubmitting] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editFields, setEditFields] = useState({
    summary: "",
    client: "",
    industry: "",
    geography: "",
    time_period: "",
    platforms: "",
    languages: "",
    methodology: "",
  });
  /** Comma-separated entity names per type (keys = ENTITY_GROUP_ORDER's `type`), edited
   * as a group of text inputs and rebuilt into the `entities` section content on save. */
  const [editEntities, setEditEntities] = useState<Record<string, string>>({});
  const [editingAnswer, setEditingAnswer] = useState<number | null>(null);
  const [editAnswerText, setEditAnswerText] = useState("");
  const [activeJob, setActiveJob] = useState<JobStatus | null>(null);
  const [jobLog, setJobLog] = useState<JobProgressEntry[]>([]);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [reanalyzeOpen, setReanalyzeOpen] = useState(false);
  const [reanalyzeText, setReanalyzeText] = useState("");
  const [reanalyzing, setReanalyzing] = useState(false);
  const [bgImage, setBgImage] = useState<string | null>(null);
  const [bgVideo, setBgVideo] = useState<string | null>(null);
  const [pexelsSourceUrl, setPexelsSourceUrl] = useState<string | null>(null);
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const [entityView, setEntityView] = useState<"chips" | "table">("chips");

  const loadSpec = useCallback(async () => {
    if (!activeProjectId) return;
    setLoading(true);
    setFetchError(null);
    try {
      const result = await intelApi.getSpec(activeProjectId);
      setSpec(result);
      setReadiness(result.readiness);
      setClarifications(result.clarifications || []);
    } catch {
      setSpec(null);
    } finally {
      setLoading(false);
    }
  }, [activeProjectId]);

  useEffect(() => { loadSpec(); }, [loadSpec]);

  // Pick up a spec-generation job already running for this project (e.g. started by
  // NewProject's Analyze Brief, which navigates here immediately rather than waiting).
  useEffect(() => {
    if (!activeProjectId) return;
    let cancelled = false;
    intelApi.listJobs(activeProjectId, SPEC_JOB_TYPE).then((jobs) => {
      if (cancelled) return;
      const running = jobs.find((j) => j.status === "pending" || j.status === "running");
      if (running) setActiveJob(running);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [activeProjectId]);

  const handleJobMessage = useCallback((msg: WsMessage) => {
    if (msg.type !== "intel_job_update" || msg.job_type !== SPEC_JOB_TYPE) return;
    if (typeof msg.project_id === "number" && msg.project_id !== activeProjectId) return;

    const message = typeof msg.message === "string" ? msg.message : "";
    const pct = typeof msg.progress_pct === "number" ? msg.progress_pct : null;
    if (message) {
      setJobLog((prev) => [...prev, { message, pct, at: Date.now() }].slice(-30));
    }

    if (msg.status === "completed") {
      setActiveJob(null);
      loadSpec();
      return;
    }
    if (msg.status === "failed") {
      setActiveJob(null);
      setFetchError(message || "Specification generation failed");
      return;
    }
    setActiveJob({
      job_id: String(msg.job_id ?? ""),
      status: "running",
      progress_pct: pct ?? 0,
      progress_message: message,
    });
  }, [activeProjectId, loadSpec]);

  useAgentSocket(handleJobMessage);

  // Dynamic, brand-related header background photo (Pexels) — keyed on the brand/client
  // name once known, falling back to the project name. A bare brand name that's also a
  // common dictionary word (Apple, Dove, Target, Shell...) returns Pexels' literal stock
  // photos for that word instead of corporate/brand imagery — confirmed live ("Apple"
  // alone surfaced fruit photography) — so "company" is always appended to steer the
  // search toward business/brand stock imagery rather than the word's literal meaning.
  const bgQuery = activeProject?.brand || activeProject?.name || "";
  const pexelsQuery = bgQuery ? `${bgQuery} company` : "";
  useEffect(() => {
    if (!pexelsQuery.trim()) return;
    let cancelled = false;
    intelApi.getPexelsImage(pexelsQuery).then((res) => {
      if (cancelled) return;
      setBgImage(res.image_url);
      setBgVideo(res.video_url);
      setPexelsSourceUrl(res.source_url);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [pexelsQuery]);

  const handleGenerate = async () => {
    if (!activeProjectId) return;
    setGenerating(true);
    setJobLog([]);
    try {
      const project = await intelApi.getProject(activeProjectId);
      const rawBrief = (project.spec as Record<string, unknown>)?.raw_brief as string || "";
      const started = await intelApi.generateSpec(activeProjectId, rawBrief, true);
      setActiveJob({ job_id: started.job_id, status: "pending", progress_pct: 0, progress_message: "Starting" });
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Failed to generate specification");
    } finally {
      setGenerating(false);
    }
  };

  const openReanalyze = () => {
    if (!spec) return;
    setReanalyzeText(spec.raw_brief_text || "");
    setFetchError(null);
    setReanalyzeOpen(true);
  };

  /** "Reanalyze" — for when the user doesn't like the generated briefing. Re-runs GPT
   * interpretation against the (optionally edited/enhanced) brief text; locked/approved
   * sections are preserved by default (confirm_overwrite_locked stays false). */
  const handleReanalyze = async () => {
    if (!spec || !reanalyzeText.trim()) return;
    setReanalyzing(true);
    setJobLog([]);
    try {
      const started = await intelApi.regenerateSpec(spec.id, reanalyzeText.trim(), true, false);
      setActiveJob({ job_id: started.job_id, status: "pending", progress_pct: 0, progress_message: "Starting" });
      setReanalyzeOpen(false);
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Failed to start reanalysis");
    } finally {
      setReanalyzing(false);
    }
  };

  const handleSubmitAnswer = async (clarId: number) => {
    const answer = answers[clarId]?.trim();
    if (!answer) return;
    setSubmitting(clarId);
    try {
      await intelApi.resolveSpecClarification(clarId, answer);
      setAnswers(prev => { const next = { ...prev }; delete next[clarId]; return next; });
      await loadSpec();
    } catch {
    } finally {
      setSubmitting(null);
    }
  };

  const handleSkipQuestion = async (clarId: number) => {
    setSubmitting(clarId);
    try {
      await intelApi.resolveSpecClarification(clarId, "Skipped — use best judgment", "analyst");
      await loadSpec();
    } catch {
    } finally {
      setSubmitting(null);
    }
  };

  /** All entity types that appear in the edit form — every ENTITY_GROUP_ORDER type,
   * so nothing typed by GPT (or a prior edit) silently vanishes on save. */
  const EDITABLE_ENTITY_TYPES = ENTITY_GROUP_ORDER.map((g) => g.type);

  const startEditing = () => {
    if (!spec) return;
    const sections = spec.spec?.sections || {};
    const uc = sections.project_understanding?.content;
    const sc = sections.scope_dimensions?.content as Record<string, unknown> | undefined;
    const mc = sections.methodology?.content;
    const ec = sections.entities?.content;
    const entitiesArr = Array.isArray(ec) ? (ec as Record<string, unknown>[]) : [];
    const grouped: Record<string, string> = {};
    for (const type of EDITABLE_ENTITY_TYPES) {
      grouped[type] = entitiesArr
        .filter((e) => e.type === type)
        .map((e) => String(e.name || ""))
        .filter(Boolean)
        .join(", ");
    }
    setEditEntities(grouped);
    setEditFields({
      summary: typeof uc === "string" ? uc : typeof uc === "object" && uc !== null ? Object.values(uc as Record<string, unknown>).filter(v => typeof v === "string").join("\n") : "",
      client,
      industry: industry?.name || "",
      geography: sc?.geography ? String(sc.geography) : "",
      time_period: sc?.time_period ? String(sc.time_period) : "",
      platforms: sc?.platforms ? (Array.isArray(sc.platforms) ? sc.platforms.join(", ") : String(sc.platforms)) : "",
      languages: sc?.languages ? (Array.isArray(sc.languages) ? sc.languages.join(", ") : String(sc.languages)) : "",
      methodology: typeof mc === "string" ? mc : typeof mc === "object" && mc !== null ? (mc as Record<string, unknown>).primary ? String((mc as Record<string, unknown>).primary) : "" : "",
    });
    setEditing(true);
  };

  const handleSaveEdits = async () => {
    if (!spec || !activeProjectId) return;
    setSaving(true);
    try {
      await intelApi.updateSpecSection(spec.id, "project_understanding", editFields.summary);
      const sc = (spec.spec?.sections?.scope_dimensions?.content || {}) as Record<string, unknown>;
      await intelApi.updateSpecSection(spec.id, "scope_dimensions", {
        ...sc,
        geography: editFields.geography,
        time_period: editFields.time_period,
        platforms: editFields.platforms.split(",").map(s => s.trim()).filter(Boolean),
        languages: editFields.languages.split(",").map(s => s.trim()).filter(Boolean),
      });
      const mc = spec.spec?.sections?.methodology?.content;
      const methObj = typeof mc === "object" && mc !== null ? mc as Record<string, unknown> : {};
      await intelApi.updateSpecSection(spec.id, "methodology", typeof mc === "string" ? editFields.methodology : { ...methObj, primary: editFields.methodology });

      // Rebuild the full entities array from every type's edited comma-separated list —
      // this is the section's only shape (a bare array), so every group must round-trip.
      const newEntities = EDITABLE_ENTITY_TYPES.flatMap((type) =>
        (editEntities[type] || "").split(",").map(s => s.trim()).filter(Boolean).map((name) => ({
          name, type, confidence: "high", reasoning: "Manually edited by analyst",
        }))
      );
      await intelApi.updateSpecSection(spec.id, "entities", newEntities);

      if (editFields.industry.trim() !== (industry?.name || "")) {
        await intelApi.updateSpecIndustry(spec.id, editFields.industry.trim(), industry?.reasoning || "Manually edited by analyst");
      }
      if (editFields.client.trim() && editFields.client.trim() !== client) {
        const updated = await intelApi.updateProject(activeProjectId, { brand: editFields.client.trim() });
        setActiveProject({
          id: updated.id, name: updated.project_name,
          project_type: (updated.project_type as ProjectType) || (activeProject?.project_type ?? "research"),
          brand: updated.brand ?? editFields.client.trim(),
        });
      }

      await loadSpec();
      setEditing(false);
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateAnswer = async (clarId: number) => {
    const text = editAnswerText.trim();
    if (!text) return;
    setSubmitting(clarId);
    try {
      await intelApi.resolveSpecClarification(clarId, text);
      setEditingAnswer(null);
      setEditAnswerText("");
      await loadSpec();
    } catch {
    } finally {
      setSubmitting(null);
    }
  };

  const [saved, setSaved] = useState(false);

  const handleSaveSpec = async () => {
    if (!spec) return;
    try {
      await intelApi.approveSpec(spec.id);
      await loadSpec();
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Save failed");
    }
  };

  const handleApproveSpec = async () => {
    if (!spec) return;
    try {
      await intelApi.approveSpec(spec.id);
      await loadSpec();
      setTimeout(() => onNavigate("background-research"), 600);
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Approval failed");
    }
  };

  const handleDownloadDocx = async () => {
    if (!spec) return;
    setDownloading(true);
    try {
      await intelApi.renderSpecDocx(spec.id);
      const blob = await intelApi.downloadSpecDocx(spec.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Research_Specification_${activeProject?.name || "spec"}.docx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
    } finally {
      setDownloading(false);
    }
  };

  // ── Early returns ──

  if (!activeProjectId) {
    return (
      <div className="p-8 max-w-3xl mx-auto animate-fade-in">
        <h1 className="text-xl font-semibold text-slate-900">Brief & Scope</h1>
        <div className="mt-8 bg-amber-50 border border-amber-200 rounded-xl p-6">
          <p className="text-sm text-amber-800">No active project. Create one first.</p>
          <button onClick={() => onNavigate("new-project")} className="mt-3 px-4 py-2.5 text-sm font-medium bg-[#5B2C9D] text-white rounded-lg hover:opacity-90 transition-colors shadow-sm">
            Create Project
          </button>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="p-8 max-w-3xl mx-auto animate-fade-in">
        <h1 className="text-xl font-semibold text-slate-900">Brief & Scope</h1>
        <p className="text-sm text-slate-500 mt-0.5">{activeProject?.name}</p>
        <div className="mt-12 flex items-center justify-center py-16">
          <div className="flex items-center gap-3 text-sm text-slate-500">
            <svg className="animate-spin h-5 w-5 text-[#5B2C9D]" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Loading...
          </div>
        </div>
      </div>
    );
  }

  if (!spec) {
    if (activeJob) {
      return (
        <div className="p-8 max-w-3xl mx-auto animate-fade-in">
          <h1 className="text-xl font-semibold text-slate-900">Brief & Scope</h1>
          <p className="text-sm text-slate-500 mt-0.5">{activeProject?.name}</p>
          <div className="mt-8">
            <JobProgressCard job={activeJob} log={jobLog} />
          </div>
        </div>
      );
    }
    return (
      <div className="p-8 max-w-3xl mx-auto animate-fade-in">
        <h1 className="text-xl font-semibold text-slate-900">Brief & Scope</h1>
        <p className="text-sm text-slate-500 mt-0.5">{activeProject?.name}</p>
        <div className="mt-8 bg-white border border-slate-200 rounded-xl p-8 text-center shadow-sm">
          <h2 className="text-base font-semibold text-slate-900">Analyze your brief</h2>
          <p className="text-sm text-slate-500 mt-2 max-w-sm mx-auto">
            We'll read your brief, extract scope, objectives, and entities, then ask you to confirm a few details.
          </p>
          {fetchError && <p className="text-sm text-red-600 mt-3">{fetchError}</p>}
          <button
            disabled={generating}
            onClick={handleGenerate}
            className="mt-5 px-5 py-2.5 text-sm font-medium text-white rounded-lg shadow-sm transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ backgroundColor: "#5B2C9D" }}
          >
            {generating ? "Starting..." : "Analyze Brief"}
          </button>
        </div>
      </div>
    );
  }

  // ── Main render — spec loaded ──

  const sections = spec.spec?.sections || {};
  const isApproved = spec.approval_status === "approved";

  // Extract the summary from project_understanding section
  const understandingContent = sections.project_understanding?.content;
  let summaryTextFull = "";
  if (typeof understandingContent === "string") {
    summaryTextFull = understandingContent.split("\n").filter(l => l.trim()).join(" ");
  } else if (typeof understandingContent === "object" && understandingContent !== null && !Array.isArray(understandingContent)) {
    const vals = Object.values(understandingContent as Record<string, unknown>);
    summaryTextFull = vals.filter(v => typeof v === "string").join(" ");
  }
  const SUMMARY_TRUNCATE_AT = 260;
  const summaryIsLong = summaryTextFull.length > SUMMARY_TRUNCATE_AT;
  const summaryText = summaryExpanded || !summaryIsLong
    ? summaryTextFull
    : summaryTextFull.slice(0, SUMMARY_TRUNCATE_AT).trimEnd() + "...";

  // Scope section fields: geography, time period, platforms/languages/content types, methodology
  const scopeContent = sections.scope_dimensions?.content;
  const scopeObj = (typeof scopeContent === "object" && scopeContent !== null && !Array.isArray(scopeContent)) ? scopeContent as Record<string, unknown> : {};
  const toList = (v: unknown): string[] => Array.isArray(v) ? v.map(String).filter(Boolean) : (v ? [String(v)] : []);
  const platformsList = toList(scopeObj.platforms);
  const languagesList = toList(scopeObj.languages);
  const contentTypesList = toList(scopeObj.content_types);
  const methodContent = sections.methodology?.content;
  const methodologyFull = (typeof methodContent === "object" && methodContent !== null && !Array.isArray(methodContent))
    ? String((methodContent as Record<string, unknown>).primary || "")
    : (typeof methodContent === "string" ? methodContent : "");

  // Header identity fields: Project Name, Client, Geography, Time Period, Research Type
  const sourceSpec = (spec.spec?.source_spec || {}) as Record<string, unknown>;
  const commissioningBrand = (sourceSpec.commissioning_brand || {}) as Record<string, unknown>;
  const client = activeProject?.brand || (commissioningBrand.name ? String(commissioningBrand.name) : "");
  const geography = scopeObj.geography ? String(scopeObj.geography) : "";
  const timePeriod = scopeObj.time_period ? String(scopeObj.time_period) : "";
  const researchType = methodologyFull;
  const industry = spec.spec?.industry && "name" in spec.spec.industry && spec.spec.industry.name
    ? spec.spec.industry as { name: string; reasoning: string }
    : null;

  // Entities grouped by type (products/companies/people/product groups/events/etc.),
  // per the extended ENTITY_TYPES enum in agents/brief_scope.py.
  const entityContent = sections.entities?.content;
  const entities: SpecEntity[] = Array.isArray(entityContent)
    ? (entityContent as Record<string, unknown>[])
        .map((e) => ({
          name: String(e.name || ""),
          type: String(e.type || "other"),
          confidence: e.confidence ? String(e.confidence) : undefined,
          reasoning: e.reasoning ? String(e.reasoning) : undefined,
          keywords: Array.isArray(e.keywords) ? e.keywords.map(String).filter(Boolean) : undefined,
        }))
        .filter((e) => e.name)
    : [];
  const entitiesByType = new Map<string, SpecEntity[]>();
  for (const e of entities) {
    const list = entitiesByType.get(e.type) || [];
    list.push(e);
    entitiesByType.set(e.type, list);
  }

  // Split clarifications
  const unresolvedBlocking = clarifications.filter(c => c.is_blocking && !c.resolved_at);
  const unresolvedAdvisory = clarifications.filter(c => !c.is_blocking && !c.resolved_at);
  const resolved = clarifications.filter(c => c.resolved_at);
  const allResolved = unresolvedBlocking.length === 0 && unresolvedAdvisory.length === 0;

  const renderQuestion = (c: SpecClarification, idx: number, isBlocking: boolean) => (
    <div key={c.id} className="py-4 border-b border-slate-100 last:border-0">
      <div className="flex items-start gap-3">
        <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold shrink-0 mt-0.5 ${isBlocking ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"}`}>
          {idx + 1}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-800 leading-relaxed max-w-prose">{c.question}</p>
          <div className="mt-2.5 flex gap-2">
            <input
              type="text"
              value={answers[c.id] || ""}
              onChange={(e) => setAnswers(prev => ({ ...prev, [c.id]: e.target.value }))}
              onKeyDown={(e) => e.key === "Enter" && handleSubmitAnswer(c.id)}
              placeholder="Type your answer..."
              className="flex-1 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-900 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40 transition-all"
            />
            <button
              onClick={() => handleSubmitAnswer(c.id)}
              disabled={!answers[c.id]?.trim() || submitting === c.id}
              className="px-3 py-2 text-xs font-medium text-white rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
              style={{ backgroundColor: "#5B2C9D" }}
            >
              {submitting === c.id ? "..." : "Submit"}
            </button>
            <button
              onClick={() => handleSkipQuestion(c.id)}
              disabled={submitting === c.id}
              className="px-3 py-2 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50 transition-all disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
            >
              Skip
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  const hasScope = !!(geography || timePeriod || platformsList.length > 0 || languagesList.length > 0 || contentTypesList.length > 0 || methodologyFull);
  const hasWhatWeUnderstood = !!(summaryText || editing);
  const hasAdvisory = !isApproved && unresolvedAdvisory.length > 0;

  return (
    <>
    <div className="p-8 max-w-7xl mx-auto space-y-6 animate-fade-in">
      {/* Header + Scope */}
      <div className={`grid grid-cols-1 gap-5 ${hasScope ? "md:grid-cols-2" : ""}`}>
      {/* Header */}
      <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {bgVideo ? (
          <>
            <video
              src={bgVideo}
              poster={bgImage || undefined}
              autoPlay muted loop playsInline
              className="absolute inset-0 w-full h-full object-cover"
              aria-hidden="true"
            />
            <div className="absolute inset-0 bg-gradient-to-r from-white/90 via-white/60 to-white/25" />
          </>
        ) : bgImage ? (
          <>
            <img src={bgImage} alt="" className="absolute inset-0 w-full h-full object-cover" aria-hidden="true" />
            <div className="absolute inset-0 bg-gradient-to-r from-white/90 via-white/60 to-white/25" />
          </>
        ) : (
          <div className="absolute inset-0 opacity-[0.04]" style={{
            background: "radial-gradient(ellipse at 15% 30%, #5B2C9D 0%, transparent 60%), radial-gradient(ellipse at 90% 80%, #7C4DFF 0%, transparent 55%)"
          }} />
        )}
        <div className="relative px-6 py-5">
          {/* Row 1: logo + title + project name */}
          <div className="flex items-center gap-3 min-w-0">
            <BrandLogo brandName={client || activeProject?.name || "?"} size={HEADER_LOGO_SIZE} rounded="lg" />
            <div className="min-w-0">
              <h1 className="text-xl font-semibold text-slate-900">Brief & Scope</h1>
              <p className="text-sm text-slate-500 mt-0.5 truncate">{activeProject?.name}</p>
            </div>
          </div>

          {/* Row 2: actions | identity chips — two columns, vertically centered */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-center mt-4 pt-4 border-t border-slate-100">
            <div className="flex flex-wrap items-center gap-2">
              {isApproved && (
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700 bg-emerald-50 px-3 py-1 rounded-full border border-emerald-200 shadow-sm">
                  <span className="relative flex h-1.5 w-1.5">
                    <span className="animate-pulse-dot absolute inline-flex h-full w-full rounded-full bg-emerald-500" />
                    <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500" />
                  </span>
                  Approved
                </span>
              )}
              <button
                onClick={openReanalyze}
                disabled={!!activeJob}
                title="Not happy with this briefing? Edit the brief and request a revision."
                className="flex items-center gap-1 text-xs font-medium text-slate-500 border border-slate-200 bg-white/80 px-2.5 py-1.5 rounded-lg hover:bg-slate-50 hover:text-slate-700 transition-colors disabled:opacity-40"
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h5M20 20v-5h-5M4.6 15a8 8 0 0014.7 2.3M19.4 9A8 8 0 004.7 6.7" />
                </svg>
                Request Revision
              </button>
              <button
                onClick={handleDownloadDocx}
                disabled={downloading}
                className="text-xs font-medium text-[#5B2C9D] border border-[#5B2C9D]/20 bg-white/80 px-3 py-1.5 rounded-lg hover:bg-[#5B2C9D]/5 transition-colors disabled:opacity-40"
              >
                {downloading ? "Exporting..." : "Export Full Spec"}
              </button>
              {readiness && (
                <button
                  onClick={() => setRulesOpen(true)}
                  title="Open the specification rules checklist"
                  className="flex items-center gap-1.5 text-xs font-medium text-slate-500 border border-slate-200 bg-white/80 px-2.5 py-1.5 rounded-lg hover:bg-slate-50 hover:text-slate-700 transition-colors"
                >
                  <span>Rules {readiness.filled_count}/{readiness.total_count}</span>
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M18 15l-6-6-6 6" />
                  </svg>
                </button>
              )}
            </div>

            {(client || geography || timePeriod || researchType) && (
              <div className="flex flex-wrap items-center gap-2 md:justify-end">
                {client && (
                  <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-600 bg-white/80 border border-slate-200 px-2.5 py-1 rounded-full">
                    <span className="text-slate-400">Client:</span> {client}
                  </span>
                )}
                {geography && (
                  <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-600 bg-white/80 border border-slate-200 px-2.5 py-1 rounded-full">
                    <CountryFlag country={geography} size={16} />
                    {geography}
                  </span>
                )}
                {timePeriod && (
                  <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-600 bg-white/80 border border-slate-200 px-2.5 py-1 rounded-full">
                    <span className="text-slate-400">Time Period:</span> {timePeriod}
                  </span>
                )}
                {researchType && (
                  <span
                    title={researchType}
                    className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-600 bg-white/80 border border-slate-200 px-2.5 py-1 rounded-full max-w-xs"
                  >
                    <span className="text-slate-400 shrink-0">Research Type:</span>
                    <span className="truncate">{researchType}</span>
                  </span>
                )}
              </div>
            )}
          </div>
          {(bgVideo || bgImage) && (
            <a href={pexelsSourceUrl || undefined} target="_blank" rel="noopener noreferrer"
               className="absolute bottom-1.5 right-2.5 text-[9px] text-slate-400 hover:text-slate-600 transition-colors">
              {bgVideo ? "Video via Pexels" : "Photo via Pexels"}
            </a>
          )}
        </div>
      </div>

      {/* Scope */}
      {hasScope && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-3">Scope</div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 items-center">
            {geography && (
              <div className="text-center">
                <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Geography</div>
                <span className="inline-flex items-center justify-center gap-1.5 text-sm text-slate-700"><CountryFlag country={geography} size={18} />{geography}</span>
              </div>
            )}
            {timePeriod && (
              <div className="text-center">
                <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Time Period</div>
                <span className="text-sm text-slate-700">{timePeriod}</span>
              </div>
            )}
            {platformsList.length > 0 && (
              <div className="col-span-2">
                <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Platforms</div>
                <div className="flex flex-wrap gap-2">
                  {platformsList.map((p) => (
                    <span key={p} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-slate-200 bg-slate-50 text-xs font-medium text-slate-700">
                      <span className="inline-flex items-center -space-x-0.5">
                        {platformIcons(p).map((icon) => (
                          <Icon key={icon} icon={icon} width={16} height={16} className="text-slate-500" />
                        ))}
                      </span>
                      {p}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {languagesList.length > 0 && (
              <div className="text-center">
                <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Languages</div>
                <span className="text-sm text-slate-700">{languagesList.join(", ")}</span>
              </div>
            )}
            {contentTypesList.length > 0 && (
              <div className="text-center">
                <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Content Types</div>
                <span className="text-sm text-slate-700">{contentTypesList.join(", ")}</span>
              </div>
            )}
            {methodologyFull && (
              <div className="col-span-2 pt-2 border-t border-slate-100">
                <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Methodology / Research Type</div>
                <p className="text-sm text-slate-700 leading-relaxed">{methodologyFull}</p>
              </div>
            )}
          </div>
        </div>
      )}
      </div>

      {activeJob && <JobProgressCard job={activeJob} log={jobLog} />}

      {fetchError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">{fetchError}</div>
      )}

      {/* What we understood + Optional clarifications */}
      {(hasWhatWeUnderstood || hasAdvisory) && (
      <div className="grid grid-cols-1 gap-5">
      {hasWhatWeUnderstood && (
        <SpotlightPanel className="rounded-2xl border border-slate-200 bg-slate-50 p-6">
          <div className="flex items-center justify-between mb-2">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">What we understood</div>
            {!editing ? (
              <button
                onClick={startEditing}
                className="flex items-center gap-1 text-[11px] font-medium text-[#5B2C9D] hover:text-[#5B2C9D]/80 transition-colors"
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                  <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                </svg>
                Edit
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setEditing(false)}
                  className="text-[11px] font-medium text-slate-400 hover:text-slate-600 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveEdits}
                  disabled={saving}
                  className="flex items-center gap-1 text-[11px] font-medium text-white px-3 py-1 rounded-md transition-all disabled:opacity-50"
                  style={{ backgroundColor: "#5B2C9D" }}
                >
                  {saving ? "Saving..." : "Save Changes"}
                </button>
              </div>
            )}
          </div>

          {!editing ? (
            <>
              <p className="text-sm text-slate-700 leading-relaxed">
                {summaryText}
                {summaryIsLong && (
                  <button
                    onClick={() => setSummaryExpanded((v) => !v)}
                    className="ml-1.5 text-xs font-medium text-[#5B2C9D] hover:text-[#5B2C9D]/80 transition-colors align-baseline"
                  >
                    {summaryExpanded ? "Show less" : "Show more"}
                  </button>
                )}
              </p>

              {(client || industry) && (
                <div className="grid grid-cols-2 gap-x-6 gap-y-2 mt-3 pt-3 border-t border-slate-200">
                  {client && (
                    <div>
                      <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Client</div>
                      <span className="text-sm text-slate-700">{client}</span>
                    </div>
                  )}
                  {industry && (
                    <div title={industry.reasoning}>
                      <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Industry</div>
                      <span className="text-sm text-slate-700">{industry.name}</span>
                    </div>
                  )}
                </div>
              )}

              {entities.length > 0 && (
                <div className="flex items-center justify-between mt-3 pt-3 border-t border-slate-200">
                  <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Entities</span>
                  <div className="flex items-center rounded-lg border border-slate-200 bg-white p-0.5">
                    {(["chips", "table"] as const).map((v) => (
                      <button
                        key={v}
                        onClick={() => setEntityView(v)}
                        className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition-colors capitalize ${entityView === v ? "bg-[#5B2C9D] text-white" : "text-slate-500 hover:text-slate-700"}`}
                      >
                        {v}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {entityView === "chips" ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4 mt-3">
                {ENTITY_GROUP_ORDER.filter(({ type }) => (entitiesByType.get(type)?.length ?? 0) > 0).map(({ type, label }) => (
                  <div key={type}>
                    <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2">{label}</div>
                    <div className="flex flex-wrap items-center gap-2">
                      {(entitiesByType.get(type) || []).map((e, i) => (
                        <span
                          key={e.name}
                          title={e.reasoning}
                          className="group inline-flex flex-col gap-1 pl-1.5 pr-3 py-1.5 rounded-2xl border border-slate-200 bg-white shadow-sm hover:shadow-md hover:border-[#5B2C9D]/30 hover:-translate-y-0.5 transition-all animate-fade-in"
                          style={{ animationDelay: `${i * 60}ms` }}
                        >
                          <span className="inline-flex items-center gap-2.5">
                            {LOGO_ENTITY_TYPES.has(type) ? (
                              <BrandLogo brandName={e.name} size={LOGO_SIZE} />
                            ) : FLAG_ENTITY_TYPES.has(type) ? (
                              <CountryFlag country={e.name} size={LOGO_SIZE} />
                            ) : (
                              <span
                                className="rounded-full bg-slate-100 flex items-center justify-center font-semibold text-slate-500 shrink-0"
                                style={{ width: LOGO_SIZE, height: LOGO_SIZE, fontSize: LOGO_SIZE * 0.45 }}
                              >
                                {e.name.charAt(0).toUpperCase()}
                              </span>
                            )}
                            <span className="text-base font-medium text-slate-700 group-hover:text-[#5B2C9D] transition-colors">{e.name}</span>
                          </span>
                          {e.keywords && e.keywords.length > 0 && (
                            <span className="flex flex-wrap gap-1 pl-1">
                              {e.keywords.map((kw) => (
                                <span key={kw} className="text-xs px-1.5 py-0.5 rounded-full bg-slate-50 text-slate-500 border border-slate-100">{kw}</span>
                              ))}
                            </span>
                          )}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
                </div>
              ) : (
                <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-slate-50 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                        <th className="px-3 py-2">Type</th>
                        <th className="px-3 py-2">Name</th>
                        <th className="px-3 py-2">Confidence</th>
                        <th className="px-3 py-2">Keywords / Reasoning</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ENTITY_GROUP_ORDER.filter(({ type }) => (entitiesByType.get(type)?.length ?? 0) > 0).flatMap(({ type, label }) =>
                        (entitiesByType.get(type) || []).map((e) => (
                          <tr key={`${type}-${e.name}`} className="border-t border-slate-100">
                            <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{label}</td>
                            <td className="px-3 py-2 font-medium text-slate-800 whitespace-nowrap">{e.name}</td>
                            <td className="px-3 py-2 text-slate-500 capitalize">{e.confidence || "—"}</td>
                            <td className="px-3 py-2 text-slate-500">
                              {e.keywords && e.keywords.length > 0 ? e.keywords.join(", ") : (e.reasoning || "—")}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : (
            <div className="space-y-3">
              <div>
                <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Summary</label>
                <textarea
                  value={editFields.summary}
                  onChange={(e) => setEditFields(f => ({ ...f, summary: e.target.value }))}
                  rows={4}
                  className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 bg-white focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40 resize-y"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                {([
                  { key: "client", label: "Client" },
                  { key: "industry", label: "Industry" },
                  { key: "geography", label: "Geography" },
                  { key: "time_period", label: "Time Period" },
                  { key: "platforms", label: "Platforms" },
                  { key: "languages", label: "Languages" },
                ] as const).map(({ key, label }) => (
                  <div key={key}>
                    <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">{label}</label>
                    <input
                      type="text"
                      value={editFields[key]}
                      onChange={(e) => setEditFields(f => ({ ...f, [key]: e.target.value }))}
                      placeholder={key === "platforms" || key === "languages" ? "comma-separated" : undefined}
                      className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 bg-white focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40"
                    />
                  </div>
                ))}
              </div>
              <div>
                <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Methodology / Research Type</label>
                <textarea
                  value={editFields.methodology}
                  onChange={(e) => setEditFields(f => ({ ...f, methodology: e.target.value }))}
                  rows={3}
                  className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 bg-white focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40 resize-y"
                />
              </div>
              <div className="pt-1 border-t border-slate-200">
                <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mt-2 mb-1.5">Entities</div>
                <div className="grid grid-cols-2 gap-3">
                  {ENTITY_GROUP_ORDER.map(({ type, label }) => (
                    <div key={type}>
                      <label className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">{label}</label>
                      <input
                        type="text"
                        value={editEntities[type] || ""}
                        onChange={(e) => setEditEntities(prev => ({ ...prev, [type]: e.target.value }))}
                        placeholder="comma-separated"
                        className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-800 bg-white focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40"
                      />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </SpotlightPanel>
      )}

      {hasAdvisory && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm">
          <div className="px-6 pt-6 pb-2">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-amber-400" />
              <h2 className="text-sm font-semibold text-slate-900">Optional clarifications</h2>
              <button
                onClick={async () => {
                  for (const c of unresolvedAdvisory) await handleSkipQuestion(c.id);
                }}
                disabled={submitting !== null}
                className="ml-auto text-xs font-medium text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-40"
              >
                Skip all
              </button>
            </div>
            <p className="text-xs text-slate-500 mt-1 ml-4">Answering these improves research quality, but you can skip them.</p>
          </div>
          <div className="px-6 pb-4">
            {unresolvedAdvisory.map((c, i) => renderQuestion(c, i, false))}
          </div>
        </div>
      )}
      </div>
      )}

      {/* Questions that need answers */}
      {!isApproved && unresolvedBlocking.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm">
          <div className="px-6 pt-6 pb-2">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-red-500" />
              <h2 className="text-sm font-semibold text-slate-900">We need a few details</h2>
              <button
                onClick={async () => {
                  for (const c of unresolvedBlocking) await handleSkipQuestion(c.id);
                }}
                disabled={submitting !== null}
                className="ml-auto text-xs font-medium text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-40"
              >
                Skip all
              </button>
            </div>
            <p className="text-xs text-slate-500 mt-1 ml-4">Answer these or skip to proceed.</p>
          </div>
          <div className="px-6 pb-4">
            {unresolvedBlocking.map((c, i) => renderQuestion(c, i, true))}
          </div>
        </div>
      )}

      {/* Answered questions (collapsed) */}
      {resolved.length > 0 && (
        <details className="group">
          <summary className="text-xs font-medium text-slate-400 cursor-pointer hover:text-slate-600 transition-colors list-none flex items-center gap-1.5">
            <svg className="w-3.5 h-3.5 transition-transform group-open:rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            {resolved.length} answered
          </summary>
          <div className="mt-2 bg-white border border-slate-200 rounded-xl shadow-sm px-5 py-2">
            {resolved.map((c) => (
              <div key={c.id} className="py-3 border-b border-slate-50 last:border-0">
                <p className="text-sm text-slate-500">{c.question}</p>
                {editingAnswer === c.id ? (
                  <div className="mt-1.5 flex gap-2">
                    <input
                      type="text"
                      value={editAnswerText}
                      onChange={(e) => setEditAnswerText(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleUpdateAnswer(c.id)}
                      className="flex-1 border border-slate-200 rounded-lg px-3 py-1.5 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40"
                    />
                    <button
                      onClick={() => handleUpdateAnswer(c.id)}
                      disabled={!editAnswerText.trim() || submitting === c.id}
                      className="px-3 py-1.5 text-xs font-medium text-white rounded-lg disabled:opacity-40"
                      style={{ backgroundColor: "#5B2C9D" }}
                    >
                      {submitting === c.id ? "..." : "Save"}
                    </button>
                    <button
                      onClick={() => { setEditingAnswer(null); setEditAnswerText(""); }}
                      className="px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div className="flex items-start justify-between mt-1 group/answer">
                    <p className="text-sm text-slate-800 pl-3 border-l-2 border-emerald-300">{c.answer}</p>
                    <button
                      onClick={() => { setEditingAnswer(c.id); setEditAnswerText(c.answer || ""); }}
                      className="opacity-0 group-hover/answer:opacity-100 ml-2 text-[11px] font-medium text-[#5B2C9D] hover:text-[#5B2C9D]/80 transition-all shrink-0"
                    >
                      Edit
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Ready state / Approval */}
      {!isApproved && allResolved && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-5 text-center">
          <div className="text-sm font-semibold text-emerald-800">All clear — ready to proceed</div>
          <p className="text-xs text-emerald-600 mt-1">The research specification is complete. Approve to begin background research.</p>
        </div>
      )}

      {!isApproved && (
        <div className="flex items-center justify-between pt-2">
          <button onClick={() => onNavigate("projects")} className="text-sm text-slate-400 hover:text-slate-600 transition-colors">
            Back to Projects
          </button>
          <div className="flex items-center gap-3">
            <button
              onClick={handleSaveSpec}
              disabled={unresolvedBlocking.length > 0}
              className="px-4 py-2.5 text-sm font-medium rounded-lg border transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ color: "#5B2C9D", borderColor: "rgba(91,44,157,0.25)" }}
            >
              {saved ? "Saved!" : "Save"}
            </button>
            <button
              onClick={handleApproveSpec}
              disabled={unresolvedBlocking.length > 0}
              className="px-5 py-2.5 text-sm font-medium text-white rounded-lg transition-all shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ backgroundColor: "#5B2C9D" }}
            >
              {unresolvedBlocking.length > 0 ? `${unresolvedBlocking.length} questions remaining` : "Approve & Proceed"}
            </button>
          </div>
        </div>
      )}

      {isApproved && (
        <div className="flex items-center justify-between pt-2">
          <button onClick={() => onNavigate("projects")} className="text-sm text-slate-400 hover:text-slate-600 transition-colors">
            Back to Projects
          </button>
          <button
            onClick={() => onNavigate("background-research")}
            className="px-5 py-2.5 text-sm font-medium text-white rounded-lg transition-all shadow-sm"
            style={{ backgroundColor: "#5B2C9D" }}
          >
            Proceed to Background Research
          </button>
        </div>
      )}
    </div>

    {/* 20-rules slide-over: cross-check every SPEC_SECTION_ORDER section's met/not-met status */}
    {readiness && (
      <div className={`fixed inset-0 z-[110] ${rulesOpen ? "" : "pointer-events-none"}`} aria-hidden={!rulesOpen}>
        <div
          className={`absolute inset-0 bg-slate-900/30 transition-opacity duration-300 ${rulesOpen ? "opacity-100" : "opacity-0"}`}
          onClick={() => setRulesOpen(false)}
        />
        <div
          className={`absolute right-0 top-0 h-full w-full max-w-md bg-white shadow-2xl border-l border-slate-200 transition-transform duration-300 ease-out flex flex-col ${rulesOpen ? "translate-x-0" : "translate-x-full"}`}
        >
          <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 shrink-0">
            <div>
              <h2 className="text-sm font-semibold text-slate-900">Specification Rules Checklist</h2>
              <p className="text-xs text-slate-500 mt-0.5">
                {readiness.filled_count}/{readiness.total_count} sections filled · {readiness.completeness_pct}% complete
              </p>
            </div>
            <button
              onClick={() => setRulesOpen(false)}
              className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-50 hover:text-slate-600 transition-colors"
              aria-label="Close"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
          <div className="flex-1 overflow-y-auto px-5 py-3">
            {(spec.spec?.section_order || []).map((key, i) => {
              const status = readiness.section_status?.[key] || "empty";
              const isFilled = status === "filled";
              const isMandatory = MANDATORY_SECTIONS.includes(key);
              const title = spec.spec?.section_titles?.[key] || key;
              return (
                <div
                  key={key}
                  className="flex items-center gap-3 py-2.5 border-b border-slate-50 last:border-0 animate-fade-in"
                  style={{ animationDelay: `${i * 25}ms` }}
                >
                  <span className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 ${isFilled ? "bg-emerald-100 text-emerald-600" : isMandatory ? "bg-red-100 text-red-600" : "bg-slate-100 text-slate-400"}`}>
                    {isFilled ? (
                      <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M20 6L9 17l-5-5" />
                      </svg>
                    ) : (
                      <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v5M12 16h.01" />
                      </svg>
                    )}
                  </span>
                  <span className="text-sm text-slate-700 flex-1 min-w-0 truncate">{title}</span>
                  {isMandatory && (
                    <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider shrink-0">Required</span>
                  )}
                </div>
              );
            })}
            {readiness.blocking_issues.length > 0 && (
              <div className="mt-4 rounded-lg bg-red-50 border border-red-200 p-3">
                <div className="text-xs font-semibold text-red-700 mb-1">Blocking issues</div>
                {readiness.blocking_issues.map((issue) => (
                  <div key={issue} className="text-xs text-red-600">{issue}</div>
                ))}
              </div>
            )}
            {readiness.warnings.length > 0 && (
              <div className="mt-3 rounded-lg bg-amber-50 border border-amber-200 p-3">
                <div className="text-xs font-semibold text-amber-700 mb-1">Warnings</div>
                {readiness.warnings.map((warn) => (
                  <div key={warn} className="text-xs text-amber-700">{warn}</div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    )}

    {/* Enhance-the-briefing / Reanalyze modal: edit or add to the brief text, then
     * re-run the full GPT interpretation from scratch (locked/approved sections kept). */}
    {reanalyzeOpen && (
      <div className="fixed inset-0 z-[120] flex items-center justify-center p-4">
        <div className="absolute inset-0 bg-slate-900/40" onClick={() => !reanalyzing && setReanalyzeOpen(false)} />
        <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-2xl border border-slate-200 animate-fade-in">
          <div className="px-5 pt-5 pb-3 border-b border-slate-100">
            <h2 className="text-sm font-semibold text-slate-900">Not happy with this briefing?</h2>
            <p className="text-xs text-slate-500 mt-1">
              Edit or add details below to enhance the brief, then reanalyze. Approved or locked sections are kept.
            </p>
          </div>
          <div className="px-5 py-4">
            <textarea
              value={reanalyzeText}
              onChange={(e) => setReanalyzeText(e.target.value)}
              rows={10}
              placeholder="Paste or edit the brief text here..."
              className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm text-slate-800 bg-white focus:outline-none focus:ring-2 focus:ring-[#5B2C9D]/20 focus:border-[#5B2C9D]/40 resize-y"
            />
          </div>
          <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-slate-100">
            <button
              onClick={() => setReanalyzeOpen(false)}
              disabled={reanalyzing}
              className="px-4 py-2 text-sm font-medium text-slate-500 hover:text-slate-700 transition-colors disabled:opacity-40"
            >
              Cancel
            </button>
            <button
              onClick={handleReanalyze}
              disabled={reanalyzing || !reanalyzeText.trim()}
              className="px-4 py-2 text-sm font-medium text-white rounded-lg shadow-sm transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ backgroundColor: "#5B2C9D" }}
            >
              {reanalyzing ? "Starting..." : "Reanalyze"}
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  );
}

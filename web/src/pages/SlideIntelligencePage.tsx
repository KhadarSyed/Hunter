import { useState, useEffect, useCallback } from "react";
import { intelApi } from "../lib/intel-api";
import type {
  SIDashboard,
  SISlide,
  SIPresentation,
  SITemplateFamily,
  SIDetectedProject,
} from "../data/contracts";

// ─── Constants ─────────────────────────────────────────────────────────────

const TABS = ["Library", "Templates", "Detected Projects", "Search", "Storyline Matching"] as const;
type Tab = (typeof TABS)[number];

const PURPOSE_OPTIONS = [
  "title", "agenda", "divider", "content", "data", "comparison",
  "timeline", "process", "summary", "appendix", "thank_you", "blank",
];

const LAYOUT_OPTIONS = [
  "full_bleed", "two_column", "three_column", "title_only",
  "title_content", "content_only", "image_focused", "chart_focused",
  "table_focused", "mixed",
];

const VISUAL_TYPE_OPTIONS = [
  "bar_chart", "line_chart", "pie_chart", "scatter_plot", "table",
  "infographic", "image", "icon_grid", "diagram", "map", "none",
];

const NARRATIVE_ROLE_OPTIONS = [
  "setup", "evidence", "analysis", "insight", "recommendation",
  "transition", "conclusion", "context",
];

const REPORT_TYPE_OPTIONS = [
  "brand_health", "campaign_analysis", "audience_insight",
  "competitive_landscape", "trend_report", "crisis_analysis",
  "media_analysis", "custom",
];

const PURPOSE_COLORS: Record<string, string> = {
  title: "text-indigo-700 bg-indigo-50 border-indigo-200",
  agenda: "text-blue-700 bg-blue-50 border-blue-200",
  divider: "text-slate-600 bg-slate-100 border-slate-200",
  content: "text-emerald-700 bg-emerald-50 border-emerald-200",
  data: "text-purple-700 bg-purple-50 border-purple-200",
  comparison: "text-orange-700 bg-orange-50 border-orange-200",
  timeline: "text-cyan-700 bg-cyan-50 border-cyan-200",
  process: "text-teal-700 bg-teal-50 border-teal-200",
  summary: "text-amber-700 bg-amber-50 border-amber-200",
  appendix: "text-rose-700 bg-rose-50 border-rose-200",
  thank_you: "text-pink-700 bg-pink-50 border-pink-200",
  blank: "text-slate-400 bg-slate-50 border-slate-200",
};

const LAYOUT_COLORS: Record<string, string> = {
  full_bleed: "text-violet-700 bg-violet-50 border-violet-200",
  two_column: "text-blue-700 bg-blue-50 border-blue-200",
  three_column: "text-indigo-700 bg-indigo-50 border-indigo-200",
  title_only: "text-slate-600 bg-slate-100 border-slate-200",
  title_content: "text-emerald-700 bg-emerald-50 border-emerald-200",
  content_only: "text-teal-700 bg-teal-50 border-teal-200",
  image_focused: "text-orange-700 bg-orange-50 border-orange-200",
  chart_focused: "text-purple-700 bg-purple-50 border-purple-200",
  table_focused: "text-cyan-700 bg-cyan-50 border-cyan-200",
  mixed: "text-amber-700 bg-amber-50 border-amber-200",
};

function formatDateTime(ts: number | null | undefined): string {
  if (!ts) return "--";
  const d = new Date(ts < 1e12 ? ts * 1000 : ts);
  if (isNaN(d.getTime())) return "--";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ─── Icons ─────────────────────────────────────────────────────────────────

const ip = {
  width: 14,
  height: 14,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

const CloseIcon = () => (
  <svg {...ip}>
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

const ChartIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="18" y="3" width="4" height="18" />
    <rect x="10" y="8" width="4" height="13" />
    <rect x="2" y="13" width="4" height="8" />
  </svg>
);

const TableIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <line x1="3" y1="9" x2="21" y2="9" />
    <line x1="3" y1="15" x2="21" y2="15" />
    <line x1="9" y1="3" x2="9" y2="21" />
  </svg>
);

const ImageIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <circle cx="8.5" cy="8.5" r="1.5" />
    <polyline points="21 15 16 10 5 21" />
  </svg>
);

const ShapeIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5 12 2" />
  </svg>
);

const SearchIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" />
    <line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);

// ─── Shared UI ─────────────────────────────────────────────────────────────

function Badge({ label, colors }: { label: string; colors: string }) {
  return (
    <span
      className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded border whitespace-nowrap ${colors}`}
    >
      {label.replace(/_/g, " ")}
    </span>
  );
}

function MetricCard({
  label,
  value,
  dot,
}: {
  label: string;
  value: number | string;
  dot: string;
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-3.5 shadow-sm">
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className={`w-2 h-2 rounded-full shrink-0 ${dot}`} />
        <span className="text-[9px] text-slate-400 font-semibold uppercase tracking-wide leading-tight">
          {label}
        </span>
      </div>
      <div className="text-xl font-bold text-slate-900 tabular-nums">{value}</div>
    </div>
  );
}

function ConfidenceBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, score * 100));
  const color =
    pct >= 70
      ? "from-emerald-500 to-emerald-400"
      : pct >= 40
        ? "from-amber-500 to-yellow-400"
        : "from-red-500 to-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 bg-slate-100 rounded-full overflow-hidden">
        <div
          className={`h-full bg-gradient-to-r ${color} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[11px] tabular-nums text-slate-500 w-8 text-right">
        {Math.round(pct)}%
      </span>
    </div>
  );
}

function SectionHeader({ title, count }: { title: string; count?: number }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest">
        {title}
      </div>
      {count !== undefined && (
        <span className="text-[10px] text-slate-400 font-medium tabular-nums">
          {count} items
        </span>
      )}
      <div className="flex-1 border-t border-slate-200" />
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="border border-slate-200 rounded-lg px-2.5 py-1.5 text-[11px] text-slate-600 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
    >
      <option value="">All {label}</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {o.replace(/_/g, " ")}
        </option>
      ))}
    </select>
  );
}

// ─── Slide Detail Drawer ──────────────────────────────────────────────────

function SlideDrawer({
  slide,
  busy,
  onClose,
  onExcludeToggle,
  onReprocess,
  onUpdateMetadata,
}: {
  slide: SISlide | null;
  busy: boolean;
  onClose: () => void;
  onExcludeToggle: () => void;
  onReprocess: () => void;
  onUpdateMetadata: (updates: Record<string, string>) => void;
}) {
  const [editPurpose, setEditPurpose] = useState("");
  const [editLayout, setEditLayout] = useState("");
  const [editVisual, setEditVisual] = useState("");
  const [editNarrative, setEditNarrative] = useState("");
  const [editReportType, setEditReportType] = useState("");

  useEffect(() => {
    if (slide) {
      setEditPurpose(slide.slide_purpose || "");
      setEditLayout(slide.layout_type || "");
      setEditVisual(slide.visual_type || "");
      setEditNarrative(slide.narrative_role || "");
      setEditReportType(slide.report_type || "");
    }
  }, [slide]);

  if (!slide) return null;

  const handleSave = () => {
    const updates: Record<string, string> = {};
    if (editPurpose !== (slide.slide_purpose || "")) updates.slide_purpose = editPurpose;
    if (editLayout !== (slide.layout_type || "")) updates.layout_type = editLayout;
    if (editVisual !== (slide.visual_type || "")) updates.visual_type = editVisual;
    if (editNarrative !== (slide.narrative_role || "")) updates.narrative_role = editNarrative;
    if (editReportType !== (slide.report_type || "")) updates.report_type = editReportType;
    if (Object.keys(updates).length > 0) {
      onUpdateMetadata(updates);
    }
  };

  return (
    <>
      <div className="fixed inset-0 bg-slate-900/30 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 h-full w-full sm:w-[560px] bg-white shadow-2xl z-50 overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-slate-200 px-5 py-4 flex items-center justify-between z-10">
          <div>
            <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-1">
              Slide Detail
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold text-slate-900">
                Slide #{slide.slide_number}
              </span>
              {slide.is_excluded && (
                <Badge label="Excluded" colors="text-red-700 bg-red-50 border-red-200" />
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
          >
            <CloseIcon />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/* Title & Classification */}
          <div>
            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
              Title
            </div>
            <p className="text-[13px] text-slate-800 font-medium">
              {slide.title_text || "(No title)"}
            </p>
          </div>

          {/* Badges row */}
          <div className="flex flex-wrap gap-1.5">
            {slide.slide_purpose && (
              <Badge
                label={slide.slide_purpose}
                colors={PURPOSE_COLORS[slide.slide_purpose] || "text-slate-600 bg-slate-100 border-slate-200"}
              />
            )}
            {slide.layout_type && (
              <Badge
                label={slide.layout_type}
                colors={LAYOUT_COLORS[slide.layout_type] || "text-slate-600 bg-slate-100 border-slate-200"}
              />
            )}
            {slide.visual_type && (
              <Badge label={slide.visual_type} colors="text-purple-700 bg-purple-50 border-purple-200" />
            )}
            {slide.narrative_role && (
              <Badge label={slide.narrative_role} colors="text-teal-700 bg-teal-50 border-teal-200" />
            )}
          </div>

          {/* Confidence */}
          {slide.classification_confidence != null && (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
                Classification Confidence
              </div>
              <ConfidenceBar score={slide.classification_confidence} />
            </div>
          )}

          {/* Metadata grid */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-[10px] text-slate-400 font-medium mb-0.5">Client</div>
              <div className="text-[12px] text-slate-700">{slide.client || "--"}</div>
            </div>
            <div>
              <div className="text-[10px] text-slate-400 font-medium mb-0.5">Brand</div>
              <div className="text-[12px] text-slate-700">{slide.brand || "--"}</div>
            </div>
            <div>
              <div className="text-[10px] text-slate-400 font-medium mb-0.5">Industry</div>
              <div className="text-[12px] text-slate-700">{slide.industry || "--"}</div>
            </div>
            <div>
              <div className="text-[10px] text-slate-400 font-medium mb-0.5">Report Type</div>
              <div className="text-[12px] text-slate-700">{slide.report_type?.replace(/_/g, " ") || "--"}</div>
            </div>
            <div>
              <div className="text-[10px] text-slate-400 font-medium mb-0.5">Data Density</div>
              <div className="text-[12px] text-slate-700">{slide.data_density || "--"}</div>
            </div>
            <div>
              <div className="text-[10px] text-slate-400 font-medium mb-0.5">Exec Suitability</div>
              <div className="text-[12px] text-slate-700">{slide.executive_suitability || "--"}</div>
            </div>
            <div>
              <div className="text-[10px] text-slate-400 font-medium mb-0.5">Visual Complexity</div>
              <div className="text-[12px] text-slate-700">{slide.visual_complexity || "--"}</div>
            </div>
            <div>
              <div className="text-[10px] text-slate-400 font-medium mb-0.5">Status</div>
              <div className="text-[12px] text-slate-700">{slide.status}</div>
            </div>
          </div>

          {/* Element counts */}
          <div>
            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
              Element Counts
            </div>
            <div className="flex gap-4 text-[11px] text-slate-600">
              <span className="flex items-center gap-1"><ShapeIcon /> {slide.shape_count} shapes</span>
              <span className="flex items-center gap-1"><ChartIcon /> {slide.chart_count} charts</span>
              <span className="flex items-center gap-1"><TableIcon /> {slide.table_count} tables</span>
              <span className="flex items-center gap-1"><ImageIcon /> {slide.image_count} images</span>
            </div>
          </div>

          {/* Body text */}
          {slide.body_text && (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
                Body Text
              </div>
              <p className="text-[12px] text-slate-600 leading-relaxed bg-slate-50 rounded-lg p-3 whitespace-pre-wrap max-h-40 overflow-y-auto">
                {slide.body_text}
              </p>
            </div>
          )}

          {/* Footer text */}
          {slide.footer_text && (
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
                Footer Text
              </div>
              <p className="text-[12px] text-slate-500 italic">{slide.footer_text}</p>
            </div>
          )}

          {/* Edit Metadata */}
          <div>
            <SectionHeader title="Edit Metadata" />
            <div className="space-y-2.5">
              <div>
                <label className="text-[10px] text-slate-400 font-medium mb-0.5 block">Purpose</label>
                <select value={editPurpose} onChange={(e) => setEditPurpose(e.target.value)} className="w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-[12px] text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20">
                  <option value="">-- Select --</option>
                  {PURPOSE_OPTIONS.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-400 font-medium mb-0.5 block">Layout</label>
                <select value={editLayout} onChange={(e) => setEditLayout(e.target.value)} className="w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-[12px] text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20">
                  <option value="">-- Select --</option>
                  {LAYOUT_OPTIONS.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-400 font-medium mb-0.5 block">Visual Type</label>
                <select value={editVisual} onChange={(e) => setEditVisual(e.target.value)} className="w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-[12px] text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20">
                  <option value="">-- Select --</option>
                  {VISUAL_TYPE_OPTIONS.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-400 font-medium mb-0.5 block">Narrative Role</label>
                <select value={editNarrative} onChange={(e) => setEditNarrative(e.target.value)} className="w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-[12px] text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20">
                  <option value="">-- Select --</option>
                  {NARRATIVE_ROLE_OPTIONS.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-400 font-medium mb-0.5 block">Report Type</label>
                <select value={editReportType} onChange={(e) => setEditReportType(e.target.value)} className="w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-[12px] text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20">
                  <option value="">-- Select --</option>
                  {REPORT_TYPE_OPTIONS.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
                </select>
              </div>
              <button
                onClick={handleSave}
                disabled={busy}
                className="px-4 py-1.5 bg-blue-600 text-white text-[11px] font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                Save Changes
              </button>
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-2 pt-2 border-t border-slate-200">
            <button
              onClick={onExcludeToggle}
              disabled={busy}
              className={`px-3 py-1.5 text-[11px] font-semibold rounded-lg border transition-colors disabled:opacity-50 ${
                slide.is_excluded
                  ? "border-emerald-300 text-emerald-700 hover:bg-emerald-50"
                  : "border-red-300 text-red-700 hover:bg-red-50"
              }`}
            >
              {slide.is_excluded ? "Include Slide" : "Exclude Slide"}
            </button>
            <button
              onClick={onReprocess}
              disabled={busy}
              className="px-3 py-1.5 text-[11px] font-semibold rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors"
            >
              Reprocess
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

// ─── Library Tab ──────────────────────────────────────────────────────────

function LibraryTab({
  slides,
  loading,
  presentations,
  dashboard,
  onRefresh,
}: {
  slides: SISlide[];
  loading: boolean;
  presentations: SIPresentation[];
  dashboard: SIDashboard | null;
  onRefresh: () => void;
}) {
  const [purposeFilter, setPurposeFilter] = useState("");
  const [layoutFilter, setLayoutFilter] = useState("");
  const [clientFilter, setClientFilter] = useState("");
  const [searchText, setSearchText] = useState("");
  const [selectedSlide, setSelectedSlide] = useState<SISlide | null>(null);
  const [busy, setBusy] = useState(false);
  const [ingestPath, setIngestPath] = useState("");
  const [ingestStatus, setIngestStatus] = useState<string | null>(null);

  const clients = dashboard?.client_distribution ? Object.keys(dashboard.client_distribution) : [];

  const filtered = slides.filter((s) => {
    if (purposeFilter && s.slide_purpose !== purposeFilter) return false;
    if (layoutFilter && s.layout_type !== layoutFilter) return false;
    if (clientFilter && s.client !== clientFilter) return false;
    if (searchText) {
      const q = searchText.toLowerCase();
      const haystack = `${s.title_text || ""} ${s.body_text || ""} ${s.client || ""}`.toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  });

  const handleIngest = async () => {
    if (!ingestPath.trim()) return;
    setIngestStatus("Ingesting...");
    try {
      await intelApi.siIngest(ingestPath.trim());
      setIngestStatus("Ingestion started successfully");
      setIngestPath("");
      setTimeout(() => { setIngestStatus(null); onRefresh(); }, 2000);
    } catch (e: any) {
      setIngestStatus(`Error: ${e.message}`);
    }
  };

  const handleExcludeToggle = async () => {
    if (!selectedSlide) return;
    setBusy(true);
    try {
      if (selectedSlide.is_excluded) {
        await intelApi.siIncludeSlide(selectedSlide.id);
      } else {
        await intelApi.siExcludeSlide(selectedSlide.id);
      }
      setSelectedSlide({ ...selectedSlide, is_excluded: !selectedSlide.is_excluded });
      onRefresh();
    } catch {
    } finally {
      setBusy(false);
    }
  };

  const handleReprocess = async () => {
    if (!selectedSlide) return;
    setBusy(true);
    try {
      await intelApi.siReprocessSlide(selectedSlide.id);
      onRefresh();
    } catch {
    } finally {
      setBusy(false);
    }
  };

  const handleUpdateMetadata = async (updates: Record<string, string>) => {
    if (!selectedSlide) return;
    setBusy(true);
    try {
      await intelApi.siUpdateMetadata(selectedSlide.id, updates);
      setSelectedSlide({ ...selectedSlide, ...updates } as SISlide);
      onRefresh();
    } catch {
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Ingest section */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
        <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-2">
          Ingest Presentation
        </div>
        <div className="flex gap-2 items-center">
          <input
            type="text"
            value={ingestPath}
            onChange={(e) => setIngestPath(e.target.value)}
            placeholder="Enter file path (e.g. /path/to/presentation.pptx)"
            className="flex-1 border border-slate-200 rounded-lg px-3 py-1.5 text-[12px] text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
          />
          <button
            onClick={handleIngest}
            disabled={!ingestPath.trim()}
            className="px-4 py-1.5 bg-blue-600 text-white text-[11px] font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors whitespace-nowrap"
          >
            Ingest Presentation
          </button>
        </div>
        {ingestStatus && (
          <div className={`mt-2 text-[11px] ${ingestStatus.startsWith("Error") ? "text-red-600" : "text-emerald-600"}`}>
            {ingestStatus}
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <FilterSelect label="Purpose" value={purposeFilter} onChange={setPurposeFilter} options={PURPOSE_OPTIONS} />
        <FilterSelect label="Layout" value={layoutFilter} onChange={setLayoutFilter} options={LAYOUT_OPTIONS} />
        <FilterSelect label="Client" value={clientFilter} onChange={setClientFilter} options={clients} />
        <div className="relative">
          <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400">
            <SearchIcon />
          </span>
          <input
            type="text"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Search slides..."
            className="pl-8 pr-3 py-1.5 border border-slate-200 rounded-lg text-[11px] text-slate-600 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 w-48"
          />
        </div>
        <span className="text-[11px] text-slate-400 ml-auto tabular-nums">
          {filtered.length} of {slides.length} slides
        </span>
      </div>

      {/* Slide Grid */}
      {loading ? (
        <div className="text-[12px] text-slate-400 py-8 text-center">Loading slides...</div>
      ) : filtered.length === 0 ? (
        <div className="text-[12px] text-slate-400 py-8 text-center">No slides found</div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {filtered.map((s) => (
            <button
              key={s.id}
              onClick={() => setSelectedSlide(s)}
              className={`text-left bg-white border rounded-xl p-3.5 shadow-sm hover:shadow-md hover:border-blue-300 transition-all ${
                s.is_excluded ? "border-red-200 opacity-60" : "border-slate-200"
              }`}
            >
              {/* Header with slide number */}
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold text-white bg-blue-600 w-6 h-6 rounded-md flex items-center justify-center tabular-nums">
                  {s.slide_number}
                </span>
                {s.is_excluded && (
                  <span className="text-[9px] text-red-500 font-semibold uppercase">Excluded</span>
                )}
              </div>

              {/* Title */}
              <div className="text-[12px] font-medium text-slate-800 leading-snug mb-2 line-clamp-2 min-h-[2.5em]">
                {s.title_text || "(No title)"}
              </div>

              {/* Badges */}
              <div className="flex flex-wrap gap-1 mb-2">
                {s.slide_purpose && (
                  <Badge
                    label={s.slide_purpose}
                    colors={PURPOSE_COLORS[s.slide_purpose] || "text-slate-600 bg-slate-100 border-slate-200"}
                  />
                )}
                {s.layout_type && (
                  <Badge
                    label={s.layout_type}
                    colors={LAYOUT_COLORS[s.layout_type] || "text-slate-600 bg-slate-100 border-slate-200"}
                  />
                )}
                {s.visual_type && (
                  <Badge label={s.visual_type} colors="text-purple-700 bg-purple-50 border-purple-200" />
                )}
              </div>

              {/* Client */}
              {s.client && (
                <div className="text-[10px] text-slate-500 mb-2 truncate">
                  {s.client}
                </div>
              )}

              {/* Confidence */}
              {s.classification_confidence != null && (
                <div className="mb-2">
                  <ConfidenceBar score={s.classification_confidence} />
                </div>
              )}

              {/* Counts */}
              <div className="flex gap-3 text-[10px] text-slate-400">
                {s.shape_count > 0 && (
                  <span className="flex items-center gap-0.5" title="Shapes"><ShapeIcon /> {s.shape_count}</span>
                )}
                {s.chart_count > 0 && (
                  <span className="flex items-center gap-0.5" title="Charts"><ChartIcon /> {s.chart_count}</span>
                )}
                {s.table_count > 0 && (
                  <span className="flex items-center gap-0.5" title="Tables"><TableIcon /> {s.table_count}</span>
                )}
                {s.image_count > 0 && (
                  <span className="flex items-center gap-0.5" title="Images"><ImageIcon /> {s.image_count}</span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}

      {/* Drawer */}
      {selectedSlide && (
        <SlideDrawer
          slide={selectedSlide}
          busy={busy}
          onClose={() => setSelectedSlide(null)}
          onExcludeToggle={handleExcludeToggle}
          onReprocess={handleReprocess}
          onUpdateMetadata={handleUpdateMetadata}
        />
      )}
    </div>
  );
}

// ─── Templates Tab ────────────────────────────────────────────────────────

function TemplatesTab() {
  const [templates, setTemplates] = useState<SITemplateFamily[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [expandedMembers, setExpandedMembers] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await intelApi.siTemplates();
      setTemplates(data);
    } catch {
      setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleApprove = async (id: number) => {
    setBusy(true);
    try {
      await intelApi.siApproveTemplate(id);
      load();
    } catch {
    } finally {
      setBusy(false);
    }
  };

  const handleExpand = async (id: number) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    try {
      const detail = await intelApi.siTemplate(id);
      setExpandedMembers(detail?.members || detail?.slides || []);
      setExpandedId(id);
    } catch {
      setExpandedMembers([]);
      setExpandedId(id);
    }
  };

  if (loading) return <div className="text-[12px] text-slate-400 py-8 text-center">Loading templates...</div>;

  return (
    <div className="space-y-4">
      <SectionHeader title="Template Families" count={templates.length} />
      {templates.length === 0 ? (
        <div className="text-[12px] text-slate-400 py-8 text-center">No template families found</div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {templates.map((t) => (
            <div key={t.id} className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
              <div className="p-4">
                <div className="flex items-start justify-between mb-2">
                  <h4 className="text-[13px] font-bold text-slate-900 leading-snug">{t.family_name}</h4>
                  {t.is_approved && (
                    <Badge label="Approved" colors="text-emerald-700 bg-emerald-50 border-emerald-200" />
                  )}
                </div>
                <div className="space-y-1.5 mb-3">
                  {t.typical_layout && (
                    <div className="text-[11px] text-slate-500">
                      <span className="text-slate-400 font-medium">Layout:</span> {t.typical_layout.replace(/_/g, " ")}
                    </div>
                  )}
                  {t.typical_visual && (
                    <div className="text-[11px] text-slate-500">
                      <span className="text-slate-400 font-medium">Visual:</span> {t.typical_visual.replace(/_/g, " ")}
                    </div>
                  )}
                  {t.typical_purpose && (
                    <div className="text-[11px] text-slate-500">
                      <span className="text-slate-400 font-medium">Purpose:</span> {t.typical_purpose.replace(/_/g, " ")}
                    </div>
                  )}
                  {t.recommended_usage && (
                    <div className="text-[11px] text-slate-500">
                      <span className="text-slate-400 font-medium">Usage:</span> {t.recommended_usage}
                    </div>
                  )}
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-slate-400 tabular-nums">{t.member_count} members</span>
                  <div className="flex gap-1.5">
                    <button
                      onClick={() => handleExpand(t.id)}
                      className="px-2.5 py-1 text-[10px] font-semibold rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors"
                    >
                      {expandedId === t.id ? "Collapse" : "View Members"}
                    </button>
                    {!t.is_approved && (
                      <button
                        onClick={() => handleApprove(t.id)}
                        disabled={busy}
                        className="px-2.5 py-1 text-[10px] font-semibold rounded-md bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 transition-colors"
                      >
                        Approve
                      </button>
                    )}
                  </div>
                </div>
              </div>
              {expandedId === t.id && (
                <div className="border-t border-slate-200 bg-slate-50/50 p-3 max-h-60 overflow-y-auto">
                  {expandedMembers.length === 0 ? (
                    <div className="text-[11px] text-slate-400">No member slides loaded</div>
                  ) : (
                    <div className="space-y-1.5">
                      {expandedMembers.map((m: any, i: number) => (
                        <div key={i} className="bg-white rounded-lg p-2.5 border border-slate-200 text-[11px]">
                          <span className="font-medium text-slate-700">Slide #{m.slide_number || i + 1}</span>
                          {m.title_text && <span className="text-slate-500 ml-2">{m.title_text}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Detected Projects Tab ───────────────────────────────────────────────

function DetectedProjectsTab({ presentations }: { presentations: SIPresentation[] }) {
  const [selectedPresId, setSelectedPresId] = useState<number | null>(null);
  const [projects, setProjects] = useState<SIDetectedProject[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (selectedPresId == null) {
      setProjects([]);
      return;
    }
    setLoading(true);
    intelApi
      .siDetectedProjects(selectedPresId)
      .then((data) => setProjects(data))
      .catch(() => setProjects([]))
      .finally(() => setLoading(false));
  }, [selectedPresId]);

  return (
    <div className="space-y-4">
      <SectionHeader title="Detected Projects" />
      <div className="flex items-center gap-3">
        <label className="text-[11px] text-slate-500 font-medium">Select Presentation:</label>
        <select
          value={selectedPresId ?? ""}
          onChange={(e) => setSelectedPresId(e.target.value ? Number(e.target.value) : null)}
          className="border border-slate-200 rounded-lg px-2.5 py-1.5 text-[11px] text-slate-600 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 min-w-[250px]"
        >
          <option value="">-- Select a presentation --</option>
          {presentations.map((p) => (
            <option key={p.id} value={p.id}>
              {p.filename} ({p.slide_count} slides)
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="text-[12px] text-slate-400 py-8 text-center">Loading detected projects...</div>
      ) : selectedPresId == null ? (
        <div className="text-[12px] text-slate-400 py-8 text-center">Select a presentation to view detected projects</div>
      ) : projects.length === 0 ? (
        <div className="text-[12px] text-slate-400 py-8 text-center">No projects detected in this presentation</div>
      ) : (
        <div className="space-y-3">
          {projects.map((p) => (
            <div key={p.id} className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h4 className="text-[13px] font-bold text-slate-900">{p.project_name || "Unnamed Project"}</h4>
                  <div className="flex gap-3 mt-1 text-[11px] text-slate-500">
                    {p.client_name && <span>Client: <strong className="text-slate-700">{p.client_name}</strong></span>}
                    {p.brand_name && <span>Brand: <strong className="text-slate-700">{p.brand_name}</strong></span>}
                    {p.analyst_name && <span>Analyst: <strong className="text-slate-700">{p.analyst_name}</strong></span>}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] text-slate-400 font-medium mb-0.5">Confidence</div>
                  <div className="w-24">
                    <ConfidenceBar score={p.confidence} />
                  </div>
                </div>
              </div>
              <div className="flex gap-4 text-[11px] text-slate-500">
                <span>Slides {p.start_slide} - {p.end_slide}</span>
                <span>{p.slide_count} slides</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Search Tab ──────────────────────────────────────────────────────────

function SearchTab() {
  const [query, setQuery] = useState("");
  const [purposeFilter, setPurposeFilter] = useState("");
  const [layoutFilter, setLayoutFilter] = useState("");
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setHasSearched(true);
    try {
      const filters: Record<string, any> = {};
      if (purposeFilter) filters.slide_purpose = purposeFilter;
      if (layoutFilter) filters.layout_type = layoutFilter;
      const data = await intelApi.siSearch(query, Object.keys(filters).length > 0 ? filters : undefined);
      setResults(data?.results || data || []);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <SectionHeader title="Search Slide Library" />
      <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm space-y-3">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400">
              <SearchIcon />
            </span>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="Search by content, title, or description..."
              className="w-full pl-8 pr-3 py-2 border border-slate-200 rounded-lg text-[12px] text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={!query.trim() || loading}
            className="px-4 py-2 bg-blue-600 text-white text-[11px] font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            Search
          </button>
        </div>
        <div className="flex gap-2">
          <FilterSelect label="Purpose" value={purposeFilter} onChange={setPurposeFilter} options={PURPOSE_OPTIONS} />
          <FilterSelect label="Layout" value={layoutFilter} onChange={setLayoutFilter} options={LAYOUT_OPTIONS} />
        </div>
      </div>

      {loading ? (
        <div className="text-[12px] text-slate-400 py-8 text-center">Searching...</div>
      ) : !hasSearched ? (
        <div className="text-[12px] text-slate-400 py-8 text-center">Enter a search query to find matching slides</div>
      ) : results.length === 0 ? (
        <div className="text-[12px] text-slate-400 py-8 text-center">No results found</div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {results.map((r: any, i: number) => (
            <div key={r.id || i} className="bg-white border border-slate-200 rounded-xl p-3.5 shadow-sm">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[10px] font-bold text-white bg-blue-600 w-6 h-6 rounded-md flex items-center justify-center tabular-nums">
                  {r.slide_number || "?"}
                </span>
                {r.similarity_score != null && (
                  <span className="text-[10px] text-slate-400 tabular-nums ml-auto">
                    {Math.round(r.similarity_score * 100)}% match
                  </span>
                )}
              </div>
              <div className="text-[12px] font-medium text-slate-800 leading-snug mb-2 line-clamp-2">
                {r.title_text || "(No title)"}
              </div>
              <div className="flex flex-wrap gap-1 mb-2">
                {r.slide_purpose && (
                  <Badge
                    label={r.slide_purpose}
                    colors={PURPOSE_COLORS[r.slide_purpose] || "text-slate-600 bg-slate-100 border-slate-200"}
                  />
                )}
                {r.layout_type && (
                  <Badge
                    label={r.layout_type}
                    colors={LAYOUT_COLORS[r.layout_type] || "text-slate-600 bg-slate-100 border-slate-200"}
                  />
                )}
              </div>
              {r.client && <div className="text-[10px] text-slate-500">{r.client}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Storyline Matching Tab ──────────────────────────────────────────────

function StorylineMatchingTab() {
  const [storylineId, setStorylineId] = useState("");
  const [matchResults, setMatchResults] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleMatch = async () => {
    const id = Number(storylineId);
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      await intelApi.siMatchStoryline(id);
      const data = await intelApi.siStorylineMatches(id);
      setMatchResults(data);
    } catch (e: any) {
      setError(e.message || "Failed to match storyline");
      setMatchResults(null);
    } finally {
      setLoading(false);
    }
  };

  const matches: any[] = matchResults?.matches || matchResults?.nodes || (Array.isArray(matchResults) ? matchResults : []);

  // Group matches by node_id
  const nodeGroups: Record<number, any[]> = {};
  for (const m of matches) {
    const nodeId = m.node_id || 0;
    if (!nodeGroups[nodeId]) nodeGroups[nodeId] = [];
    nodeGroups[nodeId].push(m);
  }

  return (
    <div className="space-y-4">
      <SectionHeader title="Storyline Matching" />
      <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
        <div className="text-[11px] text-slate-500 mb-2">
          Match an existing storyline against the historical slide library to find relevant reference slides for each node.
        </div>
        <div className="flex gap-2 items-center">
          <input
            type="number"
            value={storylineId}
            onChange={(e) => setStorylineId(e.target.value)}
            placeholder="Enter storyline ID"
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-[12px] text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 w-48"
          />
          <button
            onClick={handleMatch}
            disabled={!storylineId || loading}
            className="px-4 py-1.5 bg-blue-600 text-white text-[11px] font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            Match Storyline
          </button>
        </div>
        {error && <div className="mt-2 text-[11px] text-red-600">{error}</div>}
      </div>

      {loading ? (
        <div className="text-[12px] text-slate-400 py-8 text-center">Matching storyline...</div>
      ) : matches.length === 0 && matchResults != null ? (
        <div className="text-[12px] text-slate-400 py-8 text-center">No matches found</div>
      ) : Object.keys(nodeGroups).length > 0 ? (
        <div className="space-y-4">
          {Object.entries(nodeGroups).map(([nodeId, nodeMatches]) => (
            <div key={nodeId} className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/50">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-bold text-white bg-blue-600 w-6 h-6 rounded-md flex items-center justify-center tabular-nums">
                    {nodeId}
                  </span>
                  <span className="text-[12px] font-semibold text-slate-800">
                    Node {nodeId}
                  </span>
                  {nodeMatches[0]?.section_type && (
                    <Badge label={nodeMatches[0].section_type} colors="text-indigo-700 bg-indigo-50 border-indigo-200" />
                  )}
                  <span className="text-[10px] text-slate-400 ml-auto tabular-nums">
                    {nodeMatches.length} matches
                  </span>
                </div>
              </div>
              <div className="divide-y divide-slate-100">
                {nodeMatches.map((m: any, i: number) => (
                  <div key={i} className="p-3.5">
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] font-medium text-slate-700">
                          Slide #{m.slide_number || m.slide_id}
                        </span>
                        {m.title_text && (
                          <span className="text-[11px] text-slate-500 truncate max-w-[200px]">
                            {m.title_text}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        {m.similarity_score != null && (
                          <span className="text-[10px] font-semibold tabular-nums text-blue-600">
                            {Math.round(m.similarity_score * 100)}% similar
                          </span>
                        )}
                        {m.confidence != null && (
                          <div className="w-16">
                            <ConfidenceBar score={m.confidence} />
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-1 mb-2">
                      {m.slide_purpose && (
                        <Badge label={m.slide_purpose} colors={PURPOSE_COLORS[m.slide_purpose] || "text-slate-600 bg-slate-100 border-slate-200"} />
                      )}
                      {m.layout_type && (
                        <Badge label={m.layout_type} colors={LAYOUT_COLORS[m.layout_type] || "text-slate-600 bg-slate-100 border-slate-200"} />
                      )}
                      {m.client && <Badge label={m.client} colors="text-slate-600 bg-slate-100 border-slate-200" />}
                    </div>

                    {m.match_reason && (
                      <div className="text-[11px] text-slate-500 mb-2">
                        <span className="text-slate-400 font-medium">Reason:</span> {m.match_reason}
                      </div>
                    )}

                    {m.recommended_elements && m.recommended_elements.length > 0 && (
                      <div className="mb-1.5">
                        <span className="text-[10px] text-emerald-600 font-medium">Reuse: </span>
                        <span className="text-[10px] text-emerald-700">
                          {m.recommended_elements.join(", ")}
                        </span>
                      </div>
                    )}

                    {m.elements_not_to_reuse && m.elements_not_to_reuse.length > 0 && (
                      <div>
                        <span className="text-[10px] text-red-600 font-medium">Don't reuse: </span>
                        <span className="text-[10px] text-red-700">
                          {m.elements_not_to_reuse.join(", ")}
                        </span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────

export function SlideIntelligencePage({ onNavigate }: { onNavigate: (page: string) => void }) {
  const [tab, setTab] = useState<Tab>("Library");
  const [dashboard, setDashboard] = useState<SIDashboard | null>(null);
  const [presentations, setPresentations] = useState<SIPresentation[]>([]);
  const [slides, setSlides] = useState<SISlide[]>([]);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [dash, pres, sl] = await Promise.all([
        intelApi.siDashboard().catch(() => null),
        intelApi.siPresentations().catch(() => []),
        intelApi.siSlides().catch(() => []),
      ]);
      setDashboard(dash);
      setPresentations(pres);
      setSlides(sl);
    } catch {
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  return (
    <div className="max-w-7xl mx-auto px-6 py-6 space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-1">
          <span className="text-[9px] font-bold text-white bg-blue-600 px-2 py-0.5 rounded-md uppercase tracking-wider">
            Stage 9.5
          </span>
        </div>
        <h1 className="text-xl font-bold text-slate-900">Slide Intelligence</h1>
        <p className="text-[13px] text-slate-500 mt-0.5">
          Historical slide library for presentation style reference
        </p>
      </div>

      {/* Dashboard metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <MetricCard label="Presentations" value={dashboard?.presentation_count ?? "--"} dot="bg-blue-500" />
        <MetricCard label="Total Slides" value={dashboard?.total_slides ?? "--"} dot="bg-indigo-500" />
        <MetricCard label="Processed" value={dashboard?.processed_slides ?? "--"} dot="bg-emerald-500" />
        <MetricCard label="Template Families" value={dashboard?.template_families ?? "--"} dot="bg-purple-500" />
        <MetricCard label="Detected Projects" value={dashboard?.detected_projects ?? "--"} dot="bg-orange-500" />
        <MetricCard label="Excluded" value={dashboard?.excluded_slides ?? "--"} dot="bg-red-500" />
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-200 gap-0">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2.5 text-[12px] font-semibold border-b-2 transition-colors whitespace-nowrap ${
              tab === t
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "Library" && (
        <LibraryTab
          slides={slides}
          loading={loading}
          presentations={presentations}
          dashboard={dashboard}
          onRefresh={loadData}
        />
      )}
      {tab === "Templates" && <TemplatesTab />}
      {tab === "Detected Projects" && <DetectedProjectsTab presentations={presentations} />}
      {tab === "Search" && <SearchTab />}
      {tab === "Storyline Matching" && <StorylineMatchingTab />}

      {/* Navigation */}
      <div className="flex items-center justify-between pt-6">
        <button onClick={() => onNavigate("storyline")} className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors">
          Back to Storyline
        </button>
        <button onClick={() => onNavigate("presentation-composer")} className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm">
          Proceed to Presentation Composer
        </button>
      </div>
    </div>
  );
}

import { useState, useEffect, useCallback } from "react";
import { intelApi } from "../lib/intel-api";
import type { Insight, InsightDetail, InsightsSummary } from "../data/contracts";
import { useActiveProjectId } from "../lib/project-context";

// ─── Constants ─────────────────────────────────────────────────────────────

const INSIGHT_TYPES = [
  "behavioural", "audience", "media", "trend", "crisis",
  "brand", "competitive", "opportunity", "risk", "emerging_theme",
];
const STATUSES = ["draft", "needs_review", "approved", "rejected"];
const SORT_FIELDS: Record<string, string> = {
  confidence_score: "Confidence",
  created_at: "Created At",
  status: "Status",
};

function formatDateTime(ts: number | null | undefined): string {
  if (!ts) return "--";
  const d = new Date(ts < 1e12 ? ts * 1000 : ts);
  if (isNaN(d.getTime())) return "--";
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// ─── Icons ─────────────────────────────────────────────────────────────────

const ip = { width: 14, height: 14, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
const CloseIcon = () => <svg {...ip}><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>;
const LockIcon = () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="text-slate-400"><rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>;
const SparkleIcon = () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" /></svg>;

// ─── Shared UI ─────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  draft: "text-slate-600 bg-slate-100 border-slate-200",
  needs_review: "text-amber-700 bg-amber-50 border-amber-200",
  approved: "text-emerald-700 bg-emerald-50 border-emerald-200",
  rejected: "text-red-700 bg-red-50 border-red-200",
};

const TYPE_COLORS: Record<string, string> = {
  behavioural: "text-purple-700 bg-purple-50 border-purple-200",
  audience: "text-blue-700 bg-blue-50 border-blue-200",
  media: "text-cyan-700 bg-cyan-50 border-cyan-200",
  trend: "text-indigo-700 bg-indigo-50 border-indigo-200",
  crisis: "text-red-700 bg-red-50 border-red-200",
  brand: "text-orange-700 bg-orange-50 border-orange-200",
  competitive: "text-teal-700 bg-teal-50 border-teal-200",
  opportunity: "text-emerald-700 bg-emerald-50 border-emerald-200",
  risk: "text-rose-700 bg-rose-50 border-rose-200",
  emerging_theme: "text-violet-700 bg-violet-50 border-violet-200",
};

function Badge({ label, colors }: { label: string; colors: string }) {
  return <span className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded border whitespace-nowrap ${colors}`}>{label.replace(/_/g, " ")}</span>;
}

function MetricCard({ label, value, dot }: { label: string; value: number | string; dot: string }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-3.5 shadow-sm">
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className={`w-2 h-2 rounded-full shrink-0 ${dot}`} />
        <span className="text-[9px] text-slate-400 font-semibold uppercase tracking-wide leading-tight">{label}</span>
      </div>
      <div className="text-xl font-bold text-slate-900 tabular-nums">{value}</div>
    </div>
  );
}

function FilterSelect({ label, value, onChange, options, labels }: { label: string; value: string; onChange: (v: string) => void; options: string[]; labels?: Record<string, string> }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className="border border-slate-200 rounded-lg px-2.5 py-1.5 text-[11px] text-slate-600 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400">
      {options.map((o) => <option key={o} value={o}>{o === "all" ? `All ${label}` : labels?.[o] || o.replace(/_/g, " ")}</option>)}
    </select>
  );
}

function ConfidenceBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, score * 100));
  const color = pct >= 70 ? "from-emerald-500 to-emerald-400" : pct >= 40 ? "from-amber-500 to-yellow-400" : "from-red-500 to-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 bg-slate-100 rounded-full overflow-hidden">
        <div className={`h-full bg-gradient-to-r ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[11px] tabular-nums text-slate-500 w-8 text-right">{Math.round(pct)}%</span>
    </div>
  );
}

function SectionHeader({ title, count }: { title: string; count?: number }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest">{title}</div>
      {count !== undefined && <span className="text-[10px] text-slate-400 font-medium tabular-nums">{count} items</span>}
      <div className="flex-1 border-t border-slate-200" />
    </div>
  );
}

// ─── Detail Drawer ─────────────────────────────────────────────────────────

function InsightDrawer({ detail, loading, busy, notesDraft, setNotesDraft, onSaveNotes, onClose, onReview, onRequestRevision, onRegenerate }: {
  detail: InsightDetail | null; loading: boolean; busy: boolean; notesDraft: string; setNotesDraft: (v: string) => void;
  onSaveNotes: () => void; onClose: () => void; onReview: (status: string) => void; onRequestRevision: () => void; onRegenerate: () => void;
}) {
  const [revisionNotes, setRevisionNotes] = useState("");
  const [showRevisionInput, setShowRevisionInput] = useState(false);

  return (
    <>
      <div className="fixed inset-0 bg-slate-900/30 z-40 animate-fade-in" onClick={onClose} />
      <div className="fixed right-0 top-0 h-full w-full sm:w-[520px] bg-white shadow-2xl z-50 overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-slate-200 px-5 py-4 flex items-center justify-between z-10">
          <div>
            <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-1">Insight Detail</div>
            {detail && <Badge label={detail.insight.status} colors={STATUS_COLORS[detail.insight.status] || STATUS_COLORS.draft} />}
          </div>
          <button onClick={onClose} className="w-7 h-7 flex items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"><CloseIcon /></button>
        </div>

        {loading && <div className="p-5 text-[12px] text-slate-400">Loading detail...</div>}

        {!loading && detail && (
          <div className="p-5 space-y-5">
            {/* Title & Type */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Badge label={detail.insight.insight_type} colors={TYPE_COLORS[detail.insight.insight_type] || TYPE_COLORS.behavioural} />
                <span className="text-[10px] text-slate-400">Objective: {detail.insight.objective_id}</span>
              </div>
              <h3 className="text-base font-bold text-slate-900 leading-snug">{detail.insight.title}</h3>
            </div>

            {/* Executive Summary */}
            {detail.insight.executive_summary && (
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Executive Summary</div>
                <p className="text-[13px] text-slate-700 leading-relaxed bg-slate-50 rounded-lg p-3 whitespace-pre-wrap">{detail.insight.executive_summary}</p>
              </div>
            )}

            {/* Observation */}
            {detail.insight.observation && (
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Observation</div>
                <p className="text-[12px] text-slate-600 leading-relaxed">{detail.insight.observation}</p>
              </div>
            )}

            {/* Interpretation */}
            {detail.insight.interpretation && (
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Interpretation</div>
                <p className="text-[12px] text-slate-600 leading-relaxed">{detail.insight.interpretation}</p>
              </div>
            )}

            {/* Business Impact */}
            {detail.insight.business_impact && (
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Business Impact</div>
                <p className="text-[12px] text-slate-700 leading-relaxed bg-blue-50 rounded-lg p-3">{detail.insight.business_impact}</p>
              </div>
            )}

            {/* Confidence */}
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Confidence Score</div>
              <ConfidenceBar score={detail.insight.confidence_score} />
              {detail.insight.confidence_rationale && (
                <p className="text-[11px] text-slate-500 mt-1.5 italic">{detail.insight.confidence_rationale}</p>
              )}
            </div>

            {/* Evidence count & platforms */}
            <div className="flex items-start gap-6">
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Evidence Count</div>
                <span className="text-sm font-bold text-slate-700 tabular-nums">{detail.insight.evidence_count}</span>
              </div>
              <div className="flex-1">
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Platforms</div>
                <div className="flex flex-wrap gap-1">
                  {detail.insight.platforms_represented.map((p) => (
                    <span key={p} className="text-[10px] font-medium text-slate-500 bg-slate-100 px-2 py-0.5 rounded">{p}</span>
                  ))}
                </div>
              </div>
            </div>

            {/* Date Coverage */}
            {detail.insight.date_coverage && (
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Date Coverage</div>
                <p className="text-[12px] text-slate-600">{detail.insight.date_coverage}</p>
              </div>
            )}

            {/* Contradictory Evidence */}
            {detail.contradictory_evidence.length > 0 && (
              <div className="border-t border-slate-100 pt-4">
                <div className="text-[10px] font-semibold text-amber-600 uppercase tracking-wide mb-2">Contradictory Evidence ({detail.contradictory_evidence.length})</div>
                <div className="space-y-2 max-h-48 overflow-y-auto">
                  {detail.contradictory_evidence.map((e) => (
                    <div key={e.mapping_id} className="bg-amber-50 rounded-lg p-2.5 border border-amber-100">
                      <p className="text-[11px] text-slate-700 leading-relaxed">{e.text_excerpt || "No excerpt"}</p>
                      <div className="flex items-center gap-2 mt-1 text-[10px] text-slate-400">
                        {e.source && <span>{e.source}</span>}
                        {e.platform && <><span>&middot;</span><span>{e.platform}</span></>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Contradictory evidence text field */}
            {detail.insight.contradictory_evidence && (
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Contradictory Evidence Notes</div>
                <p className="text-[12px] text-slate-600 italic leading-relaxed">{detail.insight.contradictory_evidence}</p>
              </div>
            )}

            {/* Limitations */}
            {detail.insight.limitations && (
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Limitations</div>
                <p className="text-[12px] text-slate-500 leading-relaxed">{detail.insight.limitations}</p>
              </div>
            )}

            {/* Recommended Visualization */}
            {detail.insight.recommended_visualisation && (
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Recommended Visualization</div>
                <p className="text-[12px] text-slate-600">{detail.insight.recommended_visualisation}</p>
              </div>
            )}

            {/* Analyst Notes */}
            <div className="border-t border-slate-100 pt-4">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Analyst Notes</div>
              <textarea value={notesDraft} onChange={(e) => setNotesDraft(e.target.value)} placeholder="Add analyst notes..." rows={3}
                className="w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-[12px] focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 resize-none" />
              <button onClick={onSaveNotes} disabled={busy} className="mt-2 px-3 py-1.5 text-[11px] font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                {busy ? "Saving..." : "Save Notes"}
              </button>
            </div>

            {/* Supporting Evidence */}
            <div className="border-t border-slate-100 pt-4">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Supporting Evidence ({detail.evidence.length})</div>
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {detail.evidence.length === 0 && <p className="text-[11px] text-slate-300">No evidence mapped</p>}
                {detail.evidence.map((e) => (
                  <div key={e.mapping_id} className="bg-slate-50 rounded-lg p-2.5">
                    <p className="text-[11px] text-slate-700 leading-relaxed">{e.text_excerpt || "No excerpt"}</p>
                    <div className="flex items-center gap-2 mt-1.5 text-[10px] text-slate-400">
                      {e.source && <span>{e.source}</span>}
                      {e.platform && <><span>&middot;</span><span>{e.platform}</span></>}
                      {e.confidence && <><span>&middot;</span><Badge label={e.confidence} colors={e.confidence === "high" ? "text-blue-700 bg-blue-50 border-blue-200" : e.confidence === "medium" ? "text-amber-700 bg-amber-50 border-amber-200" : "text-slate-500 bg-slate-100 border-slate-200"} /></>}
                      <span className="text-[10px] text-slate-400">Role: {e.role}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Audit History */}
            <div className="border-t border-slate-100 pt-4">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Audit Trail ({detail.audit_history.length})</div>
              <div className="space-y-2.5 max-h-48 overflow-y-auto">
                {detail.audit_history.length === 0 && <p className="text-[11px] text-slate-300">No history yet</p>}
                {detail.audit_history.map((a) => (
                  <div key={a.id} className="flex items-start gap-2 text-[11px]">
                    <span className="w-1.5 h-1.5 rounded-full bg-slate-300 mt-1.5 shrink-0" />
                    <div className="min-w-0">
                      <span className="text-slate-600 font-medium">{a.actor}</span>
                      <span className="text-slate-400"> {a.action}{a.field ? ` - ${a.field}` : ""}</span>
                      {a.old_value && a.new_value && <span className="text-slate-400"> ({a.old_value} &rarr; {a.new_value})</span>}
                      <div className="text-[10px] text-slate-300">{formatDateTime(a.created_at)}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Review Actions */}
            <div className="border-t border-slate-100 pt-4">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Review Actions</div>
              {detail.insight.reviewed_by && (
                <p className="text-[11px] text-slate-400 mb-3">Last reviewed by {detail.insight.reviewed_by} &middot; {formatDateTime(detail.insight.reviewed_at)}</p>
              )}
              <div className="flex items-center gap-2 flex-wrap">
                <button onClick={() => onReview("approved")} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 transition-colors">Approve</button>
                <button onClick={() => onReview("rejected")} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors">Reject</button>
                <button onClick={() => setShowRevisionInput(!showRevisionInput)} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold bg-amber-500 text-white rounded-lg hover:bg-amber-600 disabled:opacity-50 transition-colors">Request Revision</button>
                <button onClick={onRegenerate} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold text-blue-600 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 disabled:opacity-50 transition-colors">Regenerate</button>
              </div>
              {showRevisionInput && (
                <div className="mt-3">
                  <textarea value={revisionNotes} onChange={(e) => setRevisionNotes(e.target.value)} placeholder="Describe what needs revision..." rows={2}
                    className="w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-[12px] focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 resize-none" />
                  <button onClick={() => { onRequestRevision(); setRevisionNotes(""); setShowRevisionInput(false); }} disabled={busy || !revisionNotes.trim()}
                    className="mt-2 px-3 py-1.5 text-[11px] font-semibold bg-amber-500 text-white rounded-lg hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                    Submit Revision Request
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────

interface Props {
  onNavigate: (page: string) => void;
}

export function InsightsPage({ onNavigate }: Props) {
  const projectId = useActiveProjectId() ?? 1;

  const [locked, setLocked] = useState<boolean | null>(null);
  const [prereqBlockers, setPrereqBlockers] = useState<string[]>([]);
  const [prereqError, setPrereqError] = useState<string | null>(null);
  const [checkingPrereqs, setCheckingPrereqs] = useState(false);

  const [insights, setInsights] = useState<Insight[]>([]);
  const [summary, setSummary] = useState<InsightsSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const [objectiveFilter, setObjectiveFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortBy, setSortBy] = useState("confidence_score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const [filterOptions, setFilterOptions] = useState<{ objectives: string[] }>({ objectives: [] });

  const [selectedDetail, setSelectedDetail] = useState<InsightDetail | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [notesDraft, setNotesDraft] = useState("");
  const [busyAction, setBusyAction] = useState(false);

  // ─── Data loading ──────────────────────────────────────────────────────

  const checkPrereqs = useCallback(async () => {
    setCheckingPrereqs(true);
    setPrereqError(null);
    try {
      const result = await intelApi.validateInsightPrereqs(projectId);
      if (result.valid) {
        setLocked(false);
        setPrereqBlockers([]);
      } else {
        setLocked(true);
        setPrereqBlockers(result.blockers || []);
      }
    } catch (e) {
      setPrereqError(e instanceof Error ? e.message : "Failed to check prerequisites");
      setLocked(true);
    } finally {
      setCheckingPrereqs(false);
    }
  }, [projectId]);

  useEffect(() => { checkPrereqs(); }, [checkPrereqs]);

  const loadSummary = useCallback(async () => {
    try {
      const s = await intelApi.getInsightsSummary(projectId);
      setSummary(s);
    } catch { setSummary(null); }
  }, [projectId]);

  const loadInsights = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = {};
      if (objectiveFilter !== "all") params.objective_id = objectiveFilter;
      if (typeFilter !== "all") params.insight_type = typeFilter;
      if (statusFilter !== "all") params.status = statusFilter;
      params.sort_by = sortBy;
      params.sort_dir = sortDir;
      const data = await intelApi.listInsights(projectId, params);
      setInsights(data);
      // extract unique objectives for filter
      const objs = Array.from(new Set(data.map((i) => i.objective_id).filter(Boolean))).sort();
      setFilterOptions({ objectives: objs });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load insights");
    } finally {
      setLoading(false);
    }
  }, [projectId, objectiveFilter, typeFilter, statusFilter, sortBy, sortDir]);

  useEffect(() => {
    if (locked === false) {
      loadInsights();
      loadSummary();
    }
  }, [locked, loadInsights, loadSummary]);

  // ─── Actions ───────────────────────────────────────────────────────────

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      await intelApi.generateInsights(projectId);
      await loadInsights();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate insights");
    } finally {
      setGenerating(false);
    }
  };

  const handleReview = async (insightId: number, status: string) => {
    setBusyAction(true);
    try {
      await intelApi.reviewInsight(insightId, status, "analyst");
      await loadInsights();
      await loadSummary();
      if (selectedDetail && selectedDetail.insight.id === insightId) {
        const d = await intelApi.getInsightDetail(insightId);
        setSelectedDetail(d);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Review action failed");
    } finally {
      setBusyAction(false);
    }
  };

  const openDetail = async (insightId: number) => {
    setDrawerOpen(true);
    setDetailLoading(true);
    setSelectedDetail(null);
    try {
      const d = await intelApi.getInsightDetail(insightId);
      setSelectedDetail(d);
      setNotesDraft(d.insight.analyst_notes || "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load insight detail");
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    setDrawerOpen(false);
    setSelectedDetail(null);
    setNotesDraft("");
  };

  const handleSaveNotes = async () => {
    if (!selectedDetail) return;
    setBusyAction(true);
    try {
      await intelApi.updateAnalystNotes(selectedDetail.insight.id, notesDraft);
      const d = await intelApi.getInsightDetail(selectedDetail.insight.id);
      setSelectedDetail(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save notes");
    } finally {
      setBusyAction(false);
    }
  };

  const handleRequestRevision = async () => {
    if (!selectedDetail) return;
    setBusyAction(true);
    try {
      await intelApi.requestRevision(selectedDetail.insight.id, notesDraft || "Revision requested");
      await loadInsights();
      await loadSummary();
      const d = await intelApi.getInsightDetail(selectedDetail.insight.id);
      setSelectedDetail(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to request revision");
    } finally {
      setBusyAction(false);
    }
  };

  const handleRegenerate = async () => {
    if (!selectedDetail) return;
    setBusyAction(true);
    try {
      await intelApi.regenerateInsight(selectedDetail.insight.id);
      await loadInsights();
      await loadSummary();
      const d = await intelApi.getInsightDetail(selectedDetail.insight.id);
      setSelectedDetail(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to regenerate insight");
    } finally {
      setBusyAction(false);
    }
  };

  // ─── Render: Loading ───────────────────────────────────────────────────

  if (locked === null) {
    return <div className="max-w-6xl mx-auto px-8 py-10"><div className="text-[13px] text-slate-400">Loading Insights...</div></div>;
  }

  // ─── Render: Locked ────────────────────────────────────────────────────

  if (locked) {
    return (
      <div className="max-w-4xl mx-auto px-8 py-10">
        <div className="mb-6">
          <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-1">Stage 8</div>
          <h1 className="text-xl font-bold text-slate-900">Insights</h1>
          <p className="text-[13px] text-slate-400 mt-1">AI-generated insights derived from curated evidence</p>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-8 shadow-sm text-center">
          <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-slate-100 flex items-center justify-center"><LockIcon /></div>
          <h3 className="text-sm font-semibold text-slate-700 mb-2">Prerequisites not met</h3>
          {prereqError && <p className="text-[12px] text-red-500 mb-3">{prereqError}</p>}
          {prereqBlockers.length > 0 && (
            <ul className="text-[12px] text-slate-500 max-w-sm mx-auto mb-4 text-left list-disc list-inside space-y-1">
              {prereqBlockers.map((b, i) => <li key={i}>{b}</li>)}
            </ul>
          )}
          {prereqBlockers.length === 0 && !prereqError && (
            <p className="text-[12px] text-slate-400 max-w-sm mx-auto mb-4">Complete Research Execution before generating insights.</p>
          )}
          <div className="flex items-center justify-center gap-3">
            <button onClick={() => onNavigate("research-execution")} className="text-[12px] text-blue-600 hover:text-blue-700 font-semibold">Go to Research Execution</button>
            <button onClick={checkPrereqs} disabled={checkingPrereqs} className="px-3 py-1.5 text-[11px] font-semibold text-blue-600 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 disabled:opacity-50 transition-colors">
              {checkingPrereqs ? "Checking..." : "Check Prerequisites"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ─── Render: Main ──────────────────────────────────────────────────────

  return (
    <div className="max-w-6xl mx-auto px-8 py-10">
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-1">Stage 8</div>
          <h1 className="text-xl font-bold text-slate-900">Insights</h1>
          <p className="text-[13px] text-slate-400 mt-1">AI-generated insights derived from curated evidence</p>
        </div>
        <button onClick={handleGenerate} disabled={generating} className="flex items-center gap-2 px-4 py-2 text-[12px] font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          <SparkleIcon />
          {generating ? "Generating..." : "Generate Insights"}
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-[12px] text-red-700 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 font-semibold">&times;</button>
        </div>
      )}

      {/* Summary Metrics */}
      {summary && (
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mb-6">
          <MetricCard label="Total Insights" value={summary.total_insights} dot="bg-blue-500" />
          <MetricCard label="Draft" value={summary.by_status?.draft || 0} dot="bg-slate-400" />
          <MetricCard label="Needs Review" value={summary.by_status?.needs_review || 0} dot="bg-amber-500" />
          <MetricCard label="Approved" value={summary.by_status?.approved || 0} dot="bg-emerald-500" />
          <MetricCard label="Avg Confidence" value={`${Math.round((summary.avg_confidence || 0) * 100)}%`} dot="bg-indigo-500" />
          <MetricCard label="Objectives Covered" value={summary.objectives_covered} dot="bg-teal-500" />
        </div>
      )}

      {/* Filter Toolbar */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm mb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <FilterSelect label="Objectives" value={objectiveFilter} onChange={setObjectiveFilter} options={["all", ...filterOptions.objectives]} />
          <FilterSelect label="Types" value={typeFilter} onChange={setTypeFilter} options={["all", ...INSIGHT_TYPES]} />
          <FilterSelect label="Statuses" value={statusFilter} onChange={setStatusFilter} options={["all", ...STATUSES]} />
          <div className="w-px h-6 bg-slate-200 mx-1" />
          <span className="text-[10px] text-slate-400 font-semibold uppercase">Sort</span>
          <FilterSelect label="Sort" value={sortBy} onChange={setSortBy} options={Object.keys(SORT_FIELDS)} labels={SORT_FIELDS} />
          <button onClick={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))} title={sortDir === "asc" ? "Ascending" : "Descending"} className="w-8 h-8 flex items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 hover:bg-slate-50 transition-colors">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d={sortDir === "asc" ? "M12 19V5M5 12l7-7 7 7" : "M12 5v14M19 12l-7 7-7-7"} /></svg>
          </button>
        </div>
      </div>

      {/* Insight Cards */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
        <SectionHeader title="Insights" count={insights.length} />

        {loading ? (
          <div className="text-center py-12 text-[12px] text-slate-400">Loading insights...</div>
        ) : insights.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-[12px] text-slate-400 mb-4">No insights generated yet. Click "Generate Insights" to begin.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {insights.map((insight) => (
              <div key={insight.id} className="bg-white border border-slate-200 rounded-xl shadow-sm p-4 flex flex-col gap-3 hover:border-slate-300 transition-colors">
                {/* Badges row */}
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge label={insight.status} colors={STATUS_COLORS[insight.status] || STATUS_COLORS.draft} />
                  <Badge label={insight.insight_type} colors={TYPE_COLORS[insight.insight_type] || TYPE_COLORS.behavioural} />
                  <span className="text-[10px] text-slate-400 ml-auto">#{insight.id}</span>
                </div>

                {/* Title */}
                <h4 className="text-[13px] font-semibold text-slate-900 leading-snug">{insight.title}</h4>

                {/* Executive Summary */}
                {insight.executive_summary && (
                  <p className="text-[11px] text-slate-500 leading-relaxed line-clamp-2">{insight.executive_summary}</p>
                )}

                {/* Business Impact */}
                {insight.business_impact && (
                  <div className="bg-blue-50 rounded-lg px-2.5 py-1.5">
                    <p className="text-[10px] text-blue-700 leading-relaxed line-clamp-2">{insight.business_impact}</p>
                  </div>
                )}

                {/* Confidence */}
                <div className="w-full">
                  <div className="text-[9px] text-slate-400 uppercase tracking-wide mb-1">Confidence</div>
                  <ConfidenceBar score={insight.confidence_score} />
                </div>

                {/* Meta row */}
                <div className="flex items-center flex-wrap gap-x-2 gap-y-1 text-[10px] text-slate-400">
                  <span>{insight.evidence_count} evidence</span>
                  {insight.platforms_represented.length > 0 && (
                    <>
                      <span>&middot;</span>
                      {insight.platforms_represented.slice(0, 3).map((p) => (
                        <span key={p} className="font-medium text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded text-[9px]">{p}</span>
                      ))}
                      {insight.platforms_represented.length > 3 && <span>+{insight.platforms_represented.length - 3}</span>}
                    </>
                  )}
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 pt-2 border-t border-slate-100">
                  <button onClick={() => handleReview(insight.id, "approved")} disabled={busyAction} className="px-2.5 py-1 text-[10px] font-semibold bg-emerald-600 text-white rounded-md hover:bg-emerald-700 disabled:opacity-50 transition-colors">Approve</button>
                  <button onClick={() => handleReview(insight.id, "rejected")} disabled={busyAction} className="px-2.5 py-1 text-[10px] font-semibold bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50 transition-colors">Reject</button>
                  <button onClick={() => handleReview(insight.id, "needs_review")} disabled={busyAction} className="px-2.5 py-1 text-[10px] font-semibold bg-amber-500 text-white rounded-md hover:bg-amber-600 disabled:opacity-50 transition-colors">Review</button>
                  <button onClick={() => openDetail(insight.id)} className="ml-auto px-2.5 py-1 text-[10px] font-semibold text-blue-600 bg-blue-50 border border-blue-200 rounded-md hover:bg-blue-100 transition-colors">View Detail</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Detail Drawer */}
      {drawerOpen && (
        <InsightDrawer
          detail={selectedDetail}
          loading={detailLoading}
          busy={busyAction}
          notesDraft={notesDraft}
          setNotesDraft={setNotesDraft}
          onSaveNotes={handleSaveNotes}
          onClose={closeDetail}
          onReview={(status) => selectedDetail && handleReview(selectedDetail.insight.id, status)}
          onRequestRevision={handleRequestRevision}
          onRegenerate={handleRegenerate}
        />
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between pt-6">
        <button onClick={() => onNavigate("research-execution")} className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors">
          Back to Research Execution
        </button>
        <button onClick={() => onNavigate("storyline")} className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm">
          Proceed to Storyline
        </button>
      </div>
    </div>
  );
}

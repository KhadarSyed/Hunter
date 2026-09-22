import { useState, useEffect, useCallback } from "react";
import { intelApi } from "../lib/intel-api";
import type { Storyline, StorylineDetail, StorylineSummary, StoryNodeEnriched } from "../data/contracts";
import { useActiveProjectId } from "../lib/project-context";

// ─── Constants ─────────────────────────────────────────────────────────────

const NODE_STATUSES = ["draft", "needs_review", "approved", "rejected"];

const SECTION_TYPE_COLORS: Record<string, string> = {
  opening: "text-indigo-700 bg-indigo-50 border-indigo-200",
  context: "text-blue-700 bg-blue-50 border-blue-200",
  finding: "text-emerald-700 bg-emerald-50 border-emerald-200",
  analysis: "text-purple-700 bg-purple-50 border-purple-200",
  recommendation: "text-orange-700 bg-orange-50 border-orange-200",
  conclusion: "text-teal-700 bg-teal-50 border-teal-200",
  transition: "text-slate-600 bg-slate-100 border-slate-200",
  appendix: "text-cyan-700 bg-cyan-50 border-cyan-200",
  executive_summary: "text-violet-700 bg-violet-50 border-violet-200",
  methodology: "text-rose-700 bg-rose-50 border-rose-200",
};

const STATUS_COLORS: Record<string, string> = {
  draft: "text-slate-600 bg-slate-100 border-slate-200",
  needs_review: "text-amber-700 bg-amber-50 border-amber-200",
  approved: "text-emerald-700 bg-emerald-50 border-emerald-200",
  rejected: "text-red-700 bg-red-50 border-red-200",
};

const PRIORITY_COLORS: Record<string, string> = {
  high: "text-red-600",
  medium: "text-amber-600",
  low: "text-slate-400",
};

const VISUAL_TYPE_COLORS: Record<string, string> = {
  chart: "text-blue-700 bg-blue-50 border-blue-200",
  table: "text-slate-600 bg-slate-100 border-slate-200",
  infographic: "text-purple-700 bg-purple-50 border-purple-200",
  quote: "text-amber-700 bg-amber-50 border-amber-200",
  diagram: "text-teal-700 bg-teal-50 border-teal-200",
  map: "text-emerald-700 bg-emerald-50 border-emerald-200",
  timeline: "text-indigo-700 bg-indigo-50 border-indigo-200",
  none: "text-slate-400 bg-slate-50 border-slate-200",
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
const StarIcon = ({ filled }: { filled: boolean }) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" className={filled ? "text-amber-500" : "text-slate-300"}>
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
  </svg>
);
const LockSmallIcon = ({ locked }: { locked: boolean }) => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={locked ? "text-amber-500" : "text-slate-300"}>
    {locked ? (
      <><rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></>
    ) : (
      <><rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 7-4.7" /></>
    )}
  </svg>
);

// ─── Shared UI ─────────────────────────────────────────────────────────────

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

// ─── Node Detail Drawer ───────────────────────────────────────────────────

function NodeDrawer({
  node, loading, busy, onClose, onReview, onSplit, onMerge, onUpdateField, storylineNodes,
}: {
  node: StoryNodeEnriched | null;
  loading: boolean;
  busy: boolean;
  onClose: () => void;
  onReview: (status: string) => void;
  onSplit: () => void;
  onMerge: (otherNodeId: number) => void;
  onUpdateField: (field: string, value: string | boolean) => void;
  storylineNodes: StoryNodeEnriched[];
}) {
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [editingSummary, setEditingSummary] = useState(false);
  const [summaryDraft, setSummaryDraft] = useState("");
  const [mergeTarget, setMergeTarget] = useState<number | null>(null);

  useEffect(() => {
    if (node) {
      setTitleDraft(node.title);
      setSummaryDraft(node.narrative_summary || "");
      setEditingTitle(false);
      setEditingSummary(false);
      setMergeTarget(null);
    }
  }, [node]);

  return (
    <>
      <div className="fixed inset-0 bg-slate-900/30 z-40 animate-fade-in" onClick={onClose} />
      <div className="fixed right-0 top-0 h-full w-full sm:w-[520px] bg-white shadow-2xl z-50 overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-slate-200 px-5 py-4 flex items-center justify-between z-10">
          <div>
            <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-1">Node Detail</div>
            {node && <Badge label={node.status} colors={STATUS_COLORS[node.status] || STATUS_COLORS.draft} />}
          </div>
          <button onClick={onClose} className="w-7 h-7 flex items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"><CloseIcon /></button>
        </div>

        {loading && <div className="p-5 text-[12px] text-slate-400">Loading detail...</div>}

        {!loading && node && (
          <div className="p-5 space-y-5">
            {/* Section Type & Priority */}
            <div className="flex items-center gap-2 flex-wrap">
              <Badge label={node.section_type} colors={SECTION_TYPE_COLORS[node.section_type] || SECTION_TYPE_COLORS.transition} />
              <span className={`text-[10px] font-semibold uppercase ${PRIORITY_COLORS[node.priority] || "text-slate-400"}`}>{node.priority} priority</span>
              <div className="ml-auto flex items-center gap-2">
                <StarIcon filled={node.is_key_message} />
                <LockSmallIcon locked={node.is_locked} />
              </div>
            </div>

            {/* Editable Title */}
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Title</div>
              {editingTitle ? (
                <div className="flex gap-2">
                  <input value={titleDraft} onChange={(e) => setTitleDraft(e.target.value)} className="flex-1 border border-slate-200 rounded-lg px-2.5 py-1.5 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400" />
                  <button onClick={() => { onUpdateField("title", titleDraft); setEditingTitle(false); }} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors">Save</button>
                  <button onClick={() => { setTitleDraft(node.title); setEditingTitle(false); }} className="px-3 py-1.5 text-[11px] font-semibold text-slate-500 bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors">Cancel</button>
                </div>
              ) : (
                <h3 onClick={() => setEditingTitle(true)} className="text-base font-bold text-slate-900 leading-snug cursor-pointer hover:text-blue-600 transition-colors">{node.title}</h3>
              )}
            </div>

            {/* Purpose */}
            {node.purpose && (
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Purpose</div>
                <p className="text-[12px] text-slate-600 leading-relaxed">{node.purpose}</p>
              </div>
            )}

            {/* Editable Narrative Summary */}
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Narrative Summary</div>
              {editingSummary ? (
                <div>
                  <textarea value={summaryDraft} onChange={(e) => setSummaryDraft(e.target.value)} rows={4}
                    className="w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-[12px] focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 resize-none" />
                  <div className="flex gap-2 mt-2">
                    <button onClick={() => { onUpdateField("narrative_summary", summaryDraft); setEditingSummary(false); }} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors">Save</button>
                    <button onClick={() => { setSummaryDraft(node.narrative_summary || ""); setEditingSummary(false); }} className="px-3 py-1.5 text-[11px] font-semibold text-slate-500 bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors">Cancel</button>
                  </div>
                </div>
              ) : (
                <p onClick={() => setEditingSummary(true)} className="text-[13px] text-slate-700 leading-relaxed bg-slate-50 rounded-lg p-3 whitespace-pre-wrap cursor-pointer hover:bg-slate-100 transition-colors">
                  {node.narrative_summary || "Click to add narrative summary..."}
                </p>
              )}
            </div>

            {/* Confidence */}
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Confidence Score</div>
              <ConfidenceBar score={node.confidence_score} />
            </div>

            {/* Visual Recommendation */}
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Suggested Visual</div>
              <Badge label={node.suggested_visual} colors={VISUAL_TYPE_COLORS[node.suggested_visual] || VISUAL_TYPE_COLORS.none} />
            </div>

            {/* Duration & Order */}
            <div className="flex items-start gap-6">
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Duration</div>
                <span className="text-sm font-bold text-slate-700 tabular-nums">{node.estimated_duration_minutes} min</span>
              </div>
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Position</div>
                <span className="text-sm font-bold text-slate-700 tabular-nums">#{node.order_position}</span>
              </div>
            </div>

            {/* Transition Text */}
            {node.transition_text && (
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Transition Text</div>
                <p className="text-[12px] text-slate-500 leading-relaxed italic bg-slate-50 rounded-lg p-3">{node.transition_text}</p>
              </div>
            )}

            {/* Supporting Insights */}
            <div className="border-t border-slate-100 pt-4">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Supporting Insights ({node.insight_count})</div>
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {node.insights.length === 0 && <p className="text-[11px] text-slate-300">No insights mapped</p>}
                {node.insights.map((ins) => (
                  <div key={ins.mapping_id} className="bg-slate-50 rounded-lg p-2.5">
                    <p className="text-[11px] text-slate-700 leading-relaxed font-medium">{ins.insight_title}</p>
                    {ins.insight_summary && <p className="text-[10px] text-slate-500 mt-1 leading-relaxed">{ins.insight_summary}</p>}
                    <div className="flex items-center gap-2 mt-1.5 text-[10px] text-slate-400">
                      <span>Role: {ins.role}</span>
                      <span>&middot;</span>
                      <Badge label={ins.insight_status} colors={STATUS_COLORS[ins.insight_status] || STATUS_COLORS.draft} />
                      <span>&middot;</span>
                      <span>{Math.round(ins.insight_confidence * 100)}% confidence</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Toggle Actions */}
            <div className="border-t border-slate-100 pt-4">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Node Properties</div>
              <div className="flex items-center gap-3">
                <button onClick={() => onUpdateField("is_key_message", !node.is_key_message)} disabled={busy}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-semibold rounded-lg border transition-colors ${node.is_key_message ? "bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100" : "bg-slate-50 text-slate-500 border-slate-200 hover:bg-slate-100"}`}>
                  <StarIcon filled={node.is_key_message} /> {node.is_key_message ? "Key Message" : "Mark Key"}
                </button>
                <button onClick={() => onUpdateField("is_locked", !node.is_locked)} disabled={busy}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-semibold rounded-lg border transition-colors ${node.is_locked ? "bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100" : "bg-slate-50 text-slate-500 border-slate-200 hover:bg-slate-100"}`}>
                  <LockSmallIcon locked={node.is_locked} /> {node.is_locked ? "Locked" : "Lock"}
                </button>
              </div>
            </div>

            {/* Split & Merge */}
            <div className="border-t border-slate-100 pt-4">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Node Operations</div>
              <div className="flex items-center gap-2 flex-wrap">
                <button onClick={onSplit} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold text-blue-600 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 disabled:opacity-50 transition-colors">Split Node</button>
                <button onClick={() => setMergeTarget(mergeTarget === null ? -1 : null)} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold text-purple-600 bg-purple-50 border border-purple-200 rounded-lg hover:bg-purple-100 disabled:opacity-50 transition-colors">
                  {mergeTarget !== null ? "Cancel Merge" : "Merge with..."}
                </button>
              </div>
              {mergeTarget !== null && (
                <div className="mt-3">
                  <select value={mergeTarget === -1 ? "" : mergeTarget} onChange={(e) => setMergeTarget(Number(e.target.value))}
                    className="border border-slate-200 rounded-lg px-2.5 py-1.5 text-[11px] text-slate-600 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 w-full">
                    <option value="">Select a node to merge with...</option>
                    {storylineNodes.filter((n) => n.id !== node.id).map((n) => (
                      <option key={n.id} value={n.id}>#{n.order_position} - {n.title}</option>
                    ))}
                  </select>
                  {mergeTarget > 0 && (
                    <button onClick={() => { onMerge(mergeTarget); setMergeTarget(null); }} disabled={busy}
                      className="mt-2 px-3 py-1.5 text-[11px] font-semibold bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 transition-colors">
                      Confirm Merge
                    </button>
                  )}
                </div>
              )}
            </div>

            {/* Review Actions */}
            <div className="border-t border-slate-100 pt-4">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Review Actions</div>
              {node.reviewed_by && (
                <p className="text-[11px] text-slate-400 mb-3">Last reviewed by {node.reviewed_by} &middot; {formatDateTime(node.reviewed_at)}</p>
              )}
              <div className="flex items-center gap-2 flex-wrap">
                <button onClick={() => onReview("approved")} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 transition-colors">Approve</button>
                <button onClick={() => onReview("rejected")} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors">Reject</button>
                <button onClick={() => onReview("needs_review")} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold bg-amber-500 text-white rounded-lg hover:bg-amber-600 disabled:opacity-50 transition-colors">Needs Review</button>
              </div>
            </div>

            {/* Timestamps */}
            <div className="border-t border-slate-100 pt-4 text-[10px] text-slate-400 space-y-1">
              <div>Created: {formatDateTime(node.created_at)}</div>
              <div>Updated: {formatDateTime(node.updated_at)}</div>
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

export function StorylinePage({ onNavigate }: Props) {
  const projectId = useActiveProjectId() ?? 1;

  const [locked, setLocked] = useState<boolean | null>(null);
  const [prereqBlockers, setPrereqBlockers] = useState<string[]>([]);
  const [prereqError, setPrereqError] = useState<string | null>(null);
  const [checkingPrereqs, setCheckingPrereqs] = useState(false);

  const [storylines, setStorylines] = useState<Storyline[]>([]);
  const [activeStoryline, setActiveStoryline] = useState<StorylineDetail | null>(null);
  const [summary, setSummary] = useState<StorylineSummary | null>(null);
  const [nodes, setNodes] = useState<StoryNodeEnriched[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const [expandedNodes, setExpandedNodes] = useState<Set<number>>(new Set());
  const [editingTitleId, setEditingTitleId] = useState<number | null>(null);
  const [titleDraft, setTitleDraft] = useState("");

  const [selectedNode, setSelectedNode] = useState<StoryNodeEnriched | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busyAction, setBusyAction] = useState(false);

  const [showAudit, setShowAudit] = useState(false);

  // ─── Data loading ──────────────────────────────────────────────────────

  const checkPrereqs = useCallback(async () => {
    setCheckingPrereqs(true);
    setPrereqError(null);
    try {
      const result = await intelApi.validateStorylinePrereqs(projectId);
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
      const s = await intelApi.getStorylineSummary(projectId);
      setSummary(s);
    } catch { setSummary(null); }
  }, [projectId]);

  const loadStorylines = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await intelApi.getStoryline(projectId);
      setStorylines(data);
      // Load the latest storyline detail
      if (data.length > 0) {
        const latest = data[data.length - 1];
        const detail = await intelApi.getStorylineDetail(latest.id);
        setActiveStoryline(detail);
        setNodes(detail.nodes.sort((a, b) => a.order_position - b.order_position));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load storylines");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (locked === false) {
      loadStorylines();
      loadSummary();
    }
  }, [locked, loadStorylines, loadSummary]);

  // ─── Actions ───────────────────────────────────────────────────────────

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      await intelApi.generateStoryline(projectId);
      await loadStorylines();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate storyline");
    } finally {
      setGenerating(false);
    }
  };

  const handleReviewNode = async (nodeId: number, status: string) => {
    setBusyAction(true);
    try {
      await intelApi.reviewNode(nodeId, status, "analyst");
      await loadStorylines();
      await loadSummary();
      if (selectedNode && selectedNode.id === nodeId) {
        const updatedNodes = await intelApi.listStorylineNodes(selectedNode.storyline_id);
        const updated = updatedNodes.find((n) => n.id === nodeId);
        if (updated) setSelectedNode(updated);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Review action failed");
    } finally {
      setBusyAction(false);
    }
  };

  const handleUpdateNodeField = async (nodeId: number, field: string, value: string | boolean) => {
    setBusyAction(true);
    try {
      await intelApi.updateNode(nodeId, { [field]: value });
      await loadStorylines();
      if (selectedNode && selectedNode.id === nodeId) {
        const storylineId = selectedNode.storyline_id;
        const updatedNodes = await intelApi.listStorylineNodes(storylineId);
        const updated = updatedNodes.find((n) => n.id === nodeId);
        if (updated) setSelectedNode(updated);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusyAction(false);
    }
  };

  const handleInlineTitleSave = async (nodeId: number) => {
    setBusyAction(true);
    try {
      await intelApi.updateNode(nodeId, { title: titleDraft });
      setEditingTitleId(null);
      await loadStorylines();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Title update failed");
    } finally {
      setBusyAction(false);
    }
  };

  const handleSplitNode = async (nodeId: number) => {
    setBusyAction(true);
    try {
      await intelApi.splitNode(nodeId);
      await loadStorylines();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Split failed");
    } finally {
      setBusyAction(false);
    }
  };

  const handleMergeNodes = async (nodeIdA: number, nodeIdB: number) => {
    if (!activeStoryline) return;
    setBusyAction(true);
    try {
      await intelApi.mergeNodes(activeStoryline.storyline.id, nodeIdA, nodeIdB);
      await loadStorylines();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Merge failed");
    } finally {
      setBusyAction(false);
    }
  };

  const handleApproveStoryline = async () => {
    if (!activeStoryline) return;
    setBusyAction(true);
    try {
      await intelApi.approveStoryline(activeStoryline.storyline.id, "analyst");
      await loadStorylines();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approve failed");
    } finally {
      setBusyAction(false);
    }
  };

  const handleRejectStoryline = async () => {
    if (!activeStoryline) return;
    setBusyAction(true);
    try {
      await intelApi.rejectStoryline(activeStoryline.storyline.id, "analyst");
      await loadStorylines();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reject failed");
    } finally {
      setBusyAction(false);
    }
  };

  const handleValidateStoryline = async () => {
    if (!activeStoryline) return;
    setBusyAction(true);
    try {
      const result = await intelApi.validateStoryline(activeStoryline.storyline.id);
      if (result.valid) {
        setError(null);
        alert("Storyline is valid. " + (result.warnings.length > 0 ? "Warnings: " + result.warnings.join(", ") : "No warnings."));
      } else {
        setError("Validation issues: " + (result.issues?.join(", ") || "Unknown issues"));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Validation failed");
    } finally {
      setBusyAction(false);
    }
  };

  const openDetail = (node: StoryNodeEnriched) => {
    setDrawerOpen(true);
    setDetailLoading(false);
    setSelectedNode(node);
  };

  const closeDetail = () => {
    setDrawerOpen(false);
    setSelectedNode(null);
  };

  const toggleExpand = (nodeId: number) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  };

  // ─── Render: Loading ───────────────────────────────────────────────────

  if (locked === null) {
    return <div className="max-w-6xl mx-auto px-8 py-10"><div className="text-[13px] text-slate-400">Loading Storyline...</div></div>;
  }

  // ─── Render: Locked ────────────────────────────────────────────────────

  if (locked) {
    return (
      <div className="max-w-4xl mx-auto px-8 py-10">
        <div className="mb-6">
          <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-1">Stage 9</div>
          <h1 className="text-xl font-bold text-slate-900">Storyline</h1>
          <p className="text-[13px] text-slate-400 mt-1">Narrative structure built from approved insights</p>
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
            <p className="text-[12px] text-slate-400 max-w-sm mx-auto mb-4">Complete Insights review before generating a storyline.</p>
          )}
          <div className="flex items-center justify-center gap-3">
            <button onClick={() => onNavigate("insights")} className="text-[12px] text-blue-600 hover:text-blue-700 font-semibold">Go to Insights</button>
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
          <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-1">Stage 9</div>
          <h1 className="text-xl font-bold text-slate-900">Storyline</h1>
          <p className="text-[13px] text-slate-400 mt-1">Narrative structure built from approved insights</p>
        </div>
        <button onClick={handleGenerate} disabled={generating} className="flex items-center gap-2 px-4 py-2 text-[12px] font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          <SparkleIcon />
          {generating ? "Generating..." : "Generate Storyline"}
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
        <div className="grid grid-cols-3 sm:grid-cols-5 gap-3 mb-6">
          <MetricCard label="Total Nodes" value={summary.total_nodes} dot="bg-blue-500" />
          <MetricCard label="Duration" value={`${summary.total_duration_minutes} min`} dot="bg-indigo-500" />
          <MetricCard label="Pattern" value={summary.latest_pattern || "--"} dot="bg-purple-500" />
          <MetricCard label="Draft Nodes" value={summary.node_statuses?.draft || 0} dot="bg-slate-400" />
          <MetricCard label="Approved Nodes" value={summary.node_statuses?.approved || 0} dot="bg-emerald-500" />
        </div>
      )}

      {/* Storyline-Level Controls */}
      {activeStoryline && (
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm mb-4">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex-1 min-w-0">
              <h3 className="text-[13px] font-semibold text-slate-900 truncate">{activeStoryline.storyline.title}</h3>
              <div className="flex items-center gap-2 mt-1">
                <Badge label={activeStoryline.storyline.status} colors={STATUS_COLORS[activeStoryline.storyline.status] || STATUS_COLORS.draft} />
                <span className="text-[10px] text-slate-400">Pattern: {activeStoryline.storyline.narrative_pattern}</span>
                <span className="text-[10px] text-slate-400">&middot; {activeStoryline.storyline.node_count} nodes</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={handleApproveStoryline} disabled={busyAction} className="px-3 py-1.5 text-[11px] font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 transition-colors">Approve Storyline</button>
              <button onClick={handleRejectStoryline} disabled={busyAction} className="px-3 py-1.5 text-[11px] font-semibold bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors">Reject Storyline</button>
              <button onClick={handleValidateStoryline} disabled={busyAction} className="px-3 py-1.5 text-[11px] font-semibold text-blue-600 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 disabled:opacity-50 transition-colors">Validate</button>
            </div>
          </div>
          {activeStoryline.storyline.executive_summary && (
            <p className="text-[12px] text-slate-500 mt-3 leading-relaxed">{activeStoryline.storyline.executive_summary}</p>
          )}
        </div>
      )}

      {/* Story Map */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
        <SectionHeader title="Story Map" count={nodes.length} />

        {loading ? (
          <div className="text-center py-12 text-[12px] text-slate-400">Loading storyline...</div>
        ) : nodes.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-[12px] text-slate-400 mb-4">No storyline generated yet. Click "Generate Storyline" to begin.</p>
          </div>
        ) : (
          <div className="space-y-0">
            {nodes.map((node, idx) => (
              <div key={node.id}>
                {/* Node Card */}
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4 flex flex-col gap-3 hover:border-slate-300 transition-colors relative">
                  {/* Top row: badges + indicators */}
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge label={node.section_type} colors={SECTION_TYPE_COLORS[node.section_type] || SECTION_TYPE_COLORS.transition} />
                    <Badge label={node.status} colors={STATUS_COLORS[node.status] || STATUS_COLORS.draft} />
                    <Badge label={node.suggested_visual} colors={VISUAL_TYPE_COLORS[node.suggested_visual] || VISUAL_TYPE_COLORS.none} />
                    <span className={`text-[10px] font-semibold uppercase ${PRIORITY_COLORS[node.priority] || "text-slate-400"}`}>{node.priority}</span>
                    <div className="ml-auto flex items-center gap-2">
                      <StarIcon filled={node.is_key_message} />
                      <LockSmallIcon locked={node.is_locked} />
                      <span className="text-[10px] text-slate-400 tabular-nums">#{node.order_position}</span>
                    </div>
                  </div>

                  {/* Title (inline editable) */}
                  {editingTitleId === node.id ? (
                    <div className="flex gap-2">
                      <input value={titleDraft} onChange={(e) => setTitleDraft(e.target.value)}
                        className="flex-1 border border-slate-200 rounded-lg px-2.5 py-1.5 text-[13px] focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
                        onKeyDown={(e) => { if (e.key === "Enter") handleInlineTitleSave(node.id); if (e.key === "Escape") setEditingTitleId(null); }}
                        autoFocus />
                      <button onClick={() => handleInlineTitleSave(node.id)} disabled={busyAction} className="px-2.5 py-1 text-[10px] font-semibold bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 transition-colors">Save</button>
                      <button onClick={() => setEditingTitleId(null)} className="px-2.5 py-1 text-[10px] font-semibold text-slate-500 bg-slate-100 rounded-md hover:bg-slate-200 transition-colors">Cancel</button>
                    </div>
                  ) : (
                    <h4 onClick={() => { setEditingTitleId(node.id); setTitleDraft(node.title); }}
                      className="text-[13px] font-semibold text-slate-900 leading-snug cursor-pointer hover:text-blue-600 transition-colors">
                      {node.title}
                    </h4>
                  )}

                  {/* Narrative Summary (truncated with expand) */}
                  {node.narrative_summary && (
                    <div>
                      <p className={`text-[11px] text-slate-500 leading-relaxed ${expandedNodes.has(node.id) ? "" : "line-clamp-2"}`}>
                        {node.narrative_summary}
                      </p>
                      {node.narrative_summary.length > 150 && (
                        <button onClick={() => toggleExpand(node.id)} className="text-[10px] text-blue-600 hover:text-blue-700 font-medium mt-0.5">
                          {expandedNodes.has(node.id) ? "Show less" : "Show more"}
                        </button>
                      )}
                    </div>
                  )}

                  {/* Confidence */}
                  <div className="w-full">
                    <div className="text-[9px] text-slate-400 uppercase tracking-wide mb-1">Confidence</div>
                    <ConfidenceBar score={node.confidence_score} />
                  </div>

                  {/* Meta row */}
                  <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-400">
                    <span>{node.insight_count} insights</span>
                    <span>&middot;</span>
                    <span>{node.estimated_duration_minutes} min</span>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 pt-2 border-t border-slate-100 flex-wrap">
                    <button onClick={() => handleReviewNode(node.id, "approved")} disabled={busyAction} className="px-2.5 py-1 text-[10px] font-semibold bg-emerald-600 text-white rounded-md hover:bg-emerald-700 disabled:opacity-50 transition-colors">Approve</button>
                    <button onClick={() => handleReviewNode(node.id, "rejected")} disabled={busyAction} className="px-2.5 py-1 text-[10px] font-semibold bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50 transition-colors">Reject</button>
                    <button onClick={() => handleReviewNode(node.id, "needs_review")} disabled={busyAction} className="px-2.5 py-1 text-[10px] font-semibold bg-amber-500 text-white rounded-md hover:bg-amber-600 disabled:opacity-50 transition-colors">Review</button>
                    <button onClick={() => handleUpdateNodeField(node.id, "is_locked", !node.is_locked)} disabled={busyAction}
                      className="px-2.5 py-1 text-[10px] font-semibold text-slate-500 bg-slate-100 border border-slate-200 rounded-md hover:bg-slate-200 disabled:opacity-50 transition-colors">
                      {node.is_locked ? "Unlock" : "Lock"}
                    </button>
                    <button onClick={() => openDetail(node)} className="ml-auto px-2.5 py-1 text-[10px] font-semibold text-blue-600 bg-blue-50 border border-blue-200 rounded-md hover:bg-blue-100 transition-colors">View Detail</button>
                  </div>
                </div>

                {/* Transition connector to next node */}
                {idx < nodes.length - 1 && (
                  <div className="flex items-center justify-center py-2">
                    <div className="flex flex-col items-center">
                      <div className="w-px h-4 bg-slate-300" />
                      {node.transition_text && (
                        <div className="bg-slate-50 border border-slate-200 rounded-lg px-3 py-1.5 max-w-md">
                          <p className="text-[10px] text-slate-400 italic text-center leading-relaxed">{node.transition_text}</p>
                        </div>
                      )}
                      <div className="w-px h-4 bg-slate-300" />
                      <svg width="10" height="8" viewBox="0 0 10 8" fill="none"><path d="M5 8L0 0h10L5 8z" fill="#cbd5e1" /></svg>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Audit Trail */}
      {activeStoryline && activeStoryline.audit_history.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5 mt-4">
          <div className="flex items-center justify-between mb-4">
            <SectionHeader title="Audit Trail" count={activeStoryline.audit_history.length} />
            <button onClick={() => setShowAudit(!showAudit)} className="text-[10px] text-blue-600 hover:text-blue-700 font-semibold">
              {showAudit ? "Hide" : "Show"}
            </button>
          </div>
          {showAudit && (
            <div className="space-y-2.5 max-h-64 overflow-y-auto">
              {activeStoryline.audit_history.map((a) => (
                <div key={a.id} className="flex items-start gap-2 text-[11px]">
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-300 mt-1.5 shrink-0" />
                  <div className="min-w-0">
                    <span className="text-slate-600 font-medium">{a.actor}</span>
                    <span className="text-slate-400"> {a.action}{a.field ? ` - ${a.field}` : ""}</span>
                    {a.old_value && a.new_value && <span className="text-slate-400"> ({a.old_value} &rarr; {a.new_value})</span>}
                    {a.node_id && <span className="text-slate-300"> (Node #{a.node_id})</span>}
                    <div className="text-[10px] text-slate-300">{formatDateTime(a.created_at)}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Detail Drawer */}
      {drawerOpen && (
        <NodeDrawer
          node={selectedNode}
          loading={detailLoading}
          busy={busyAction}
          onClose={closeDetail}
          onReview={(status) => selectedNode && handleReviewNode(selectedNode.id, status)}
          onSplit={() => selectedNode && handleSplitNode(selectedNode.id)}
          onMerge={(otherNodeId) => selectedNode && handleMergeNodes(selectedNode.id, otherNodeId)}
          onUpdateField={(field, value) => selectedNode && handleUpdateNodeField(selectedNode.id, field, value)}
          storylineNodes={nodes}
        />
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between pt-6">
        <button onClick={() => onNavigate("insights")} className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors">
          Back to Insights
        </button>
        <button onClick={() => onNavigate("slide-intelligence")} className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm">
          Proceed to Slide Intelligence
        </button>
      </div>
    </div>
  );
}

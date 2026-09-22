import { useState, useEffect, useCallback } from "react";
import { intelApi } from "../lib/intel-api";
import type { Insight, InsightDetail, InsightsSummary, StorylineDetail, StorylineSummary, StoryNodeEnriched } from "../data/contracts";
import { useActiveProjectId } from "../lib/project-context";

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

type Phase = "idle" | "insights" | "storyline" | "done";

const ip = { width: 14, height: 14, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
const CloseIcon = () => <svg {...ip}><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>;
const LockIcon = () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="text-slate-400"><rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>;
const SparkleIcon = () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" /></svg>;
const ChevronIcon = ({ open }: { open: boolean }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`transition-transform ${open ? "rotate-90" : ""}`}>
    <polyline points="9 18 15 12 9 6" />
  </svg>
);
const CheckIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-emerald-500">
    <polyline points="20 6 9 17 4 12" />
  </svg>
);
const SpinnerIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className="text-blue-500 animate-spin">
    <path d="M12 2a10 10 0 0 1 10 10" />
  </svg>
);

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

function InsightDrawer({ detail, loading, busy, onClose, onReview }: {
  detail: InsightDetail | null; loading: boolean; busy: boolean;
  onClose: () => void; onReview: (status: string) => void;
}) {
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
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Badge label={detail.insight.insight_type} colors={TYPE_COLORS[detail.insight.insight_type] || TYPE_COLORS.behavioural} />
                <span className="text-[10px] text-slate-400">Objective: {detail.insight.objective_id}</span>
              </div>
              <h3 className="text-base font-bold text-slate-900 leading-snug">{detail.insight.title}</h3>
            </div>

            {detail.insight.executive_summary && (
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Executive Summary</div>
                <p className="text-[13px] text-slate-700 leading-relaxed bg-slate-50 rounded-lg p-3 whitespace-pre-wrap">{detail.insight.executive_summary}</p>
              </div>
            )}

            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Confidence Score</div>
              <ConfidenceBar score={detail.insight.confidence_score} />
              {detail.insight.confidence_rationale && (
                <p className="text-[11px] text-slate-500 mt-1.5 italic">{detail.insight.confidence_rationale}</p>
              )}
            </div>

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
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="border-t border-slate-100 pt-4">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Review Actions</div>
              <div className="flex items-center gap-2 flex-wrap">
                <button onClick={() => onReview("approved")} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 transition-colors">Approve</button>
                <button onClick={() => onReview("rejected")} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors">Reject</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function NodeDrawer({ node, loading, busy, onClose, onReview }: {
  node: StoryNodeEnriched | null; loading: boolean; busy: boolean;
  onClose: () => void; onReview: (status: string) => void;
}) {
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
            <div className="flex items-center gap-2 flex-wrap">
              <Badge label={node.section_type} colors={SECTION_TYPE_COLORS[node.section_type] || SECTION_TYPE_COLORS.transition} />
              <Badge label={node.status} colors={STATUS_COLORS[node.status] || STATUS_COLORS.draft} />
              <span className="text-[10px] text-slate-400 tabular-nums">#{node.order_position}</span>
            </div>

            <div>
              <h3 className="text-base font-bold text-slate-900 leading-snug">{node.title}</h3>
            </div>

            {node.narrative_summary && (
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Narrative Summary</div>
                <p className="text-[13px] text-slate-700 leading-relaxed bg-slate-50 rounded-lg p-3 whitespace-pre-wrap">{node.narrative_summary}</p>
              </div>
            )}

            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Confidence Score</div>
              <ConfidenceBar score={node.confidence_score} />
            </div>

            <div className="flex items-start gap-6">
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Duration</div>
                <span className="text-sm font-bold text-slate-700 tabular-nums">{node.estimated_duration_minutes} min</span>
              </div>
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Insights</div>
                <span className="text-sm font-bold text-slate-700 tabular-nums">{node.insight_count}</span>
              </div>
            </div>

            {node.insights.length > 0 && (
              <div className="border-t border-slate-100 pt-4">
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Supporting Insights ({node.insight_count})</div>
                <div className="space-y-2 max-h-64 overflow-y-auto">
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
            )}

            <div className="border-t border-slate-100 pt-4">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Review Actions</div>
              <div className="flex items-center gap-2 flex-wrap">
                <button onClick={() => onReview("approved")} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 transition-colors">Approve</button>
                <button onClick={() => onReview("rejected")} disabled={busy} className="px-3 py-1.5 text-[11px] font-semibold bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors">Reject</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

export function AnalysisPage({ onNavigate }: { onNavigate: (page: string) => void }) {
  const projectId = useActiveProjectId() ?? 1;

  const [locked, setLocked] = useState<boolean | null>(null);
  const [prereqBlockers, setPrereqBlockers] = useState<string[]>([]);
  const [prereqError, setPrereqError] = useState<string | null>(null);
  const [checkingPrereqs, setCheckingPrereqs] = useState(false);

  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);

  const [insights, setInsights] = useState<Insight[]>([]);
  const [insightsSummary, setInsightsSummary] = useState<InsightsSummary | null>(null);
  const [storylineDetail, setStorylineDetail] = useState<StorylineDetail | null>(null);
  const [storylineSummary, setStorylineSummary] = useState<StorylineSummary | null>(null);
  const [nodes, setNodes] = useState<StoryNodeEnriched[]>([]);
  const [loading, setLoading] = useState(false);

  const [insightsOpen, setInsightsOpen] = useState(true);
  const [storylineOpen, setStorylineOpen] = useState(true);

  const [insightDrawerOpen, setInsightDrawerOpen] = useState(false);
  const [selectedInsightDetail, setSelectedInsightDetail] = useState<InsightDetail | null>(null);
  const [insightDetailLoading, setInsightDetailLoading] = useState(false);

  const [nodeDrawerOpen, setNodeDrawerOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState<StoryNodeEnriched | null>(null);

  const [busyAction, setBusyAction] = useState(false);

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

  const loadInsights = useCallback(async () => {
    try {
      const data = await intelApi.listInsights(projectId);
      setInsights(data);
    } catch { setInsights([]); }
  }, [projectId]);

  const loadInsightsSummary = useCallback(async () => {
    try {
      const s = await intelApi.getInsightsSummary(projectId);
      setInsightsSummary(s);
    } catch { setInsightsSummary(null); }
  }, [projectId]);

  const loadStoryline = useCallback(async () => {
    try {
      const data = await intelApi.getStoryline(projectId);
      if (data.length > 0) {
        const latest = data[data.length - 1];
        const detail = await intelApi.getStorylineDetail(latest.id);
        setStorylineDetail(detail);
        setNodes(detail.nodes.sort((a, b) => a.order_position - b.order_position));
      }
    } catch {
      setStorylineDetail(null);
      setNodes([]);
    }
  }, [projectId]);

  const loadStorylineSummary = useCallback(async () => {
    try {
      const s = await intelApi.getStorylineSummary(projectId);
      setStorylineSummary(s);
    } catch { setStorylineSummary(null); }
  }, [projectId]);

  const loadAllData = useCallback(async () => {
    setLoading(true);
    await Promise.all([loadInsights(), loadInsightsSummary(), loadStoryline(), loadStorylineSummary()]);
    setLoading(false);
  }, [loadInsights, loadInsightsSummary, loadStoryline, loadStorylineSummary]);

  useEffect(() => {
    if (locked === false) {
      loadAllData();
    }
  }, [locked, loadAllData]);

  const handleRunAnalysis = async () => {
    setError(null);
    try {
      setPhase("insights");
      await intelApi.generateInsights(projectId);
      setPhase("storyline");
      await intelApi.generateStoryline(projectId);
      setPhase("done");
      await loadAllData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis generation failed");
      setPhase("idle");
    }
  };

  const openInsightDetail = async (insightId: number) => {
    setInsightDrawerOpen(true);
    setInsightDetailLoading(true);
    setSelectedInsightDetail(null);
    try {
      const d = await intelApi.getInsightDetail(insightId);
      setSelectedInsightDetail(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load insight detail");
    } finally {
      setInsightDetailLoading(false);
    }
  };

  const closeInsightDetail = () => {
    setInsightDrawerOpen(false);
    setSelectedInsightDetail(null);
  };

  const handleReviewInsight = async (insightId: number, status: string) => {
    setBusyAction(true);
    try {
      await intelApi.reviewInsight(insightId, status, "analyst");
      await Promise.all([loadInsights(), loadInsightsSummary()]);
      if (selectedInsightDetail && selectedInsightDetail.insight.id === insightId) {
        const d = await intelApi.getInsightDetail(insightId);
        setSelectedInsightDetail(d);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Review action failed");
    } finally {
      setBusyAction(false);
    }
  };

  const openNodeDetail = (node: StoryNodeEnriched) => {
    setNodeDrawerOpen(true);
    setSelectedNode(node);
  };

  const closeNodeDetail = () => {
    setNodeDrawerOpen(false);
    setSelectedNode(null);
  };

  const handleReviewNode = async (nodeId: number, status: string) => {
    setBusyAction(true);
    try {
      await intelApi.reviewNode(nodeId, status, "analyst");
      await Promise.all([loadStoryline(), loadStorylineSummary()]);
      if (selectedNode && selectedNode.id === nodeId) {
        const updated = nodes.find((n) => n.id === nodeId);
        if (updated) setSelectedNode(updated);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Review action failed");
    } finally {
      setBusyAction(false);
    }
  };

  const handleApproveStoryline = async () => {
    if (!storylineDetail) return;
    setBusyAction(true);
    try {
      await intelApi.approveStoryline(storylineDetail.storyline.id, "analyst");
      await Promise.all([loadStoryline(), loadStorylineSummary()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approve failed");
    } finally {
      setBusyAction(false);
    }
  };

  const handleRejectStoryline = async () => {
    if (!storylineDetail) return;
    setBusyAction(true);
    try {
      await intelApi.rejectStoryline(storylineDetail.storyline.id, "analyst");
      await Promise.all([loadStoryline(), loadStorylineSummary()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reject failed");
    } finally {
      setBusyAction(false);
    }
  };

  const handleValidateStoryline = async () => {
    if (!storylineDetail) return;
    setBusyAction(true);
    try {
      await intelApi.validateStoryline(storylineDetail.storyline.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Validation failed");
    } finally {
      setBusyAction(false);
    }
  };

  if (locked === null) {
    return <div className="max-w-6xl mx-auto px-8 py-10"><div className="text-[13px] text-slate-400">Loading Analysis...</div></div>;
  }

  if (locked) {
    return (
      <div className="max-w-4xl mx-auto px-8 py-10">
        <div className="mb-6">
          <h1 className="text-xl font-bold text-slate-900">Analysis</h1>
          <p className="text-[13px] text-slate-400 mt-1">Insights and narrative structure from your research</p>
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
            <p className="text-[12px] text-slate-400 max-w-sm mx-auto mb-4">Complete Research Execution before running analysis.</p>
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

  const isRunning = phase === "insights" || phase === "storyline";

  return (
    <div className="max-w-6xl mx-auto px-8 py-10">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Analysis</h1>
          <p className="text-[13px] text-slate-400 mt-1">Insights and narrative structure from your research</p>
        </div>
        <button onClick={handleRunAnalysis} disabled={isRunning} className="flex items-center gap-2 px-4 py-2 text-[12px] font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          <SparkleIcon />
          {isRunning ? "Running..." : "Run Analysis"}
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-[12px] text-red-700 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 font-semibold">&times;</button>
        </div>
      )}

      {isRunning && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm mb-6">
          <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-4">Progress</div>
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              {phase === "insights" ? <SpinnerIcon /> : <CheckIcon />}
              <span className={`text-[13px] font-medium ${phase === "insights" ? "text-blue-600" : "text-emerald-600"}`}>Generating Insights...</span>
            </div>
            <div className="ml-[7px] w-px h-3 bg-slate-200" />
            <div className="flex items-center gap-3">
              {phase === "storyline" ? <SpinnerIcon /> : <span className="w-3.5 h-3.5 rounded-full border-2 border-slate-200" />}
              <span className={`text-[13px] font-medium ${phase === "storyline" ? "text-blue-600" : "text-slate-400"}`}>Building Storyline...</span>
            </div>
          </div>
        </div>
      )}

      {!isRunning && (insightsSummary || storylineSummary) && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <MetricCard label="Total Insights" value={insightsSummary?.total_insights ?? 0} dot="bg-blue-500" />
          <MetricCard label="Avg Confidence" value={insightsSummary ? `${Math.round((insightsSummary.avg_confidence || 0) * 100)}%` : "--"} dot="bg-indigo-500" />
          <MetricCard label="Storyline Nodes" value={storylineSummary?.total_nodes ?? 0} dot="bg-purple-500" />
          <MetricCard label="Duration" value={storylineSummary ? `${storylineSummary.total_duration_minutes} min` : "--"} dot="bg-teal-500" />
        </div>
      )}

      {!isRunning && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm mb-4">
          <button onClick={() => setInsightsOpen(!insightsOpen)} className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-slate-50 transition-colors rounded-t-xl">
            <ChevronIcon open={insightsOpen} />
            <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest">Insights</div>
            {insights.length > 0 && <span className="text-[10px] text-slate-400 font-medium tabular-nums">{insights.length} items</span>}
            <div className="flex-1 border-t border-slate-200" />
          </button>

          {insightsOpen && (
            <div className="px-5 pb-5">
              {loading ? (
                <div className="text-center py-12 text-[12px] text-slate-400">Loading insights...</div>
              ) : insights.length === 0 ? (
                <div className="text-center py-12">
                  <p className="text-[12px] text-slate-400">No insights generated yet. Click "Run Analysis" to begin.</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {insights.map((insight) => (
                    <div key={insight.id} onClick={() => openInsightDetail(insight.id)} className="bg-white border border-slate-200 rounded-xl shadow-sm p-4 flex flex-col gap-3 hover:border-slate-300 cursor-pointer transition-colors">
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge label={insight.insight_type} colors={TYPE_COLORS[insight.insight_type] || TYPE_COLORS.behavioural} />
                        <Badge label={insight.status} colors={STATUS_COLORS[insight.status] || STATUS_COLORS.draft} />
                        <span className="text-[10px] text-slate-400 ml-auto">#{insight.id}</span>
                      </div>
                      <h4 className="text-[13px] font-semibold text-slate-900 leading-snug">{insight.title}</h4>
                      {insight.executive_summary && (
                        <p className="text-[11px] text-slate-500 leading-relaxed line-clamp-2">{insight.executive_summary}</p>
                      )}
                      <div className="w-full">
                        <div className="text-[9px] text-slate-400 uppercase tracking-wide mb-1">Confidence</div>
                        <ConfidenceBar score={insight.confidence_score} />
                      </div>
                      <div className="flex items-center text-[10px] text-slate-400">
                        <span>{insight.evidence_count} evidence</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {!isRunning && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm mb-4">
          <button onClick={() => setStorylineOpen(!storylineOpen)} className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-slate-50 transition-colors rounded-t-xl">
            <ChevronIcon open={storylineOpen} />
            <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest">Storyline</div>
            {nodes.length > 0 && <span className="text-[10px] text-slate-400 font-medium tabular-nums">{nodes.length} nodes</span>}
            <div className="flex-1 border-t border-slate-200" />
          </button>

          {storylineOpen && (
            <div className="px-5 pb-5">
              {storylineDetail && (
                <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 mb-4">
                  <div className="flex items-center gap-3 flex-wrap">
                    <div className="flex-1 min-w-0">
                      <h3 className="text-[13px] font-semibold text-slate-900 truncate">{storylineDetail.storyline.title}</h3>
                      <div className="flex items-center gap-2 mt-1">
                        <Badge label={storylineDetail.storyline.status} colors={STATUS_COLORS[storylineDetail.storyline.status] || STATUS_COLORS.draft} />
                        <span className="text-[10px] text-slate-400">Pattern: {storylineDetail.storyline.narrative_pattern}</span>
                        <span className="text-[10px] text-slate-400">&middot; {storylineDetail.storyline.node_count} nodes</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button onClick={handleApproveStoryline} disabled={busyAction} className="px-3 py-1.5 text-[11px] font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 transition-colors">Approve</button>
                      <button onClick={handleRejectStoryline} disabled={busyAction} className="px-3 py-1.5 text-[11px] font-semibold bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors">Reject</button>
                      <button onClick={handleValidateStoryline} disabled={busyAction} className="px-3 py-1.5 text-[11px] font-semibold text-blue-600 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 disabled:opacity-50 transition-colors">Validate</button>
                    </div>
                  </div>
                </div>
              )}

              {loading ? (
                <div className="text-center py-12 text-[12px] text-slate-400">Loading storyline...</div>
              ) : nodes.length === 0 ? (
                <div className="text-center py-12">
                  <p className="text-[12px] text-slate-400">No storyline generated yet. Click "Run Analysis" to begin.</p>
                </div>
              ) : (
                <div className="space-y-0">
                  {nodes.map((node, idx) => (
                    <div key={node.id}>
                      <div onClick={() => openNodeDetail(node)} className="bg-white border border-slate-200 rounded-xl shadow-sm p-4 flex flex-col gap-3 hover:border-slate-300 cursor-pointer transition-colors">
                        <div className="flex items-center gap-2 flex-wrap">
                          <Badge label={node.section_type} colors={SECTION_TYPE_COLORS[node.section_type] || SECTION_TYPE_COLORS.transition} />
                          <Badge label={node.status} colors={STATUS_COLORS[node.status] || STATUS_COLORS.draft} />
                          <span className="text-[10px] text-slate-400 tabular-nums ml-auto">#{node.order_position}</span>
                        </div>
                        <h4 className="text-[13px] font-semibold text-slate-900 leading-snug">{node.title}</h4>
                        {node.narrative_summary && (
                          <p className="text-[11px] text-slate-500 leading-relaxed line-clamp-2">{node.narrative_summary}</p>
                        )}
                        <div className="w-full">
                          <div className="text-[9px] text-slate-400 uppercase tracking-wide mb-1">Confidence</div>
                          <ConfidenceBar score={node.confidence_score} />
                        </div>
                      </div>
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
          )}
        </div>
      )}

      {insightDrawerOpen && (
        <InsightDrawer
          detail={selectedInsightDetail}
          loading={insightDetailLoading}
          busy={busyAction}
          onClose={closeInsightDetail}
          onReview={(status) => selectedInsightDetail && handleReviewInsight(selectedInsightDetail.insight.id, status)}
        />
      )}

      {nodeDrawerOpen && (
        <NodeDrawer
          node={selectedNode}
          loading={false}
          busy={busyAction}
          onClose={closeNodeDetail}
          onReview={(status) => selectedNode && handleReviewNode(selectedNode.id, status)}
        />
      )}

      <div className="flex items-center justify-between pt-6">
        <button onClick={() => onNavigate("research-execution")} className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors">
          Back to Research Execution
        </button>
        <button onClick={() => onNavigate("deliverables")} className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm">
          Proceed to Deliverables
        </button>
      </div>
    </div>
  );
}

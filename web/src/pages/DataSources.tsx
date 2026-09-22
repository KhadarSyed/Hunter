import { useState, useEffect, useRef } from "react";
import { intelApi } from "../lib/intel-api";
import { useActiveProjectId, useProject } from "../lib/project-context";
import { useDemoState } from "../lib/demo-state";

const V = "#5B2C9D";

interface RQ {
  id: string;
  question: string;
  query: string;
  rationale: string;
}

interface DatasetRecord {
  id: number;
  project_id: number;
  file_name: string;
  record_count: number;
  research_question_id: string | null;
  processing_status: string;
  processing_error: string | null;
  approval_status: string;
  stats: Record<string, any>;
  column_mapping: Record<string, any>;
  preview: Record<string, string>[];
}

interface Props {
  onNavigate: (page: string) => void;
}

function RQCard({
  rq,
  dataset,
  uploading,
  onUpload,
  onApprove,
  onDelete,
  onExpand,
  expanded,
  onEditRQ,
  onDeleteRQ,
}: {
  rq: RQ;
  dataset: DatasetRecord | null;
  uploading: boolean;
  onUpload: (file: File) => void;
  onApprove: () => void;
  onDelete: () => void;
  onExpand: () => void;
  expanded: boolean;
  onEditRQ: (question: string, query: string) => void;
  onDeleteRQ: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [editing, setEditing] = useState(false);
  const [editQuestion, setEditQuestion] = useState(rq.question);
  const [editQuery, setEditQuery] = useState(rq.query);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const isApproved = dataset?.approval_status === "approved";
  const isProcessing = uploading || dataset?.processing_status === "processing";
  const hasData = dataset && dataset.processing_status === "done";
  const stats = dataset?.stats || {};

  const handleSaveEdit = () => {
    if (!editQuestion.trim()) return;
    onEditRQ(editQuestion.trim(), editQuery.trim());
    setEditing(false);
  };

  const handleCancelEdit = () => {
    setEditQuestion(rq.question);
    setEditQuery(rq.query);
    setEditing(false);
  };

  return (
    <div className={`bg-white border rounded-xl shadow-sm transition-all ${
      isApproved ? "border-emerald-200" : hasData ? "border-violet-200" : "border-slate-200"
    }`}>
      {/* Delete confirmation */}
      {showDeleteConfirm && (
        <div className="px-5 py-3 bg-red-50 border-b border-red-100 rounded-t-xl flex items-center justify-between">
          <span className="text-xs text-red-700 font-medium">Delete this research question?</span>
          <div className="flex items-center gap-2">
            <button onClick={() => setShowDeleteConfirm(false)}
              className="text-[11px] font-medium px-3 py-1 rounded-lg text-slate-500 hover:bg-white transition-colors">
              Cancel
            </button>
            <button onClick={() => { onDeleteRQ(); setShowDeleteConfirm(false); }}
              className="text-[11px] font-medium px-3 py-1 rounded-lg bg-red-600 text-white hover:bg-red-700 transition-colors">
              Delete
            </button>
          </div>
        </div>
      )}

      {/* Card header */}
      <div className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0">
            <span className="text-xs font-bold px-2 py-1 rounded shrink-0 mt-0.5 tabular-nums"
              style={{ color: V, background: "#f5f3ff" }}>
              {rq.id}
            </span>
            {editing ? (
              <div className="flex-1 min-w-0 space-y-2">
                <textarea
                  value={editQuestion}
                  onChange={(e) => setEditQuestion(e.target.value)}
                  rows={2}
                  className="w-full text-sm font-semibold text-slate-800 border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:border-violet-400 resize-y"
                />
                <input
                  type="text"
                  value={editQuery}
                  onChange={(e) => setEditQuery(e.target.value)}
                  placeholder="Boolean query (optional)"
                  className="w-full text-[11px] text-slate-500 border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:border-violet-400"
                />
                <div className="flex items-center gap-2">
                  <button onClick={handleSaveEdit}
                    className="text-[11px] font-medium px-3 py-1 rounded-lg text-white transition-colors"
                    style={{ background: V }}>
                    Save
                  </button>
                  <button onClick={handleCancelEdit}
                    className="text-[11px] font-medium px-3 py-1 rounded-lg text-slate-500 hover:bg-slate-100 transition-colors">
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="min-w-0">
                <div className="text-sm font-semibold text-slate-800 leading-snug">{rq.question}</div>
                {rq.query && (
                  <div className="text-[11px] text-slate-500 mt-1 leading-relaxed">{rq.query}</div>
                )}
                <div className="flex items-center gap-2 mt-1.5">
                  {isApproved && (
                    <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded border text-emerald-700 bg-emerald-50 border-emerald-200">
                      Approved
                    </span>
                  )}
                  {hasData && !isApproved && (
                    <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded border text-amber-700 bg-amber-50 border-amber-200">
                      Pending Review
                    </span>
                  )}
                  {isProcessing && (
                    <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded border text-blue-700 bg-blue-50 border-blue-200">
                      Processing
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Action icons */}
          {!editing && (
            <div className="flex items-center gap-1 shrink-0">
              <button onClick={() => { setEditQuestion(rq.question); setEditQuery(rq.query); setEditing(true); }}
                className="w-7 h-7 rounded-lg flex items-center justify-center text-slate-300 hover:text-violet-600 hover:bg-violet-50 transition-colors"
                title="Edit question">
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                </svg>
              </button>
              <button onClick={() => setShowDeleteConfirm(true)}
                className="w-7 h-7 rounded-lg flex items-center justify-center text-slate-300 hover:text-red-500 hover:bg-red-50 transition-colors"
                title="Delete question">
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                isApproved ? "bg-emerald-50" : hasData ? "bg-violet-50" : "bg-slate-50"
              }`}>
                {isApproved ? (
                  <svg className="w-4 h-4 text-emerald-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                ) : hasData ? (
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke={V} strokeWidth="1.5">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Processing spinner */}
        {isProcessing && (
          <div className="mt-4 flex items-center gap-3 px-4 py-3 bg-blue-50 rounded-lg">
            <div className="w-5 h-5 rounded-full border-2 border-blue-200 border-t-blue-600 animate-spin shrink-0" />
            <span className="text-xs text-blue-700">Processing upload... detecting columns, mapping fields, computing statistics</span>
          </div>
        )}

        {/* Upload zone — no data yet */}
        {!hasData && !isProcessing && (
          <label className="block mt-4 cursor-pointer rounded-lg border-2 border-dashed p-6 transition-colors hover:border-[#5B2C9D] hover:bg-[#f5f3ff]"
            style={{ borderColor: "#c4b5fd" }}
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); e.currentTarget.style.borderColor = V; e.currentTarget.style.background = "#f5f3ff"; }}
            onDragLeave={(e) => { e.preventDefault(); e.currentTarget.style.borderColor = "#c4b5fd"; e.currentTarget.style.background = ""; }}
            onDrop={(e) => {
              e.preventDefault(); e.stopPropagation();
              e.currentTarget.style.borderColor = "#c4b5fd"; e.currentTarget.style.background = "";
              const f = e.dataTransfer.files?.[0];
              if (f) onUpload(f);
            }}
          >
            <input ref={inputRef} type="file"
              accept=".csv,.xlsx,.xls"
              style={{ position: "absolute", width: 1, height: 1, opacity: 0, overflow: "hidden", pointerEvents: "none" }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = ""; }}
            />
            <div className="flex flex-col items-center gap-1.5">
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke={V} strokeWidth="1.5">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              <span className="text-xs font-medium" style={{ color: V }}>Drop Meltwater export or click to browse</span>
              <span className="text-[10px] text-slate-400">CSV, XLSX</span>
            </div>
          </label>
        )}

        {/* Dataset summary — has data */}
        {hasData && (
          <div className="mt-4 space-y-3">
            {/* File info row */}
            <div className="flex items-center gap-3 px-4 py-3 bg-slate-50 rounded-lg">
              <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke={V} strokeWidth="1.5">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" />
              </svg>
              <span className="text-xs font-medium text-slate-700 truncate flex-1">{dataset.file_name}</span>
              <span className="text-xs font-bold tabular-nums" style={{ color: V }}>
                {dataset.record_count?.toLocaleString()} records
              </span>
            </div>

            {/* Mini stats grid */}
            <div className="grid grid-cols-3 gap-2">
              {stats.top_sources && (
                <div className="bg-slate-50 rounded-lg px-3 py-2">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wide">Sources</div>
                  <div className="text-xs font-semibold text-slate-700 mt-0.5 tabular-nums">{stats.unique_source_count ?? (Object.keys(stats.top_sources).length >= 10 ? "10+" : Object.keys(stats.top_sources).length)}</div>
                </div>
              )}
              {stats.date_range && (
                <div className="bg-slate-50 rounded-lg px-3 py-2">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wide">Date Range</div>
                  <div className="text-[10px] font-medium text-slate-600 mt-0.5">{stats.date_range.earliest?.slice(0, 10)} — {stats.date_range.latest?.slice(0, 10)}</div>
                </div>
              )}
              {stats.sentiment && (
                <div className="bg-slate-50 rounded-lg px-3 py-2">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wide">Sentiment</div>
                  <div className="flex gap-1.5 mt-1">
                    <span className="text-[10px] font-semibold text-emerald-600">+{stats.sentiment.positive}</span>
                    <span className="text-[10px] font-semibold text-slate-400">{stats.sentiment.neutral}</span>
                    <span className="text-[10px] font-semibold text-red-500">-{stats.sentiment.negative}</span>
                  </div>
                </div>
              )}
            </div>

            {/* Expandable details */}
            {expanded && (
              <div className="space-y-3 pt-2 border-t border-slate-100 animate-fade-in">
                {/* Sheets */}
                {stats.sheets && (
                  <div>
                    <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Sheets ({Object.keys(stats.sheets).length})</div>
                    <div className="grid grid-cols-2 gap-x-6 gap-y-1">
                      {Object.entries(stats.sheets).map(([sheet, count]) => (
                        <div key={sheet} className="flex items-center justify-between text-xs">
                          <span className="text-slate-600 truncate">{sheet}</span>
                          <span className="font-semibold text-slate-700 tabular-nums">{(count as number).toLocaleString()}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Column mapping summary */}
                {dataset.column_mapping?.mapped && (
                  <div>
                    <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">
                      Mapped Fields ({Object.keys(dataset.column_mapping.mapped).length})
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {Object.keys(dataset.column_mapping.mapped).map((f) => (
                        <span key={f} className="text-[10px] font-medium px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">{f}</span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Top sources */}
                {stats.top_sources && (
                  <div>
                    <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Top Sources</div>
                    <div className="space-y-1">
                      {Object.entries(stats.top_sources).slice(0, 5).map(([source, count]) => (
                        <div key={source} className="flex items-center justify-between text-xs">
                          <span className="text-slate-600 truncate">{source}</span>
                          <span className="font-semibold text-slate-700 tabular-nums">{(count as number).toLocaleString()}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Action buttons */}
            <div className="flex items-center gap-2 pt-1">
              {hasData && (
                <button onClick={onExpand}
                  className="text-[11px] font-medium px-3 py-1.5 rounded-lg transition-colors hover:bg-slate-100 text-slate-500">
                  {expanded ? "Show less" : "Show details"}
                </button>
              )}
              <div className="flex-1" />
              {hasData && !isApproved && (
                <>
                  <button onClick={onDelete}
                    className="text-[11px] font-medium px-3 py-1.5 rounded-lg transition-colors hover:bg-red-50 text-red-500">
                    Remove
                  </button>
                  <button onClick={() => inputRef.current?.click()}
                    className="text-[11px] font-medium px-3 py-1.5 rounded-lg border transition-colors hover:bg-slate-50"
                    style={{ color: V, borderColor: "#ddd6fe" }}>
                    Replace
                  </button>
                  <button onClick={onApprove}
                    className="text-[11px] font-medium px-3 py-1.5 rounded-lg text-white transition-all hover:shadow-md"
                    style={{ background: V }}>
                    Approve
                  </button>
                </>
              )}
              {isApproved && (
                <span className="text-[11px] font-medium text-emerald-600 flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M20 6L9 17l-5-5" /></svg>
                  Dataset approved
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function DataSources({ onNavigate }: Props) {
  const projectId = useActiveProjectId();
  const { activeProject } = useProject();
  const demo = useDemoState();

  const [researchQuestions, setResearchQuestions] = useState<RQ[]>([]);
  const [datasets, setDatasets] = useState<Record<string, DatasetRecord>>({});
  const [uploadingRQs, setUploadingRQs] = useState<Set<string>>(new Set());
  const [expandedRQ, setExpandedRQ] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [strategyId, setStrategyId] = useState<number | null>(null);

  const loadData = async () => {
    if (!projectId) return;
    try {
      const stratResult = await intelApi.getStrategy(projectId);
      if (stratResult?.strategy_id) setStrategyId(stratResult.strategy_id as number);
      const strat = (stratResult?.strategy ?? {}) as Record<string, any>;
      const stratRQs: any[] = strat.research_question_queries || [];
      const rqs: RQ[] = stratRQs.map((rq: any) => ({
        id: rq.question_id || "?",
        question: rq.question || "",
        query: rq.query || "",
        rationale: rq.rationale || "",
      }));
      setResearchQuestions(rqs);

      const allDatasets: DatasetRecord[] = await intelApi.getAllDatasets(projectId);
      const dsMap: Record<string, DatasetRecord> = {};
      for (const ds of allDatasets) {
        const rqId = ds.research_question_id;
        if (rqId && (!dsMap[rqId] || ds.id > dsMap[rqId].id)) {
          dsMap[rqId] = ds;
        }
      }
      setDatasets(dsMap);

      const anyApproved = rqs.some((rq) => dsMap[rq.id]?.approval_status === "approved");
      if (anyApproved) demo.setDatasetApproved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load data sources");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, [projectId]);

  const pollUntilDone = async (rqId: string) => {
    if (!projectId) return;
    for (let i = 0; i < 120; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const allDs: DatasetRecord[] = await intelApi.getAllDatasets(projectId);
        const ds = allDs.find((d) => d.research_question_id === rqId);
        if (ds?.processing_status === "done") {
          setDatasets((prev) => ({ ...prev, [rqId]: ds }));
          setUploadingRQs((prev) => { const n = new Set(prev); n.delete(rqId); return n; });
          return;
        }
        if (ds?.processing_status === "error") {
          setError(`${rqId}: ${ds.processing_error || "Processing failed"}`);
          setUploadingRQs((prev) => { const n = new Set(prev); n.delete(rqId); return n; });
          return;
        }
      } catch { /* keep polling */ }
    }
    setError(`${rqId}: Processing timed out`);
    setUploadingRQs((prev) => { const n = new Set(prev); n.delete(rqId); return n; });
  };

  const handleUpload = async (rqId: string, file: File) => {
    if (!projectId) {
      setError("No active project selected");
      return;
    }
    setUploadingRQs((prev) => new Set(prev).add(rqId));
    setError(null);
    try {
      await intelApi.uploadDataset(projectId, file, rqId);
      pollUntilDone(rqId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
      setUploadingRQs((prev) => { const n = new Set(prev); n.delete(rqId); return n; });
    }
  };

  const handleApprove = async (rqId: string) => {
    const ds = datasets[rqId];
    if (!ds) return;
    try {
      await intelApi.approveDataset(ds.id);
      setDatasets((prev) => ({
        ...prev,
        [rqId]: { ...prev[rqId], approval_status: "approved" },
      }));
      demo.setDatasetApproved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    }
  };

  const handleDelete = async (rqId: string) => {
    const ds = datasets[rqId];
    if (!ds) return;
    try {
      await intelApi.deleteDataset(ds.id);
      setDatasets((prev) => {
        const n = { ...prev };
        delete n[rqId];
        return n;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const handleApproveAll = async () => {
    const pending = researchQuestions.filter(
      (rq) => datasets[rq.id]?.processing_status === "done" && datasets[rq.id]?.approval_status !== "approved"
    );
    for (const rq of pending) {
      await handleApprove(rq.id);
    }
  };

  const handleEditRQ = async (rqId: string, question: string, query: string) => {
    if (!strategyId) return;
    try {
      await intelApi.editResearchQuestion(strategyId, rqId, question, query);
      setResearchQuestions((prev) =>
        prev.map((rq) => rq.id === rqId ? { ...rq, question, query } : rq)
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update question");
    }
  };

  const handleDeleteRQ = async (rqId: string) => {
    if (!strategyId) return;
    try {
      await intelApi.deleteResearchQuestion(strategyId, rqId);
      setResearchQuestions((prev) => prev.filter((rq) => rq.id !== rqId));
      setDatasets((prev) => {
        const n = { ...prev };
        delete n[rqId];
        return n;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete question");
    }
  };

  const totalRQs = researchQuestions.length;
  const uploadedCount = researchQuestions.filter((rq) => datasets[rq.id]?.processing_status === "done").length;
  const approvedCount = researchQuestions.filter((rq) => datasets[rq.id]?.approval_status === "approved").length;
  const allUploaded = totalRQs > 0 && uploadedCount === totalRQs;
  const allApproved = totalRQs > 0 && approvedCount === totalRQs;
  const canApproveAll = uploadedCount > approvedCount;

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center space-y-3">
          <div className="w-10 h-10 rounded-full mx-auto border-4 border-slate-200 border-t-violet-600 animate-spin" />
          <p className="text-sm text-slate-500">Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden animate-fade-in">
      {/* Header */}
      <div className="shrink-0 px-8 pt-6 pb-4 border-b border-slate-100">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">Data Sources</h1>
            <p className="text-sm text-slate-500 mt-0.5">
              Upload a dataset for each research question
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* Progress indicator */}
            <div className="flex items-center gap-2">
              <div className="flex gap-1">
                {researchQuestions.map((rq) => {
                  const ds = datasets[rq.id];
                  const isApp = ds?.approval_status === "approved";
                  const hasD = ds?.processing_status === "done";
                  return (
                    <div key={rq.id} className={`w-2.5 h-2.5 rounded-full transition-colors ${
                      isApp ? "bg-emerald-500" : hasD ? "bg-violet-400" : "bg-slate-200"
                    }`} title={`${rq.id}: ${isApp ? "Approved" : hasD ? "Uploaded" : "No data"}`} />
                  );
                })}
              </div>
              <span className="text-xs font-medium tabular-nums" style={{ color: allApproved ? "#059669" : V }}>
                {approvedCount}/{totalRQs} approved
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mx-8 mt-4 bg-red-50 border border-red-200 rounded-lg px-4 py-3 flex items-start gap-2">
          <svg className="w-4 h-4 text-red-500 mt-0.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
          </svg>
          <span className="text-xs text-red-700 flex-1">{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600">
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
          </button>
        </div>
      )}

      {/* No RQs fallback */}
      {researchQuestions.length === 0 && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="text-center space-y-3">
            <div className="w-16 h-16 rounded-2xl mx-auto flex items-center justify-center bg-slate-50">
              <svg className="w-8 h-8 text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
            </div>
            <h3 className="text-base font-semibold text-slate-800">No research questions available</h3>
            <p className="text-sm text-slate-500">Complete the Search Strategy stage first to generate research questions.</p>
            <button onClick={() => onNavigate("search-strategy")}
              className="text-sm font-medium px-4 py-2 rounded-lg text-white" style={{ background: V }}>
              Go to Search Strategy
            </button>
          </div>
        </div>
      )}

      {/* RQ cards */}
      {researchQuestions.length > 0 && (
        <div className="flex-1 min-h-0 overflow-y-auto px-8 py-6">
          <div className="max-w-3xl mx-auto space-y-4">
            {researchQuestions.map((rq) => (
              <RQCard
                key={rq.id}
                rq={rq}
                dataset={datasets[rq.id] || null}
                uploading={uploadingRQs.has(rq.id)}
                onUpload={(file) => handleUpload(rq.id, file)}
                onApprove={() => handleApprove(rq.id)}
                onDelete={() => handleDelete(rq.id)}
                onExpand={() => setExpandedRQ(expandedRQ === rq.id ? null : rq.id)}
                expanded={expandedRQ === rq.id}
                onEditRQ={(question, query) => handleEditRQ(rq.id, question, query)}
                onDeleteRQ={() => handleDeleteRQ(rq.id)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Bottom bar */}
      {researchQuestions.length > 0 && (
        <div className="shrink-0 px-8 py-4 border-t border-slate-200 bg-white">
          <div className="flex items-center justify-between max-w-3xl mx-auto">
            <button onClick={() => onNavigate("search-strategy")}
              className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-700 transition-colors">
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
              Search Strategy
            </button>
            <div className="flex items-center gap-3">
              {canApproveAll && (
                <button onClick={handleApproveAll}
                  className="px-4 py-2 text-sm font-medium text-white rounded-lg transition-all hover:shadow-md"
                  style={{ background: V }}>
                  Approve All ({uploadedCount - approvedCount})
                </button>
              )}
              {allApproved && (
                <span className="text-xs font-medium text-emerald-600 flex items-center gap-1 mr-2">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M20 6L9 17l-5-5" /></svg>
                  All datasets approved
                </span>
              )}
              <button onClick={() => onNavigate("research-execution")}
                className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-700 transition-colors">
                Research Execution
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

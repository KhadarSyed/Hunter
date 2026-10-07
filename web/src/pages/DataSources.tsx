import { useState, useEffect, useRef } from "react";
import { intelApi, type JobStatus } from "../services/intel-api";
import { useActiveProjectId, useProject } from "../context/project-context";
import { useDemoState } from "../context/demo-state";
import { EnrichedArticlesTable, loadThreshold, reviewQueueOf } from "../components/EnrichedArticlesTable";
import type { EnrichedRecord } from "../services/intel-api";

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
  enrichment_status: string | null;
  enrichment_error: string | null;
  stats: Record<string, any>;
  column_mapping: Record<string, any>;
  preview: Record<string, string>[];
}

interface EnrichLogEntry {
  message: string;
  pct: number | null;
}

interface Props {
  onNavigate: (page: string) => void;
}

/** "RQ{n+1}" after the highest existing RQn — mirrors the backend's numbering. */
function nextRqId(rqs: RQ[]): string {
  const nums = rqs.map((r) => Number(/^RQ(\d+)$/.exec(r.id)?.[1] ?? 0));
  return `RQ${Math.max(0, ...nums) + 1}`;
}

function AddRQCard({ nextId, onAdd }: { nextId: string; onAdd: (question: string, query: string) => Promise<boolean> }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const canSave = question.trim().length > 0 && !saving;

  const save = async () => {
    if (!canSave) return;
    setSaving(true);
    const ok = await onAdd(question.trim(), query.trim());
    setSaving(false);
    if (ok) { setQuestion(""); setQuery(""); setOpen(false); }
  };

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}
        className="w-full rounded-xl border-2 border-dashed px-5 py-4 text-sm font-medium transition-colors hover:bg-[#f5f3ff]"
        style={{ borderColor: "#c4b5fd", color: V }}>
        + Add research question
      </button>
    );
  }
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-3">
      <div className="text-xs font-semibold" style={{ color: V }}>{nextId} — new research question</div>
      <label className="block text-xs font-medium text-slate-600">
        Research question
        <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={2} maxLength={1000}
          placeholder="e.g. How much of category coverage is celebrity-led?"
          className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-200" />
      </label>
      <label className="block text-xs font-medium text-slate-600">
        Meltwater query (optional)
        <textarea value={query} onChange={(e) => setQuery(e.target.value)} rows={2} maxLength={10000}
          placeholder={'e.g. ("baby skincare" OR "baby lotion") AND celebrity'}
          className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-200" />
      </label>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={() => setOpen(false)}
          className="text-sm px-3 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100">Cancel</button>
        <button type="button" onClick={save} disabled={!canSave}
          className="text-sm px-4 py-1.5 rounded-lg text-white disabled:opacity-50" style={{ background: V }}>
          {saving ? "Adding…" : "Add question"}
        </button>
      </div>
    </div>
  );
}

function RQCard({
  rq,
  datasets,
  uploading,
  onUpload,
  onApprove,
  onDelete,
  expandedId,
  onToggleExpand,
  onEditRQ,
  onDeleteRQ,
  onEnrich,
  enrichingIds,
  enrichLogs,
}: {
  rq: RQ;
  /** Every file uploaded for this RQ, not just the latest — a research question can
   * now hold multiple datasets (e.g. one export per media type) instead of one. */
  datasets: DatasetRecord[];
  uploading: boolean;
  onUpload: (files: File[]) => void;
  onApprove: (datasetId: number) => void;
  onDelete: (datasetId: number) => void;
  expandedId: number | null;
  onToggleExpand: (datasetId: number) => void;
  onEditRQ: (question: string, query: string) => void;
  onDeleteRQ: () => void;
  onEnrich: (datasetId: number) => void;
  enrichingIds: Set<number>;
  enrichLogs: Record<number, EnrichLogEntry[]>;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [editing, setEditing] = useState(false);
  const [editQuestion, setEditQuestion] = useState(rq.question);
  const [editQuery, setEditQuery] = useState(rq.query);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const doneDatasets = datasets.filter((d) => d.processing_status === "done");
  const failedDatasets = datasets.filter((d) => d.processing_status === "error");
  const isApproved = doneDatasets.some((d) => d.approval_status === "approved");
  const isProcessing = uploading || datasets.some((d) => d.processing_status === "processing");
  const hasData = doneDatasets.length > 0;

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

        {/* Upload zone — stays visible even once files exist, so a research question
            can hold more than one dataset (e.g. one export per media type). */}
        {!isProcessing && (
          <label className={`block cursor-pointer rounded-lg border-2 border-dashed transition-colors hover:border-[#5B2C9D] hover:bg-[#f5f3ff] ${hasData ? "mt-3 p-3" : "mt-4 p-6"}`}
            style={{ borderColor: "#c4b5fd" }}
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); e.currentTarget.style.borderColor = V; e.currentTarget.style.background = "#f5f3ff"; }}
            onDragLeave={(e) => { e.preventDefault(); e.currentTarget.style.borderColor = "#c4b5fd"; e.currentTarget.style.background = ""; }}
            onDrop={(e) => {
              e.preventDefault(); e.stopPropagation();
              e.currentTarget.style.borderColor = "#c4b5fd"; e.currentTarget.style.background = "";
              const files = Array.from(e.dataTransfer.files || []);
              if (files.length) onUpload(files);
            }}
          >
            <input ref={inputRef} type="file" multiple
              accept=".csv,.xlsx,.xls"
              style={{ position: "absolute", width: 1, height: 1, opacity: 0, overflow: "hidden", pointerEvents: "none" }}
              onChange={(e) => { const files = Array.from(e.target.files || []); if (files.length) onUpload(files); e.target.value = ""; }}
            />
            <div className="flex flex-col items-center gap-1.5">
              <svg className={hasData ? "w-4 h-4" : "w-5 h-5"} viewBox="0 0 24 24" fill="none" stroke={V} strokeWidth="1.5">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              <span className="text-xs font-medium" style={{ color: V }}>
                {hasData ? "Add more files" : "Drop Meltwater exports (one or more) or click to browse"}
              </span>
              {!hasData && <span className="text-[10px] text-slate-400">CSV, XLSX</span>}
            </div>
          </label>
        )}

        {/* Files that failed to process stay visible (with the reason) until removed */}
        {failedDatasets.map((dataset) => (
          <div key={dataset.id} className="mt-3 flex items-start gap-3 px-4 py-3 bg-red-50 border border-red-100 rounded-lg">
            <span className="text-xs font-medium text-slate-700 truncate">{dataset.file_name}</span>
            <span className="text-xs text-red-600 flex-1">{dataset.processing_error || "Processing failed"}</span>
            <button onClick={() => onDelete(dataset.id)} className="text-xs font-medium text-red-600 hover:text-red-700 shrink-0">
              Remove
            </button>
          </div>
        ))}

        {/* Dataset summaries — one per uploaded file */}
        {doneDatasets.map((dataset) => {
          const expanded = expandedId === dataset.id;
          const dsApproved = dataset.approval_status === "approved";
          const stats = dataset.stats || {};
          return (
        <div key={dataset.id} className="mt-3 space-y-3">
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
              {stats.media_types && (
                <div className="bg-slate-50 rounded-lg px-3 py-2">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wide">Media Types</div>
                  <div className="flex flex-wrap gap-x-2 gap-y-0.5 mt-0.5">
                    {Object.entries(stats.media_types as Record<string, number>).slice(0, 3).map(([type, count]) => (
                      <span key={type} className="text-[10px] font-semibold text-slate-700 tabular-nums">{type} {count}</span>
                    ))}
                  </div>
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

                {/* Media type breakdown — confirms article/post segregation to the user,
                    including when it came from the LLM's domain-based inference rather
                    than an explicit column in the uploaded file. */}
                {stats.media_types && Object.keys(stats.media_types).length > 1 && (
                  <div>
                    <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Media Type Breakdown</div>
                    <div className="space-y-1">
                      {Object.entries(stats.media_types as Record<string, number>).map(([type, count]) => (
                        <div key={type} className="flex items-center justify-between text-xs">
                          <span className="text-slate-600">{type}</span>
                          <span className="font-semibold text-slate-700 tabular-nums">{count.toLocaleString()}</span>
                        </div>
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
              <button onClick={() => onToggleExpand(dataset.id)}
                className="text-[11px] font-medium px-3 py-1.5 rounded-lg transition-colors hover:bg-slate-100 text-slate-500">
                {expanded ? "Show less" : "Show details"}
              </button>
              <div className="flex-1" />
              {!dsApproved && (
                <>
                  <button onClick={() => onDelete(dataset.id)}
                    className="text-[11px] font-medium px-3 py-1.5 rounded-lg transition-colors hover:bg-red-50 text-red-500">
                    Remove
                  </button>
                  <button onClick={() => onApprove(dataset.id)}
                    className="text-[11px] font-medium px-3 py-1.5 rounded-lg text-white transition-all hover:shadow-md"
                    style={{ background: V }}>
                    Approve
                  </button>
                </>
              )}
              {dsApproved && (
                <span className="text-[11px] font-medium text-emerald-600 flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M20 6L9 17l-5-5" /></svg>
                  Dataset approved
                </span>
              )}
            </div>

            {/* Enrichment — tags every record with sentiment/themes/entities/brand
                scores via batched LLM calls; results surface in the Review tab. */}
            <div className="pt-1">
              {enrichingIds.has(dataset.id) ? (
                <div className="bg-violet-50 border border-violet-100 rounded-lg px-4 py-3 space-y-1.5">
                  <div className="flex items-center gap-2">
                    <div className="w-3.5 h-3.5 rounded-full border-2 border-violet-200 border-t-violet-600 animate-spin shrink-0" />
                    <span className="text-xs font-medium text-violet-700">
                      {(enrichLogs[dataset.id] || []).slice(-1)[0]?.message || "Starting enrichment..."}
                    </span>
                  </div>
                  <div className="max-h-28 overflow-y-auto space-y-0.5 pl-5">
                    {(enrichLogs[dataset.id] || []).slice(0, -1).reverse().map((e, i) => (
                      <div key={i} className="text-[10px] text-violet-400">{e.message}</div>
                    ))}
                  </div>
                </div>
              ) : dataset.enrichment_status === "done" ? (
                <span className="text-[11px] font-medium text-violet-600 flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 3l1.9 4.5L18 9l-4.1 1.5L12 15l-1.9-4.5L6 9l4.1-1.5z" /></svg>
                  Enriched — see the Review tab
                </span>
              ) : (
                <button onClick={() => onEnrich(dataset.id)}
                  className="flex items-center gap-1.5 text-[11px] font-medium px-3 py-1.5 rounded-lg border transition-colors hover:bg-violet-50"
                  style={{ color: V, borderColor: "#ddd6fe" }}>
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 3l1.9 4.5L18 9l-4.1 1.5L12 15l-1.9-4.5L6 9l4.1-1.5z" /></svg>
                  {dataset.enrichment_status === "error" ? "Retry Enrich" : "Enrich"}
                </button>
              )}
              {dataset.enrichment_status === "error" && !enrichingIds.has(dataset.id) && (
                <div className="text-[10px] text-red-500 mt-1">{dataset.enrichment_error}</div>
              )}
            </div>
        </div>
          );
        })}
      </div>
    </div>
  );
}

interface ReviewSummary {
  total: number;
  approved: number;
  autoAccepted: number;
  needsReview: number;
  excluded: number;
}

/** Same rules as the proceed gate: disapproved/irrelevant rows are excluded, manually approved rows count,
 * and the rest split by the confidence threshold into auto-accepted vs needs-review. */
function summarizeReview(records: EnrichedRecord[], threshold: number): ReviewSummary {
  const summary: ReviewSummary = { total: records.length, approved: 0, autoAccepted: 0, needsReview: 0, excluded: 0 };
  for (const r of records) {
    if (r.approval_status === "disapproved" || r.review_status === "irrelevant") summary.excluded += 1;
    else if (r.approval_status === "approved") summary.approved += 1;
    else if (reviewQueueOf(r, threshold) === "auto_accepted") summary.autoAccepted += 1;
    else summary.needsReview += 1;
  }
  return summary;
}

function reviewSummaryText(s: ReviewSummary): string {
  return `${s.total} articles — ${s.approved} approved, ${s.autoAccepted} auto-accepted, ${s.needsReview} need review, ${s.excluded} excluded.`;
}

export function DataSources({ onNavigate }: Props) {
  const projectId = useActiveProjectId();
  const { activeProject } = useProject();
  const demo = useDemoState();

  const [researchQuestions, setResearchQuestions] = useState<RQ[]>([]);
  // Every file uploaded for a research question, not just the latest.
  const [datasets, setDatasets] = useState<Record<string, DatasetRecord[]>>({});
  const [uploadingRQs, setUploadingRQs] = useState<Set<string>>(new Set());
  const [expandedDatasetId, setExpandedDatasetId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [strategyId, setStrategyId] = useState<number | null>(null);

  // Enrichment — datasets currently running, per-dataset streaming log, and
  // the aggregated Review tab (every enriched record across every dataset).
  const [mainTab, setMainTab] = useState<"sources" | "review">("sources");
  const [enrichingIds, setEnrichingIds] = useState<Set<number>>(new Set());
  const [enrichLogs, setEnrichLogs] = useState<Record<number, EnrichLogEntry[]>>({});
  const [reviewRecords, setReviewRecords] = useState<import("../services/intel-api").EnrichedRecord[]>([]);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [showProceedConfirm, setShowProceedConfirm] = useState(false);
  const [proceedBlockedMsg, setProceedBlockedMsg] = useState<string | null>(null);

  const hasAnyEnriched = Object.values(datasets).some((list) => list.some((d) => d.enrichment_status === "done"));

  // Article-level review gate — separate from (and in addition to) the dataset-level
  // approval gate above. An analyst can approve every uploaded dataset without ever having
  // reviewed/approved a single tagged article, so this checks the Review tab's own
  // approval_status independently: only enforced when there IS enriched data to review at
  // all (hasAnyEnriched) — a project that hasn't enriched anything yet isn't blocked by a
  // gate about a review step it has no way to have done.
  const reviewSummary = summarizeReview(reviewRecords, loadThreshold());

  const handleRequestProceed = async () => {
    // Re-fetch and use the returned records directly, rather than the articleApprovedCount
    // closed over at render time — setReviewRecords's update wouldn't be visible to this
    // function invocation until the next render, so reading the outer const straight after
    // awaiting loadReview() would still see its pre-fetch (possibly stale) value.
    const fresh = await loadReview();
    const records = fresh ?? reviewRecords;
    // Auto-accepted rows (above the confidence threshold, not disapproved) count like approved ones.
    const freshSummary = summarizeReview(records, loadThreshold());
    if (hasAnyEnriched && freshSummary.approved + freshSummary.autoAccepted === 0) {
      setProceedBlockedMsg(
        "At least 1 article must be approved or auto-accepted (at or above the confidence threshold) in the Review tab before you can proceed to Research Execution."
      );
      return;
    }
    setShowProceedConfirm(true);
  };

  const groupByRQ = (allDatasets: DatasetRecord[]): Record<string, DatasetRecord[]> => {
    const grouped: Record<string, DatasetRecord[]> = {};
    for (const ds of allDatasets) {
      const rqId = ds.research_question_id;
      if (!rqId) continue;
      (grouped[rqId] ??= []).push(ds);
    }
    for (const rqId of Object.keys(grouped)) {
      grouped[rqId].sort((a, b) => a.id - b.id);
    }
    return grouped;
  };

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
      const grouped = groupByRQ(allDatasets);
      setDatasets(grouped);

      const anyApproved = rqs.some((rq) => grouped[rq.id]?.some((d) => d.approval_status === "approved"));
      if (anyApproved) demo.setDatasetApproved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load data sources");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, [projectId]);
  // Loaded eagerly (not only on first Review-tab visit) so the proceed-to-Research-Execution
  // gate below has real approved/disapproved counts even if the analyst never opened Review.
  useEffect(() => { loadReview(); }, [projectId]);

  const pollUntilDone = async (rqId: string, datasetId: number) => {
    if (!projectId) return;
    for (let i = 0; i < 120; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const allDs: DatasetRecord[] = await intelApi.getAllDatasets(projectId);
        const ds = allDs.find((d) => d.id === datasetId);
        if (ds?.processing_status === "done") {
          setDatasets((prev) => ({
            ...prev,
            [rqId]: [...(prev[rqId] || []).filter((d) => d.id !== datasetId), ds],
          }));
          return;
        }
        if (ds?.processing_status === "error") {
          setDatasets((prev) => ({
            ...prev,
            [rqId]: [...(prev[rqId] || []).filter((d) => d.id !== datasetId), ds],
          }));
          appendError(`${rqId}: ${ds.processing_error || "Processing failed"}`);
          return;
        }
      } catch { /* keep polling */ }
    }
    appendError(`${rqId}: Processing timed out`);
  };

  /** Several files can fail in one batch — keep every message instead of the last one winning. */
  const appendError = (msg: string) => setError((prev) => (prev ? `${prev}; ${msg}` : msg));

  /** Uploads every selected file for one RQ in turn, then waits for all of them to finish processing
   * before clearing the RQ's "processing" state (one failed file doesn't stop the others). */
  const handleUpload = async (rqId: string, files: File[]) => {
    if (!projectId) {
      setError("No active project selected");
      return;
    }
    setUploadingRQs((prev) => new Set(prev).add(rqId));
    setError(null);
    const polls: Promise<void>[] = [];
    for (const file of files) {
      try {
        const result = await intelApi.uploadDataset(projectId, file, rqId);
        polls.push(pollUntilDone(rqId, result.dataset_id));
      } catch (e) {
        appendError(`${file.name}: ${e instanceof Error ? e.message : "Upload failed"}`);
      }
    }
    await Promise.all(polls);
    setUploadingRQs((prev) => { const n = new Set(prev); n.delete(rqId); return n; });
  };

  const handleAddRQ = async (question: string, query: string): Promise<boolean> => {
    if (!strategyId) return false;
    try {
      const { question_id } = await intelApi.addResearchQuestion(strategyId, question, query);
      setResearchQuestions((prev) => [...prev, { id: question_id, question, query, rationale: "" }]);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add research question");
      return false;
    }
  };

  const loadReview = async (): Promise<import("../services/intel-api").EnrichedRecord[] | null> => {
    if (!projectId) return null;
    setReviewLoading(true);
    try {
      const res = await intelApi.getProjectEnriched(projectId);
      setReviewRecords(res.records);
      return res.records;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load enriched articles");
      return null;
    } finally {
      setReviewLoading(false);
    }
  };

  const handleEnrich = async (rqId: string, datasetId: number) => {
    setEnrichingIds((prev) => new Set(prev).add(datasetId));
    setEnrichLogs((prev) => ({ ...prev, [datasetId]: [{ message: "Starting enrichment...", pct: 0 }] }));
    setError(null);
    try {
      const { job_id } = await intelApi.enrichDataset(datasetId);
      for (let i = 0; i < 300; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const status: JobStatus = await intelApi.getJob(job_id);
        if (status.progress_message) {
          setEnrichLogs((prev) => {
            const log = prev[datasetId] || [];
            if (log[log.length - 1]?.message === status.progress_message) return prev;
            return { ...prev, [datasetId]: [...log, { message: status.progress_message!, pct: status.progress_pct }].slice(-30) };
          });
        }
        if (status.status === "completed") {
          setDatasets((prev) => ({
            ...prev,
            [rqId]: (prev[rqId] || []).map((d) => d.id === datasetId ? { ...d, enrichment_status: "done" } : d),
          }));
          // Refreshes reviewRecords immediately — without this, the proceed-gate's
          // approved/disapproved counts stay at whatever they were when the page
          // mounted (likely all-zero, before this dataset was even enriched) until the
          // analyst happens to click the Review tab themselves.
          loadReview();
          break;
        }
        if (status.status === "failed") {
          setDatasets((prev) => ({
            ...prev,
            [rqId]: (prev[rqId] || []).map((d) => d.id === datasetId ? { ...d, enrichment_status: "error", enrichment_error: status.error || "Enrichment failed" } : d),
          }));
          break;
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start enrichment");
    } finally {
      setEnrichingIds((prev) => { const n = new Set(prev); n.delete(datasetId); return n; });
    }
  };

  const handleApprove = async (rqId: string, datasetId: number) => {
    try {
      await intelApi.approveDataset(datasetId);
      setDatasets((prev) => ({
        ...prev,
        [rqId]: (prev[rqId] || []).map((d) => d.id === datasetId ? { ...d, approval_status: "approved" } : d),
      }));
      demo.setDatasetApproved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    }
  };

  const handleDelete = async (rqId: string, datasetId: number) => {
    try {
      await intelApi.deleteDataset(datasetId);
      setDatasets((prev) => ({
        ...prev,
        [rqId]: (prev[rqId] || []).filter((d) => d.id !== datasetId),
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const handleApproveAll = async () => {
    for (const rq of researchQuestions) {
      const pending = (datasets[rq.id] || []).filter(
        (d) => d.processing_status === "done" && d.approval_status !== "approved"
      );
      for (const ds of pending) {
        await handleApprove(rq.id, ds.id);
      }
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
  const uploadedCount = researchQuestions.filter((rq) => (datasets[rq.id] || []).some((d) => d.processing_status === "done")).length;
  const approvedCount = researchQuestions.filter((rq) => (datasets[rq.id] || []).some((d) => d.approval_status === "approved")).length;
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
                  const rqDatasets = datasets[rq.id] || [];
                  const isApp = rqDatasets.some((d) => d.approval_status === "approved");
                  const hasD = rqDatasets.some((d) => d.processing_status === "done");
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

      {/* Tabs — Review only appears once something has been enriched; switching
          back to Data Sources always keeps the per-RQ upload/remove/approve flow. */}
      {hasAnyEnriched && (
        <div className="shrink-0 px-8 pt-3 border-b border-slate-100">
          <div className="flex items-center gap-1">
            {(["sources", "review"] as const).map((t) => (
              <button key={t} onClick={() => { setMainTab(t); if (t === "review") loadReview(); }}
                className={`px-4 py-2 text-xs font-medium border-b-2 transition-all -mb-px ${
                  mainTab === t ? "border-current text-[#5B2C9D]" : "border-transparent text-slate-400 hover:text-slate-600"
                }`}>
                {t === "sources" ? "Data Sources" : "Review"}
              </button>
            ))}
          </div>
        </div>
      )}

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

      {mainTab === "review" ? (
        <div className="flex-1 min-h-0 overflow-y-auto">
          <EnrichedArticlesTable records={reviewRecords} loading={reviewLoading} />
        </div>
      ) : (
      <>
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
                datasets={datasets[rq.id] || []}
                uploading={uploadingRQs.has(rq.id)}
                onUpload={(files) => handleUpload(rq.id, files)}
                onApprove={(datasetId) => handleApprove(rq.id, datasetId)}
                onDelete={(datasetId) => handleDelete(rq.id, datasetId)}
                expandedId={expandedDatasetId}
                onToggleExpand={(datasetId) => setExpandedDatasetId(expandedDatasetId === datasetId ? null : datasetId)}
                onEditRQ={(question, query) => handleEditRQ(rq.id, question, query)}
                onDeleteRQ={() => handleDeleteRQ(rq.id)}
                onEnrich={(datasetId) => handleEnrich(rq.id, datasetId)}
                enrichingIds={enrichingIds}
                enrichLogs={enrichLogs}
              />
            ))}
            {strategyId && <AddRQCard nextId={nextRqId(researchQuestions)} onAdd={handleAddRQ} />}
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
              <button onClick={handleRequestProceed}
                className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-700 transition-colors">
                Research Execution
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
              </button>
            </div>
          </div>
        </div>
      )}

      {proceedBlockedMsg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setProceedBlockedMsg(null)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-sm w-full p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 mb-3 text-amber-600">
              <svg className="w-5 h-5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
              <h3 className="text-sm font-semibold">Review required</h3>
            </div>
            <p className="text-sm text-slate-600 mb-4">{proceedBlockedMsg}</p>
            <p className="text-xs text-slate-400 mb-4">
              {reviewSummaryText(reviewSummary)}
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => { setProceedBlockedMsg(null); setMainTab("review"); loadReview(); }}
                className="text-sm font-medium px-4 py-2 rounded-lg text-white" style={{ background: V }}>
                Go to Review
              </button>
            </div>
          </div>
        </div>
      )}

      {showProceedConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setShowProceedConfirm(false)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-sm w-full p-6" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-slate-800 mb-3">Proceed to Research Execution?</h3>
            <p className="text-xs text-slate-500 mb-4">
              {reviewSummary.total} articles — <span className="text-emerald-600 font-medium">{reviewSummary.approved + reviewSummary.autoAccepted} included</span>{" "}
              ({reviewSummary.approved} approved, {reviewSummary.autoAccepted} auto-accepted),{" "}
              <span className="text-amber-600 font-medium">{reviewSummary.needsReview} need review</span>,{" "}
              <span className="text-red-600 font-medium">{reviewSummary.excluded} excluded</span>.
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowProceedConfirm(false)} className="text-sm font-medium px-4 py-2 rounded-lg text-slate-500 hover:bg-slate-100">
                Cancel
              </button>
              <button onClick={() => { setShowProceedConfirm(false); onNavigate("research-execution"); }}
                className="text-sm font-medium px-4 py-2 rounded-lg text-white" style={{ background: V }}>
                Confirm & Proceed
              </button>
            </div>
          </div>
        </div>
      )}
      </>
      )}
    </div>
  );
}

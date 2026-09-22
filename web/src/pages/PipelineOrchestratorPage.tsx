import { useState, useEffect, useCallback } from "react";
import { intelApi } from "../lib/intel-api";
import { useActiveProjectId } from "../lib/project-context";
import type {
  PipelineProjectStatus,
  PipelineStageStatus,
  PipelineLog,
  PipelineTimelineEntry,
  PipelineDependencyNode,
} from "../data/contracts";

const STAGE_LABELS: Record<string, string> = {
  brief_scope: "Brief & Scope",
  background_research: "Background Research",
  search_strategy: "Search Strategy",
  dataset_upload: "Dataset Upload",
  research_planner: "Research Planner",
  research_executor: "Research Executor",
  insight_generator: "Insight Generator",
  storyline_builder: "Storyline Builder",
  si_retrieval: "SI Retrieval",
  presentation_composer: "Presentation Composer",
  pptx_renderer: "PowerPoint Renderer",
};

const STATUS_COLORS: Record<string, string> = {
  completed: "bg-emerald-100 text-emerald-700",
  running: "bg-blue-100 text-blue-700",
  pending: "bg-slate-100 text-slate-500",
  failed: "bg-red-100 text-red-700",
  awaiting_approval: "bg-amber-100 text-amber-700",
  cancelled: "bg-slate-200 text-slate-500",
  paused: "bg-yellow-100 text-yellow-700",
  cached: "bg-violet-100 text-violet-700",
  skipped: "bg-slate-100 text-slate-400",
  not_started: "bg-slate-50 text-slate-400",
  retrying: "bg-orange-100 text-orange-700",
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_COLORS[status] || "bg-slate-100 text-slate-500";
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function PipelineOrchestratorPage({ onNavigate }: { onNavigate: (p: string) => void }) {
  const activeProjectId = useActiveProjectId();
  const [projectId, setProjectId] = useState<number | null>(activeProjectId);
  const [projectIdInput, setProjectIdInput] = useState(String(activeProjectId ?? 1));
  const [status, setStatus] = useState<PipelineProjectStatus | null>(null);
  const [logs, setLogs] = useState<PipelineLog[]>([]);
  const [timeline, setTimeline] = useState<PipelineTimelineEntry[]>([]);
  const [graph, setGraph] = useState<Record<string, PipelineDependencyNode>>({});
  const [tab, setTab] = useState<"stages" | "logs" | "timeline" | "metrics" | "cache">("stages");
  const [loading, setLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState("");
  const [selectedStage, setSelectedStage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!projectId) return;
    try {
      const s = await intelApi.pipelineProjectStatus(projectId);
      setStatus(s);
      if (s.latest_run) {
        const l = await intelApi.pipelineLogs(s.latest_run.id);
        setLogs(l);
        const t = await intelApi.pipelineTimeline(s.latest_run.id);
        setTimeline(t);
      }
    } catch { /* ignore */ }
  }, [projectId]);

  useEffect(() => {
    intelApi.pipelineGraph().then(setGraph).catch(() => {});
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const loadProject = () => {
    const id = parseInt(projectIdInput, 10);
    if (id > 0) {
      setProjectId(id);
      setActionMsg("");
    }
  };

  const runAction = async (fn: () => Promise<any>, label: string) => {
    setLoading(true);
    setActionMsg("");
    try {
      const r = await fn();
      setActionMsg(`${label}: ${r.status || "done"}`);
      await refresh();
    } catch (e: any) {
      setActionMsg(`${label} failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const stageList = status
    ? Object.values(status.stage_statuses).sort((a, b) => a.order - b.order)
    : [];

  const perf = status?.performance;

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-slate-900">Pipeline Orchestrator</h1>
            <span className="px-2 py-0.5 bg-violet-100 text-violet-700 text-[10px] font-bold rounded-full uppercase tracking-wide">
              Orchestration
            </span>
          </div>
          <p className="text-sm text-slate-500 mt-1">
            Coordinate, schedule, and monitor the full intelligence workflow
          </p>
        </div>
      </div>

      {/* Project selector */}
      <div className="bg-white rounded-xl border border-slate-200 p-4 mb-6 flex items-center gap-3">
        <label className="text-sm font-medium text-slate-700">Project ID:</label>
        <input
          type="number"
          value={projectIdInput}
          onChange={e => setProjectIdInput(e.target.value)}
          className="w-24 px-3 py-1.5 border border-slate-200 rounded-lg text-sm"
          min={1}
        />
        <button onClick={loadProject}
          className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700">
          Load
        </button>
        {projectId && (
          <span className="text-sm text-slate-500 ml-2">
            Loaded project #{projectId}
            {status?.latest_run && (
              <> — Latest run: <StatusBadge status={status.latest_run.status} /></>
            )}
          </span>
        )}
      </div>

      {!projectId && (
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
          <p className="text-slate-500 text-sm">Enter a project ID to view its pipeline status</p>
        </div>
      )}

      {projectId && status && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-5 gap-4 mb-6">
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="text-[10px] text-slate-400 font-semibold uppercase tracking-wide mb-1">Stages</div>
              <div className="text-2xl font-bold text-slate-900">{stageList.length}</div>
              <div className="text-xs text-slate-500 mt-0.5">
                {stageList.filter(s => s.status === "completed").length} completed
              </div>
            </div>
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="text-[10px] text-slate-400 font-semibold uppercase tracking-wide mb-1">Total Runs</div>
              <div className="text-2xl font-bold text-slate-900">{perf?.total_runs || 0}</div>
              <div className="text-xs text-slate-500 mt-0.5">
                {perf?.completed_runs || 0} completed, {perf?.failed_runs || 0} failed
              </div>
            </div>
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="text-[10px] text-slate-400 font-semibold uppercase tracking-wide mb-1">Avg Duration</div>
              <div className="text-2xl font-bold text-slate-900">
                {perf?.avg_duration_ms ? `${(perf.avg_duration_ms / 1000).toFixed(1)}s` : "—"}
              </div>
            </div>
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="text-[10px] text-slate-400 font-semibold uppercase tracking-wide mb-1">Cache Entries</div>
              <div className="text-2xl font-bold text-slate-900">{perf?.cache_entries || 0}</div>
              <div className="text-xs text-slate-500 mt-0.5">
                {perf?.cache_hit_ratio != null ? `${(perf.cache_hit_ratio * 100).toFixed(0)}%` : "—"} hit ratio
              </div>
            </div>
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="text-[10px] text-slate-400 font-semibold uppercase tracking-wide mb-1">Current Stage</div>
              <div className="text-lg font-bold text-slate-900 truncate">
                {status.latest_run?.current_stage
                  ? STAGE_LABELS[status.latest_run.current_stage] || status.latest_run.current_stage
                  : "—"}
              </div>
            </div>
          </div>

          {/* Action bar */}
          <div className="bg-white rounded-xl border border-slate-200 p-4 mb-6 flex items-center gap-2 flex-wrap">
            <button
              onClick={() => runAction(() => intelApi.pipelineStart(projectId, "full"), "Full pipeline")}
              disabled={loading}
              className="px-4 py-1.5 bg-violet-600 text-white text-sm font-medium rounded-lg hover:bg-violet-700 disabled:opacity-50">
              Start Full Pipeline
            </button>
            <button
              onClick={() => runAction(() => intelApi.pipelineStart(projectId, "changed"), "Changed stages")}
              disabled={loading}
              className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50">
              Run Changed
            </button>
            {status.latest_run && ["paused", "awaiting_approval"].includes(status.latest_run.status) && (
              <button
                onClick={() => runAction(() => intelApi.pipelineResume(status.latest_run!.id), "Resume")}
                disabled={loading}
                className="px-4 py-1.5 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 disabled:opacity-50">
                Resume Pipeline
              </button>
            )}
            {status.latest_run && status.latest_run.status === "running" && (
              <button
                onClick={() => runAction(() => intelApi.pipelinePause(status.latest_run!.id), "Pause")}
                disabled={loading}
                className="px-4 py-1.5 bg-yellow-500 text-white text-sm font-medium rounded-lg hover:bg-yellow-600 disabled:opacity-50">
                Pause
              </button>
            )}
            {status.latest_run && !["completed", "cancelled"].includes(status.latest_run.status) && (
              <button
                onClick={() => runAction(() => intelApi.pipelineCancel(status.latest_run!.id), "Cancel")}
                disabled={loading}
                className="px-3 py-1.5 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 disabled:opacity-50">
                Cancel
              </button>
            )}
            <button
              onClick={() => runAction(() => intelApi.pipelineClearCache(projectId), "Clear cache")}
              disabled={loading}
              className="px-3 py-1.5 border border-slate-200 text-slate-600 text-sm font-medium rounded-lg hover:bg-slate-50 disabled:opacity-50">
              Clear Cache
            </button>
            <button onClick={refresh} disabled={loading}
              className="px-3 py-1.5 border border-slate-200 text-slate-600 text-sm font-medium rounded-lg hover:bg-slate-50 disabled:opacity-50 ml-auto">
              Refresh
            </button>
            {actionMsg && (
              <span className={`text-xs ml-2 ${actionMsg.includes("fail") ? "text-red-600" : "text-emerald-600"}`}>
                {actionMsg}
              </span>
            )}
          </div>

          {/* Progress bar */}
          {status.latest_run && status.latest_run.status === "running" && (
            <div className="bg-white rounded-xl border border-slate-200 p-4 mb-6">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-slate-700">Progress</span>
                <span className="text-sm text-slate-500">{status.latest_run.progress_pct.toFixed(0)}%</span>
              </div>
              <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                <div className="h-full bg-violet-500 rounded-full transition-all"
                  style={{ width: `${status.latest_run.progress_pct}%` }} />
              </div>
            </div>
          )}

          {/* Tabs */}
          <div className="flex gap-1 mb-4 border-b border-slate-200">
            {(["stages", "logs", "timeline", "metrics", "cache"] as const).map(t => (
              <button key={t} onClick={() => setTab(t)}
                className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                  tab === t
                    ? "border-violet-600 text-violet-700"
                    : "border-transparent text-slate-500 hover:text-slate-700"
                }`}>
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>

          <div className="flex gap-6">
            {/* Main content */}
            <div className="flex-1 min-w-0">
              {tab === "stages" && (
                <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-slate-50 border-b border-slate-200">
                        <th className="text-left px-4 py-2 text-[10px] uppercase text-slate-400 font-semibold">#</th>
                        <th className="text-left px-4 py-2 text-[10px] uppercase text-slate-400 font-semibold">Stage</th>
                        <th className="text-left px-4 py-2 text-[10px] uppercase text-slate-400 font-semibold">Status</th>
                        <th className="text-left px-4 py-2 text-[10px] uppercase text-slate-400 font-semibold">Dependencies</th>
                        <th className="text-right px-4 py-2 text-[10px] uppercase text-slate-400 font-semibold">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stageList.map(stage => (
                        <tr key={stage.stage_id}
                          className={`border-b border-slate-100 hover:bg-slate-50 cursor-pointer ${
                            selectedStage === stage.stage_id ? "bg-violet-50" : ""
                          }`}
                          onClick={() => setSelectedStage(
                            selectedStage === stage.stage_id ? null : stage.stage_id
                          )}>
                          <td className="px-4 py-2.5 text-slate-400 font-mono text-xs">{stage.order}</td>
                          <td className="px-4 py-2.5 font-medium text-slate-800">{stage.name}</td>
                          <td className="px-4 py-2.5"><StatusBadge status={stage.status} /></td>
                          <td className="px-4 py-2.5 text-xs text-slate-500">
                            {graph[stage.stage_id]?.dependencies.map(d => STAGE_LABELS[d] || d).join(", ") || "—"}
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <button
                              onClick={e => { e.stopPropagation(); runAction(() => intelApi.pipelineRunStage(projectId, stage.stage_id), `Run ${stage.name}`); }}
                              className="px-2 py-0.5 text-[11px] text-violet-600 border border-violet-200 rounded hover:bg-violet-50">
                              Run
                            </button>
                            {stage.status === "failed" && status.latest_run && (
                              <button
                                onClick={e => { e.stopPropagation(); runAction(() => intelApi.pipelineRetry(status.latest_run!.id, stage.stage_id), `Retry ${stage.name}`); }}
                                className="px-2 py-0.5 text-[11px] text-orange-600 border border-orange-200 rounded hover:bg-orange-50 ml-1">
                                Retry
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {tab === "logs" && (
                <div className="bg-white rounded-xl border border-slate-200 p-4 max-h-[500px] overflow-y-auto">
                  {logs.length === 0 ? (
                    <p className="text-sm text-slate-400 text-center py-8">No logs yet</p>
                  ) : (
                    <div className="space-y-1 font-mono text-xs">
                      {logs.map(log => (
                        <div key={log.id} className={`flex gap-2 py-0.5 ${
                          log.level === "error" ? "text-red-600" : "text-slate-600"
                        }`}>
                          <span className="text-slate-400 shrink-0 w-20">
                            {new Date(log.created_at * 1000).toLocaleTimeString()}
                          </span>
                          <span className={`shrink-0 w-12 uppercase text-[10px] font-bold ${
                            log.level === "error" ? "text-red-500" : log.level === "warn" ? "text-amber-500" : "text-slate-400"
                          }`}>{log.level}</span>
                          {log.stage_id && (
                            <span className="text-violet-500 shrink-0">[{STAGE_LABELS[log.stage_id] || log.stage_id}]</span>
                          )}
                          <span>{log.message}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {tab === "timeline" && (
                <div className="bg-white rounded-xl border border-slate-200 p-4">
                  {timeline.length === 0 ? (
                    <p className="text-sm text-slate-400 text-center py-8">No timeline data</p>
                  ) : (
                    <div className="space-y-2">
                      {timeline.map(entry => (
                        <div key={entry.stage_id} className="flex items-center gap-3">
                          <div className="w-40 text-sm font-medium text-slate-700 truncate">
                            {entry.stage_name}
                          </div>
                          <StatusBadge status={entry.status} />
                          <div className="flex-1 h-5 bg-slate-50 rounded relative overflow-hidden">
                            {entry.execution_time_ms > 0 && (
                              <div className={`h-full rounded ${
                                entry.cache_status === "hit" ? "bg-violet-200" : "bg-blue-200"
                              }`} style={{
                                width: `${Math.min(100, Math.max(5, entry.execution_time_ms / 50))}%`
                              }} />
                            )}
                          </div>
                          <span className="text-xs text-slate-400 w-16 text-right">
                            {entry.execution_time_ms > 0 ? `${entry.execution_time_ms}ms` : "—"}
                          </span>
                          {entry.cache_status === "hit" && (
                            <span className="text-[10px] text-violet-500 font-medium">CACHED</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {tab === "metrics" && perf && (
                <div className="space-y-4">
                  <div className="bg-white rounded-xl border border-slate-200 p-4">
                    <h3 className="text-sm font-semibold text-slate-700 mb-3">Stage Average Execution Time</h3>
                    {Object.keys(perf.stage_averages).length === 0 ? (
                      <p className="text-sm text-slate-400">No metrics yet</p>
                    ) : (
                      <div className="space-y-2">
                        {Object.entries(perf.stage_averages)
                          .sort(([, a], [, b]) => b.avg_ms - a.avg_ms)
                          .map(([stageId, data]) => (
                            <div key={stageId} className="flex items-center gap-3">
                              <div className="w-48 text-sm text-slate-700 truncate">
                                {STAGE_LABELS[stageId] || stageId}
                              </div>
                              <div className="flex-1 h-4 bg-slate-50 rounded overflow-hidden">
                                <div className="h-full bg-blue-300 rounded"
                                  style={{
                                    width: `${Math.min(100, data.avg_ms / 20)}%`
                                  }} />
                              </div>
                              <span className="text-xs text-slate-500 w-20 text-right">
                                {data.avg_ms > 1000
                                  ? `${(data.avg_ms / 1000).toFixed(1)}s`
                                  : `${Math.round(data.avg_ms)}ms`}
                              </span>
                              <span className="text-[10px] text-slate-400 w-12 text-right">
                                {data.runs} run{data.runs !== 1 ? "s" : ""}
                              </span>
                            </div>
                          ))}
                      </div>
                    )}
                  </div>
                  <div className="bg-white rounded-xl border border-slate-200 p-4">
                    <h3 className="text-sm font-semibold text-slate-700 mb-3">Cache Performance</h3>
                    <div className="grid grid-cols-3 gap-4">
                      {Object.entries(perf.cache_breakdown).map(([status, count]) => (
                        <div key={status} className="text-center">
                          <div className="text-xl font-bold text-slate-900">{count}</div>
                          <div className="text-[10px] text-slate-400 uppercase">{status}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {tab === "cache" && (
                <div className="bg-white rounded-xl border border-slate-200 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold text-slate-700">Cache Entries</h3>
                    <button
                      onClick={() => runAction(() => intelApi.pipelineClearCache(projectId), "Clear all cache")}
                      className="text-xs text-red-500 hover:text-red-700">Clear All</button>
                  </div>
                  {perf?.cache_entries === 0 ? (
                    <p className="text-sm text-slate-400 text-center py-8">No cache entries</p>
                  ) : (
                    <p className="text-sm text-slate-500">{perf?.cache_entries || 0} cached stage outputs</p>
                  )}
                </div>
              )}
            </div>

            {/* Stage inspector */}
            {selectedStage && (
              <div className="w-80 shrink-0">
                <div className="bg-white rounded-xl border border-slate-200 p-4 sticky top-6">
                  <h3 className="text-sm font-semibold text-slate-900 mb-3">
                    {STAGE_LABELS[selectedStage] || selectedStage}
                  </h3>
                  {(() => {
                    const st = status.stage_statuses[selectedStage];
                    const dep = graph[selectedStage];
                    if (!st) return null;
                    return (
                      <div className="space-y-3 text-sm">
                        <div>
                          <div className="text-[10px] text-slate-400 uppercase font-semibold mb-1">Status</div>
                          <StatusBadge status={st.status} />
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-400 uppercase font-semibold mb-1">Order</div>
                          <span className="text-slate-700">Stage {st.order} of 13</span>
                        </div>
                        {dep && dep.dependencies.length > 0 && (
                          <div>
                            <div className="text-[10px] text-slate-400 uppercase font-semibold mb-1">Depends On</div>
                            <div className="flex flex-wrap gap-1">
                              {dep.dependencies.map(d => (
                                <span key={d} className="px-2 py-0.5 bg-slate-100 text-slate-600 text-[11px] rounded">
                                  {STAGE_LABELS[d] || d}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                        {dep && dep.downstream.length > 0 && (
                          <div>
                            <div className="text-[10px] text-slate-400 uppercase font-semibold mb-1">Downstream</div>
                            <div className="flex flex-wrap gap-1">
                              {dep.downstream.map(d => (
                                <span key={d} className="px-2 py-0.5 bg-slate-100 text-slate-600 text-[11px] rounded">
                                  {STAGE_LABELS[d] || d}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                        {dep?.requires_approval && (
                          <div>
                            <div className="text-[10px] text-amber-500 uppercase font-semibold">Requires Approval</div>
                          </div>
                        )}
                        <div className="pt-2 border-t border-slate-100 flex gap-2">
                          <button
                            onClick={() => runAction(() => intelApi.pipelineRunStage(projectId, selectedStage), `Run ${STAGE_LABELS[selectedStage]}`)}
                            disabled={loading}
                            className="flex-1 px-3 py-1.5 bg-violet-600 text-white text-xs font-medium rounded-lg hover:bg-violet-700 disabled:opacity-50">
                            Run Stage
                          </button>
                          <button
                            onClick={() => runAction(() => intelApi.pipelineRunFrom(projectId, selectedStage), `From ${STAGE_LABELS[selectedStage]}`)}
                            disabled={loading}
                            className="flex-1 px-3 py-1.5 border border-violet-200 text-violet-600 text-xs font-medium rounded-lg hover:bg-violet-50 disabled:opacity-50">
                            Run From Here
                          </button>
                        </div>
                        <button
                          onClick={() => runAction(() => intelApi.pipelineClearCache(projectId, selectedStage), "Clear stage cache")}
                          disabled={loading}
                          className="w-full px-3 py-1.5 text-xs text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50">
                          Clear Stage Cache
                        </button>
                      </div>
                    );
                  })()}
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between pt-6">
        <button onClick={() => onNavigate("word-renderer")} className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors">
          Back to Word Report
        </button>
        <button onClick={() => onNavigate("publishing-gateway")} className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm">
          Proceed to Publishing & QA
        </button>
      </div>
    </div>
  );
}

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useDemoState } from "../context/demo-state";
import { intelApi, type JobStatus } from "../services/intel-api";
import { useActiveProjectId, useProject } from "../context/project-context";
import { useJobStatus } from "../hooks/useJobStatus";
import { PexelsHeaderBanner } from "../components/PexelsHeaderBanner";

interface UnitRow {
  id: number;
  unit_id: string;
  objective_id: string;
  method: string;
  status: string;
  progress_pct: number;
  records_processed: number;
  /** Every article for the unit, syndicated copies included; records_processed is unique stories. */
  coverage_volume?: number | null;
  evidence_count: number;
  error: string | null;
}

interface LogEntry {
  level: string;
  message: string;
  unit_id: string | null;
  created_at: number;
}

interface RunStatus {
  run_id: number;
  project_id: number;
  plan_id: number;
  status: string;
  total_units: number;
  completed_units: number;
  failed_units: number;
  skipped_units: number;
  total_evidence: number;
  elapsed_seconds: number | null;
  started_at: number | null;
  finished_at: number | null;
  units: UnitRow[];
  logs: LogEntry[];
}

function Badge({ label, variant }: { label: string; variant: string }) {
  const colors: Record<string, string> = {
    completed: "text-emerald-700 bg-emerald-50 border-emerald-200",
    completed_with_errors: "text-amber-700 bg-amber-50 border-amber-200",
    running: "text-blue-700 bg-blue-50 border-blue-200",
    pending: "text-slate-500 bg-slate-100 border-slate-200",
    failed: "text-red-700 bg-red-50 border-red-200",
    skipped: "text-slate-400 bg-slate-50 border-slate-200",
    paused: "text-violet-700 bg-violet-50 border-violet-200",
    cancelled: "text-slate-500 bg-slate-100 border-slate-200",
    blocked: "text-red-700 bg-red-50 border-red-200",
    high: "text-blue-700 bg-blue-50 border-blue-200",
    medium: "text-amber-700 bg-amber-50 border-amber-200",
    low: "text-slate-500 bg-slate-100 border-slate-200",
    info: "text-slate-500 bg-slate-100 border-slate-200",
    warn: "text-amber-700 bg-amber-50 border-amber-200",
    error: "text-red-700 bg-red-50 border-red-200",
  };
  return (
    <span
      className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded border ${colors[variant] || colors.pending}`}
    >
      {label}
    </span>
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

function StatCard({
  value,
  label,
  accent,
}: {
  value: string | number;
  label: string;
  accent?: boolean;
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm text-center">
      <div
        className={`text-2xl font-bold tabular-nums ${accent ? "text-blue-600" : "text-slate-900"}`}
      >
        {value}
      </div>
      <div className="text-[11px] text-slate-400 mt-1 font-medium">{label}</div>
    </div>
  );
}

function ProgressBar({
  completed,
  failed,
  skipped,
  total,
}: {
  completed: number;
  failed: number;
  skipped: number;
  total: number;
}) {
  if (total === 0) return null;
  const pctC = (completed / total) * 100;
  const pctF = (failed / total) * 100;
  const pctS = (skipped / total) * 100;

  return (
    <div className="h-2.5 bg-slate-100 rounded-full overflow-hidden flex">
      {pctC > 0 && (
        <div
          className="bg-emerald-500 transition-all duration-500"
          style={{ width: `${pctC}%` }}
        />
      )}
      {pctF > 0 && (
        <div
          className="bg-red-400 transition-all duration-500"
          style={{ width: `${pctF}%` }}
        />
      )}
      {pctS > 0 && (
        <div
          className="bg-slate-300 transition-all duration-500"
          style={{ width: `${pctS}%` }}
        />
      )}
    </div>
  );
}

/** The start endpoint answers 409 with {detail: {message, prerequisites}} when approvals are missing. */
function readableStartError(raw: string): string {
  const match = raw.match(/^409: (.*)$/s);
  if (!match) return raw;
  try {
    const body = JSON.parse(match[1]) as { detail?: { message?: string } };
    return body.detail?.message ?? raw;
  } catch {
    return raw;
  }
}

function formatElapsed(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return "--";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function UnitTable({
  units,
  onRetry,
}: {
  units: UnitRow[];
  onRetry: (unitId: string) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="text-left text-[10px] text-slate-400 uppercase tracking-wider border-b border-slate-200">
            <th className="pb-2 pr-3 font-semibold">Unit</th>
            <th className="pb-2 pr-3 font-semibold">Method</th>
            <th className="pb-2 pr-3 font-semibold">Status</th>
            <th className="pb-2 pr-3 font-semibold text-right tabular-nums" title="Every article, syndicated copies included">Volume</th>
            <th className="pb-2 pr-3 font-semibold text-right tabular-nums" title="Syndicated copies merged; what the analysis reads">Unique stories</th>
            <th className="pb-2 pr-3 font-semibold text-right tabular-nums">Evidence</th>
            <th className="pb-2 font-semibold"></th>
          </tr>
        </thead>
        <tbody>
          {units.map((u) => (
            <tr
              key={u.unit_id}
              className="border-b border-slate-100 last:border-0"
            >
              <td className="py-2.5 pr-3">
                <div className="font-medium text-slate-700">{u.unit_id}</div>
                <div className="text-[10px] text-slate-400">{u.objective_id}</div>
              </td>
              <td className="py-2.5 pr-3 text-slate-600">{u.method}</td>
              <td className="py-2.5 pr-3">
                <Badge label={u.status} variant={u.status} />
                {u.error && (
                  <div className="text-[10px] text-red-500 mt-1 max-w-[200px] truncate">
                    {u.error}
                  </div>
                )}
              </td>
              <td className="py-2.5 pr-3 text-right tabular-nums text-slate-600">
                {u.coverage_volume ?? "--"}
              </td>
              <td className="py-2.5 pr-3 text-right tabular-nums text-slate-600">
                {u.records_processed || "--"}
              </td>
              <td className="py-2.5 pr-3 text-right tabular-nums text-slate-600">
                {u.evidence_count || "--"}
              </td>
              <td className="py-2.5">
                {(u.status === "failed" || u.status === "skipped") && (
                  <button
                    onClick={() => onRetry(u.unit_id)}
                    className="text-[10px] text-blue-600 hover:text-blue-700 font-semibold uppercase"
                  >
                    Retry
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LogPanel({ logs }: { logs: LogEntry[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  return (
    <div className="bg-slate-900 rounded-lg p-4 max-h-64 overflow-y-auto font-mono text-[11px] leading-relaxed">
      {logs.length === 0 && (
        <div className="text-slate-500">No logs yet</div>
      )}
      {logs.map((l, i) => (
        <div key={i} className="flex gap-2">
          <span
            className={
              l.level === "error"
                ? "text-red-400"
                : l.level === "warn"
                  ? "text-amber-400"
                  : "text-slate-500"
            }
          >
            [{l.level.toUpperCase().padEnd(5)}]
          </span>
          {l.unit_id && <span className="text-blue-400">[{l.unit_id}]</span>}
          <span className="text-slate-300">{l.message}</span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

export function ResearchExecution({
  onNavigate,
}: {
  onNavigate: (page: string) => void;
}) {
  const { researchPlanLocked } = useDemoState();
  const [run, setRun] = useState<RunStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"units" | "logs" | "evidence">(
    "units",
  );
  const [evidence, setEvidence] = useState<unknown[]>([]);
  // Streaming text for the gap between clicking Start and a run row existing — the
  // auto-plan-generation phase (and the planner LLM call within it) used to be a
  // silent "Starting..." pill with no visible progress at all, since progress_message
  // was broadcast over the websocket but never persisted to the job row this page
  // polls. Reset on every new Start; once `run` exists, the Logs tab (run.logs, from
  // the DB) takes over with the same level of per-unit detail.
  const [progressLog, setProgressLog] = useState<{ message: string; at: number }[]>([]);

  const [liveElapsed, setLiveElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval>>();
  const startTimeRef = useRef<number | null>(null);

  const projectId = useActiveProjectId() ?? 1;
  const { activeProject } = useProject();

  useEffect(() => {
    if (starting || run?.status === "running" || run?.status === "paused") {
      if (!startTimeRef.current) {
        startTimeRef.current = run?.started_at
          ? run.started_at * 1000
          : Date.now();
      }
      timerRef.current = setInterval(() => {
        const elapsed = Math.floor(
          (Date.now() - (startTimeRef.current || Date.now())) / 1000,
        );
        setLiveElapsed(elapsed);
      }, 1000);
      return () => clearInterval(timerRef.current);
    }
    if (
      run?.status &&
      !["running", "paused", "pending"].includes(run.status)
    ) {
      clearInterval(timerRef.current);
      if (run.elapsed_seconds != null) setLiveElapsed(Math.round(run.elapsed_seconds));
    }
  }, [starting, run?.status, run?.started_at, run?.elapsed_seconds]);

  useEffect(() => {
    if (run?.started_at && startTimeRef.current === null) {
      startTimeRef.current = run.started_at * 1000;
    }
  }, [run?.started_at]);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await intelApi.getExecutionStatus(projectId);
      setRun(data as RunStatus);
      setError(null);
    } catch {
      // no execution yet
    }
  }, [projectId]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Refresh execution status on a 2s interval while a run or job is active.
  const shouldPollRun = run?.status === "running" || run?.status === "paused" || !!jobId;
  const fetchRunStatus = useMemo(
    () => (shouldPollRun ? () => intelApi.getExecutionStatus(projectId) : null),
    [shouldPollRun, projectId],
  );
  const { status: polledRun } = useJobStatus<RunStatus>(fetchRunStatus, {
    // Run refresh is enabled/disabled externally via `shouldPollRun` (which
    // reacts to run/job state), not by a per-tick terminal check.
    isTerminal: () => false,
  });
  useEffect(() => {
    if (polledRun) setRun(polledRun);
  }, [polledRun]);

  // Surface the per-unit streaming log by default once a run is actually executing,
  // rather than leaving the analyst on the "units" overview tab and requiring a manual
  // click to discover that per-unit detail (method, records filtered, evidence found)
  // exists at all.
  const hasSwitchedToLogsRef = useRef(false);
  useEffect(() => {
    if (run?.status === "running" && !hasSwitchedToLogsRef.current) {
      setActiveTab("logs");
      hasSwitchedToLogsRef.current = true;
    }
    if (!run) hasSwitchedToLogsRef.current = false;
  }, [run?.status]);

  // Watch the started job (if any) until it completes or fails.
  const fetchJobStatus = useMemo(
    () => (jobId ? () => intelApi.getJob(jobId) : null),
    [jobId],
  );
  const { status: polledJob } = useJobStatus<JobStatus>(fetchJobStatus);
  useEffect(() => {
    if (!polledJob?.progress_message) return;
    setProgressLog((prev) => {
      if (prev[prev.length - 1]?.message === polledJob.progress_message) return prev;
      return [...prev, { message: polledJob.progress_message!, at: Date.now() }].slice(-30);
    });
  }, [polledJob?.progress_message]);

  useEffect(() => {
    if (!polledJob) return;
    if (polledJob.status === "failed") {
      setError(polledJob.error || "Execution failed");
      setJobId(null);
      setStarting(false);
    } else if (polledJob.status === "completed") {
      setJobId(null);
      setStarting(false);
      fetchStatus();
    }
  }, [polledJob, fetchStatus]);

  useEffect(() => {
    if (
      run?.status &&
      !["running", "pending"].includes(run.status) &&
      jobId
    ) {
      setJobId(null);
      setStarting(false);
    }
  }, [run?.status, jobId]);

  const handleStart = async () => {
    setStarting(true);
    setError(null);
    startTimeRef.current = Date.now();
    setLiveElapsed(0);
    setProgressLog([]);
    try {
      const result = await intelApi.startExecution(projectId);
      setJobId(result.job_id);
      setTimeout(async () => {
        await fetchStatus();
        try {
          const job = await intelApi.getJob(result.job_id);
          if (job.status === "failed") {
            setError(job.error || "Execution failed to start");
            setJobId(null);
            setStarting(false);
          }
        } catch {
          // will be caught by polling
        }
      }, 1500);
    } catch (e: unknown) {
      setError(e instanceof Error ? readableStartError(e.message) : "Failed to start");
      setStarting(false);
    }
  };

  const handlePause = async () => {
    if (!run) return;
    try {
      await intelApi.pauseExecution(run.run_id);
      setTimeout(fetchStatus, 500);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to pause");
    }
  };

  const handleResume = async () => {
    if (!run) return;
    try {
      await intelApi.resumeExecution(run.run_id, projectId);
      setTimeout(fetchStatus, 1000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to resume");
    }
  };

  const handleCancel = async () => {
    if (!run) return;
    try {
      await intelApi.cancelExecution(run.run_id);
      setTimeout(fetchStatus, 500);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to cancel");
    }
  };

  const handleRetry = async (unitId: string) => {
    if (!run) return;
    try {
      await intelApi.retryUnit(run.run_id, unitId, projectId);
      setTimeout(fetchStatus, 1000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Retry failed");
    }
  };

  const fetchEvidence = useCallback(async () => {
    if (!run) return;
    try {
      const data = await intelApi.getEvidence(run.run_id);
      setEvidence(data);
    } catch {
      // ignore
    }
  }, [run?.run_id]);

  useEffect(() => {
    if (activeTab === "evidence" && run) {
      fetchEvidence();
    }
  }, [activeTab, run?.run_id, fetchEvidence]);

  const isLocked = researchPlanLocked;
  const isRunning = run?.status === "running";
  const isPaused = run?.status === "paused";
  const isFinished =
    run?.status === "completed" ||
    run?.status === "completed_with_errors" ||
    run?.status === "failed" ||
    run?.status === "cancelled";

  if (isLocked) {
    return (
      <div className="max-w-4xl mx-auto px-8 py-10">
        <div className="mb-6">
          <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-1">
            Stage 6
          </div>
          <h1 className="text-xl font-bold text-slate-900">
            Research Execution
          </h1>
          <p className="text-[13px] text-slate-400 mt-1">
            Execute the approved Research Plan against the uploaded dataset
          </p>
        </div>

        <div className="bg-white border border-slate-200 rounded-xl p-8 shadow-sm text-center">
          <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-slate-100 flex items-center justify-center">
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              className="text-slate-400"
            >
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
          </div>
          <h3 className="text-sm font-semibold text-slate-700 mb-2">
            Prerequisites Required
          </h3>
          <p className="text-[12px] text-slate-400 max-w-sm mx-auto mb-4">
            All datasets must be approved before execution can begin.
            Complete all prior stages first.
          </p>
          <button
            onClick={() => onNavigate("data-sources")}
            className="text-[12px] text-blue-600 hover:text-blue-700 font-semibold"
          >
            Go to Data Sources
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-8 py-10">
      <PexelsHeaderBanner brandName={activeProject?.brand || activeProject?.name} className="mb-6" />
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-1">
            Stage 6
          </div>
          <h1 className="text-xl font-bold text-slate-900">
            Research Execution
          </h1>
          <p className="text-[13px] text-slate-400 mt-1">
            Execute the approved Research Plan against the uploaded dataset
          </p>
        </div>
        <div className="flex items-center gap-2">
          {run && <Badge label={run.status.replace(/_/g, " ")} variant={run.status} />}
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-[12px] text-red-700">
          {error}
        </div>
      )}

      {/* Controls */}
      <div className="flex items-center gap-3 mb-6">
        {!run || isFinished ? (
          <button
            onClick={handleStart}
            disabled={starting}
            className="px-4 py-2 bg-blue-600 text-white text-[12px] font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {starting
              ? "Starting..."
              : run
                ? "Re-run Execution"
                : "Start Execution"}
          </button>
        ) : null}
        {isRunning && (
          <>
            <button
              onClick={handlePause}
              className="px-4 py-2 bg-violet-600 text-white text-[12px] font-semibold rounded-lg hover:bg-violet-700 transition-colors"
            >
              Pause
            </button>
            <button
              onClick={handleCancel}
              className="px-4 py-2 bg-slate-200 text-slate-700 text-[12px] font-semibold rounded-lg hover:bg-slate-300 transition-colors"
            >
              Cancel
            </button>
          </>
        )}
        {isPaused && (
          <>
            <button
              onClick={handleResume}
              className="px-4 py-2 bg-blue-600 text-white text-[12px] font-semibold rounded-lg hover:bg-blue-700 transition-colors"
            >
              Resume
            </button>
            <button
              onClick={handleCancel}
              className="px-4 py-2 bg-slate-200 text-slate-700 text-[12px] font-semibold rounded-lg hover:bg-slate-300 transition-colors"
            >
              Cancel
            </button>
          </>
        )}

        {/* Live timer */}
        {(starting || isRunning || isPaused) && (
          <div className="flex items-center gap-2 ml-2 px-3 py-1.5 bg-slate-50 border border-slate-200 rounded-lg">
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{
                backgroundColor: isPaused ? "#f59e0b" : "#3b82f6",
                animation: isPaused ? "none" : "pulse-dot 1.5s ease-in-out infinite",
              }}
            />
            <span className="text-[12px] font-mono font-semibold text-slate-700 tabular-nums">
              {formatElapsed(liveElapsed)}
            </span>
            <span className="text-[10px] text-slate-400 font-medium">
              {isPaused ? "paused" : "elapsed"}
            </span>
          </div>
        )}
      </div>

      {!run && !starting && (
        <div className="bg-white border border-slate-200 rounded-xl p-8 shadow-sm text-center">
          <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-blue-50 flex items-center justify-center">
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              className="text-blue-500"
            >
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
          </div>
          <h3 className="text-sm font-semibold text-slate-700 mb-2">
            Ready to Execute
          </h3>
          <p className="text-[12px] text-slate-400 max-w-md mx-auto">
            The approved Research Plan will be executed unit by unit against your
            dataset. Each unit runs independently — failures won't block other
            units.
          </p>
        </div>
      )}

      {!run && starting && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <span className="w-2 h-2 rounded-full shrink-0 bg-blue-500" style={{ animation: "pulse-dot 1.5s ease-in-out infinite" }} />
            <h3 className="text-sm font-semibold text-slate-700">
              {progressLog[progressLog.length - 1]?.message ?? "Starting execution..."}
            </h3>
          </div>
          <p className="text-[11px] text-slate-400 mb-3">
            No approved Research Plan exists yet for most new projects — one is generated
            automatically before any analysis runs, which can take a minute or two.
          </p>
          {progressLog.length > 0 && (
            <div className="max-h-48 overflow-y-auto border-t border-slate-100 pt-3 space-y-1.5">
              {progressLog.map((entry, i) => (
                <div key={i} className={`text-[11px] ${i === progressLog.length - 1 ? "text-slate-700 font-medium" : "text-slate-400"}`}>
                  {entry.message}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {run && (
        <>
          {/* Summary stats */}
          <div className="grid grid-cols-5 gap-3 mb-6">
            <StatCard value={run.total_units} label="Total Units" />
            <StatCard
              value={run.completed_units}
              label="Completed"
              accent
            />
            <StatCard value={run.failed_units} label="Failed" />
            <StatCard value={run.total_evidence} label="Evidence" accent />
            <StatCard
              value={formatElapsed(isRunning || isPaused ? liveElapsed : run.elapsed_seconds)}
              label="Elapsed"
            />
          </div>

          {/* Progress bar */}
          <div className="mb-6">
            <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1.5">
              <span>Execution Progress</span>
              <span className="tabular-nums">
                {run.completed_units + run.failed_units + run.skipped_units} /{" "}
                {run.total_units}
              </span>
            </div>
            <ProgressBar
              completed={run.completed_units}
              failed={run.failed_units}
              skipped={run.skipped_units}
              total={run.total_units}
            />
            <div className="flex gap-4 mt-1.5 text-[10px]">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                <span className="text-slate-400">Completed</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-red-400" />
                <span className="text-slate-400">Failed</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-slate-300" />
                <span className="text-slate-400">Skipped</span>
              </span>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex gap-1 mb-4 border-b border-slate-200">
            {(["units", "logs", "evidence"] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2.5 text-[12px] font-semibold border-b-2 transition-colors ${
                  activeTab === tab
                    ? "text-blue-600 border-blue-600"
                    : "text-slate-400 border-transparent hover:text-slate-600"
                }`}
              >
                {tab === "units"
                  ? "Execution Units"
                  : tab === "logs"
                    ? "Execution Log"
                    : `Evidence (${run.total_evidence})`}
              </button>
            ))}
          </div>

          <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
            {activeTab === "units" && (
              <>
                <SectionHeader
                  title="Execution Units"
                  count={run.units.length}
                />
                <UnitTable units={run.units} onRetry={handleRetry} />
              </>
            )}

            {activeTab === "logs" && (
              <>
                <SectionHeader title="Execution Log" count={run.logs.length} />
                <LogPanel logs={run.logs} />
              </>
            )}

            {activeTab === "evidence" && (
              <>
                <SectionHeader
                  title="Evidence Records"
                  count={evidence.length}
                />
                {evidence.length === 0 ? (
                  <div className="text-center py-8 text-[12px] text-slate-400">
                    No evidence collected yet
                  </div>
                ) : (
                  <div className="space-y-3 max-h-96 overflow-y-auto">
                    {(evidence as any[]).map((ev: any, i: number) => (
                      <div
                        key={i}
                        className="border border-slate-100 rounded-lg p-3"
                      >
                        <div className="flex items-center gap-2 mb-1.5">
                          <Badge
                            label={String(ev.method || "unknown")}
                            variant="medium"
                          />
                          <Badge
                            label={String(ev.confidence || "medium")}
                            variant={String(ev.confidence || "medium")}
                          />
                          {ev.platform && (
                            <span className="text-[10px] text-slate-400">
                              {String(ev.platform)}
                            </span>
                          )}
                          {ev.source && (
                            <span className="text-[10px] text-slate-400">
                              {String(ev.source)}
                            </span>
                          )}
                        </div>
                        <p className="text-[12px] text-slate-700 leading-relaxed">
                          {String(ev.text_excerpt || "").slice(0, 300)}
                          {String(ev.text_excerpt || "").length > 300 && "..."}
                        </p>
                        {ev.rationale && (
                          <p className="text-[10px] text-slate-400 mt-1.5 italic">
                            {String(ev.rationale)}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between pt-6">
        <button onClick={() => onNavigate("data-sources")} className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors">
          Back to Data Sources
        </button>
        <button onClick={() => onNavigate("analysis")} className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm">
          Proceed to Analysis
        </button>
      </div>
    </div>
  );
}

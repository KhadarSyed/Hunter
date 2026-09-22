import { useState, useEffect, useCallback } from "react";
import { intelApi as api } from "../lib/intel-api";
import { useActiveProjectId } from "../lib/project-context";
import type {
  PubValidationResult, PubDiffReport, PubReadinessSummary,
  PubVersion, PubApproval, PubAuditEntry, PubPackage, PubIssue,
} from "../data/contracts";

interface Props { onNavigate: (page: string) => void }

const DIMENSIONS = ["narrative","evidence","design","branding","completeness","rendering","consistency"] as const;
const DIM_LABELS: Record<string, string> = {
  narrative: "Narrative", evidence: "Evidence", design: "Design",
  branding: "Branding", completeness: "Completeness",
  rendering: "Rendering", consistency: "Consistency",
};

function statusBadge(s: string) {
  const map: Record<string, string> = {
    draft: "bg-slate-100 text-slate-600",
    submitted: "bg-yellow-100 text-yellow-700",
    approved: "bg-green-100 text-green-700",
    rejected: "bg-red-100 text-red-700",
    revision_requested: "bg-orange-100 text-orange-700",
    published: "bg-blue-100 text-blue-700",
    archived: "bg-slate-200 text-slate-500",
    blocked: "bg-red-100 text-red-700",
    client_ready: "bg-green-100 text-green-700",
    internal_review: "bg-yellow-100 text-yellow-700",
    completed: "bg-green-100 text-green-700",
    building: "bg-yellow-100 text-yellow-700",
    failed: "bg-red-100 text-red-700",
  };
  return <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${map[s] || "bg-slate-100 text-slate-600"}`}>{s.replace(/_/g," ")}</span>;
}

function severityBadge(s: string) {
  const map: Record<string, string> = {
    critical: "bg-red-100 text-red-700",
    major: "bg-orange-100 text-orange-700",
    minor: "bg-yellow-100 text-yellow-600",
    information: "bg-blue-100 text-blue-600",
  };
  return <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase ${map[s] || "bg-slate-100 text-slate-600"}`}>{s}</span>;
}

function formatTime(ts: number) {
  return new Date(ts * 1000).toLocaleString();
}

function formatBytes(b: number) {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / (1024 * 1024)).toFixed(1)} MB`;
}

function scorePct(n: number) {
  return `${Math.round(n * 100)}%`;
}

export function PublishingGatewayPage({ onNavigate }: Props) {
  const activeProjectId = useActiveProjectId();
  const [projects, setProjects] = useState<any[]>([]);
  const [presentations, setPresentations] = useState<any[]>([]);
  const [projectId, setProjectId] = useState<number | null>(activeProjectId);
  const [presId, setPresId] = useState<number | null>(null);

  const [summary, setSummary] = useState<PubReadinessSummary | null>(null);
  const [validation, setValidation] = useState<PubValidationResult | null>(null);
  const [diffReport, setDiffReport] = useState<PubDiffReport | null>(null);
  const [versions, setVersions] = useState<PubVersion[]>([]);
  const [approvals, setApprovals] = useState<PubApproval[]>([]);
  const [audit, setAudit] = useState<PubAuditEntry[]>([]);
  const [packages, setPackages] = useState<PubPackage[]>([]);

  const [tab, setTab] = useState<"validation"|"diff"|"versions"|"approvals"|"packages"|"audit">("validation");
  const [loading, setLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  useEffect(() => {
    api.listProjects().then(setProjects).catch(() => {});
  }, []);

  useEffect(() => {
    if (projectId) {
      api.pcPresentations(projectId).then(setPresentations).catch(() => setPresentations([]));
    }
  }, [projectId]);

  const refresh = useCallback(() => {
    if (!projectId || !presId) return;
    api.pubReadiness(projectId, presId).then(setSummary).catch(() => {});
    api.pubVersions(presId).then(setVersions).catch(() => setVersions([]));
    api.pubApprovals(presId).then(setApprovals).catch(() => setApprovals([]));
    api.pubAudit(projectId).then(setAudit).catch(() => setAudit([]));
    api.pubPackages(presId).then(setPackages).catch(() => setPackages([]));
    api.pubDiff(presId).then(setDiffReport).catch(() => setDiffReport(null));
  }, [projectId, presId]);

  useEffect(() => { refresh(); }, [refresh]);

  const doAction = async (label: string, fn: () => Promise<any>) => {
    setLoading(true); setActionMsg(null);
    try {
      await fn();
      setActionMsg(`${label} completed`);
      refresh();
    } catch (e: any) { setActionMsg(`${label} failed: ${e.message}`); }
    finally { setLoading(false); }
  };

  const runValidation = () => doAction("Validation", async () => {
    const r = await api.pubValidate(projectId!, presId!);
    setValidation(r);
  });

  const runCompare = () => doAction("Comparison", async () => {
    const r = await api.pubCompare(projectId!, presId!);
    setDiffReport(r);
    setTab("diff");
  });

  const createVersion = () => doAction("Create Version", () => api.pubCreateVersion(projectId!, presId!));
  const submitForReview = () => doAction("Submit for Review", () => api.pubSubmit(projectId!, presId!));
  const approveAction = () => doAction("Approve", () => api.pubApprove(projectId!, presId!));
  const rejectAction = () => doAction("Reject", () => api.pubReject(projectId!, presId!));
  const requestRevision = () => doAction("Request Revision", () => api.pubRevision(projectId!, presId!));
  const publishAction = () => doAction("Publish", () => api.pubPublish(projectId!, presId!));
  const archiveAction = () => doAction("Archive", () => api.pubArchive(projectId!, presId!));
  const buildPackage = () => doAction("Build Package", () => api.pubPackage(projectId!, presId!));

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-slate-900">Publishing & Quality Gateway</h1>
            <span className="px-2 py-0.5 rounded bg-blue-100 text-blue-700 text-[11px] font-semibold">STAGE 15</span>
          </div>
          <p className="text-sm text-slate-500 mt-1">Validate, compare, certify, package and publish deliverables</p>
        </div>
      </div>

      {/* Selectors */}
      <div className="flex gap-4">
        <select value={projectId ?? ""} onChange={e => { setProjectId(Number(e.target.value) || null); setPresId(null); setSummary(null); setValidation(null); }}
          className="border border-slate-300 rounded-lg px-3 py-2 text-sm w-64">
          <option value="">Select Project...</option>
          {projects.map(p => <option key={p.id} value={p.id}>{p.project_name}</option>)}
        </select>
        <select value={presId ?? ""} onChange={e => { setPresId(Number(e.target.value) || null); setValidation(null); setSummary(null); }}
          className="border border-slate-300 rounded-lg px-3 py-2 text-sm w-64" disabled={!projectId}>
          <option value="">Select Presentation...</option>
          {presentations.map(p => <option key={p.id} value={p.id}>{p.title || `Presentation #${p.id}`}</option>)}
        </select>
      </div>

      {!projectId || !presId ? (
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center text-slate-400">
          Select a project and presentation to begin quality review
        </div>
      ) : (
        <>
          {/* Readiness Score Cards */}
          <div className="grid grid-cols-5 gap-4">
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="text-[11px] text-slate-400 font-medium uppercase">Readiness Score</div>
              <div className="text-2xl font-bold text-slate-900 mt-1">{summary ? scorePct(summary.readiness_score) : "—"}</div>
              {summary && statusBadge(summary.readiness_class)}
            </div>
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="text-[11px] text-slate-400 font-medium uppercase">Version</div>
              <div className="text-2xl font-bold text-slate-900 mt-1">{summary?.latest_version || "—"}</div>
              {summary?.latest_version_status && statusBadge(summary.latest_version_status)}
            </div>
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="text-[11px] text-slate-400 font-medium uppercase">Output Match</div>
              <div className="text-2xl font-bold text-slate-900 mt-1">{summary?.diff_match_pct != null ? scorePct(summary.diff_match_pct) : "—"}</div>
              <div className="text-[11px] text-slate-400">PPTX vs Word</div>
            </div>
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="text-[11px] text-slate-400 font-medium uppercase">Package</div>
              <div className="text-2xl font-bold text-slate-900 mt-1">{summary?.stats.packages || 0}</div>
              {summary?.latest_package_status && statusBadge(summary.latest_package_status)}
            </div>
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="text-[11px] text-slate-400 font-medium uppercase">Publications</div>
              <div className="text-2xl font-bold text-slate-900 mt-1">{summary?.stats.publications || 0}</div>
              <div className="text-[11px] text-slate-400">{summary?.stats.downloads || 0} downloads</div>
            </div>
          </div>

          {/* Dimension Scores */}
          {summary && summary.scores && Object.keys(summary.scores).length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="text-[11px] text-slate-400 font-medium uppercase mb-3">Dimension Scores</div>
              <div className="grid grid-cols-7 gap-3">
                {DIMENSIONS.map(d => (
                  <div key={d} className="text-center">
                    <div className="text-sm font-medium text-slate-600">{DIM_LABELS[d]}</div>
                    <div className="mt-1">
                      <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
                        <div className="h-full rounded-full transition-all" style={{
                          width: scorePct(summary.scores[d] ?? 0),
                          backgroundColor: (summary.scores[d] ?? 0) >= 0.8 ? "#22c55e" : (summary.scores[d] ?? 0) >= 0.5 ? "#eab308" : "#ef4444",
                        }} />
                      </div>
                      <div className="text-xs font-semibold text-slate-700 mt-1">{scorePct(summary.scores[d] ?? 0)}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Action Bar */}
          <div className="flex items-center gap-2 flex-wrap">
            <button onClick={runValidation} disabled={loading} className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50">Run Validation</button>
            <button onClick={runCompare} disabled={loading} className="px-4 py-2 bg-slate-600 text-white text-sm font-medium rounded-lg hover:bg-slate-700 disabled:opacity-50">Compare Outputs</button>
            <button onClick={buildPackage} disabled={loading} className="px-4 py-2 bg-slate-600 text-white text-sm font-medium rounded-lg hover:bg-slate-700 disabled:opacity-50">Build Package</button>
            <div className="w-px h-6 bg-slate-300 mx-1" />
            <button onClick={createVersion} disabled={loading} className="px-3 py-2 border border-slate-300 text-sm rounded-lg hover:bg-slate-50 disabled:opacity-50">New Version</button>
            <button onClick={submitForReview} disabled={loading} className="px-3 py-2 border border-yellow-400 text-yellow-700 text-sm rounded-lg hover:bg-yellow-50 disabled:opacity-50">Submit for Review</button>
            <button onClick={approveAction} disabled={loading} className="px-3 py-2 border border-green-400 text-green-700 text-sm rounded-lg hover:bg-green-50 disabled:opacity-50">Approve</button>
            <button onClick={rejectAction} disabled={loading} className="px-3 py-2 border border-red-400 text-red-700 text-sm rounded-lg hover:bg-red-50 disabled:opacity-50">Reject</button>
            <button onClick={requestRevision} disabled={loading} className="px-3 py-2 border border-orange-400 text-orange-700 text-sm rounded-lg hover:bg-orange-50 disabled:opacity-50">Request Revision</button>
            <button onClick={publishAction} disabled={loading} className="px-3 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 disabled:opacity-50">Publish</button>
            <button onClick={archiveAction} disabled={loading} className="px-3 py-2 border border-slate-300 text-slate-500 text-sm rounded-lg hover:bg-slate-50 disabled:opacity-50">Archive</button>
            <button onClick={refresh} disabled={loading} className="ml-auto px-3 py-2 border border-slate-300 text-sm rounded-lg hover:bg-slate-50 disabled:opacity-50">Refresh</button>
          </div>

          {actionMsg && (
            <div className={`text-sm px-3 py-2 rounded-lg ${actionMsg.includes("failed") ? "bg-red-50 text-red-700" : "bg-green-50 text-green-700"}`}>{actionMsg}</div>
          )}

          {/* Downloads */}
          <div className="flex gap-3">
            <a href={api.pubDownloadPptxUrl(presId)} className="px-4 py-2 border border-blue-300 text-blue-700 text-sm rounded-lg hover:bg-blue-50 inline-flex items-center gap-2" download>
              Download PPTX
            </a>
            <a href={api.pubDownloadWordUrl(presId)} className="px-4 py-2 border border-blue-300 text-blue-700 text-sm rounded-lg hover:bg-blue-50 inline-flex items-center gap-2" download>
              Download Word
            </a>
            {packages.length > 0 && packages[0].status === "completed" && (
              <a href={api.pubDownloadPackageUrl(packages[0].id)} className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 inline-flex items-center gap-2" download>
                Download Package (.zip)
              </a>
            )}
          </div>

          {/* Tabs */}
          <div className="border-b border-slate-200 flex gap-0">
            {(["validation","diff","versions","approvals","packages","audit"] as const).map(t => (
              <button key={t} onClick={() => setTab(t)}
                className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${tab === t ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-700"}`}>
                {t === "validation" ? "Validation" : t === "diff" ? "Difference Report" : t === "versions" ? "Versions" : t === "approvals" ? "Approval History" : t === "packages" ? "Packages" : "Audit Trail"}
              </button>
            ))}
          </div>

          {/* Validation Tab */}
          {tab === "validation" && (
            <div className="space-y-4">
              {validation && (
                <div className="bg-white rounded-xl border border-slate-200 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="text-sm font-semibold text-slate-800">Validation Results</div>
                    <div className="flex items-center gap-2">
                      {statusBadge(validation.readiness_class)}
                      <span className="text-sm font-bold">{scorePct(validation.readiness_score)}</span>
                      <span className="text-[11px] text-slate-400">{validation.duration_ms}ms</span>
                    </div>
                  </div>
                  {validation.issues.length === 0 ? (
                    <div className="text-sm text-green-600 font-medium">No issues found</div>
                  ) : (
                    <div className="space-y-2">
                      {validation.issues.map((iss: PubIssue, i: number) => (
                        <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-slate-50 border border-slate-100">
                          <div className="shrink-0 mt-0.5">{severityBadge(iss.severity)}</div>
                          <div className="flex-1 min-w-0">
                            <div className="text-sm text-slate-800">{iss.description}</div>
                            <div className="text-[11px] text-slate-400 mt-1">
                              {iss.deliverable} {iss.page_slide > 0 ? `/ Slide ${iss.page_slide}` : ""} — {iss.suggested_resolution}
                            </div>
                          </div>
                          <div className="text-[11px] text-slate-400 shrink-0">{Math.round(iss.confidence * 100)}%</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Difference Report Tab */}
          {tab === "diff" && (
            <div className="space-y-4">
              {diffReport ? (
                <div className="bg-white rounded-xl border border-slate-200 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="text-sm font-semibold text-slate-800">Output Comparison</div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold">{scorePct(diffReport.match_pct)} match</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3 mb-4">
                    <div className="p-3 rounded-lg bg-slate-50 text-sm">
                      <span className="text-slate-500">PPTX rendered:</span>{" "}
                      <span className={diffReport.summary.pptx_rendered ? "text-green-600 font-medium" : "text-red-600 font-medium"}>
                        {diffReport.summary.pptx_rendered ? "Yes" : "No"}
                      </span>
                    </div>
                    <div className="p-3 rounded-lg bg-slate-50 text-sm">
                      <span className="text-slate-500">Word rendered:</span>{" "}
                      <span className={diffReport.summary.word_rendered ? "text-green-600 font-medium" : "text-red-600 font-medium"}>
                        {diffReport.summary.word_rendered ? "Yes" : "No"}
                      </span>
                    </div>
                  </div>
                  {diffReport.differences.length === 0 ? (
                    <div className="text-sm text-green-600 font-medium">Outputs are identical</div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead><tr className="text-left text-[11px] text-slate-400 uppercase">
                          <th className="pb-2 pr-4">Field</th><th className="pb-2 pr-4">Type</th><th className="pb-2 pr-4">Value</th><th className="pb-2">Severity</th>
                        </tr></thead>
                        <tbody>
                          {diffReport.differences.map((d, i) => (
                            <tr key={i} className="border-t border-slate-100">
                              <td className="py-2 pr-4 font-medium text-slate-700">{d.field}</td>
                              <td className="py-2 pr-4 text-slate-500">{d.type}</td>
                              <td className="py-2 pr-4 text-slate-600 max-w-xs truncate">{d.value}</td>
                              <td className="py-2">{severityBadge(d.severity)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ) : (
                <div className="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-400 text-sm">
                  Click "Compare Outputs" to generate a difference report
                </div>
              )}
            </div>
          )}

          {/* Versions Tab */}
          {tab === "versions" && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              {versions.length === 0 ? (
                <div className="p-8 text-center text-slate-400 text-sm">No versions created yet</div>
              ) : (
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-[11px] text-slate-400 uppercase bg-slate-50">
                    <th className="px-4 py-3">Version</th><th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Approved By</th><th className="px-4 py-3">Notes</th><th className="px-4 py-3">Created</th>
                  </tr></thead>
                  <tbody>
                    {versions.map(v => (
                      <tr key={v.id} className="border-t border-slate-100">
                        <td className="px-4 py-3 font-mono font-medium text-slate-800">{v.version_label}</td>
                        <td className="px-4 py-3">{statusBadge(v.approval_status)}</td>
                        <td className="px-4 py-3 text-slate-500">{v.approved_by || "—"}</td>
                        <td className="px-4 py-3 text-slate-500 max-w-xs truncate">{v.notes || "—"}</td>
                        <td className="px-4 py-3 text-slate-400 text-xs">{formatTime(v.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Approvals Tab */}
          {tab === "approvals" && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              {approvals.length === 0 ? (
                <div className="p-8 text-center text-slate-400 text-sm">No approval history yet</div>
              ) : (
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-[11px] text-slate-400 uppercase bg-slate-50">
                    <th className="px-4 py-3">Action</th><th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Actor</th><th className="px-4 py-3">Notes</th><th className="px-4 py-3">Date</th>
                  </tr></thead>
                  <tbody>
                    {approvals.map(a => (
                      <tr key={a.id} className="border-t border-slate-100">
                        <td className="px-4 py-3 font-medium text-slate-700">{a.action.replace(/_/g," ")}</td>
                        <td className="px-4 py-3">{statusBadge(a.status)}</td>
                        <td className="px-4 py-3 text-slate-500">{a.actor}</td>
                        <td className="px-4 py-3 text-slate-500 max-w-xs truncate">{a.notes || "—"}</td>
                        <td className="px-4 py-3 text-slate-400 text-xs">{formatTime(a.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Packages Tab */}
          {tab === "packages" && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              {packages.length === 0 ? (
                <div className="p-8 text-center text-slate-400 text-sm">No packages built yet</div>
              ) : (
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-[11px] text-slate-400 uppercase bg-slate-50">
                    <th className="px-4 py-3">ID</th><th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Size</th><th className="px-4 py-3">Files</th>
                    <th className="px-4 py-3">Created</th><th className="px-4 py-3">Download</th>
                  </tr></thead>
                  <tbody>
                    {packages.map(p => (
                      <tr key={p.id} className="border-t border-slate-100">
                        <td className="px-4 py-3 font-mono text-slate-700">#{p.id}</td>
                        <td className="px-4 py-3">{statusBadge(p.status)}</td>
                        <td className="px-4 py-3 text-slate-600">{formatBytes(p.package_size_bytes)}</td>
                        <td className="px-4 py-3 text-slate-500">{Array.isArray(p.contents_json) ? p.contents_json.length : 0}</td>
                        <td className="px-4 py-3 text-slate-400 text-xs">{formatTime(p.created_at)}</td>
                        <td className="px-4 py-3">
                          {p.status === "completed" && (
                            <a href={api.pubDownloadPackageUrl(p.id)} className="text-blue-600 hover:underline text-xs" download>Download</a>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Audit Trail Tab */}
          {tab === "audit" && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              {audit.length === 0 ? (
                <div className="p-8 text-center text-slate-400 text-sm">No audit entries yet</div>
              ) : (
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-[11px] text-slate-400 uppercase bg-slate-50">
                    <th className="px-4 py-3">Type</th><th className="px-4 py-3">Action</th>
                    <th className="px-4 py-3">Actor</th><th className="px-4 py-3">Details</th><th className="px-4 py-3">Date</th>
                  </tr></thead>
                  <tbody>
                    {audit.map(a => (
                      <tr key={a.id} className="border-t border-slate-100">
                        <td className="px-4 py-3">{statusBadge(a.entity_type)}</td>
                        <td className="px-4 py-3 font-medium text-slate-700">{a.action.replace(/_/g," ")}</td>
                        <td className="px-4 py-3 text-slate-500">{a.actor}</td>
                        <td className="px-4 py-3 text-slate-400 text-xs max-w-sm truncate">
                          {typeof a.details_json === "object" ? JSON.stringify(a.details_json) : String(a.details_json || "—")}
                        </td>
                        <td className="px-4 py-3 text-slate-400 text-xs">{formatTime(a.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

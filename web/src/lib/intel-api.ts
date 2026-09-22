import type { Insight, InsightDetail, InsightsSummary, InsightValidation, InsightEvidence, Storyline, StorylineDetail, StorylineSummary, StorylineValidation, StoryNodeEnriched, StoryNode, SIDashboard, SIPresentation, SISlide, SITemplateFamily, SIDetectedProject, SIRecommendation, PCPresentation, PCSlide, PCPresentationDetail, PCPresentationSummary, PCValidation, RenderJob, RenderResult, RenderSummary, RenderTheme, RenderValidation, RenderMetric, RenderHistory, PipelineRunDetail, PipelineProjectStatus, PipelineTimelineEntry, PipelineLog, PipelinePerformance, PipelineCacheMetrics, PipelineDependencyNode, PipelineStageStatus, WordRenderResult, WordRenderJob, WordDocument, WordRenderMetric, WordRenderHistory, WordRenderSummary, WordValidation, PubValidationResult, PubValidation, PubDiffReport, PubVersion, PubPackage, PubPackageResult, PubApproval, PubApprovalResult, PubReadinessSummary, PubAuditEntry, PubDownload, PubVersionResult } from "../data/contracts";

const API_BASE = "/api/intel";

async function json<T>(res: Response): Promise<T> {
  const ct = res.headers.get("content-type") || "";
  if (!ct.includes("application/json")) {
    throw new Error("Backend not reachable — restart the backend server");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  }).then((r) => json<T>(r));
}

function get<T>(path: string): Promise<T> {
  return fetch(`${API_BASE}${path}`).then((r) => json<T>(r));
}

function put<T>(path: string, body?: unknown): Promise<T> {
  return fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  }).then((r) => json<T>(r));
}

function del<T>(path: string): Promise<T> {
  return fetch(`${API_BASE}${path}`, { method: "DELETE" }).then((r) => json<T>(r));
}

// ─── Types ──────────────────────────────────────────────────────────────────

export interface JobStatus {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  progress_pct: number;
  progress_message: string;
  error?: string;
  started_at?: number;
  finished_at?: number;
}

export interface ResearchResult {
  research_id: number;
  version: number;
  approval_status: string;
  research: {
    status: string;
    web_search_executed: boolean;
    brand_name: string;
    metadata: {
      sources_reviewed: number;
      sources_retained: number;
      sources_rejected: number;
      tier_1_count: number;
      tier_2_count: number;
      tier_3_count: number;
      date_range_start: string;
      date_range_end: string;
      search_queries_executed: number;
      elapsed_seconds: number;
      execution_date: string;
    };
    news_items: NewsItem[];
    background_context: NewsItem[];
    rejected_sources: { headline: string; url: string; rejection_reason: string }[];
    search_log: { query: string; family: string; web_count: number; news_count: number }[];
    research_gaps: string[];
    confidence: Record<string, string>;
  };
  llm_output: Record<string, unknown> | null;
  can_approve: boolean;
  blocking_reasons: string[];
  created_at: number;
}

export interface NewsItem {
  headline: string;
  publisher: string;
  date: string;
  url: string;
  tier: string;
  summary: string;
  family?: string;
  query?: string;
  date_status?: string;
  date_note?: string;
  relevance_confidence?: string;
  relevance_reason?: string;
  access_date?: string;
  approval_status?: string;
  approval_notes?: string;
}

export interface StrategyResult {
  strategy_id: number;
  version: number;
  approval_status: string;
  strategy: Record<string, unknown>;
  query_versions: unknown[];
  created_at: number;
}

export interface EvaluationResult {
  id: number;
  file_name: string;
  status: string;
  evaluation: Record<string, unknown> | null;
}

export interface PlanResult {
  id: number;
  project_id: number;
  version: number;
  status: string;
  plan_json: Record<string, unknown>;
  source: string;
  approval_status: string;
  approved_by: string | null;
  approved_at: number | null;
  notes: string | null;
  created_at: number;
}

export interface BriefSection {
  title: string;
  content: string;
  edited: boolean;
}

export interface SourceRef {
  ref: string;
  publisher: string;
  date: string;
  headline: string;
  url: string;
  tier: number;
}

export interface BriefData {
  title: string;
  research_subject: string;
  brand_name: string;
  category: string;
  generated_at: string;
  section_order: string[];
  section_titles: Record<string, string>;
  sections: Record<string, BriefSection>;
  source_register: SourceRef[];
  research_gaps: string[];
  source_count: number;
  enrichment_status: string;
  metadata: {
    sources_reviewed: number;
    sources_retained: number;
    tier_1_count: number;
    tier_2_count: number;
    date_range_start: string;
    date_range_end: string;
  };
}

export interface BriefResult {
  brief_id: number;
  version: number;
  approval_status: string;
  brief: BriefData;
  docx_path: string | null;
  docx_generated_at: number | null;
  research_approved: boolean;
  created_at: number;
  updated_at: number;
}

export interface BriefVersion {
  id: number;
  version: number;
  status: string;
  approval_status: string;
  docx_path: string | null;
  created_at: number;
  updated_at: number;
}

// Research Specification types

export interface SpecSection {
  title: string;
  content: string | Record<string, unknown> | unknown[];
  edited: boolean;
}

export interface SpecSectionApproval {
  id: number;
  spec_id: number;
  section_key: string;
  status: string;
  is_locked: number;
  locked_by: string | null;
  locked_at: number | null;
  edited_content: string | null;
  analyst_note: string | null;
  reviewed_by: string | null;
  reviewed_at: number | null;
}

export interface SpecClarification {
  id: number;
  spec_id: number;
  section_key: string;
  question: string;
  is_blocking: number;
  answer: string | null;
  resolved_by: string | null;
  resolved_at: number | null;
  created_at: number;
}

export interface SpecReadiness {
  status: string;
  blocking_issues: string[];
  warnings: string[];
  section_status: Record<string, string>;
  filled_count: number;
  total_count: number;
  completeness_pct: number;
}

export interface SpecData {
  project_id: number;
  project_name: string;
  section_order: string[];
  section_titles: Record<string, string>;
  sections: Record<string, SpecSection>;
  source_spec: Record<string, unknown>;
  generated_at: number;
}

export interface SpecResult {
  id: number;
  project_id: number;
  version: number;
  spec_json: string;
  spec: SpecData;
  status: string;
  readiness_status: string;
  readiness: SpecReadiness | null;
  approval_status: string;
  approved_by: string | null;
  approved_at: number | null;
  generation_source: string;
  docx_path: string | null;
  docx_generated_at: number | null;
  section_approvals: Record<string, SpecSectionApproval>;
  clarifications: SpecClarification[];
  created_at: number;
  updated_at: number;
}

export interface SpecVersion {
  id: number;
  version: number;
  status: string;
  readiness_status: string;
  approval_status: string;
  generation_source: string;
  docx_path: string | null;
  created_at: number;
  updated_at: number;
}

export interface SpecAuditEntry {
  id: number;
  spec_id: number;
  action: string;
  section_key: string | null;
  field: string | null;
  old_value: string | null;
  new_value: string | null;
  actor: string;
  created_at: number;
}

export interface GenerateSpecResult {
  spec_id: number;
  spec: SpecData;
  readiness: SpecReadiness;
  clarifications: { question: string; section_key: string; is_blocking: boolean }[];
}

// ─── API Functions ──────────────────────────────────────────────────────────

export const intelApi = {
  // Projects
  listProjects: (type?: string) =>
    get<{ id: number; project_name: string; project_type: string; created_at: number; updated_at: number }[]>(
      type ? `/projects?type=${type}` : "/projects"
    ),

  createProject: (name: string, spec: Record<string, unknown> = {}, project_type: string = "research") =>
    post<{ id: number; project_name: string; project_type: string; spec: Record<string, unknown> }>("/projects", {
      project_name: name,
      spec,
      project_type,
    }),

  getProject: (projectId: number) =>
    get<{ id: number; project_name: string; project_type: string; spec: Record<string, unknown> }>(`/projects/${projectId}`),

  // Presentation Composer — list presentations
  pcPresentations: (projectId: number) =>
    get<any[]>(`/composer/${projectId}`),

  // Background Research
  startResearch: (spec: Record<string, unknown>, projectId?: number) =>
    post<{ job_id: string; project_id: number }>("/research/start", { spec, project_id: projectId }),

  getResearchStatus: (jobId: string) =>
    get<JobStatus>(`/research/status/${jobId}`),

  getResearch: (projectId: number) =>
    get<ResearchResult>(`/research/${projectId}`),

  approveResearch: (researchId: number, reviewer = "analyst") =>
    post<{ ok: boolean }>(`/research/${researchId}/approve`, { reviewer }),

  reviseResearch: (researchId: number, notes: string) =>
    post<{ ok: boolean }>(`/research/${researchId}/revise`, { notes }),

  approveNewsItem: (researchId: number, itemIndex: number, status: string, notes = "") =>
    post<{ ok: boolean }>(`/research/${researchId}/news-approval`, {
      item_index: itemIndex,
      status,
      notes,
    }),

  // Analyst Orientation Brief
  generateBrief: (projectId: number) =>
    post<{ brief_id: number; brief: BriefData }>("/brief/generate", { project_id: projectId }),

  getBrief: (projectId: number) =>
    get<BriefResult>(`/brief/${projectId}`),

  updateBriefSection: (briefId: number, sectionKey: string, content: string, analystNote = "") =>
    post<{ ok: boolean }>(`/brief/${briefId}/section`, {
      section_key: sectionKey,
      content,
      analyst_note: analystNote,
    }),

  approveBrief: (briefId: number, reviewer = "analyst") =>
    post<{ ok: boolean }>(`/brief/${briefId}/approve`, { reviewer }),

  rejectBrief: (briefId: number, notes = "") =>
    post<{ ok: boolean }>(`/brief/${briefId}/reject`, { notes }),

  renderBriefDocx: (briefId: number) =>
    post<{ ok: boolean; docx_path: string }>(`/brief/${briefId}/render`),

  downloadBriefDocx: (briefId: number) =>
    fetch(`${API_BASE}/brief/${briefId}/download`).then((r) => {
      if (!r.ok) throw new Error("Download failed");
      return r.blob();
    }),

  listBriefVersions: (projectId: number) =>
    get<BriefVersion[]>(`/brief/versions/${projectId}`),

  // Research Specification
  generateSpec: (projectId: number, rawBriefText = "", useLlm = false) =>
    post<GenerateSpecResult>("/spec/generate", {
      project_id: projectId,
      raw_brief_text: rawBriefText,
      use_llm: useLlm,
    }),

  getSpec: (projectId: number) =>
    get<SpecResult>(`/spec/${projectId}`),

  getSpecDetail: (specId: number) =>
    get<SpecResult>(`/spec/detail/${specId}`),

  updateSpecSection: (specId: number, sectionKey: string, content: string | Record<string, unknown> | unknown[], analystNote = "") =>
    post<{ status: string; section_key: string }>(`/spec/${specId}/section`, {
      section_key: sectionKey,
      content,
      analyst_note: analystNote,
    }),

  approveSpecSection: (specId: number, sectionKey: string, reviewer = "analyst") =>
    post<{ status: string; section_key: string }>(`/spec/${specId}/section/approve`, {
      section_key: sectionKey,
      reviewer,
    }),

  lockSpecSection: (specId: number, sectionKey: string, lockedBy = "analyst") =>
    post<{ status: string; section_key: string }>(`/spec/${specId}/section/lock`, {
      section_key: sectionKey,
      locked_by: lockedBy,
    }),

  unlockSpecSection: (specId: number, sectionKey: string, lockedBy = "analyst") =>
    post<{ status: string; section_key: string }>(`/spec/${specId}/section/unlock`, {
      section_key: sectionKey,
      locked_by: lockedBy,
    }),

  approveSpec: (specId: number, reviewer = "analyst") =>
    post<{ status: string; spec_id: number }>(`/spec/${specId}/approve`, { reviewer }),

  rejectSpec: (specId: number, reason = "", reviewer = "analyst") =>
    post<{ status: string; spec_id: number }>(`/spec/${specId}/reject`, { reason, reviewer }),

  regenerateSpec: (specId: number, rawBriefText = "", useLlm = false, confirmOverwriteLocked = false) =>
    post<{ spec_id: number; spec: SpecData; readiness: SpecReadiness }>(`/spec/${specId}/regenerate`, {
      raw_brief_text: rawBriefText,
      use_llm: useLlm,
      confirm_overwrite_locked: confirmOverwriteLocked,
    }),

  getSpecReadiness: (specId: number) =>
    get<SpecReadiness>(`/spec/${specId}/readiness`),

  renderSpecDocx: (specId: number) =>
    post<{ status: string; docx_path: string }>(`/spec/${specId}/render`),

  downloadSpecDocx: (specId: number) =>
    fetch(`${API_BASE}/spec/${specId}/download`).then((r) => {
      if (!r.ok) throw new Error("Download failed");
      return r.blob();
    }),

  listSpecVersions: (projectId: number) =>
    get<SpecVersion[]>(`/spec/versions/${projectId}`),

  getSpecAudit: (specId: number) =>
    get<SpecAuditEntry[]>(`/spec/${specId}/audit`),

  getSpecClarifications: (specId: number, unresolvedOnly = false) =>
    get<SpecClarification[]>(`/spec/${specId}/clarifications${unresolvedOnly ? "?unresolved_only=true" : ""}`),

  addSpecClarification: (specId: number, question: string, sectionKey = "", isBlocking = true) =>
    post<{ status: string; clarification_id: number }>(`/spec/${specId}/clarification`, {
      question,
      section_key: sectionKey,
      is_blocking: isBlocking,
    }),

  resolveSpecClarification: (clarificationId: number, answer: string, resolvedBy = "analyst") =>
    post<{ status: string; clarification_id: number }>(`/spec/clarification/${clarificationId}/resolve`, {
      answer,
      resolved_by: resolvedBy,
    }),

  // Search Strategy
  generateStrategy: (projectId: number) =>
    post<{ job_id: string; project_id: number }>("/strategy/generate", {
      project_id: projectId,
    }),

  getStrategy: (projectId: number) =>
    get<StrategyResult>(`/strategy/${projectId}`),

  editQuery: (strategyId: number, queryType: string, queryText: string) =>
    post<{ version_id: number; validation_issues: string[]; validation_status: string }>(
      `/strategy/${strategyId}/edit-query`,
      { query_type: queryType, query_text: queryText },
    ),

  getQueryVersions: (strategyId: number) =>
    get<unknown[]>(`/strategy/${strategyId}/versions`),

  approveStrategy: (strategyId: number, reviewer = "analyst") =>
    post<{ ok: boolean }>(`/strategy/${strategyId}/approve`, { reviewer }),

  editResearchQuestion: (strategyId: number, questionId: string, question: string, query: string) =>
    put<{ ok: boolean }>(`/strategy/${strategyId}/research-question`, { question_id: questionId, question, query }),

  deleteResearchQuestion: (strategyId: number, questionId: string) =>
    del<{ ok: boolean }>(`/strategy/${strategyId}/research-question/${questionId}`),

  // Brief file upload
  parseBriefFile: async (file: File): Promise<{ text: string; file_name: string }> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/brief/parse-file`, { method: "POST", body: form });
    return json<{ text: string; file_name: string }>(res);
  },

  // Sample Evaluation
  uploadSample: async (projectId: number, strategyId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(
      `${API_BASE}/evaluation/upload?project_id=${projectId}&strategy_id=${strategyId}`,
      { method: "POST", body: formData },
    );
    return json<{ job_id: string; eval_id: number }>(res);
  },

  getEvaluation: (projectId: number) =>
    get<EvaluationResult>(`/evaluation/${projectId}`),

  // Dataset
  uploadDataset: async (projectId: number, file: File, researchQuestionId?: string) => {
    const form = new FormData();
    form.append("file", file);
    let url = `/api/intel/dataset/upload?project_id=${projectId}`;
    if (researchQuestionId) url += `&research_question_id=${encodeURIComponent(researchQuestionId)}`;
    const res = await fetch(url, {
      method: "POST",
      body: form,
    });
    const ct = res.headers.get("content-type") || "";
    if (!ct.includes("application/json")) {
      throw new Error("Backend not reachable — restart the backend server and try again");
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Upload failed");
    }
    return res.json();
  },

  getDataset: (projectId: number) =>
    get<any>(`/dataset/${projectId}`),

  getAllDatasets: (projectId: number) =>
    get<any[]>(`/dataset/${projectId}?scope=all`),

  approveDataset: (datasetId: number) =>
    post<{ ok: boolean }>(`/dataset/${datasetId}/approve`, {}),

  deleteDataset: (datasetId: number) =>
    fetch(`${API_BASE}/dataset/${datasetId}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),

  // Final Approval
  finalApproval: (projectId: number, opts: {
    reviewer?: string;
    sample_evaluation_waived?: boolean;
    acknowledge_meltwater_validation?: boolean;
  }) =>
    post<{ approved: boolean; blocking_reasons?: string[]; strategy_id?: number }>(
      `/strategy/${projectId}/final-approve`,
      {
        reviewer: opts.reviewer || "analyst",
        sample_evaluation_waived: opts.sample_evaluation_waived || false,
        acknowledge_meltwater_validation: opts.acknowledge_meltwater_validation || false,
      },
    ),

  // Research Plan
  generatePlan: (projectId: number) =>
    post<{ job_id: string; project_id: number; status?: string; prerequisites?: Record<string, unknown> }>(
      "/plan/generate",
      { project_id: projectId },
    ),

  getPlan: (projectId: number) =>
    get<PlanResult>(`/plan/${projectId}`),

  approvePlan: (planId: number, reviewer = "analyst") =>
    post<{ ok: boolean }>(`/plan/${planId}/approve`, { reviewer }),

  rejectPlan: (planId: number, notes = "") =>
    post<{ ok: boolean }>(`/plan/${planId}/reject`, { notes }),

  regeneratePlan: (projectId: number) =>
    post<{ job_id: string; project_id: number }>("/plan/regenerate", {
      project_id: projectId,
    }),

  validatePlanPrereqs: (projectId: number) =>
    post<{
      ready: boolean;
      prerequisites: Record<string, { status: string; message: string }>;
    }>("/plan/validate", { project_id: projectId }),

  // Research Execution
  startExecution: (projectId: number) =>
    post<{ job_id: string; project_id: number }>("/execution/start", {
      project_id: projectId,
    }),

  getExecutionStatus: (projectId: number) =>
    get<{
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
      units: {
        id: number;
        unit_id: string;
        objective_id: string;
        method: string;
        status: string;
        progress_pct: number;
        records_processed: number;
        evidence_count: number;
        error: string | null;
      }[];
      logs: {
        level: string;
        message: string;
        unit_id: string | null;
        created_at: number;
      }[];
    }>(`/execution/${projectId}`),

  pauseExecution: (runId: number) =>
    post<{ ok: boolean }>(`/execution/${runId}/pause`),

  resumeExecution: (runId: number, projectId: number) =>
    post<{ job_id: string }>(`/execution/${runId}/resume`, {
      project_id: projectId,
    }),

  cancelExecution: (runId: number) =>
    post<{ ok: boolean }>(`/execution/${runId}/cancel`),

  retryUnit: (runId: number, unitId: string, projectId: number) =>
    post<{ status: string; evidence_count?: number }>(
      `/execution/${runId}/retry/${unitId}`,
      { project_id: projectId },
    ),

  getEvidence: (runId: number, unitId?: string) =>
    get<unknown[]>(`/execution/${runId}/evidence${unitId ? `?unit_id=${unitId}` : ""}`),

  getExecutionLogs: (runId: number, limit = 100) =>
    get<unknown[]>(`/execution/${runId}/logs?limit=${limit}`),

  // Evidence Library
  ingestEvidence: (projectId: number, runId: number) =>
    post<{ ingested: number; skipped: number; duplicates_found: number; total: number }>(
      "/library/ingest",
      { project_id: projectId, run_id: runId },
    ),

  listLibraryItems: (
    projectId: number,
    opts?: {
      review_status?: string;
      objective_id?: string;
      unit_id?: string;
      method?: string;
      platform?: string;
      confidence?: string;
      is_representative?: boolean;
      is_high_value?: boolean;
      search?: string;
      sort_by?: string;
      sort_dir?: string;
      limit?: number;
      offset?: number;
    },
  ) => {
    const params = new URLSearchParams();
    if (opts) {
      Object.entries(opts).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
      });
    }
    const qs = params.toString();
    return get<unknown[]>(`/library/${projectId}${qs ? `?${qs}` : ""}`);
  },

  getLibraryDetail: (itemId: number) =>
    get<unknown>(`/library/detail/${itemId}`),

  reviewEvidence: (itemId: number, status: string, reviewer = "analyst", note?: string) =>
    post<unknown>(`/library/${itemId}/review`, { status, reviewer, note }),

  annotateEvidence: (itemId: number, note: string, author = "analyst") =>
    post<{ annotation_id: number }>(`/library/${itemId}/annotate`, { note, author }),

  bulkReview: (itemIds: number[], status: string, reviewer = "analyst") =>
    post<{ updated: number }>("/library/bulk-review", {
      item_ids: itemIds,
      status,
      reviewer,
    }),

  updateClassification: (
    itemId: number,
    opts: { objective_id?: string; unit_id?: string; confidence?: string; reviewer?: string },
  ) => post<{ ok: boolean }>(`/library/${itemId}/classify`, opts),

  markRepresentative: (itemId: number, value = true) =>
    post<{ ok: boolean }>(`/library/${itemId}/representative`, {
      is_representative: value,
    }),

  markHighValue: (itemId: number, value = true) =>
    post<{ ok: boolean }>(`/library/${itemId}/high-value`, {
      is_high_value: value,
    }),

  restoreRejected: (itemId: number) =>
    post<unknown>(`/library/${itemId}/restore`),

  getLibrarySummary: (projectId: number) =>
    get<{
      total: number;
      unreviewed: number;
      accepted: number;
      rejected: number;
      needs_review: number;
      representative: number;
      high_value: number;
      duplicate_groups: number;
      objectives_covered: number;
      objectives_insufficient: number;
    }>(`/library/${projectId}/summary`),

  getLibraryCoverage: (projectId: number) =>
    get<{
      objectives: unknown[];
      summary: {
        total_objectives: number;
        covered: number;
        partial: number;
        insufficient: number;
        blocking_gaps: number;
      };
    }>(`/library/${projectId}/coverage`),

  getDuplicateGroups: (projectId: number) =>
    get<{ group: string; count: number; canonical_id: number | null }[]>(
      `/library/${projectId}/duplicates`,
    ),

  getAuditHistory: (itemId: number) =>
    get<unknown[]>(`/library/audit/${itemId}`),

  // Jobs
  listJobs: (projectId: number, jobType?: string) =>
    get<JobStatus[]>(`/jobs/${projectId}${jobType ? `?job_type=${jobType}` : ""}`),

  getJob: (jobId: string) =>
    get<JobStatus>(`/job/${jobId}`),

  // Insights
  generateInsights: (projectId: number) =>
    post<{ generated: number; objectives_covered: number; objectives_skipped: number; generation_id: string }>("/insights/generate", { project_id: projectId }),

  listInsights: (projectId: number, params?: { objective_id?: string; insight_type?: string; status?: string; sort_by?: string; sort_dir?: string }) => {
    const query = new URLSearchParams();
    if (params?.objective_id) query.set("objective_id", params.objective_id);
    if (params?.insight_type) query.set("insight_type", params.insight_type);
    if (params?.status) query.set("status", params.status);
    if (params?.sort_by) query.set("sort_by", params.sort_by);
    if (params?.sort_dir) query.set("sort_dir", params.sort_dir);
    const qs = query.toString();
    return get<Insight[]>(`/insights/${projectId}${qs ? `?${qs}` : ""}`);
  },

  getInsightDetail: (insightId: number) =>
    get<InsightDetail>(`/insights/detail/${insightId}`),

  reviewInsight: (insightId: number, status: string, reviewer?: string, notes?: string) =>
    post<Insight>(`/insights/${insightId}/review`, { status, reviewer, notes }),

  requestRevision: (insightId: number, notes: string) =>
    post<Insight>(`/insights/${insightId}/revision`, { notes }),

  updateAnalystNotes: (insightId: number, notes: string) =>
    post<Insight>(`/insights/${insightId}/notes`, { notes }),

  regenerateInsight: (insightId: number) =>
    post<Insight>(`/insights/${insightId}/regenerate`, {}),

  getInsightsSummary: (projectId: number) =>
    get<InsightsSummary>(`/insights/${projectId}/summary`),

  validateInsight: (insightId: number) =>
    get<InsightValidation>(`/insights/${insightId}/validate`),

  getInsightEvidence: (insightId: number) =>
    get<InsightEvidence[]>(`/insights/${insightId}/evidence`),

  validateInsightPrereqs: (projectId: number) =>
    post<{ valid: boolean; blockers?: string[] }>("/insights/validate-prereqs", { project_id: projectId }),

  // Storyline
  generateStoryline: (projectId: number) =>
    post<{ storyline_id: number; node_count: number; generation_id: string }>("/storyline/generate", { project_id: projectId }),

  validateStorylinePrereqs: (projectId: number) =>
    post<{ valid: boolean; blockers?: string[] }>("/storyline/validate-prereqs", { project_id: projectId }),

  getStoryline: (projectId: number) =>
    get<Storyline[]>(`/storyline/${projectId}`),

  getStorylineDetail: (storylineId: number) =>
    get<StorylineDetail>(`/storyline/detail/${storylineId}`),

  getStorylineSummary: (projectId: number) =>
    get<StorylineSummary>(`/storyline/${projectId}/summary`),

  listStorylineNodes: (storylineId: number) =>
    get<StoryNodeEnriched[]>(`/storyline/${storylineId}/nodes`),

  validateStoryline: (storylineId: number) =>
    get<StorylineValidation>(`/storyline/${storylineId}/validate`),

  reorderNodes: (storylineId: number, nodeIds: number[]) =>
    post<{ ok: boolean }>(`/storyline/${storylineId}/reorder`, { node_ids: nodeIds }),

  mergeNodes: (storylineId: number, nodeIdA: number, nodeIdB: number) =>
    post<StoryNodeEnriched>(`/storyline/${storylineId}/merge`, { node_id_a: nodeIdA, node_id_b: nodeIdB }),

  approveStoryline: (storylineId: number, reviewer?: string) =>
    post<{ ok: boolean }>(`/storyline/${storylineId}/approve`, { reviewer }),

  rejectStoryline: (storylineId: number, reviewer?: string) =>
    post<{ ok: boolean }>(`/storyline/${storylineId}/reject`, { reviewer }),

  reviewNode: (nodeId: number, status: string, reviewer?: string) =>
    post<StoryNode>(`/storyline/node/${nodeId}/review`, { status, reviewer }),

  splitNode: (nodeId: number) =>
    post<{ nodes: StoryNodeEnriched[] }>(`/storyline/node/${nodeId}/split`, {}),

  updateNode: (nodeId: number, updates: Partial<{ title: string; narrative_summary: string; purpose: string; suggested_visual: string; priority: string; is_key_message: boolean; is_locked: boolean }>) =>
    fetch(`${API_BASE}/storyline/node/${nodeId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    }).then((r) => json<StoryNode>(r)),

  // Slide Intelligence
  siIngest: (filePath: string) => post<any>('/slide-intel/ingest', { file_path: filePath }),
  siDashboard: () => get<SIDashboard>('/slide-intel/dashboard'),
  siPresentations: () => get<SIPresentation[]>('/slide-intel/presentations'),
  siPresentation: (id: number) => get<any>(`/slide-intel/presentations/${id}`),
  siSlides: (params?: Record<string, any>) => {
    const qs = params ? '?' + new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([_, v]) => v != null).map(([k, v]) => [k, String(v)]))
    ).toString() : '';
    return get<SISlide[]>(`/slide-intel/slides${qs}`);
  },
  siSlide: (id: number) => get<any>(`/slide-intel/slides/${id}`),
  siUpdateMetadata: (id: number, updates: Record<string, string>) =>
    fetch(`${API_BASE}/slide-intel/slides/${id}/metadata`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    }).then((r) => json<any>(r)),
  siExcludeSlide: (id: number) => post<any>(`/slide-intel/slides/${id}/exclude`, {}),
  siIncludeSlide: (id: number) => post<any>(`/slide-intel/slides/${id}/include`, {}),
  siReprocessSlide: (id: number) => post<any>(`/slide-intel/slides/${id}/reprocess`, {}),
  siTemplates: () => get<SITemplateFamily[]>('/slide-intel/templates'),
  siTemplate: (id: number) => get<any>(`/slide-intel/templates/${id}`),
  siApproveTemplate: (id: number) => post<any>(`/slide-intel/templates/${id}/approve`, {}),
  siDetectedProjects: (presId: number) => get<SIDetectedProject[]>(`/slide-intel/detected-projects/${presId}`),
  siStylePatterns: (presId?: number) => get<any[]>(`/slide-intel/style-patterns${presId ? `?presentation_id=${presId}` : ''}`),
  siSearch: (query: string, filters?: Record<string, any>) => post<any>('/slide-intel/search', { query, ...filters }),
  siRetrieve: (nodeId: number, topK?: number) => post<any>('/slide-intel/retrieve', { node_id: nodeId, top_k: topK || 10 }),
  siMatchStoryline: (storylineId: number) => post<any>('/slide-intel/match-storyline', { storyline_id: storylineId }),
  siStorylineMatches: (storylineId: number) => get<any>(`/slide-intel/storyline-matches/${storylineId}`),
  siRecommend: (nodeId: number) => get<SIRecommendation>(`/slide-intel/recommend/${nodeId}`),
  siDuplicates: (presId?: number) => get<any>(`/slide-intel/duplicates${presId ? `?presentation_id=${presId}` : ''}`),
  siProcessingLog: (presId: number) => get<any[]>(`/slide-intel/processing-log/${presId}`),

  // Presentation Composer
  composerGenerate: (projectId: number) =>
    post<{ presentation_id: number; slides_created: number; estimated_duration_minutes: number; generation_id: string }>("/composer/generate", { project_id: projectId }),

  composerValidatePrereqs: (projectId: number) =>
    post<{ valid: boolean; blockers?: string[] }>("/composer/validate-prereqs", { project_id: projectId }),

  composerList: (projectId: number) =>
    get<PCPresentation[]>(`/composer/${projectId}`),

  composerSummary: (projectId: number) =>
    get<PCPresentationSummary>(`/composer/${projectId}/summary`),

  composerDetail: (presId: number) =>
    get<PCPresentationDetail>(`/composer/detail/${presId}`),

  composerSlides: (presId: number) =>
    get<PCSlide[]>(`/composer/slides/${presId}`),

  composerSlide: (slideId: number) =>
    get<PCSlide>(`/composer/slide/${slideId}`),

  composerUpdateSlide: (slideId: number, updates: Partial<{ title: string; subtitle: string; narrative: string; key_message: string; recommended_visual: string; recommended_chart: string; layout_recommendation: string; speaker_notes: string; slide_purpose: string }>) =>
    fetch(`${API_BASE}/composer/slide/${slideId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    }).then((r) => json<PCSlide>(r)),

  composerReviewSlide: (slideId: number, status: string, reviewer?: string) =>
    post<PCSlide>(`/composer/slide/${slideId}/review`, { status, reviewer }),

  composerLockSlide: (slideId: number) =>
    post<PCSlide>(`/composer/slide/${slideId}/lock`, {}),

  composerUnlockSlide: (slideId: number) =>
    post<PCSlide>(`/composer/slide/${slideId}/unlock`, {}),

  composerSelectLayout: (slideId: number, layout: string, rationale?: string) =>
    post<PCSlide>(`/composer/slide/${slideId}/layout`, { layout, rationale }),

  composerSelectVisual: (slideId: number, visual: string) =>
    post<PCSlide>(`/composer/slide/${slideId}/visual`, { visual }),

  composerReorder: (presId: number, slideIds: number[]) =>
    post<{ reordered: boolean }>(`/composer/${presId}/reorder`, { slide_ids: slideIds }),

  composerApprove: (presId: number, reviewer?: string) =>
    post<PCPresentation>(`/composer/${presId}/approve`, { reviewer }),

  composerReject: (presId: number, reviewer?: string) =>
    post<PCPresentation>(`/composer/${presId}/reject`, { reviewer }),

  composerValidate: (presId: number) =>
    get<PCValidation>(`/composer/${presId}/validate`),

  composerTransitions: (presId: number) =>
    post<{ transitions_updated: number }>(`/composer/${presId}/transitions`, {}),

  composerAudit: (presId: number) =>
    get<any[]>(`/composer/audit/${presId}`),

  // PowerPoint Renderer
  rendererRender: (presentationId: number, themeId?: string) =>
    post<RenderResult>("/renderer/render", { presentation_id: presentationId, theme_id: themeId || "hunter_default" }),

  rendererRenderSlide: (slideId: number, themeId?: string) =>
    post<RenderResult>(`/renderer/render-slide/${slideId}`, { theme_id: themeId || "hunter_default" }),

  rendererRenderSection: (presId: number, purpose: string, themeId?: string) =>
    post<RenderResult>(`/renderer/render-section/${presId}`, { purpose, theme_id: themeId || "hunter_default" }),

  rendererStatus: (jobId: string) =>
    get<RenderJob>(`/renderer/status/${jobId}`),

  rendererDownloadUrl: (jobId: string) =>
    `${API_BASE}/renderer/download/${jobId}`,

  rendererThemes: () =>
    get<RenderTheme[]>("/renderer/themes"),

  rendererValidate: (presId: number) =>
    post<RenderValidation>(`/renderer/validate/${presId}`, {}),

  rendererSummary: (presId: number) =>
    get<RenderSummary>(`/renderer/summary/${presId}`),

  rendererJobs: (presId: number) =>
    get<RenderJob[]>(`/renderer/jobs/${presId}`),

  rendererHistory: (presId: number) =>
    get<RenderHistory[]>(`/renderer/history/${presId}`),

  rendererMetrics: (jobId: string) =>
    get<RenderMetric[]>(`/renderer/metrics/${jobId}`),

  // ── Pipeline Orchestrator ─────────────────────────────────────────

  pipelineStart: (projectId: number, mode = "full", startStage?: string, singleStage?: string) =>
    post<any>("/pipeline/start", { project_id: projectId, mode, start_stage: startStage, single_stage: singleStage }),

  pipelinePause: (runId: string) =>
    post<any>(`/pipeline/${runId}/pause`, {}),

  pipelineResume: (runId: string) =>
    post<any>(`/pipeline/${runId}/resume`, {}),

  pipelineCancel: (runId: string) =>
    post<any>(`/pipeline/${runId}/cancel`, {}),

  pipelineRetry: (runId: string, stageId: string) =>
    post<any>(`/pipeline/${runId}/retry`, { stage_id: stageId }),

  pipelineRunStage: (projectId: number, stageId: string) =>
    post<any>("/pipeline/run-stage", { project_id: projectId, single_stage: stageId }),

  pipelineRunFrom: (projectId: number, stageId: string) =>
    post<any>("/pipeline/run-from", { project_id: projectId, start_stage: stageId }),

  pipelineStatus: (runId: string) =>
    get<PipelineRunDetail>(`/pipeline/status/${runId}`),

  pipelineProjectStatus: (projectId: number) =>
    get<PipelineProjectStatus>(`/pipeline/project/${projectId}`),

  pipelineTimeline: (runId: string) =>
    get<PipelineTimelineEntry[]>(`/pipeline/timeline/${runId}`),

  pipelineLogs: (runId: string, stageId?: string) =>
    get<PipelineLog[]>(`/pipeline/logs/${runId}${stageId ? `?stage_id=${stageId}` : ""}`),

  pipelineMetrics: (projectId: number) =>
    get<PipelinePerformance>(`/pipeline/metrics/${projectId}`),

  pipelineCache: (projectId: number) =>
    get<PipelineCacheMetrics>(`/pipeline/cache/${projectId}`),

  pipelineClearCache: (projectId: number, stageId?: string) =>
    post<{ cleared: number }>(`/pipeline/cache/${projectId}/clear`, { stage_id: stageId }),

  pipelineGraph: () =>
    get<Record<string, PipelineDependencyNode>>("/pipeline/graph"),

  pipelineStages: (projectId: number) =>
    get<Record<string, PipelineStageStatus>>(`/pipeline/stages/${projectId}`),

  // ── Word Report Renderer ─────────────────────────────────────────

  wordRender: (presentationId: number, themeId = "hunter_default", actor = "system") =>
    post<WordRenderResult>("/word-renderer/render", { presentation_id: presentationId, theme_id: themeId, actor }),

  wordRenderSection: (presId: number, sectionName: string, themeId = "hunter_default", actor = "system") =>
    post<WordRenderResult>(`/word-renderer/render-section/${presId}`, { section_name: sectionName, theme_id: themeId, actor }),

  wordValidate: (presId: number) =>
    post<WordValidation>(`/word-renderer/validate/${presId}`),

  wordRenderStatus: (jobId: string) =>
    get<WordRenderJob>(`/word-renderer/status/${jobId}`),

  wordDownloadUrl: (jobId: string) =>
    `${API_BASE}/word-renderer/download/${jobId}`,

  wordThemes: () =>
    get<RenderTheme[]>("/word-renderer/themes"),

  wordRenderSummary: (presId: number) =>
    get<WordRenderSummary>(`/word-renderer/summary/${presId}`),

  wordJobs: (presId: number) =>
    get<WordRenderJob[]>(`/word-renderer/jobs/${presId}`),

  wordHistory: (presId: number, limit = 50) =>
    get<WordRenderHistory[]>(`/word-renderer/history/${presId}?limit=${limit}`),

  wordMetrics: (jobId: string) =>
    get<WordRenderMetric[]>(`/word-renderer/metrics/${jobId}`),

  // ── Publishing & Quality Gateway ─────────────────────────────────

  pubValidate: (projectId: number, presentationId: number, actor = "system") =>
    post<PubValidationResult>("/publishing/validate", { project_id: projectId, presentation_id: presentationId, actor }),

  pubCompare: (projectId: number, presentationId: number, actor = "system") =>
    post<PubDiffReport>("/publishing/compare", { project_id: projectId, presentation_id: presentationId, actor }),

  pubPackage: (projectId: number, presentationId: number, actor = "system") =>
    post<PubPackageResult>("/publishing/package", { project_id: projectId, presentation_id: presentationId, actor }),

  pubCreateVersion: (projectId: number, presentationId: number, actor = "system", notes?: string) =>
    post<PubVersionResult>("/publishing/version", { project_id: projectId, presentation_id: presentationId, actor, notes }),

  pubSubmit: (projectId: number, presentationId: number, actor = "system", notes?: string) =>
    post<PubApprovalResult>("/publishing/submit", { project_id: projectId, presentation_id: presentationId, actor, notes }),

  pubApprove: (projectId: number, presentationId: number, actor = "system", notes?: string) =>
    post<PubApprovalResult>("/publishing/approve", { project_id: projectId, presentation_id: presentationId, actor, notes }),

  pubReject: (projectId: number, presentationId: number, actor = "system", notes?: string) =>
    post<PubApprovalResult>("/publishing/reject", { project_id: projectId, presentation_id: presentationId, actor, notes }),

  pubRevision: (projectId: number, presentationId: number, actor = "system", notes?: string) =>
    post<PubApprovalResult>("/publishing/revision", { project_id: projectId, presentation_id: presentationId, actor, notes }),

  pubPublish: (projectId: number, presentationId: number, actor = "system", notes?: string) =>
    post<PubApprovalResult>("/publishing/publish", { project_id: projectId, presentation_id: presentationId, actor, notes }),

  pubArchive: (projectId: number, presentationId: number, actor = "system", notes?: string) =>
    post<PubApprovalResult>("/publishing/archive", { project_id: projectId, presentation_id: presentationId, actor, notes }),

  pubReadiness: (projectId: number, presId: number) =>
    get<PubReadinessSummary>(`/publishing/readiness/${projectId}/${presId}`),

  pubVersions: (presId: number) =>
    get<PubVersion[]>(`/publishing/versions/${presId}`),

  pubAudit: (projectId: number, limit = 100) =>
    get<PubAuditEntry[]>(`/publishing/audit/${projectId}?limit=${limit}`),

  pubValidationDetail: (validationId: number) =>
    get<PubValidation>(`/publishing/validation/${validationId}`),

  pubValidations: (presId: number) =>
    get<PubValidation[]>(`/publishing/validations/${presId}`),

  pubDiff: (presId: number) =>
    get<PubDiffReport>(`/publishing/diff/${presId}`),

  pubPackageDetail: (packageId: number) =>
    get<PubPackage>(`/publishing/package/${packageId}`),

  pubPackages: (presId: number) =>
    get<PubPackage[]>(`/publishing/packages/${presId}`),

  pubDownloadPackageUrl: (packageId: number) =>
    `${API_BASE}/publishing/download/package/${packageId}`,

  pubDownloadPptxUrl: (presId: number) =>
    `${API_BASE}/publishing/download/pptx/${presId}`,

  pubDownloadWordUrl: (presId: number) =>
    `${API_BASE}/publishing/download/word/${presId}`,

  pubDownloads: (projectId: number, limit = 50) =>
    get<PubDownload[]>(`/publishing/downloads/${projectId}?limit=${limit}`),

  pubApprovals: (presId: number, limit = 50) =>
    get<PubApproval[]>(`/publishing/approvals/${presId}?limit=${limit}`),

  pubStats: (projectId: number) =>
    get<Record<string, number>>(`/publishing/stats/${projectId}`),

  // ─── Monitoring QC ───────────────────────────────────────────────────

  qcGetReport: (projectId: number) =>
    get<Record<string, unknown>>(`/qc/report/${projectId}`),

  qcGetReportDetail: (reportId: number) =>
    get<Record<string, unknown>>(`/qc/report/detail/${reportId}`),

  qcGetPreview: (reportId: number) =>
    get<{ status: string; preview: Record<string, string>[]; error?: string }>(`/qc/preview/${reportId}`),

  qcSaveFieldMapping: (reportId: number, mapping: Record<string, string>) =>
    post<{ ok: boolean }>(`/qc/field-mapping/${reportId}`, { mapping }),

  qcStartRun: (reportId: number) =>
    post<{ status: string; report_id: number; job_id: string }>(`/qc/run/${reportId}`),

  qcGetRuns: (reportId: number) =>
    get<Record<string, unknown>[]>(`/qc/runs/${reportId}`),

  qcGetResults: (runId: number, severity?: string, checkType?: string) => {
    const params = new URLSearchParams();
    if (severity) params.set("severity", severity);
    if (checkType) params.set("check_type", checkType);
    const qs = params.toString();
    return get<Record<string, unknown>[]>(`/qc/results/${runId}${qs ? `?${qs}` : ""}`);
  },

  qcGetSummary: (runId: number) =>
    get<Record<string, unknown>>(`/qc/summary/${runId}`),

  qcFindingAction: (findingId: number, action: string) =>
    post<{ ok: boolean }>(`/qc/finding/${findingId}/action`, { action }),

  qcExport: (runId: number) =>
    post<{ export_id: number; file_name: string }>(`/qc/export/${runId}`),

  qcExportDownloadUrl: (exportId: number) =>
    `${API_BASE}/qc/export/download/${exportId}`,
};

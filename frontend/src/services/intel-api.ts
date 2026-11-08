import type { ArticleFacets, ArticleFilters, ArticlePage, ArticleRow, Channel, RqCounts, RqEstimate, RqPreview, RqStatus, RqSummary, UploadResult, UploadedFile } from "../types/dataset";
import type { UsageCallsPage, UsagePriceRequest, UsagePrices, UsageQuery, UsageSummary } from "../types/usage";

// Empty by default (relative paths), matching same-origin deploys where the backend
// serves the built SPA directly. Set VITE_API_BASE_URL (e.g. "https://api.example.com")
// when the frontend and backend are deployed on separate origins (FE on Vercel, BE on
// Render) — see also ws.ts, which derives the WebSocket origin from the same variable.
const API_ORIGIN = import.meta.env.VITE_API_BASE_URL ?? "";
export type ExclusionKind = "domain" | "keyword";
export interface ExclusionRecord {
  id: number; kind: ExclusionKind; value: string; created_at: number;
  kept_relevant?: number; last_comment?: string | null;     // org memory of analysts keeping blocked articles
}

export const API_BASE = `${API_ORIGIN}/api/intel`;

// "include" is required (not just "same-origin", the fetch default) once API_ORIGIN
// points at a different origin than the page — otherwise the browser never attaches
// the session cookie to the request. Harmless same-origin too, so always set it.
export const CREDENTIALS: RequestCredentials = "include";

async function json<T>(res: Response): Promise<T> {
  const ct = res.headers.get("content-type") || "";
  if (!ct.includes("application/json")) {
    throw new Error("Backend not reachable — restart the backend server");
  }
  if (!res.ok) {
    // keep the "<status>: " prefix (callers check it), but show FastAPI's readable detail, not the raw JSON body
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail
      : Array.isArray(body?.detail) ? body.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ")
      : res.statusText;
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return fetch(`${API_BASE}${path}`, {
    method: "POST",
    credentials: CREDENTIALS,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  }).then((r) => json<T>(r));
}

function get<T>(path: string): Promise<T> {
  return fetch(`${API_BASE}${path}`, { credentials: CREDENTIALS }).then((r) => json<T>(r));
}

function put<T>(path: string, body?: unknown): Promise<T> {
  return fetch(`${API_BASE}${path}`, {
    method: "PUT",
    credentials: CREDENTIALS,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  }).then((r) => json<T>(r));
}

function del<T>(path: string): Promise<T> {
  return fetch(`${API_BASE}${path}`, { method: "DELETE", credentials: CREDENTIALS }).then((r) => json<T>(r));
}

function patch<T>(path: string, body?: unknown): Promise<T> {
  return fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    credentials: CREDENTIALS,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  }).then((r) => json<T>(r));
}

/** Query string for the Data set page / select-all endpoints: only the filters that are set. */
function articleQuery(f: ArticleFilters, extra: Record<string, number> = {}): string {
  const p = new URLSearchParams({ channel: f.channel });
  for (const k of ["status", "rq", "sentiment", "theme", "brand", "content_status", "q", "pool"] as const) {
    if (f[k] && !(k === "status" && f[k] === "all")) p.set(k, f[k]);
  }
  Object.entries(extra).forEach(([k, v]) => p.set(k, String(v)));
  return p.toString();
}

const AUTH_BASE = `${API_ORIGIN}/api/auth`;

async function authJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || res.statusText || "Request failed");
  }
  return res.json();
}

function authPost<T>(path: string, body?: unknown): Promise<T> {
  return fetch(`${AUTH_BASE}${path}`, {
    method: "POST",
    credentials: CREDENTIALS,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  }).then((r) => authJson<T>(r));
}

function authGet<T>(path: string): Promise<T> {
  return fetch(`${AUTH_BASE}${path}`, { credentials: CREDENTIALS }).then((r) => authJson<T>(r));
}

function authDelete<T>(path: string): Promise<T> {
  return fetch(`${AUTH_BASE}${path}`, { method: "DELETE", credentials: CREDENTIALS }).then((r) => authJson<T>(r));
}

export interface AuthUser {
  id: number;
  email: string;
  display_name: string;
  role: "super_admin" | "admin" | "analyser";
  org_id: number | null;
  org_name: string | null;
  org_logo_url?: string | null;
  avatar_url: string | null;
  must_change_password: boolean;
}

export interface AuthUserRow {
  id: number;
  org_id: number | null;
  email: string;
  display_name: string;
  role: string;
  avatar_url: string | null;
  archived_at: number | null;
  created_at: number | null;
}

export interface UserOrganizationRow {
  id: number;
  name: string;
  is_primary: boolean;
}

export interface AuthOrganizationRow {
  id: number;
  name: string;
  admin_name: string | null;
  admin_email: string | null;
  archived_at: number | null;
  temp_password?: string | null;  // only on create: the new admin's one-time password
}

async function authUpload<T>(path: string, form: FormData): Promise<T> {
  return fetch(`${AUTH_BASE}${path}`, { method: "POST", credentials: CREDENTIALS, body: form }).then((r) => authJson<T>(r));
}

function authPatch<T>(path: string, body?: unknown): Promise<T> {
  return fetch(`${AUTH_BASE}${path}`, {
    method: "PATCH",
    credentials: CREDENTIALS,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  }).then((r) => authJson<T>(r));
}

// ─── Types ──────────────────────────────────────────────────────────────────

export interface ExclusionImportResult {
  added: number; duplicates: number; invalid: string[]; invalid_count: number; total: number;
}

export interface DataSourceRecord {
  source: string;
  display_name: string;
  renew_url: string;
  configured: boolean;
  masked_key: string | null;
  status: "not_configured" | "ok" | "expired";
  expired_at: number | null;
  last_error: string | null;
  updated_at: number | null;
}

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
    search_log: { topic: string; query: string }[];
    research_gaps: string[];
    search_degraded?: boolean;
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

export interface ArticleBlock {
  type: "heading" | "paragraph" | "image";
  text?: string | null;
  src?: string | null;
  alt?: string | null;
}

export interface ArticleFullTextResponse {
  status: "ok" | "failed" | "paywalled" | "social_media" | "video";
  title: string | null;
  blocks: ArticleBlock[];
  error: string | null;
  platform: string | null;
  embed_url: string | null;
  cached: boolean;
}

export interface ResearchItem {
  id: number;
  topic: string;
  source_api: string;
  publication: string | null;
  domain: string | null;
  title: string | null;
  content: string | null;
  url: string;
  author: string | null;
  thumbnail_url: string | null;
  published_date: number;
  keywords_matched: string[];
  relevant: boolean;
  /** "free" opens for readers; "paid" = the site refuses readers or paywalls; null = not checked yet */
  access: "free" | "paid" | null;
}

export interface ResearchItemsResult {
  items: ResearchItem[];
  total: number;
}

/** Related item ids, closest first. Syndicated: the same article by another publisher.
 * Similar: a different article on the same theme, content or context. */
export interface ItemRelations {
  syndicated: number[];
  similar: number[];
}

/** Jev's answers per item: probability it is about the brief's brand, and its tone toward the brand. */
export interface ItemClassification {
  about_brand: number | null;
  sentiment: "positive" | "neutral" | "negative" | null;
  sentiment_confidence: number | null;
}

export interface ResearchItemClassificationResult {
  classifications: Record<string, ItemClassification>;
  method: "jev" | "jev_partial" | "rules";
}

/** Related Review-tab rows, as "<dataset_id>:<record id>" keys. */
export interface RowRelations {
  syndicated: string[];
  similar: string[];
}

export interface ResearchItemRelationsResult {
  relations: Record<string, ItemRelations>;
  method: "embeddings" | "embeddings_partial" | "titles";
}

export interface StrategyResult {
  strategy_id: number;
  version: number;
  approval_status: string;
  strategy: Record<string, unknown>;
  query_versions: unknown[];
  created_at: number;
}

export interface BrandSentiment {
  brand: string;
  is_primary: boolean;
  sentiment: "Positive" | "Neutral" | "Negative" | null;
  confidence: number | null;
}

/** One tag a research question needs, derived from the question itself (no fixed taxonomy). */
export interface DynamicTagDef {
  tag_name: string;
  tag_type: "classification" | "multi_classification" | "entity";
  definition: string;
  allowed_values: string[];
  extraction_rule: string;
  review_column: string | null;
}

export interface EnrichedRecord {
  id: string;
  title: string;
  content: string;
  url: string;
  date: string;
  source_name: string;
  author: string;
  country: string;
  media_type: string;
  reach: string;
  overall_sentiment: "Positive" | "Neutral" | "Negative" | null;
  overall_sentiment_confidence: number | null;
  themes: { primary: string | null; secondary: string | null; tertiary: string | null };
  signals: string[];
  entities: {
    brands: string[]; companies: string[]; organizations: string[];
    people: string[]; products: string[]; events: string[];
  };
  brand_sentiments: BrandSentiment[];
  reason: string | null;
  enrichment_error?: string | null;
  dataset_id?: number;
  dataset_file_name?: string;
  research_question_id?: string | null;
  review_status?: "relevant" | "irrelevant";
  approval_status?: "pending" | "approved" | "disapproved";
  disapproval_reason?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  manually_edited?: boolean;
  /** Research-question dimension key -> values the LLM tagged (e.g. sport: ["Soccer"]). */
  question_tags?: Record<string, string[]>;
  author_type?: string;
  /** The question's dynamic tags for this article, with the quote that supports each and a 0-1 confidence. */
  dynamic_tags?: Record<string, string | string[]>;
  tag_evidence?: Record<string, string>;
  tag_confidence?: Record<string, number>;
  tag_schema_question?: string;
  /** One sentence on what the article says about its research question. */
  question_summary?: string;
  /** The research question's search keywords the article actually contains. */
  keyword_matches?: string[];
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
  /** Register refs (S#) this section cites — set server-side after citation checks (older briefs omit it). */
  sources?: string[];
  /** True when no valid citation survived for this section. */
  unsourced?: boolean;
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
  search_log: { topic: string; query: string }[];
  metadata: {
    sources_reviewed: number;
    sources_retained: number;
    sources_rejected: number;
    tier_1_count: number;
    tier_2_count: number;
    tier_3_count: number;
    search_queries_executed: number;
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
  /** Industry classification identified from the brief (agents/brief_scope.py RULE #8). */
  industry?: { name: string; reasoning: string } | Record<string, never>;
  generated_at: number;
}

export interface SpecResult {
  id: number;
  project_id: number;
  version: number;
  spec_json: string;
  raw_brief_text: string | null;
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

/** Ack for POST /spec/generate — the job runs in the background; track it via `job_id`
 * (WS `intel_job_update` messages carrying this job_id, or poll with `getJob`). */
export interface SpecGenerationStarted {
  job_id: string;
  project_id: number;
  status: string;
}

export interface PexelsImageResponse {
  query: string;
  image_url: string | null;
  video_url: string | null;
  photographer: string | null;
  source_url: string | null;
  cached: boolean;
}

export interface SectionVideoResponse {
  query: string;
  video_id: string | null;
  embed_url: string | null;
  title: string | null;
  thumbnail_url: string | null;
  cached: boolean;
}

// ─── API Functions ──────────────────────────────────────────────────────────

export interface BriefSource {
  type: string; // pdf | docx | doc | pptx | ppt | xlsx | xls | txt | text
  file_name?: string;
}

/** Row returned by GET /projects — card fields are resolved server-side. */
export interface ProjectSummary {
  id: number;
  project_name: string;
  project_type: string;
  /** Primary brand (spec.commissioning_brand.name) — fed to Brandfetch for the logo. */
  brand: string | null;
  description: string;
  geography: string;
  client: string;
  /** Where the brief came from: an uploaded file type (pdf, docx, ...) or "text" (pasted). */
  brief_source: BriefSource | null;
  created_at: number;
  updated_at: number;
  /** Live pipeline position: done stages count in full, a running stage adds its job's share. */
  progress_pct?: number;
  current_stage?: string;
  org_id?: number | null;
  owner_user_id?: number | null;
  archived_at?: number | null;
}

export interface OrgProfileInput {
  logo_url?: string | null; procurement_phone?: string; address?: string; country?: string; pin_code?: string;
  plan_id?: number;
}
export interface PlanInput {
  name: string; max_users: number; max_projects: number; duration_months: number; price: number; currency: string;
  active: boolean;
}
export interface Plan extends Omit<PlanInput, "active"> { id: number; active: number }
export interface Subscription {
  id: number; org_id: number; plan_id: number; plan_name: string; status: string; starts_at: number | null;
  ends_at: number | null; max_users: number; max_projects: number; duration_months: number; price: number;
  currency: string;
}
export interface SubscriptionSummary {
  current: Subscription | null; queued: Subscription[]; history: Subscription[]; users: number; projects: number;
  days_left: number;
}
export interface OrgProfile {
  id: number; name: string; archived_at: number | null; created_at: number; logo_url: string | null;
  procurement_name: string | null; procurement_email: string | null; procurement_phone: string | null;
  address: string | null; country: string | null; pin_code: string | null;
}
export interface AdminOrgRow extends OrgProfile {
  plan: string | null; ends_at: number | null; days_left: number; max_users: number; max_projects: number;
  users: number; projects: number; renewal_queued: boolean; tokens_month: number;
}
export interface AdminOverview {
  counts: { orgs: number; users: number; projects: number; active_subscriptions: number; expiring_30d: number };
  orgs: AdminOrgRow[];
}
export interface OrgDetail {
  org: OrgProfile; subscription: SubscriptionSummary;
  projects: { id: number; project_name: string; brand: string | null; updated_at: number; owner_name: string | null;
    owner_email: string | null; current_stage: string | null; tokens: number }[];
  users: { id: number; email: string; display_name: string; role: string; archived_at: number | null;
    last_login: number | null; tokens_month: number; monthly_tokens: number | null }[];
}
export interface GuardrailInput { title: string; body: string; active: boolean }
export interface Guardrail extends Omit<GuardrailInput, "active"> {
  id: number; org_id: number; active: number; updated_at: number;
}

export const intelApi = {
  // Auth
  login: (email: string, password: string) => authPost<AuthUser>("/login", { email, password }),
  me: () => authGet<AuthUser>("/me"),
  logout: () => authPost<{ ok: boolean }>("/logout"),
  changePassword: (current_password: string, new_password: string) =>
    authPost<{ ok: boolean }>("/change-password", { current_password, new_password }),
  updateProfile: (display_name: string) =>
    authPatch<{ ok: boolean }>("/profile", { display_name }),
  uploadAvatar: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return authUpload<{ avatar_url: string }>("/profile/avatar", form);
  },
  createUser: (email: string, display_name: string, role: string, org_id?: number) =>
    authPost<AuthUserRow & { temp_password: string | null }>("/users", { email, display_name, role, org_id }),
  resetUserPassword: (userId: number) =>
    authPost<{ ok: boolean; temp_password: string }>(`/users/${userId}/reset-password`),
  /** Admin/Super Admin emails the user a one-time reset link. */
  sendResetEmail: (userId: number) => authPost<{ ok: boolean }>(`/users/${userId}/send-reset`),
  /** Forgot password: email → 6-digit code → a reset link is emailed → resetPassword with the link's token. */
  forgotPassword: (email: string) => authPost<{ ok: boolean; message: string }>("/forgot-password", { email }),
  verifyResetCode: (email: string, code: string) =>
    authPost<{ ok: boolean; message: string }>("/forgot-password/verify", { email, code }),
  resetPassword: (token: string, new_password: string) =>
    authPost<{ ok: boolean }>("/reset-password", { token, new_password }),
  listUsers: (orgId?: number) =>
    authGet<AuthUserRow[]>(orgId ? `/users?org_id=${orgId}` : "/users"),
  archiveUser: (userId: number) => authPost<{ ok: boolean }>(`/users/${userId}/archive`),
  createOrganization: (name: string, adminEmail: string, adminDisplayName: string, profile: OrgProfileInput = {}) =>
    authPost<AuthOrganizationRow>("/organizations", {
      name, admin_email: adminEmail, admin_display_name: adminDisplayName, ...profile,
    }),
  listOrganizations: () => authGet<AuthOrganizationRow[]>("/organizations"),
  // Subscriptions, dashboards, token allowances (domains/billing)
  listPlans: (all = false) => get<Plan[]>(`/billing/plans${all ? "?all=true" : ""}`),
  savePlan: (plan: PlanInput, id?: number) => (id ? put<Plan>(`/billing/plans/${id}`, plan) : post<Plan>("/billing/plans", plan)),
  subscription: (orgId?: number) => get<SubscriptionSummary>(`/billing/subscription${orgId ? `?org_id=${orgId}` : ""}`),
  startCheckout: (planId: number) => post<{ subscription_id: number; gateway: string }>("/billing/checkout", { plan_id: planId }),
  getCheckout: (subId: number) => get<Subscription & { org_name: string; gateway: string }>(`/billing/checkout/${subId}`),
  payCheckout: (subId: number, success: boolean) => post<Subscription>(`/billing/checkout/${subId}/pay`, { success }),
  adminOverview: () => get<AdminOverview>("/billing/overview"),
  orgDetail: (orgId: number) => get<OrgDetail>(`/billing/orgs/${orgId}`),
  setTokenLimit: (userId: number, monthlyTokens: number | null) =>
    put<{ ok: boolean }>(`/billing/token-limits/${userId}`, { monthly_tokens: monthlyTokens }),
  // Organization guardrails (sent with the org's LLM calls)
  listGuardrails: (orgId?: number) => get<Guardrail[]>(`/guardrails${orgId ? `?org_id=${orgId}` : ""}`),
  saveGuardrail: (g: GuardrailInput, id?: number) => (id ? put<Guardrail>(`/guardrails/${id}`, g) : post<Guardrail>("/guardrails", g)),
  deleteGuardrail: (id: number) => del<{ ok: boolean }>(`/guardrails/${id}`),
  archiveOrganization: (orgId: number) => authPost<{ ok: boolean }>(`/organizations/${orgId}/archive`),
  deleteOrganization: (orgId: number) => authDelete<{ ok: boolean }>(`/organizations/${orgId}`),
  deleteUser: (userId: number) => authDelete<{ ok: boolean }>(`/users/${userId}`),
  listMyOrganizations: () => authGet<UserOrganizationRow[]>("/me/organizations"),
  /** Switch the organisation this session works in; null goes back to your own org (Super Admin: all orgs). */
  setActiveOrg: (orgId: number | null) => authPost<AuthUser>("/me/active-org", { org_id: orgId }),

  // Projects
  listProjects: (type?: string) => get<ProjectSummary[]>(type ? `/projects?type=${type}` : "/projects"),

  createProject: (name: string, spec: Record<string, unknown> = {}, project_type: string = "research", brand?: string) =>
    post<{ id: number; project_name: string; project_type: string; brand?: string | null; spec: Record<string, unknown> }>("/projects", {
      project_name: name,
      spec,
      project_type,
      brand,
    }),

  getProject: (projectId: number) =>
    get<{ id: number; project_name: string; project_type: string; brand?: string | null; spec: Record<string, unknown>; archived_at?: number | null }>(`/projects/${projectId}`),

  updateProject: (id: number, body: { project_name?: string; spec?: Record<string, unknown>; brand?: string }) =>
    put<{ id: number; project_name: string; project_type: string; brand?: string | null; spec: Record<string, unknown> }>(`/projects/${id}`, body),

  /** Deletes the project and all of its pipeline data (irreversible). */
  deleteProject: (id: number) =>
    del<{ ok: boolean; project_id: number; rows_deleted: number; tables: Record<string, number> }>(`/projects/${id}`),

  // Background Research
  startResearch: (spec: Record<string, unknown>, projectId?: number) =>
    post<{ job_id: string; project_id: number }>("/research/start", { spec, project_id: projectId }),

  getResearchStatus: (jobId: string) =>
    get<JobStatus>(`/research/status/${jobId}`),

  getResearch: (projectId: number) =>
    get<ResearchResult>(`/research/${projectId}`),

  getResearchItems: (projectId: number) =>
    get<ResearchItemsResult>(`/research/${projectId}/items`),
  getResearchItemClassification: (projectId: number) =>
    get<ResearchItemClassificationResult>(`/research/${projectId}/items/classification`),
  getResearchItemRelations: (projectId: number) =>
    get<ResearchItemRelationsResult>(`/research/${projectId}/items/relations`),
  getArticleFullText: (itemId: number, force = false) =>
    get<ArticleFullTextResponse>(`/research/items/${itemId}/full-text${force ? "?force=true" : ""}`),

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
    fetch(`${API_BASE}/brief/${briefId}/download`, { credentials: CREDENTIALS }).then((r) => {
      if (!r.ok) throw new Error("Download failed");
      return r.blob();
    }),

  // Research Specification
  /** Starts spec generation in the background; returns immediately with a job_id.
   * Track progress via WS `intel_job_update` messages or `intelApi.getJob(job_id)`. */
  generateSpec: (projectId: number, rawBriefText = "", useLlm = false) =>
    post<SpecGenerationStarted>("/spec/generate", {
      project_id: projectId,
      raw_brief_text: rawBriefText,
      use_llm: useLlm,
    }),

  getSpec: (projectId: number) =>
    get<SpecResult>(`/spec/${projectId}`),

  updateSpecSection: (specId: number, sectionKey: string, content: string | Record<string, unknown> | unknown[], analystNote = "") =>
    post<{ status: string; section_key: string }>(`/spec/${specId}/section`, {
      section_key: sectionKey,
      content,
      analyst_note: analystNote,
    }),

  updateSpecIndustry: (specId: number, name: string, reasoning = "") =>
    post<{ status: string; spec_id: number }>(`/spec/${specId}/industry`, { name, reasoning }),

  approveSpec: (specId: number, reviewer = "analyst") =>
    post<{ status: string; spec_id: number }>(`/spec/${specId}/approve`, { reviewer }),

  /** Starts spec re-analysis ("Reanalyze") in the background; returns immediately with
   * a job_id — same async pattern as generateSpec(). */
  regenerateSpec: (specId: number, rawBriefText = "", useLlm = false, confirmOverwriteLocked = false) =>
    post<SpecGenerationStarted>(`/spec/${specId}/regenerate`, {
      raw_brief_text: rawBriefText,
      use_llm: useLlm,
      confirm_overwrite_locked: confirmOverwriteLocked,
    }),

  renderSpecDocx: (specId: number) =>
    post<{ status: string; docx_path: string }>(`/spec/${specId}/render`),

  downloadSpecDocx: (specId: number) =>
    fetch(`${API_BASE}/spec/${specId}/download`, { credentials: CREDENTIALS }).then((r) => {
      if (!r.ok) throw new Error("Download failed");
      return r.blob();
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

  /** The checks autorun approves through: an unapproved strategy with validation issues comes back with reasons. */
  finalApproveStrategy: (projectId: number, reviewer = "auto") =>
    post<{ approved: boolean; blocking_reasons?: string[] }>(`/strategy/${projectId}/final-approve`, { reviewer }),
  approveStrategy: (strategyId: number, reviewer = "analyst") =>
    post<{ ok: boolean }>(`/strategy/${strategyId}/approve`, { reviewer }),

  editResearchQuestion: (strategyId: number, questionId: string, question: string, query: string) =>
    put<{ ok: boolean }>(`/strategy/${strategyId}/research-question`, { question_id: questionId, question, query }),

  addResearchQuestion: (strategyId: number, question: string, query: string) =>
    post<{ question_id: string }>(`/strategy/${strategyId}/research-question`, { question, query }),

  setResearchQuestionStatus: (strategyId: number, questionId: string, status: "draft" | "approved") =>
    post<{ ok: boolean }>(`/strategy/${strategyId}/research-question/${questionId}/status`, { status }),

  taggingState: (projectId: number) =>
    get<{ running: boolean; phase: string | null; done: number; total: number; minutes_left: number | null;
          counts: { total: number; content: Record<string, number>; tags: Record<string, number>;
                    matched?: number; irrelevant?: number; unmatched?: number };
          approval?: { at: number; by: string | null } | null }>(
      `/articles/${projectId}/tagging`),

  // Data set (uploaded articles, tagging, per-RQ decisions)
  uploadArticles: (projectId: number, files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return fetch(`${API_BASE}/articles/${projectId}/upload`, { method: "POST", credentials: CREDENTIALS, body: form })
      .then((r) => json<UploadResult>(r));
  },

  startTagging: (projectId: number) => post<{ job_id: string }>(`/articles/${projectId}/tag`),
  /** Keep an article the exclusion list blocked; the comment is required (the organization learns from it). */
  keepArticle: (projectId: number, articleId: number, comment: string) =>
    post<{ matched: number; irrelevant: number; blocked: number }>(`/articles/${projectId}/${articleId}/keep`, { comment }),
  /** Free: each approved question's Boolean query maps the articles; the rest go to Irrelevant (never tagged). */
  /** The analyst's sign-off on the tagged data set; the server starts the deck run from it. */
  approveDataset: (projectId: number) =>
    post<{ approved: boolean; run_id: number | null; note?: string }>(`/articles/${projectId}/approve`, {}),
  matchRqs: (projectId: number) =>
    post<{ per_rq: Record<string, number>; matched: number; irrelevant: number; total: number; copies: number }>(`/articles/${projectId}/match`, {}),

  listArticles: (projectId: number, f: ArticleFilters, offset = 0, limit = 100) =>
    get<ArticlePage>(`/articles/${projectId}?${articleQuery(f, { offset, limit })}`),

  articleFacets: (projectId: number, channel: Channel) =>
    get<ArticleFacets>(`/articles/${projectId}/facets?channel=${channel}`),

  articlesByIds: (projectId: number, ids: number[]) =>
    get<{ rows: ArticleRow[] }>(`/articles/${projectId}/by-ids?${ids.slice(0, 200).map((i) => `ids=${i}`).join("&")}`).then((r) => r.rows),

  articleIds: (projectId: number, f: ArticleFilters) =>
    get<{ ids: number[] }>(`/articles/${projectId}/ids?${articleQuery(f)}`).then((r) => r.ids),

  decideArticles: (projectId: number, articleIds: number[], rqId: string | null, status: RqStatus, reason?: string) =>
    post<{ changed: number; undo_token: string }>(`/articles/${projectId}/decisions`,
      { article_ids: articleIds, rq_id: rqId, status, reason: reason || undefined }),

  undoDecision: (projectId: number, undoToken: string) =>
    post<{ restored: number }>(`/articles/${projectId}/decisions/undo`, { undo_token: undoToken }),

  editArticle: (projectId: number, articleId: number, edit: { sentiment?: string; themes?: string[]; brands?: string[] }) =>
    patch<{ ok: boolean; approved_rqs: string[] }>(`/articles/${projectId}/${articleId}`, edit),

  // Data set uploaded files: list, what removing one takes with it, remove (its articles and their RQ rows)
  listDatasetFiles: (projectId: number) => get<UploadedFile[]>(`/articles/${projectId}/files`),
  datasetFileImpact: (projectId: number, fileId: number) =>
    get<{ articles: number; approved: number }>(`/articles/${projectId}/files/${fileId}/impact`),
  deleteDatasetFile: (projectId: number, fileId: number) =>
    del<{ ok: boolean; articles_removed: number; approved_removed: number }>(`/articles/${projectId}/files/${fileId}`),

  // Data set research-question panel: query preview / save (free re-match), re-tag estimate, re-tag, delete
  datasetRqs: (projectId: number) => get<RqSummary[]>(`/articles/${projectId}/rqs`),

  previewRqQuery: (projectId: number, rqId: string, query: string) =>
    post<RqPreview>(`/articles/${projectId}/rqs/${encodeURIComponent(rqId)}/preview`, { query }),

  saveRqQuery: (projectId: number, rqId: string, query: string) =>
    post<{ counts: RqCounts }>(`/articles/${projectId}/rqs/${encodeURIComponent(rqId)}/save`, { query }),

  estimateRqRetag: (projectId: number, rqId: string) =>
    get<RqEstimate>(`/articles/${projectId}/rqs/${encodeURIComponent(rqId)}/estimate`),

  retagRq: (projectId: number, rqId: string) =>
    post<{ job_id: string }>(`/articles/${projectId}/rqs/${encodeURIComponent(rqId)}/retag`),

  deleteDatasetRq: (projectId: number, rqId: string) =>
    del<{ removed_approved: number }>(`/articles/${projectId}/rqs/${encodeURIComponent(rqId)}`),

  deleteResearchQuestion: (strategyId: number, questionId: string) =>
    del<{ ok: boolean }>(`/strategy/${strategyId}/research-question/${questionId}`),

  // Brief file upload
  parseBriefFile: async (file: File): Promise<{ text: string; file_name: string; ocr_used?: boolean; extraction_method?: "nvidia" | "native"; model?: string | null; pages?: number | null }> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/brief/parse-file`, { method: "POST", credentials: CREDENTIALS, body: form });
    return json<{ text: string; file_name: string }>(res);
  },

  // Brandfetch logo lookup
  // The logo is served by this API (Brandfetch refuses hotlinked images), so its path takes the API's origin
  /** The project's own logo: its client brand's logo, else a photo of its brief's main theme (no client brand). */
  getProjectLogo: (projectId: number) =>
    get<{ logo_url: string | null; is_light?: boolean; source: "brand" | "theme" | "none"; brand: string | null; theme: string | null }>(
      `/projects/${projectId}/logo`,
    ).then((res) => ({ ...res, logo_url: res.logo_url?.startsWith("/api/") ? `${API_ORIGIN}${res.logo_url}` : res.logo_url })),

  getBrandLogo: (brandName: string) =>
    get<{ brand_name: string; logo_url: string | null; is_light?: boolean }>(
      `/brandfetch/logo?brand_name=${encodeURIComponent(brandName)}`,
    ).then((res) => ({ ...res, logo_url: res.logo_url?.startsWith("/api/") ? `${API_ORIGIN}${res.logo_url}` : res.logo_url })),

  // Pexels dynamic background image lookup
  getPexelsImage: (query: string) =>
    get<PexelsImageResponse>(`/pexels/image?query=${encodeURIComponent(query)}`),

  getSectionVideo: (query: string, brandName: string) =>
    get<SectionVideoResponse>(`/video/section?query=${encodeURIComponent(query)}&brand_name=${encodeURIComponent(brandName)}`),

  getAllDatasets: (projectId: number) =>
    get<any[]>(`/dataset/${projectId}?scope=all`),

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

  validatePlanPrereqs: (projectId: number) =>
    post<{
      ready: boolean;
      prerequisites: Record<string, { status: string; message: string }>;
    }>("/plan/validate", { project_id: projectId }),

  // Jobs
  listJobs: (projectId: number, jobType?: string) =>
    get<JobStatus[]>(`/jobs/${projectId}${jobType ? `?job_type=${jobType}` : ""}`),

  getJob: (jobId: string) =>
    get<JobStatus>(`/job/${jobId}`),


  // Settings > Exclusions: websites/domains and keywords kept out of research, datasets, decks and reports
  listExclusions: () => get<ExclusionRecord[]>("/exclusions"),
  addExclusion: (kind: ExclusionKind, value: string) => post<ExclusionRecord>("/exclusions", { kind, value }),
  deleteExclusion: (id: number) => del<{ ok: boolean }>(`/exclusions/${id}`),
  /** Many at once: separated by commas, semicolons, spaces or new lines. */
  bulkExclusions: (kind: ExclusionKind, text: string) => post<ExclusionImportResult>("/exclusions/bulk", { kind, text }),
  /** An .xlsx, .csv, .txt or .json list. */
  importExclusions: (kind: ExclusionKind, file: File) => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    return fetch(`${API_BASE}/exclusions/import`, { method: "POST", credentials: CREDENTIALS, body: form })
      .then((r) => json<ExclusionImportResult>(r));
  },

  /** Whether the active org has a model (its own provider, or the platform model for InfoVision). */
  llmProviderStatus: () => get<{ ready: boolean; source: "org" | "platform" | "none"; model: string; name?: string;
    can_manage?: boolean }>("/llm-providers/status"),
  /** An organisation's own chat LLM providers (Settings → LLM Providers); the key is write-only. */
  listLlmProviders: (orgId?: number) => get<LlmProvidersResponse>(`/llm-providers${orgId ? `?org_id=${orgId}` : ""}`),
  createLlmProvider: (body: ProviderFields & { org_id?: number; api_key: string }) =>
    post<LlmProvider>("/llm-providers", body),
  updateLlmProvider: (id: number, body: ProviderFields & { api_key: string }) => put<LlmProvider>(`/llm-providers/${id}`, body),
  deleteLlmProvider: (id: number) => del<{ ok: boolean }>(`/llm-providers/${id}`),
  setDefaultLlmProvider: (id: number) => post<LlmProvider>(`/llm-providers/${id}/default`, {}),
  usePlatformLlm: (orgId?: number) => post<{ ok: boolean }>(`/llm-providers/use-platform${orgId ? `?org_id=${orgId}` : ""}`, {}),
  testLlmProvider: (id: number) => post<ProviderTestResult>(`/llm-providers/${id}/test`, {}),
  testLlmProviderDraft: (body: ProviderFields & { org_id?: number; provider_id?: number; api_key: string }) =>
    post<ProviderTestResult>("/llm-providers/test", body),

  listDataSources: () => get<DataSourceRecord[]>("/datasources"),

  setDataSourceKey: (source: string, apiKey: string) =>
    put<DataSourceRecord>(`/datasources/${source}`, { api_key: apiKey }),

  validateDataSource: (source: string) =>
    post<{ source: string; status: string; error: string | null }>(`/datasources/${source}/validate`),
  // Deliverable engine: one run streams stages and sections over /ws and produces the PPTX + Word brief.
  // The deck reads only article-RQ rows approved on the Data set page; 409 while tagging is still running.
  deliverableRun: (projectId: number) => post<{ run_id: number }>(`/deliverable/${projectId}/run`),
  deliverableRepair: (projectId: number, runId: number, scope: RepairScope) =>
    post<{ run_id: number; scope: RepairScope }>(`/deliverable/${projectId}/runs/${runId}/repair?scope=${scope}`, {}),
  deliverableLatest: (projectId: number) => get<DeliverablePayload>(`/deliverable/${projectId}/latest`),
  /** "Refresh latest 24h": starts the fetch (progress streams on /ws as latest24h_progress); latest = the stored result. */
  latest24hRefresh: (projectId: number) => post<{ refresh_id: number }>(`/deliverable/${projectId}/latest24h`, {}),
  latest24hLatest: (projectId: number) => get<{ refresh: Latest24hRefresh | null }>(`/deliverable/${projectId}/latest24h`),
  deliverableCoverage: (projectId: number) => get<DataCoverage>(`/deliverable/${projectId}/coverage`),
  agentState: (projectId: number) => get<AgentState>(`/agent/${projectId}`),
  agentStart: (projectId: number, inputFolder?: string) =>
    post<AgentState["autopilot"]>(`/agent/${projectId}/autopilot/start`, { input_folder: inputFolder || null }),
  agentStop: (projectId: number) => post<{ ok: boolean }>(`/agent/${projectId}/autopilot/stop`, {}),
  /** After Brief & Scope approval: research and strategy run and approve themselves up to Data Sources. */
  autorunStatus: (projectId: number) => get<Autorun>(`/agent/${projectId}/autorun`),
  autorunStart: (projectId: number) => post<Autorun>(`/agent/${projectId}/autorun`, {}),
  /** Stage gates: a stage opens only when every stage before it is done. */
  projectGates: (projectId: number) =>
    get<{ gates: Record<string, "done" | "running" | "open" | "locked">; progress_pct: number; current_stage: string;
          detail?: Record<string, { state: "done" | "running" | "open" | "locked"; pct: number; sub: string }> }>(`/projects/${projectId}/gates`),
  copilotSend: (projectId: number, message: string, confirm?: string) =>
    post<CopilotReply>(`/agent/${projectId}/copilot`, { message, confirm: confirm ?? null }),
  agentEvents: (projectId: number, limit = 10) => get<AgentEvent[]>(`/agent/${projectId}/events?limit=${limit}`),
  deliverableDownloadUrl: (projectId: number, runId: number, kind: "pptx" | "docx" | "html" | "pdf" | "studio_pptx" | "xlsx") =>
    `${API_BASE}/deliverable/${projectId}/runs/${runId}/download/${kind}`,
  deliverableDeckUrl: (projectId: number, runId: number, path: string) =>
    `${API_BASE}/deliverable/${projectId}/runs/${runId}/deck/${path}`,
  deliverableThumbUrl: (projectId: number, runId: number, n: number) =>
    `${API_BASE}/deliverable/${projectId}/runs/${runId}/thumbnail/${n}`,
  // Deck colours on a finished run: preview re-renders the HTML only (seconds); apply/reset re-export PPTX + PDF (~1 min)
  deckDesign: (projectId: number, runId: number) =>
    get<DeckDesign>(`/deliverable/${projectId}/runs/${runId}/design`),
  deckDesignPreview: (projectId: number, runId: number, change: DeckDesignChange) =>
    post<DeckDesignResult>(`/deliverable/${projectId}/runs/${runId}/design/preview`, change),
  deckDesignApply: (projectId: number, runId: number, change: DeckDesignChange) =>
    post<DeckDesignResult>(`/deliverable/${projectId}/runs/${runId}/design`, change),
  deckDesignReset: (projectId: number, runId: number) =>
    post<DeckDesignResult>(`/deliverable/${projectId}/runs/${runId}/design/reset`, {}),

  // LLM usage & cost (backend/domains/usage/router.py), scoped server-side to the caller's role
  usageSummary: (q: UsageQuery) => get<UsageSummary>(`/usage/summary${usageQuery(q)}`),
  usageCalls: (q: UsageQuery, offset = 0, limit = 50) =>
    get<UsageCallsPage>(`/usage/calls${usageQuery(q, { offset, limit })}`),
  usagePrices: () => get<UsagePrices>("/usage/prices"),
  setUsagePrice: (body: UsagePriceRequest) => put<{ ok: boolean }>("/usage/prices", body),
  setUsageSettings: (body: { deployment_type?: string; region?: string }) =>
    put<{ deployment_type: string; region: string }>("/usage/settings", body),
  projectUsageTotal: (projectId: number) =>
    get<{ cost_usd: number; total_tokens: number }>(`/usage/projects/${projectId}/total`),
};

/** "?date_from=…&model=…" with only the filters that are set. */
function usageQuery(q: UsageQuery, extra: Record<string, number> = {}): string {
  const p = new URLSearchParams();
  Object.entries({ ...q, ...extra }).forEach(([k, v]) => {
    if (v !== undefined && v !== null && (v !== "" || k === "sub_stage")) p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** Deck colours are 6 hex digits without '#'. */
export interface DeckDesignChange { primary?: string; accent?: string }
export interface DeckDesign { primary: string; accent: string; swatches: string[]; can_reset: boolean }
export interface DeckDesignResult { applied: string[]; rejected: Record<string, string>; html: string }

export interface DeliverableRun {
  id: number; project_id: number; status: "running" | "completed" | "failed"; stage: string | null;
  stages: Record<string, "running" | "done" | "failed">; pptx_path: string | null; docx_path: string | null;
  studio_pptx_path?: string | null; html_path?: string | null; pdf_path?: string | null;
  error: string | null;
  /** False on runs made before repairs were saved with the deck: those need one regenerate before Fix works. */
  repairable?: boolean;
}
export interface DeliverableCard { headline: string; text: string; citations: number[] }
/** What the Fix button repairs: the open deck checks, the brief's open asks, or both. */
export type RepairScope = "checks" | "brief" | "all";

export interface DeliverableSection {
  id: string; rq_id: string | null; module: string; title: string;
  chart?: import("../components/deliverable/ChartRenderer").ChartSpec | null;
  table?: { header: string[]; rows: string[][] } | null;
  facts?: string[]; notes?: string[]; skipped?: string | null;
  insights?: DeliverableCard[];
  answers?: { rq_id: string; question: string; value: string; answer: string }[];
  takeaways?: DeliverableCard[];
  data?: { files: number; unique_urls: number; stories: number; base_n: number; by_rq: Record<string, number> };
  report?: { ready: boolean; facts: unknown[]; layout: unknown[]; pngs: string[]; fixed: number };
  citations?: DeliverableCitation[];
  hero?: { url: string | null; credit: string };
  logos?: Record<string, string>;
  country?: string | null;
  brand?: string;
  lines?: DeliverableLogLine[];
  pct?: number; stage?: string; label?: string; started_at?: number;
  family?: string; family_reason?: string; design_system?: string; design_reason?: string;
  slides?: unknown[];
  checklist?: { ask: string; kind: string; status: "covered" | "partial" | "missing"; slides: number[]; note: string }[];
  scorecard?: { covered: number; partial: number; missing: number };
  /** The deck validator's checks: cover logo, brand vs competitors, each question's answer/chart/cited summary... */
  validation?: { check: string; status: "pass" | "warn" | "fail"; detail: string }[];
}
export interface DeliverableProgress { pct: number; stage: string; label: string; started_at: number; typical_seconds?: number | null }
export type AgentStep = { key: string; label: string; state: "done" | "ready" | "waiting" | "failed" | "todo"; detail: string };
export type Autorun = { status: "idle" | "running" | "done" | "blocked";
  step?: "research" | "brief" | "strategy" | "data-sources"; job_id?: string | null; error?: string | null };
export type AgentState ={ autopilot: { status: string; note: string; updated_at: number } | null;
  status: { project_id: number; name: string; steps: AgentStep[]; next: string | null } };
export type CopilotReply = { reply: string; actions: { tool: string; ok: boolean; error?: string }[];
  pending: { id: string; tool: string; args: Record<string, unknown>; summary: string } | null };
export type ProviderType = "openai_compatible" | "azure_openai" | "anthropic" | "gemini";
export type ProviderFields = { name: string; provider_type: ProviderType; base_url: string; model: string; api_version: string };
export type LlmProvider = ProviderFields & { id: number; org_id: number; key_hint: string; is_default: boolean;
  status: "untested" | "ok" | "failed"; last_error: string; last_tested_at: number | null; last_latency_ms: number | null;
  updated_at: number };
export type LlmOutage = { acting_provider_id: number | null; down_since: number; paused: number; last_error: string;
  failed_calls: number };
export type LlmProvidersResponse = { org_id: number; org_name: string; platform_model: string; platform_llm: boolean;
  providers: LlmProvider[]; outage: LlmOutage | null };
export type ProviderTestResult = { ok: boolean; latency_ms: number; reply: string; error: string };
export type AgentEvent = { id: number; actor: string; action: string; detail: Record<string, unknown> | null; at: number; run_id: number | null };
export interface DeliverableLogLine { ts: number; message: string }
export interface DeliverableCitation { n: number; outlet: string; title: string; url: string; date: string; domain: string }
// per question: articles approved for it on the Data set tab (shared = that count)
export interface DataCoverage { rqs: { rq_id: string; has_own_upload: boolean; shared: number | null }[] }
export interface DeliverablePayload { run: DeliverableRun | null; sections: DeliverableSection[] }

export interface Latest24hSourceCount { label: string; status: "fetching" | "done" | "failed"; found: number }
export interface Latest24hArticle {
  n: number; title: string; url: string; outlet: string; date: string; snippet: string; source: string;
  brands: string[]; copies: number; sources: string[];
}
export interface Latest24hRefresh {
  id: number; project_id: number; status: "running" | "completed" | "failed"; started_at: number;
  finished_at: number | null; counts: Record<string, Latest24hSourceCount>; fetched: number; kept: number;
  summary: { source: "llm" | "deterministic"; bullets: { text: string; citations: number[] }[] } | null;
  charts: Record<string, import("../components/deliverable/ChartRenderer").ChartSpec & { counts?: number[] }> | null;
  articles: Latest24hArticle[] | null; error: string | null;
}

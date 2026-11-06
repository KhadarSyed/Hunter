/** Shapes of /api/intel/usage/* (backend/domains/usage/router.py). */

export interface UsageTokens {
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface UsageKpis extends UsageTokens {
  cost_usd: number;
  calls: number;
  cache_hits: number;
  nvidia_credits: number;
  saved_by_cache_usd: number;
}

/** The trend's bucket follows the range: under 7 days hourly, to ~3 months daily, to 3 years monthly, then yearly. */
export type TrendGrain = "hour" | "day" | "month" | "year";
/** bucket is UTC text: 2026-11-07T04 (hour) / 2026-11-07 / 2026-11 / 2026 */
export interface UsageTrendRow { bucket: string; provider: string; model: string; cost_usd: number; total_tokens: number }

export interface UsageModelRow extends UsageTokens {
  provider: string;
  model: string;
  deployment_type: string | null;
  calls: number;
  cost_usd: number;
}

export interface UsageSubStageRow extends UsageTokens {
  sub_stage: string;   // "" = calls made outside any named phase ("(unattributed)")
  calls: number;
  cost_usd: number;
  avg_latency_ms: number | null;   // mean over non-cache-hit calls; null when every call was a cache hit
  models: { provider: string; model: string; total_tokens: number; cost_usd: number }[];
}

export interface UsageStageRow extends UsageTokens {
  stage: string;
  calls: number;
  cost_usd: number;
  sub_stages: UsageSubStageRow[];
}

export interface UsageProjectModel {
  provider: string; model: string; input_tokens: number; output_tokens: number; total_tokens: number; cost_usd: number;
}

export interface UsageProjectRow extends UsageTokens {
  project_id: number | null;
  project_name: string | null;
  owner_name: string | null;
  cost_usd: number;
  calls: number;
  share_pct: number;
  top_stage: string;
  models: UsageProjectModel[];
  stages: { stage: string; total_tokens: number; cost_usd: number }[];
}

export interface UsageSummary {
  kpis: UsageKpis;
  grain: TrendGrain;
  trend: UsageTrendRow[];
  by_model: UsageModelRow[];
  by_stage: UsageStageRow[];
  by_project: UsageProjectRow[];
}

export interface UsageCall extends UsageTokens {
  ts: number;
  project_id: number | null;
  project_name: string | null;
  stage: string;
  sub_stage: string;
  provider: string;
  model: string;
  kind: string;
  cost_usd: number;
  latency_ms: number | null;
  cache_hit: number;
  error: number;   // 1 when the call failed
  error_reason?: string;   // why it failed: HTTP status and message, timeout, rate limit, bad reply
}

export interface UsageCallsPage { rows: UsageCall[]; total: number }

export interface UsagePrice {
  provider: string; model: string; deployment_type: string;
  input_per_m: number; cached_per_m: number; output_per_m: number; effective_from: string; source: string;
}

export interface UsagePrices { prices: UsagePrice[]; deployment_type: string; region: string }

export interface UsagePriceRequest {
  provider: string; model: string; deployment_type: string;
  input_per_m: number; cached_per_m: number; output_per_m: number; effective_from: string;
}

/** Query filters shared by /summary and /calls; empty values are left out of the query string. */
export interface UsageQuery {
  date_from?: string;
  date_to?: string;
  org_id?: number | null;
  project_id?: number | null;
  stage?: string;
  model?: string;
  sub_stage?: string | null;   // /calls only; "" is sent (the unattributed calls), null is left out
}

/** One `llm_usage` socket message: the row just recorded. */
export interface UsageLiveRow extends UsageTokens {
  ts: number; org_id: number | null; project_id: number | null; user_id: number | null;
  stage: string; sub_stage: string; provider: string; model: string; kind: string;
  cost_usd: number; latency_ms: number; cache_hit: number; error: number; error_reason?: string; credits?: number;
}

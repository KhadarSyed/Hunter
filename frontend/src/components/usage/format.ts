/** Number, money and label formatting shared by the Usage & cost page. */

export const STAGE_LABELS: Record<string, string> = {
  brief_scope: "Brief & Scope",
  background_research: "Background research",
  search_strategy: "Search strategy",
  matching_label: "Matching label",
  dataset_tagging: "Data set tagging",
  deck_engine: "Deck engine",
  deck_studio: "Deck Studio",
  agent: "Agent",
  qc: "QC",
  other: "Other",
};

export const STAGE_ICONS: Record<string, string> = {
  brief_scope: "lucide:file-text",
  background_research: "lucide:globe",
  search_strategy: "lucide:search",
  matching_label: "lucide:tags",
  dataset_tagging: "lucide:database",
  deck_engine: "lucide:presentation",
  deck_studio: "lucide:palette",
  agent: "lucide:bot",
  qc: "lucide:badge-check",
  other: "lucide:circle-dashed",
};

export const stageLabel = (stage: string | null | undefined): string =>
  stage ? STAGE_LABELS[stage] ?? stage : "Other";

const SUB_STAGE_LABELS: Record<string, string> = { qc: "QC" };

/** A raw sub-stage name, title-cased only at its first letter ("article tags" -> "Article tags", "RQ1 tags" kept). */
export const subStageLabel = (sub: string): string =>
  !sub ? "(unattributed)" : SUB_STAGE_LABELS[sub] ?? sub.charAt(0).toUpperCase() + sub.slice(1);

export const PROVIDER_LABELS: Record<string, string> = { azure_openai: "Azure OpenAI", nvidia: "NVIDIA",
  openai_compatible: "OpenAI-compatible", anthropic: "Anthropic", gemini: "Google Gemini" };
export const providerLabel = (p: string): string => PROVIDER_LABELS[p] ?? p;

/** "$0.00" for zero, 4 decimals below one cent so a fraction of a cent never shows as $0.00, else 2 decimals. */
export function money(v: number | null | undefined): string {
  const n = Number(v) || 0;
  const digits = n !== 0 && Math.abs(n) < 0.01 ? 4 : 2;
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

/** Exact count with thousands separators. */
export const num = (v: number | null | undefined): string => (Number(v) || 0).toLocaleString("en-US");

/** Compact count for tiles (1.2M); always pair it with num() in a title. */
export const compact = (v: number | null | undefined): string =>
  (Number(v) || 0).toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 });

export const pct = (v: number): string => `${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}%`;

export type Channel = "traditional" | "social";
export type RqStatus = "pending" | "approved" | "irrelevant";
export type StatusFilter = "all" | "approved" | "review" | "irrelevant" | "no_match";

export interface BrandTag { brand: string; is_primary?: boolean; sentiment: string | null; confidence: number | null; summary?: string }

export interface ArticleTags {
  overall_sentiment?: string | null;
  overall_sentiment_confidence?: number | null;
  sentiment_summary?: string | null;
  themes?: { primary?: string | null; secondary?: string | null; tertiary?: string | null };
  entities?: Record<string, string[]>;
  category?: string | null;
  group?: string | null;
  signals?: string[];
  author_type?: string | null;
  brands?: BrandTag[];
}

export interface RqRow {
  status: RqStatus;
  matched: boolean;
  match_confidence: number | null;
  keywords: string[];
  tags: Record<string, string | string[]>;
  evidence: Record<string, string>;
  summary: string | null;
  reason: string | null;
  decided_by: string | null;
  decided_at: number | null;   // epoch seconds
  query_changed?: boolean;     // the RQ's query no longer matches this row; its decision was kept
}

export interface ArticleRow {
  id: number;
  url: string;
  channel: Channel;
  title: string | null;
  summary: string | null;
  content?: string | null;
  outlet: string | null;
  published: string | null;
  country: string | null;
  author_name: string | null;
  author_id: string | null;
  post_id: string | null;
  content_status: string;
  tag_status: string;
  sentiment: string | null;
  sentiment_confidence: number | null;
  tags: ArticleTags;
  syndicated: number[] | null;
  similar: number[] | null;
  theme_titles?: Record<string, string>;
  rq: Record<string, RqRow>;
  matched_rqs: string[];
  status: "Approved" | "Review" | "Irrelevant" | "No RQ match";
  /** set when the organization's exclusion list blocked it (Settings > Exclusions) */
  excluded_reason?: string | null;
  /** an analyst kept it relevant despite the exclusion list */
  keep_by?: string | null;
  keep_at?: number | null;
  keep_comment?: string | null;
}

export interface RqColumn {
  id: string;
  question: string;
  tag_columns: { key: string; type: string; allowed_values: string[]; review_column: string }[];
}

export interface ArticleFilters {
  channel: Channel;
  status: StatusFilter;
  rq: string;
  sentiment: string;
  theme: string;
  brand: string;
  content_status: string;
  q: string;
  /** matched (default): articles a question's Boolean query matched (or not matched yet); irrelevant: none did */
  pool?: "matched" | "irrelevant";
}

/** The filter dropdowns' values for one channel (GET /articles/{id}/facets). */
export interface ArticleFacets { themes: { label: string; title: string }[]; brands: string[]; content_statuses: string[] }

export interface ArticlePage { rows: ArticleRow[]; total: number; rqs: RqColumn[] }

/** blocked = rows from the organization's blocked websites, dropped before saving */
export interface UploadFileResult { file_name: string; rows_read: number; added: number; duplicates: number; blocked: number; error: string | null }
export interface UploadedFile { id: number; file_name: string; s3_key: string | null; rows_read: number | null; added: number | null;
  duplicates: number | null; error: string | null; uploaded_by: string | null; created_at: number }
export interface UploadResult { files: UploadFileResult[]; added: number; duplicates: number; blocked: number; traditional: number; social: number }

/** The research-question panel on the Data set page (GET /articles/{id}/rqs and the per-RQ routes). */
export interface TagSchemaField { name: string; type: string; definition?: string; values: string[] }
export interface RqCounts { matched: number; tagged: number; approved: number; needs_tagging: number; query_changed: number }
export interface RqSummary { rq_id: string; question: string; query: string; status: string; counts: RqCounts; schema: { fields: TagSchemaField[] } }
export interface RqArticleRef { id: number; title: string }
export interface RqPreview { valid: boolean; errors: string[]; current: number; edited: number; added: RqArticleRef[]; dropped: RqArticleRef[] }
export interface RqEstimate { articles: number; batches: number; input_tokens: number; output_tokens: number; cost_usd: number }

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
  decided_at: string | null;
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
}

export interface ArticlePage { rows: ArticleRow[]; total: number; rqs: RqColumn[]; theme_titles: Record<string, string> }

export interface UploadFileResult { file_name: string; rows_read: number; added: number; duplicates: number; error: string | null }
export interface UploadResult { files: UploadFileResult[]; added: number; duplicates: number; traditional: number; social: number }

export interface UploadedFile extends UploadFileResult { id: number; uploaded_by: string | null; created_at: number }

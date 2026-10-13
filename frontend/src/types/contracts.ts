// ─── Brand & Issue Intelligence ───────────────────────────────────────────

export interface BrandIntelligenceRecord {
  workspace_id: string;
  brand_id: string;
  official_name: string;
  parent_company: string;
  entity_type: "brand" | "product" | "service" | "organization";
  category: string;
  products: string[];
  markets: string[];
  official_sources: string[];
  social_handles: { platform: string; handle: string }[];
  aliases: string[];
  misspellings: string[];
  ambiguous_terms: { term: string; irrelevant_meanings: string[]; exclusion_recommendation: string }[];
  exclusions: string[];
  confidence: "high" | "medium" | "low";
  approval_status: "draft" | "approved" | "rejected";
}

export interface CategoryContext {
  definition: string;
  terminology: string[];
  consumer_needs: string[];
  cultural_context: string;
  seasonal_factors: string[];
  false_positive_sources: string[];
}

export interface EntityDisambiguation {
  correct_spelling: string;
  punctuation_variations: string[];
  common_misspellings: string[];
  product_names: string[];
  ambiguous_terms: { term: string; irrelevant_meanings: string[]; exclusion_recommendation: string }[];
  false_positive_risks: string[];
}

export interface SearchImplication {
  term: string;
  type: "must_include" | "precision" | "exclusion" | "emerging" | "audience_language" | "campaign_hashtag";
  rationale: string;
}

export interface NewsContextRecord {
  news_id: string;
  workspace_id: string;
  headline: string;
  publication: string;
  publication_date: string;
  url: string;
  source_tier: 1 | 2 | 3 | 4 | 5;
  summary: string;
  relevance: string;
  query_implications: string;
  suggested_terms: string[];
  suggested_exclusions: string[];
  within_approved_period: boolean;
  approval_status: "included" | "excluded" | "pending";
}

export interface SourceRecord {
  url: string;
  title: string;
  source_type: "official" | "news" | "industry" | "government" | "consumer" | "community";
  tier: 1 | 2 | 3 | 4 | 5;
  accessed_date: string;
}

export interface BrandIntelligenceOutput {
  brand_overview: BrandIntelligenceRecord;
  category_context: CategoryContext;
  entity_disambiguation: EntityDisambiguation;
  search_implications: SearchImplication[];
  news_context: NewsContextRecord[];
  sources: SourceRecord[];
  research_confidence: {
    overall: "high" | "medium" | "low";
    brand_clarity: "high" | "medium" | "low";
    category_clarity: "high" | "medium" | "low";
    disambiguation_clarity: "high" | "medium" | "low";
    news_coverage: "high" | "medium" | "low";
  };
  research_gaps: string[];
  metadata: {
    total_sources_reviewed: number;
    sources_retained: number;
    sources_rejected: number;
    tier_one_sources: number;
    date_coverage_start: string;
    date_coverage_end: string;
  };
}

// ─── Meltwater Search Strategy ────────────────────────────────────────────

export interface SearchTermRecord {
  term_id: string;
  workspace_id: string;
  term: string;
  term_type: "brand" | "product" | "audience" | "topic" | "behaviour" | "tension" | "resolution" | "geography" | "language" | "platform" | "exclusion";
  source: "brief" | "background-research" | "analyst" | "inferred";
  rationale: string;
  inclusion_status: "included" | "excluded" | "candidate";
  ambiguity_risk: "high" | "medium" | "low" | "none";
  false_positive_risk: "high" | "medium" | "low" | "none";
  related_research_questions: string[];
}

export interface QueryModule {
  module_name: string;
  module_type: "brand" | "product" | "audience" | "topic" | "behaviour" | "tension" | "resolution" | "geography" | "language" | "platform" | "exclusion";
  terms: string[];
  boolean_fragment: string;
}

export interface QueryVersion {
  boolean_string: string;
  description: string;
  recall_level: "broad" | "balanced" | "precise";
  precision_level: "low" | "medium" | "high";
}

export interface MeltwaterQueryRecord {
  query_id: string;
  workspace_id: string;
  version: number;
  query_name: string;
  query_type: "master" | "research-question" | "audience-segment" | "topic";
  boolean_string: string;
  query_modules: QueryModule[];
  research_questions: string[];
  recommended_filters: FilterRecommendations;
  exclusions: { term: string; reason: string }[];
  recall_level: "broad" | "balanced" | "precise";
  precision_level: "low" | "medium" | "high";
  quality_score: QueryQualityScore;
  warnings: string[];
  approval_status: "draft" | "review" | "approved" | "rejected";
  created_at: string;
  approved_at: string | null;
}

export interface FilterRecommendations {
  geography: string;
  language: string;
  date_range_start: string;
  date_range_end: string;
  source_types: string[];
  social_platforms: string[];
  editorial_handling: string;
  owned_content_handling: string;
  retweet_handling: string;
  engagement_threshold: string;
  duplicate_handling: string;
}

export interface QueryQualityScore {
  overall: number;
  entity_accuracy: number;
  scope_alignment: number;
  recall: number;
  precision: number;
  ambiguity_control: number;
  audience_relevance: number;
  topic_coverage: number;
  false_positive_protection: number;
  rq_coverage: number;
  blocking_issues: string[];
  warnings: string[];
  recommended_refinements: string[];
}

export interface ResearchQuestionQuery {
  question_id: string;
  question_text: string;
  boolean_string: string;
  query_type: "standalone" | "additive" | "filter";
  coverage_notes: string;
}

export interface QueryEvaluationRecord {
  evaluation_id: string;
  query_id: string;
  sample_dataset_id: string;
  total_records: number;
  relevant_records: number;
  irrelevant_records: number;
  relevance_rate: number;
  false_positive_rate: number;
  missed_terms: string[];
  noisy_terms: string[];
  recommended_additions: string[];
  recommended_exclusions: string[];
  recommended_revisions: string[];
  approval_status: "pending" | "approved" | "rejected";
}

export interface MeltwaterStrategyOutput {
  strategy_summary: {
    objective: string;
    approach: "brand-led" | "audience-led" | "topic-led" | "issue-led" | "hybrid";
    strengths: string[];
    blind_spots: string[];
    false_positive_risks: string[];
    validation_steps: string[];
  };
  query_modules: QueryModule[];
  core_query: {
    broad: QueryVersion;
    balanced: QueryVersion;
    precise: QueryVersion;
  };
  research_question_queries: ResearchQuestionQuery[];
  exclusion_logic: {
    entity_exclusions: { term: string; reason: string }[];
    spam_exclusions: string[];
    content_type_exclusions: string[];
    geography_exclusions: string[];
    general_exclusions: string[];
    combined_not_string: string;
  };
  filter_recommendations: FilterRecommendations;
  term_rationale: {
    term: string;
    reason_included: string;
    expected_capture: string;
    risk_introduced: string;
    source: "brief" | "background-research" | "analyst" | "inferred";
  }[];
  quality_score: QueryQualityScore;
  versions: {
    version_id: number;
    created_at: string;
    change_summary: string;
    approval_status: "draft" | "review" | "approved" | "rejected";
  }[];
}

// ─── Research Plan ─────────────────────────────────────────────────────────

export interface ExecutionUnit {
  id: string;
  title: string;
  description: string;
  objective_id: string;
  priority: "high" | "medium" | "low";
  status: "pending" | "in_progress" | "completed";
  estimated_complexity: "high" | "medium" | "low";
  estimated_runtime: string;
  required_datasets: string[];
  required_fields: string[];
  filters_required: string[];
  evidence_target: string;
  recommended_method: string;
  audience_segmentation: string | null;
  expected_output: string;
  confidence: "high" | "medium" | "low";
  dependencies: string[];
  platforms: string[];
  search_concepts: string[];
}

export interface PlanObjective {
  objective_id: string;
  business_question_ids: string[];
  objective: string;
  priority: "high" | "medium" | "low";
  reason?: string;
  platforms: { name: string; justification: string }[];
  search_concepts: string[];
  evidence: {
    mandatory: string[];
    optional: string[];
  };
  inclusion_rules?: string[];
  exclusion_rules?: string[];
  methods: string[];
  expected_output: string;
  deliverable_mapping?: {
    supports: string;
    evidence_type: string;
    recommended_visual: string;
  };
  dependencies: string[];
  confidence_target: "high" | "medium" | "low";
  estimated_complexity: "high" | "medium" | "low";
}

export interface PlanValidation {
  warnings: {
    unit_id?: string;
    type: string;
    message: string;
    fields?: string[];
  }[];
  blockers: { type: string; message: string }[];
  status: "clean" | "warnings" | "blocked";
  total_execution_units: number;
  total_objectives: number;
  question_coverage: string;
}

export interface AnalysisMethodSummary {
  method: string;
  execution_units: string[];
  description: string;
  output_type: string;
}

export interface EvidenceRequirements {
  mandatory: string[];
  optional: string[];
  minimum_sample_size: number;
  platform_coverage: string[];
  dataset_records_available: number;
  dataset_relevant_records: number;
}

export interface ResearchPlanData {
  plan_summary: string;
  project_overview?: {
    project_name: string;
    brand: string;
    category: string;
    objective: string;
    research_objective: string;
    scope: {
      platforms: string[];
      countries: string[];
      time_period: string;
    };
    dataset_summary: {
      total_records: number;
      relevant_records: number;
      platforms: string[];
      fields_available: string[];
    };
  };
  research_objectives: PlanObjective[];
  execution_units: ExecutionUnit[];
  evidence_requirements: EvidenceRequirements;
  analysis_methods: AnalysisMethodSummary[];
  expected_deliverables: {
    deliverable: string;
    execution_units: string[];
    format: string;
  }[];
  validation: PlanValidation;
  _meta?: {
    agent: string;
    version: string;
    source: "llm" | "deterministic";
    attempts: number;
    elapsed_seconds: number;
    note?: string;
  };
}

export interface ResearchPlanRecord {
  id: number;
  project_id: number;
  version: number;
  status: string;
  plan_json: ResearchPlanData;
  source: "llm" | "deterministic";
  approval_status: "pending" | "approved" | "rejected";
  approved_by: string | null;
  approved_at: number | null;
  notes: string | null;
  created_at: number;
}

// ─── Research Execution ───────────────────────────────────────────────────

export interface ExecutionRunStatus {
  run_id: number;
  project_id: number;
  plan_id: number;
  status: "pending" | "running" | "paused" | "completed" | "completed_with_errors" | "failed" | "cancelled";
  total_units: number;
  completed_units: number;
  failed_units: number;
  skipped_units: number;
  total_evidence: number;
  elapsed_seconds: number | null;
  started_at: number | null;
  finished_at: number | null;
  units: ExecutionUnitStatus[];
  logs: ExecutionLogEntry[];
}

export interface ExecutionUnitStatus {
  id: number;
  unit_id: string;
  objective_id: string;
  method: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped" | "cancelled";
  progress_pct: number;
  records_processed: number;
  evidence_count: number;
  error: string | null;
}

export interface ExecutionLogEntry {
  level: "info" | "warn" | "error";
  message: string;
  unit_id: string | null;
  created_at: number;
}

export interface EvidenceRecord {
  id: number;
  run_id: number;
  unit_id: string;
  objective_id: string;
  evidence_type: string;
  method: string;
  platform: string | null;
  source: string | null;
  date: string | null;
  text_excerpt: string;
  metrics: Record<string, unknown> | null;
  confidence: "high" | "medium" | "low";
  rationale: string;
  dataset: string | null;
  created_at: number;
}

export interface ExecutionStartResult {
  job_id: string;
  project_id: number;
}

// ─── Evidence Library ─────────────────────────────────────────────────────

export interface LibraryItem {
  id: number;
  project_id: number;
  evidence_id: number;
  review_status: "unreviewed" | "accepted" | "rejected" | "needs_review" | "superseded";
  quality_score: number | null;
  quality_components: Record<string, number> | null;
  relevance_score: number | null;
  is_representative: boolean;
  is_high_value: boolean;
  canonical_id: number | null;
  duplicate_group: string | null;
  objective_id: string;
  unit_id: string;
  reviewed_by: string | null;
  reviewed_at: number | null;
  created_at: number;
  updated_at: number;
  text_excerpt: string;
  source: string | null;
  platform: string | null;
  date: string | null;
  method: string;
  confidence: "high" | "medium" | "low";
  rationale: string | null;
  evidence_type: string;
  metrics: Record<string, unknown> | null;
  run_id: number;
  dataset: string | null;
}

export interface LibraryAnnotation {
  id: number;
  library_item_id: number;
  author: string;
  note: string;
  created_at: number;
}

export interface LibraryAuditEntry {
  id: number;
  library_item_id: number;
  action: string;
  field: string | null;
  old_value: string | null;
  new_value: string | null;
  actor: string;
  created_at: number;
}

export interface LibrarySummaryMetrics {
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
}

export interface ObjectiveCoverage {
  objective_id: string;
  objective: string;
  total_evidence: number;
  accepted_evidence: number;
  rejected_evidence: number;
  unreviewed_evidence: number;
  coverage_status: "sufficient" | "partial" | "insufficient";
  confidence_distribution: Record<string, number>;
  platform_gaps: string[];
}

export interface CoverageReport {
  objectives: ObjectiveCoverage[];
  summary: {
    total_objectives: number;
    covered: number;
    partial: number;
    insufficient: number;
    blocking_gaps: number;
  };
}

export interface DuplicateGroup {
  group: string;
  count: number;
  canonical_id: number | null;
}

export interface EvidenceDetail {
  item: LibraryItem;
  annotations: LibraryAnnotation[];
  audit: LibraryAuditEntry[];
  duplicate_members: LibraryItem[];
}

// ─── Insights ────────────────────────────────────────────────────────────

export interface Insight {
  id: number;
  project_id: number;
  objective_id: string;
  insight_type: string;
  title: string;
  executive_summary: string | null;
  observation: string | null;
  interpretation: string | null;
  business_impact: string | null;
  confidence_score: number;
  confidence_rationale: string | null;
  evidence_count: number;
  platforms_represented: string[];
  date_coverage: string | null;
  contradictory_evidence: string | null;
  limitations: string | null;
  recommended_visualisation: string | null;
  analyst_notes: string | null;
  status: "draft" | "needs_review" | "approved" | "rejected";
  reviewed_by: string | null;
  reviewed_at: number | null;
  generation_id: string | null;
  created_at: number;
  updated_at: number;
}

export interface InsightEvidence {
  mapping_id: number;
  insight_id: number;
  library_item_id: number;
  role: string;
  text_excerpt: string | null;
  source: string | null;
  platform: string | null;
  confidence: string | null;
  quality_score: number | null;
}

export interface InsightDetail {
  insight: Insight;
  evidence: InsightEvidence[];
  contradictory_evidence: InsightEvidence[];
  audit_history: { id: number; action: string; field: string | null; old_value: string | null; new_value: string | null; actor: string; created_at: number }[];
}

export interface InsightsSummary {
  total_insights: number;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
  avg_confidence: number;
  total_evidence_mapped: number;
  objectives_covered: number;
}

export interface InsightValidation {
  valid: boolean;
  issues?: string[];
  warnings?: string[];
}

// ─── Storyline ──────────────────────────────────────────────────────────

export interface StoryNode {
  id: number;
  storyline_id: number;
  section_type: string;
  title: string;
  purpose: string | null;
  narrative_summary: string | null;
  suggested_visual: string;
  priority: string;
  estimated_duration_minutes: number;
  confidence_score: number;
  transition_text: string | null;
  is_key_message: boolean;
  is_locked: boolean;
  order_position: number;
  status: string;
  reviewed_by: string | null;
  reviewed_at: number | null;
  created_at: number;
  updated_at: number;
}

export interface StoryNodeEnriched extends StoryNode {
  insights: Array<{
    mapping_id: number;
    node_id: number;
    insight_id: number;
    role: string;
    insight_title: string;
    insight_summary: string | null;
    insight_confidence: number;
    insight_status: string;
  }>;
  insight_count: number;
}

export interface Storyline {
  id: number;
  project_id: number;
  narrative_pattern: string;
  title: string;
  executive_summary: string | null;
  total_duration_minutes: number;
  node_count: number;
  status: string;
  generated_by: string;
  approved_by: string | null;
  approved_at: number | null;
  generation_id: string | null;
  created_at: number;
  updated_at: number;
}

export interface StorylineDetail {
  storyline: Storyline;
  nodes: StoryNodeEnriched[];
  audit_history: Array<{
    id: number;
    storyline_id: number;
    node_id: number | null;
    action: string;
    field: string | null;
    old_value: string | null;
    new_value: string | null;
    actor: string;
    created_at: number;
  }>;
}

export interface StorylineSummary {
  storyline_count: number;
  latest_pattern: string | null;
  latest_status: string | null;
  total_nodes: number;
  total_duration_minutes: number;
  node_statuses: Record<string, number>;
  latest_storyline_id: number | null;
}

export interface StorylineValidation {
  valid: boolean;
  issues?: string[];
  warnings: string[];
}

// ─── Slide Intelligence ──────────────────────────────────────────────────

export interface SIPresentation {
  id: number;
  filename: string;
  file_path: string;
  file_size: number;
  slide_count: number;
  processed_count: number;
  status: string;
  error?: string;
  started_at?: number;
  completed_at?: number;
  created_at: number;
}

export interface SISlide {
  id: number;
  presentation_id: number;
  slide_number: number;
  all_text?: string;
  title_text?: string;
  body_text?: string;
  footer_text?: string;
  slide_purpose?: string;
  layout_type?: string;
  visual_type?: string;
  narrative_role?: string;
  report_type?: string;
  industry?: string;
  client?: string;
  brand?: string;
  data_density?: string;
  executive_suitability?: string;
  visual_complexity?: string;
  classification_confidence?: number;
  shape_count: number;
  chart_count: number;
  table_count: number;
  image_count: number;
  has_chart: boolean;
  has_table: boolean;
  has_image: boolean;
  is_excluded: boolean;
  is_template_approved: boolean;
  status: string;
}

export interface SITemplateFamily {
  id: number;
  family_name: string;
  typical_layout?: string;
  typical_visual?: string;
  typical_purpose?: string;
  required_inputs?: string[];
  recommended_usage?: string;
  member_count: number;
  is_approved: boolean;
}

export interface SIDashboard {
  presentation_count: number;
  total_slides: number;
  processed_slides: number;
  excluded_slides: number;
  template_families: number;
  detected_projects: number;
  duplicate_count: number;
  purpose_distribution: Record<string, number>;
  layout_distribution: Record<string, number>;
  client_distribution: Record<string, number>;
}

export interface SIDetectedProject {
  id: number;
  presentation_id: number;
  project_name?: string;
  client_name?: string;
  brand_name?: string;
  analyst_name?: string;
  start_slide: number;
  end_slide: number;
  slide_count: number;
  confidence: number;
}

export interface SIStorylineMatch {
  id: number;
  storyline_id: number;
  node_id: number;
  slide_id: number;
  similarity_score: number;
  match_reason?: string;
  recommended_elements?: string[];
  elements_not_to_reuse?: string[];
  recommended_layout?: string;
  recommended_visual?: string;
  confidence: number;
  slide_number?: number;
  title_text?: string;
  slide_purpose?: string;
  layout_type?: string;
  client?: string;
}

export interface SIRecommendation {
  node_id: number;
  section_type: string;
  best_layout: string;
  best_visual: string;
  best_chart?: string;
  best_content_hierarchy: string[];
  best_callout_style: string;
  best_evidence_placement: string;
  best_title_style: string;
  historical_slides: any[];
  alternative_layouts: string[];
}

// ─── Presentation Composer ────────────────────────────────────────────────

export interface PCPresentation {
  id: number;
  project_id: number;
  storyline_id: number;
  title: string;
  executive_summary?: string;
  narrative_pattern?: string;
  total_slides: number;
  estimated_duration_minutes: number;
  status: string;
  generated_by?: string;
  approved_by?: string;
  approved_at?: number;
  generation_id?: string;
  created_at: number;
  updated_at: number;
}

export interface PCContentBlock {
  type: string;
  content: string;
}

export interface PCConfidence {
  evidence_coverage: number;
  storyline_coverage: number;
  historical_layout_match: number;
  visual_suitability: number;
  overall: number;
  low_confidence_reasons?: string[];
}

export interface PCHistoricalRef {
  slide_id: number;
  similarity: number;
  reason: string;
}

export interface PCSlide {
  id: number;
  presentation_id: number;
  slide_number: number;
  slide_purpose: string;
  node_id?: number;
  title: string;
  subtitle?: string;
  narrative?: string;
  business_objective?: string;
  key_message?: string;
  speaker_notes?: string;
  recommended_visual?: string;
  recommended_chart?: string;
  layout_recommendation?: string;
  layout_rationale?: string;
  alt_layout_1?: string;
  alt_layout_1_rationale?: string;
  alt_layout_2?: string;
  alt_layout_2_rationale?: string;
  template_family_id?: number;
  content_blocks_json: PCContentBlock[];
  evidence_ids_json: number[];
  insight_ids_json: number[];
  historical_refs_json: PCHistoricalRef[];
  confidence_json: PCConfidence;
  overall_confidence: number;
  transition_to_next?: string;
  status: string;
  is_locked: number;
  reviewed_by?: string;
  reviewed_at?: number;
  created_at: number;
  updated_at: number;
}

export interface PCPresentationDetail {
  presentation: PCPresentation;
  slides: PCSlide[];
  audit_history: any[];
  total_duration_minutes: number;
  flow_analysis: {
    stages_present: string[];
    stages_missing: string[];
    flow_complete: boolean;
    total_slides: number;
  };
}

export interface PCPresentationSummary {
  presentation_count: number;
  latest_status?: string;
  total_slides: number;
  total_duration_minutes: number;
  slide_statuses: Record<string, number>;
  latest_presentation_id?: number;
  latest_storyline_id?: number;
}

export interface PCValidation {
  valid: boolean;
  issues?: string[];
  warnings?: string[];
}

// ─── PowerPoint Renderer ─────────────────────────────────────────────

export interface RenderJob {
  id: string;
  presentation_id: number;
  job_type: string;
  status: string;
  progress_pct: number;
  progress_message: string;
  slide_ids_json: number[];
  theme_id: string;
  output_path?: string;
  output_size_bytes?: number;
  warnings_json: string[];
  error?: string;
  started_at?: number;
  finished_at?: number;
  created_at: number;
}

export interface RenderedPresentation {
  id: number;
  job_id: string;
  presentation_id: number;
  version: number;
  output_path: string;
  output_size_bytes: number;
  slide_count: number;
  theme_id: string;
  render_duration_ms: number;
  metadata_json: Record<string, any>;
  created_at: number;
}

export interface RenderTheme {
  id: string;
  name: string;
  description?: string;
  primary_color: string;
  secondary_color: string;
  accent_color: string;
  background_color: string;
  text_color: string;
  font_heading: string;
  font_body: string;
  font_size_title: number;
  font_size_body: number;
  font_size_caption: number;
  logo_position: string;
  footer_style: string;
  color_palette_json: string[];
  is_default: number;
  is_active: number;
  created_at: number;
  updated_at: number;
}

export interface RenderResult {
  job_id: string;
  status: string;
  output_path?: string;
  file_size_bytes?: number;
  slide_count?: number;
  render_duration_ms?: number;
  warnings?: string[];
  version?: number;
  rendered_presentation_id?: number;
  error?: string;
}

export interface RenderSummary {
  total_renders: number;
  total_jobs: number;
  latest_job?: RenderJob;
  latest_render?: RenderedPresentation;
  has_download: boolean;
  history_count: number;
}

export interface RenderMetric {
  id: number;
  job_id: string;
  slide_id: number;
  slide_number: number;
  render_type: string;
  duration_ms: number;
  warnings_json: string[];
  created_at: number;
}

export interface RenderHistory {
  id: number;
  presentation_id: number;
  job_id: string;
  action: string;
  actor: string;
  details_json: Record<string, any>;
  created_at: number;
}

export interface RenderValidation {
  valid: boolean;
  issues: string[];
  warnings: string[];
}

// ─── Pipeline Orchestrator ────────────────────────────────────────────

export interface PipelineRun {
  id: string;
  project_id: number;
  status: string;
  execution_mode: string;
  current_stage: string | null;
  start_stage: string | null;
  completed_stages_json: string[];
  remaining_stages_json: string[];
  skipped_stages_json: string[];
  progress_pct: number;
  estimated_remaining_ms: number;
  user: string;
  error: string | null;
  started_at: number | null;
  completed_at: number | null;
  created_at: number;
}

export interface PipelineStage {
  id: number;
  run_id: string;
  stage_id: string;
  stage_name: string;
  status: string;
  version: number;
  input_hash: string | null;
  output_hash: string | null;
  dependencies_json: string[];
  execution_time_ms: number;
  started_at: number | null;
  completed_at: number | null;
  logs_json: string[];
  warnings_json: string[];
  errors_json: string[];
  cache_status: string;
  result_json: Record<string, any>;
  created_at: number;
}

export interface PipelineRunDetail extends PipelineRun {
  stages: PipelineStage[];
}

export interface PipelineStageStatus {
  stage_id: string;
  name: string;
  order: number;
  status: string;
  exists: boolean;
  id?: number;
  count?: number;
  approved?: number;
}

export interface PipelineProjectStatus {
  project_id: number;
  stage_statuses: Record<string, PipelineStageStatus>;
  latest_run: PipelineRun | null;
  recent_runs: PipelineRun[];
  performance: PipelinePerformance;
  dependency_graph: Record<string, PipelineDependencyNode>;
}

export interface PipelinePerformance {
  total_runs: number;
  completed_runs: number;
  failed_runs: number;
  avg_duration_ms: number;
  cache_entries: number;
  cache_hit_ratio: number;
  stage_averages: Record<string, { avg_ms: number; runs: number }>;
  cache_breakdown: Record<string, number>;
}

export interface PipelineDependencyNode {
  name: string;
  order: number;
  dependencies: string[];
  downstream: string[];
  requires_approval: boolean;
}

export interface PipelineLog {
  id: number;
  run_id: string;
  stage_id: string | null;
  level: string;
  message: string;
  details_json: Record<string, any>;
  created_at: number;
}

export interface PipelineTimelineEntry {
  stage_id: string;
  stage_name: string;
  status: string;
  started_at: number | null;
  completed_at: number | null;
  execution_time_ms: number;
  cache_status: string;
}

export interface PipelineCacheMetrics {
  total_entries: number;
  entries: Array<{
    stage_id: string;
    input_hash: string;
    created_at: number;
  }>;
  stages_cached: string[];
}

// ── Word Report Renderer ─────────────────────────────────────────────

export interface WordRenderResult {
  job_id: string;
  status: string;
  output_path?: string;
  file_size_bytes?: number;
  section_count?: number;
  word_count?: number;
  render_duration_ms?: number;
  warnings?: string[];
  version?: number;
  document_id?: string;
  error?: string;
  section?: string;
}

export interface WordRenderJob {
  id: string;
  presentation_id: number;
  job_type: string;
  status: string;
  progress_pct: number;
  progress_message: string | null;
  sections_json: string[];
  theme_id: string;
  output_path: string | null;
  output_size_bytes: number | null;
  warnings_json: string[];
  error: string | null;
  started_at: number | null;
  finished_at: number | null;
  created_at: number;
}

export interface WordDocument {
  id: string;
  job_id: string;
  presentation_id: number;
  version: number;
  output_path: string;
  output_size_bytes: number;
  section_count: number;
  page_count: number | null;
  word_count: number;
  theme_id: string;
  render_duration_ms: number;
  metadata_json: Record<string, any>;
  created_at: number;
}

export interface WordRenderMetric {
  id: string;
  job_id: string;
  section_name: string;
  section_number: number;
  render_type: string | null;
  duration_ms: number;
  element_count: number;
  warnings_json: string[];
  created_at: number;
}

export interface WordRenderHistory {
  id: string;
  presentation_id: number;
  job_id: string;
  action: string;
  actor: string;
  details_json: Record<string, any>;
  created_at: number;
}

export interface WordRenderSummary {
  total_renders: number;
  total_jobs: number;
  latest_job: WordRenderJob | null;
  latest_document: WordDocument | null;
  has_download: boolean;
  history_count: number;
}

export interface WordValidation {
  valid: boolean;
  issues: string[];
  warnings: string[];
}

// ─── Publishing & Quality Gateway ─────────────────────────────────────────

export interface PubIssue {
  description: string;
  deliverable: string;
  page_slide: number;
  severity: "critical" | "major" | "minor" | "information";
  suggested_resolution: string;
  confidence: number;
}

export interface PubValidationResult {
  validation_id: number;
  readiness_score: number;
  readiness_class: "draft" | "internal_review" | "client_ready" | "blocked";
  scores: Record<string, number>;
  issues: PubIssue[];
  warnings: string[];
  critical_count: number;
  total_issues: number;
  duration_ms: number;
}

export interface PubValidation {
  id: number;
  project_id: number;
  presentation_id: number;
  status: string;
  readiness_score: number;
  readiness_class: string;
  scores_json: Record<string, number>;
  issues_json: PubIssue[];
  warnings_json: string[];
  pptx_job_id: string | null;
  word_job_id: string | null;
  validated_by: string;
  started_at: number | null;
  finished_at: number | null;
  created_at: number;
}

export interface PubDiffReport {
  diff_id: number;
  match_pct: number;
  differences: PubDifference[];
  summary: PubDiffSummary;
}

export interface PubDifference {
  field: string;
  type: string;
  value: string;
  severity: string;
}

export interface PubDiffSummary {
  total_differences: number;
  pptx_rendered: boolean;
  word_rendered: boolean;
  pptx_file_exists: boolean;
  word_file_exists: boolean;
  match_pct: number;
}

export interface PubVersion {
  id: number;
  project_id: number;
  presentation_id: number;
  major: number;
  minor: number;
  revision: number;
  version_label: string;
  pipeline_version: string | null;
  renderer_version: string | null;
  presentation_version: number;
  approval_status: string;
  approved_by: string | null;
  approved_at: number | null;
  notes: string | null;
  created_at: number;
}

export interface PubPackage {
  id: number;
  project_id: number;
  presentation_id: number;
  version_id: number | null;
  validation_id: number | null;
  status: string;
  package_path: string | null;
  package_size_bytes: number;
  manifest_json: Record<string, any>;
  contents_json: PubPackageContent[];
  created_by: string;
  created_at: number;
  finished_at: number | null;
}

export interface PubPackageContent {
  type: string;
  filename: string;
  size: number;
}

export interface PubPackageResult {
  package_id: number;
  package_path: string;
  package_size_bytes: number;
  file_count: number;
  contents: PubPackageContent[];
  version: string;
}

export interface PubApproval {
  id: number;
  project_id: number;
  presentation_id: number;
  version_id: number | null;
  action: string;
  status: string;
  actor: string;
  notes: string | null;
  created_at: number;
}

export interface PubApprovalResult {
  approval_id: number;
  status: string;
  version_id: number;
  package_id?: number;
  published_at?: number;
}

export interface PubReadinessSummary {
  readiness_score: number;
  readiness_class: string;
  scores: Record<string, number>;
  latest_validation_id: number | null;
  latest_version: string | null;
  latest_version_status: string | null;
  latest_package_id: number | null;
  latest_package_status: string | null;
  diff_match_pct: number | null;
  latest_approval_action: string | null;
  stats: {
    validations: number;
    packages: number;
    versions: number;
    downloads: number;
    publications: number;
  };
}

export interface PubAuditEntry {
  id: number;
  project_id: number;
  presentation_id: number | null;
  entity_type: string;
  entity_id: number | null;
  action: string;
  actor: string;
  details_json: Record<string, any>;
  created_at: number;
}

export interface PubDownload {
  id: number;
  project_id: number;
  package_id: number | null;
  file_type: string;
  file_path: string;
  file_size_bytes: number;
  downloaded_by: string;
  created_at: number;
}

export interface PubVersionResult {
  version_id: number;
  version_label: string;
  major: number;
  minor: number;
  revision: number;
}

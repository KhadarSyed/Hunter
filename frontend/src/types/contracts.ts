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

export interface QueryModule {
  module_name: string;
  module_type: "brand" | "product" | "audience" | "topic" | "behavior" | "tension" | "resolution" | "geography" | "language" | "platform" | "exclusion";
  terms: string[];
  boolean_fragment: string;
}

export interface QueryVersion {
  boolean_string: string;
  description: string;
  recall_level: "broad" | "balanced" | "precise";
  precision_level: "low" | "medium" | "high";
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

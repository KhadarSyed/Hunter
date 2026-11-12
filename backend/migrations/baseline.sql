CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE TABLE agent_autopilots (
    project_id bigint NOT NULL,
    user_id bigint NOT NULL,
    status text NOT NULL,
    note text DEFAULT ''::text NOT NULL,
    attempts bigint DEFAULT 0 NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE agent_autopilots_project_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE agent_autopilots_project_id_seq OWNED BY agent_autopilots.project_id;
CREATE TABLE agent_events (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    run_id bigint,
    actor text NOT NULL,
    action text NOT NULL,
    detail_json text,
    at double precision NOT NULL
);
CREATE SEQUENCE agent_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE agent_events_id_seq OWNED BY agent_events.id;
CREATE TABLE agent_fixes (
    id bigint NOT NULL,
    issue_id bigint NOT NULL,
    branch text NOT NULL,
    tier text NOT NULL,
    diff text NOT NULL,
    tests_json text NOT NULL,
    status text NOT NULL,
    note text DEFAULT ''::text NOT NULL,
    commit_sha text,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE agent_fixes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE agent_fixes_id_seq OWNED BY agent_fixes.id;
CREATE TABLE agent_issues (
    id bigint NOT NULL,
    project_id bigint,
    source text NOT NULL,
    kind text NOT NULL,
    title text NOT NULL,
    detail_json text NOT NULL,
    fingerprint text NOT NULL,
    status text NOT NULL,
    note text DEFAULT ''::text NOT NULL,
    seen bigint DEFAULT 1 NOT NULL,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE agent_issues_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE agent_issues_id_seq OWNED BY agent_issues.id;
CREATE TABLE agent_memory (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    kind text NOT NULL,
    key text NOT NULL,
    value_json text NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE agent_memory_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE agent_memory_id_seq OWNED BY agent_memory.id;
CREATE TABLE brand_logos (
    brand_key text NOT NULL,
    brand_name text NOT NULL,
    logo_url text,
    domain text,
    source text NOT NULL,
    fetched_at double precision NOT NULL
);
CREATE TABLE deck_reference_decks (
    id bigint NOT NULL,
    path text NOT NULL,
    hash text NOT NULL,
    family text NOT NULL,
    n_slides bigint NOT NULL,
    indexed_at double precision NOT NULL
);
CREATE SEQUENCE deck_reference_decks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE deck_reference_decks_id_seq OWNED BY deck_reference_decks.id;
CREATE TABLE deck_reference_slides (
    id bigint NOT NULL,
    deck_id bigint NOT NULL,
    n bigint NOT NULL,
    type text NOT NULL,
    features_json text NOT NULL
);
CREATE SEQUENCE deck_reference_slides_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE deck_reference_slides_id_seq OWNED BY deck_reference_slides.id;
CREATE TABLE intel_article_classifications (
    norm_url text NOT NULL,
    field text NOT NULL,
    value_json text NOT NULL,
    model text,
    created_at double precision NOT NULL
);
CREATE TABLE intel_article_rq (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    article_id bigint NOT NULL,
    rq_id text NOT NULL,
    signature text NOT NULL,
    matched bigint DEFAULT 0 NOT NULL,
    match_confidence double precision,
    keywords_json text DEFAULT '[]'::text NOT NULL,
    tags_json text DEFAULT '{}'::text NOT NULL,
    evidence_json text DEFAULT '{}'::text NOT NULL,
    summary text DEFAULT ''::text NOT NULL,
    reason text DEFAULT ''::text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    decided_by text,
    decided_at double precision,
    decision_reason text,
    tagged_at double precision,
    query_changed bigint DEFAULT 0 NOT NULL
);
CREATE SEQUENCE intel_article_rq_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_article_rq_id_seq OWNED BY intel_article_rq.id;
CREATE TABLE intel_articles (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    norm_url text NOT NULL,
    url text NOT NULL,
    channel text NOT NULL,
    title text DEFAULT ''::text NOT NULL,
    summary text DEFAULT ''::text NOT NULL,
    outlet text DEFAULT ''::text NOT NULL,
    published text,
    country text DEFAULT ''::text NOT NULL,
    reach double precision DEFAULT 0 NOT NULL,
    author_name text DEFAULT ''::text NOT NULL,
    author_id text DEFAULT ''::text NOT NULL,
    post_id text DEFAULT ''::text NOT NULL,
    raw_json text DEFAULT '{}'::text NOT NULL,
    file_id bigint,
    content text DEFAULT ''::text NOT NULL,
    content_status text DEFAULT 'pending'::text NOT NULL,
    tags_json text,
    tag_status text DEFAULT 'pending'::text NOT NULL,
    tag_error text,
    sentiment text,
    sentiment_confidence double precision,
    syndicated_json text,
    similar_json text,
    created_at double precision NOT NULL,
    rq_matched bigint,
    copy_of bigint,
    excluded_reason text,
    keep_by text,
    keep_at double precision,
    keep_comment text
);
CREATE SEQUENCE intel_articles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_articles_id_seq OWNED BY intel_articles.id;
CREATE TABLE intel_asset_library (
    id bigint NOT NULL,
    kind text NOT NULL,
    key text NOT NULL,
    s3_key text,
    content_type text DEFAULT ''::text NOT NULL,
    sha256 text DEFAULT ''::text NOT NULL,
    size bigint DEFAULT 0 NOT NULL,
    brand text DEFAULT ''::text NOT NULL,
    summary text DEFAULT ''::text NOT NULL,
    meta_json text DEFAULT '{}'::text NOT NULL,
    embedding vector,
    missing bigint DEFAULT 0 NOT NULL,
    use_count bigint DEFAULT 0 NOT NULL,
    last_used_at double precision,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_asset_library_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_asset_library_id_seq OWNED BY intel_asset_library.id;
CREATE TABLE intel_assets (
    kind text NOT NULL,
    key text NOT NULL,
    content bytea NOT NULL,
    content_type text DEFAULT ''::text NOT NULL,
    meta_json text DEFAULT '{}'::text NOT NULL,
    created_at double precision NOT NULL
);
CREATE TABLE intel_background_briefs (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    research_id bigint NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    brief_json text NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    approval_status text DEFAULT 'pending'::text,
    approved_by text,
    approved_at double precision,
    docx_path text,
    docx_generated_at double precision,
    notes text,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE intel_background_briefs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_background_briefs_id_seq OWNED BY intel_background_briefs.id;
CREATE TABLE intel_background_research (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    research_json text NOT NULL,
    llm_output_json text,
    approval_status text DEFAULT 'pending'::text,
    approved_by text,
    approved_at double precision,
    notes text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_background_research_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_background_research_id_seq OWNED BY intel_background_research.id;
CREATE TABLE intel_brief_section_edits (
    id bigint NOT NULL,
    brief_id bigint NOT NULL,
    section_key text NOT NULL,
    edited_content text NOT NULL,
    analyst_note text,
    edited_by text DEFAULT 'analyst'::text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_brief_section_edits_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_brief_section_edits_id_seq OWNED BY intel_brief_section_edits.id;
CREATE TABLE intel_dataset_files (
    dataset_id bigint NOT NULL,
    file_name text NOT NULL,
    content bytea NOT NULL,
    created_at double precision NOT NULL
);
CREATE TABLE intel_datasets (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    file_name text NOT NULL,
    file_path text NOT NULL,
    record_count bigint DEFAULT 0 NOT NULL,
    column_mapping_json text,
    stats_json text,
    preview_json text,
    approval_status text DEFAULT 'pending'::text,
    approved_by text,
    approved_at double precision,
    created_at double precision NOT NULL,
    processing_status text DEFAULT 'done'::text,
    processing_error text,
    research_question_id text,
    enrichment_status text,
    enrichment_json text,
    enrichment_error text
);
CREATE SEQUENCE intel_datasets_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_datasets_id_seq OWNED BY intel_datasets.id;
CREATE TABLE intel_deliverable_files (
    run_id bigint NOT NULL,
    project_id bigint NOT NULL,
    name text NOT NULL,
    part bigint NOT NULL,
    gz bigint DEFAULT 0 NOT NULL,
    content bytea NOT NULL,
    created_at double precision NOT NULL,
    s3_key text
);
CREATE TABLE intel_deliverable_plans (
    project_id bigint NOT NULL,
    rq_id text NOT NULL,
    signature text NOT NULL,
    plan_json text NOT NULL,
    source text NOT NULL,
    updated_at double precision NOT NULL
);
CREATE TABLE intel_deliverable_runs (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    status text DEFAULT 'running'::text NOT NULL,
    stage text,
    stages_json text,
    pptx_path text,
    docx_path text,
    thumbs_dir text,
    error text,
    created_at double precision NOT NULL,
    finished_at double precision,
    html_path text,
    pdf_path text,
    studio_pptx_path text,
    deck_dir text
);
CREATE SEQUENCE intel_deliverable_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_deliverable_runs_id_seq OWNED BY intel_deliverable_runs.id;
CREATE TABLE intel_deliverable_sections (
    id bigint NOT NULL,
    run_id bigint NOT NULL,
    section_key text NOT NULL,
    rq_id text,
    module text,
    payload_json text NOT NULL,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_deliverable_sections_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_deliverable_sections_id_seq OWNED BY intel_deliverable_sections.id;
CREATE TABLE intel_evidence (
    id bigint NOT NULL,
    run_id bigint NOT NULL,
    unit_id text NOT NULL,
    objective_id text NOT NULL,
    evidence_type text NOT NULL,
    platform text,
    source text,
    date text,
    text_excerpt text,
    metrics_json text,
    confidence text DEFAULT 'medium'::text,
    method text NOT NULL,
    rationale text,
    dataset text DEFAULT 'meltwater_export'::text,
    created_at double precision NOT NULL,
    url text,
    document_id text,
    source_file text,
    row_index bigint
);
CREATE SEQUENCE intel_evidence_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_evidence_id_seq OWNED BY intel_evidence.id;
CREATE TABLE intel_exclusions (
    id bigint NOT NULL,
    org_id bigint,
    kind text NOT NULL,
    value text NOT NULL,
    created_by bigint,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_exclusions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_exclusions_id_seq OWNED BY intel_exclusions.id;
CREATE TABLE intel_execution_logs (
    id bigint NOT NULL,
    run_id bigint NOT NULL,
    unit_id text,
    level text DEFAULT 'info'::text NOT NULL,
    message text NOT NULL,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_execution_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_execution_logs_id_seq OWNED BY intel_execution_logs.id;
CREATE TABLE intel_execution_runs (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    plan_id bigint NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    total_units bigint DEFAULT 0 NOT NULL,
    completed_units bigint DEFAULT 0 NOT NULL,
    failed_units bigint DEFAULT 0 NOT NULL,
    skipped_units bigint DEFAULT 0 NOT NULL,
    total_evidence bigint DEFAULT 0 NOT NULL,
    started_at double precision,
    finished_at double precision,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_execution_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_execution_runs_id_seq OWNED BY intel_execution_runs.id;
CREATE TABLE intel_execution_units (
    id bigint NOT NULL,
    run_id bigint NOT NULL,
    unit_id text NOT NULL,
    objective_id text NOT NULL,
    method text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    progress_pct bigint DEFAULT 0,
    records_processed bigint DEFAULT 0,
    evidence_count bigint DEFAULT 0,
    error text,
    result_json text,
    started_at double precision,
    finished_at double precision,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_execution_units_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_execution_units_id_seq OWNED BY intel_execution_units.id;
CREATE TABLE intel_insight_audit (
    id bigint NOT NULL,
    insight_id bigint NOT NULL,
    action text NOT NULL,
    field text,
    old_value text,
    new_value text,
    actor text DEFAULT 'analyst'::text NOT NULL,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_insight_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_insight_audit_id_seq OWNED BY intel_insight_audit.id;
CREATE TABLE intel_insight_evidence (
    id bigint NOT NULL,
    insight_id bigint NOT NULL,
    library_item_id bigint NOT NULL,
    role text DEFAULT 'supporting'::text NOT NULL,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_insight_evidence_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_insight_evidence_id_seq OWNED BY intel_insight_evidence.id;
CREATE TABLE intel_insights (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    objective_id text NOT NULL,
    insight_type text DEFAULT 'behavioural'::text NOT NULL,
    title text NOT NULL,
    executive_summary text,
    observation text,
    interpretation text,
    business_impact text,
    confidence_score double precision DEFAULT 0.5,
    confidence_rationale text,
    evidence_count bigint DEFAULT 0,
    platforms_represented text,
    date_coverage text,
    contradictory_evidence text,
    limitations text,
    recommended_visualisation text,
    analyst_notes text,
    status text DEFAULT 'draft'::text NOT NULL,
    reviewed_by text,
    reviewed_at double precision,
    generation_id text,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE intel_insights_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_insights_id_seq OWNED BY intel_insights.id;
CREATE TABLE intel_jobs (
    id text NOT NULL,
    project_id bigint NOT NULL,
    job_type text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    progress_pct bigint DEFAULT 0,
    progress_message text DEFAULT ''::text,
    result_json text,
    error text,
    started_at double precision,
    finished_at double precision,
    created_at double precision NOT NULL
);
CREATE TABLE intel_latest24h_refreshes (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    status text NOT NULL,
    started_at double precision NOT NULL,
    finished_at double precision,
    counts_json text DEFAULT '{}'::text NOT NULL,
    fetched bigint DEFAULT 0 NOT NULL,
    kept bigint DEFAULT 0 NOT NULL,
    summary_json text,
    charts_json text,
    articles_json text,
    error text
);
CREATE SEQUENCE intel_latest24h_refreshes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_latest24h_refreshes_id_seq OWNED BY intel_latest24h_refreshes.id;
CREATE TABLE intel_library_annotations (
    id bigint NOT NULL,
    library_item_id bigint NOT NULL,
    author text DEFAULT 'analyst'::text NOT NULL,
    note text NOT NULL,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_library_annotations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_library_annotations_id_seq OWNED BY intel_library_annotations.id;
CREATE TABLE intel_library_audit (
    id bigint NOT NULL,
    library_item_id bigint NOT NULL,
    action text NOT NULL,
    field text,
    old_value text,
    new_value text,
    actor text DEFAULT 'analyst'::text NOT NULL,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_library_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_library_audit_id_seq OWNED BY intel_library_audit.id;
CREATE TABLE intel_library_items (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    evidence_id bigint NOT NULL,
    review_status text DEFAULT 'unreviewed'::text NOT NULL,
    quality_score double precision,
    quality_components_json text,
    relevance_score double precision,
    is_representative bigint DEFAULT 0,
    is_high_value bigint DEFAULT 0,
    canonical_id bigint,
    duplicate_group text,
    objective_id text,
    unit_id text,
    reviewed_by text,
    reviewed_at double precision,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE intel_library_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_library_items_id_seq OWNED BY intel_library_items.id;
CREATE TABLE intel_news_approvals (
    id bigint NOT NULL,
    research_id bigint NOT NULL,
    item_index bigint NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    notes text,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE intel_news_approvals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_news_approvals_id_seq OWNED BY intel_news_approvals.id;
CREATE TABLE intel_pc_audit (
    id bigint NOT NULL,
    presentation_id bigint NOT NULL,
    slide_id bigint,
    action text NOT NULL,
    field text,
    old_value text,
    new_value text,
    actor text DEFAULT 'system'::text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_pc_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_pc_audit_id_seq OWNED BY intel_pc_audit.id;
CREATE TABLE intel_pc_presentations (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    storyline_id bigint NOT NULL,
    title text NOT NULL,
    executive_summary text,
    narrative_pattern text,
    total_slides bigint DEFAULT 0,
    estimated_duration_minutes double precision DEFAULT 0,
    status text DEFAULT 'draft'::text NOT NULL,
    generated_by text DEFAULT 'system'::text,
    approved_by text,
    approved_at double precision,
    generation_id text,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE intel_pc_presentations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_pc_presentations_id_seq OWNED BY intel_pc_presentations.id;
CREATE TABLE intel_pc_slides (
    id bigint NOT NULL,
    presentation_id bigint NOT NULL,
    slide_number bigint NOT NULL,
    slide_purpose text NOT NULL,
    node_id bigint,
    title text NOT NULL,
    subtitle text,
    narrative text,
    business_objective text,
    key_message text,
    speaker_notes text,
    recommended_visual text,
    recommended_chart text,
    layout_recommendation text,
    layout_rationale text,
    alt_layout_1 text,
    alt_layout_1_rationale text,
    alt_layout_2 text,
    alt_layout_2_rationale text,
    template_family_id bigint,
    content_blocks_json text DEFAULT '[]'::text,
    evidence_ids_json text DEFAULT '[]'::text,
    insight_ids_json text DEFAULT '[]'::text,
    historical_refs_json text DEFAULT '[]'::text,
    confidence_json text DEFAULT '{}'::text,
    overall_confidence double precision DEFAULT 0.5,
    transition_to_next text,
    status text DEFAULT 'draft'::text NOT NULL,
    is_locked bigint DEFAULT 0,
    reviewed_by text,
    reviewed_at double precision,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE intel_pc_slides_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_pc_slides_id_seq OWNED BY intel_pc_slides.id;
CREATE TABLE intel_pipeline_cache (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    stage_id text NOT NULL,
    input_hash text NOT NULL,
    output_hash text,
    version bigint DEFAULT 1,
    result_summary_json text DEFAULT '{}'::text,
    created_at double precision NOT NULL,
    expires_at double precision
);
CREATE SEQUENCE intel_pipeline_cache_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_pipeline_cache_id_seq OWNED BY intel_pipeline_cache.id;
CREATE TABLE intel_pipeline_logs (
    id bigint NOT NULL,
    run_id text NOT NULL,
    stage_id text,
    level text DEFAULT 'info'::text,
    message text NOT NULL,
    details_json text DEFAULT '{}'::text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_pipeline_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_pipeline_logs_id_seq OWNED BY intel_pipeline_logs.id;
CREATE TABLE intel_pipeline_metrics (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    stage_id text,
    run_id text,
    metric_type text NOT NULL,
    value double precision NOT NULL,
    unit text DEFAULT 'ms'::text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_pipeline_metrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_pipeline_metrics_id_seq OWNED BY intel_pipeline_metrics.id;
CREATE TABLE intel_pipeline_runs (
    id text NOT NULL,
    project_id bigint NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    execution_mode text DEFAULT 'full'::text NOT NULL,
    current_stage text,
    start_stage text,
    completed_stages_json text DEFAULT '[]'::text,
    remaining_stages_json text DEFAULT '[]'::text,
    skipped_stages_json text DEFAULT '[]'::text,
    progress_pct double precision DEFAULT 0,
    estimated_remaining_ms bigint DEFAULT 0,
    "user" text DEFAULT 'system'::text,
    error text,
    started_at double precision,
    completed_at double precision,
    created_at double precision NOT NULL
);
CREATE TABLE intel_pipeline_stages (
    id bigint NOT NULL,
    run_id text NOT NULL,
    stage_id text NOT NULL,
    stage_name text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    version bigint DEFAULT 1,
    input_hash text,
    output_hash text,
    dependencies_json text DEFAULT '[]'::text,
    execution_time_ms bigint DEFAULT 0,
    started_at double precision,
    completed_at double precision,
    logs_json text DEFAULT '[]'::text,
    warnings_json text DEFAULT '[]'::text,
    errors_json text DEFAULT '[]'::text,
    cache_status text DEFAULT 'miss'::text,
    result_json text DEFAULT '{}'::text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_pipeline_stages_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_pipeline_stages_id_seq OWNED BY intel_pipeline_stages.id;
CREATE TABLE intel_projects (
    id bigint NOT NULL,
    project_name text NOT NULL,
    spec_json text NOT NULL,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL,
    project_type text DEFAULT 'research'::text NOT NULL,
    brand text,
    org_id bigint,
    owner_user_id bigint,
    archived_at double precision,
    dataset_approved_at double precision,
    dataset_approved_by text
);
CREATE SEQUENCE intel_projects_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_projects_id_seq OWNED BY intel_projects.id;
CREATE TABLE intel_pub_approvals (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    presentation_id bigint NOT NULL,
    version_id bigint,
    action text NOT NULL,
    status text NOT NULL,
    actor text DEFAULT 'system'::text,
    notes text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL
);
CREATE SEQUENCE intel_pub_approvals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_pub_approvals_id_seq OWNED BY intel_pub_approvals.id;
CREATE TABLE intel_pub_audit (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    presentation_id bigint,
    entity_type text NOT NULL,
    entity_id bigint,
    action text NOT NULL,
    actor text DEFAULT 'system'::text,
    details_json text DEFAULT '{}'::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL
);
CREATE SEQUENCE intel_pub_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_pub_audit_id_seq OWNED BY intel_pub_audit.id;
CREATE TABLE intel_pub_diff_reports (
    id bigint NOT NULL,
    validation_id bigint NOT NULL,
    project_id bigint NOT NULL,
    presentation_id bigint NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    match_pct double precision DEFAULT 0,
    differences_json text DEFAULT '[]'::text,
    summary_json text DEFAULT '{}'::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL
);
CREATE SEQUENCE intel_pub_diff_reports_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_pub_diff_reports_id_seq OWNED BY intel_pub_diff_reports.id;
CREATE TABLE intel_pub_downloads (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    package_id bigint,
    file_type text NOT NULL,
    file_path text NOT NULL,
    file_size_bytes bigint DEFAULT 0,
    downloaded_by text DEFAULT 'system'::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL
);
CREATE SEQUENCE intel_pub_downloads_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_pub_downloads_id_seq OWNED BY intel_pub_downloads.id;
CREATE TABLE intel_pub_packages (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    presentation_id bigint NOT NULL,
    version_id bigint,
    validation_id bigint,
    status text DEFAULT 'building'::text NOT NULL,
    package_path text,
    package_size_bytes bigint DEFAULT 0,
    manifest_json text DEFAULT '{}'::text,
    contents_json text DEFAULT '[]'::text,
    created_by text DEFAULT 'system'::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL,
    finished_at double precision
);
CREATE SEQUENCE intel_pub_packages_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_pub_packages_id_seq OWNED BY intel_pub_packages.id;
CREATE TABLE intel_pub_validations (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    presentation_id bigint NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    readiness_score double precision DEFAULT 0,
    readiness_class text DEFAULT 'draft'::text,
    scores_json text DEFAULT '{}'::text,
    issues_json text DEFAULT '[]'::text,
    warnings_json text DEFAULT '[]'::text,
    pptx_job_id text,
    word_job_id text,
    validated_by text DEFAULT 'system'::text,
    started_at double precision,
    finished_at double precision,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL
);
CREATE SEQUENCE intel_pub_validations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_pub_validations_id_seq OWNED BY intel_pub_validations.id;
CREATE TABLE intel_pub_versions (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    presentation_id bigint NOT NULL,
    major bigint DEFAULT 1 NOT NULL,
    minor bigint DEFAULT 0 NOT NULL,
    revision bigint DEFAULT 0 NOT NULL,
    version_label text,
    pipeline_version text,
    renderer_version text,
    presentation_version bigint DEFAULT 1,
    approval_status text DEFAULT 'draft'::text,
    approved_by text,
    approved_at double precision,
    notes text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL
);
CREATE SEQUENCE intel_pub_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_pub_versions_id_seq OWNED BY intel_pub_versions.id;
CREATE TABLE intel_query_versions (
    id bigint NOT NULL,
    strategy_id bigint NOT NULL,
    version_label text NOT NULL,
    query_type text NOT NULL,
    query_text text NOT NULL,
    is_active bigint DEFAULT 1,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_query_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_query_versions_id_seq OWNED BY intel_query_versions.id;
CREATE TABLE intel_question_dimensions (
    project_id bigint NOT NULL,
    rq_id text NOT NULL,
    signature text NOT NULL,
    dimensions_json text NOT NULL,
    source text NOT NULL,
    updated_at double precision NOT NULL
);
CREATE TABLE intel_question_tag_schemas (
    project_id bigint NOT NULL,
    rq_id text NOT NULL,
    signature text NOT NULL,
    schema_json text NOT NULL,
    source text NOT NULL,
    updated_at double precision NOT NULL
);
CREATE TABLE intel_reference_decks (
    path text NOT NULL,
    text text,
    embedding_json text,
    indexed_at double precision NOT NULL,
    model text
);
CREATE TABLE intel_render_history (
    id bigint NOT NULL,
    presentation_id bigint NOT NULL,
    job_id text NOT NULL,
    action text NOT NULL,
    actor text DEFAULT 'system'::text,
    details_json text DEFAULT '{}'::text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_render_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_render_history_id_seq OWNED BY intel_render_history.id;
CREATE TABLE intel_render_jobs (
    id text NOT NULL,
    presentation_id bigint NOT NULL,
    job_type text DEFAULT 'full'::text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    progress_pct bigint DEFAULT 0,
    progress_message text DEFAULT ''::text,
    slide_ids_json text DEFAULT '[]'::text,
    theme_id text DEFAULT 'hunter_default'::text,
    output_path text,
    output_size_bytes bigint,
    warnings_json text DEFAULT '[]'::text,
    error text,
    started_at double precision,
    finished_at double precision,
    created_at double precision NOT NULL
);
CREATE TABLE intel_render_metrics (
    id bigint NOT NULL,
    job_id text NOT NULL,
    slide_id bigint NOT NULL,
    slide_number bigint NOT NULL,
    render_type text NOT NULL,
    duration_ms bigint DEFAULT 0,
    warnings_json text DEFAULT '[]'::text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_render_metrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_render_metrics_id_seq OWNED BY intel_render_metrics.id;
CREATE TABLE intel_rendered_presentations (
    id bigint NOT NULL,
    job_id text NOT NULL,
    presentation_id bigint NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    output_path text NOT NULL,
    output_size_bytes bigint DEFAULT 0,
    slide_count bigint DEFAULT 0,
    theme_id text DEFAULT 'hunter_default'::text,
    render_duration_ms bigint DEFAULT 0,
    metadata_json text DEFAULT '{}'::text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_rendered_presentations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_rendered_presentations_id_seq OWNED BY intel_rendered_presentations.id;
CREATE TABLE intel_research_item_vectors (
    item_id bigint NOT NULL,
    model text NOT NULL,
    dim bigint NOT NULL,
    vector bytea NOT NULL,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_research_item_vectors_item_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_research_item_vectors_item_id_seq OWNED BY intel_research_item_vectors.item_id;
CREATE TABLE intel_research_items (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    research_id bigint,
    topic text NOT NULL,
    source_api text NOT NULL,
    platform text,
    publication text,
    published_date double precision NOT NULL,
    title text,
    content text,
    url text NOT NULL,
    created_at double precision NOT NULL,
    author text,
    thumbnail_url text,
    access text,
    about_brand double precision,
    sentiment text,
    sentiment_confidence double precision,
    classified_for text
);
CREATE SEQUENCE intel_research_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_research_items_id_seq OWNED BY intel_research_items.id;
CREATE TABLE intel_research_plans (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    plan_json text NOT NULL,
    source text DEFAULT 'llm'::text NOT NULL,
    approval_status text DEFAULT 'pending'::text,
    approved_by text,
    approved_at double precision,
    notes text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_research_plans_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_research_plans_id_seq OWNED BY intel_research_plans.id;
CREATE TABLE intel_research_specifications (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    spec_json text NOT NULL,
    raw_brief_text text,
    status text DEFAULT 'draft'::text NOT NULL,
    readiness_status text DEFAULT 'not_ready'::text NOT NULL,
    readiness_json text,
    approval_status text DEFAULT 'pending'::text NOT NULL,
    approved_by text,
    approved_at double precision,
    rejected_reason text,
    generation_source text DEFAULT 'manual'::text NOT NULL,
    llm_model text,
    docx_path text,
    docx_generated_at double precision,
    notes text,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE intel_research_specifications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_research_specifications_id_seq OWNED BY intel_research_specifications.id;
CREATE TABLE intel_sample_evaluations (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    strategy_id bigint NOT NULL,
    file_name text NOT NULL,
    file_path text NOT NULL,
    evaluation_json text,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_sample_evaluations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_sample_evaluations_id_seq OWNED BY intel_sample_evaluations.id;
CREATE TABLE intel_search_strategies (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    strategy_json text NOT NULL,
    approval_status text DEFAULT 'pending'::text,
    approved_by text,
    approved_at double precision,
    notes text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_search_strategies_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_search_strategies_id_seq OWNED BY intel_search_strategies.id;
CREATE TABLE intel_si_corrections (
    id bigint NOT NULL,
    slide_id bigint NOT NULL,
    field_name text NOT NULL,
    old_value text,
    new_value text NOT NULL,
    corrected_by text DEFAULT 'analyst'::text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_si_corrections_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_si_corrections_id_seq OWNED BY intel_si_corrections.id;
CREATE TABLE intel_si_detected_projects (
    id bigint NOT NULL,
    presentation_id bigint NOT NULL,
    project_name text,
    client_name text,
    brand_name text,
    analyst_name text,
    start_slide bigint NOT NULL,
    end_slide bigint NOT NULL,
    slide_count bigint DEFAULT 0,
    confidence double precision DEFAULT 0.0,
    is_confirmed bigint DEFAULT 0,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_si_detected_projects_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_si_detected_projects_id_seq OWNED BY intel_si_detected_projects.id;
CREATE TABLE intel_si_embeddings (
    id bigint NOT NULL,
    slide_id bigint NOT NULL,
    embedding_blob bytea NOT NULL,
    model_name text DEFAULT 'nomic-embed-text'::text NOT NULL,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_si_embeddings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_si_embeddings_id_seq OWNED BY intel_si_embeddings.id;
CREATE TABLE intel_si_presentations (
    id bigint NOT NULL,
    filename text NOT NULL,
    file_path text NOT NULL,
    file_size bigint DEFAULT 0 NOT NULL,
    file_hash text,
    slide_count bigint DEFAULT 0,
    processed_count bigint DEFAULT 0,
    status text DEFAULT 'pending'::text NOT NULL,
    error text,
    started_at double precision,
    completed_at double precision,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_si_presentations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_si_presentations_id_seq OWNED BY intel_si_presentations.id;
CREATE TABLE intel_si_processing_logs (
    id bigint NOT NULL,
    presentation_id bigint NOT NULL,
    step text NOT NULL,
    slide_number bigint,
    status text NOT NULL,
    message text,
    duration_ms double precision,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_si_processing_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_si_processing_logs_id_seq OWNED BY intel_si_processing_logs.id;
CREATE TABLE intel_si_retrieval_history (
    id bigint NOT NULL,
    query_text text NOT NULL,
    node_id bigint,
    storyline_id bigint,
    results_json text NOT NULL,
    result_count bigint DEFAULT 0,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_si_retrieval_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_si_retrieval_history_id_seq OWNED BY intel_si_retrieval_history.id;
CREATE TABLE intel_si_slides (
    id bigint NOT NULL,
    presentation_id bigint NOT NULL,
    slide_number bigint NOT NULL,
    all_text text,
    title_text text,
    body_text text,
    footer_text text,
    notes_text text,
    shape_count bigint DEFAULT 0,
    text_shape_count bigint DEFAULT 0,
    chart_count bigint DEFAULT 0,
    table_count bigint DEFAULT 0,
    image_count bigint DEFAULT 0,
    has_chart bigint DEFAULT 0,
    has_table bigint DEFAULT 0,
    has_image bigint DEFAULT 0,
    thumbnail_b64 text,
    slide_purpose text,
    layout_type text,
    visual_type text,
    narrative_role text,
    report_type text,
    industry text,
    client text,
    brand text,
    data_density text DEFAULT 'medium'::text,
    executive_suitability text DEFAULT 'medium'::text,
    visual_complexity text DEFAULT 'medium'::text,
    classification_confidence double precision DEFAULT 0.0,
    detected_project_id bigint,
    is_excluded bigint DEFAULT 0,
    is_template_approved bigint DEFAULT 0,
    status text DEFAULT 'pending'::text NOT NULL,
    error text,
    processed_at double precision,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_si_slides_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_si_slides_id_seq OWNED BY intel_si_slides.id;
CREATE TABLE intel_si_storyline_matches (
    id bigint NOT NULL,
    storyline_id bigint NOT NULL,
    node_id bigint NOT NULL,
    slide_id bigint NOT NULL,
    similarity_score double precision DEFAULT 0.0,
    match_reason text,
    recommended_elements text,
    elements_not_to_reuse text,
    recommended_layout text,
    recommended_visual text,
    recommended_chart text,
    confidence double precision DEFAULT 0.0,
    is_accepted bigint DEFAULT 0,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_si_storyline_matches_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_si_storyline_matches_id_seq OWNED BY intel_si_storyline_matches.id;
CREATE TABLE intel_si_style_patterns (
    id bigint NOT NULL,
    presentation_id bigint,
    pattern_type text NOT NULL,
    pattern_name text NOT NULL,
    pattern_data text NOT NULL,
    frequency bigint DEFAULT 1,
    source_slides text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_si_style_patterns_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_si_style_patterns_id_seq OWNED BY intel_si_style_patterns.id;
CREATE TABLE intel_si_template_families (
    id bigint NOT NULL,
    family_name text NOT NULL,
    typical_layout text,
    typical_visual text,
    typical_purpose text,
    required_inputs text,
    recommended_usage text,
    member_count bigint DEFAULT 0,
    is_approved bigint DEFAULT 0,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE intel_si_template_families_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_si_template_families_id_seq OWNED BY intel_si_template_families.id;
CREATE TABLE intel_si_template_members (
    id bigint NOT NULL,
    family_id bigint NOT NULL,
    slide_id bigint NOT NULL,
    is_representative bigint DEFAULT 0,
    similarity_score double precision DEFAULT 0.0,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_si_template_members_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_si_template_members_id_seq OWNED BY intel_si_template_members.id;
CREATE TABLE intel_spec_audit (
    id bigint NOT NULL,
    spec_id bigint NOT NULL,
    action text NOT NULL,
    section_key text,
    field text,
    old_value text,
    new_value text,
    actor text DEFAULT 'analyst'::text NOT NULL,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_spec_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_spec_audit_id_seq OWNED BY intel_spec_audit.id;
CREATE TABLE intel_spec_clarifications (
    id bigint NOT NULL,
    spec_id bigint NOT NULL,
    section_key text,
    question text NOT NULL,
    is_blocking bigint DEFAULT 1 NOT NULL,
    answer text,
    resolved_by text,
    resolved_at double precision,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE intel_spec_clarifications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_spec_clarifications_id_seq OWNED BY intel_spec_clarifications.id;
CREATE TABLE intel_spec_section_approvals (
    id bigint NOT NULL,
    spec_id bigint NOT NULL,
    section_key text NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    is_locked bigint DEFAULT 0 NOT NULL,
    locked_by text,
    locked_at double precision,
    edited_content text,
    analyst_note text,
    reviewed_by text,
    reviewed_at double precision,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE intel_spec_section_approvals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_spec_section_approvals_id_seq OWNED BY intel_spec_section_approvals.id;
CREATE TABLE intel_story_node_insights (
    id bigint NOT NULL,
    node_id bigint NOT NULL,
    insight_id bigint NOT NULL,
    role text DEFAULT 'supporting'::text NOT NULL,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_story_node_insights_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_story_node_insights_id_seq OWNED BY intel_story_node_insights.id;
CREATE TABLE intel_story_nodes (
    id bigint NOT NULL,
    storyline_id bigint NOT NULL,
    section_type text NOT NULL,
    title text NOT NULL,
    purpose text,
    narrative_summary text,
    suggested_visual text DEFAULT 'table'::text,
    priority text DEFAULT 'medium'::text,
    estimated_duration_minutes double precision DEFAULT 2.0,
    confidence_score double precision DEFAULT 0.5,
    transition_text text,
    is_key_message bigint DEFAULT 0,
    is_locked bigint DEFAULT 0,
    order_position bigint DEFAULT 0 NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    reviewed_by text,
    reviewed_at double precision,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE intel_story_nodes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_story_nodes_id_seq OWNED BY intel_story_nodes.id;
CREATE TABLE intel_storyline_audit (
    id bigint NOT NULL,
    storyline_id bigint NOT NULL,
    node_id bigint,
    action text NOT NULL,
    field text,
    old_value text,
    new_value text,
    actor text DEFAULT 'analyst'::text NOT NULL,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_storyline_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_storyline_audit_id_seq OWNED BY intel_storyline_audit.id;
CREATE TABLE intel_storylines (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    narrative_pattern text DEFAULT 'executive_briefing'::text NOT NULL,
    title text NOT NULL,
    executive_summary text,
    total_duration_minutes double precision DEFAULT 0,
    node_count bigint DEFAULT 0,
    status text DEFAULT 'draft'::text NOT NULL,
    generated_by text DEFAULT 'system'::text,
    approved_by text,
    approved_at double precision,
    generation_id text,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE intel_storylines_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_storylines_id_seq OWNED BY intel_storylines.id;
CREATE TABLE intel_template_versions (
    id bigint NOT NULL,
    theme_id text NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    template_path text NOT NULL,
    changelog text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_template_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_template_versions_id_seq OWNED BY intel_template_versions.id;
CREATE TABLE intel_theme_titles (
    project_id bigint NOT NULL,
    label_key text NOT NULL,
    title text NOT NULL
);
CREATE TABLE intel_themes (
    id text NOT NULL,
    name text NOT NULL,
    description text,
    primary_color text DEFAULT '#5B2C9D'::text,
    secondary_color text DEFAULT '#5E35B1'::text,
    accent_color text DEFAULT '#A6CAEC'::text,
    background_color text DEFAULT '#FFFFFF'::text,
    text_color text DEFAULT '#1A1A1A'::text,
    font_heading text DEFAULT 'Calibri'::text,
    font_body text DEFAULT 'Calibri'::text,
    font_size_title bigint DEFAULT 26,
    font_size_body bigint DEFAULT 14,
    font_size_caption bigint DEFAULT 9,
    logo_position text DEFAULT 'top_right'::text,
    footer_style text DEFAULT 'grey_band'::text,
    color_palette_json text DEFAULT '[]'::text,
    is_default bigint DEFAULT 0,
    is_active bigint DEFAULT 1,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE TABLE intel_upload_files (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    file_name text NOT NULL,
    s3_key text,
    content bytea,
    rows_read bigint DEFAULT 0 NOT NULL,
    added bigint DEFAULT 0 NOT NULL,
    duplicates bigint DEFAULT 0 NOT NULL,
    error text,
    uploaded_by text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE intel_upload_files_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_upload_files_id_seq OWNED BY intel_upload_files.id;
CREATE TABLE intel_word_documents (
    id bigint NOT NULL,
    job_id text NOT NULL,
    presentation_id bigint NOT NULL,
    version bigint DEFAULT 1,
    output_path text NOT NULL,
    output_size_bytes bigint DEFAULT 0,
    section_count bigint DEFAULT 0,
    page_count bigint DEFAULT 0,
    word_count bigint DEFAULT 0,
    theme_id text DEFAULT 'hunter_default'::text,
    render_duration_ms bigint DEFAULT 0,
    metadata_json text DEFAULT '{}'::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL
);
CREATE SEQUENCE intel_word_documents_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_word_documents_id_seq OWNED BY intel_word_documents.id;
CREATE TABLE intel_word_history (
    id bigint NOT NULL,
    presentation_id bigint NOT NULL,
    job_id text NOT NULL,
    action text NOT NULL,
    actor text DEFAULT 'system'::text,
    details_json text DEFAULT '{}'::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL
);
CREATE SEQUENCE intel_word_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_word_history_id_seq OWNED BY intel_word_history.id;
CREATE TABLE intel_word_jobs (
    id text NOT NULL,
    presentation_id bigint NOT NULL,
    job_type text DEFAULT 'full'::text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    progress_pct double precision DEFAULT 0,
    progress_message text,
    sections_json text DEFAULT '[]'::text,
    theme_id text DEFAULT 'hunter_default'::text,
    output_path text,
    output_size_bytes bigint DEFAULT 0,
    warnings_json text DEFAULT '[]'::text,
    error text,
    started_at double precision,
    finished_at double precision,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL
);
CREATE TABLE intel_word_metrics (
    id bigint NOT NULL,
    job_id text NOT NULL,
    section_name text NOT NULL,
    section_number bigint DEFAULT 0,
    render_type text DEFAULT 'section'::text NOT NULL,
    duration_ms bigint DEFAULT 0,
    element_count bigint DEFAULT 0,
    warnings_json text DEFAULT '[]'::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL
);
CREATE SEQUENCE intel_word_metrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE intel_word_metrics_id_seq OWNED BY intel_word_metrics.id;
CREATE TABLE llm_prices (
    id bigint NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    deployment_type text DEFAULT ''::text NOT NULL,
    input_per_m double precision DEFAULT 0 NOT NULL,
    cached_per_m double precision DEFAULT 0 NOT NULL,
    output_per_m double precision DEFAULT 0 NOT NULL,
    effective_from text NOT NULL,
    source text DEFAULT 'manual'::text NOT NULL
);
CREATE SEQUENCE llm_prices_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE llm_prices_id_seq OWNED BY llm_prices.id;
CREATE TABLE llm_settings (
    key text NOT NULL,
    value text NOT NULL
);
CREATE TABLE llm_usage (
    id bigint NOT NULL,
    ts double precision NOT NULL,
    org_id bigint,
    project_id bigint,
    stage text DEFAULT 'other'::text NOT NULL,
    user_id bigint,
    provider text NOT NULL,
    model text NOT NULL,
    deployment_type text DEFAULT ''::text NOT NULL,
    kind text NOT NULL,
    input_tokens bigint DEFAULT 0 NOT NULL,
    cached_input_tokens bigint DEFAULT 0 NOT NULL,
    output_tokens bigint DEFAULT 0 NOT NULL,
    total_tokens bigint DEFAULT 0 NOT NULL,
    requests bigint DEFAULT 1 NOT NULL,
    credits double precision DEFAULT 0 NOT NULL,
    latency_ms bigint DEFAULT 0 NOT NULL,
    cache_hit bigint DEFAULT 0 NOT NULL,
    error bigint DEFAULT 0 NOT NULL,
    cost_usd double precision DEFAULT 0 NOT NULL,
    sub_stage text DEFAULT ''::text NOT NULL,
    error_reason text DEFAULT ''::text NOT NULL
);
CREATE SEQUENCE llm_usage_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE llm_usage_id_seq OWNED BY llm_usage.id;
CREATE TABLE memory_items (
    id bigint NOT NULL,
    scope text NOT NULL,
    scope_id text NOT NULL,
    type text NOT NULL,
    key text NOT NULL,
    value_json text NOT NULL,
    hits bigint DEFAULT 0 NOT NULL,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL,
    expires_at double precision
);
CREATE SEQUENCE memory_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE memory_items_id_seq OWNED BY memory_items.id;
CREATE TABLE org_data_sources (
    id bigint NOT NULL,
    org_id bigint NOT NULL,
    source text NOT NULL,
    api_key text NOT NULL,
    status text DEFAULT 'ok'::text NOT NULL,
    expired_at double precision,
    last_error text,
    updated_at double precision NOT NULL,
    updated_by_user_id bigint,
    settings_json text DEFAULT '{}'::text NOT NULL,
    CONSTRAINT org_data_sources_source_check CHECK ((source = ANY (ARRAY['tavily'::text, 'serpapi'::text, 'firecrawl'::text]))),
    CONSTRAINT org_data_sources_status_check CHECK ((status = ANY (ARRAY['ok'::text, 'expired'::text, 'unverified'::text, 'quota'::text])))
);
CREATE SEQUENCE org_data_sources_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE org_data_sources_id_seq OWNED BY org_data_sources.id;
CREATE TABLE org_guardrails (
    id bigint NOT NULL,
    org_id bigint NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    active bigint DEFAULT 1 NOT NULL,
    updated_by bigint,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE org_guardrails_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE org_guardrails_id_seq OWNED BY org_guardrails.id;
CREATE TABLE org_llm_providers (
    id bigint NOT NULL,
    org_id bigint NOT NULL,
    name text NOT NULL,
    provider_type text NOT NULL,
    base_url text DEFAULT ''::text NOT NULL,
    model text NOT NULL,
    api_version text DEFAULT ''::text NOT NULL,
    api_key_enc text NOT NULL,
    key_hint text DEFAULT ''::text NOT NULL,
    is_default bigint DEFAULT 0 NOT NULL,
    status text DEFAULT 'untested'::text NOT NULL,
    last_error text DEFAULT ''::text NOT NULL,
    last_tested_at double precision,
    last_latency_ms bigint,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL,
    updated_by_user_id bigint
);
CREATE SEQUENCE org_llm_providers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE org_llm_providers_id_seq OWNED BY org_llm_providers.id;
CREATE TABLE org_llm_state (
    org_id bigint NOT NULL,
    acting_provider_id bigint,
    down_since double precision NOT NULL,
    failed_calls bigint DEFAULT 0 NOT NULL,
    notified text DEFAULT ''::text NOT NULL,
    paused bigint DEFAULT 0 NOT NULL,
    last_error text DEFAULT ''::text NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE org_llm_state_org_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE org_llm_state_org_id_seq OWNED BY org_llm_state.org_id;
CREATE TABLE org_subscriptions (
    id bigint NOT NULL,
    org_id bigint NOT NULL,
    plan_id bigint NOT NULL,
    status text NOT NULL,
    starts_at double precision,
    ends_at double precision,
    payment_ref text,
    reminders text DEFAULT ''::text NOT NULL,
    created_by bigint,
    created_at double precision NOT NULL
);
CREATE SEQUENCE org_subscriptions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE org_subscriptions_id_seq OWNED BY org_subscriptions.id;
CREATE TABLE organizations (
    id bigint NOT NULL,
    name text NOT NULL,
    background_image_url text,
    created_at double precision NOT NULL,
    archived_at double precision,
    platform_llm bigint DEFAULT 0 NOT NULL,
    logo_url text,
    procurement_name text,
    procurement_email text,
    procurement_phone text,
    address text,
    country text,
    pin_code text,
    allow_editorial_images bigint DEFAULT 0 NOT NULL
);
CREATE SEQUENCE organizations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE organizations_id_seq OWNED BY organizations.id;
CREATE TABLE password_resets (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    otp_hash text,
    otp_expires double precision,
    attempts bigint DEFAULT 0 NOT NULL,
    verified_at double precision,
    token_hash text,
    token_expires double precision,
    used_at double precision,
    created_at double precision NOT NULL
);
CREATE SEQUENCE password_resets_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE password_resets_id_seq OWNED BY password_resets.id;
CREATE TABLE pexels_images (
    query_key text NOT NULL,
    query_text text NOT NULL,
    image_url text,
    photographer text,
    source_url text,
    fetched_at double precision NOT NULL,
    video_url text
);
CREATE TABLE qc_configs (
    id bigint NOT NULL,
    report_id bigint NOT NULL,
    check_type text NOT NULL,
    enabled bigint DEFAULT 1,
    severity text DEFAULT 'medium'::text,
    parameters text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE qc_configs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE qc_configs_id_seq OWNED BY qc_configs.id;
CREATE TABLE qc_exports (
    id bigint NOT NULL,
    run_id bigint NOT NULL,
    file_name text NOT NULL,
    file_path text NOT NULL,
    format text DEFAULT 'xlsx'::text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE qc_exports_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE qc_exports_id_seq OWNED BY qc_exports.id;
CREATE TABLE qc_findings (
    id bigint NOT NULL,
    run_id bigint NOT NULL,
    report_id bigint NOT NULL,
    check_type text NOT NULL,
    row_number bigint,
    column_name text,
    severity text NOT NULL,
    message text NOT NULL,
    expected text,
    actual text,
    source_url text,
    analyst_action text,
    created_at double precision NOT NULL
);
CREATE SEQUENCE qc_findings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE qc_findings_id_seq OWNED BY qc_findings.id;
CREATE TABLE qc_reports (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    file_name text NOT NULL,
    file_path text NOT NULL,
    row_count bigint DEFAULT 0,
    column_count bigint DEFAULT 0,
    columns_json text,
    field_mapping text,
    parse_status text DEFAULT 'pending'::text,
    parse_error text,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE qc_reports_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE qc_reports_id_seq OWNED BY qc_reports.id;
CREATE TABLE qc_runs (
    id bigint NOT NULL,
    report_id bigint NOT NULL,
    status text DEFAULT 'pending'::text,
    total_rows bigint DEFAULT 0,
    total_checks bigint DEFAULT 0,
    total_findings bigint DEFAULT 0,
    score double precision,
    score_breakdown text,
    started_at double precision,
    completed_at double precision,
    created_at double precision NOT NULL
);
CREATE SEQUENCE qc_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE qc_runs_id_seq OWNED BY qc_runs.id;
CREATE TABLE qc_source_cache (
    id bigint NOT NULL,
    url text NOT NULL,
    status_code bigint,
    is_accessible bigint DEFAULT 1,
    is_paywalled bigint DEFAULT 0,
    extracted_headline text,
    extracted_date text,
    extracted_text text,
    fetch_error text,
    fetched_at double precision NOT NULL
);
CREATE SEQUENCE qc_source_cache_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE qc_source_cache_id_seq OWNED BY qc_source_cache.id;
CREATE TABLE research_article_fulltext (
    url text NOT NULL,
    status text NOT NULL,
    title text,
    blocks_json text,
    error text,
    fetched_at double precision NOT NULL,
    platform text,
    embed_url text,
    CONSTRAINT research_article_fulltext_status_check CHECK ((status = ANY (ARRAY['ok'::text, 'failed'::text, 'paywalled'::text])))
);
CREATE TABLE sessions (
    token text NOT NULL,
    user_id bigint NOT NULL,
    created_at double precision NOT NULL,
    expires_at double precision NOT NULL,
    active_org_id bigint
);
CREATE TABLE subscription_plans (
    id bigint NOT NULL,
    name text NOT NULL,
    max_users bigint NOT NULL,
    max_projects bigint NOT NULL,
    duration_months bigint DEFAULT 12 NOT NULL,
    price double precision DEFAULT 0 NOT NULL,
    currency text DEFAULT 'USD'::text NOT NULL,
    active bigint DEFAULT 1 NOT NULL,
    created_at double precision NOT NULL
);
CREATE SEQUENCE subscription_plans_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE subscription_plans_id_seq OWNED BY subscription_plans.id;
CREATE TABLE user_organizations (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    org_id bigint NOT NULL,
    added_at double precision NOT NULL
);
CREATE SEQUENCE user_organizations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE user_organizations_id_seq OWNED BY user_organizations.id;
CREATE TABLE user_token_limits (
    user_id bigint NOT NULL,
    monthly_tokens bigint,
    notified_period text DEFAULT ''::text NOT NULL,
    updated_at double precision NOT NULL
);
CREATE SEQUENCE user_token_limits_user_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE user_token_limits_user_id_seq OWNED BY user_token_limits.user_id;
CREATE TABLE users (
    id bigint NOT NULL,
    org_id bigint,
    email text NOT NULL,
    password_hash text NOT NULL,
    display_name text NOT NULL,
    avatar_url text,
    role text NOT NULL,
    must_change_password bigint DEFAULT 1 NOT NULL,
    failed_login_count bigint DEFAULT 0 NOT NULL,
    locked_until double precision,
    created_at double precision NOT NULL,
    archived_at double precision,
    CONSTRAINT users_role_check CHECK ((role = ANY (ARRAY['super_admin'::text, 'admin'::text, 'analyser'::text])))
);
CREATE SEQUENCE users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE users_id_seq OWNED BY users.id;
CREATE TABLE youtube_videos (
    query_key text NOT NULL,
    query_text text NOT NULL,
    video_id text,
    embed_url text,
    title text,
    thumbnail_url text,
    fetched_at double precision NOT NULL
);
ALTER TABLE ONLY agent_autopilots ALTER COLUMN project_id SET DEFAULT nextval('agent_autopilots_project_id_seq'::regclass);
ALTER TABLE ONLY agent_events ALTER COLUMN id SET DEFAULT nextval('agent_events_id_seq'::regclass);
ALTER TABLE ONLY agent_fixes ALTER COLUMN id SET DEFAULT nextval('agent_fixes_id_seq'::regclass);
ALTER TABLE ONLY agent_issues ALTER COLUMN id SET DEFAULT nextval('agent_issues_id_seq'::regclass);
ALTER TABLE ONLY agent_memory ALTER COLUMN id SET DEFAULT nextval('agent_memory_id_seq'::regclass);
ALTER TABLE ONLY deck_reference_decks ALTER COLUMN id SET DEFAULT nextval('deck_reference_decks_id_seq'::regclass);
ALTER TABLE ONLY deck_reference_slides ALTER COLUMN id SET DEFAULT nextval('deck_reference_slides_id_seq'::regclass);
ALTER TABLE ONLY intel_article_rq ALTER COLUMN id SET DEFAULT nextval('intel_article_rq_id_seq'::regclass);
ALTER TABLE ONLY intel_articles ALTER COLUMN id SET DEFAULT nextval('intel_articles_id_seq'::regclass);
ALTER TABLE ONLY intel_asset_library ALTER COLUMN id SET DEFAULT nextval('intel_asset_library_id_seq'::regclass);
ALTER TABLE ONLY intel_background_briefs ALTER COLUMN id SET DEFAULT nextval('intel_background_briefs_id_seq'::regclass);
ALTER TABLE ONLY intel_background_research ALTER COLUMN id SET DEFAULT nextval('intel_background_research_id_seq'::regclass);
ALTER TABLE ONLY intel_brief_section_edits ALTER COLUMN id SET DEFAULT nextval('intel_brief_section_edits_id_seq'::regclass);
ALTER TABLE ONLY intel_datasets ALTER COLUMN id SET DEFAULT nextval('intel_datasets_id_seq'::regclass);
ALTER TABLE ONLY intel_deliverable_runs ALTER COLUMN id SET DEFAULT nextval('intel_deliverable_runs_id_seq'::regclass);
ALTER TABLE ONLY intel_deliverable_sections ALTER COLUMN id SET DEFAULT nextval('intel_deliverable_sections_id_seq'::regclass);
ALTER TABLE ONLY intel_evidence ALTER COLUMN id SET DEFAULT nextval('intel_evidence_id_seq'::regclass);
ALTER TABLE ONLY intel_exclusions ALTER COLUMN id SET DEFAULT nextval('intel_exclusions_id_seq'::regclass);
ALTER TABLE ONLY intel_execution_logs ALTER COLUMN id SET DEFAULT nextval('intel_execution_logs_id_seq'::regclass);
ALTER TABLE ONLY intel_execution_runs ALTER COLUMN id SET DEFAULT nextval('intel_execution_runs_id_seq'::regclass);
ALTER TABLE ONLY intel_execution_units ALTER COLUMN id SET DEFAULT nextval('intel_execution_units_id_seq'::regclass);
ALTER TABLE ONLY intel_insight_audit ALTER COLUMN id SET DEFAULT nextval('intel_insight_audit_id_seq'::regclass);
ALTER TABLE ONLY intel_insight_evidence ALTER COLUMN id SET DEFAULT nextval('intel_insight_evidence_id_seq'::regclass);
ALTER TABLE ONLY intel_insights ALTER COLUMN id SET DEFAULT nextval('intel_insights_id_seq'::regclass);
ALTER TABLE ONLY intel_latest24h_refreshes ALTER COLUMN id SET DEFAULT nextval('intel_latest24h_refreshes_id_seq'::regclass);
ALTER TABLE ONLY intel_library_annotations ALTER COLUMN id SET DEFAULT nextval('intel_library_annotations_id_seq'::regclass);
ALTER TABLE ONLY intel_library_audit ALTER COLUMN id SET DEFAULT nextval('intel_library_audit_id_seq'::regclass);
ALTER TABLE ONLY intel_library_items ALTER COLUMN id SET DEFAULT nextval('intel_library_items_id_seq'::regclass);
ALTER TABLE ONLY intel_news_approvals ALTER COLUMN id SET DEFAULT nextval('intel_news_approvals_id_seq'::regclass);
ALTER TABLE ONLY intel_pc_audit ALTER COLUMN id SET DEFAULT nextval('intel_pc_audit_id_seq'::regclass);
ALTER TABLE ONLY intel_pc_presentations ALTER COLUMN id SET DEFAULT nextval('intel_pc_presentations_id_seq'::regclass);
ALTER TABLE ONLY intel_pc_slides ALTER COLUMN id SET DEFAULT nextval('intel_pc_slides_id_seq'::regclass);
ALTER TABLE ONLY intel_pipeline_cache ALTER COLUMN id SET DEFAULT nextval('intel_pipeline_cache_id_seq'::regclass);
ALTER TABLE ONLY intel_pipeline_logs ALTER COLUMN id SET DEFAULT nextval('intel_pipeline_logs_id_seq'::regclass);
ALTER TABLE ONLY intel_pipeline_metrics ALTER COLUMN id SET DEFAULT nextval('intel_pipeline_metrics_id_seq'::regclass);
ALTER TABLE ONLY intel_pipeline_stages ALTER COLUMN id SET DEFAULT nextval('intel_pipeline_stages_id_seq'::regclass);
ALTER TABLE ONLY intel_projects ALTER COLUMN id SET DEFAULT nextval('intel_projects_id_seq'::regclass);
ALTER TABLE ONLY intel_pub_approvals ALTER COLUMN id SET DEFAULT nextval('intel_pub_approvals_id_seq'::regclass);
ALTER TABLE ONLY intel_pub_audit ALTER COLUMN id SET DEFAULT nextval('intel_pub_audit_id_seq'::regclass);
ALTER TABLE ONLY intel_pub_diff_reports ALTER COLUMN id SET DEFAULT nextval('intel_pub_diff_reports_id_seq'::regclass);
ALTER TABLE ONLY intel_pub_downloads ALTER COLUMN id SET DEFAULT nextval('intel_pub_downloads_id_seq'::regclass);
ALTER TABLE ONLY intel_pub_packages ALTER COLUMN id SET DEFAULT nextval('intel_pub_packages_id_seq'::regclass);
ALTER TABLE ONLY intel_pub_validations ALTER COLUMN id SET DEFAULT nextval('intel_pub_validations_id_seq'::regclass);
ALTER TABLE ONLY intel_pub_versions ALTER COLUMN id SET DEFAULT nextval('intel_pub_versions_id_seq'::regclass);
ALTER TABLE ONLY intel_query_versions ALTER COLUMN id SET DEFAULT nextval('intel_query_versions_id_seq'::regclass);
ALTER TABLE ONLY intel_render_history ALTER COLUMN id SET DEFAULT nextval('intel_render_history_id_seq'::regclass);
ALTER TABLE ONLY intel_render_metrics ALTER COLUMN id SET DEFAULT nextval('intel_render_metrics_id_seq'::regclass);
ALTER TABLE ONLY intel_rendered_presentations ALTER COLUMN id SET DEFAULT nextval('intel_rendered_presentations_id_seq'::regclass);
ALTER TABLE ONLY intel_research_item_vectors ALTER COLUMN item_id SET DEFAULT nextval('intel_research_item_vectors_item_id_seq'::regclass);
ALTER TABLE ONLY intel_research_items ALTER COLUMN id SET DEFAULT nextval('intel_research_items_id_seq'::regclass);
ALTER TABLE ONLY intel_research_plans ALTER COLUMN id SET DEFAULT nextval('intel_research_plans_id_seq'::regclass);
ALTER TABLE ONLY intel_research_specifications ALTER COLUMN id SET DEFAULT nextval('intel_research_specifications_id_seq'::regclass);
ALTER TABLE ONLY intel_sample_evaluations ALTER COLUMN id SET DEFAULT nextval('intel_sample_evaluations_id_seq'::regclass);
ALTER TABLE ONLY intel_search_strategies ALTER COLUMN id SET DEFAULT nextval('intel_search_strategies_id_seq'::regclass);
ALTER TABLE ONLY intel_si_corrections ALTER COLUMN id SET DEFAULT nextval('intel_si_corrections_id_seq'::regclass);
ALTER TABLE ONLY intel_si_detected_projects ALTER COLUMN id SET DEFAULT nextval('intel_si_detected_projects_id_seq'::regclass);
ALTER TABLE ONLY intel_si_embeddings ALTER COLUMN id SET DEFAULT nextval('intel_si_embeddings_id_seq'::regclass);
ALTER TABLE ONLY intel_si_presentations ALTER COLUMN id SET DEFAULT nextval('intel_si_presentations_id_seq'::regclass);
ALTER TABLE ONLY intel_si_processing_logs ALTER COLUMN id SET DEFAULT nextval('intel_si_processing_logs_id_seq'::regclass);
ALTER TABLE ONLY intel_si_retrieval_history ALTER COLUMN id SET DEFAULT nextval('intel_si_retrieval_history_id_seq'::regclass);
ALTER TABLE ONLY intel_si_slides ALTER COLUMN id SET DEFAULT nextval('intel_si_slides_id_seq'::regclass);
ALTER TABLE ONLY intel_si_storyline_matches ALTER COLUMN id SET DEFAULT nextval('intel_si_storyline_matches_id_seq'::regclass);
ALTER TABLE ONLY intel_si_style_patterns ALTER COLUMN id SET DEFAULT nextval('intel_si_style_patterns_id_seq'::regclass);
ALTER TABLE ONLY intel_si_template_families ALTER COLUMN id SET DEFAULT nextval('intel_si_template_families_id_seq'::regclass);
ALTER TABLE ONLY intel_si_template_members ALTER COLUMN id SET DEFAULT nextval('intel_si_template_members_id_seq'::regclass);
ALTER TABLE ONLY intel_spec_audit ALTER COLUMN id SET DEFAULT nextval('intel_spec_audit_id_seq'::regclass);
ALTER TABLE ONLY intel_spec_clarifications ALTER COLUMN id SET DEFAULT nextval('intel_spec_clarifications_id_seq'::regclass);
ALTER TABLE ONLY intel_spec_section_approvals ALTER COLUMN id SET DEFAULT nextval('intel_spec_section_approvals_id_seq'::regclass);
ALTER TABLE ONLY intel_story_node_insights ALTER COLUMN id SET DEFAULT nextval('intel_story_node_insights_id_seq'::regclass);
ALTER TABLE ONLY intel_story_nodes ALTER COLUMN id SET DEFAULT nextval('intel_story_nodes_id_seq'::regclass);
ALTER TABLE ONLY intel_storyline_audit ALTER COLUMN id SET DEFAULT nextval('intel_storyline_audit_id_seq'::regclass);
ALTER TABLE ONLY intel_storylines ALTER COLUMN id SET DEFAULT nextval('intel_storylines_id_seq'::regclass);
ALTER TABLE ONLY intel_template_versions ALTER COLUMN id SET DEFAULT nextval('intel_template_versions_id_seq'::regclass);
ALTER TABLE ONLY intel_upload_files ALTER COLUMN id SET DEFAULT nextval('intel_upload_files_id_seq'::regclass);
ALTER TABLE ONLY intel_word_documents ALTER COLUMN id SET DEFAULT nextval('intel_word_documents_id_seq'::regclass);
ALTER TABLE ONLY intel_word_history ALTER COLUMN id SET DEFAULT nextval('intel_word_history_id_seq'::regclass);
ALTER TABLE ONLY intel_word_metrics ALTER COLUMN id SET DEFAULT nextval('intel_word_metrics_id_seq'::regclass);
ALTER TABLE ONLY llm_prices ALTER COLUMN id SET DEFAULT nextval('llm_prices_id_seq'::regclass);
ALTER TABLE ONLY llm_usage ALTER COLUMN id SET DEFAULT nextval('llm_usage_id_seq'::regclass);
ALTER TABLE ONLY memory_items ALTER COLUMN id SET DEFAULT nextval('memory_items_id_seq'::regclass);
ALTER TABLE ONLY org_data_sources ALTER COLUMN id SET DEFAULT nextval('org_data_sources_id_seq'::regclass);
ALTER TABLE ONLY org_guardrails ALTER COLUMN id SET DEFAULT nextval('org_guardrails_id_seq'::regclass);
ALTER TABLE ONLY org_llm_providers ALTER COLUMN id SET DEFAULT nextval('org_llm_providers_id_seq'::regclass);
ALTER TABLE ONLY org_llm_state ALTER COLUMN org_id SET DEFAULT nextval('org_llm_state_org_id_seq'::regclass);
ALTER TABLE ONLY org_subscriptions ALTER COLUMN id SET DEFAULT nextval('org_subscriptions_id_seq'::regclass);
ALTER TABLE ONLY organizations ALTER COLUMN id SET DEFAULT nextval('organizations_id_seq'::regclass);
ALTER TABLE ONLY password_resets ALTER COLUMN id SET DEFAULT nextval('password_resets_id_seq'::regclass);
ALTER TABLE ONLY qc_configs ALTER COLUMN id SET DEFAULT nextval('qc_configs_id_seq'::regclass);
ALTER TABLE ONLY qc_exports ALTER COLUMN id SET DEFAULT nextval('qc_exports_id_seq'::regclass);
ALTER TABLE ONLY qc_findings ALTER COLUMN id SET DEFAULT nextval('qc_findings_id_seq'::regclass);
ALTER TABLE ONLY qc_reports ALTER COLUMN id SET DEFAULT nextval('qc_reports_id_seq'::regclass);
ALTER TABLE ONLY qc_runs ALTER COLUMN id SET DEFAULT nextval('qc_runs_id_seq'::regclass);
ALTER TABLE ONLY qc_source_cache ALTER COLUMN id SET DEFAULT nextval('qc_source_cache_id_seq'::regclass);
ALTER TABLE ONLY subscription_plans ALTER COLUMN id SET DEFAULT nextval('subscription_plans_id_seq'::regclass);
ALTER TABLE ONLY user_organizations ALTER COLUMN id SET DEFAULT nextval('user_organizations_id_seq'::regclass);
ALTER TABLE ONLY user_token_limits ALTER COLUMN user_id SET DEFAULT nextval('user_token_limits_user_id_seq'::regclass);
ALTER TABLE ONLY users ALTER COLUMN id SET DEFAULT nextval('users_id_seq'::regclass);
ALTER TABLE ONLY agent_autopilots
    ADD CONSTRAINT agent_autopilots_pkey PRIMARY KEY (project_id);
ALTER TABLE ONLY agent_events
    ADD CONSTRAINT agent_events_pkey PRIMARY KEY (id);
ALTER TABLE ONLY agent_fixes
    ADD CONSTRAINT agent_fixes_pkey PRIMARY KEY (id);
ALTER TABLE ONLY agent_issues
    ADD CONSTRAINT agent_issues_pkey PRIMARY KEY (id);
ALTER TABLE ONLY agent_memory
    ADD CONSTRAINT agent_memory_pkey PRIMARY KEY (id);
ALTER TABLE ONLY agent_memory
    ADD CONSTRAINT agent_memory_project_id_kind_key_key UNIQUE (project_id, kind, key);
ALTER TABLE ONLY brand_logos
    ADD CONSTRAINT brand_logos_pkey PRIMARY KEY (brand_key);
ALTER TABLE ONLY deck_reference_decks
    ADD CONSTRAINT deck_reference_decks_path_key UNIQUE (path);
ALTER TABLE ONLY deck_reference_decks
    ADD CONSTRAINT deck_reference_decks_pkey PRIMARY KEY (id);
ALTER TABLE ONLY deck_reference_slides
    ADD CONSTRAINT deck_reference_slides_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_article_classifications
    ADD CONSTRAINT intel_article_classifications_pkey PRIMARY KEY (norm_url, field);
ALTER TABLE ONLY intel_article_rq
    ADD CONSTRAINT intel_article_rq_article_id_rq_id_key UNIQUE (article_id, rq_id);
ALTER TABLE ONLY intel_article_rq
    ADD CONSTRAINT intel_article_rq_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_articles
    ADD CONSTRAINT intel_articles_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_articles
    ADD CONSTRAINT intel_articles_project_id_norm_url_key UNIQUE (project_id, norm_url);
ALTER TABLE ONLY intel_asset_library
    ADD CONSTRAINT intel_asset_library_kind_key_key UNIQUE (kind, key);
ALTER TABLE ONLY intel_asset_library
    ADD CONSTRAINT intel_asset_library_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_assets
    ADD CONSTRAINT intel_assets_pkey PRIMARY KEY (kind, key);
ALTER TABLE ONLY intel_background_briefs
    ADD CONSTRAINT intel_background_briefs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_background_research
    ADD CONSTRAINT intel_background_research_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_brief_section_edits
    ADD CONSTRAINT intel_brief_section_edits_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_dataset_files
    ADD CONSTRAINT intel_dataset_files_pkey PRIMARY KEY (dataset_id);
ALTER TABLE ONLY intel_datasets
    ADD CONSTRAINT intel_datasets_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_deliverable_files
    ADD CONSTRAINT intel_deliverable_files_pkey PRIMARY KEY (run_id, name, part);
ALTER TABLE ONLY intel_deliverable_plans
    ADD CONSTRAINT intel_deliverable_plans_pkey PRIMARY KEY (project_id, rq_id);
ALTER TABLE ONLY intel_deliverable_runs
    ADD CONSTRAINT intel_deliverable_runs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_deliverable_sections
    ADD CONSTRAINT intel_deliverable_sections_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_evidence
    ADD CONSTRAINT intel_evidence_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_exclusions
    ADD CONSTRAINT intel_exclusions_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_execution_logs
    ADD CONSTRAINT intel_execution_logs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_execution_runs
    ADD CONSTRAINT intel_execution_runs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_execution_units
    ADD CONSTRAINT intel_execution_units_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_insight_audit
    ADD CONSTRAINT intel_insight_audit_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_insight_evidence
    ADD CONSTRAINT intel_insight_evidence_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_insights
    ADD CONSTRAINT intel_insights_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_jobs
    ADD CONSTRAINT intel_jobs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_latest24h_refreshes
    ADD CONSTRAINT intel_latest24h_refreshes_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_library_annotations
    ADD CONSTRAINT intel_library_annotations_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_library_audit
    ADD CONSTRAINT intel_library_audit_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_library_items
    ADD CONSTRAINT intel_library_items_evidence_id_key UNIQUE (evidence_id);
ALTER TABLE ONLY intel_library_items
    ADD CONSTRAINT intel_library_items_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_news_approvals
    ADD CONSTRAINT intel_news_approvals_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pc_audit
    ADD CONSTRAINT intel_pc_audit_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pc_presentations
    ADD CONSTRAINT intel_pc_presentations_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pc_slides
    ADD CONSTRAINT intel_pc_slides_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pipeline_cache
    ADD CONSTRAINT intel_pipeline_cache_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pipeline_logs
    ADD CONSTRAINT intel_pipeline_logs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pipeline_metrics
    ADD CONSTRAINT intel_pipeline_metrics_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pipeline_runs
    ADD CONSTRAINT intel_pipeline_runs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pipeline_stages
    ADD CONSTRAINT intel_pipeline_stages_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_projects
    ADD CONSTRAINT intel_projects_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pub_approvals
    ADD CONSTRAINT intel_pub_approvals_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pub_audit
    ADD CONSTRAINT intel_pub_audit_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pub_diff_reports
    ADD CONSTRAINT intel_pub_diff_reports_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pub_downloads
    ADD CONSTRAINT intel_pub_downloads_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pub_packages
    ADD CONSTRAINT intel_pub_packages_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pub_validations
    ADD CONSTRAINT intel_pub_validations_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_pub_versions
    ADD CONSTRAINT intel_pub_versions_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_query_versions
    ADD CONSTRAINT intel_query_versions_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_question_dimensions
    ADD CONSTRAINT intel_question_dimensions_pkey PRIMARY KEY (project_id, rq_id);
ALTER TABLE ONLY intel_question_tag_schemas
    ADD CONSTRAINT intel_question_tag_schemas_pkey PRIMARY KEY (project_id, rq_id);
ALTER TABLE ONLY intel_reference_decks
    ADD CONSTRAINT intel_reference_decks_pkey PRIMARY KEY (path);
ALTER TABLE ONLY intel_render_history
    ADD CONSTRAINT intel_render_history_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_render_jobs
    ADD CONSTRAINT intel_render_jobs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_render_metrics
    ADD CONSTRAINT intel_render_metrics_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_rendered_presentations
    ADD CONSTRAINT intel_rendered_presentations_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_research_item_vectors
    ADD CONSTRAINT intel_research_item_vectors_pkey PRIMARY KEY (item_id);
ALTER TABLE ONLY intel_research_items
    ADD CONSTRAINT intel_research_items_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_research_items
    ADD CONSTRAINT intel_research_items_project_id_url_key UNIQUE (project_id, url);
ALTER TABLE ONLY intel_research_plans
    ADD CONSTRAINT intel_research_plans_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_research_specifications
    ADD CONSTRAINT intel_research_specifications_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_sample_evaluations
    ADD CONSTRAINT intel_sample_evaluations_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_search_strategies
    ADD CONSTRAINT intel_search_strategies_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_si_corrections
    ADD CONSTRAINT intel_si_corrections_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_si_detected_projects
    ADD CONSTRAINT intel_si_detected_projects_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_si_embeddings
    ADD CONSTRAINT intel_si_embeddings_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_si_embeddings
    ADD CONSTRAINT intel_si_embeddings_slide_id_key UNIQUE (slide_id);
ALTER TABLE ONLY intel_si_presentations
    ADD CONSTRAINT intel_si_presentations_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_si_processing_logs
    ADD CONSTRAINT intel_si_processing_logs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_si_retrieval_history
    ADD CONSTRAINT intel_si_retrieval_history_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_si_slides
    ADD CONSTRAINT intel_si_slides_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_si_storyline_matches
    ADD CONSTRAINT intel_si_storyline_matches_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_si_style_patterns
    ADD CONSTRAINT intel_si_style_patterns_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_si_template_families
    ADD CONSTRAINT intel_si_template_families_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_si_template_members
    ADD CONSTRAINT intel_si_template_members_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_spec_audit
    ADD CONSTRAINT intel_spec_audit_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_spec_clarifications
    ADD CONSTRAINT intel_spec_clarifications_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_spec_section_approvals
    ADD CONSTRAINT intel_spec_section_approvals_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_story_node_insights
    ADD CONSTRAINT intel_story_node_insights_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_story_nodes
    ADD CONSTRAINT intel_story_nodes_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_storyline_audit
    ADD CONSTRAINT intel_storyline_audit_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_storylines
    ADD CONSTRAINT intel_storylines_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_template_versions
    ADD CONSTRAINT intel_template_versions_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_theme_titles
    ADD CONSTRAINT intel_theme_titles_pkey PRIMARY KEY (project_id, label_key);
ALTER TABLE ONLY intel_themes
    ADD CONSTRAINT intel_themes_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_upload_files
    ADD CONSTRAINT intel_upload_files_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_word_documents
    ADD CONSTRAINT intel_word_documents_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_word_history
    ADD CONSTRAINT intel_word_history_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_word_jobs
    ADD CONSTRAINT intel_word_jobs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY intel_word_metrics
    ADD CONSTRAINT intel_word_metrics_pkey PRIMARY KEY (id);
ALTER TABLE ONLY llm_prices
    ADD CONSTRAINT llm_prices_pkey PRIMARY KEY (id);
ALTER TABLE ONLY llm_prices
    ADD CONSTRAINT llm_prices_provider_model_deployment_type_effective_from_key UNIQUE (provider, model, deployment_type, effective_from);
ALTER TABLE ONLY llm_settings
    ADD CONSTRAINT llm_settings_pkey PRIMARY KEY (key);
ALTER TABLE ONLY llm_usage
    ADD CONSTRAINT llm_usage_pkey PRIMARY KEY (id);
ALTER TABLE ONLY memory_items
    ADD CONSTRAINT memory_items_pkey PRIMARY KEY (id);
ALTER TABLE ONLY memory_items
    ADD CONSTRAINT memory_items_scope_scope_id_type_key_key UNIQUE (scope, scope_id, type, key);
ALTER TABLE ONLY org_data_sources
    ADD CONSTRAINT org_data_sources_org_id_source_key UNIQUE (org_id, source);
ALTER TABLE ONLY org_data_sources
    ADD CONSTRAINT org_data_sources_pkey PRIMARY KEY (id);
ALTER TABLE ONLY org_guardrails
    ADD CONSTRAINT org_guardrails_pkey PRIMARY KEY (id);
ALTER TABLE ONLY org_llm_providers
    ADD CONSTRAINT org_llm_providers_pkey PRIMARY KEY (id);
ALTER TABLE ONLY org_llm_state
    ADD CONSTRAINT org_llm_state_pkey PRIMARY KEY (org_id);
ALTER TABLE ONLY org_subscriptions
    ADD CONSTRAINT org_subscriptions_pkey PRIMARY KEY (id);
ALTER TABLE ONLY organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (id);
ALTER TABLE ONLY password_resets
    ADD CONSTRAINT password_resets_pkey PRIMARY KEY (id);
ALTER TABLE ONLY pexels_images
    ADD CONSTRAINT pexels_images_pkey PRIMARY KEY (query_key);
ALTER TABLE ONLY qc_configs
    ADD CONSTRAINT qc_configs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY qc_exports
    ADD CONSTRAINT qc_exports_pkey PRIMARY KEY (id);
ALTER TABLE ONLY qc_findings
    ADD CONSTRAINT qc_findings_pkey PRIMARY KEY (id);
ALTER TABLE ONLY qc_reports
    ADD CONSTRAINT qc_reports_pkey PRIMARY KEY (id);
ALTER TABLE ONLY qc_runs
    ADD CONSTRAINT qc_runs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY qc_source_cache
    ADD CONSTRAINT qc_source_cache_pkey PRIMARY KEY (id);
ALTER TABLE ONLY qc_source_cache
    ADD CONSTRAINT qc_source_cache_url_key UNIQUE (url);
ALTER TABLE ONLY research_article_fulltext
    ADD CONSTRAINT research_article_fulltext_pkey PRIMARY KEY (url);
ALTER TABLE ONLY sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (token);
ALTER TABLE ONLY subscription_plans
    ADD CONSTRAINT subscription_plans_pkey PRIMARY KEY (id);
ALTER TABLE ONLY user_organizations
    ADD CONSTRAINT user_organizations_pkey PRIMARY KEY (id);
ALTER TABLE ONLY user_organizations
    ADD CONSTRAINT user_organizations_user_id_org_id_key UNIQUE (user_id, org_id);
ALTER TABLE ONLY user_token_limits
    ADD CONSTRAINT user_token_limits_pkey PRIMARY KEY (user_id);
ALTER TABLE ONLY users
    ADD CONSTRAINT users_email_key UNIQUE (email);
ALTER TABLE ONLY users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);
ALTER TABLE ONLY youtube_videos
    ADD CONSTRAINT youtube_videos_pkey PRIMARY KEY (query_key);
CREATE INDEX idx_agent_events_project ON agent_events USING btree (project_id, id);
CREATE INDEX idx_agent_issues_fp ON agent_issues USING btree (fingerprint, status);
CREATE INDEX idx_article_rq_project_rq ON intel_article_rq USING btree (project_id, rq_id, status);
CREATE INDEX idx_articles_project_channel ON intel_articles USING btree (project_id, channel);
CREATE INDEX idx_asset_library_kind_brand ON intel_asset_library USING btree (kind, brand);
CREATE INDEX idx_brief_edit_brief ON intel_brief_section_edits USING btree (brief_id);
CREATE INDEX idx_brief_project ON intel_background_briefs USING btree (project_id);
CREATE INDEX idx_brief_research ON intel_background_briefs USING btree (research_id);
CREATE INDEX idx_datasets_project ON intel_datasets USING btree (project_id);
CREATE INDEX idx_deck_ref_slides_type ON deck_reference_slides USING btree (type);
CREATE INDEX idx_deliv_runs_project ON intel_deliverable_runs USING btree (project_id);
CREATE INDEX idx_deliv_sections_run ON intel_deliverable_sections USING btree (run_id);
CREATE INDEX idx_deliverable_files_project ON intel_deliverable_files USING btree (project_id);
CREATE INDEX idx_intel_bg_project ON intel_background_research USING btree (project_id);
CREATE INDEX idx_intel_el_run ON intel_execution_logs USING btree (run_id);
CREATE INDEX idx_intel_er_project ON intel_execution_runs USING btree (project_id);
CREATE INDEX idx_intel_eu_run ON intel_execution_units USING btree (run_id);
CREATE INDEX idx_intel_ev_run ON intel_evidence USING btree (run_id);
CREATE INDEX idx_intel_ev_unit ON intel_evidence USING btree (unit_id);
CREATE INDEX idx_intel_exclusions_org ON intel_exclusions USING btree (org_id);
CREATE INDEX idx_intel_execution_runs_plan_id ON intel_execution_runs USING btree (plan_id);
CREATE INDEX idx_intel_ia_insight ON intel_insight_audit USING btree (insight_id);
CREATE INDEX idx_intel_ie_insight ON intel_insight_evidence USING btree (insight_id);
CREATE INDEX idx_intel_ie_item ON intel_insight_evidence USING btree (library_item_id);
CREATE INDEX idx_intel_ins_objective ON intel_insights USING btree (objective_id);
CREATE INDEX idx_intel_ins_project ON intel_insights USING btree (project_id);
CREATE INDEX idx_intel_ins_status ON intel_insights USING btree (status);
CREATE INDEX idx_intel_ins_type ON intel_insights USING btree (insight_type);
CREATE INDEX idx_intel_jobs_project ON intel_jobs USING btree (project_id);
CREATE INDEX idx_intel_jobs_status ON intel_jobs USING btree (status);
CREATE INDEX idx_intel_la_item ON intel_library_annotations USING btree (library_item_id);
CREATE INDEX idx_intel_lau_item ON intel_library_audit USING btree (library_item_id);
CREATE INDEX idx_intel_li_canonical ON intel_library_items USING btree (canonical_id);
CREATE INDEX idx_intel_li_evidence ON intel_library_items USING btree (evidence_id);
CREATE INDEX idx_intel_li_group ON intel_library_items USING btree (duplicate_group);
CREATE INDEX idx_intel_li_project ON intel_library_items USING btree (project_id);
CREATE INDEX idx_intel_li_status ON intel_library_items USING btree (review_status);
CREATE INDEX idx_intel_news_approvals_research_id ON intel_news_approvals USING btree (research_id);
CREATE INDEX idx_intel_pub_approvals_version_id ON intel_pub_approvals USING btree (version_id);
CREATE INDEX idx_intel_pub_diff_reports_project_id ON intel_pub_diff_reports USING btree (project_id);
CREATE INDEX idx_intel_pub_downloads_package_id ON intel_pub_downloads USING btree (package_id);
CREATE INDEX idx_intel_pub_packages_validation_id ON intel_pub_packages USING btree (validation_id);
CREATE INDEX idx_intel_pub_packages_version_id ON intel_pub_packages USING btree (version_id);
CREATE INDEX idx_intel_query_versions_strategy_id ON intel_query_versions USING btree (strategy_id);
CREATE INDEX idx_intel_rp_project ON intel_research_plans USING btree (project_id);
CREATE INDEX idx_intel_sample_evaluations_project_id ON intel_sample_evaluations USING btree (project_id);
CREATE INDEX idx_intel_sample_evaluations_strategy_id ON intel_sample_evaluations USING btree (strategy_id);
CREATE INDEX idx_intel_si_storyline_matches_slide_id ON intel_si_storyline_matches USING btree (slide_id);
CREATE INDEX idx_intel_sl_project ON intel_storylines USING btree (project_id);
CREATE INDEX idx_intel_sl_status ON intel_storylines USING btree (status);
CREATE INDEX idx_intel_sla_storyline ON intel_storyline_audit USING btree (storyline_id);
CREATE INDEX idx_intel_sn_order ON intel_story_nodes USING btree (storyline_id, order_position);
CREATE INDEX idx_intel_sn_storyline ON intel_story_nodes USING btree (storyline_id);
CREATE INDEX idx_intel_sni_insight ON intel_story_node_insights USING btree (insight_id);
CREATE INDEX idx_intel_sni_node ON intel_story_node_insights USING btree (node_id);
CREATE INDEX idx_intel_ss_project ON intel_search_strategies USING btree (project_id);
CREATE INDEX idx_latest24h_project ON intel_latest24h_refreshes USING btree (project_id, id);
CREATE INDEX idx_llm_usage_org_ts ON llm_usage USING btree (org_id, ts);
CREATE INDEX idx_llm_usage_project_ts ON llm_usage USING btree (project_id, ts);
CREATE INDEX idx_llm_usage_ts ON llm_usage USING btree (ts);
CREATE INDEX idx_memory_items_lookup ON memory_items USING btree (scope, scope_id, type, updated_at);
CREATE INDEX idx_org_guardrails_org ON org_guardrails USING btree (org_id);
CREATE INDEX idx_org_llm_providers_org ON org_llm_providers USING btree (org_id);
CREATE INDEX idx_org_subscriptions_org ON org_subscriptions USING btree (org_id);
CREATE INDEX idx_password_resets_token ON password_resets USING btree (token_hash);
CREATE INDEX idx_password_resets_user ON password_resets USING btree (user_id);
CREATE INDEX idx_pc_audit_pres ON intel_pc_audit USING btree (presentation_id);
CREATE INDEX idx_pc_pres_project ON intel_pc_presentations USING btree (project_id);
CREATE INDEX idx_pc_pres_status ON intel_pc_presentations USING btree (status);
CREATE INDEX idx_pc_pres_storyline ON intel_pc_presentations USING btree (storyline_id);
CREATE INDEX idx_pc_slides_node ON intel_pc_slides USING btree (node_id);
CREATE INDEX idx_pc_slides_pres ON intel_pc_slides USING btree (presentation_id);
CREATE INDEX idx_pc_slides_purpose ON intel_pc_slides USING btree (slide_purpose);
CREATE INDEX idx_pc_slides_status ON intel_pc_slides USING btree (status);
CREATE INDEX idx_plc_hash ON intel_pipeline_cache USING btree (input_hash);
CREATE INDEX idx_plc_project ON intel_pipeline_cache USING btree (project_id);
CREATE INDEX idx_plc_stage ON intel_pipeline_cache USING btree (stage_id);
CREATE INDEX idx_pll_run ON intel_pipeline_logs USING btree (run_id);
CREATE INDEX idx_plm_project ON intel_pipeline_metrics USING btree (project_id);
CREATE INDEX idx_plm_run ON intel_pipeline_metrics USING btree (run_id);
CREATE INDEX idx_plr_project ON intel_pipeline_runs USING btree (project_id);
CREATE INDEX idx_plr_status ON intel_pipeline_runs USING btree (status);
CREATE INDEX idx_pls_run ON intel_pipeline_stages USING btree (run_id);
CREATE INDEX idx_pls_stage ON intel_pipeline_stages USING btree (stage_id);
CREATE INDEX idx_pub_app_proj ON intel_pub_approvals USING btree (project_id);
CREATE INDEX idx_pub_aud_pres ON intel_pub_audit USING btree (presentation_id);
CREATE INDEX idx_pub_aud_proj ON intel_pub_audit USING btree (project_id);
CREATE INDEX idx_pub_diff_val ON intel_pub_diff_reports USING btree (validation_id);
CREATE INDEX idx_pub_dl_proj ON intel_pub_downloads USING btree (project_id);
CREATE INDEX idx_pub_pkg_proj ON intel_pub_packages USING btree (project_id);
CREATE INDEX idx_pub_val_pres ON intel_pub_validations USING btree (presentation_id);
CREATE INDEX idx_pub_val_proj ON intel_pub_validations USING btree (project_id);
CREATE INDEX idx_pub_ver_pres ON intel_pub_versions USING btree (presentation_id);
CREATE INDEX idx_pub_ver_proj ON intel_pub_versions USING btree (project_id);
CREATE INDEX idx_qc_configs_report_id ON qc_configs USING btree (report_id);
CREATE INDEX idx_qc_exports_run_id ON qc_exports USING btree (run_id);
CREATE INDEX idx_qc_findings_report_id ON qc_findings USING btree (report_id);
CREATE INDEX idx_qc_findings_run_id ON qc_findings USING btree (run_id);
CREATE INDEX idx_qc_reports_project_id ON qc_reports USING btree (project_id);
CREATE INDEX idx_qc_runs_report_id ON qc_runs USING btree (report_id);
CREATE INDEX idx_research_items_project ON intel_research_items USING btree (project_id);
CREATE INDEX idx_research_items_project_date ON intel_research_items USING btree (project_id, published_date);
CREATE INDEX idx_rh_job ON intel_render_history USING btree (job_id);
CREATE INDEX idx_rh_pres ON intel_render_history USING btree (presentation_id);
CREATE INDEX idx_rj_pres ON intel_render_jobs USING btree (presentation_id);
CREATE INDEX idx_rj_status ON intel_render_jobs USING btree (status);
CREATE INDEX idx_rm_job ON intel_render_metrics USING btree (job_id);
CREATE INDEX idx_rm_slide ON intel_render_metrics USING btree (slide_id);
CREATE INDEX idx_rp_job ON intel_rendered_presentations USING btree (job_id);
CREATE INDEX idx_rp_pres ON intel_rendered_presentations USING btree (presentation_id);
CREATE INDEX idx_rspec_approval ON intel_research_specifications USING btree (approval_status);
CREATE INDEX idx_rspec_project ON intel_research_specifications USING btree (project_id);
CREATE INDEX idx_rspec_status ON intel_research_specifications USING btree (status);
CREATE INDEX idx_sessions_user ON sessions USING btree (user_id);
CREATE INDEX idx_si_corr_slide ON intel_si_corrections USING btree (slide_id);
CREATE INDEX idx_si_dp_pres ON intel_si_detected_projects USING btree (presentation_id);
CREATE INDEX idx_si_emb_slide ON intel_si_embeddings USING btree (slide_id);
CREATE INDEX idx_si_pl_pres ON intel_si_processing_logs USING btree (presentation_id);
CREATE INDEX idx_si_slides_client ON intel_si_slides USING btree (client);
CREATE INDEX idx_si_slides_layout ON intel_si_slides USING btree (layout_type);
CREATE INDEX idx_si_slides_pres ON intel_si_slides USING btree (presentation_id);
CREATE INDEX idx_si_slides_project ON intel_si_slides USING btree (detected_project_id);
CREATE INDEX idx_si_slides_purpose ON intel_si_slides USING btree (slide_purpose);
CREATE INDEX idx_si_slides_status ON intel_si_slides USING btree (status);
CREATE INDEX idx_si_sm_node ON intel_si_storyline_matches USING btree (node_id);
CREATE INDEX idx_si_sm_storyline ON intel_si_storyline_matches USING btree (storyline_id);
CREATE INDEX idx_si_sp_pres ON intel_si_style_patterns USING btree (presentation_id);
CREATE INDEX idx_si_tm_family ON intel_si_template_members USING btree (family_id);
CREATE INDEX idx_si_tm_slide ON intel_si_template_members USING btree (slide_id);
CREATE INDEX idx_spec_audit_spec ON intel_spec_audit USING btree (spec_id);
CREATE INDEX idx_spec_clar_blocking ON intel_spec_clarifications USING btree (spec_id, is_blocking);
CREATE INDEX idx_spec_clar_spec ON intel_spec_clarifications USING btree (spec_id);
CREATE INDEX idx_spec_sa_key ON intel_spec_section_approvals USING btree (spec_id, section_key);
CREATE INDEX idx_spec_sa_spec ON intel_spec_section_approvals USING btree (spec_id);
CREATE INDEX idx_tv_theme ON intel_template_versions USING btree (theme_id);
CREATE INDEX idx_wd_job ON intel_word_documents USING btree (job_id);
CREATE INDEX idx_wd_pres ON intel_word_documents USING btree (presentation_id);
CREATE INDEX idx_wh_pres ON intel_word_history USING btree (presentation_id);
CREATE INDEX idx_wj_pres ON intel_word_jobs USING btree (presentation_id);
CREATE INDEX idx_wj_status ON intel_word_jobs USING btree (status);
CREATE INDEX idx_wm_job ON intel_word_metrics USING btree (job_id);
CREATE UNIQUE INDEX ux_organizations_name ON organizations USING btree (lower(TRIM(BOTH FROM name)));

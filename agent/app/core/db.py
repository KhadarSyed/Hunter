"""Shared SQLite connection, schema bootstrap, and QC source-cache helpers.

Every domains/<name>/repository.py opens connections through _conn() here.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Optional

from . import config

logger = logging.getLogger(__name__)

INTELLIGENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS intel_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS intel_jobs (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    progress_pct INTEGER DEFAULT 0,
    progress_message TEXT DEFAULT '',
    result_json TEXT,
    error TEXT,
    started_at REAL,
    finished_at REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES intel_projects(id)
);

CREATE TABLE IF NOT EXISTS intel_background_research (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft',
    research_json TEXT NOT NULL,
    llm_output_json TEXT,
    approval_status TEXT DEFAULT 'pending',
    approved_by TEXT,
    approved_at REAL,
    notes TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES intel_projects(id)
);

CREATE TABLE IF NOT EXISTS intel_search_strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft',
    strategy_json TEXT NOT NULL,
    approval_status TEXT DEFAULT 'pending',
    approved_by TEXT,
    approved_at REAL,
    notes TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES intel_projects(id)
);

CREATE TABLE IF NOT EXISTS intel_query_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER NOT NULL,
    version_label TEXT NOT NULL,
    query_type TEXT NOT NULL,
    query_text TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at REAL NOT NULL,
    FOREIGN KEY (strategy_id) REFERENCES intel_search_strategies(id)
);

CREATE TABLE IF NOT EXISTS intel_sample_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    strategy_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    evaluation_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES intel_projects(id),
    FOREIGN KEY (strategy_id) REFERENCES intel_search_strategies(id)
);

CREATE TABLE IF NOT EXISTS intel_news_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    research_id INTEGER NOT NULL,
    item_index INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    notes TEXT,
    updated_at REAL NOT NULL,
    FOREIGN KEY (research_id) REFERENCES intel_background_research(id)
);

CREATE TABLE IF NOT EXISTS intel_research_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft',
    plan_json TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'llm',
    approval_status TEXT DEFAULT 'pending',
    approved_by TEXT,
    approved_at REAL,
    notes TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES intel_projects(id)
);

CREATE TABLE IF NOT EXISTS intel_execution_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    plan_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    total_units INTEGER NOT NULL DEFAULT 0,
    completed_units INTEGER NOT NULL DEFAULT 0,
    failed_units INTEGER NOT NULL DEFAULT 0,
    skipped_units INTEGER NOT NULL DEFAULT 0,
    total_evidence INTEGER NOT NULL DEFAULT 0,
    started_at REAL,
    finished_at REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES intel_projects(id),
    FOREIGN KEY (plan_id) REFERENCES intel_research_plans(id)
);

CREATE TABLE IF NOT EXISTS intel_execution_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    unit_id TEXT NOT NULL,
    objective_id TEXT NOT NULL,
    method TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    progress_pct INTEGER DEFAULT 0,
    records_processed INTEGER DEFAULT 0,
    evidence_count INTEGER DEFAULT 0,
    error TEXT,
    result_json TEXT,
    started_at REAL,
    finished_at REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES intel_execution_runs(id)
);

CREATE TABLE IF NOT EXISTS intel_execution_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    unit_id TEXT,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES intel_execution_runs(id)
);

CREATE TABLE IF NOT EXISTS intel_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    unit_id TEXT NOT NULL,
    objective_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    platform TEXT,
    source TEXT,
    date TEXT,
    text_excerpt TEXT,
    metrics_json TEXT,
    confidence TEXT DEFAULT 'medium',
    method TEXT NOT NULL,
    rationale TEXT,
    dataset TEXT DEFAULT 'meltwater_export',
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES intel_execution_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_intel_jobs_project ON intel_jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_intel_jobs_status ON intel_jobs(status);
CREATE INDEX IF NOT EXISTS idx_intel_bg_project ON intel_background_research(project_id);
CREATE INDEX IF NOT EXISTS idx_intel_ss_project ON intel_search_strategies(project_id);
CREATE INDEX IF NOT EXISTS idx_intel_rp_project ON intel_research_plans(project_id);
CREATE INDEX IF NOT EXISTS idx_intel_er_project ON intel_execution_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_intel_eu_run ON intel_execution_units(run_id);
CREATE INDEX IF NOT EXISTS idx_intel_ev_run ON intel_evidence(run_id);
CREATE INDEX IF NOT EXISTS idx_intel_ev_unit ON intel_evidence(unit_id);
CREATE INDEX IF NOT EXISTS idx_intel_el_run ON intel_execution_logs(run_id);

CREATE TABLE IF NOT EXISTS intel_library_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    evidence_id INTEGER NOT NULL UNIQUE,
    review_status TEXT NOT NULL DEFAULT 'unreviewed',
    quality_score REAL,
    quality_components_json TEXT,
    relevance_score REAL,
    is_representative INTEGER DEFAULT 0,
    is_high_value INTEGER DEFAULT 0,
    canonical_id INTEGER,
    duplicate_group TEXT,
    objective_id TEXT,
    unit_id TEXT,
    reviewed_by TEXT,
    reviewed_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES intel_projects(id),
    FOREIGN KEY (evidence_id) REFERENCES intel_evidence(id),
    FOREIGN KEY (canonical_id) REFERENCES intel_library_items(id)
);

CREATE TABLE IF NOT EXISTS intel_library_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_item_id INTEGER NOT NULL,
    author TEXT NOT NULL DEFAULT 'analyst',
    note TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (library_item_id) REFERENCES intel_library_items(id)
);

CREATE TABLE IF NOT EXISTS intel_library_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_item_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    actor TEXT NOT NULL DEFAULT 'analyst',
    created_at REAL NOT NULL,
    FOREIGN KEY (library_item_id) REFERENCES intel_library_items(id)
);

CREATE INDEX IF NOT EXISTS idx_intel_li_project ON intel_library_items(project_id);
CREATE INDEX IF NOT EXISTS idx_intel_li_evidence ON intel_library_items(evidence_id);
CREATE INDEX IF NOT EXISTS idx_intel_li_status ON intel_library_items(review_status);
CREATE INDEX IF NOT EXISTS idx_intel_li_canonical ON intel_library_items(canonical_id);
CREATE INDEX IF NOT EXISTS idx_intel_li_group ON intel_library_items(duplicate_group);
CREATE INDEX IF NOT EXISTS idx_intel_la_item ON intel_library_annotations(library_item_id);
CREATE INDEX IF NOT EXISTS idx_intel_lau_item ON intel_library_audit(library_item_id);

CREATE TABLE IF NOT EXISTS intel_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    objective_id TEXT NOT NULL,
    insight_type TEXT NOT NULL DEFAULT 'behavioural',
    title TEXT NOT NULL,
    executive_summary TEXT,
    observation TEXT,
    interpretation TEXT,
    business_impact TEXT,
    confidence_score REAL DEFAULT 0.5,
    confidence_rationale TEXT,
    evidence_count INTEGER DEFAULT 0,
    platforms_represented TEXT,
    date_coverage TEXT,
    contradictory_evidence TEXT,
    limitations TEXT,
    recommended_visualisation TEXT,
    analyst_notes TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    reviewed_by TEXT,
    reviewed_at REAL,
    generation_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES intel_projects(id)
);

CREATE TABLE IF NOT EXISTS intel_insight_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_id INTEGER NOT NULL,
    library_item_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'supporting',
    created_at REAL NOT NULL,
    FOREIGN KEY (insight_id) REFERENCES intel_insights(id),
    FOREIGN KEY (library_item_id) REFERENCES intel_library_items(id)
);

CREATE TABLE IF NOT EXISTS intel_insight_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    actor TEXT NOT NULL DEFAULT 'analyst',
    created_at REAL NOT NULL,
    FOREIGN KEY (insight_id) REFERENCES intel_insights(id)
);

CREATE INDEX IF NOT EXISTS idx_intel_ins_project ON intel_insights(project_id);
CREATE INDEX IF NOT EXISTS idx_intel_ins_objective ON intel_insights(objective_id);
CREATE INDEX IF NOT EXISTS idx_intel_ins_status ON intel_insights(status);
CREATE INDEX IF NOT EXISTS idx_intel_ins_type ON intel_insights(insight_type);
CREATE INDEX IF NOT EXISTS idx_intel_ie_insight ON intel_insight_evidence(insight_id);
CREATE INDEX IF NOT EXISTS idx_intel_ie_item ON intel_insight_evidence(library_item_id);
CREATE INDEX IF NOT EXISTS idx_intel_ia_insight ON intel_insight_audit(insight_id);

CREATE TABLE IF NOT EXISTS intel_storylines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    narrative_pattern TEXT NOT NULL DEFAULT 'executive_briefing',
    title TEXT NOT NULL,
    executive_summary TEXT,
    total_duration_minutes REAL DEFAULT 0,
    node_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',
    generated_by TEXT DEFAULT 'system',
    approved_by TEXT,
    approved_at REAL,
    generation_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES intel_projects(id)
);

CREATE TABLE IF NOT EXISTS intel_story_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    storyline_id INTEGER NOT NULL,
    section_type TEXT NOT NULL,
    title TEXT NOT NULL,
    purpose TEXT,
    narrative_summary TEXT,
    suggested_visual TEXT DEFAULT 'table',
    priority TEXT DEFAULT 'medium',
    estimated_duration_minutes REAL DEFAULT 2.0,
    confidence_score REAL DEFAULT 0.5,
    transition_text TEXT,
    is_key_message INTEGER DEFAULT 0,
    is_locked INTEGER DEFAULT 0,
    order_position INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',
    reviewed_by TEXT,
    reviewed_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (storyline_id) REFERENCES intel_storylines(id)
);

CREATE TABLE IF NOT EXISTS intel_story_node_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL,
    insight_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'supporting',
    created_at REAL NOT NULL,
    FOREIGN KEY (node_id) REFERENCES intel_story_nodes(id),
    FOREIGN KEY (insight_id) REFERENCES intel_insights(id)
);

CREATE TABLE IF NOT EXISTS intel_storyline_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    storyline_id INTEGER NOT NULL,
    node_id INTEGER,
    action TEXT NOT NULL,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    actor TEXT NOT NULL DEFAULT 'analyst',
    created_at REAL NOT NULL,
    FOREIGN KEY (storyline_id) REFERENCES intel_storylines(id)
);

CREATE INDEX IF NOT EXISTS idx_intel_sl_project ON intel_storylines(project_id);
CREATE INDEX IF NOT EXISTS idx_intel_sl_status ON intel_storylines(status);
CREATE INDEX IF NOT EXISTS idx_intel_sn_storyline ON intel_story_nodes(storyline_id);
CREATE INDEX IF NOT EXISTS idx_intel_sn_order ON intel_story_nodes(storyline_id, order_position);
CREATE INDEX IF NOT EXISTS idx_intel_sni_node ON intel_story_node_insights(node_id);
CREATE INDEX IF NOT EXISTS idx_intel_sni_insight ON intel_story_node_insights(insight_id);
CREATE INDEX IF NOT EXISTS idx_intel_sla_storyline ON intel_storyline_audit(storyline_id);

CREATE TABLE IF NOT EXISTS intel_si_presentations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER NOT NULL DEFAULT 0,
    file_hash TEXT,
    slide_count INTEGER DEFAULT 0,
    processed_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    started_at REAL,
    completed_at REAL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS intel_si_slides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    presentation_id INTEGER NOT NULL,
    slide_number INTEGER NOT NULL,
    all_text TEXT,
    title_text TEXT,
    body_text TEXT,
    footer_text TEXT,
    notes_text TEXT,
    shape_count INTEGER DEFAULT 0,
    text_shape_count INTEGER DEFAULT 0,
    chart_count INTEGER DEFAULT 0,
    table_count INTEGER DEFAULT 0,
    image_count INTEGER DEFAULT 0,
    has_chart INTEGER DEFAULT 0,
    has_table INTEGER DEFAULT 0,
    has_image INTEGER DEFAULT 0,
    thumbnail_b64 TEXT,
    slide_purpose TEXT,
    layout_type TEXT,
    visual_type TEXT,
    narrative_role TEXT,
    report_type TEXT,
    industry TEXT,
    client TEXT,
    brand TEXT,
    data_density TEXT DEFAULT 'medium',
    executive_suitability TEXT DEFAULT 'medium',
    visual_complexity TEXT DEFAULT 'medium',
    classification_confidence REAL DEFAULT 0.0,
    detected_project_id INTEGER,
    is_excluded INTEGER DEFAULT 0,
    is_template_approved INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    processed_at REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (presentation_id) REFERENCES intel_si_presentations(id)
);

CREATE TABLE IF NOT EXISTS intel_si_template_families (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_name TEXT NOT NULL,
    typical_layout TEXT,
    typical_visual TEXT,
    typical_purpose TEXT,
    required_inputs TEXT,
    recommended_usage TEXT,
    member_count INTEGER DEFAULT 0,
    is_approved INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS intel_si_template_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL,
    slide_id INTEGER NOT NULL,
    is_representative INTEGER DEFAULT 0,
    similarity_score REAL DEFAULT 0.0,
    created_at REAL NOT NULL,
    FOREIGN KEY (family_id) REFERENCES intel_si_template_families(id),
    FOREIGN KEY (slide_id) REFERENCES intel_si_slides(id)
);

CREATE TABLE IF NOT EXISTS intel_si_detected_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    presentation_id INTEGER NOT NULL,
    project_name TEXT,
    client_name TEXT,
    brand_name TEXT,
    analyst_name TEXT,
    start_slide INTEGER NOT NULL,
    end_slide INTEGER NOT NULL,
    slide_count INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.0,
    is_confirmed INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    FOREIGN KEY (presentation_id) REFERENCES intel_si_presentations(id)
);

CREATE TABLE IF NOT EXISTS intel_si_style_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    presentation_id INTEGER,
    pattern_type TEXT NOT NULL,
    pattern_name TEXT NOT NULL,
    pattern_data TEXT NOT NULL,
    frequency INTEGER DEFAULT 1,
    source_slides TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS intel_si_retrieval_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text TEXT NOT NULL,
    node_id INTEGER,
    storyline_id INTEGER,
    results_json TEXT NOT NULL,
    result_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS intel_si_storyline_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    storyline_id INTEGER NOT NULL,
    node_id INTEGER NOT NULL,
    slide_id INTEGER NOT NULL,
    similarity_score REAL DEFAULT 0.0,
    match_reason TEXT,
    recommended_elements TEXT,
    elements_not_to_reuse TEXT,
    recommended_layout TEXT,
    recommended_visual TEXT,
    recommended_chart TEXT,
    confidence REAL DEFAULT 0.0,
    is_accepted INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    FOREIGN KEY (slide_id) REFERENCES intel_si_slides(id)
);

CREATE TABLE IF NOT EXISTS intel_si_processing_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    presentation_id INTEGER NOT NULL,
    step TEXT NOT NULL,
    slide_number INTEGER,
    status TEXT NOT NULL,
    message TEXT,
    duration_ms REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (presentation_id) REFERENCES intel_si_presentations(id)
);

CREATE TABLE IF NOT EXISTS intel_si_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slide_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT NOT NULL,
    corrected_by TEXT DEFAULT 'analyst',
    created_at REAL NOT NULL,
    FOREIGN KEY (slide_id) REFERENCES intel_si_slides(id)
);

CREATE TABLE IF NOT EXISTS intel_si_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slide_id INTEGER NOT NULL UNIQUE,
    embedding_blob BLOB NOT NULL,
    model_name TEXT NOT NULL DEFAULT 'nomic-embed-text',
    created_at REAL NOT NULL,
    FOREIGN KEY (slide_id) REFERENCES intel_si_slides(id)
);

CREATE INDEX IF NOT EXISTS idx_si_slides_pres ON intel_si_slides(presentation_id);
CREATE INDEX IF NOT EXISTS idx_si_slides_purpose ON intel_si_slides(slide_purpose);
CREATE INDEX IF NOT EXISTS idx_si_slides_layout ON intel_si_slides(layout_type);
CREATE INDEX IF NOT EXISTS idx_si_slides_client ON intel_si_slides(client);
CREATE INDEX IF NOT EXISTS idx_si_slides_status ON intel_si_slides(status);
CREATE INDEX IF NOT EXISTS idx_si_slides_project ON intel_si_slides(detected_project_id);
CREATE INDEX IF NOT EXISTS idx_si_tm_family ON intel_si_template_members(family_id);
CREATE INDEX IF NOT EXISTS idx_si_tm_slide ON intel_si_template_members(slide_id);
CREATE INDEX IF NOT EXISTS idx_si_dp_pres ON intel_si_detected_projects(presentation_id);
CREATE INDEX IF NOT EXISTS idx_si_sp_pres ON intel_si_style_patterns(presentation_id);
CREATE INDEX IF NOT EXISTS idx_si_sm_storyline ON intel_si_storyline_matches(storyline_id);
CREATE INDEX IF NOT EXISTS idx_si_sm_node ON intel_si_storyline_matches(node_id);
CREATE INDEX IF NOT EXISTS idx_si_pl_pres ON intel_si_processing_logs(presentation_id);
CREATE INDEX IF NOT EXISTS idx_si_corr_slide ON intel_si_corrections(slide_id);
CREATE INDEX IF NOT EXISTS idx_si_emb_slide ON intel_si_embeddings(slide_id);

CREATE TABLE IF NOT EXISTS intel_pc_presentations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    storyline_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    executive_summary TEXT,
    narrative_pattern TEXT,
    total_slides INTEGER DEFAULT 0,
    estimated_duration_minutes REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',
    generated_by TEXT DEFAULT 'system',
    approved_by TEXT,
    approved_at REAL,
    generation_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES intel_projects(id),
    FOREIGN KEY (storyline_id) REFERENCES intel_storylines(id)
);

CREATE TABLE IF NOT EXISTS intel_pc_slides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    presentation_id INTEGER NOT NULL,
    slide_number INTEGER NOT NULL,
    slide_purpose TEXT NOT NULL,
    node_id INTEGER,
    title TEXT NOT NULL,
    subtitle TEXT,
    narrative TEXT,
    business_objective TEXT,
    key_message TEXT,
    speaker_notes TEXT,
    recommended_visual TEXT,
    recommended_chart TEXT,
    layout_recommendation TEXT,
    layout_rationale TEXT,
    alt_layout_1 TEXT,
    alt_layout_1_rationale TEXT,
    alt_layout_2 TEXT,
    alt_layout_2_rationale TEXT,
    template_family_id INTEGER,
    content_blocks_json TEXT DEFAULT '[]',
    evidence_ids_json TEXT DEFAULT '[]',
    insight_ids_json TEXT DEFAULT '[]',
    historical_refs_json TEXT DEFAULT '[]',
    confidence_json TEXT DEFAULT '{}',
    overall_confidence REAL DEFAULT 0.5,
    transition_to_next TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    is_locked INTEGER DEFAULT 0,
    reviewed_by TEXT,
    reviewed_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (presentation_id) REFERENCES intel_pc_presentations(id),
    FOREIGN KEY (node_id) REFERENCES intel_story_nodes(id)
);

CREATE TABLE IF NOT EXISTS intel_pc_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    presentation_id INTEGER NOT NULL,
    slide_id INTEGER,
    action TEXT NOT NULL,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    actor TEXT DEFAULT 'system',
    created_at REAL NOT NULL,
    FOREIGN KEY (presentation_id) REFERENCES intel_pc_presentations(id)
);

CREATE INDEX IF NOT EXISTS idx_pc_pres_project ON intel_pc_presentations(project_id);
CREATE INDEX IF NOT EXISTS idx_pc_pres_storyline ON intel_pc_presentations(storyline_id);
CREATE INDEX IF NOT EXISTS idx_pc_pres_status ON intel_pc_presentations(status);
CREATE INDEX IF NOT EXISTS idx_pc_slides_pres ON intel_pc_slides(presentation_id);
CREATE INDEX IF NOT EXISTS idx_pc_slides_purpose ON intel_pc_slides(slide_purpose);
CREATE INDEX IF NOT EXISTS idx_pc_slides_node ON intel_pc_slides(node_id);
CREATE INDEX IF NOT EXISTS idx_pc_slides_status ON intel_pc_slides(status);
CREATE INDEX IF NOT EXISTS idx_pc_audit_pres ON intel_pc_audit(presentation_id);

CREATE TABLE IF NOT EXISTS intel_render_jobs (
    id TEXT PRIMARY KEY,
    presentation_id INTEGER NOT NULL,
    job_type TEXT NOT NULL DEFAULT 'full',
    status TEXT NOT NULL DEFAULT 'pending',
    progress_pct INTEGER DEFAULT 0,
    progress_message TEXT DEFAULT '',
    slide_ids_json TEXT DEFAULT '[]',
    theme_id TEXT DEFAULT 'hunter_default',
    output_path TEXT,
    output_size_bytes INTEGER,
    warnings_json TEXT DEFAULT '[]',
    error TEXT,
    started_at REAL,
    finished_at REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (presentation_id) REFERENCES intel_pc_presentations(id)
);

CREATE TABLE IF NOT EXISTS intel_rendered_presentations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    presentation_id INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    output_path TEXT NOT NULL,
    output_size_bytes INTEGER DEFAULT 0,
    slide_count INTEGER DEFAULT 0,
    theme_id TEXT DEFAULT 'hunter_default',
    render_duration_ms INTEGER DEFAULT 0,
    metadata_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY (job_id) REFERENCES intel_render_jobs(id),
    FOREIGN KEY (presentation_id) REFERENCES intel_pc_presentations(id)
);

CREATE TABLE IF NOT EXISTS intel_render_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    slide_id INTEGER NOT NULL,
    slide_number INTEGER NOT NULL,
    render_type TEXT NOT NULL,
    duration_ms INTEGER DEFAULT 0,
    warnings_json TEXT DEFAULT '[]',
    created_at REAL NOT NULL,
    FOREIGN KEY (job_id) REFERENCES intel_render_jobs(id),
    FOREIGN KEY (slide_id) REFERENCES intel_pc_slides(id)
);

CREATE TABLE IF NOT EXISTS intel_themes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    primary_color TEXT DEFAULT '#5B2C9D',
    secondary_color TEXT DEFAULT '#5E35B1',
    accent_color TEXT DEFAULT '#A6CAEC',
    background_color TEXT DEFAULT '#FFFFFF',
    text_color TEXT DEFAULT '#1A1A1A',
    font_heading TEXT DEFAULT 'Calibri',
    font_body TEXT DEFAULT 'Calibri',
    font_size_title INTEGER DEFAULT 26,
    font_size_body INTEGER DEFAULT 14,
    font_size_caption INTEGER DEFAULT 9,
    logo_position TEXT DEFAULT 'top_right',
    footer_style TEXT DEFAULT 'grey_band',
    color_palette_json TEXT DEFAULT '[]',
    is_default INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS intel_template_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    theme_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    template_path TEXT NOT NULL,
    changelog TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (theme_id) REFERENCES intel_themes(id)
);

CREATE TABLE IF NOT EXISTS intel_render_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    presentation_id INTEGER NOT NULL,
    job_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT DEFAULT 'system',
    details_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY (presentation_id) REFERENCES intel_pc_presentations(id),
    FOREIGN KEY (job_id) REFERENCES intel_render_jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_rj_pres ON intel_render_jobs(presentation_id);
CREATE INDEX IF NOT EXISTS idx_rj_status ON intel_render_jobs(status);
CREATE INDEX IF NOT EXISTS idx_rp_pres ON intel_rendered_presentations(presentation_id);
CREATE INDEX IF NOT EXISTS idx_rp_job ON intel_rendered_presentations(job_id);
CREATE INDEX IF NOT EXISTS idx_rm_job ON intel_render_metrics(job_id);
CREATE INDEX IF NOT EXISTS idx_rm_slide ON intel_render_metrics(slide_id);
CREATE INDEX IF NOT EXISTS idx_tv_theme ON intel_template_versions(theme_id);
CREATE INDEX IF NOT EXISTS idx_rh_pres ON intel_render_history(presentation_id);
CREATE INDEX IF NOT EXISTS idx_rh_job ON intel_render_history(job_id);

-- Pipeline Orchestrator tables
CREATE TABLE IF NOT EXISTS intel_pipeline_runs (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    execution_mode TEXT NOT NULL DEFAULT 'full',
    current_stage TEXT,
    start_stage TEXT,
    completed_stages_json TEXT DEFAULT '[]',
    remaining_stages_json TEXT DEFAULT '[]',
    skipped_stages_json TEXT DEFAULT '[]',
    progress_pct REAL DEFAULT 0,
    estimated_remaining_ms INTEGER DEFAULT 0,
    user TEXT DEFAULT 'system',
    error TEXT,
    started_at REAL,
    completed_at REAL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS intel_pipeline_stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    version INTEGER DEFAULT 1,
    input_hash TEXT,
    output_hash TEXT,
    dependencies_json TEXT DEFAULT '[]',
    execution_time_ms INTEGER DEFAULT 0,
    started_at REAL,
    completed_at REAL,
    logs_json TEXT DEFAULT '[]',
    warnings_json TEXT DEFAULT '[]',
    errors_json TEXT DEFAULT '[]',
    cache_status TEXT DEFAULT 'miss',
    result_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES intel_pipeline_runs(id)
);

CREATE TABLE IF NOT EXISTS intel_pipeline_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    stage_id TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    output_hash TEXT,
    version INTEGER DEFAULT 1,
    result_summary_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    expires_at REAL
);

CREATE TABLE IF NOT EXISTS intel_pipeline_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage_id TEXT,
    level TEXT DEFAULT 'info',
    message TEXT NOT NULL,
    details_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES intel_pipeline_runs(id)
);

CREATE TABLE IF NOT EXISTS intel_pipeline_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    stage_id TEXT,
    run_id TEXT,
    metric_type TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT DEFAULT 'ms',
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_plr_project ON intel_pipeline_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_plr_status ON intel_pipeline_runs(status);
CREATE INDEX IF NOT EXISTS idx_pls_run ON intel_pipeline_stages(run_id);
CREATE INDEX IF NOT EXISTS idx_pls_stage ON intel_pipeline_stages(stage_id);
CREATE INDEX IF NOT EXISTS idx_plc_project ON intel_pipeline_cache(project_id);
CREATE INDEX IF NOT EXISTS idx_plc_stage ON intel_pipeline_cache(stage_id);
CREATE INDEX IF NOT EXISTS idx_plc_hash ON intel_pipeline_cache(input_hash);
CREATE INDEX IF NOT EXISTS idx_pll_run ON intel_pipeline_logs(run_id);
CREATE INDEX IF NOT EXISTS idx_plm_project ON intel_pipeline_metrics(project_id);
CREATE INDEX IF NOT EXISTS idx_plm_run ON intel_pipeline_metrics(run_id);

-- ── Word Renderer ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS intel_word_jobs (
    id TEXT PRIMARY KEY,
    presentation_id INTEGER NOT NULL,
    job_type TEXT NOT NULL DEFAULT 'full',
    status TEXT NOT NULL DEFAULT 'pending',
    progress_pct REAL DEFAULT 0,
    progress_message TEXT,
    sections_json TEXT DEFAULT '[]',
    theme_id TEXT DEFAULT 'hunter_default',
    output_path TEXT,
    output_size_bytes INTEGER DEFAULT 0,
    warnings_json TEXT DEFAULT '[]',
    error TEXT,
    started_at REAL,
    finished_at REAL,
    created_at REAL NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE TABLE IF NOT EXISTS intel_word_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    presentation_id INTEGER NOT NULL,
    version INTEGER DEFAULT 1,
    output_path TEXT NOT NULL,
    output_size_bytes INTEGER DEFAULT 0,
    section_count INTEGER DEFAULT 0,
    page_count INTEGER DEFAULT 0,
    word_count INTEGER DEFAULT 0,
    theme_id TEXT DEFAULT 'hunter_default',
    render_duration_ms INTEGER DEFAULT 0,
    metadata_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE TABLE IF NOT EXISTS intel_word_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    section_name TEXT NOT NULL,
    section_number INTEGER DEFAULT 0,
    render_type TEXT NOT NULL DEFAULT 'section',
    duration_ms INTEGER DEFAULT 0,
    element_count INTEGER DEFAULT 0,
    warnings_json TEXT DEFAULT '[]',
    created_at REAL NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE TABLE IF NOT EXISTS intel_word_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    presentation_id INTEGER NOT NULL,
    job_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT DEFAULT 'system',
    details_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_wj_pres ON intel_word_jobs(presentation_id);
CREATE INDEX IF NOT EXISTS idx_wj_status ON intel_word_jobs(status);
CREATE INDEX IF NOT EXISTS idx_wd_pres ON intel_word_documents(presentation_id);
CREATE INDEX IF NOT EXISTS idx_wd_job ON intel_word_documents(job_id);
CREATE INDEX IF NOT EXISTS idx_wm_job ON intel_word_metrics(job_id);
CREATE INDEX IF NOT EXISTS idx_wh_pres ON intel_word_history(presentation_id);

CREATE TABLE IF NOT EXISTS intel_pub_validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    presentation_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    readiness_score REAL DEFAULT 0,
    readiness_class TEXT DEFAULT 'draft',
    scores_json TEXT DEFAULT '{}',
    issues_json TEXT DEFAULT '[]',
    warnings_json TEXT DEFAULT '[]',
    pptx_job_id TEXT,
    word_job_id TEXT,
    validated_by TEXT DEFAULT 'system',
    started_at REAL,
    finished_at REAL,
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    FOREIGN KEY (project_id) REFERENCES intel_projects(id),
    FOREIGN KEY (presentation_id) REFERENCES intel_pc_presentations(id)
);

CREATE TABLE IF NOT EXISTS intel_pub_diff_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    validation_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    presentation_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    match_pct REAL DEFAULT 0,
    differences_json TEXT DEFAULT '[]',
    summary_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    FOREIGN KEY (validation_id) REFERENCES intel_pub_validations(id),
    FOREIGN KEY (project_id) REFERENCES intel_projects(id)
);

CREATE TABLE IF NOT EXISTS intel_pub_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    presentation_id INTEGER NOT NULL,
    major INTEGER NOT NULL DEFAULT 1,
    minor INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0,
    version_label TEXT,
    pipeline_version TEXT,
    renderer_version TEXT,
    presentation_version INTEGER DEFAULT 1,
    approval_status TEXT DEFAULT 'draft',
    approved_by TEXT,
    approved_at REAL,
    notes TEXT,
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    FOREIGN KEY (project_id) REFERENCES intel_projects(id),
    FOREIGN KEY (presentation_id) REFERENCES intel_pc_presentations(id)
);

CREATE TABLE IF NOT EXISTS intel_pub_packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    presentation_id INTEGER NOT NULL,
    version_id INTEGER,
    validation_id INTEGER,
    status TEXT NOT NULL DEFAULT 'building',
    package_path TEXT,
    package_size_bytes INTEGER DEFAULT 0,
    manifest_json TEXT DEFAULT '{}',
    contents_json TEXT DEFAULT '[]',
    created_by TEXT DEFAULT 'system',
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    finished_at REAL,
    FOREIGN KEY (project_id) REFERENCES intel_projects(id),
    FOREIGN KEY (version_id) REFERENCES intel_pub_versions(id),
    FOREIGN KEY (validation_id) REFERENCES intel_pub_validations(id)
);

CREATE TABLE IF NOT EXISTS intel_pub_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    presentation_id INTEGER NOT NULL,
    version_id INTEGER,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    actor TEXT DEFAULT 'system',
    notes TEXT,
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    FOREIGN KEY (project_id) REFERENCES intel_projects(id),
    FOREIGN KEY (version_id) REFERENCES intel_pub_versions(id)
);

CREATE TABLE IF NOT EXISTS intel_pub_downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    package_id INTEGER,
    file_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size_bytes INTEGER DEFAULT 0,
    downloaded_by TEXT DEFAULT 'system',
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    FOREIGN KEY (project_id) REFERENCES intel_projects(id),
    FOREIGN KEY (package_id) REFERENCES intel_pub_packages(id)
);

CREATE TABLE IF NOT EXISTS intel_pub_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    presentation_id INTEGER,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    action TEXT NOT NULL,
    actor TEXT DEFAULT 'system',
    details_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
    FOREIGN KEY (project_id) REFERENCES intel_projects(id)
);

CREATE INDEX IF NOT EXISTS idx_pub_val_proj ON intel_pub_validations(project_id);
CREATE INDEX IF NOT EXISTS idx_pub_val_pres ON intel_pub_validations(presentation_id);
CREATE INDEX IF NOT EXISTS idx_pub_diff_val ON intel_pub_diff_reports(validation_id);
CREATE INDEX IF NOT EXISTS idx_pub_ver_proj ON intel_pub_versions(project_id);
CREATE INDEX IF NOT EXISTS idx_pub_ver_pres ON intel_pub_versions(presentation_id);
CREATE INDEX IF NOT EXISTS idx_pub_pkg_proj ON intel_pub_packages(project_id);
CREATE INDEX IF NOT EXISTS idx_pub_app_proj ON intel_pub_approvals(project_id);
CREATE INDEX IF NOT EXISTS idx_pub_dl_proj ON intel_pub_downloads(project_id);
CREATE INDEX IF NOT EXISTS idx_pub_aud_proj ON intel_pub_audit(project_id);
CREATE INDEX IF NOT EXISTS idx_pub_aud_pres ON intel_pub_audit(presentation_id);

CREATE TABLE IF NOT EXISTS intel_background_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    research_id INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    brief_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    approval_status TEXT DEFAULT 'pending',
    approved_by TEXT,
    approved_at REAL,
    docx_path TEXT,
    docx_generated_at REAL,
    notes TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES intel_projects(id),
    FOREIGN KEY (research_id) REFERENCES intel_background_research(id)
);

CREATE TABLE IF NOT EXISTS intel_brief_section_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_id INTEGER NOT NULL,
    section_key TEXT NOT NULL,
    edited_content TEXT NOT NULL,
    analyst_note TEXT,
    edited_by TEXT DEFAULT 'analyst',
    created_at REAL NOT NULL,
    FOREIGN KEY (brief_id) REFERENCES intel_background_briefs(id)
);

CREATE INDEX IF NOT EXISTS idx_brief_project ON intel_background_briefs(project_id);
CREATE INDEX IF NOT EXISTS idx_brief_research ON intel_background_briefs(research_id);
CREATE INDEX IF NOT EXISTS idx_brief_edit_brief ON intel_brief_section_edits(brief_id);

CREATE TABLE IF NOT EXISTS intel_research_specifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    spec_json TEXT NOT NULL,
    raw_brief_text TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    readiness_status TEXT NOT NULL DEFAULT 'not_ready',
    readiness_json TEXT,
    approval_status TEXT NOT NULL DEFAULT 'pending',
    approved_by TEXT,
    approved_at REAL,
    rejected_reason TEXT,
    generation_source TEXT NOT NULL DEFAULT 'manual',
    llm_model TEXT,
    docx_path TEXT,
    docx_generated_at REAL,
    notes TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES intel_projects(id)
);

CREATE TABLE IF NOT EXISTS intel_spec_section_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spec_id INTEGER NOT NULL,
    section_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    is_locked INTEGER NOT NULL DEFAULT 0,
    locked_by TEXT,
    locked_at REAL,
    edited_content TEXT,
    analyst_note TEXT,
    reviewed_by TEXT,
    reviewed_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (spec_id) REFERENCES intel_research_specifications(id)
);

CREATE TABLE IF NOT EXISTS intel_spec_clarifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spec_id INTEGER NOT NULL,
    section_key TEXT,
    question TEXT NOT NULL,
    is_blocking INTEGER NOT NULL DEFAULT 1,
    answer TEXT,
    resolved_by TEXT,
    resolved_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (spec_id) REFERENCES intel_research_specifications(id)
);

CREATE TABLE IF NOT EXISTS intel_spec_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spec_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    section_key TEXT,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    actor TEXT NOT NULL DEFAULT 'analyst',
    created_at REAL NOT NULL,
    FOREIGN KEY (spec_id) REFERENCES intel_research_specifications(id)
);

CREATE INDEX IF NOT EXISTS idx_rspec_project ON intel_research_specifications(project_id);
CREATE INDEX IF NOT EXISTS idx_rspec_status ON intel_research_specifications(status);
CREATE INDEX IF NOT EXISTS idx_rspec_approval ON intel_research_specifications(approval_status);
CREATE INDEX IF NOT EXISTS idx_spec_sa_spec ON intel_spec_section_approvals(spec_id);
CREATE INDEX IF NOT EXISTS idx_spec_sa_key ON intel_spec_section_approvals(spec_id, section_key);
CREATE INDEX IF NOT EXISTS idx_spec_clar_spec ON intel_spec_clarifications(spec_id);
CREATE INDEX IF NOT EXISTS idx_spec_clar_blocking ON intel_spec_clarifications(spec_id, is_blocking);
CREATE INDEX IF NOT EXISTS idx_spec_audit_spec ON intel_spec_audit(spec_id);

CREATE TABLE IF NOT EXISTS intel_datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    record_count INTEGER NOT NULL DEFAULT 0,
    column_mapping_json TEXT,
    stats_json TEXT,
    preview_json TEXT,
    approval_status TEXT DEFAULT 'pending',
    approved_by TEXT,
    approved_at REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES intel_projects(id)
);
CREATE INDEX IF NOT EXISTS idx_datasets_project ON intel_datasets(project_id);
"""


# Versioned, forward-only migrations, applied once each and recorded in
# schema_migrations. Append new entries; never edit or reorder applied ones.
# ADD COLUMN on a DB that already has the column (pre-versioning DBs) is tolerated.
_FK_INDEXES = [
    ("intel_query_versions", "strategy_id"), ("intel_sample_evaluations", "project_id"),
    ("intel_sample_evaluations", "strategy_id"), ("intel_news_approvals", "research_id"),
    ("intel_execution_runs", "plan_id"), ("intel_si_storyline_matches", "slide_id"),
    ("intel_pub_diff_reports", "project_id"), ("intel_pub_packages", "validation_id"),
    ("intel_pub_packages", "version_id"), ("intel_pub_approvals", "version_id"),
    ("intel_pub_downloads", "package_id"), ("qc_reports", "project_id"),
    ("qc_configs", "report_id"), ("qc_findings", "report_id"), ("qc_findings", "run_id"),
    ("qc_runs", "report_id"), ("qc_exports", "run_id"),
]

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (1, "dataset processing columns", [
        "ALTER TABLE intel_datasets ADD COLUMN processing_status TEXT DEFAULT 'done'",
        "ALTER TABLE intel_datasets ADD COLUMN processing_error TEXT",
        "ALTER TABLE intel_datasets ADD COLUMN research_question_id TEXT",
    ]),
    (2, "project type", ["ALTER TABLE intel_projects ADD COLUMN project_type TEXT NOT NULL DEFAULT 'research'"]),
    (3, "qc source cache text", ["ALTER TABLE qc_source_cache ADD COLUMN extracted_text TEXT"]),
    # Brand = the Client name entered on the New Project form (drives the Brandfetch logo).
    (4, "project brand", [
        "ALTER TABLE intel_projects ADD COLUMN brand TEXT",
        "UPDATE intel_projects SET brand = NULLIF(TRIM(json_extract(spec_json, '$.client')), '') WHERE brand IS NULL",
    ]),
    (5, "foreign-key indexes", [f"CREATE INDEX IF NOT EXISTS idx_{t}_{c} ON {t}({c})" for t, c in _FK_INDEXES]),
    # Resolved brand/product logos (first lookup source; see domains/research/brandfetch.py).
    (6, "brand logo cache", ["""
        CREATE TABLE IF NOT EXISTS brand_logos (
            brand_key  TEXT PRIMARY KEY,   -- normalised name (lower-case, single spaces)
            brand_name TEXT NOT NULL,
            logo_url   TEXT,               -- NULL = nothing found (retried after a while)
            domain     TEXT,
            source     TEXT NOT NULL,      -- brandfetch | google | none
            fetched_at REAL NOT NULL
        )"""]),
    # Resolved Pexels background images, keyed by search query (see domains/research/pexels.py).
    (7, "pexels image cache", ["""
        CREATE TABLE IF NOT EXISTS pexels_images (
            query_key    TEXT PRIMARY KEY,  -- normalised query (lower-case, single spaces)
            query_text   TEXT NOT NULL,
            image_url    TEXT,              -- NULL = nothing found (retried after a while)
            photographer TEXT,
            source_url   TEXT,
            fetched_at   REAL NOT NULL
        )"""]),
    # Per-item normalized research results (news/social posts from the multi-source
    # research pipeline), linked to project_id — see domains/research/multi_source.py.
    (8, "research items", ["""
        CREATE TABLE IF NOT EXISTS intel_research_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            research_id INTEGER,
            topic TEXT NOT NULL,
            source_api TEXT NOT NULL,
            platform TEXT,
            publication TEXT,
            published_date REAL NOT NULL,
            title TEXT,
            content TEXT,
            url TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(project_id, url),
            FOREIGN KEY (project_id) REFERENCES intel_projects(id),
            FOREIGN KEY (research_id) REFERENCES intel_background_research(id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_research_items_project ON intel_research_items(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_research_items_project_date ON intel_research_items(project_id, published_date)",
    ]),
    (9, "research item author", [
        "ALTER TABLE intel_research_items ADD COLUMN author TEXT",
    ]),
    (10, "research item thumbnail", [
        "ALTER TABLE intel_research_items ADD COLUMN thumbnail_url TEXT",
    ]),
    (11, "pexels video cache", [
        "ALTER TABLE pexels_images ADD COLUMN video_url TEXT",
    ]),
    (12, "youtube section video cache", ["""
        CREATE TABLE IF NOT EXISTS youtube_videos (
            query_key    TEXT PRIMARY KEY,  -- normalised query (lower-case, single spaces)
            query_text   TEXT NOT NULL,
            video_id     TEXT,              -- NULL = nothing found (retried after a while)
            embed_url    TEXT,
            title        TEXT,
            thumbnail_url TEXT,
            fetched_at   REAL NOT NULL
        )"""]),
    (13, "organizations, users, sessions, project scoping", ["""
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            background_image_url TEXT,
            created_at REAL NOT NULL,
            archived_at REAL
        )""", """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER REFERENCES organizations(id),
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            avatar_url TEXT,
            role TEXT NOT NULL CHECK (role IN ('super_admin', 'admin', 'analyser')),
            must_change_password INTEGER NOT NULL DEFAULT 1,
            failed_login_count INTEGER NOT NULL DEFAULT 0,
            locked_until REAL,
            created_at REAL NOT NULL,
            archived_at REAL
        )""", """
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
        "ALTER TABLE intel_projects ADD COLUMN org_id INTEGER REFERENCES organizations(id)",
        "ALTER TABLE intel_projects ADD COLUMN owner_user_id INTEGER REFERENCES users(id)",
        "ALTER TABLE intel_projects ADD COLUMN archived_at REAL",
        "INSERT INTO organizations (name, created_at, archived_at) "
        "SELECT 'Default Organization', 0, NULL WHERE NOT EXISTS "
        "(SELECT 1 FROM organizations WHERE name = 'Default Organization')",
        "UPDATE intel_projects SET org_id = "
        "(SELECT id FROM organizations WHERE name = 'Default Organization') "
        "WHERE org_id IS NULL",
    ]),
]


QC_SCHEMA = """
CREATE TABLE IF NOT EXISTS qc_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES intel_projects(id),
    file_name     TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    row_count     INTEGER DEFAULT 0,
    column_count  INTEGER DEFAULT 0,
    columns_json  TEXT,
    field_mapping TEXT,
    parse_status  TEXT DEFAULT 'pending',
    parse_error   TEXT,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS qc_configs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id     INTEGER NOT NULL REFERENCES qc_reports(id),
    check_type    TEXT NOT NULL,
    enabled       INTEGER DEFAULT 1,
    severity      TEXT DEFAULT 'medium',
    parameters    TEXT,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS qc_findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES qc_runs(id),
    report_id     INTEGER NOT NULL REFERENCES qc_reports(id),
    check_type    TEXT NOT NULL,
    row_number    INTEGER,
    column_name   TEXT,
    severity      TEXT NOT NULL,
    message       TEXT NOT NULL,
    expected      TEXT,
    actual        TEXT,
    source_url    TEXT,
    analyst_action TEXT,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS qc_source_cache (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL UNIQUE,
    status_code   INTEGER,
    is_accessible INTEGER DEFAULT 1,
    is_paywalled  INTEGER DEFAULT 0,
    extracted_headline TEXT,
    extracted_date TEXT,
    extracted_text TEXT,
    fetch_error   TEXT,
    fetched_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS qc_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id     INTEGER NOT NULL REFERENCES qc_reports(id),
    status        TEXT DEFAULT 'pending',
    total_rows    INTEGER DEFAULT 0,
    total_checks  INTEGER DEFAULT 0,
    total_findings INTEGER DEFAULT 0,
    score         REAL,
    score_breakdown TEXT,
    started_at    REAL,
    completed_at  REAL,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS qc_exports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES qc_runs(id),
    file_name     TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    format        TEXT DEFAULT 'xlsx',
    created_at    REAL NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    """Open a connection. Cheap (SQLite is in-process), so repositories open one per call;
    WAL mode is persistent and set once in init_intelligence_db()."""
    conn = sqlite3.connect(str(config.MEMORY_DB_PATH), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")  # safe with WAL; avoids an fsync per commit
    # Foreign keys are declared but deliberately NOT enforced: existing code paths (and
    # tests) insert child rows before/without their parents. Deleting a project cleans
    # up its children explicitly (projects/repository.delete_project) instead.
    return conn


def _apply_migrations(conn: sqlite3.Connection) -> list[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at REAL NOT NULL)"
    )
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for version, name, statements in MIGRATIONS:
        if version in done:
            continue
        with conn:  # one transaction per migration
            for sql in statements:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column name" not in str(e):
                        raise
            conn.execute("INSERT INTO schema_migrations VALUES (?, ?, ?)", (version, name, time.time()))
        applied.append(version)
    return applied


def init_intelligence_db() -> None:
    conn = _conn()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(INTELLIGENCE_SCHEMA)
        conn.executescript(QC_SCHEMA)
        applied = _apply_migrations(conn)
        if applied:
            logger.info("Applied DB migrations %s", applied)
    finally:
        conn.close()


# ─── QC Source Cache ────────────────────────────────────────────────────────

def get_cached_source(url: str) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM qc_source_cache WHERE url = ?", (url,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_source_cache(url: str, **kwargs) -> None:
    conn = _conn()
    existing = conn.execute("SELECT id FROM qc_source_cache WHERE url = ?", (url,)).fetchone()
    now = time.time()
    if existing:
        sets = []
        vals = []
        for k, v in kwargs.items():
            sets.append(f"{k} = ?")
            vals.append(v)
        sets.append("fetched_at = ?")
        vals.append(now)
        vals.append(existing["id"])
        conn.execute(f"UPDATE qc_source_cache SET {', '.join(sets)} WHERE id = ?", vals)
    else:
        cols = ["url", "fetched_at"] + list(kwargs.keys())
        placeholders = ["?"] * len(cols)
        vals = [url, now] + list(kwargs.values())
        conn.execute(f"INSERT INTO qc_source_cache ({', '.join(cols)}) VALUES ({', '.join(placeholders)})", vals)
    conn.commit()
    conn.close()

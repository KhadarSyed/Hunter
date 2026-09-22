"""Persistent storage for the intelligence workflow: background research,
search strategies, query versions, sample evaluations, and approval states.

Uses the same SQLite database as memory.py (agent/data/memory.db).
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Optional

from . import config

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

_DATASET_MIGRATIONS = [
    "ALTER TABLE intel_datasets ADD COLUMN processing_status TEXT DEFAULT 'done'",
    "ALTER TABLE intel_datasets ADD COLUMN processing_error TEXT",
    "ALTER TABLE intel_datasets ADD COLUMN research_question_id TEXT",
    "ALTER TABLE intel_projects ADD COLUMN project_type TEXT NOT NULL DEFAULT 'research'",
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
    conn = sqlite3.connect(str(config.MEMORY_DB_PATH), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_intelligence_db():
    conn = _conn()
    conn.executescript(INTELLIGENCE_SCHEMA)
    conn.executescript(QC_SCHEMA)
    for mig in _DATASET_MIGRATIONS:
        try:
            conn.execute(mig)
        except sqlite3.OperationalError:
            pass
    try:
        conn.execute("ALTER TABLE qc_source_cache ADD COLUMN extracted_text TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


# ─── Projects ────────────────────────────────────────────────────────────────

def create_project(name: str, spec: dict, project_type: str = "research") -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_projects (project_name, spec_json, project_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (name, json.dumps(spec), project_type, now, now),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_project(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {**dict(row), "spec": json.loads(row["spec_json"])}


def list_projects(project_type: str | None = None) -> list[dict]:
    conn = _conn()
    if project_type:
        rows = conn.execute(
            "SELECT id, project_name, project_type, created_at, updated_at FROM intel_projects WHERE project_type = ? ORDER BY updated_at DESC",
            (project_type,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, project_name, project_type, created_at, updated_at FROM intel_projects ORDER BY updated_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_or_create_project(spec: dict) -> int:
    name = ""
    cb = spec.get("commissioning_brand", {})
    if isinstance(cb, dict):
        name = cb.get("name", "")
    if not name:
        name = spec.get("project_name", "Untitled")

    conn = _conn()
    row = conn.execute(
        "SELECT id FROM intel_projects WHERE project_name = ? ORDER BY created_at DESC LIMIT 1",
        (name,),
    ).fetchone()
    conn.close()

    if row:
        return row["id"]
    return create_project(name, spec)


# ─── Jobs ────────────────────────────────────────────────────────────────────

def create_job(job_id: str, project_id: int, job_type: str) -> str:
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT INTO intel_jobs (id, project_id, job_type, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
        (job_id, project_id, job_type, now),
    )
    conn.commit()
    conn.close()
    return job_id


def update_job(job_id: str, *, status: str | None = None, progress_pct: int | None = None,
               progress_message: str | None = None, result: dict | None = None, error: str | None = None):
    conn = _conn()
    parts = []
    vals = []
    if status is not None:
        parts.append("status = ?")
        vals.append(status)
        if status == "running" and not parts.__contains__("started_at"):
            parts.append("started_at = ?")
            vals.append(time.time())
        if status in ("completed", "failed", "cancelled"):
            parts.append("finished_at = ?")
            vals.append(time.time())
    if progress_pct is not None:
        parts.append("progress_pct = ?")
        vals.append(progress_pct)
    if progress_message is not None:
        parts.append("progress_message = ?")
        vals.append(progress_message)
    if result is not None:
        parts.append("result_json = ?")
        vals.append(json.dumps(result))
    if error is not None:
        parts.append("error = ?")
        vals.append(error)

    if parts:
        vals.append(job_id)
        conn.execute(f"UPDATE intel_jobs SET {', '.join(parts)} WHERE id = ?", vals)
        conn.commit()
    conn.close()


def get_job(job_id: str) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("result_json"):
        d["result"] = json.loads(d["result_json"])
    return d


def list_jobs(project_id: int, job_type: str | None = None) -> list[dict]:
    conn = _conn()
    if job_type:
        rows = conn.execute(
            "SELECT * FROM intel_jobs WHERE project_id = ? AND job_type = ? ORDER BY created_at DESC",
            (project_id, job_type),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM intel_jobs WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("result_json"):
            d["result"] = json.loads(d["result_json"])
        result.append(d)
    return result


# ─── Background Research ─────────────────────────────────────────────────────

def save_background_research(project_id: int, research: dict, llm_output: dict | None = None) -> int:
    conn = _conn()
    now = time.time()
    existing = conn.execute(
        "SELECT MAX(version) as v FROM intel_background_research WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    version = (existing["v"] or 0) + 1

    cur = conn.execute(
        "INSERT INTO intel_background_research (project_id, version, status, research_json, llm_output_json, created_at) "
        "VALUES (?, ?, 'draft', ?, ?, ?)",
        (project_id, version, json.dumps(research), json.dumps(llm_output) if llm_output else None, now),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def save_background_research_update(research_id: int, research: dict, llm_output: dict | None = None):
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_research SET research_json = ?, llm_output_json = ? WHERE id = ?",
        (json.dumps(research), json.dumps(llm_output) if llm_output else None, research_id),
    )
    conn.commit()
    conn.close()


def get_latest_research(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_background_research WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["research"] = json.loads(d["research_json"])
    if d.get("llm_output_json"):
        d["llm_output"] = json.loads(d["llm_output_json"])
    return d


def approve_research(research_id: int, reviewer: str = "analyst") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_research SET approval_status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
        (reviewer, time.time(), research_id),
    )
    conn.commit()
    conn.close()
    return True


def reject_research(research_id: int, notes: str = "") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_research SET approval_status = 'revision_requested', notes = ? WHERE id = ?",
        (notes, research_id),
    )
    conn.commit()
    conn.close()
    return True


# ─── Search Strategies ───────────────────────────────────────────────────────

def save_search_strategy(project_id: int, strategy: dict) -> int:
    conn = _conn()
    now = time.time()
    existing = conn.execute(
        "SELECT MAX(version) as v FROM intel_search_strategies WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    version = (existing["v"] or 0) + 1

    cur = conn.execute(
        "INSERT INTO intel_search_strategies (project_id, version, status, strategy_json, created_at) "
        "VALUES (?, ?, 'draft', ?, ?)",
        (project_id, version, json.dumps(strategy), now),
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def get_latest_strategy(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_search_strategies WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["strategy"] = json.loads(d["strategy_json"])
    return d


def approve_strategy(strategy_id: int, reviewer: str = "analyst") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_search_strategies SET approval_status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
        (reviewer, time.time(), strategy_id),
    )
    conn.commit()
    conn.close()
    return True


def update_strategy_query(strategy_id: int, query_type: str, query_text: str) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_query_versions (strategy_id, version_label, query_type, query_text, created_at) "
        "VALUES (?, datetime('now'), ?, ?, ?)",
        (strategy_id, query_type, query_text, now),
    )
    vid = cur.lastrowid
    conn.commit()

    row = conn.execute("SELECT strategy_json FROM intel_search_strategies WHERE id = ?", (strategy_id,)).fetchone()
    if row:
        strategy = json.loads(row["strategy_json"])
        if "core_queries" in strategy:
            for q in strategy["core_queries"]:
                if q.get("type") == query_type:
                    q["query"] = query_text
            conn.execute(
                "UPDATE intel_search_strategies SET strategy_json = ? WHERE id = ?",
                (json.dumps(strategy), strategy_id),
            )
            conn.commit()

    conn.close()
    return vid


def get_query_versions(strategy_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_query_versions WHERE strategy_id = ? ORDER BY created_at DESC",
        (strategy_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_research_question(strategy_id: int, question_id: str, question: str, query: str) -> bool:
    conn = _conn()
    row = conn.execute("SELECT strategy_json FROM intel_search_strategies WHERE id = ?", (strategy_id,)).fetchone()
    if not row:
        conn.close()
        return False
    strategy = json.loads(row["strategy_json"])
    rqs = strategy.get("research_question_queries", [])
    for rq in rqs:
        if rq.get("question_id") == question_id:
            rq["question"] = question
            rq["query"] = query
            break
    else:
        conn.close()
        return False
    strategy["research_question_queries"] = rqs
    conn.execute(
        "UPDATE intel_search_strategies SET strategy_json = ? WHERE id = ?",
        (json.dumps(strategy), strategy_id),
    )
    conn.commit()
    conn.close()
    return True


def delete_research_question(strategy_id: int, question_id: str) -> bool:
    conn = _conn()
    row = conn.execute("SELECT strategy_json FROM intel_search_strategies WHERE id = ?", (strategy_id,)).fetchone()
    if not row:
        conn.close()
        return False
    strategy = json.loads(row["strategy_json"])
    rqs = strategy.get("research_question_queries", [])
    original_len = len(rqs)
    rqs = [rq for rq in rqs if rq.get("question_id") != question_id]
    if len(rqs) == original_len:
        conn.close()
        return False
    strategy["research_question_queries"] = rqs
    conn.execute(
        "UPDATE intel_search_strategies SET strategy_json = ? WHERE id = ?",
        (json.dumps(strategy), strategy_id),
    )
    conn.commit()
    conn.close()
    return True


# ─── Datasets ───────────────────────────────────────────────────────────────

def save_dataset(project_id: int, file_name: str, file_path: str,
                 record_count: int, column_mapping: dict, stats: dict,
                 preview: list, processing_status: str = "done",
                 research_question_id: str | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_datasets (project_id, file_name, file_path, record_count, "
        "column_mapping_json, stats_json, preview_json, processing_status, "
        "research_question_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, file_name, file_path, record_count,
         json.dumps(column_mapping), json.dumps(stats), json.dumps(preview),
         processing_status, research_question_id, now),
    )
    dataset_id = cur.lastrowid
    conn.commit()
    conn.close()
    return dataset_id


def update_dataset_parsed(dataset_id: int, record_count: int,
                          column_mapping: dict, stats: dict, preview: list):
    conn = _conn()
    conn.execute(
        "UPDATE intel_datasets SET record_count=?, column_mapping_json=?, "
        "stats_json=?, preview_json=?, processing_status='done' WHERE id=?",
        (record_count, json.dumps(column_mapping), json.dumps(stats),
         json.dumps(preview), dataset_id),
    )
    conn.commit()
    conn.close()


def update_dataset_error(dataset_id: int, error: str):
    conn = _conn()
    conn.execute(
        "UPDATE intel_datasets SET processing_status='error', processing_error=? WHERE id=?",
        (error, dataset_id),
    )
    conn.commit()
    conn.close()


def get_latest_dataset(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_datasets WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["column_mapping"] = json.loads(d["column_mapping_json"]) if d["column_mapping_json"] else {}
    d["stats"] = json.loads(d["stats_json"]) if d["stats_json"] else {}
    d["preview"] = json.loads(d["preview_json"]) if d["preview_json"] else []
    return d


def get_datasets_by_project(project_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_datasets WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    conn.close()
    results = []
    for row in rows:
        d = dict(row)
        d["column_mapping"] = json.loads(d["column_mapping_json"]) if d.get("column_mapping_json") else {}
        d["stats"] = json.loads(d["stats_json"]) if d.get("stats_json") else {}
        d["preview"] = json.loads(d["preview_json"]) if d.get("preview_json") else []
        results.append(d)
    return results


def get_dataset_for_rq(project_id: int, research_question_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_datasets WHERE project_id = ? AND research_question_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (project_id, research_question_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["column_mapping"] = json.loads(d["column_mapping_json"]) if d.get("column_mapping_json") else {}
    d["stats"] = json.loads(d["stats_json"]) if d.get("stats_json") else {}
    d["preview"] = json.loads(d["preview_json"]) if d.get("preview_json") else []
    return d


def approve_dataset(dataset_id: int, reviewer: str = "analyst") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_datasets SET approval_status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
        (reviewer, time.time(), dataset_id),
    )
    conn.commit()
    conn.close()
    return True


def delete_dataset(dataset_id: int) -> bool:
    conn = _conn()
    conn.execute("DELETE FROM intel_datasets WHERE id = ?", (dataset_id,))
    conn.commit()
    conn.close()
    return True


# ─── Sample Evaluations ─────────────────────────────────────────────────────

def save_sample_evaluation(project_id: int, strategy_id: int, file_name: str,
                           file_path: str, evaluation: dict | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_sample_evaluations (project_id, strategy_id, file_name, file_path, evaluation_json, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, strategy_id, file_name, file_path,
         json.dumps(evaluation) if evaluation else None,
         "completed" if evaluation else "pending", now),
    )
    eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid


def cancel_stale_running_jobs():
    conn = _conn()
    now = time.time()
    conn.execute(
        "UPDATE intel_jobs SET status = 'cancelled', finished_at = ?, error = 'Cancelled: stale running job from prior session' "
        "WHERE status = 'running'",
        (now,),
    )
    conn.commit()
    conn.close()


def get_latest_evaluation(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_sample_evaluations WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("evaluation_json"):
        d["evaluation"] = json.loads(d["evaluation_json"])
    return d


def update_evaluation(eval_id: int, evaluation: dict):
    conn = _conn()
    conn.execute(
        "UPDATE intel_sample_evaluations SET evaluation_json = ?, status = 'completed' WHERE id = ?",
        (json.dumps(evaluation), eval_id),
    )
    conn.commit()
    conn.close()


# ─── News Item Approvals ────────────────────────────────────────────────────

def update_news_approval(research_id: int, item_index: int, status: str, notes: str = ""):
    conn = _conn()
    now = time.time()
    existing = conn.execute(
        "SELECT id FROM intel_news_approvals WHERE research_id = ? AND item_index = ?",
        (research_id, item_index),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE intel_news_approvals SET status = ?, notes = ?, updated_at = ? WHERE id = ?",
            (status, notes, now, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO intel_news_approvals (research_id, item_index, status, notes, updated_at) VALUES (?, ?, ?, ?, ?)",
            (research_id, item_index, status, notes, now),
        )
    conn.commit()
    conn.close()


def get_news_approvals(research_id: int) -> dict[int, dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_news_approvals WHERE research_id = ?",
        (research_id,),
    ).fetchall()
    conn.close()
    return {row["item_index"]: dict(row) for row in rows}


# ─── Research Plans ────────────────────────────────────────────────────────

def save_research_plan(project_id: int, plan: dict, source: str = "llm") -> int:
    conn = _conn()
    now = time.time()
    existing = conn.execute(
        "SELECT MAX(version) as v FROM intel_research_plans WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    version = (existing["v"] or 0) + 1

    cur = conn.execute(
        "INSERT INTO intel_research_plans (project_id, version, status, plan_json, source, created_at) "
        "VALUES (?, ?, 'draft', ?, ?, ?)",
        (project_id, version, json.dumps(plan), source, now),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_latest_plan(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_research_plans WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["plan"] = json.loads(d["plan_json"])
    return d


def approve_plan(plan_id: int, reviewer: str = "analyst") -> bool:
    conn = _conn()
    cur = conn.execute(
        "UPDATE intel_research_plans SET approval_status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?",
        (reviewer, time.time(), plan_id),
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def reject_plan(plan_id: int, notes: str = "") -> bool:
    conn = _conn()
    cur = conn.execute(
        "UPDATE intel_research_plans SET approval_status = 'rejected', notes = ? WHERE id = ?",
        (notes, plan_id),
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def update_plan_status(plan_id: int, status: str) -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_research_plans SET status = ? WHERE id = ?",
        (status, plan_id),
    )
    conn.commit()
    conn.close()
    return True


# ─── Execution Runs ────────────────────────────────────────────────────────

def create_execution_run(project_id: int, plan_id: int, total_units: int) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_execution_runs (project_id, plan_id, status, total_units, created_at) "
        "VALUES (?, ?, 'pending', ?, ?)",
        (project_id, plan_id, total_units, now),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def get_execution_run(run_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_execution_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def get_latest_execution_run(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_execution_runs WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def update_execution_run(run_id: int, *, status: str | None = None, completed_units: int | None = None,
                          failed_units: int | None = None, skipped_units: int | None = None,
                          total_evidence: int | None = None, started_at: float | None = None,
                          finished_at: float | None = None):
    conn = _conn()
    parts = []
    vals = []
    if status is not None:
        parts.append("status = ?")
        vals.append(status)
        if status == "running" and not parts.__contains__("started_at"):
            parts.append("started_at = ?")
            vals.append(time.time())
        if status in ("completed", "failed", "cancelled"):
            parts.append("finished_at = ?")
            vals.append(time.time())
    if completed_units is not None:
        parts.append("completed_units = ?")
        vals.append(completed_units)
    if failed_units is not None:
        parts.append("failed_units = ?")
        vals.append(failed_units)
    if skipped_units is not None:
        parts.append("skipped_units = ?")
        vals.append(skipped_units)
    if total_evidence is not None:
        parts.append("total_evidence = ?")
        vals.append(total_evidence)
    if started_at is not None:
        parts.append("started_at = ?")
        vals.append(started_at)
    if finished_at is not None:
        parts.append("finished_at = ?")
        vals.append(finished_at)

    if parts:
        vals.append(run_id)
        conn.execute(f"UPDATE intel_execution_runs SET {', '.join(parts)} WHERE id = ?", vals)
        conn.commit()
    conn.close()


def create_execution_unit(run_id: int, unit_id: str, objective_id: str, method: str) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_execution_units (run_id, unit_id, objective_id, method, status, created_at) "
        "VALUES (?, ?, ?, ?, 'pending', ?)",
        (run_id, unit_id, objective_id, method, now),
    )
    eu_id = cur.lastrowid
    conn.commit()
    conn.close()
    return eu_id


def update_execution_unit(eu_id: int, *, status: str | None = None, progress_pct: int | None = None,
                           records_processed: int | None = None, evidence_count: int | None = None,
                           error: str | None = None, result: dict | None = None,
                           started_at: float | None = None, finished_at: float | None = None):
    conn = _conn()
    parts = []
    vals = []
    if status is not None:
        parts.append("status = ?")
        vals.append(status)
        if status == "running" and not parts.__contains__("started_at"):
            parts.append("started_at = ?")
            vals.append(time.time())
        if status in ("completed", "failed", "cancelled", "skipped"):
            parts.append("finished_at = ?")
            vals.append(time.time())
    if progress_pct is not None:
        parts.append("progress_pct = ?")
        vals.append(progress_pct)
    if records_processed is not None:
        parts.append("records_processed = ?")
        vals.append(records_processed)
    if evidence_count is not None:
        parts.append("evidence_count = ?")
        vals.append(evidence_count)
    if error is not None:
        parts.append("error = ?")
        vals.append(error)
    if result is not None:
        parts.append("result_json = ?")
        vals.append(json.dumps(result))
    if started_at is not None:
        parts.append("started_at = ?")
        vals.append(started_at)
    if finished_at is not None:
        parts.append("finished_at = ?")
        vals.append(finished_at)

    if parts:
        vals.append(eu_id)
        conn.execute(f"UPDATE intel_execution_units SET {', '.join(parts)} WHERE id = ?", vals)
        conn.commit()
    conn.close()


def get_execution_units(run_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_execution_units WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("result_json"):
            d["result"] = json.loads(d["result_json"])
        result.append(d)
    return result


def get_execution_unit_by_unit_id(run_id: int, unit_id: str) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_execution_units WHERE run_id = ? AND unit_id = ?",
        (run_id, unit_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("result_json"):
        d["result"] = json.loads(d["result_json"])
    return d


def add_execution_log(run_id: int, message: str, unit_id: str | None = None, level: str = "info"):
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT INTO intel_execution_logs (run_id, unit_id, level, message, created_at) VALUES (?, ?, ?, ?, ?)",
        (run_id, unit_id, level, message, now),
    )
    conn.commit()
    conn.close()


def get_execution_logs(run_id: int, limit: int = 100) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_execution_logs WHERE run_id = ? ORDER BY id DESC LIMIT ?",
        (run_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_evidence(run_id: int, unit_id: str, objective_id: str, evidence_type: str, method: str,
                   *, platform: str | None = None, source: str | None = None, date: str | None = None,
                   text_excerpt: str | None = None, metrics: dict | None = None,
                   confidence: str = "medium", rationale: str | None = None,
                   dataset: str = "meltwater_export") -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_evidence (run_id, unit_id, objective_id, evidence_type, platform, source, date, "
        "text_excerpt, metrics_json, confidence, method, rationale, dataset, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, unit_id, objective_id, evidence_type, platform, source, date,
         text_excerpt, json.dumps(metrics) if metrics is not None else None,
         confidence, method, rationale, dataset, now),
    )
    ev_id = cur.lastrowid
    conn.commit()
    conn.close()
    return ev_id


def get_evidence(run_id: int, unit_id: str | None = None) -> list[dict]:
    conn = _conn()
    if unit_id:
        rows = conn.execute(
            "SELECT * FROM intel_evidence WHERE run_id = ? AND unit_id = ? ORDER BY id",
            (run_id, unit_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM intel_evidence WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("metrics_json"):
            d["metrics"] = json.loads(d["metrics_json"])
        result.append(d)
    return result


def get_evidence_record(evidence_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_evidence WHERE id = ?", (evidence_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("metrics_json"):
        d["metrics"] = json.loads(d["metrics_json"])
    return d


def count_evidence(run_id: int, unit_id: str | None = None) -> int:
    conn = _conn()
    if unit_id:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM intel_evidence WHERE run_id = ? AND unit_id = ?",
            (run_id, unit_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM intel_evidence WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    conn.close()
    return row["c"] if row else 0



# ─── Evidence Library ───────────────────────────────────────────────────────

_LIBRARY_JOIN_SELECT = (
    "SELECT li.id AS id, li.project_id AS project_id, li.evidence_id AS evidence_id, "
    "li.review_status AS review_status, li.quality_score AS quality_score, "
    "li.quality_components_json AS quality_components_json, li.relevance_score AS relevance_score, "
    "li.is_representative AS is_representative, li.is_high_value AS is_high_value, "
    "li.canonical_id AS canonical_id, li.duplicate_group AS duplicate_group, "
    "li.objective_id AS objective_id, li.unit_id AS unit_id, li.reviewed_by AS reviewed_by, "
    "li.reviewed_at AS reviewed_at, li.created_at AS created_at, li.updated_at AS updated_at, "
    "ev.run_id AS run_id, ev.evidence_type AS evidence_type, ev.platform AS platform, "
    "ev.source AS source, ev.date AS date, ev.text_excerpt AS text_excerpt, "
    "ev.metrics_json AS metrics_json, ev.confidence AS confidence, ev.method AS method, "
    "ev.rationale AS rationale, ev.dataset AS dataset, ev.created_at AS evidence_created_at "
    "FROM intel_library_items li JOIN intel_evidence ev ON li.evidence_id = ev.id"
)

_LIBRARY_SORT_COLUMNS = {
    "created_at", "updated_at", "quality_score", "relevance_score", "review_status",
    "reviewed_at", "date", "evidence_type", "platform", "source", "method", "confidence",
    "objective_id", "unit_id", "id",
}


def _row_to_library_item(d: dict) -> dict:
    if d.get("quality_components_json"):
        d["quality_components"] = json.loads(d["quality_components_json"])
    if d.get("metrics_json"):
        d["metrics"] = json.loads(d["metrics_json"])
    return d


def create_library_item(project_id: int, evidence_id: int, objective_id: str | None = None,
                         unit_id: str | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_library_items (project_id, evidence_id, review_status, objective_id, unit_id, "
        "created_at, updated_at) VALUES (?, ?, 'unreviewed', ?, ?, ?, ?)",
        (project_id, evidence_id, objective_id, unit_id, now, now),
    )
    item_id = cur.lastrowid
    conn.commit()
    conn.close()
    return item_id


def get_library_item(item_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(f"{_LIBRARY_JOIN_SELECT} WHERE li.id = ?", (item_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_library_item(dict(row))


def get_library_item_by_evidence_id(evidence_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(f"{_LIBRARY_JOIN_SELECT} WHERE li.evidence_id = ?", (evidence_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_library_item(dict(row))


def list_library_items(project_id: int, *, review_status: str | None = None, objective_id: str | None = None,
                        unit_id: str | None = None, method: str | None = None, platform: str | None = None,
                        confidence: str | None = None, is_representative: bool | None = None,
                        is_high_value: bool | None = None, search: str | None = None,
                        sort_by: str = "created_at", sort_dir: str = "desc",
                        limit: int = 200, offset: int = 0) -> list[dict]:
    conn = _conn()
    where = ["li.project_id = ?"]
    vals: list[Any] = [project_id]

    if review_status is not None:
        where.append("li.review_status = ?")
        vals.append(review_status)
    if objective_id is not None:
        where.append("li.objective_id = ?")
        vals.append(objective_id)
    if unit_id is not None:
        where.append("li.unit_id = ?")
        vals.append(unit_id)
    if method is not None:
        where.append("ev.method = ?")
        vals.append(method)
    if platform is not None:
        where.append("ev.platform = ?")
        vals.append(platform)
    if confidence is not None:
        where.append("ev.confidence = ?")
        vals.append(confidence)
    if is_representative is not None:
        where.append("li.is_representative = ?")
        vals.append(1 if is_representative else 0)
    if is_high_value is not None:
        where.append("li.is_high_value = ?")
        vals.append(1 if is_high_value else 0)
    if search:
        where.append(
            "(ev.text_excerpt LIKE ? OR ev.source LIKE ? OR ev.platform LIKE ? OR ev.rationale LIKE ?)"
        )
        like = f"%{search}%"
        vals.extend([like, like, like, like])

    sort_col = sort_by if sort_by in _LIBRARY_SORT_COLUMNS else "created_at"
    sort_direction = "ASC" if str(sort_dir).lower() == "asc" else "DESC"

    query = (
        f"{_LIBRARY_JOIN_SELECT} WHERE {' AND '.join(where)} "
        f"ORDER BY {sort_col} {sort_direction} LIMIT ? OFFSET ?"
    )
    vals.extend([limit, offset])

    rows = conn.execute(query, vals).fetchall()
    conn.close()
    return [_row_to_library_item(dict(r)) for r in rows]


def count_library_items(project_id: int, *, review_status: str | None = None) -> int:
    conn = _conn()
    if review_status is not None:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM intel_library_items WHERE project_id = ? AND review_status = ?",
            (project_id, review_status),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM intel_library_items WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    conn.close()
    return row["c"] if row else 0


def update_library_item(item_id: int, *, review_status: str | None = None, quality_score: float | None = None,
                         quality_components: dict | None = None, relevance_score: float | None = None,
                         is_representative: bool | None = None, is_high_value: bool | None = None,
                         canonical_id: int | None = None, duplicate_group: str | None = None,
                         objective_id: str | None = None, unit_id: str | None = None,
                         reviewed_by: str | None = None, confidence: str | None = None) -> bool:
    conn = _conn()
    parts = ["updated_at = ?"]
    vals: list[Any] = [time.time()]

    if review_status is not None:
        parts.append("review_status = ?")
        vals.append(review_status)
    if quality_score is not None:
        parts.append("quality_score = ?")
        vals.append(quality_score)
    if quality_components is not None:
        parts.append("quality_components_json = ?")
        vals.append(json.dumps(quality_components))
    if relevance_score is not None:
        parts.append("relevance_score = ?")
        vals.append(relevance_score)
    if is_representative is not None:
        parts.append("is_representative = ?")
        vals.append(1 if is_representative else 0)
    if is_high_value is not None:
        parts.append("is_high_value = ?")
        vals.append(1 if is_high_value else 0)
    if canonical_id is not None:
        parts.append("canonical_id = ?")
        vals.append(canonical_id)
    if duplicate_group is not None:
        parts.append("duplicate_group = ?")
        vals.append(duplicate_group)
    if objective_id is not None:
        parts.append("objective_id = ?")
        vals.append(objective_id)
    if unit_id is not None:
        parts.append("unit_id = ?")
        vals.append(unit_id)
    if reviewed_by is not None:
        parts.append("reviewed_by = ?")
        parts.append("reviewed_at = ?")
        vals.append(reviewed_by)
        vals.append(time.time())

    vals.append(item_id)
    cur = conn.execute(f"UPDATE intel_library_items SET {', '.join(parts)} WHERE id = ?", vals)
    changed = cur.rowcount > 0

    if confidence is not None:
        conn.execute(
            "UPDATE intel_evidence SET confidence = ? WHERE id = "
            "(SELECT evidence_id FROM intel_library_items WHERE id = ?)",
            (confidence, item_id),
        )

    conn.commit()
    conn.close()
    return changed


def bulk_update_library_items(item_ids: list[int], *, review_status: str | None = None,
                               reviewed_by: str | None = None) -> int:
    if not item_ids:
        return 0

    conn = _conn()
    parts = ["updated_at = ?"]
    vals: list[Any] = [time.time()]

    if review_status is not None:
        parts.append("review_status = ?")
        vals.append(review_status)
    if reviewed_by is not None:
        parts.append("reviewed_by = ?")
        parts.append("reviewed_at = ?")
        vals.append(reviewed_by)
        vals.append(time.time())

    placeholders = ", ".join("?" for _ in item_ids)
    query = f"UPDATE intel_library_items SET {', '.join(parts)} WHERE id IN ({placeholders})"
    cur = conn.execute(query, vals + list(item_ids))
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def add_library_annotation(library_item_id: int, note: str, author: str = "analyst") -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_library_annotations (library_item_id, author, note, created_at) VALUES (?, ?, ?, ?)",
        (library_item_id, author, note, now),
    )
    ann_id = cur.lastrowid
    conn.commit()
    conn.close()
    return ann_id


def get_library_annotations(library_item_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_library_annotations WHERE library_item_id = ? ORDER BY created_at DESC",
        (library_item_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_library_audit(library_item_id: int, action: str, field: str | None = None,
                       old_value: str | None = None, new_value: str | None = None,
                       actor: str = "analyst") -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_library_audit (library_item_id, action, field, old_value, new_value, actor, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (library_item_id, action, field, old_value, new_value, actor, now),
    )
    audit_id = cur.lastrowid
    conn.commit()
    conn.close()
    return audit_id


def get_library_audit(library_item_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_library_audit WHERE library_item_id = ? ORDER BY created_at DESC",
        (library_item_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_duplicate_groups(project_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT duplicate_group as group_, COUNT(*) as count, MAX(canonical_id) as canonical_id "
        "FROM intel_library_items WHERE project_id = ? AND duplicate_group IS NOT NULL "
        "GROUP BY duplicate_group",
        (project_id,),
    ).fetchall()
    conn.close()
    return [
        {"group": r["group_"], "count": r["count"], "canonical_id": r["canonical_id"]}
        for r in rows
    ]


def get_objective_coverage(project_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT objective_id, "
        "COUNT(*) as total, "
        "SUM(CASE WHEN review_status = 'accepted' THEN 1 ELSE 0 END) as accepted, "
        "SUM(CASE WHEN review_status = 'rejected' THEN 1 ELSE 0 END) as rejected, "
        "SUM(CASE WHEN review_status = 'unreviewed' THEN 1 ELSE 0 END) as unreviewed "
        "FROM intel_library_items WHERE project_id = ? GROUP BY objective_id",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_library_status_counts(project_id: int) -> dict:
    conn = _conn()
    rows = conn.execute(
        "SELECT review_status, COUNT(*) as c FROM intel_library_items WHERE project_id = ? GROUP BY review_status",
        (project_id,),
    ).fetchall()
    rep = conn.execute(
        "SELECT COUNT(*) as c FROM intel_library_items WHERE project_id = ? AND is_representative = 1",
        (project_id,),
    ).fetchone()
    hv = conn.execute(
        "SELECT COUNT(*) as c FROM intel_library_items WHERE project_id = ? AND is_high_value = 1",
        (project_id,),
    ).fetchone()
    dup = conn.execute(
        "SELECT COUNT(DISTINCT duplicate_group) as c FROM intel_library_items "
        "WHERE project_id = ? AND duplicate_group IS NOT NULL",
        (project_id,),
    ).fetchone()
    conn.close()
    return {
        "by_status": {r["review_status"]: r["c"] for r in rows},
        "representative": rep["c"] if rep else 0,
        "high_value": hv["c"] if hv else 0,
        "duplicate_groups": dup["c"] if dup else 0,
    }


def get_duplicate_group_members(duplicate_group: str) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        f"{_LIBRARY_JOIN_SELECT} WHERE li.duplicate_group = ? ORDER BY li.id",
        (duplicate_group,),
    ).fetchall()
    conn.close()
    return [_row_to_library_item(dict(r)) for r in rows]


# ─── Insights ──────────────────────────────────────────────────────────────

_INSIGHT_SORT_COLUMNS = {
    "created_at", "updated_at", "title", "insight_type", "status",
    "confidence_score", "evidence_count", "objective_id", "id",
}

_INSIGHT_UPDATABLE_FIELDS = {
    "objective_id", "insight_type", "title", "executive_summary", "observation",
    "interpretation", "business_impact", "confidence_score", "confidence_rationale",
    "evidence_count", "platforms_represented", "date_coverage",
    "contradictory_evidence", "limitations", "recommended_visualisation",
    "analyst_notes", "status", "reviewed_by", "reviewed_at", "generation_id",
}


def create_insight(
    project_id: int,
    objective_id: str,
    insight_type: str,
    title: str,
    *,
    executive_summary: str | None = None,
    observation: str | None = None,
    interpretation: str | None = None,
    business_impact: str | None = None,
    confidence_score: float = 0.5,
    confidence_rationale: str | None = None,
    contradictory_evidence: str | None = None,
    limitations: str | None = None,
    recommended_visualisation: str | None = None,
    platforms_represented: list[str] | None = None,
    date_coverage: str | None = None,
    generation_id: str | None = None,
) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_insights "
        "(project_id, objective_id, insight_type, title, executive_summary, observation, "
        "interpretation, business_impact, confidence_score, confidence_rationale, "
        "contradictory_evidence, limitations, recommended_visualisation, "
        "platforms_represented, date_coverage, generation_id, "
        "status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
        (
            project_id, objective_id, insight_type, title,
            executive_summary, observation, interpretation, business_impact,
            confidence_score, confidence_rationale,
            contradictory_evidence, limitations, recommended_visualisation,
            json.dumps(platforms_represented) if platforms_represented is not None else None,
            date_coverage, generation_id,
            now, now,
        ),
    )
    insight_id = cur.lastrowid
    conn.commit()
    conn.close()
    return insight_id


def _parse_insight_row(d: dict) -> dict:
    if d.get("platforms_represented"):
        try:
            d["platforms_represented"] = json.loads(d["platforms_represented"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def get_insight(insight_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_insights WHERE id = ?", (insight_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_insight_row(dict(row))


def list_insights(
    project_id: int,
    *,
    objective_id: str | None = None,
    insight_type: str | None = None,
    status: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    conn = _conn()
    where = ["project_id = ?"]
    vals: list[Any] = [project_id]

    if objective_id is not None:
        where.append("objective_id = ?")
        vals.append(objective_id)
    if insight_type is not None:
        where.append("insight_type = ?")
        vals.append(insight_type)
    if status is not None:
        where.append("status = ?")
        vals.append(status)

    sort_col = sort_by if sort_by in _INSIGHT_SORT_COLUMNS else "created_at"
    sort_direction = "ASC" if str(sort_dir).lower() == "asc" else "DESC"

    query = (
        f"SELECT * FROM intel_insights WHERE {' AND '.join(where)} "
        f"ORDER BY {sort_col} {sort_direction} LIMIT ? OFFSET ?"
    )
    vals.extend([limit, offset])

    rows = conn.execute(query, vals).fetchall()
    conn.close()
    return [_parse_insight_row(dict(r)) for r in rows]


def update_insight(insight_id: int, **kwargs: Any) -> bool:
    conn = _conn()
    parts = ["updated_at = ?"]
    vals: list[Any] = [time.time()]

    for key, value in kwargs.items():
        if key not in _INSIGHT_UPDATABLE_FIELDS:
            continue
        if key == "platforms_represented" and isinstance(value, list):
            parts.append("platforms_represented = ?")
            vals.append(json.dumps(value))
        else:
            parts.append(f"{key} = ?")
            vals.append(value)

    # Auto-set reviewed_at when reviewed_by is provided
    if "reviewed_by" in kwargs and "reviewed_at" not in kwargs:
        parts.append("reviewed_at = ?")
        vals.append(time.time())

    vals.append(insight_id)
    cur = conn.execute(f"UPDATE intel_insights SET {', '.join(parts)} WHERE id = ?", vals)
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def delete_insight(insight_id: int) -> bool:
    conn = _conn()
    conn.execute("DELETE FROM intel_insight_evidence WHERE insight_id = ?", (insight_id,))
    conn.execute("DELETE FROM intel_insight_audit WHERE insight_id = ?", (insight_id,))
    cur = conn.execute("DELETE FROM intel_insights WHERE id = ?", (insight_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def add_insight_evidence(insight_id: int, library_item_id: int, role: str = "supporting") -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_insight_evidence (insight_id, library_item_id, role, created_at) "
        "VALUES (?, ?, ?, ?)",
        (insight_id, library_item_id, role, now),
    )
    mapping_id = cur.lastrowid
    conn.commit()
    conn.close()
    return mapping_id


def get_insight_evidence(insight_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT ie.id AS mapping_id, ie.insight_id AS insight_id, "
        "ie.library_item_id AS library_item_id, ie.role AS role, "
        "ie.created_at AS mapping_created_at, "
        "li.id AS li_id, li.project_id AS project_id, li.evidence_id AS evidence_id, "
        "li.review_status AS review_status, li.quality_score AS quality_score, "
        "li.quality_components_json AS quality_components_json, li.relevance_score AS relevance_score, "
        "li.is_representative AS is_representative, li.is_high_value AS is_high_value, "
        "li.canonical_id AS canonical_id, li.duplicate_group AS duplicate_group, "
        "li.objective_id AS objective_id, li.unit_id AS unit_id, li.reviewed_by AS reviewed_by, "
        "li.reviewed_at AS reviewed_at, li.created_at AS created_at, li.updated_at AS updated_at, "
        "ev.run_id AS run_id, ev.evidence_type AS evidence_type, ev.platform AS platform, "
        "ev.source AS source, ev.date AS date, ev.text_excerpt AS text_excerpt, "
        "ev.metrics_json AS metrics_json, ev.confidence AS confidence, ev.method AS method, "
        "ev.rationale AS rationale, ev.dataset AS dataset, ev.created_at AS evidence_created_at "
        "FROM intel_insight_evidence ie "
        "JOIN intel_library_items li ON ie.library_item_id = li.id "
        "JOIN intel_evidence ev ON li.evidence_id = ev.id "
        "WHERE ie.insight_id = ? ORDER BY ie.id",
        (insight_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("quality_components_json"):
            d["quality_components"] = json.loads(d["quality_components_json"])
        if d.get("metrics_json"):
            d["metrics"] = json.loads(d["metrics_json"])
        result.append(d)
    return result


def remove_insight_evidence(insight_id: int, library_item_id: int) -> bool:
    conn = _conn()
    cur = conn.execute(
        "DELETE FROM intel_insight_evidence WHERE insight_id = ? AND library_item_id = ?",
        (insight_id, library_item_id),
    )
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def add_insight_audit(
    insight_id: int,
    action: str,
    field: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    actor: str = "analyst",
) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_insight_audit (insight_id, action, field, old_value, new_value, actor, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            insight_id, action, field,
            str(old_value) if old_value is not None else None,
            str(new_value) if new_value is not None else None,
            actor, now,
        ),
    )
    audit_id = cur.lastrowid
    conn.commit()
    conn.close()
    return audit_id


def get_insight_audit(insight_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_insight_audit WHERE insight_id = ? ORDER BY created_at DESC",
        (insight_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_insights(project_id: int, *, status: str | None = None) -> int:
    conn = _conn()
    if status is not None:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM intel_insights WHERE project_id = ? AND status = ?",
            (project_id, status),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM intel_insights WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    conn.close()
    return row["c"] if row else 0


def get_insight_status_counts(project_id: int) -> dict:
    conn = _conn()
    status_rows = conn.execute(
        "SELECT status, COUNT(*) as c FROM intel_insights WHERE project_id = ? GROUP BY status",
        (project_id,),
    ).fetchall()
    type_rows = conn.execute(
        "SELECT insight_type, COUNT(*) as c FROM intel_insights WHERE project_id = ? GROUP BY insight_type",
        (project_id,),
    ).fetchall()
    total_row = conn.execute(
        "SELECT COUNT(*) as c FROM intel_insights WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    conn.close()
    return {
        "by_status": {r["status"]: r["c"] for r in status_rows},
        "by_type": {r["insight_type"]: r["c"] for r in type_rows},
        "total": total_row["c"] if total_row else 0,
    }


# ─── Storyline Store ──────────────────────────────────────────────────────

_STORYLINE_SORT_COLUMNS = {
    "created_at", "updated_at", "title", "status", "narrative_pattern", "id",
}

_STORYLINE_UPDATABLE_FIELDS = {
    "narrative_pattern", "title", "executive_summary", "total_duration_minutes",
    "node_count", "status", "generated_by", "approved_by", "approved_at",
    "generation_id",
}

_NODE_SORT_COLUMNS = {
    "order_position", "created_at", "title", "priority", "status",
    "confidence_score", "id",
}

_NODE_UPDATABLE_FIELDS = {
    "section_type", "title", "purpose", "narrative_summary", "suggested_visual",
    "priority", "estimated_duration_minutes", "confidence_score",
    "transition_text", "is_key_message", "is_locked", "order_position",
    "status", "reviewed_by", "reviewed_at",
}


def create_storyline(
    project_id: int,
    narrative_pattern: str,
    title: str,
    *,
    executive_summary: str | None = None,
    total_duration_minutes: float = 0,
    node_count: int = 0,
    generated_by: str = "system",
    generation_id: str | None = None,
) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_storylines "
        "(project_id, narrative_pattern, title, executive_summary, "
        "total_duration_minutes, node_count, status, generated_by, "
        "generation_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)",
        (
            project_id, narrative_pattern, title, executive_summary,
            total_duration_minutes, node_count, generated_by,
            generation_id, now, now,
        ),
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def get_storyline(storyline_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_storylines WHERE id = ?", (storyline_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_latest_storyline(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_storylines WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_storylines(project_id: int, *, status: str | None = None,
                    limit: int = 50, offset: int = 0) -> list[dict]:
    conn = _conn()
    where = ["project_id = ?"]
    vals: list[Any] = [project_id]
    if status is not None:
        where.append("status = ?")
        vals.append(status)
    query = (
        f"SELECT * FROM intel_storylines WHERE {' AND '.join(where)} "
        f"ORDER BY created_at DESC LIMIT ? OFFSET ?"
    )
    vals.extend([limit, offset])
    rows = conn.execute(query, vals).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_storyline(storyline_id: int, **kwargs: Any) -> bool:
    conn = _conn()
    parts = ["updated_at = ?"]
    vals: list[Any] = [time.time()]
    for key, value in kwargs.items():
        if key not in _STORYLINE_UPDATABLE_FIELDS:
            continue
        parts.append(f"{key} = ?")
        vals.append(value)
    if "approved_by" in kwargs and "approved_at" not in kwargs:
        parts.append("approved_at = ?")
        vals.append(time.time())
    vals.append(storyline_id)
    cur = conn.execute(
        f"UPDATE intel_storylines SET {', '.join(parts)} WHERE id = ?", vals,
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def delete_storyline(storyline_id: int) -> bool:
    conn = _conn()
    node_ids = [
        r["id"] for r in conn.execute(
            "SELECT id FROM intel_story_nodes WHERE storyline_id = ?",
            (storyline_id,),
        ).fetchall()
    ]
    for nid in node_ids:
        conn.execute("DELETE FROM intel_story_node_insights WHERE node_id = ?", (nid,))
    conn.execute("DELETE FROM intel_story_nodes WHERE storyline_id = ?", (storyline_id,))
    conn.execute("DELETE FROM intel_storyline_audit WHERE storyline_id = ?", (storyline_id,))
    cur = conn.execute("DELETE FROM intel_storylines WHERE id = ?", (storyline_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def create_story_node(
    storyline_id: int,
    section_type: str,
    title: str,
    order_position: int,
    *,
    purpose: str | None = None,
    narrative_summary: str | None = None,
    suggested_visual: str = "table",
    priority: str = "medium",
    estimated_duration_minutes: float = 2.0,
    confidence_score: float = 0.5,
    transition_text: str | None = None,
    is_key_message: bool = False,
) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_story_nodes "
        "(storyline_id, section_type, title, order_position, purpose, "
        "narrative_summary, suggested_visual, priority, estimated_duration_minutes, "
        "confidence_score, transition_text, is_key_message, is_locked, "
        "status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'draft', ?, ?)",
        (
            storyline_id, section_type, title, order_position,
            purpose, narrative_summary, suggested_visual, priority,
            estimated_duration_minutes, confidence_score, transition_text,
            1 if is_key_message else 0, now, now,
        ),
    )
    node_id = cur.lastrowid
    conn.commit()
    conn.close()
    return node_id


def get_story_node(node_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_story_nodes WHERE id = ?", (node_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["is_key_message"] = bool(d.get("is_key_message"))
    d["is_locked"] = bool(d.get("is_locked"))
    return d


def list_story_nodes(storyline_id: int, *, status: str | None = None) -> list[dict]:
    conn = _conn()
    where = ["storyline_id = ?"]
    vals: list[Any] = [storyline_id]
    if status is not None:
        where.append("status = ?")
        vals.append(status)
    rows = conn.execute(
        f"SELECT * FROM intel_story_nodes WHERE {' AND '.join(where)} "
        f"ORDER BY order_position ASC",
        vals,
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["is_key_message"] = bool(d.get("is_key_message"))
        d["is_locked"] = bool(d.get("is_locked"))
        result.append(d)
    return result


def update_story_node(node_id: int, **kwargs: Any) -> bool:
    conn = _conn()
    parts = ["updated_at = ?"]
    vals: list[Any] = [time.time()]
    for key, value in kwargs.items():
        if key not in _NODE_UPDATABLE_FIELDS:
            continue
        if key in ("is_key_message", "is_locked"):
            parts.append(f"{key} = ?")
            vals.append(1 if value else 0)
        else:
            parts.append(f"{key} = ?")
            vals.append(value)
    if "reviewed_by" in kwargs and "reviewed_at" not in kwargs:
        parts.append("reviewed_at = ?")
        vals.append(time.time())
    vals.append(node_id)
    cur = conn.execute(
        f"UPDATE intel_story_nodes SET {', '.join(parts)} WHERE id = ?", vals,
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def delete_story_node(node_id: int) -> bool:
    conn = _conn()
    conn.execute("DELETE FROM intel_story_node_insights WHERE node_id = ?", (node_id,))
    cur = conn.execute("DELETE FROM intel_story_nodes WHERE id = ?", (node_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def add_node_insight(node_id: int, insight_id: int, role: str = "supporting") -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_story_node_insights (node_id, insight_id, role, created_at) "
        "VALUES (?, ?, ?, ?)",
        (node_id, insight_id, role, now),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def get_node_insights(node_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT sni.id AS mapping_id, sni.node_id, sni.insight_id, sni.role, "
        "sni.created_at AS mapping_created_at, "
        "ins.project_id, ins.objective_id, ins.insight_type, ins.title AS insight_title, "
        "ins.executive_summary AS insight_summary, ins.confidence_score AS insight_confidence, "
        "ins.evidence_count, ins.status AS insight_status "
        "FROM intel_story_node_insights sni "
        "JOIN intel_insights ins ON sni.insight_id = ins.id "
        "WHERE sni.node_id = ? ORDER BY sni.id",
        (node_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def remove_node_insight(node_id: int, insight_id: int) -> bool:
    conn = _conn()
    cur = conn.execute(
        "DELETE FROM intel_story_node_insights WHERE node_id = ? AND insight_id = ?",
        (node_id, insight_id),
    )
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def add_storyline_audit(
    storyline_id: int,
    action: str,
    *,
    node_id: int | None = None,
    field: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    actor: str = "analyst",
) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_storyline_audit "
        "(storyline_id, node_id, action, field, old_value, new_value, actor, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            storyline_id, node_id, action, field,
            str(old_value) if old_value is not None else None,
            str(new_value) if new_value is not None else None,
            actor, now,
        ),
    )
    aid = cur.lastrowid
    conn.commit()
    conn.close()
    return aid


def get_storyline_audit(storyline_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_storyline_audit WHERE storyline_id = ? ORDER BY created_at DESC",
        (storyline_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def reorder_story_nodes(storyline_id: int, node_ids_in_order: list[int]) -> bool:
    conn = _conn()
    now = time.time()
    for pos, nid in enumerate(node_ids_in_order):
        conn.execute(
            "UPDATE intel_story_nodes SET order_position = ?, updated_at = ? "
            "WHERE id = ? AND storyline_id = ? AND is_locked = 0",
            (pos, now, nid, storyline_id),
        )
    conn.commit()
    conn.close()
    return True


# ─── Slide Intelligence: Presentations ─────────────────────────────────────

def create_si_presentation(filename: str, file_path: str, file_size: int = 0,
                           file_hash: str | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_presentations (filename, file_path, file_size, file_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (filename, file_path, file_size, file_hash, now),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_si_presentation(pres_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_si_presentations WHERE id = ?", (pres_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_si_presentations() -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT * FROM intel_si_presentations ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_si_presentation(pres_id: int, **kwargs: Any) -> bool:
    allowed = {"slide_count", "processed_count", "status", "error", "started_at",
               "completed_at", "file_hash"}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return False
    conn = _conn()
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [pres_id]
    conn.execute(f"UPDATE intel_si_presentations SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return True


def delete_si_presentation(pres_id: int):
    conn = _conn()
    slide_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM intel_si_slides WHERE presentation_id = ?", (pres_id,)
    ).fetchall()]
    for sid in slide_ids:
        conn.execute("DELETE FROM intel_si_template_members WHERE slide_id = ?", (sid,))
        conn.execute("DELETE FROM intel_si_corrections WHERE slide_id = ?", (sid,))
        conn.execute("DELETE FROM intel_si_embeddings WHERE slide_id = ?", (sid,))
        conn.execute("DELETE FROM intel_si_storyline_matches WHERE slide_id = ?", (sid,))
    conn.execute("DELETE FROM intel_si_slides WHERE presentation_id = ?", (pres_id,))
    conn.execute("DELETE FROM intel_si_detected_projects WHERE presentation_id = ?", (pres_id,))
    conn.execute("DELETE FROM intel_si_style_patterns WHERE presentation_id = ?", (pres_id,))
    conn.execute("DELETE FROM intel_si_processing_logs WHERE presentation_id = ?", (pres_id,))
    conn.execute("DELETE FROM intel_si_presentations WHERE id = ?", (pres_id,))
    conn.commit()
    conn.close()


# ─── Slide Intelligence: Slides ────────────────────────────────────────────

def create_si_slide(presentation_id: int, slide_number: int, **kwargs: Any) -> int:
    conn = _conn()
    now = time.time()
    base_cols = ["presentation_id", "slide_number", "created_at"]
    base_vals = [presentation_id, slide_number, now]
    allowed = {
        "all_text", "title_text", "body_text", "footer_text", "notes_text",
        "shape_count", "text_shape_count", "chart_count", "table_count", "image_count",
        "has_chart", "has_table", "has_image", "thumbnail_b64",
        "slide_purpose", "layout_type", "visual_type", "narrative_role", "report_type",
        "industry", "client", "brand", "data_density", "executive_suitability",
        "visual_complexity", "classification_confidence", "detected_project_id",
        "status", "processed_at",
    }
    for k, v in kwargs.items():
        if k in allowed and v is not None:
            base_cols.append(k)
            base_vals.append(v)
    placeholders = ", ".join("?" for _ in base_vals)
    col_str = ", ".join(base_cols)
    cur = conn.execute(
        f"INSERT INTO intel_si_slides ({col_str}) VALUES ({placeholders})", base_vals
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def get_si_slide(slide_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_si_slides WHERE id = ?", (slide_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for bf in ("has_chart", "has_table", "has_image", "is_excluded", "is_template_approved"):
        if bf in d:
            d[bf] = bool(d[bf])
    return d


def list_si_slides(presentation_id: int | None = None, *,
                   slide_purpose: str | None = None, layout_type: str | None = None,
                   visual_type: str | None = None, client: str | None = None,
                   report_type: str | None = None, is_excluded: bool | None = None,
                   search: str | None = None,
                   sort_by: str = "slide_number", sort_dir: str = "ASC",
                   limit: int = 200, offset: int = 0) -> list[dict]:
    conn = _conn()
    clauses, params = [], []
    if presentation_id is not None:
        clauses.append("presentation_id = ?")
        params.append(presentation_id)
    if slide_purpose:
        clauses.append("slide_purpose = ?")
        params.append(slide_purpose)
    if layout_type:
        clauses.append("layout_type = ?")
        params.append(layout_type)
    if visual_type:
        clauses.append("visual_type = ?")
        params.append(visual_type)
    if client:
        clauses.append("client = ?")
        params.append(client)
    if report_type:
        clauses.append("report_type = ?")
        params.append(report_type)
    if is_excluded is not None:
        clauses.append("is_excluded = ?")
        params.append(1 if is_excluded else 0)
    if search:
        clauses.append("(all_text LIKE ? OR title_text LIKE ? OR client LIKE ? OR brand LIKE ?)")
        s = f"%{search}%"
        params.extend([s, s, s, s])
    where = " AND ".join(clauses) if clauses else "1=1"
    valid_sort = {"slide_number", "slide_purpose", "layout_type", "client", "classification_confidence",
                  "created_at", "processed_at"}
    col = sort_by if sort_by in valid_sort else "slide_number"
    direction = "DESC" if sort_dir.upper() == "DESC" else "ASC"
    rows = conn.execute(
        f"SELECT * FROM intel_si_slides WHERE {where} ORDER BY {col} {direction} LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for bf in ("has_chart", "has_table", "has_image", "is_excluded", "is_template_approved"):
            if bf in d:
                d[bf] = bool(d[bf])
        result.append(d)
    return result


def update_si_slide(slide_id: int, **kwargs: Any) -> bool:
    allowed = {
        "all_text", "title_text", "body_text", "footer_text", "notes_text",
        "shape_count", "text_shape_count", "chart_count", "table_count", "image_count",
        "has_chart", "has_table", "has_image", "thumbnail_b64",
        "slide_purpose", "layout_type", "visual_type", "narrative_role", "report_type",
        "industry", "client", "brand", "data_density", "executive_suitability",
        "visual_complexity", "classification_confidence", "detected_project_id",
        "is_excluded", "is_template_approved", "status", "error", "processed_at",
    }
    fields = {}
    for k, v in kwargs.items():
        if k in allowed:
            if k in ("has_chart", "has_table", "has_image", "is_excluded", "is_template_approved"):
                fields[k] = int(v) if isinstance(v, bool) else v
            else:
                fields[k] = v
    if not fields:
        return False
    conn = _conn()
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [slide_id]
    conn.execute(f"UPDATE intel_si_slides SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return True


def delete_si_slide(slide_id: int):
    conn = _conn()
    conn.execute("DELETE FROM intel_si_template_members WHERE slide_id = ?", (slide_id,))
    conn.execute("DELETE FROM intel_si_corrections WHERE slide_id = ?", (slide_id,))
    conn.execute("DELETE FROM intel_si_embeddings WHERE slide_id = ?", (slide_id,))
    conn.execute("DELETE FROM intel_si_storyline_matches WHERE slide_id = ?", (slide_id,))
    conn.execute("DELETE FROM intel_si_slides WHERE id = ?", (slide_id,))
    conn.commit()
    conn.close()


def count_si_slides(presentation_id: int | None = None, **filters) -> int:
    conn = _conn()
    clauses, params = [], []
    if presentation_id is not None:
        clauses.append("presentation_id = ?")
        params.append(presentation_id)
    for k in ("slide_purpose", "layout_type", "visual_type", "client", "status"):
        if k in filters and filters[k] is not None:
            clauses.append(f"{k} = ?")
            params.append(filters[k])
    where = " AND ".join(clauses) if clauses else "1=1"
    cnt = conn.execute(f"SELECT COUNT(*) FROM intel_si_slides WHERE {where}", params).fetchone()[0]
    conn.close()
    return cnt


# ─── Slide Intelligence: Template Families ─────────────────────────────────

def create_si_template_family(family_name: str, typical_layout: str | None = None,
                              typical_visual: str | None = None, typical_purpose: str | None = None,
                              required_inputs: list | None = None,
                              recommended_usage: str | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_template_families "
        "(family_name, typical_layout, typical_visual, typical_purpose, required_inputs, "
        "recommended_usage, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (family_name, typical_layout, typical_visual, typical_purpose,
         json.dumps(required_inputs or []), recommended_usage, now, now),
    )
    fid = cur.lastrowid
    conn.commit()
    conn.close()
    return fid


def get_si_template_family(family_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_si_template_families WHERE id = ?", (family_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["is_approved"] = bool(d.get("is_approved", 0))
    if d.get("required_inputs"):
        try:
            d["required_inputs"] = json.loads(d["required_inputs"])
        except (json.JSONDecodeError, TypeError):
            d["required_inputs"] = []
    return d


def list_si_template_families() -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_si_template_families ORDER BY member_count DESC"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["is_approved"] = bool(d.get("is_approved", 0))
        if d.get("required_inputs"):
            try:
                d["required_inputs"] = json.loads(d["required_inputs"])
            except (json.JSONDecodeError, TypeError):
                d["required_inputs"] = []
        result.append(d)
    return result


def update_si_template_family(family_id: int, **kwargs: Any) -> bool:
    allowed = {"family_name", "typical_layout", "typical_visual", "typical_purpose",
               "required_inputs", "recommended_usage", "member_count", "is_approved"}
    fields = {}
    for k, v in kwargs.items():
        if k in allowed:
            if k == "required_inputs" and isinstance(v, list):
                fields[k] = json.dumps(v)
            elif k == "is_approved" and isinstance(v, bool):
                fields[k] = int(v)
            else:
                fields[k] = v
    if not fields:
        return False
    fields["updated_at"] = time.time()
    conn = _conn()
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [family_id]
    conn.execute(f"UPDATE intel_si_template_families SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return True


def delete_si_template_family(family_id: int):
    conn = _conn()
    conn.execute("DELETE FROM intel_si_template_members WHERE family_id = ?", (family_id,))
    conn.execute("DELETE FROM intel_si_template_families WHERE id = ?", (family_id,))
    conn.commit()
    conn.close()


def add_si_template_member(family_id: int, slide_id: int,
                           is_representative: bool = False,
                           similarity_score: float = 0.0) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_template_members (family_id, slide_id, is_representative, "
        "similarity_score, created_at) VALUES (?, ?, ?, ?, ?)",
        (family_id, slide_id, int(is_representative), similarity_score, now),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def get_si_template_members(family_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT tm.*, s.slide_number, s.title_text, s.slide_purpose, s.layout_type, "
        "s.presentation_id FROM intel_si_template_members tm "
        "JOIN intel_si_slides s ON tm.slide_id = s.id "
        "WHERE tm.family_id = ? ORDER BY tm.is_representative DESC, tm.similarity_score DESC",
        (family_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Slide Intelligence: Detected Projects ─────────────────────────────────

def create_si_detected_project(presentation_id: int, start_slide: int, end_slide: int,
                               project_name: str | None = None, client_name: str | None = None,
                               brand_name: str | None = None, analyst_name: str | None = None,
                               slide_count: int = 0, confidence: float = 0.0) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_detected_projects "
        "(presentation_id, project_name, client_name, brand_name, analyst_name, "
        "start_slide, end_slide, slide_count, confidence, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (presentation_id, project_name, client_name, brand_name, analyst_name,
         start_slide, end_slide, slide_count, confidence, now),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def list_si_detected_projects(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_si_detected_projects WHERE presentation_id = ? "
        "ORDER BY start_slide", (presentation_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_si_detected_project(project_id: int, **kwargs: Any) -> bool:
    allowed = {"project_name", "client_name", "brand_name", "analyst_name",
               "start_slide", "end_slide", "slide_count", "confidence", "is_confirmed"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False
    if "is_confirmed" in fields and isinstance(fields["is_confirmed"], bool):
        fields["is_confirmed"] = int(fields["is_confirmed"])
    conn = _conn()
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [project_id]
    conn.execute(f"UPDATE intel_si_detected_projects SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return True


# ─── Slide Intelligence: Style Patterns ────────────────────────────────────

def add_si_style_pattern(pattern_type: str, pattern_name: str, pattern_data: dict,
                         presentation_id: int | None = None, frequency: int = 1,
                         source_slides: list | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_style_patterns "
        "(presentation_id, pattern_type, pattern_name, pattern_data, frequency, source_slides, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (presentation_id, pattern_type, pattern_name, json.dumps(pattern_data),
         frequency, json.dumps(source_slides or []), now),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def list_si_style_patterns(presentation_id: int | None = None,
                           pattern_type: str | None = None) -> list[dict]:
    conn = _conn()
    clauses, params = [], []
    if presentation_id is not None:
        clauses.append("presentation_id = ?")
        params.append(presentation_id)
    if pattern_type:
        clauses.append("pattern_type = ?")
        params.append(pattern_type)
    where = " AND ".join(clauses) if clauses else "1=1"
    rows = conn.execute(
        f"SELECT * FROM intel_si_style_patterns WHERE {where} ORDER BY frequency DESC", params
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for jf in ("pattern_data", "source_slides"):
            if d.get(jf):
                try:
                    d[jf] = json.loads(d[jf])
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result


# ─── Slide Intelligence: Storyline Matches ─────────────────────────────────

def create_si_storyline_match(storyline_id: int, node_id: int, slide_id: int,
                              similarity_score: float = 0.0, match_reason: str | None = None,
                              recommended_elements: list | None = None,
                              elements_not_to_reuse: list | None = None,
                              recommended_layout: str | None = None,
                              recommended_visual: str | None = None,
                              recommended_chart: str | None = None,
                              confidence: float = 0.0) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_storyline_matches "
        "(storyline_id, node_id, slide_id, similarity_score, match_reason, "
        "recommended_elements, elements_not_to_reuse, recommended_layout, "
        "recommended_visual, recommended_chart, confidence, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (storyline_id, node_id, slide_id, similarity_score, match_reason,
         json.dumps(recommended_elements or []), json.dumps(elements_not_to_reuse or []),
         recommended_layout, recommended_visual, recommended_chart, confidence, now),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def get_si_storyline_matches(storyline_id: int | None = None,
                             node_id: int | None = None) -> list[dict]:
    conn = _conn()
    clauses, params = [], []
    if storyline_id is not None:
        clauses.append("m.storyline_id = ?")
        params.append(storyline_id)
    if node_id is not None:
        clauses.append("m.node_id = ?")
        params.append(node_id)
    where = " AND ".join(clauses) if clauses else "1=1"
    rows = conn.execute(
        f"SELECT m.*, s.slide_number, s.title_text, s.slide_purpose, s.layout_type, "
        f"s.visual_type, s.client, s.presentation_id "
        f"FROM intel_si_storyline_matches m "
        f"JOIN intel_si_slides s ON m.slide_id = s.id "
        f"WHERE {where} ORDER BY m.similarity_score DESC",
        params,
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for jf in ("recommended_elements", "elements_not_to_reuse"):
            if d.get(jf):
                try:
                    d[jf] = json.loads(d[jf])
                except (json.JSONDecodeError, TypeError):
                    pass
        d["is_accepted"] = bool(d.get("is_accepted", 0))
        result.append(d)
    return result


def delete_si_storyline_matches(storyline_id: int | None = None,
                                node_id: int | None = None):
    conn = _conn()
    if node_id is not None:
        conn.execute("DELETE FROM intel_si_storyline_matches WHERE node_id = ?", (node_id,))
    elif storyline_id is not None:
        conn.execute("DELETE FROM intel_si_storyline_matches WHERE storyline_id = ?", (storyline_id,))
    conn.commit()
    conn.close()


# ─── Slide Intelligence: Processing Logs ───────────────────────────────────

def add_si_processing_log(presentation_id: int, step: str, status: str,
                          slide_number: int | None = None, message: str | None = None,
                          duration_ms: float | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_processing_logs "
        "(presentation_id, step, slide_number, status, message, duration_ms, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (presentation_id, step, slide_number, status, message, duration_ms, now),
    )
    lid = cur.lastrowid
    conn.commit()
    conn.close()
    return lid


def get_si_processing_logs(presentation_id: int, limit: int = 200) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_si_processing_logs WHERE presentation_id = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (presentation_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Slide Intelligence: Manual Corrections ────────────────────────────────

def add_si_correction(slide_id: int, field_name: str, new_value: str,
                      old_value: str | None = None, corrected_by: str = "analyst") -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_corrections (slide_id, field_name, old_value, new_value, "
        "corrected_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (slide_id, field_name, old_value, new_value, corrected_by, now),
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid


def get_si_corrections(slide_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_si_corrections WHERE slide_id = ? ORDER BY created_at DESC",
        (slide_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Slide Intelligence: Embeddings ────────────────────────────────────────

def save_si_embedding(slide_id: int, embedding_blob: bytes, model_name: str = "nomic-embed-text"):
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT OR REPLACE INTO intel_si_embeddings (slide_id, embedding_blob, model_name, created_at) "
        "VALUES (?, ?, ?, ?)",
        (slide_id, embedding_blob, model_name, now),
    )
    conn.commit()
    conn.close()


def get_si_embedding(slide_id: int) -> Optional[bytes]:
    conn = _conn()
    row = conn.execute(
        "SELECT embedding_blob FROM intel_si_embeddings WHERE slide_id = ?", (slide_id,)
    ).fetchone()
    conn.close()
    return row["embedding_blob"] if row else None


def get_all_si_embeddings() -> list[dict]:
    conn = _conn()
    rows = conn.execute("SELECT slide_id, embedding_blob FROM intel_si_embeddings").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Slide Intelligence: Retrieval History ─────────────────────────────────

def add_si_retrieval_history(query_text: str, results: list, node_id: int | None = None,
                             storyline_id: int | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_si_retrieval_history "
        "(query_text, node_id, storyline_id, results_json, result_count, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (query_text, node_id, storyline_id, json.dumps(results), len(results), now),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


# ─── Slide Intelligence: Dashboard Aggregates ──────────────────────────────

def get_si_dashboard() -> dict:
    conn = _conn()
    pres_count = conn.execute("SELECT COUNT(*) FROM intel_si_presentations").fetchone()[0]
    slide_count = conn.execute("SELECT COUNT(*) FROM intel_si_slides").fetchone()[0]
    processed = conn.execute(
        "SELECT COUNT(*) FROM intel_si_slides WHERE status = 'processed'"
    ).fetchone()[0]
    excluded = conn.execute(
        "SELECT COUNT(*) FROM intel_si_slides WHERE is_excluded = 1"
    ).fetchone()[0]
    family_count = conn.execute("SELECT COUNT(*) FROM intel_si_template_families").fetchone()[0]
    project_count = conn.execute("SELECT COUNT(*) FROM intel_si_detected_projects").fetchone()[0]
    purpose_counts = {}
    for row in conn.execute(
        "SELECT slide_purpose, COUNT(*) as cnt FROM intel_si_slides "
        "WHERE slide_purpose IS NOT NULL GROUP BY slide_purpose ORDER BY cnt DESC"
    ).fetchall():
        purpose_counts[row["slide_purpose"]] = row["cnt"]
    layout_counts = {}
    for row in conn.execute(
        "SELECT layout_type, COUNT(*) as cnt FROM intel_si_slides "
        "WHERE layout_type IS NOT NULL GROUP BY layout_type ORDER BY cnt DESC"
    ).fetchall():
        layout_counts[row["layout_type"]] = row["cnt"]
    client_counts = {}
    for row in conn.execute(
        "SELECT client, COUNT(*) as cnt FROM intel_si_slides "
        "WHERE client IS NOT NULL GROUP BY client ORDER BY cnt DESC"
    ).fetchall():
        client_counts[row["client"]] = row["cnt"]
    duplicate_count = 0
    conn.close()
    return {
        "presentation_count": pres_count,
        "total_slides": slide_count,
        "processed_slides": processed,
        "excluded_slides": excluded,
        "template_families": family_count,
        "detected_projects": project_count,
        "duplicate_count": duplicate_count,
        "purpose_distribution": purpose_counts,
        "layout_distribution": layout_counts,
        "client_distribution": client_counts,
    }


# ─── Presentation Composer ─────────────────────────────────────────────────

def create_pc_presentation(project_id: int, storyline_id: int, title: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_pc_presentations "
        "(project_id, storyline_id, title, executive_summary, narrative_pattern, "
        "total_slides, estimated_duration_minutes, status, generated_by, generation_id, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, storyline_id, title,
         kw.get("executive_summary"), kw.get("narrative_pattern"),
         kw.get("total_slides", 0), kw.get("estimated_duration_minutes", 0),
         kw.get("status", "draft"), kw.get("generated_by", "system"),
         kw.get("generation_id"), now, now),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_pc_presentation(pres_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_pc_presentations WHERE id=?", (pres_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_pc_presentations(project_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pc_presentations WHERE project_id=? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_pc_presentation(project_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pc_presentations WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_pc_presentation(pres_id: int, **kw) -> None:
    if not kw:
        return
    sets = []
    vals = []
    for k, v in kw.items():
        sets.append(f"{k}=?")
        vals.append(v)
    sets.append("updated_at=?")
    vals.append(time.time())
    vals.append(pres_id)
    conn = _conn()
    conn.execute(
        f"UPDATE intel_pc_presentations SET {', '.join(sets)} WHERE id=?", vals,
    )
    conn.commit()
    conn.close()


def delete_pc_presentation(pres_id: int) -> None:
    conn = _conn()
    conn.execute("DELETE FROM intel_pc_audit WHERE presentation_id=?", (pres_id,))
    conn.execute("DELETE FROM intel_pc_slides WHERE presentation_id=?", (pres_id,))
    conn.execute("DELETE FROM intel_pc_presentations WHERE id=?", (pres_id,))
    conn.commit()
    conn.close()


def create_pc_slide(presentation_id: int, slide_number: int, slide_purpose: str,
                    title: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_pc_slides "
        "(presentation_id, slide_number, slide_purpose, node_id, title, subtitle, "
        "narrative, business_objective, key_message, speaker_notes, "
        "recommended_visual, recommended_chart, layout_recommendation, layout_rationale, "
        "alt_layout_1, alt_layout_1_rationale, alt_layout_2, alt_layout_2_rationale, "
        "template_family_id, content_blocks_json, evidence_ids_json, insight_ids_json, "
        "historical_refs_json, confidence_json, overall_confidence, transition_to_next, "
        "status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (presentation_id, slide_number, slide_purpose,
         kw.get("node_id"), title, kw.get("subtitle"),
         kw.get("narrative"), kw.get("business_objective"), kw.get("key_message"),
         kw.get("speaker_notes"),
         kw.get("recommended_visual"), kw.get("recommended_chart"),
         kw.get("layout_recommendation"), kw.get("layout_rationale"),
         kw.get("alt_layout_1"), kw.get("alt_layout_1_rationale"),
         kw.get("alt_layout_2"), kw.get("alt_layout_2_rationale"),
         kw.get("template_family_id"),
         json.dumps(kw.get("content_blocks", [])),
         json.dumps(kw.get("evidence_ids", [])),
         json.dumps(kw.get("insight_ids", [])),
         json.dumps(kw.get("historical_refs", [])),
         json.dumps(kw.get("confidence", {})),
         kw.get("overall_confidence", 0.5),
         kw.get("transition_to_next"),
         kw.get("status", "draft"), now, now),
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def get_pc_slide(slide_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_pc_slides WHERE id=?", (slide_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for jf in ("content_blocks_json", "evidence_ids_json", "insight_ids_json",
               "historical_refs_json", "confidence_json"):
        if d.get(jf):
            try:
                d[jf] = json.loads(d[jf])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def list_pc_slides(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pc_slides WHERE presentation_id=? ORDER BY slide_number",
        (presentation_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for jf in ("content_blocks_json", "evidence_ids_json", "insight_ids_json",
                    "historical_refs_json", "confidence_json"):
            if d.get(jf):
                try:
                    d[jf] = json.loads(d[jf])
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result


def update_pc_slide(slide_id: int, **kw) -> None:
    if not kw:
        return
    sets = []
    vals = []
    json_fields = {"content_blocks": "content_blocks_json",
                   "evidence_ids": "evidence_ids_json",
                   "insight_ids": "insight_ids_json",
                   "historical_refs": "historical_refs_json",
                   "confidence": "confidence_json"}
    for k, v in kw.items():
        col = json_fields.get(k, k)
        if k in json_fields:
            v = json.dumps(v)
        sets.append(f"{col}=?")
        vals.append(v)
    sets.append("updated_at=?")
    vals.append(time.time())
    vals.append(slide_id)
    conn = _conn()
    conn.execute(f"UPDATE intel_pc_slides SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def delete_pc_slide(slide_id: int) -> None:
    conn = _conn()
    conn.execute("DELETE FROM intel_pc_slides WHERE id=?", (slide_id,))
    conn.commit()
    conn.close()


def reorder_pc_slides(presentation_id: int, slide_ids: list[int]) -> None:
    conn = _conn()
    now = time.time()
    for pos, sid in enumerate(slide_ids):
        conn.execute(
            "UPDATE intel_pc_slides SET slide_number=?, updated_at=? WHERE id=? AND presentation_id=?",
            (pos, now, sid, presentation_id),
        )
    conn.commit()
    conn.close()


def add_pc_audit(presentation_id: int, action: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_pc_audit "
        "(presentation_id, slide_id, action, field, old_value, new_value, actor, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (presentation_id, kw.get("slide_id"), action,
         kw.get("field"), kw.get("old_value"), kw.get("new_value"),
         kw.get("actor", "system"), now),
    )
    aid = cur.lastrowid
    conn.commit()
    conn.close()
    return aid


def get_pc_audit(presentation_id: int, limit: int = 100) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pc_audit WHERE presentation_id=? ORDER BY created_at DESC LIMIT ?",
        (presentation_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_pc_slides(presentation_id: int, status: str | None = None) -> int:
    conn = _conn()
    if status:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM intel_pc_slides WHERE presentation_id=? AND status=?",
            (presentation_id, status),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM intel_pc_slides WHERE presentation_id=?",
            (presentation_id,),
        ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


# ── PowerPoint Renderer store functions ──────────────────────────────

def create_render_job(job_id: str, presentation_id: int, **kw) -> str:
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT INTO intel_render_jobs "
        "(id, presentation_id, job_type, status, progress_pct, progress_message, "
        "slide_ids_json, theme_id, output_path, warnings_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (job_id, presentation_id,
         kw.get("job_type", "full"), kw.get("status", "pending"),
         0, "", json.dumps(kw.get("slide_ids", [])),
         kw.get("theme_id", "hunter_default"),
         kw.get("output_path"), json.dumps([]), now),
    )
    conn.commit()
    conn.close()
    return job_id


def get_render_job(job_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_render_jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for jf in ("slide_ids_json", "warnings_json"):
        if d.get(jf):
            try:
                d[jf] = json.loads(d[jf])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def list_render_jobs(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_render_jobs WHERE presentation_id=? ORDER BY created_at DESC",
        (presentation_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for jf in ("slide_ids_json", "warnings_json"):
            if d.get(jf):
                try:
                    d[jf] = json.loads(d[jf])
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result


def update_render_job(job_id: str, **kw) -> None:
    if not kw:
        return
    sets = []
    vals = []
    json_map = {"slide_ids": "slide_ids_json", "warnings": "warnings_json"}
    for k, v in kw.items():
        col = json_map.get(k, k)
        if k in json_map:
            v = json.dumps(v)
        sets.append(f"{col}=?")
        vals.append(v)
    vals.append(job_id)
    conn = _conn()
    conn.execute(f"UPDATE intel_render_jobs SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def create_rendered_presentation(job_id: str, presentation_id: int,
                                  output_path: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_rendered_presentations "
        "(job_id, presentation_id, version, output_path, output_size_bytes, "
        "slide_count, theme_id, render_duration_ms, metadata_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (job_id, presentation_id,
         kw.get("version", 1), output_path,
         kw.get("output_size_bytes", 0), kw.get("slide_count", 0),
         kw.get("theme_id", "hunter_default"),
         kw.get("render_duration_ms", 0),
         json.dumps(kw.get("metadata", {})), now),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def get_rendered_presentation(rp_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_rendered_presentations WHERE id=?", (rp_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("metadata_json"):
        try:
            d["metadata_json"] = json.loads(d["metadata_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def get_latest_rendered(presentation_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_rendered_presentations WHERE presentation_id=? "
        "ORDER BY created_at DESC LIMIT 1",
        (presentation_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("metadata_json"):
        try:
            d["metadata_json"] = json.loads(d["metadata_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def list_rendered_presentations(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_rendered_presentations WHERE presentation_id=? "
        "ORDER BY created_at DESC",
        (presentation_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("metadata_json"):
            try:
                d["metadata_json"] = json.loads(d["metadata_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def add_render_metric(job_id: str, slide_id: int, slide_number: int,
                      render_type: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_render_metrics "
        "(job_id, slide_id, slide_number, render_type, duration_ms, warnings_json, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (job_id, slide_id, slide_number, render_type,
         kw.get("duration_ms", 0), json.dumps(kw.get("warnings", [])), now),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def get_render_metrics(job_id: str) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_render_metrics WHERE job_id=? ORDER BY slide_number",
        (job_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("warnings_json"):
            try:
                d["warnings_json"] = json.loads(d["warnings_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def create_theme(theme_id: str, name: str, **kw) -> str:
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT OR REPLACE INTO intel_themes "
        "(id, name, description, primary_color, secondary_color, accent_color, "
        "background_color, text_color, font_heading, font_body, "
        "font_size_title, font_size_body, font_size_caption, "
        "logo_position, footer_style, color_palette_json, "
        "is_default, is_active, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (theme_id, name, kw.get("description"),
         kw.get("primary_color", "#5B2C9D"),
         kw.get("secondary_color", "#5E35B1"),
         kw.get("accent_color", "#A6CAEC"),
         kw.get("background_color", "#FFFFFF"),
         kw.get("text_color", "#1A1A1A"),
         kw.get("font_heading", "Calibri"),
         kw.get("font_body", "Calibri"),
         kw.get("font_size_title", 26),
         kw.get("font_size_body", 14),
         kw.get("font_size_caption", 9),
         kw.get("logo_position", "top_right"),
         kw.get("footer_style", "grey_band"),
         json.dumps(kw.get("color_palette", [])),
         1 if kw.get("is_default") else 0,
         1, now, now),
    )
    conn.commit()
    conn.close()
    return theme_id


def get_theme(theme_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_themes WHERE id=?", (theme_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("color_palette_json"):
        try:
            d["color_palette_json"] = json.loads(d["color_palette_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def list_themes(active_only: bool = True) -> list[dict]:
    conn = _conn()
    q = "SELECT * FROM intel_themes"
    if active_only:
        q += " WHERE is_active=1"
    q += " ORDER BY is_default DESC, name"
    rows = conn.execute(q).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("color_palette_json"):
            try:
                d["color_palette_json"] = json.loads(d["color_palette_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def create_template_version(theme_id: str, template_path: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    max_ver = conn.execute(
        "SELECT COALESCE(MAX(version), 0) as mv FROM intel_template_versions WHERE theme_id=?",
        (theme_id,),
    ).fetchone()
    ver = (max_ver["mv"] if max_ver else 0) + 1
    cur = conn.execute(
        "INSERT INTO intel_template_versions (theme_id, version, template_path, changelog, created_at) "
        "VALUES (?,?,?,?,?)",
        (theme_id, ver, template_path, kw.get("changelog"), now),
    )
    tv_id = cur.lastrowid
    conn.commit()
    conn.close()
    return tv_id


def list_template_versions(theme_id: str) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_template_versions WHERE theme_id=? ORDER BY version DESC",
        (theme_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_render_history(presentation_id: int, job_id: str, action: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_render_history "
        "(presentation_id, job_id, action, actor, details_json, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (presentation_id, job_id, action,
         kw.get("actor", "system"),
         json.dumps(kw.get("details", {})), now),
    )
    hid = cur.lastrowid
    conn.commit()
    conn.close()
    return hid


def get_render_history(presentation_id: int, limit: int = 50) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_render_history WHERE presentation_id=? ORDER BY created_at DESC LIMIT ?",
        (presentation_id, limit),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("details_json"):
            try:
                d["details_json"] = json.loads(d["details_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def ensure_default_theme() -> None:
    existing = get_theme("hunter_default")
    if existing:
        return
    create_theme(
        "hunter_default", "Hunter PR Default",
        description="Lavender/violet brand theme from Hunter PR template",
        primary_color="#5B2C9D",
        secondary_color="#5E35B1",
        accent_color="#A6CAEC",
        background_color="#FFFFFF",
        text_color="#1A1A1A",
        font_heading="Calibri",
        font_body="Calibri",
        color_palette=["#5E35B1", "#156082", "#A02B93", "#4EA72E",
                        "#196B24", "#DE2A00", "#A6CAEC", "#D1C4E9"],
        is_default=True,
    )


# ─── Pipeline Orchestrator ─────────────────────────────────────────────────

def create_pipeline_run(run_id: str, project_id: int, **kw) -> str:
    conn = _conn()
    now = time.time()
    conn.execute(
        "INSERT INTO intel_pipeline_runs "
        "(id,project_id,status,execution_mode,current_stage,start_stage,"
        "completed_stages_json,remaining_stages_json,skipped_stages_json,"
        "progress_pct,estimated_remaining_ms,user,started_at,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, project_id,
         kw.get("status", "pending"),
         kw.get("execution_mode", "full"),
         kw.get("current_stage"),
         kw.get("start_stage"),
         json.dumps(kw.get("completed_stages", [])),
         json.dumps(kw.get("remaining_stages", [])),
         json.dumps(kw.get("skipped_stages", [])),
         kw.get("progress_pct", 0),
         kw.get("estimated_remaining_ms", 0),
         kw.get("user", "system"),
         kw.get("started_at", now), now),
    )
    conn.commit()
    conn.close()
    return run_id


def get_pipeline_run(run_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_pipeline_runs WHERE id=?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("completed_stages_json", "remaining_stages_json", "skipped_stages_json"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def list_pipeline_runs(project_id: int, limit: int = 50) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pipeline_runs WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for k in ("completed_stages_json", "remaining_stages_json", "skipped_stages_json"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result


def update_pipeline_run(run_id: str, **kw) -> None:
    parts, vals = [], []
    for col in ("status", "current_stage", "progress_pct",
                "estimated_remaining_ms", "error", "started_at", "completed_at"):
        if col in kw:
            parts.append(f"{col}=?")
            vals.append(kw[col])
    for col in ("completed_stages", "remaining_stages", "skipped_stages"):
        json_col = f"{col}_json"
        if col in kw:
            parts.append(f"{json_col}=?")
            vals.append(json.dumps(kw[col]))
    if not parts:
        return
    vals.append(run_id)
    conn = _conn()
    conn.execute(f"UPDATE intel_pipeline_runs SET {','.join(parts)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def get_latest_pipeline_run(project_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pipeline_runs WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("completed_stages_json", "remaining_stages_json", "skipped_stages_json"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def create_pipeline_stage(run_id: str, stage_id: str, stage_name: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_pipeline_stages "
        "(run_id,stage_id,stage_name,status,version,input_hash,output_hash,"
        "dependencies_json,execution_time_ms,cache_status,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, stage_id, stage_name,
         kw.get("status", "pending"),
         kw.get("version", 1),
         kw.get("input_hash"),
         kw.get("output_hash"),
         json.dumps(kw.get("dependencies", [])),
         kw.get("execution_time_ms", 0),
         kw.get("cache_status", "miss"), now),
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def get_pipeline_stages(run_id: str) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pipeline_stages WHERE run_id=? ORDER BY id ASC",
        (run_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for k in ("dependencies_json", "logs_json", "warnings_json", "errors_json", "result_json"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result


def update_pipeline_stage(run_id: str, stage_id: str, **kw) -> None:
    parts, vals = [], []
    for col in ("status", "input_hash", "output_hash", "execution_time_ms",
                "started_at", "completed_at", "cache_status", "version"):
        if col in kw:
            parts.append(f"{col}=?")
            vals.append(kw[col])
    for col in ("logs", "warnings", "errors", "result", "dependencies"):
        json_col = f"{col}_json"
        if col in kw:
            parts.append(f"{json_col}=?")
            vals.append(json.dumps(kw[col]))
    if not parts:
        return
    vals.extend([run_id, stage_id])
    conn = _conn()
    conn.execute(
        f"UPDATE intel_pipeline_stages SET {','.join(parts)} WHERE run_id=? AND stage_id=?",
        vals,
    )
    conn.commit()
    conn.close()


def get_pipeline_stage(run_id: str, stage_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pipeline_stages WHERE run_id=? AND stage_id=?",
        (run_id, stage_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("dependencies_json", "logs_json", "warnings_json", "errors_json", "result_json"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def set_pipeline_cache(project_id: int, stage_id: str, input_hash: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    conn.execute(
        "DELETE FROM intel_pipeline_cache WHERE project_id=? AND stage_id=?",
        (project_id, stage_id),
    )
    cur = conn.execute(
        "INSERT INTO intel_pipeline_cache "
        "(project_id,stage_id,input_hash,output_hash,version,result_summary_json,created_at,expires_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (project_id, stage_id, input_hash,
         kw.get("output_hash"),
         kw.get("version", 1),
         json.dumps(kw.get("result_summary", {})),
         now, kw.get("expires_at")),
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid


def get_pipeline_cache(project_id: int, stage_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pipeline_cache WHERE project_id=? AND stage_id=? ORDER BY created_at DESC LIMIT 1",
        (project_id, stage_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("result_summary_json"):
        try:
            d["result_summary_json"] = json.loads(d["result_summary_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def clear_pipeline_cache(project_id: int, stage_id: str | None = None) -> int:
    conn = _conn()
    if stage_id:
        cur = conn.execute(
            "DELETE FROM intel_pipeline_cache WHERE project_id=? AND stage_id=?",
            (project_id, stage_id),
        )
    else:
        cur = conn.execute(
            "DELETE FROM intel_pipeline_cache WHERE project_id=?",
            (project_id,),
        )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def list_pipeline_cache(project_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pipeline_cache WHERE project_id=? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("result_summary_json"):
            try:
                d["result_summary_json"] = json.loads(d["result_summary_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def add_pipeline_log(run_id: str, message: str, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_pipeline_logs (run_id,stage_id,level,message,details_json,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (run_id, kw.get("stage_id"), kw.get("level", "info"),
         message, json.dumps(kw.get("details", {})), now),
    )
    lid = cur.lastrowid
    conn.commit()
    conn.close()
    return lid


def get_pipeline_logs(run_id: str, stage_id: str | None = None, limit: int = 200) -> list[dict]:
    conn = _conn()
    if stage_id:
        rows = conn.execute(
            "SELECT * FROM intel_pipeline_logs WHERE run_id=? AND stage_id=? ORDER BY created_at ASC LIMIT ?",
            (run_id, stage_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM intel_pipeline_logs WHERE run_id=? ORDER BY created_at ASC LIMIT ?",
            (run_id, limit),
        ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("details_json"):
            try:
                d["details_json"] = json.loads(d["details_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def add_pipeline_metric(project_id: int, metric_type: str, value: float, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_pipeline_metrics (project_id,stage_id,run_id,metric_type,value,unit,created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (project_id, kw.get("stage_id"), kw.get("run_id"),
         metric_type, value, kw.get("unit", "ms"), now),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def get_pipeline_metrics(project_id: int, run_id: str | None = None) -> list[dict]:
    conn = _conn()
    if run_id:
        rows = conn.execute(
            "SELECT * FROM intel_pipeline_metrics WHERE project_id=? AND run_id=? ORDER BY created_at DESC",
            (project_id, run_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM intel_pipeline_metrics WHERE project_id=? ORDER BY created_at DESC LIMIT 200",
            (project_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pipeline_performance(project_id: int) -> dict:
    conn = _conn()
    runs = conn.execute(
        "SELECT COUNT(*) as total, "
        "AVG(CASE WHEN completed_at IS NOT NULL AND started_at IS NOT NULL "
        "THEN (completed_at - started_at) * 1000 END) as avg_duration_ms, "
        "SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed, "
        "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed "
        "FROM intel_pipeline_runs WHERE project_id=?",
        (project_id,),
    ).fetchone()
    cache_stats = conn.execute(
        "SELECT COUNT(*) as total_entries FROM intel_pipeline_cache WHERE project_id=?",
        (project_id,),
    ).fetchone()
    stage_avgs = conn.execute(
        "SELECT stage_id, AVG(execution_time_ms) as avg_ms, COUNT(*) as runs "
        "FROM intel_pipeline_stages WHERE run_id IN "
        "(SELECT id FROM intel_pipeline_runs WHERE project_id=?) "
        "AND execution_time_ms > 0 GROUP BY stage_id",
        (project_id,),
    ).fetchall()
    cache_hits = conn.execute(
        "SELECT cache_status, COUNT(*) as cnt "
        "FROM intel_pipeline_stages WHERE run_id IN "
        "(SELECT id FROM intel_pipeline_runs WHERE project_id=?) "
        "GROUP BY cache_status",
        (project_id,),
    ).fetchall()
    conn.close()
    hit_map = {r["cache_status"]: r["cnt"] for r in cache_hits}
    total_cache = sum(hit_map.values()) or 1
    return {
        "total_runs": runs["total"] if runs else 0,
        "completed_runs": runs["completed"] if runs else 0,
        "failed_runs": runs["failed"] if runs else 0,
        "avg_duration_ms": runs["avg_duration_ms"] if runs else 0,
        "cache_entries": cache_stats["total_entries"] if cache_stats else 0,
        "cache_hit_ratio": hit_map.get("hit", 0) / total_cache,
        "stage_averages": {r["stage_id"]: {"avg_ms": r["avg_ms"], "runs": r["runs"]} for r in stage_avgs},
        "cache_breakdown": hit_map,
    }


# ─── Word Renderer ───────────────────────────────────────────────────────────

def create_word_job(job_id: str, presentation_id: int, **kw) -> str:
    conn = _conn()
    conn.execute(
        "INSERT INTO intel_word_jobs (id, presentation_id, job_type, status, theme_id, created_at) "
        "VALUES (?, ?, ?, 'pending', ?, ?)",
        (job_id, presentation_id, kw.get("job_type", "full"),
         kw.get("theme_id", "hunter_default"), time.time()),
    )
    conn.commit()
    conn.close()
    return job_id


def get_word_job(job_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_word_jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("sections_json", "warnings_json"):
        if d.get(k) and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def list_word_jobs(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_word_jobs WHERE presentation_id=? ORDER BY created_at DESC",
        (presentation_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for k in ("sections_json", "warnings_json"):
            if d.get(k) and isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result


def update_word_job(job_id: str, **kw) -> None:
    json_map = {"sections": "sections_json", "warnings": "warnings_json"}
    sets, vals = [], []
    for k, v in kw.items():
        col = json_map.get(k, k)
        if k in json_map:
            v = json.dumps(v) if not isinstance(v, str) else v
        sets.append(f"{col}=?")
        vals.append(v)
    if not sets:
        return
    vals.append(job_id)
    conn = _conn()
    conn.execute(f"UPDATE intel_word_jobs SET {','.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def create_word_document(job_id: str, presentation_id: int, output_path: str, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_word_documents "
        "(job_id, presentation_id, output_path, version, output_size_bytes, "
        " section_count, page_count, word_count, theme_id, render_duration_ms, metadata_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, presentation_id, output_path,
         kw.get("version", 1), kw.get("output_size_bytes", 0),
         kw.get("section_count", 0), kw.get("page_count", 0),
         kw.get("word_count", 0), kw.get("theme_id", "hunter_default"),
         kw.get("render_duration_ms", 0),
         json.dumps(kw.get("metadata", {})), time.time()),
    )
    doc_id = cur.lastrowid
    conn.commit()
    conn.close()
    return doc_id


def list_word_documents(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_word_documents WHERE presentation_id=? ORDER BY created_at DESC",
        (presentation_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_word_document(presentation_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_word_documents WHERE presentation_id=? ORDER BY created_at DESC LIMIT 1",
        (presentation_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def add_word_metric(job_id: str, section_name: str, section_number: int,
                    render_type: str = "section", **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_word_metrics "
        "(job_id, section_name, section_number, render_type, duration_ms, element_count, warnings_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, section_name, section_number, render_type,
         kw.get("duration_ms", 0), kw.get("element_count", 0),
         json.dumps(kw.get("warnings", [])), time.time()),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def get_word_metrics(job_id: str) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_word_metrics WHERE job_id=? ORDER BY section_number",
        (job_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("warnings_json") and isinstance(d["warnings_json"], str):
            try:
                d["warnings_json"] = json.loads(d["warnings_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


def add_word_history(presentation_id: int, job_id: str, action: str, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_word_history (presentation_id, job_id, action, actor, details_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (presentation_id, job_id, action,
         kw.get("actor", "system"),
         json.dumps(kw.get("details", {})), time.time()),
    )
    hid = cur.lastrowid
    conn.commit()
    conn.close()
    return hid


def get_word_history(presentation_id: int, limit: int = 50) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_word_history WHERE presentation_id=? ORDER BY created_at DESC LIMIT ?",
        (presentation_id, limit),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("details_json") and isinstance(d["details_json"], str):
            try:
                d["details_json"] = json.loads(d["details_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


# ─── Publishing Gateway ────────────────────────────────────────────────────

def _parse_json_fields(d: dict, fields: list[str]) -> dict:
    for f in fields:
        val = d.get(f)
        if val and isinstance(val, str):
            try:
                d[f] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def create_pub_validation(project_id: int, presentation_id: int, **kw) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_pub_validations "
        "(project_id, presentation_id, status, readiness_score, readiness_class, "
        "scores_json, issues_json, warnings_json, pptx_job_id, word_job_id, "
        "validated_by, started_at, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, presentation_id,
         kw.get("status", "pending"), kw.get("readiness_score", 0),
         kw.get("readiness_class", "draft"),
         json.dumps(kw.get("scores", {})), json.dumps(kw.get("issues", [])),
         json.dumps(kw.get("warnings", [])),
         kw.get("pptx_job_id"), kw.get("word_job_id"),
         kw.get("validated_by", "system"), now, now),
    )
    vid = cur.lastrowid
    conn.commit()
    conn.close()
    return vid


def get_pub_validation(validation_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_pub_validations WHERE id=?",
                       (validation_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_json_fields(dict(row), ["scores_json", "issues_json", "warnings_json"])


def get_latest_pub_validation(presentation_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pub_validations WHERE presentation_id=? ORDER BY created_at DESC LIMIT 1",
        (presentation_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_json_fields(dict(row), ["scores_json", "issues_json", "warnings_json"])


def update_pub_validation(validation_id: int, **kw) -> None:
    if not kw:
        return
    sets, vals = [], []
    json_fields = {"scores": "scores_json", "issues": "issues_json", "warnings": "warnings_json"}
    for k, v in kw.items():
        col = json_fields.get(k, k)
        if k in json_fields:
            v = json.dumps(v)
        sets.append(f"{col}=?")
        vals.append(v)
    vals.append(validation_id)
    conn = _conn()
    conn.execute(f"UPDATE intel_pub_validations SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def list_pub_validations(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pub_validations WHERE presentation_id=? ORDER BY created_at DESC",
        (presentation_id,),
    ).fetchall()
    conn.close()
    return [_parse_json_fields(dict(r), ["scores_json", "issues_json", "warnings_json"]) for r in rows]


def create_pub_diff_report(validation_id: int, project_id: int,
                           presentation_id: int, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_pub_diff_reports "
        "(validation_id, project_id, presentation_id, status, match_pct, "
        "differences_json, summary_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (validation_id, project_id, presentation_id,
         kw.get("status", "pending"), kw.get("match_pct", 0),
         json.dumps(kw.get("differences", [])),
         json.dumps(kw.get("summary", {})), time.time()),
    )
    did = cur.lastrowid
    conn.commit()
    conn.close()
    return did


def get_pub_diff_report(diff_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_pub_diff_reports WHERE id=?",
                       (diff_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_json_fields(dict(row), ["differences_json", "summary_json"])


def get_latest_diff_report(presentation_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pub_diff_reports WHERE presentation_id=? ORDER BY created_at DESC LIMIT 1",
        (presentation_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_json_fields(dict(row), ["differences_json", "summary_json"])


def create_pub_version(project_id: int, presentation_id: int, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_pub_versions "
        "(project_id, presentation_id, major, minor, revision, version_label, "
        "pipeline_version, renderer_version, presentation_version, "
        "approval_status, approved_by, approved_at, notes, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, presentation_id,
         kw.get("major", 1), kw.get("minor", 0), kw.get("revision", 0),
         kw.get("version_label"), kw.get("pipeline_version"),
         kw.get("renderer_version"), kw.get("presentation_version", 1),
         kw.get("approval_status", "draft"), kw.get("approved_by"),
         kw.get("approved_at"), kw.get("notes"), time.time()),
    )
    vid = cur.lastrowid
    conn.commit()
    conn.close()
    return vid


def get_pub_version(version_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_pub_versions WHERE id=?",
                       (version_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_latest_pub_version(presentation_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pub_versions WHERE presentation_id=? ORDER BY created_at DESC LIMIT 1",
        (presentation_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_pub_versions(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pub_versions WHERE presentation_id=? ORDER BY created_at DESC",
        (presentation_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_pub_version(version_id: int, **kw) -> None:
    if not kw:
        return
    sets, vals = [], []
    for k, v in kw.items():
        sets.append(f"{k}=?")
        vals.append(v)
    vals.append(version_id)
    conn = _conn()
    conn.execute(f"UPDATE intel_pub_versions SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def create_pub_package(project_id: int, presentation_id: int, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_pub_packages "
        "(project_id, presentation_id, version_id, validation_id, status, "
        "package_path, package_size_bytes, manifest_json, contents_json, "
        "created_by, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, presentation_id,
         kw.get("version_id"), kw.get("validation_id"),
         kw.get("status", "building"), kw.get("package_path"),
         kw.get("package_size_bytes", 0),
         json.dumps(kw.get("manifest", {})),
         json.dumps(kw.get("contents", [])),
         kw.get("created_by", "system"), time.time()),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_pub_package(package_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_pub_packages WHERE id=?",
                       (package_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_json_fields(dict(row), ["manifest_json", "contents_json"])


def get_latest_pub_package(presentation_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_pub_packages WHERE presentation_id=? ORDER BY created_at DESC LIMIT 1",
        (presentation_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_json_fields(dict(row), ["manifest_json", "contents_json"])


def update_pub_package(package_id: int, **kw) -> None:
    if not kw:
        return
    sets, vals = [], []
    json_fields = {"manifest": "manifest_json", "contents": "contents_json"}
    for k, v in kw.items():
        col = json_fields.get(k, k)
        if k in json_fields:
            v = json.dumps(v)
        sets.append(f"{col}=?")
        vals.append(v)
    vals.append(package_id)
    conn = _conn()
    conn.execute(f"UPDATE intel_pub_packages SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def list_pub_packages(presentation_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pub_packages WHERE presentation_id=? ORDER BY created_at DESC",
        (presentation_id,),
    ).fetchall()
    conn.close()
    return [_parse_json_fields(dict(r), ["manifest_json", "contents_json"]) for r in rows]


def create_pub_approval(project_id: int, presentation_id: int, action: str,
                        status: str, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_pub_approvals "
        "(project_id, presentation_id, version_id, action, status, actor, notes, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (project_id, presentation_id, kw.get("version_id"),
         action, status, kw.get("actor", "system"),
         kw.get("notes"), time.time()),
    )
    aid = cur.lastrowid
    conn.commit()
    conn.close()
    return aid


def list_pub_approvals(presentation_id: int, limit: int = 50) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pub_approvals WHERE presentation_id=? ORDER BY created_at DESC LIMIT ?",
        (presentation_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_pub_download(project_id: int, file_type: str, file_path: str, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_pub_downloads "
        "(project_id, package_id, file_type, file_path, file_size_bytes, downloaded_by, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (project_id, kw.get("package_id"), file_type, file_path,
         kw.get("file_size_bytes", 0), kw.get("downloaded_by", "system"), time.time()),
    )
    did = cur.lastrowid
    conn.commit()
    conn.close()
    return did


def list_pub_downloads(project_id: int, limit: int = 50) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pub_downloads WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_pub_audit(project_id: int, entity_type: str, action: str, **kw) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO intel_pub_audit "
        "(project_id, presentation_id, entity_type, entity_id, action, actor, details_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (project_id, kw.get("presentation_id"), entity_type,
         kw.get("entity_id"), action, kw.get("actor", "system"),
         json.dumps(kw.get("details", {})), time.time()),
    )
    aid = cur.lastrowid
    conn.commit()
    conn.close()
    return aid


def list_pub_audit(project_id: int, limit: int = 100) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_pub_audit WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    conn.close()
    return [_parse_json_fields(dict(r), ["details_json"]) for r in rows]


def get_pub_stats(project_id: int) -> dict:
    conn = _conn()
    val_count = conn.execute(
        "SELECT COUNT(*) FROM intel_pub_validations WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    pkg_count = conn.execute(
        "SELECT COUNT(*) FROM intel_pub_packages WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    ver_count = conn.execute(
        "SELECT COUNT(*) FROM intel_pub_versions WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    dl_count = conn.execute(
        "SELECT COUNT(*) FROM intel_pub_downloads WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    pub_count = conn.execute(
        "SELECT COUNT(*) FROM intel_pub_approvals WHERE project_id=? AND action='publish'",
        (project_id,),
    ).fetchone()[0]
    conn.close()
    return {
        "validations": val_count,
        "packages": pkg_count,
        "versions": ver_count,
        "downloads": dl_count,
        "publications": pub_count,
    }


# ─── Analyst Orientation Briefs ─────────────────────────────────────────────

def save_background_brief(project_id: int, research_id: int, brief: dict) -> int:
    conn = _conn()
    now = time.time()
    existing = conn.execute(
        "SELECT MAX(version) as v FROM intel_background_briefs WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    version = (existing["v"] or 0) + 1
    cur = conn.execute(
        "INSERT INTO intel_background_briefs (project_id, research_id, version, brief_json, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'draft', ?, ?)",
        (project_id, research_id, version, json.dumps(brief), now, now),
    )
    bid = cur.lastrowid
    conn.commit()
    conn.close()
    return bid


def get_latest_brief(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_background_briefs WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["brief"] = json.loads(d["brief_json"])
    return d


def get_brief_by_id(brief_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM intel_background_briefs WHERE id = ?", (brief_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["brief"] = json.loads(d["brief_json"])
    return d


def update_brief(brief_id: int, brief: dict):
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_briefs SET brief_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(brief), time.time(), brief_id),
    )
    conn.commit()
    conn.close()


def update_brief_section(brief_id: int, section_key: str, content: str, analyst_note: str = ""):
    conn = _conn()
    now = time.time()
    row = conn.execute("SELECT brief_json FROM intel_background_briefs WHERE id = ?", (brief_id,)).fetchone()
    if row:
        brief = json.loads(row["brief_json"])
        if section_key in brief.get("sections", {}):
            brief["sections"][section_key]["content"] = content
            brief["sections"][section_key]["edited"] = True
            conn.execute(
                "UPDATE intel_background_briefs SET brief_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(brief), now, brief_id),
            )
        conn.execute(
            "INSERT INTO intel_brief_section_edits (brief_id, section_key, edited_content, analyst_note, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (brief_id, section_key, content, analyst_note, now),
        )
    conn.commit()
    conn.close()


def approve_brief(brief_id: int, reviewer: str = "analyst") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_briefs SET approval_status = 'approved', approved_by = ?, approved_at = ?, updated_at = ? WHERE id = ?",
        (reviewer, time.time(), time.time(), brief_id),
    )
    conn.commit()
    conn.close()
    return True


def reject_brief(brief_id: int, notes: str = "") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_briefs SET approval_status = 'revision_requested', notes = ?, updated_at = ? WHERE id = ?",
        (notes, time.time(), brief_id),
    )
    conn.commit()
    conn.close()
    return True


def update_brief_docx(brief_id: int, docx_path: str):
    conn = _conn()
    conn.execute(
        "UPDATE intel_background_briefs SET docx_path = ?, docx_generated_at = ?, updated_at = ? WHERE id = ?",
        (docx_path, time.time(), time.time(), brief_id),
    )
    conn.commit()
    conn.close()


def list_brief_versions(project_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT id, version, status, approval_status, docx_path, created_at, updated_at FROM intel_background_briefs "
        "WHERE project_id = ? ORDER BY version DESC",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Project Spec Update ──────────────────────────────────────────────────────

def update_project_spec(project_id: int, spec: dict) -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE intel_projects SET spec_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(spec), time.time(), project_id),
    )
    conn.commit()
    conn.close()
    return True


# ─── Research Specifications ──────────────────────────────────────────────────

SPEC_SECTION_ORDER = [
    "project_understanding",
    "business_objective",
    "research_objectives",
    "research_questions",
    "scope_dimensions",
    "entities",
    "audiences",
    "inclusions",
    "exclusions",
    "methodology",
    "question_method_mapping",
    "data_requirements",
    "metrics",
    "deliverables",
    "assumptions",
    "clarifications",
    "risks",
    "dependencies",
    "success_criteria",
    "approval_status",
]


def save_research_spec(
    project_id: int,
    spec: dict,
    raw_brief_text: str = "",
    generation_source: str = "manual",
    llm_model: str = "",
) -> int:
    conn = _conn()
    now = time.time()
    existing = conn.execute(
        "SELECT MAX(version) as v FROM intel_research_specifications WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    version = (existing["v"] or 0) + 1
    readiness = _compute_readiness(spec)
    cur = conn.execute(
        "INSERT INTO intel_research_specifications "
        "(project_id, version, spec_json, raw_brief_text, status, readiness_status, readiness_json, "
        "generation_source, llm_model, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?)",
        (
            project_id, version, json.dumps(spec), raw_brief_text,
            readiness["status"], json.dumps(readiness),
            generation_source, llm_model, now, now,
        ),
    )
    spec_id = cur.lastrowid
    for key in SPEC_SECTION_ORDER:
        conn.execute(
            "INSERT INTO intel_spec_section_approvals "
            "(spec_id, section_key, status, created_at, updated_at) VALUES (?, ?, 'draft', ?, ?)",
            (spec_id, key, now, now),
        )
    conn.commit()
    conn.close()
    return spec_id


def get_latest_spec(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_research_specifications WHERE project_id = ? ORDER BY version DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    d["spec"] = json.loads(d["spec_json"])
    d["readiness"] = json.loads(d["readiness_json"]) if d.get("readiness_json") else None
    section_rows = conn.execute(
        "SELECT * FROM intel_spec_section_approvals WHERE spec_id = ?", (d["id"],)
    ).fetchall()
    d["section_approvals"] = {r["section_key"]: dict(r) for r in section_rows}
    clar_rows = conn.execute(
        "SELECT * FROM intel_spec_clarifications WHERE spec_id = ? ORDER BY created_at",
        (d["id"],),
    ).fetchall()
    d["clarifications"] = [dict(r) for r in clar_rows]
    conn.close()
    return d


def get_spec_by_id(spec_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM intel_research_specifications WHERE id = ?", (spec_id,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    d["spec"] = json.loads(d["spec_json"])
    d["readiness"] = json.loads(d["readiness_json"]) if d.get("readiness_json") else None
    section_rows = conn.execute(
        "SELECT * FROM intel_spec_section_approvals WHERE spec_id = ?", (spec_id,)
    ).fetchall()
    d["section_approvals"] = {r["section_key"]: dict(r) for r in section_rows}
    clar_rows = conn.execute(
        "SELECT * FROM intel_spec_clarifications WHERE spec_id = ? ORDER BY created_at",
        (spec_id,),
    ).fetchall()
    d["clarifications"] = [dict(r) for r in clar_rows]
    conn.close()
    return d


def update_spec(spec_id: int, spec: dict) -> bool:
    conn = _conn()
    now = time.time()
    readiness = _compute_readiness(spec)
    conn.execute(
        "UPDATE intel_research_specifications SET spec_json = ?, readiness_status = ?, "
        "readiness_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(spec), readiness["status"], json.dumps(readiness), now, spec_id),
    )
    conn.commit()
    conn.close()
    return True


def update_spec_section(
    spec_id: int, section_key: str, content: Any, analyst_note: str = "", actor: str = "analyst"
) -> bool:
    conn = _conn()
    now = time.time()
    row = conn.execute(
        "SELECT spec_json FROM intel_research_specifications WHERE id = ?", (spec_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    spec = json.loads(row["spec_json"])
    sections = spec.get("sections", {})
    old_value = json.dumps(sections.get(section_key, {}).get("content", ""))
    if section_key in sections:
        sections[section_key]["content"] = content
        sections[section_key]["edited"] = True
    else:
        sections[section_key] = {"title": section_key, "content": content, "edited": True}
    spec["sections"] = sections
    readiness = _compute_readiness(spec)
    conn.execute(
        "UPDATE intel_research_specifications SET spec_json = ?, readiness_status = ?, "
        "readiness_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(spec), readiness["status"], json.dumps(readiness), now, spec_id),
    )
    sa_row = conn.execute(
        "SELECT id FROM intel_spec_section_approvals WHERE spec_id = ? AND section_key = ?",
        (spec_id, section_key),
    ).fetchone()
    if sa_row:
        conn.execute(
            "UPDATE intel_spec_section_approvals SET edited_content = ?, analyst_note = ?, "
            "status = 'edited', updated_at = ? WHERE id = ?",
            (json.dumps(content) if not isinstance(content, str) else content, analyst_note, now, sa_row["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO intel_spec_section_approvals "
            "(spec_id, section_key, status, edited_content, analyst_note, created_at, updated_at) "
            "VALUES (?, ?, 'edited', ?, ?, ?, ?)",
            (spec_id, section_key, json.dumps(content) if not isinstance(content, str) else content, analyst_note, now, now),
        )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, section_key, old_value, new_value, actor, created_at) "
        "VALUES (?, 'section_edit', ?, ?, ?, ?, ?)",
        (spec_id, section_key, old_value, json.dumps(content) if not isinstance(content, str) else content, actor, now),
    )
    conn.commit()
    conn.close()
    return True


def approve_spec_section(
    spec_id: int, section_key: str, reviewer: str = "analyst"
) -> bool:
    conn = _conn()
    now = time.time()
    conn.execute(
        "UPDATE intel_spec_section_approvals SET status = 'approved', reviewed_by = ?, "
        "reviewed_at = ?, updated_at = ? WHERE spec_id = ? AND section_key = ?",
        (reviewer, now, now, spec_id, section_key),
    )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, section_key, new_value, actor, created_at) "
        "VALUES (?, 'section_approved', ?, 'approved', ?, ?)",
        (spec_id, section_key, reviewer, now),
    )
    conn.commit()
    conn.close()
    return True


def lock_spec_section(
    spec_id: int, section_key: str, locked_by: str = "analyst"
) -> bool:
    conn = _conn()
    now = time.time()
    conn.execute(
        "UPDATE intel_spec_section_approvals SET is_locked = 1, locked_by = ?, "
        "locked_at = ?, updated_at = ? WHERE spec_id = ? AND section_key = ?",
        (locked_by, now, now, spec_id, section_key),
    )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, section_key, new_value, actor, created_at) "
        "VALUES (?, 'section_locked', ?, 'locked', ?, ?)",
        (spec_id, section_key, locked_by, now),
    )
    conn.commit()
    conn.close()
    return True


def unlock_spec_section(
    spec_id: int, section_key: str, actor: str = "analyst"
) -> bool:
    conn = _conn()
    now = time.time()
    conn.execute(
        "UPDATE intel_spec_section_approvals SET is_locked = 0, locked_by = NULL, "
        "locked_at = NULL, updated_at = ? WHERE spec_id = ? AND section_key = ?",
        (now, spec_id, section_key),
    )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, section_key, new_value, actor, created_at) "
        "VALUES (?, 'section_unlocked', ?, 'unlocked', ?, ?)",
        (spec_id, section_key, actor, now),
    )
    conn.commit()
    conn.close()
    return True


def approve_full_spec(spec_id: int, reviewer: str = "analyst") -> bool:
    conn = _conn()
    now = time.time()
    row = conn.execute(
        "SELECT readiness_json FROM intel_research_specifications WHERE id = ?", (spec_id,)
    ).fetchone()
    if row and row["readiness_json"]:
        readiness = json.loads(row["readiness_json"])
        if readiness.get("blocking_issues"):
            conn.close()
            return False
    conn.execute(
        "UPDATE intel_research_specifications SET approval_status = 'approved', "
        "approved_by = ?, approved_at = ?, status = 'approved', updated_at = ? WHERE id = ?",
        (reviewer, now, now, spec_id),
    )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, new_value, actor, created_at) "
        "VALUES (?, 'spec_approved', 'approved', ?, ?)",
        (spec_id, reviewer, now),
    )
    conn.commit()
    conn.close()
    return True


def reject_spec(spec_id: int, reason: str = "", reviewer: str = "analyst") -> bool:
    conn = _conn()
    now = time.time()
    conn.execute(
        "UPDATE intel_research_specifications SET approval_status = 'revision_requested', "
        "rejected_reason = ?, status = 'revision_requested', updated_at = ? WHERE id = ?",
        (reason, now, spec_id),
    )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, new_value, actor, created_at) "
        "VALUES (?, 'spec_rejected', ?, ?, ?)",
        (spec_id, reason, reviewer, now),
    )
    conn.commit()
    conn.close()
    return True


def update_spec_docx(spec_id: int, docx_path: str):
    conn = _conn()
    now = time.time()
    conn.execute(
        "UPDATE intel_research_specifications SET docx_path = ?, docx_generated_at = ?, updated_at = ? WHERE id = ?",
        (docx_path, now, now, spec_id),
    )
    conn.commit()
    conn.close()


def list_spec_versions(project_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT id, version, status, readiness_status, approval_status, generation_source, "
        "docx_path, created_at, updated_at FROM intel_research_specifications "
        "WHERE project_id = ? ORDER BY version DESC",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_spec_audit(spec_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM intel_spec_audit WHERE spec_id = ? ORDER BY created_at DESC",
        (spec_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Research Spec Clarifications ─────────────────────────────────────────────

def add_clarification(
    spec_id: int, question: str, section_key: str = "", is_blocking: bool = True
) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO intel_spec_clarifications "
        "(spec_id, section_key, question, is_blocking, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (spec_id, section_key, question, 1 if is_blocking else 0, now, now),
    )
    cid = cur.lastrowid
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, section_key, new_value, actor, created_at) "
        "VALUES (?, 'clarification_added', ?, ?, 'system', ?)",
        (spec_id, section_key, question, now),
    )
    _recompute_and_save_readiness(conn, spec_id, now)
    conn.commit()
    conn.close()
    return cid


def resolve_clarification(
    clarification_id: int, answer: str, resolved_by: str = "analyst"
) -> bool:
    conn = _conn()
    now = time.time()
    row = conn.execute(
        "SELECT spec_id, question FROM intel_spec_clarifications WHERE id = ?",
        (clarification_id,),
    ).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        "UPDATE intel_spec_clarifications SET answer = ?, resolved_by = ?, "
        "resolved_at = ?, updated_at = ? WHERE id = ?",
        (answer, resolved_by, now, now, clarification_id),
    )
    conn.execute(
        "INSERT INTO intel_spec_audit (spec_id, action, old_value, new_value, actor, created_at) "
        "VALUES (?, 'clarification_resolved', ?, ?, ?, ?)",
        (row["spec_id"], row["question"], answer, resolved_by, now),
    )
    _recompute_and_save_readiness(conn, row["spec_id"], now)
    conn.commit()
    conn.close()
    return True


def get_clarifications(spec_id: int, unresolved_only: bool = False) -> list[dict]:
    conn = _conn()
    sql = "SELECT * FROM intel_spec_clarifications WHERE spec_id = ?"
    if unresolved_only:
        sql += " AND resolved_at IS NULL"
    sql += " ORDER BY created_at"
    rows = conn.execute(sql, (spec_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Readiness Engine ─────────────────────────────────────────────────────────

MANDATORY_SECTIONS = [
    "project_understanding",
    "business_objective",
    "research_objectives",
    "research_questions",
    "scope_dimensions",
    "entities",
    "methodology",
    "data_requirements",
    "deliverables",
    "success_criteria",
]


def _compute_readiness(spec: dict) -> dict:
    sections = spec.get("sections", {})
    blocking_issues: list[str] = []
    warnings: list[str] = []
    section_status: dict[str, str] = {}

    for key in MANDATORY_SECTIONS:
        sec = sections.get(key, {})
        content = sec.get("content", "")
        if not content or (isinstance(content, str) and not content.strip()):
            blocking_issues.append(f"Mandatory section '{key}' is empty")
            section_status[key] = "empty"
        else:
            section_status[key] = "filled"

    rqs = sections.get("research_questions", {}).get("content", [])
    if isinstance(rqs, list) and len(rqs) == 0:
        blocking_issues.append("No research questions defined")
    elif isinstance(rqs, str) and not rqs.strip():
        blocking_issues.append("No research questions defined")

    entities_content = sections.get("entities", {}).get("content", [])
    if isinstance(entities_content, list) and len(entities_content) == 0:
        blocking_issues.append("No entities identified")

    for key in SPEC_SECTION_ORDER:
        if key not in section_status:
            sec = sections.get(key, {})
            content = sec.get("content", "")
            if not content or (isinstance(content, str) and not content.strip()):
                if key not in MANDATORY_SECTIONS:
                    warnings.append(f"Optional section '{key}' is empty")
                    section_status[key] = "empty"
            else:
                section_status[key] = "filled"

    filled_count = sum(1 for v in section_status.values() if v == "filled")
    total_count = len(SPEC_SECTION_ORDER)

    status = "ready" if not blocking_issues else "not_ready"
    return {
        "status": status,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "section_status": section_status,
        "filled_count": filled_count,
        "total_count": total_count,
        "completeness_pct": round((filled_count / total_count) * 100) if total_count else 0,
    }


def _recompute_and_save_readiness(conn: sqlite3.Connection, spec_id: int, now: float):
    row = conn.execute(
        "SELECT spec_json FROM intel_research_specifications WHERE id = ?", (spec_id,)
    ).fetchone()
    if not row:
        return
    spec = json.loads(row["spec_json"])
    readiness = _compute_readiness(spec)
    unresolved = conn.execute(
        "SELECT COUNT(*) as cnt FROM intel_spec_clarifications "
        "WHERE spec_id = ? AND is_blocking = 1 AND resolved_at IS NULL",
        (spec_id,),
    ).fetchone()
    if unresolved and unresolved["cnt"] > 0:
        readiness["blocking_issues"].append(
            f"{unresolved['cnt']} unresolved blocking clarification(s)"
        )
        readiness["status"] = "not_ready"
    conn.execute(
        "UPDATE intel_research_specifications SET readiness_status = ?, readiness_json = ?, updated_at = ? WHERE id = ?",
        (readiness["status"], json.dumps(readiness), now, spec_id),
    )


def get_spec_readiness(spec_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT spec_json, readiness_json FROM intel_research_specifications WHERE id = ?",
        (spec_id,),
    ).fetchone()
    if not row:
        conn.close()
        return None
    spec = json.loads(row["spec_json"])
    readiness = _compute_readiness(spec)
    unresolved = conn.execute(
        "SELECT COUNT(*) as cnt FROM intel_spec_clarifications "
        "WHERE spec_id = ? AND is_blocking = 1 AND resolved_at IS NULL",
        (spec_id,),
    ).fetchone()
    conn.close()
    if unresolved and unresolved["cnt"] > 0:
        readiness["blocking_issues"].append(
            f"{unresolved['cnt']} unresolved blocking clarification(s)"
        )
        readiness["status"] = "not_ready"
    return readiness


# ─── QC Reports ─────────────────────────────────────────────────────────────

def create_qc_report(project_id: int, file_name: str, file_path: str) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO qc_reports (project_id, file_name, file_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (project_id, file_name, file_path, now, now),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def update_qc_report(report_id: int, **kwargs) -> None:
    conn = _conn()
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in ("row_count", "column_count", "columns_json", "field_mapping", "parse_status", "parse_error"):
            sets.append(f"{k} = ?")
            vals.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
    if sets:
        sets.append("updated_at = ?")
        vals.append(time.time())
        vals.append(report_id)
        conn.execute(f"UPDATE qc_reports SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()
    conn.close()


def get_qc_report(report_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM qc_reports WHERE id = ?", (report_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("columns_json", "field_mapping"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def get_qc_report_for_project(project_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM qc_reports WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for k in ("columns_json", "field_mapping"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def save_qc_field_mapping(report_id: int, mapping: dict) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE qc_reports SET field_mapping = ?, updated_at = ? WHERE id = ?",
        (json.dumps(mapping), time.time(), report_id),
    )
    conn.commit()
    conn.close()


# ─── QC Runs ────────────────────────────────────────────────────────────────

def create_qc_run(report_id: int) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO qc_runs (report_id, status, created_at) VALUES (?, 'pending', ?)",
        (report_id, now),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def update_qc_run(run_id: int, **kwargs) -> None:
    conn = _conn()
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in ("status", "total_rows", "total_checks", "total_findings", "score", "score_breakdown", "started_at", "completed_at"):
            sets.append(f"{k} = ?")
            vals.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
    if sets:
        vals.append(run_id)
        conn.execute(f"UPDATE qc_runs SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()
    conn.close()


def get_qc_run(run_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute("SELECT * FROM qc_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("score_breakdown"):
        try:
            d["score_breakdown"] = json.loads(d["score_breakdown"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def get_qc_runs_for_report(report_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM qc_runs WHERE report_id = ? ORDER BY created_at DESC", (report_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── QC Findings ────────────────────────────────────────────────────────────

def add_qc_finding(run_id: int, report_id: int, check_type: str, severity: str,
                   message: str, row_number: int | None = None, column_name: str | None = None,
                   expected: str | None = None, actual: str | None = None,
                   source_url: str | None = None) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO qc_findings (run_id, report_id, check_type, row_number, column_name, severity, message, expected, actual, source_url, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, report_id, check_type, row_number, column_name, severity, message, expected, actual, source_url, now),
    )
    fid = cur.lastrowid
    conn.commit()
    conn.close()
    return fid


def add_qc_findings_batch(findings: list[dict]) -> int:
    if not findings:
        return 0
    conn = _conn()
    now = time.time()
    rows = [
        (f["run_id"], f["report_id"], f["check_type"], f.get("row_number"),
         f.get("column_name"), f["severity"], f["message"],
         f.get("expected"), f.get("actual"), f.get("source_url"), now)
        for f in findings
    ]
    conn.executemany(
        "INSERT INTO qc_findings (run_id, report_id, check_type, row_number, column_name, severity, message, expected, actual, source_url, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def get_qc_findings(run_id: int, severity: str | None = None, check_type: str | None = None) -> list[dict]:
    conn = _conn()
    sql = "SELECT * FROM qc_findings WHERE run_id = ?"
    params: list = [run_id]
    if severity:
        sql += " AND severity = ?"
        params.append(severity)
    if check_type:
        sql += " AND check_type = ?"
        params.append(check_type)
    sql += " ORDER BY row_number ASC, severity ASC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_qc_finding_action(finding_id: int, action: str) -> None:
    conn = _conn()
    conn.execute("UPDATE qc_findings SET analyst_action = ? WHERE id = ?", (action, finding_id))
    conn.commit()
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

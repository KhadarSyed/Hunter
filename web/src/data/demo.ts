export interface ProjectSummary {
  name: string;
  client: string;
  status: string;
  stage: string;
  progress: number;
  gate: string;
  lastUpdated: string;
  researchType: string;
  geography: string;
  timePeriod: string;
}

export const DEMO_PROJECT: ProjectSummary = {
  name: "Sample Research Project",
  client: "",
  status: "In Progress",
  stage: "Research Planning",
  progress: 32,
  gate: "Scope Approved",
  lastUpdated: "2 mins ago",
  researchType: "Social Listening · Audience Insights",
  geography: "United States",
  timePeriod: "Past 12 months",
};

export const DEMO_BRIEF = ``;

export const DEMO_SPEC = {
  executive_interpretation:
    "The client wants to understand broader social conversations among moms on social media — their priorities, tensions, coping strategies, food-preparation behaviours, and language — segmented by life stage (young children vs. teenagers). This is an audience insight study, not a brand-tracking exercise.",
  commissioning_brand: { name: "Sample Brand", role: "Strategic context and funding client" },
  research_subject: {
    description:
      "Broader social conversations among moms on US social media over the past 12 months — their priorities, tensions, food-preparation behaviours, and consumer language.",
    is_brand_study: false,
  },
  research_audience: {
    description: "US Moms discussing parenting, daily life, food preparation, and family management on social media platforms.",
  },
  strategic_application:
    "Findings will inform audience strategy, content positioning, and product messaging by revealing how the target audience talks about key topics in their own words.",
  business_objective:
    "Understand how moms prioritise their lives, identify the themes and tensions they discuss, and determine whether these differ between moms of young children and moms of teenagers.",
  research_objective:
    "Analyse social media conversations among US moms to map priorities, tensions, resolution strategies, food-preparation behaviours, simplification patterns, and consumer language — segmented by child age group.",
  deliverable_objective:
    "A qualitative research report with thematic analysis, life-stage comparison, food-behaviour mapping, and a consumer language glossary — supported by verbatims and platform evidence.",
  validated_entities: [
    { name: "Sample Brand", type: "brand", confidence: "high" as const, reasoning: "Identified as the brand commissioning the research." },
    { name: "US Moms", type: "audience", confidence: "high" as const, reasoning: "Brief explicitly names moms as the research audience, scoped to the United States." },
  ],
  research_questions: [
    { id: "RQ1", question: "What are moms' priorities?", priority: "primary" as const, source: "explicit" as const },
    { id: "RQ2", question: "What are the key themes and tensions being discussed?", priority: "primary" as const, source: "explicit" as const },
    { id: "RQ3", question: "How are those tensions resolved?", priority: "primary" as const, source: "explicit" as const },
    { id: "RQ4", question: "Are themes and tensions different for moms with young children vs. older children?", priority: "primary" as const, source: "explicit" as const },
    { id: "RQ5", question: "How are moms simplifying their lives?", priority: "primary" as const, source: "explicit" as const },
    { id: "RQ6", question: "What role does food preparation play?", priority: "primary" as const, source: "explicit" as const },
    { id: "RQ7", question: "What colloquialisms or distinctive phrases are moms using?", priority: "primary" as const, source: "explicit" as const },
    { id: "RQ8", question: "Do priorities differ between moms of young children and moms of teenagers?", priority: "secondary" as const, source: "inferred" as const },
  ],
  included_scope: {
    platforms: ["Social media"],
    geography: "United States",
    audience: "Moms",
    time_period: "Past 12 months",
    languages: ["English"],
    content_types: ["Social media conversations"],
    segments: [
      { id: "A1", name: "Moms of young children", role: "Primary segment" },
      { id: "A2", name: "Moms of teenagers / older children", role: "Comparison segment" },
    ],
    deliverables: ["Qualitative research report"],
  },
  excluded_scope: [
    { item: "Sentiment Analysis / Sentiment Scoring", reason: "Brief explicitly excludes", severity: "hard" as const },
    { item: "Share of Voice", reason: "Not a brand-tracking study", severity: "hard" as const },
    { item: "Competitor Benchmarking", reason: "Not in scope", severity: "hard" as const },
    { item: "Brand Sentiment", reason: "Not a brand-sentiment study", severity: "hard" as const },
    { item: "Brand Perception Analysis", reason: "Not a brand-tracking study", severity: "hard" as const },
    { item: "Editorial / News Coverage", reason: "Social media only", severity: "hard" as const },
    { item: "Generic Market Analysis", reason: "Not requested", severity: "hard" as const },
    { item: "Unsupported Demographic Claims", reason: "Requires evidence", severity: "hard" as const },
    { item: "Unsupported Quantitative Metrics", reason: "Requires evidence", severity: "hard" as const },
    { item: "Charts Without Underlying Data", reason: "Requires evidence", severity: "hard" as const },
  ],
  methodology: {
    primary: "Qualitative Analysis",
    reasoning: "Thematic and narrative analysis allows understanding of mom conversations in their own words, without imposing quantitative scoring the brief explicitly excludes.",
  },
  confidence: { overall: "high" as const, entity: "high" as const, scope: "high" as const, methodology: "high" as const },
  validation: { errors: 0, warnings: 0, status: "passed" as const },
};

export const DEMO_ANALYSIS_STEPS = [
  { label: "Reading brief", status: "completed" as const },
  { label: "Extracting entities", status: "completed" as const },
  { label: "Understanding objective", status: "completed" as const },
  { label: "Finding audience", status: "completed" as const },
  { label: "Validating scope", status: "completed" as const },
  { label: "Building project specification", status: "completed" as const },
  { label: "Running validation", status: "completed" as const },
];

export const DEMO_WORKFLOW_STAGES = [
  { id: "understanding", label: "Understanding", status: "completed" as const, progress: 100, owner: "Brief & Scope Agent", inputs: "Client brief (1,162 chars)", outputs: "Project Specification", approval: "Gate 1 — Approved" },
  { id: "background", label: "Background", status: "completed" as const, progress: 100, owner: "Brand Intelligence", inputs: "Approved Specification", outputs: "Brand & Issue Research", approval: "Approved" },
  { id: "search-strategy", label: "Search Strategy", status: "completed" as const, progress: 100, owner: "Query Builder", inputs: "Spec + Brand Intelligence", outputs: "Meltwater Queries", approval: "Gate — Approved" },
  { id: "data-collection", label: "Data Collection", status: "completed" as const, progress: 100, owner: "Data Source Manager", inputs: "Approved Queries", outputs: "Meltwater Dataset", approval: "Dataset Validated" },
  { id: "planning", label: "Planning", status: "completed" as const, progress: 100, owner: "Research Planner", inputs: "Spec + Dataset + Background", outputs: "Research Plan (10 objectives)", approval: "Gate — Approved" },
  { id: "researching", label: "Researching", status: "pending" as const, progress: 0, owner: "Research Executor", inputs: "Research Plan + Dataset", outputs: "Evidence Collection", approval: "Pending" },
  { id: "synthesizing", label: "Synthesizing", status: "pending" as const, progress: 0, owner: "Insight Agent", inputs: "Evidence Collection", outputs: "Insights & Themes", approval: "Pending" },
  { id: "storylining", label: "Storylining", status: "pending" as const, progress: 0, owner: "Storyline Agent", inputs: "Insights & Themes", outputs: "Narrative Structure", approval: "Pending" },
  { id: "designing", label: "Designing", status: "pending" as const, progress: 0, owner: "Deck Builder", inputs: "Narrative Structure", outputs: "Presentation Deck", approval: "Pending" },
  { id: "quality", label: "Quality Review", status: "pending" as const, progress: 0, owner: "QA Agent", inputs: "Final Deck", outputs: "Approved Deliverable", approval: "Pending" },
];

export const DEMO_RECENT_ACTIVITY = [
  { time: "2 mins ago", action: "Research Plan approved", detail: "10 objectives across 6 platforms" },
  { time: "12 mins ago", action: "Research Plan generated", detail: "Planner completed in 6m 12s" },
  { time: "24 mins ago", action: "Scope approved at Gate 1", detail: "8 research questions validated" },
  { time: "29 mins ago", action: "Brief analysis completed", detail: "1 attempt, 0 errors, 0 warnings" },
  { time: "30 mins ago", action: "Project created", detail: "Sample Research Project" },
];

export interface ResearchObjective {
  id: string;
  objective: string;
  why: string;
  questionIds: string[];
  priority: "high" | "medium" | "low";
  platforms: { name: string; justification: string }[];
  evidence: string[];
  methods: string[];
  deliverable: string;
  confidence: "high" | "medium" | "low";
  complexity: "high" | "medium" | "low";
  status: "completed" | "in_progress" | "pending";
  searchConcepts: string[];
}

export const DEMO_RESEARCH_OBJECTIVES: ResearchObjective[] = [
  {
    id: "RO1", objective: "Identify the priorities and daily concerns moms discuss most frequently on social media",
    why: "Core question — understanding what matters most to moms anchors every subsequent insight",
    questionIds: ["RQ1", "RQ2"], priority: "high",
    platforms: [
      { name: "Reddit", justification: "Long-form r/Mommit and r/Parenting discussions reveal authentic priorities" },
      { name: "Facebook", justification: "Community groups show daily concerns and peer advice" },
      { name: "X", justification: "Real-time reactions surface what's top-of-mind" },
    ],
    evidence: ["Recurring discussion themes with examples", "High-engagement posts showing resonance", "Consumer verbatims expressing priorities"],
    methods: ["Thematic Analysis", "Conversation Mapping"],
    deliverable: "Key Priorities & Themes section", confidence: "high", complexity: "medium", status: "pending",
    searchConcepts: ["mom priorities", "parenting concerns 2026", "daily struggles mom", "mom mental load"],
  },
  {
    id: "RO2", objective: "Map the emotional tensions and frustrations moms express in online conversations",
    why: "Tensions reveal unmet needs — the richest territory for strategic insight",
    questionIds: ["RQ2", "RQ3"], priority: "high",
    platforms: [
      { name: "Reddit", justification: "Anonymous posting encourages honest expression of frustrations" },
      { name: "TikTok", justification: "Stitches and duets surface tensions through reaction content" },
      { name: "Threads", justification: "Short-form venting captures emerging tensions" },
    ],
    evidence: ["Tension themes with verbatim examples", "Emotional language patterns", "High-engagement tension conversations"],
    methods: ["Tension Analysis", "Narrative Analysis"],
    deliverable: "Tensions & Frustrations section", confidence: "high", complexity: "medium", status: "pending",
    searchConcepts: ["mom frustration", "parenting guilt", "work life balance mom", "mom burnout"],
  },
  {
    id: "RO3", objective: "Document how moms resolve tensions and cope with parenting challenges",
    why: "Resolution strategies reveal consumer agency and product opportunities",
    questionIds: ["RQ3"], priority: "high",
    platforms: [
      { name: "Reddit", justification: "Solution-oriented subreddits show detailed problem-solving" },
      { name: "TikTok", justification: "Life hack videos demonstrate coping behaviours visually" },
      { name: "Instagram", justification: "Carousel posts share curated solutions and tips" },
    ],
    evidence: ["Resolution strategies with examples", "Coping mechanism categories", "Before/after narratives"],
    methods: ["Behaviour Analysis", "Narrative Analysis"],
    deliverable: "Resolution & Coping section", confidence: "high", complexity: "medium", status: "pending",
    searchConcepts: ["mom life hacks", "parenting tips", "mom self care routine", "setting boundaries"],
  },
  {
    id: "RO4", objective: "Compare themes between moms of young children (A1) and moms of teenagers (A2)",
    why: "The brief explicitly requests this life-stage comparison — a core deliverable",
    questionIds: ["RQ4", "RQ8"], priority: "high",
    platforms: [
      { name: "Reddit", justification: "Age-specific subreddits enable clean segmentation" },
      { name: "Facebook", justification: "Groups organized by child age provide natural comparison cohorts" },
      { name: "TikTok", justification: "Content tagging (#toddlermom, #teenmom) allows age-stage filtering" },
    ],
    evidence: ["Comparative themes across age groups", "Divergent tensions by life stage", "Shared vs unique priorities"],
    methods: ["Life-stage Comparison", "Thematic Analysis"],
    deliverable: "Life-stage Comparison section", confidence: "high", complexity: "high", status: "pending",
    searchConcepts: ["toddler mom vs teen mom", "raising teenagers", "mom life stages"],
  },
  {
    id: "RO5", objective: "Identify how moms simplify and streamline their daily lives",
    why: "Simplification behaviours connect directly to product opportunities",
    questionIds: ["RQ5"], priority: "medium",
    platforms: [
      { name: "TikTok", justification: "Life hack and routine videos demonstrate simplification visually" },
      { name: "Instagram", justification: "Organization content is a major format" },
      { name: "Reddit", justification: "Practical discussion threads on simplifying routines" },
    ],
    evidence: ["Simplification strategies and categories", "Frequency and engagement indicators", "Verbatims about what works"],
    methods: ["Behaviour Analysis", "Trend Analysis"],
    deliverable: "Simplification Behaviours section", confidence: "medium", complexity: "medium", status: "pending",
    searchConcepts: ["simplify life as mom", "mom routine", "batch cooking", "minimalist mom"],
  },
  {
    id: "RO6", objective: "Analyse the role of food preparation in moms' daily lives",
    why: "Directly relevant to the commissioning brand's strategic context",
    questionIds: ["RQ6"], priority: "high",
    platforms: [
      { name: "TikTok", justification: "Cooking content and 'what I feed my kids' is a massive category" },
      { name: "Reddit", justification: "r/MealPrepSunday discussions reveal practical food behaviours" },
      { name: "Instagram", justification: "Food content and family meal sharing is engagement-rich" },
      { name: "Facebook", justification: "Recipe sharing and 'what's for dinner' discussions" },
    ],
    evidence: ["Food preparation behaviours and routines", "Pain points around cooking", "Time-saving food strategies"],
    methods: ["Behaviour Analysis", "Thematic Analysis"],
    deliverable: "Food Preparation Behaviours section", confidence: "high", complexity: "medium", status: "pending",
    searchConcepts: ["weeknight dinners", "meal prep mom", "picky eaters", "cooking fatigue"],
  },
  {
    id: "RO7", objective: "Map meal simplification strategies and decision-making patterns",
    why: "Granular view of how moms reduce cooking complexity — actionable for food brand strategy",
    questionIds: ["RQ6"], priority: "medium",
    platforms: [
      { name: "TikTok", justification: "Viral meal hack content shows real simplification" },
      { name: "Reddit", justification: "Discussion about what actually saves time in the kitchen" },
    ],
    evidence: ["Meal simplification strategies", "Decision factors (time, cost, nutrition)", "Convenience vs guilt tension"],
    methods: ["Behaviour Analysis", "Tension Analysis"],
    deliverable: "Food Preparation Behaviours section (detail)", confidence: "medium", complexity: "medium", status: "pending",
    searchConcepts: ["5 minute dinner", "dump meals", "frozen food hack", "convenience food guilt"],
  },
  {
    id: "RO8", objective: "Catalogue the colloquialisms, slang, and phrases moms use across platforms",
    why: "Consumer language informs brand voice, content strategy, and audience targeting",
    questionIds: ["RQ7"], priority: "medium",
    platforms: [
      { name: "TikTok", justification: "Platform-native slang reveals current language patterns" },
      { name: "Reddit", justification: "Authentic, unfiltered language in long-form posts" },
      { name: "X", justification: "Short-form commentary captures colloquial expressions" },
    ],
    evidence: ["Glossary of current mom-specific language", "Usage context and frequency indicators", "Platform-specific differences"],
    methods: ["Language Analysis", "Platform Comparison"],
    deliverable: "Consumer Language section", confidence: "medium", complexity: "low", status: "pending",
    searchConcepts: ["mom slang", "touched out", "mom brain", "gentle parenting language"],
  },
  {
    id: "RO9", objective: "Identify platform-specific differences in how moms discuss themes",
    why: "Understanding platform dynamics helps target research and content strategy",
    questionIds: ["RQ1", "RQ2"], priority: "low",
    platforms: [
      { name: "Reddit", justification: "Long-form discussion baseline" },
      { name: "TikTok", justification: "Short-form visual baseline" },
      { name: "Instagram", justification: "Visual/aspirational baseline" },
      { name: "Facebook", justification: "Community discussion baseline" },
    ],
    evidence: ["Platform-specific content formats", "Engagement patterns", "Topic prevalence by platform"],
    methods: ["Platform Comparison", "Thematic Analysis"],
    deliverable: "Methodology & Platform Rationale section", confidence: "medium", complexity: "low", status: "pending",
    searchConcepts: ["mom community", "parenting discussion", "parent advice"],
  },
  {
    id: "RO10", objective: "Compare food-preparation behaviours across life stages (A1 vs A2)",
    why: "Life-stage comparison applied to food behaviours — directly relevant to brand strategy",
    questionIds: ["RQ4", "RQ6"], priority: "medium",
    platforms: [
      { name: "Reddit", justification: "Age-specific subreddits for cohort separation" },
      { name: "TikTok", justification: "Creators self-identify their child's age" },
      { name: "Facebook", justification: "Age-specific parenting groups for targeted comparison" },
    ],
    evidence: ["Divergent food behaviours by child age", "Shared vs unique food challenges", "Strategy differences by life stage"],
    methods: ["Life-stage Comparison", "Behaviour Analysis"],
    deliverable: "Life-stage Comparison section (food focus)", confidence: "medium", complexity: "medium", status: "pending",
    searchConcepts: ["cooking for toddlers vs teenagers", "picky eater stages", "feeding family"],
  },
];

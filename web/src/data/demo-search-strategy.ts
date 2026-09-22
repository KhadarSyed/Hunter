import type {
  MeltwaterStrategyOutput,
  QueryModule,
  ResearchQuestionQuery,
} from "./contracts";

export const DEMO_QUERY_MODULES: QueryModule[] = [
  {
    module_name: "Brand Terms",
    module_type: "brand",
    terms: ['"Sample Brand"', '"SampleBrand"'],
    boolean_fragment: '("Sample Brand" OR "SampleBrand")',
  },
  {
    module_name: "Audience Terms",
    module_type: "audience",
    terms: ["mom", "moms", "mother", "mothers", '"mom life"', "parenting", "mama", "mommy"],
    boolean_fragment: '(mom OR moms OR mother OR mothers OR "mom life" OR parenting OR mama OR mommy)',
  },
  {
    module_name: "Topic — Priorities & Daily Life",
    module_type: "topic",
    terms: ["priorities", '"daily routine"', '"mental load"', "overwhelmed", "juggling", '"to do list"'],
    boolean_fragment: '(priorities OR "daily routine" OR "mental load" OR overwhelmed OR juggling OR "to do list")',
  },
  {
    module_name: "Topic — Tensions & Frustrations",
    module_type: "tension",
    terms: ["frustrated", "stressed", "guilt", "burnout", '"mom guilt"', '"touched out"', "exhausted", "rant"],
    boolean_fragment: '(frustrated OR stressed OR guilt OR burnout OR "mom guilt" OR "touched out" OR exhausted OR rant)',
  },
  {
    module_name: "Topic — Food & Meals",
    module_type: "behaviour",
    terms: ['"meal prep"', '"weeknight dinner"', "cooking", '"picky eater"', '"what to cook"', '"dinner ideas"', '"freezer meals"', '"air fryer"'],
    boolean_fragment: '("meal prep" OR "weeknight dinner" OR cooking OR "picky eater" OR "what to cook" OR "dinner ideas" OR "freezer meals" OR "air fryer")',
  },
  {
    module_name: "Topic — Simplification",
    module_type: "resolution",
    terms: ["simplify", "shortcut", '"life hack"', "minimize", '"girl dinner"', '"snack dinner"', '"sad beige food"', "convenience"],
    boolean_fragment: '(simplify OR shortcut OR "life hack" OR minimize OR "girl dinner" OR "snack dinner" OR "sad beige food" OR convenience)',
  },
  {
    module_name: "Life Stage — Young Children",
    module_type: "audience",
    terms: ["toddler", "preschool", "baby", '"young kids"', "infant", '"little ones"'],
    boolean_fragment: '(toddler OR preschool OR baby OR "young kids" OR infant OR "little ones")',
  },
  {
    module_name: "Life Stage — Teenagers",
    module_type: "audience",
    terms: ["teenager", "teen", "adolescent", '"high school"', "tween", '"older kids"'],
    boolean_fragment: '(teenager OR teen OR adolescent OR "high school" OR tween OR "older kids")',
  },
  {
    module_name: "Language & Colloquialisms",
    module_type: "topic",
    terms: ['"mom brain"', '"touched out"', '"gentle parenting"', '"crunchy mom"', '"silky mom"', '"hot mess"', '"wine mom"', '"boy mom"', '"girl mom"'],
    boolean_fragment: '("mom brain" OR "touched out" OR "gentle parenting" OR "crunchy mom" OR "silky mom" OR "hot mess" OR "wine mom" OR "boy mom" OR "girl mom")',
  },
  {
    module_name: "Exclusion Terms",
    module_type: "exclusion",
    terms: [
      '"off-topic brand A"', '"off-topic brand B"', '"off-topic brand C"', '"off-topic brand D"', '"off-topic brand E"', '"Mr. T"',
      "hiring", "job", "careers", "coupon", "giveaway", "sweepstakes", "sponsored", "ad", "promo",
    ],
    boolean_fragment:
      'NOT ("off-topic brand A" OR "off-topic brand B" OR "off-topic brand C" OR "off-topic brand D" OR "off-topic brand E" OR "Mr. T" OR hiring OR job OR careers OR coupon OR giveaway OR sweepstakes)',
  },
];

export const DEMO_RQ_QUERIES: ResearchQuestionQuery[] = [
  {
    question_id: "RQ1",
    question_text: "What are moms' priorities?",
    boolean_string:
      '(mom OR moms OR mother OR mothers OR mama) AND (priorities OR "most important" OR "top priority" OR "daily routine" OR "mental load" OR juggling OR "to do list") AND NOT (hiring OR job OR coupon OR giveaway)',
    query_type: "standalone",
    coverage_notes: "Captures priority-framing language across platforms. May need engagement threshold to filter low-quality results.",
  },
  {
    question_id: "RQ2",
    question_text: "What are the key themes and tensions being discussed?",
    boolean_string:
      '(mom OR moms OR mother OR mothers) AND (frustrated OR stressed OR guilt OR burnout OR "mom guilt" OR "touched out" OR exhausted OR rant OR tension OR struggle) AND NOT (hiring OR job OR coupon OR giveaway)',
    query_type: "standalone",
    coverage_notes: "Broad tension capture. High volume expected — use engagement threshold or precision version to manage.",
  },
  {
    question_id: "RQ3",
    question_text: "How are those tensions resolved?",
    boolean_string:
      '(mom OR moms OR mother) AND (cope OR coping OR "life hack" OR solution OR "figured out" OR "what works" OR tip OR advice OR "self care" OR boundary OR boundaries) AND NOT (hiring OR job OR ad)',
    query_type: "standalone",
    coverage_notes: "Resolution and coping strategies. TikTok life-hack content will be a major source.",
  },
  {
    question_id: "RQ4",
    question_text: "Are themes different for moms with young children vs. older children?",
    boolean_string:
      '(mom OR moms OR mother) AND ((toddler OR preschool OR baby OR "young kids" OR infant) OR (teenager OR teen OR "high school" OR tween)) AND NOT (hiring OR job OR coupon)',
    query_type: "standalone",
    coverage_notes: "Segmentation query. Run separately for each age group, then compare thematically.",
  },
  {
    question_id: "RQ5",
    question_text: "How are moms simplifying their lives?",
    boolean_string:
      '(mom OR moms OR mother) AND (simplify OR shortcut OR "life hack" OR minimize OR routine OR streamline OR "girl dinner" OR "snack dinner" OR "sad beige food" OR convenience OR "batch cooking") AND NOT (hiring OR job OR ad)',
    query_type: "standalone",
    coverage_notes: "Captures simplification behaviours including viral food trends. High TikTok volume expected.",
  },
  {
    question_id: "RQ6",
    question_text: "What role does food preparation play?",
    boolean_string:
      '(mom OR moms OR mother) AND ("meal prep" OR "weeknight dinner" OR cooking OR "picky eater" OR "what to cook" OR "dinner ideas" OR "freezer meals" OR "air fryer" OR recipe OR "what I feed" OR "feeding my kids") AND NOT (hiring OR job OR coupon OR giveaway OR "restaurant review")',
    query_type: "standalone",
    coverage_notes: "Core food query. High volume — use balanced version for working dataset, broad for exhaustive capture.",
  },
  {
    question_id: "RQ7",
    question_text: "What colloquialisms or distinctive phrases are moms using?",
    boolean_string:
      '(mom OR moms OR mother) AND ("mom brain" OR "touched out" OR "gentle parenting" OR "crunchy mom" OR "silky mom" OR "hot mess" OR "wine mom" OR "boy mom" OR "girl mom" OR "fed is best" OR "mom rage" OR "invisible labor") AND NOT (hiring OR job OR ad)',
    query_type: "standalone",
    coverage_notes: "Language-specific query. Designed to surface identity-signalling and community-specific phrases.",
  },
  {
    question_id: "RQ8",
    question_text: "Do priorities differ between moms of young children and moms of teenagers?",
    boolean_string:
      '(mom OR moms OR mother) AND (priorities OR "most important" OR "daily routine") AND ((toddler OR baby OR "young kids") OR (teenager OR teen OR tween)) AND NOT (hiring OR job)',
    query_type: "additive",
    coverage_notes: "Refinement of RQ1 × RQ4. Lower volume but high analytical value for life-stage comparison.",
  },
];

export const DEMO_SEARCH_STRATEGY: MeltwaterStrategyOutput = {
  strategy_summary: {
    objective:
      "Capture authentic social media conversations among US moms about their priorities, tensions, coping strategies, food-preparation behaviours, simplification patterns, and community language — segmented by child age group.",
    approach: "audience-led",
    strengths: [
      "Audience-led approach captures organic conversations rather than brand-filtered mentions",
      "Modular query design allows independent tuning of each topic area",
      "Life-stage segmentation built into query structure for clean comparison",
      "Strong exclusion logic prevents common false positives from brand name confusion",
    ],
    blind_spots: [
      "Visual-only content (images without text captions) will not be captured by text-based queries",
      "Private Facebook group conversations may be inaccessible depending on Meltwater access",
      "Emerging slang not yet in the term list may be missed — iterative refinement recommended",
    ],
    false_positive_risks: [
      "Generic 'mom' keyword captures non-US content — geography filter essential",
      "Food content from non-mom creators using similar terminology",
      "Parenting advice from professionals rather than authentic mom conversation",
    ],
    validation_steps: [
      "Export 200-record sample from balanced query",
      "Manual relevance check — target >75% relevance rate",
      "Identify top false-positive patterns and add to exclusion module",
      "Verify life-stage segmentation produces comparable volume for both cohorts",
      "Check platform distribution matches expected conversation sources",
    ],
  },

  query_modules: DEMO_QUERY_MODULES,

  core_query: {
    broad: {
      boolean_string:
        '(mom OR moms OR mother OR mothers OR mama OR mommy OR parenting) AND (priorities OR tensions OR stressed OR guilt OR "meal prep" OR cooking OR simplify OR "life hack" OR "picky eater" OR "mom guilt" OR "touched out" OR "weeknight dinner") AND NOT ("off-topic brand A" OR "off-topic brand B" OR "off-topic brand C" OR "Mr. T" OR hiring OR job OR careers OR coupon OR giveaway OR sweepstakes)',
      description: "Maximum recall — captures broad mom conversations across all topic areas. Expect higher noise.",
      recall_level: "broad",
      precision_level: "low",
    },
    balanced: {
      boolean_string:
        '(mom OR moms OR mother OR mothers) AND ((priorities OR "daily routine" OR "mental load") OR (frustrated OR stressed OR guilt OR burnout OR "mom guilt") OR ("meal prep" OR "weeknight dinner" OR cooking OR "picky eater" OR "dinner ideas") OR (simplify OR shortcut OR "life hack" OR "girl dinner") OR ("mom brain" OR "touched out" OR "gentle parenting")) AND NOT ("off-topic brand A" OR "off-topic brand B" OR "off-topic brand C" OR "off-topic brand D" OR "off-topic brand E" OR "Mr. T" OR hiring OR job OR careers OR coupon OR giveaway OR sweepstakes OR sponsored)',
      description: "Recommended working query — balanced coverage across all research questions with manageable volume.",
      recall_level: "balanced",
      precision_level: "medium",
    },
    precise: {
      boolean_string:
        '(mom OR moms OR mother) AND ("mom life" OR "as a mom" OR "mom of" OR "being a mom") AND ((priorities OR "most important") OR ("mom guilt" OR burnout OR "touched out") OR ("meal prep" OR "picky eater" OR "weeknight dinner") OR ("life hack" OR simplify) OR ("mom brain" OR "gentle parenting" OR "crunchy mom")) AND NOT ("off-topic brand A" OR "off-topic brand B" OR "off-topic brand C" OR "off-topic brand D" OR "off-topic brand E" OR "Mr. T" OR hiring OR job OR careers OR coupon OR giveaway OR sweepstakes OR sponsored OR ad OR promo)',
      description: "High-precision version — requires self-identification as a mom. Lower volume, higher relevance.",
      recall_level: "precise",
      precision_level: "high",
    },
  },

  research_question_queries: DEMO_RQ_QUERIES,

  exclusion_logic: {
    entity_exclusions: [
      { term: '"off-topic brand A"', reason: "Film title — high false-positive risk with similar name" },
      { term: '"off-topic brand B"', reason: "Cookie brand — unrelated category, similar name pattern" },
      { term: '"off-topic brand C"', reason: "Cleaning products brand — similar name pattern" },
      { term: '"off-topic brand D"', reason: "Seasoning brand — similar name pattern" },
      { term: '"off-topic brand E"', reason: "Syrup brand — similar name pattern" },
      { term: '"Mr. T"', reason: "Celebrity — phonetic similarity to brand name" },
    ],
    spam_exclusions: ["coupon", "giveaway", "sweepstakes", "sponsored", "ad", "promo", '"click link"', '"link in bio"'],
    content_type_exclusions: ["hiring", "job", "careers", '"now hiring"', "recruitment", '"job posting"'],
    geography_exclusions: [],
    general_exclusions: ['"restaurant review"', '"recipe blog"'],
    combined_not_string:
      'NOT ("off-topic brand A" OR "off-topic brand B" OR "off-topic brand C" OR "off-topic brand D" OR "off-topic brand E" OR "Mr. T" OR coupon OR giveaway OR sweepstakes OR sponsored OR promo OR hiring OR job OR careers OR "now hiring" OR recruitment)',
  },

  filter_recommendations: {
    geography: "United States",
    language: "English",
    date_range_start: "2025-07-22",
    date_range_end: "2026-07-22",
    source_types: ["Social Media"],
    social_platforms: ["Reddit", "TikTok", "Facebook", "Instagram", "X (Twitter)", "Threads"],
    editorial_handling: "Exclude — brief specifies social media only",
    owned_content_handling: "Exclude — brand-owned content is not organic conversation",
    retweet_handling: "Exclude retweets — capture original content only",
    engagement_threshold: "Minimum 2 engagements (reduces bot/spam noise)",
    duplicate_handling: "Remove near-duplicates — keep highest-engagement version",
  },

  term_rationale: [
    { term: "mom / moms / mother", reason_included: "Core audience identifier from brief", expected_capture: "All mom-identifying social content", risk_introduced: "Very broad — requires topic co-occurrence", source: "brief" },
    { term: '"mom life"', reason_included: "Self-identification phrase — higher precision than bare 'mom'", expected_capture: "Content where user identifies as a mom discussing their life", risk_introduced: "Low risk — highly specific phrase", source: "inferred" },
    { term: '"meal prep"', reason_included: "Key food preparation behaviour from RQ6", expected_capture: "Planned meal preparation discussions", risk_introduced: "May capture non-mom meal prep content", source: "brief" },
    { term: '"picky eater"', reason_included: "Top food tension identified in background research", expected_capture: "Parent discussions about children's eating habits", risk_introduced: "Low — almost always in parenting context", source: "background-research" },
    { term: '"touched out"', reason_included: "Emerging mom-specific term for sensory overwhelm", expected_capture: "Authentic tension expression unique to parenting", risk_introduced: "Very low — term is parenting-specific", source: "background-research" },
    { term: '"girl dinner"', reason_included: "Viral simplification trend from background research", expected_capture: "Low-effort meal conversations showing simplification behaviour", risk_introduced: "Medium — not always mom-specific", source: "background-research" },
    { term: '"gentle parenting"', reason_included: "Major parenting philosophy generating online discussion", expected_capture: "Parenting approach debates and experiences", risk_introduced: "Low — specific to parenting domain", source: "background-research" },
  ],

  quality_score: {
    overall: 82,
    entity_accuracy: 95,
    scope_alignment: 88,
    recall: 78,
    precision: 75,
    ambiguity_control: 90,
    audience_relevance: 85,
    topic_coverage: 80,
    false_positive_protection: 88,
    rq_coverage: 100,
    blocking_issues: [],
    warnings: [
      "Broad query may exceed Meltwater volume limits — use balanced version as default",
      "Visual-only TikTok content will not appear in text-based results",
      "Private Facebook group content accessibility depends on Meltwater data agreements",
    ],
    recommended_refinements: [
      "Run 200-record sample export and check relevance rate before full pull",
      "Consider adding platform-specific hashtags (#momtok, #momlife) as a separate filter layer",
      "After initial results, identify additional exclusion terms from actual noise patterns",
      "Test life-stage queries independently to ensure comparable volume per cohort",
    ],
  },

  versions: [
    { version_id: 1, created_at: "2026-07-22T10:30:00Z", change_summary: "Initial query generation from approved spec + brand intelligence", approval_status: "draft" },
  ],
};

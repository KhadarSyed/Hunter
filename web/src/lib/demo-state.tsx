import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import { DEMO_SEARCH_STRATEGY } from "../data/demo-search-strategy";
import { DEMO_BRAND_INTELLIGENCE } from "../data/demo-brand-intelligence";

interface ActivityEntry {
  timestamp: string;
  action: string;
  detail: string;
}

interface QueryVersion {
  id: number;
  queryText: string;
  timestamp: string;
  summary: string;
}

interface ExclusionItem {
  term: string;
  reason: string;
  enabled: boolean;
}

interface DemoState {
  briefApproved: boolean;
  backgroundApproved: boolean;
  strategyApproved: boolean;
  datasetApproved: boolean;

  balancedQuery: string;
  queryVersions: QueryVersion[];

  searchTerms: Array<{ term: string; type: string; added?: boolean }>;
  exclusions: ExclusionItem[];

  evaluationRun: boolean;

  activityLog: ActivityEntry[];

  setBriefApproved: (v: boolean) => void;
  setBackgroundApproved: (v: boolean) => void;
  setStrategyApproved: (v: boolean) => void;
  setDatasetApproved: (v: boolean) => void;

  updateBalancedQuery: (text: string, summary: string) => void;
  addSearchTerm: (term: string, type: string) => void;
  removeSearchTerm: (term: string) => void;
  addExclusion: (term: string, reason: string) => void;
  toggleExclusion: (term: string) => void;
  setEvaluationRun: (v: boolean) => void;
  addActivity: (action: string, detail: string) => void;

  resetDemoState: () => void;
  nextAction: string;
  researchPlanLocked: boolean;
}

const DemoStateContext = createContext<DemoState | null>(null);

export function useDemoState(): DemoState {
  const ctx = useContext(DemoStateContext);
  if (!ctx) throw new Error("useDemoState must be within DemoStateProvider");
  return ctx;
}

const initialExclusions: ExclusionItem[] =
  DEMO_SEARCH_STRATEGY.exclusion_logic.entity_exclusions.map((e) => ({
    term: e.term,
    reason: e.reason,
    enabled: true,
  }));

const initialTerms = (DEMO_BRAND_INTELLIGENCE.search_implications || []).map((s) => ({
  term: s.term,
  type: s.type,
}));

const now = () => new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });

export function DemoStateProvider({ children }: { children: ReactNode }) {
  const [briefApproved, setBriefApproved] = useState(true);
  const [backgroundApproved, setBackgroundApprovedRaw] = useState(false);
  const [strategyApproved, setStrategyApprovedRaw] = useState(false);
  const [datasetApproved, setDatasetApprovedRaw] = useState(false);

  const [balancedQuery, setBalancedQuery] = useState(
    DEMO_SEARCH_STRATEGY.core_query.balanced.boolean_string
  );
  const [queryVersions, setQueryVersions] = useState<QueryVersion[]>([
    {
      id: 1,
      queryText: DEMO_SEARCH_STRATEGY.core_query.balanced.boolean_string,
      timestamp: "2026-07-22T10:30:00Z",
      summary: "Initial query generation from approved spec + brand intelligence",
    },
  ]);

  const [searchTerms, setSearchTerms] = useState<Array<{ term: string; type: string; added?: boolean }>>(initialTerms);
  const [exclusions, setExclusions] = useState(initialExclusions);
  const [evaluationRun, setEvaluationRun] = useState(false);

  const [activityLog, setActivityLog] = useState<ActivityEntry[]>([]);

  const addActivity = useCallback((action: string, detail: string) => {
    setActivityLog((prev) => [{ timestamp: now(), action, detail }, ...prev]);
  }, []);

  const setBackgroundApproved = useCallback(
    (v: boolean) => {
      setBackgroundApprovedRaw(v);
      if (v) addActivity("Background Research Approved", "Gate 2 passed — proceeding to search strategy");
    },
    [addActivity]
  );

  const setStrategyApproved = useCallback(
    (v: boolean) => {
      setStrategyApprovedRaw(v);
      if (v) addActivity("Search Strategy Approved", "Gate 3 passed — ready for Meltwater data upload");
    },
    [addActivity]
  );

  const setDatasetApproved = useCallback(
    (v: boolean) => {
      setDatasetApprovedRaw(v);
      if (v) addActivity("Dataset Approved", "Gate 4 passed — research plan unlocked");
    },
    [addActivity]
  );

  const updateBalancedQuery = useCallback(
    (text: string, summary: string) => {
      setBalancedQuery(text);
      setQueryVersions((prev) => [
        ...prev,
        {
          id: prev.length + 1,
          queryText: text,
          timestamp: new Date().toISOString(),
          summary,
        },
      ]);
      addActivity("Query Updated", summary);
    },
    [addActivity]
  );

  const addSearchTerm = useCallback(
    (term: string, type: string) => {
      setSearchTerms((prev) => {
        if (prev.some((t) => t.term === term)) return prev;
        return [...prev, { term, type, added: true }];
      });
      addActivity("Search Term Added", `"${term}" (${type})`);
    },
    [addActivity]
  );

  const removeSearchTerm = useCallback(
    (term: string) => {
      setSearchTerms((prev) => prev.filter((t) => t.term !== term));
      addActivity("Search Term Removed", `"${term}"`);
    },
    [addActivity]
  );

  const addExclusion = useCallback(
    (term: string, reason: string) => {
      setExclusions((prev) => {
        if (prev.some((e) => e.term === term)) return prev;
        return [...prev, { term, reason, enabled: true }];
      });
      addActivity("Exclusion Added", `${term} — ${reason}`);
    },
    [addActivity]
  );

  const toggleExclusion = useCallback((term: string) => {
    setExclusions((prev) =>
      prev.map((e) => (e.term === term ? { ...e, enabled: !e.enabled } : e))
    );
  }, []);

  const resetDemoState = useCallback(() => {
    setBriefApproved(false);
    setBackgroundApprovedRaw(false);
    setStrategyApprovedRaw(false);
    setDatasetApprovedRaw(false);
    setBalancedQuery(DEMO_SEARCH_STRATEGY.core_query.balanced.boolean_string);
    setQueryVersions([{
      id: 1,
      queryText: DEMO_SEARCH_STRATEGY.core_query.balanced.boolean_string,
      timestamp: new Date().toISOString(),
      summary: "Initial query generation",
    }]);
    setSearchTerms(initialTerms);
    setExclusions(initialExclusions);
    setEvaluationRun(false);
    setActivityLog([]);
  }, []);

  const nextAction = !backgroundApproved
    ? "Review Background Research"
    : !strategyApproved
      ? "Review Meltwater Search Strategy"
      : !datasetApproved
        ? "Upload Meltwater Dataset"
        : "Review Research Plan";

  const researchPlanLocked = false;

  return (
    <DemoStateContext.Provider
      value={{
        briefApproved,
        backgroundApproved,
        strategyApproved,
        datasetApproved,
        balancedQuery,
        queryVersions,
        searchTerms,
        exclusions,
        evaluationRun,
        activityLog,
        setBriefApproved,
        setBackgroundApproved,
        setStrategyApproved,
        setDatasetApproved,
        updateBalancedQuery,
        addSearchTerm,
        removeSearchTerm,
        addExclusion,
        toggleExclusion,
        setEvaluationRun,
        addActivity,
        resetDemoState,
        nextAction,
        researchPlanLocked,
      }}
    >
      {children}
    </DemoStateContext.Provider>
  );
}

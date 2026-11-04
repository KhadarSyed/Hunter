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

export const DEMO_ANALYSIS_STEPS = [
  { label: "Reading brief", status: "completed" as const },
  { label: "Extracting entities", status: "completed" as const },
  { label: "Understanding objective", status: "completed" as const },
  { label: "Finding audience", status: "completed" as const },
  { label: "Validating scope", status: "completed" as const },
  { label: "Building project specification", status: "completed" as const },
  { label: "Running validation", status: "completed" as const },
];

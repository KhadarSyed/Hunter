import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

export type ProjectType = "research" | "monitoring_qc";

interface ActiveProject {
  id: number;
  name: string;
  project_type: ProjectType;
}

interface ProjectContextValue {
  activeProject: ActiveProject | null;
  setActiveProject: (project: ActiveProject | null) => void;
  clearProject: () => void;
  projectVersion: number;
}

const PROJECT_STORAGE_KEY = "infovision-active-project";

function loadPersistedProject(): ActiveProject | null {
  try {
    const raw = localStorage.getItem(PROJECT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.id === "number" && typeof parsed.name === "string") {
      return { ...parsed, project_type: parsed.project_type || "research" };
    }
    return null;
  } catch {
    return null;
  }
}

function persistProject(project: ActiveProject | null): void {
  if (project) {
    localStorage.setItem(PROJECT_STORAGE_KEY, JSON.stringify(project));
  } else {
    localStorage.removeItem(PROJECT_STORAGE_KEY);
  }
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

export function useProject(): ProjectContextValue {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error("useProject must be within ProjectProvider");
  return ctx;
}

export function useActiveProjectId(): number | null {
  const { activeProject } = useProject();
  return activeProject?.id ?? null;
}

export function useProjectType(): ProjectType {
  const { activeProject } = useProject();
  return activeProject?.project_type ?? "research";
}

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [activeProject, setActiveProjectRaw] = useState<ActiveProject | null>(loadPersistedProject);
  const [projectVersion, setProjectVersion] = useState(0);

  const setActiveProject = useCallback((project: ActiveProject | null) => {
    setActiveProjectRaw(project);
    persistProject(project);
    setProjectVersion((v) => v + 1);
  }, []);

  const clearProject = useCallback(() => {
    setActiveProjectRaw(null);
    persistProject(null);
    setProjectVersion((v) => v + 1);
  }, []);

  return (
    <ProjectContext.Provider value={{ activeProject, setActiveProject, clearProject, projectVersion }}>
      {children}
    </ProjectContext.Provider>
  );
}

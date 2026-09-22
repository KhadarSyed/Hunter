import { useState, useEffect, useRef, useCallback } from "react";
import { useProject, type ProjectType } from "../lib/project-context";
import { intelApi } from "../lib/intel-api";

const DRAFT_KEY = "infovision-project-draft";

interface Draft {
  projectName: string;
  client: string;
  geography: string;
  researchType: string;
  timePeriod: string;
  briefText: string;
  savedAt: string;
}

function loadDraft(): Draft | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

interface ProjectListItem {
  id: number;
  project_name: string;
  project_type: string;
  created_at: number;
  updated_at: number;
}

export function NewProject({ onNavigate, projectType = "research" }: { onNavigate: (page: string) => void; projectType?: ProjectType }) {
  const isQC = projectType === "monitoring_qc";
  const { activeProject, setActiveProject } = useProject();
  const saved = loadDraft();
  const [projectName, setProjectName] = useState(saved?.projectName ?? "");
  const [client, setClient] = useState(saved?.client ?? "");
  const [geography, setGeography] = useState(saved?.geography ?? "United States");
  const [researchType, setResearchType] = useState(saved?.researchType ?? "Social Listening");
  const [timePeriod, setTimePeriod] = useState(saved?.timePeriod ?? "Past 12 months");
  const [briefText, setBriefText] = useState(saved?.briefText ?? "");
  const [creating, setCreating] = useState(false);
  const [llmStatus, setLlmStatus] = useState("");
  const [error, setError] = useState("");
  const [draftSaved, setDraftSaved] = useState(false);
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [showNewForm, setShowNewForm] = useState(false);
  const [uploadingBrief, setUploadingBrief] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleBriefFile = useCallback(async (file: File) => {
    setUploadingBrief(true);
    setError("");
    try {
      const result = await intelApi.parseBriefFile(file);
      setBriefText(result.text);
    } catch (e: any) {
      setError(e.message || "Failed to parse file");
    } finally {
      setUploadingBrief(false);
    }
  }, []);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleBriefFile(file);
  }, [handleBriefFile]);

  useEffect(() => {
    intelApi.listProjects(projectType)
      .then((list) => {
        setProjects(list);
        setShowNewForm(list.length === 0);
      })
      .catch(() => {})
      .finally(() => setLoadingProjects(false));
  }, [projectType]);

  useEffect(() => {
    if (draftSaved) {
      const t = setTimeout(() => setDraftSaved(false), 2000);
      return () => clearTimeout(t);
    }
  }, [draftSaved]);

  const handleSaveDraft = () => {
    const draft: Draft = {
      projectName, client, geography, researchType, timePeriod, briefText,
      savedAt: new Date().toISOString(),
    };
    localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    setDraftSaved(true);
  };

  const handleCreateQC = async () => {
    if (!projectName.trim()) return;
    setCreating(true);
    setError("");
    try {
      const spec = {
        commissioning_brand: { name: client || projectName },
        project_type: "monitoring_qc",
        client,
      };
      const result = await intelApi.createProject(projectName, spec, "monitoring_qc");
      setActiveProject({ id: result.id, name: result.project_name, project_type: "monitoring_qc" });
      localStorage.removeItem(DRAFT_KEY);
      onNavigate("qc-upload");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Project creation failed");
      setCreating(false);
    }
  };

  const handleAnalyze = async () => {
    if (!briefText.trim() || !projectName.trim()) return;
    setCreating(true);
    setError("");
    setLlmStatus("Creating project...");
    try {
      const spec = {
        executive_interpretation: briefText.trim(),
        commissioning_brand: { name: client || projectName, role: "Strategic context and funding client" },
        research_subject: { description: briefText.trim(), is_brand_study: false },
        research_audience: { description: `Target audience for ${client || projectName} research.` },
        strategic_application: `Findings will inform ${client || projectName} strategy and positioning.`,
        business_objective: briefText.trim(),
        research_objective: briefText.trim(),
        deliverable_objective: "Research report with thematic analysis and evidence.",
        validated_entities: [
          { name: client || projectName, type: "brand", confidence: "high", reasoning: "Identified from project brief." },
        ],
        research_questions: [
          { id: "RQ1", question: "What are the key themes and conversations?", priority: "primary", source: "inferred" },
          { id: "RQ2", question: "What are the emerging trends?", priority: "primary", source: "inferred" },
          { id: "RQ3", question: "How does the audience engage with the topic?", priority: "secondary", source: "inferred" },
        ],
        included_scope: {
          platforms: ["Social media"],
          geography,
          audience: `Target audience for ${client || projectName}`,
          time_period: timePeriod,
          languages: ["English"],
          content_types: ["Social media conversations"],
          segments: [],
          deliverables: ["Research report"],
        },
        excluded_scope: [],
        methodology: { primary: researchType, reasoning: `Selected as primary methodology for ${projectName}.` },
        confidence: { overall: "medium", entity: "high", scope: "medium", methodology: "medium" },
        validation: { errors: 0, warnings: 0 },
        raw_brief: briefText.trim(),
        client,
        geography,
        research_type: researchType,
        time_period: timePeriod,
      };
      const result = await intelApi.createProject(projectName, spec, projectType);
      setActiveProject({ id: result.id, name: result.project_name, project_type: (result.project_type as ProjectType) || projectType });
      setLlmStatus("Analyzing brief with LLM — this may take 1–2 minutes...");
      await intelApi.generateSpec(result.id, briefText.trim(), true);
      localStorage.removeItem(DRAFT_KEY);
      onNavigate(isQC ? "qc-upload" : "brief-scope-review");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Analysis failed";
      setError(msg);
      setCreating(false);
      setLlmStatus("");
    }
  };

  const handleSelectProject = (proj: ProjectListItem) => {
    const pType = (proj.project_type as ProjectType) || "research";
    setActiveProject({ id: proj.id, name: proj.project_name, project_type: pType });
    onNavigate(pType === "monitoring_qc" ? "qc-upload" : "dashboard");
  };

  const formatDate = (ts: number) => {
    const d = new Date(ts * 1000);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  };

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">{isQC ? "QC Projects" : "Projects"}</h1>
          <p className="text-sm text-slate-500 mt-0.5">{isQC ? "Select an existing QC project or create a new one" : "Select an existing project or create a new one"}</p>
        </div>
        {!showNewForm && (
          <button
            onClick={() => setShowNewForm(true)}
            className="px-4 py-2 text-sm font-medium text-white rounded-lg shadow-sm transition-colors"
            style={{ backgroundColor: isQC ? "#0F7B6C" : "#5B2C9D" }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = isQC ? "#0A6558" : "#4A2380")}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = isQC ? "#0F7B6C" : "#5B2C9D")}
          >
            + New {isQC ? "QC " : ""}Project
          </button>
        )}
      </div>

      {showNewForm && isQC ? (
      <>
      <div className="flex items-center justify-between pt-2">
        <h2 className="text-base font-semibold text-slate-700">New QC Project</h2>
        {projects.length > 0 && (
          <button onClick={() => setShowNewForm(false)} className="text-xs text-slate-400 hover:text-slate-600 transition-colors">Cancel</button>
        )}
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-5">
        <div className="grid grid-cols-2 gap-5">
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1.5">Project Name</label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="e.g. July 2026 QC - Acme Corp"
              className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm text-slate-900 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-400 transition-all"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1.5">Client</label>
            <input
              type="text"
              value={client}
              onChange={(e) => setClient(e.target.value)}
              placeholder="e.g. Acme Corp"
              className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm text-slate-900 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-400 transition-all"
            />
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex items-center justify-end gap-3">
        <button
          disabled={!projectName.trim() || creating}
          onClick={handleCreateQC}
          className="px-5 py-2.5 text-sm font-medium text-white rounded-lg transition-colors shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ backgroundColor: "#0F7B6C" }}
        >
          {creating ? "Creating..." : "Create & Upload Report"}
        </button>
      </div>
      </>
      ) : showNewForm ? (
      <>
      <div className="flex items-center justify-between pt-2">
        <h2 className="text-base font-semibold text-slate-700">New Project</h2>
        {projects.length > 0 && (
          <button onClick={() => setShowNewForm(false)} className="text-xs text-slate-400 hover:text-slate-600 transition-colors">Cancel</button>
        )}
      </div>
      {saved && (
        <span className="text-xs text-slate-400">Draft from {new Date(saved.savedAt).toLocaleDateString()}</span>
      )}

      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-5">
        <div className="grid grid-cols-2 gap-5">
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1.5">Project Name</label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="e.g. Brand Audience Research"
              className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm text-slate-900 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1.5">Client</label>
            <input
              type="text"
              value={client}
              onChange={(e) => setClient(e.target.value)}
              placeholder="e.g. Acme Corp"
              className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm text-slate-900 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
            />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-5">
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1.5">Geography</label>
            <select
              value={geography}
              onChange={(e) => setGeography(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm text-slate-900 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
            >
              <option>United States</option>
              <option>United Kingdom</option>
              <option>Global</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1.5">Research Type</label>
            <select
              value={researchType}
              onChange={(e) => setResearchType(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm text-slate-900 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
            >
              <option>Social Listening</option>
              <option>Audience Insights</option>
              <option>Competitor Analysis</option>
              <option>Brand Tracking</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1.5">Time Period</label>
            <select
              value={timePeriod}
              onChange={(e) => setTimePeriod(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm text-slate-900 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
            >
              <option>Past 12 months</option>
              <option>Past 6 months</option>
              <option>Past 3 months</option>
              <option>Past 30 days</option>
            </select>
          </div>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-4">
        <div>
          <label className="block text-xs font-medium text-slate-500 mb-1.5">Client Brief</label>
          <textarea
            rows={12}
            value={briefText}
            onChange={(e) => setBriefText(e.target.value)}
            placeholder="Paste your client brief here..."
            className="w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm text-slate-900 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all resize-y leading-relaxed"
          />
        </div>

        <div
          onClick={() => fileInputRef.current?.click()}
          onDrop={onDrop}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          className={`border-2 border-dashed rounded-xl p-8 text-center transition-all cursor-pointer group ${
            dragOver ? "border-blue-400 bg-blue-50/50" : "border-slate-200 hover:border-blue-300 hover:bg-blue-50/30"
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".docx,.pptx,.txt,.pdf,.xlsx,.xls"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleBriefFile(file);
              e.target.value = "";
            }}
          />
          {uploadingBrief ? (
            <>
              <svg className="mx-auto mb-3 animate-spin text-blue-500" width="28" height="28" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <p className="text-sm font-medium text-blue-600">Extracting text from file...</p>
            </>
          ) : (
            <>
              <svg className="mx-auto mb-3 text-slate-300 group-hover:text-blue-400 transition-colors" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              <p className="text-sm font-medium text-slate-600">Drop a file here or click to browse</p>
              <p className="text-xs text-slate-400 mt-1">PDF, DOCX, PPT, or Excel</p>
            </>
          )}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {creating && llmStatus && (
        <div className="bg-violet-50 border border-violet-200 rounded-lg px-4 py-3 flex items-center gap-3">
          <svg className="animate-spin h-4 w-4 text-violet-600 shrink-0" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span className="text-sm text-violet-700 font-medium">{llmStatus}</span>
        </div>
      )}

      <div className="flex items-center justify-end gap-3">
        <button
          onClick={handleSaveDraft}
          disabled={creating}
          className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-40"
        >
          {draftSaved ? "Saved" : "Save Draft"}
        </button>
        <button
          disabled={!briefText.trim() || !projectName.trim() || creating}
          onClick={handleAnalyze}
          className="px-5 py-2.5 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {creating ? "Analyzing..." : "Analyze Brief"}
        </button>
      </div>
      </>
      ) : null}

      {loadingProjects ? (
        <div className="text-sm text-slate-400 py-8 text-center">Loading projects...</div>
      ) : projects.length > 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm divide-y divide-slate-100">
          {projects
            .sort((a, b) => b.updated_at - a.updated_at)
            .map((proj) => (
            <button
              key={proj.id}
              onClick={() => handleSelectProject(proj)}
              className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-slate-50 transition-colors first:rounded-t-xl last:rounded-b-xl group"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold shrink-0" style={{ backgroundColor: proj.project_type === "monitoring_qc" ? "#0F7B6C" : "#5B2C9D" }}>
                  {proj.project_type === "monitoring_qc" ? "Q" : proj.project_name.charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900 truncate">{proj.project_name}</p>
                  <p className="text-xs text-slate-400">Created {formatDate(proj.created_at)}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {activeProject?.id === proj.id && (
                  <span className="text-xs font-medium px-2 py-0.5 rounded-full text-white" style={{ backgroundColor: "#5B2C9D" }}>Active</span>
                )}
                <svg className="w-4 h-4 text-slate-300 group-hover:text-slate-500 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
              </div>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

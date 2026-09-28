import { useState, useEffect, useRef, useCallback } from "react";
import { CountryFlag, GEOGRAPHIES } from "../components/CountryFlag";
import { useProject, type ProjectType } from "../context/project-context";
import { intelApi, type BriefSource } from "../services/intel-api";

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

const str = (v: unknown, fallback = "") => (typeof v === "string" && v ? v : fallback);

const INPUT =
  "w-full border border-slate-200 rounded-lg px-3 py-2.5 text-sm text-slate-900 bg-white placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:border-violet-400 transition-all";

interface Props {
  onNavigate: (page: string) => void;
  projectType?: ProjectType;
  /** "new" always creates a project; "edit" loads the active project by id and updates it. */
  mode?: "new" | "edit";
}

/**
 * New / Edit Project form. Nothing is written to the database until "Analyze Brief"
 * (or, for QC, "Save & Upload Report") is clicked — "Save Draft" is browser-only.
 */
export function NewProject({ onNavigate, projectType = "research", mode = "new" }: Props) {
  const isQC = projectType === "monitoring_qc";
  const { activeProject, setActiveProject } = useProject();
  const editingId = mode === "edit" ? activeProject?.id ?? null : null;
  const draft = editingId ? null : loadDraft();

  const [projectName, setProjectName] = useState(draft?.projectName ?? "");
  const [client, setClient] = useState(draft?.client ?? "");
  const [geography, setGeography] = useState(draft?.geography ?? "United States");
  const [researchType, setResearchType] = useState(draft?.researchType ?? "Social Listening");
  const [timePeriod, setTimePeriod] = useState(draft?.timePeriod ?? "Past 30 days");
  const [briefText, setBriefText] = useState(draft?.briefText ?? "");
  const [existingSpec, setExistingSpec] = useState<Record<string, unknown>>({});
  const [loadingProject, setLoadingProject] = useState(editingId !== null);
  const [creating, setCreating] = useState(false);
  const [llmStatus, setLlmStatus] = useState("");
  const [error, setError] = useState("");
  const [draftSaved, setDraftSaved] = useState(false);
  const [uploadingBrief, setUploadingBrief] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [extractionNote, setExtractionNote] = useState("");
  // Uploaded file behind the brief text; null = typed/pasted text.
  const [briefSource, setBriefSource] = useState<BriefSource | null>(null);
  // File chosen but not yet extracted: the primary button reads "Extract Text" until it is.
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  // Set once a new project is saved, so retrying Analyze Brief updates it instead of duplicating.
  const [savedProjectId, setSavedProjectId] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Edit mode: load the project's saved brief by id.
  useEffect(() => {
    if (editingId === null) return;
    setLoadingProject(true);
    intelApi
      .getProject(editingId)
      .then((p) => {
        const s = p.spec ?? {};
        setExistingSpec(s);
        setProjectName(p.project_name);
        setClient(str(s.client));
        setGeography(str(s.geography, "United States"));
        setResearchType(str(s.research_type, "Social Listening"));
        setTimePeriod(str(s.time_period, "Past 30 days"));
        setBriefText(str(s.raw_brief));
        const src = s.brief_source as BriefSource | undefined;
        setBriefSource(src && src.type !== "text" ? src : null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load project"))
      .finally(() => setLoadingProject(false));
  }, [editingId]);

  const handleBriefFile = useCallback(async (file: File): Promise<boolean> => {
    setUploadingBrief(true);
    setError("");
    setExtractionNote("");
    try {
      const result = await intelApi.parseBriefFile(file);
      setBriefText(result.text);
      setBriefSource({ type: (file.name.split(".").pop() || "file").toLowerCase(), file_name: file.name });
      setExtractionNote(
        result.extraction_method === "nvidia"
          ? `Text extracted from ${file.name} with NVIDIA ${result.model ?? "Nemotron-Parse"}${result.pages ? ` (${result.pages} page${result.pages > 1 ? "s" : ""})` : ""} — review before analysing.`
          : `Text extracted from ${file.name} — review before analysing.`,
      );
      return true;
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to parse file");
      return false;
    } finally {
      setUploadingBrief(false);
    }
  }, []);

  const selectFile = (file: File) => {
    setPendingFile(file);
    setError("");
    setExtractionNote("");
  };

  const extractText = async () => {
    if (pendingFile && (await handleBriefFile(pendingFile))) setPendingFile(null);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) selectFile(file);
  };

  useEffect(() => {
    if (!draftSaved) return;
    const t = setTimeout(() => setDraftSaved(false), 2000);
    return () => clearTimeout(t);
  }, [draftSaved]);

  const handleSaveDraft = () => {
    const d: Draft = { projectName, client, geography, researchType, timePeriod, briefText, savedAt: new Date().toISOString() };
    localStorage.setItem(DRAFT_KEY, JSON.stringify(d));
    setDraftSaved(true);
  };

  /** Create (new mode) or update (edit mode) the project, then make it active.
   *  Brand = the Client field (drives the Brandfetch logo on the project card). */
  const persistProject = async (spec: Record<string, unknown>) => {
    const brand = client.trim();
    const targetId = editingId ?? savedProjectId;
    const result = targetId !== null
      ? await intelApi.updateProject(targetId, { project_name: projectName.trim(), spec: { ...existingSpec, ...spec }, brand })
      : await intelApi.createProject(projectName.trim(), spec, projectType, brand || undefined);
    if (targetId === null) setSavedProjectId(result.id);
    setActiveProject({ id: result.id, name: result.project_name, project_type: (result.project_type as ProjectType) || projectType });
    return result;
  };

  const handleSaveQC = async () => {
    if (!projectName.trim()) return;
    setCreating(true);
    setError("");
    try {
      await persistProject({ commissioning_brand: { name: client || projectName }, project_type: "monitoring_qc", client, geography });
      localStorage.removeItem(DRAFT_KEY);
      onNavigate("qc-upload");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Saving the project failed");
      setCreating(false);
    }
  };

  const handleAnalyze = async () => {
    if (!briefText.trim() || !projectName.trim()) return;
    setCreating(true);
    setError("");
    setLlmStatus(editingId !== null || savedProjectId !== null ? "Updating project..." : "Creating project...");
    const brand = client || projectName;
    let saved = false;
    try {
      // Seed spec; the Brief & Scope analysis below replaces it and detects the primary brand.
      const spec = {
        executive_interpretation: briefText.trim(),
        commissioning_brand: { name: brand, role: "Strategic context and funding client" },
        research_subject: { description: briefText.trim(), is_brand_study: false },
        research_audience: { description: `Target audience for ${brand} research.` },
        strategic_application: `Findings will inform ${brand} strategy and positioning.`,
        business_objective: briefText.trim(),
        research_objective: briefText.trim(),
        deliverable_objective: "Research report with thematic analysis and evidence.",
        validated_entities: [{ name: brand, type: "brand", confidence: "high", reasoning: "Identified from project brief." }],
        research_questions: [
          { id: "RQ1", question: "What are the key themes and conversations?", priority: "primary", source: "inferred" },
          { id: "RQ2", question: "What are the emerging trends?", priority: "primary", source: "inferred" },
          { id: "RQ3", question: "How does the audience engage with the topic?", priority: "secondary", source: "inferred" },
        ],
        included_scope: {
          platforms: ["Social media"],
          geography,
          audience: `Target audience for ${brand}`,
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
        brief_source: briefSource ?? { type: "text" },
        client,
        geography,
        research_type: researchType,
        time_period: timePeriod,
      };
      const result = await persistProject(spec);
      saved = true;
      setLlmStatus("Analyzing brief with LLM — this may take 1–2 minutes...");
      await intelApi.generateSpec(result.id, briefText.trim(), true);
      localStorage.removeItem(DRAFT_KEY);
      onNavigate("brief-scope-review");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "unknown error";
      setError(saved
        ? `Project saved, but the brief analysis failed (${msg}). Click Analyze Brief to retry.`
        : `Could not save the project: ${msg}`);
      setCreating(false);
      setLlmStatus("");
    }
  };

  const listPage = isQC ? "qc-projects" : "projects";
  const title = `${editingId !== null ? "Edit" : "New"} ${isQC ? "QC " : ""}Project`;
  const geographyOptions = GEOGRAPHIES.some((g) => g.name === geography) ? GEOGRAPHIES : [...GEOGRAPHIES, { name: geography, code: null }];

  if (loadingProject) {
    return <div className="p-8 text-sm text-slate-400">Loading project...</div>;
  }

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-6 animate-fade-in">
      <div>
        <nav className="text-sm text-slate-500">
          <button onClick={() => onNavigate(listPage)} className="hover:text-slate-800">Projects</button>
          <span className="mx-2 text-slate-300">›</span>
          <span className="font-semibold text-slate-900">{title}</span>
        </nav>
        <h1 className="mt-2 text-xl font-semibold text-slate-900">{title}</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          {isQC ? "Name the QC project, then upload the monitoring report." : "Upload the client brief and click Extract Text (or paste it) — the project is saved when you click Analyze Brief."}
        </p>
        {draft && <span className="text-xs text-slate-400">Draft from {new Date(draft.savedAt).toLocaleDateString()}</span>}
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-5">
        <div className="grid grid-cols-2 gap-5">
          <label className="block">
            <span className="block text-xs font-medium text-slate-500 mb-1.5">Project Name</span>
            <input type="text" value={projectName} onChange={(e) => setProjectName(e.target.value)}
              placeholder={isQC ? "e.g. July 2026 QC - Acme Corp" : "e.g. Brand Audience Research"} className={INPUT} />
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-slate-500 mb-1.5">Client</span>
            <input type="text" value={client} onChange={(e) => setClient(e.target.value)} placeholder="e.g. Heineken — used as the project brand" className={INPUT} />
          </label>
        </div>

        <div className={`grid gap-5 ${isQC ? "grid-cols-1 max-w-xs" : "grid-cols-3"}`}>
          <label className="block">
            <span className="block text-xs font-medium text-slate-500 mb-1.5">Geography</span>
            <div className="relative">
              <CountryFlag country={geography} size={18} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2" />
              <select value={geography} onChange={(e) => setGeography(e.target.value)} className={`${INPUT} pl-10`}>
                {geographyOptions.map((g) => <option key={g.name}>{g.name}</option>)}
              </select>
            </div>
          </label>
          {!isQC && (
            <>
              <label className="block">
                <span className="block text-xs font-medium text-slate-500 mb-1.5">Research Type</span>
                <select value={researchType} onChange={(e) => setResearchType(e.target.value)} className={INPUT}>
                  <option>Social Listening</option>
                  <option>Audience Insights</option>
                  <option>Competitor Analysis</option>
                  <option>Brand Tracking</option>
                </select>
              </label>
              <label className="block">
                <span className="block text-xs font-medium text-slate-500 mb-1.5">Time Period</span>
                <select value={timePeriod} onChange={(e) => setTimePeriod(e.target.value)} className={INPUT}>
                  <option>Past 30 days</option>
                  <option>Past 3 months</option>
                  <option>Past 6 months</option>
                  <option>Past 12 months</option>
                </select>
              </label>
            </>
          )}
        </div>
      </div>

      {!isQC && (
        <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-4">
          <label className="block">
            <span className="block text-xs font-medium text-slate-500 mb-1.5">Client Brief</span>
            <textarea rows={12} value={briefText} onChange={(e) => {
                setBriefText(e.target.value);
                if (!e.target.value.trim()) { setBriefSource(null); setExtractionNote(""); }
              }}
              placeholder="Paste your client brief here..." className={`${INPUT} resize-y leading-relaxed`} />
          </label>
          {extractionNote && <p className="text-xs text-emerald-700">{extractionNote}</p>}

          <div
            onClick={() => fileInputRef.current?.click()}
            onDrop={onDrop}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            className={`border-2 border-dashed rounded-xl p-8 text-center transition-all cursor-pointer group ${
              dragOver ? "border-violet-400 bg-violet-50/50" : "border-slate-200 hover:border-violet-300 hover:bg-violet-50/30"
            }`}
          >
            <input ref={fileInputRef} type="file" accept=".pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.txt" className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) selectFile(file);
                e.target.value = "";
              }}
            />
            {uploadingBrief ? (
              <p className="text-sm font-medium text-violet-600">Extracting text from {pendingFile?.name ?? "file"} with NVIDIA...</p>
            ) : pendingFile ? (
              <div className="flex items-center justify-center gap-3">
                <svg className="text-violet-500 shrink-0" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" />
                </svg>
                <div className="text-left">
                  <p className="text-sm font-medium text-slate-700">{pendingFile.name} <span className="text-slate-400 font-normal">({Math.max(1, Math.round(pendingFile.size / 1024))} KB)</span></p>
                  <p className="text-xs text-violet-600">Ready — click <span className="font-semibold">Extract Text</span> to read this file</p>
                </div>
                <button type="button" aria-label="Remove selected file"
                  onClick={(e) => { e.stopPropagation(); setPendingFile(null); }}
                  className="ml-2 rounded-md px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600">✕</button>
              </div>
            ) : briefSource?.file_name ? (
              <div className="flex items-center justify-center gap-3">
                <svg className="text-emerald-600 shrink-0" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><path d="m9 15 2 2 4-4" />
                </svg>
                <div className="text-left">
                  <p className="text-sm font-medium text-slate-700">{briefSource.file_name}</p>
                  <p className="text-xs text-emerald-700">Text extracted ✓ — click or drop another file to replace</p>
                </div>
                <button type="button" aria-label="Remove file and its extracted text"
                  onClick={(e) => { e.stopPropagation(); setBriefSource(null); setBriefText(""); setExtractionNote(""); }}
                  className="ml-2 rounded-md px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600">✕</button>
              </div>
            ) : (
              <>
                <svg className="mx-auto mb-3 text-slate-300 group-hover:text-violet-400 transition-colors" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
                <p className="text-sm font-medium text-slate-600">Drop a file here or click to browse</p>
                <p className="text-xs text-slate-400 mt-1">PDF, Word, PowerPoint, or Excel — text is extracted with NVIDIA Nemotron-Parse</p>
              </>
            )}
          </div>
        </div>
      )}

      {error && <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">{error}</div>}

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
        <button onClick={() => onNavigate(listPage)} disabled={creating}
          className="px-4 py-2.5 text-sm font-medium text-slate-500 hover:text-slate-700 disabled:opacity-40">
          Cancel
        </button>
        {isQC ? (
          <button disabled={!projectName.trim() || creating} onClick={handleSaveQC}
            className="px-5 py-2.5 text-sm font-medium text-white rounded-lg shadow-sm disabled:opacity-40 disabled:cursor-not-allowed bg-[#0F7B6C] hover:bg-[#0A6558]">
            {creating ? "Saving..." : "Save & Upload Report"}
          </button>
        ) : (
          <>
            {editingId === null && (
              <button onClick={handleSaveDraft} disabled={creating}
                className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40">
                {draftSaved ? "Saved" : "Save Draft"}
              </button>
            )}
            {pendingFile ? (
              <button disabled={uploadingBrief || creating} onClick={extractText}
                className="px-5 py-2.5 text-sm font-medium text-white rounded-lg shadow-sm disabled:opacity-40 disabled:cursor-not-allowed bg-[#5B2C9D] hover:bg-[#4A2380]">
                {uploadingBrief ? "Extracting..." : "Extract Text"}
              </button>
            ) : (
              <button disabled={!briefText.trim() || !projectName.trim() || creating} onClick={handleAnalyze}
                className="px-5 py-2.5 text-sm font-medium text-white rounded-lg shadow-sm disabled:opacity-40 disabled:cursor-not-allowed bg-[#5B2C9D] hover:bg-[#4A2380]">
                {creating ? "Analyzing..." : "Analyze Brief"}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

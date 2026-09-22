import { useState, useEffect } from "react";
import { useProject, type ProjectType } from "../lib/project-context";
import { intelApi } from "../lib/intel-api";

interface RecentProject {
  id: number;
  project_name: string;
  project_type: string;
  updated_at: number;
}

export function LandingPage({ onNavigate }: { onNavigate: (page: string) => void }) {
  const { setActiveProject } = useProject();
  const [recent, setRecent] = useState<RecentProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [counts, setCounts] = useState({ research: 0, qc: 0 });

  useEffect(() => {
    intelApi
      .listProjects()
      .then((list) => {
        setRecent(list.slice(0, 5));
        setCounts({
          research: list.filter((p) => p.project_type !== "monitoring_qc").length,
          qc: list.filter((p) => p.project_type === "monitoring_qc").length,
        });
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleWorkflow = (type: ProjectType) => {
    onNavigate(type === "research" ? "new-project" : "new-qc-project");
  };

  const handleSelectRecent = (proj: RecentProject) => {
    const pType = (proj.project_type as ProjectType) || "research";
    setActiveProject({
      id: proj.id,
      name: proj.project_name,
      project_type: pType,
    });
    onNavigate(pType === "monitoring_qc" ? "qc-upload" : "dashboard");
  };

  const formatDate = (ts: number) => {
    const d = new Date(ts * 1000);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };

  return (
    <div className="flex-1 flex flex-col min-h-screen relative overflow-hidden" style={{ backgroundColor: "#f8f7fb" }}>
      {/* ── Background layers ── */}
      <div className="absolute inset-0" style={{
        background: "linear-gradient(145deg, #f8f7fb 0%, #f3f0f9 20%, #f0eef7 45%, #eef3f7 70%, #f0f5f4 100%)",
      }} />
      {/* Ambient glow — research (purple, left) */}
      <div className="absolute rounded-full" style={{
        width: 700, height: 700,
        top: "10%", left: "0%",
        background: "radial-gradient(circle, rgba(91,44,157,0.06) 0%, transparent 65%)",
        filter: "blur(80px)",
      }} />
      {/* Ambient glow — QC (teal, right) */}
      <div className="absolute rounded-full" style={{
        width: 650, height: 650,
        top: "12%", right: "0%",
        background: "radial-gradient(circle, rgba(15,123,108,0.05) 0%, transparent 65%)",
        filter: "blur(80px)",
      }} />

      {/* ── Content ── */}
      <div className="relative z-10 flex-1 flex flex-col items-center px-6 pt-16 pb-8 animate-fade-in">
        <div className="w-full" style={{ maxWidth: 1200 }}>

          {/* ── Header ── */}
          <header className="text-center mb-12 animate-fade-in">
            <div className="inline-block rounded-xl px-8 py-3 mb-8" style={{
              backgroundColor: "#ffffff",
              boxShadow: "0 1px 3px rgba(91,44,157,0.08), 0 4px 16px rgba(91,44,157,0.04)",
            }}>
              <span className="h-10 flex items-center gap-2.5">
                <img
                  src="/logo.png"
                  alt="InfoVision Intelligence"
                  className="h-9 w-9 rounded-lg object-cover"
                />
                <span className="text-xl font-bold" style={{ letterSpacing: "-0.01em" }}>
                  <span style={{ color: "#5B2C9D" }}>InfoVision</span>{" "}
                  <span style={{ color: "#1e1833", fontWeight: 500 }}>Intelligence</span>
                </span>
              </span>
            </div>
            <h1 className="mb-3" style={{ fontSize: 38, fontWeight: 700, letterSpacing: "-0.02em", lineHeight: 1.15, color: "#1e1833" }}>
              Choose how you want to work
            </h1>
            <p className="mx-auto leading-relaxed" style={{ color: "#7c7a8a", fontSize: 15, maxWidth: 480 }}>
              Start a research project or validate a monitoring report before delivery.
            </p>
          </header>

          {/* ── Workflow Cards ── */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-20 animate-fade-in-1">

            {/* Research card */}
            <button
              onClick={() => handleWorkflow("research")}
              className="group text-left flex flex-col transition-all duration-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-400/50 focus-visible:ring-offset-2"
              style={{
                borderRadius: 22,
                padding: "36px 32px 32px",
                backgroundColor: "#ffffff",
                border: "1px solid rgba(91,44,157,0.08)",
                boxShadow: "0 1px 2px rgba(91,44,157,0.04), 0 4px 24px rgba(91,44,157,0.06)",
              }}
              onMouseEnter={(e) => {
                const el = e.currentTarget;
                el.style.transform = "translateY(-4px)";
                el.style.borderColor = "rgba(91,44,157,0.18)";
                el.style.boxShadow = "0 2px 4px rgba(91,44,157,0.06), 0 12px 40px rgba(91,44,157,0.1), 0 0 0 1px rgba(91,44,157,0.04)";
              }}
              onMouseLeave={(e) => {
                const el = e.currentTarget;
                el.style.transform = "translateY(0)";
                el.style.borderColor = "rgba(91,44,157,0.08)";
                el.style.boxShadow = "0 1px 2px rgba(91,44,157,0.04), 0 4px 24px rgba(91,44,157,0.06)";
              }}
            >
              {/* Icon */}
              <div className="mb-6 flex items-center justify-center rounded-2xl" style={{
                width: 56, height: 56,
                background: "linear-gradient(135deg, rgba(91,44,157,0.1) 0%, rgba(124,58,237,0.06) 100%)",
                border: "1px solid rgba(91,44,157,0.1)",
              }}>
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="7" />
                  <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  <circle cx="11" cy="11" r="3" opacity="0.4" />
                  <line x1="11" y1="1" x2="11" y2="4" opacity="0.3" />
                  <line x1="11" y1="18" x2="11" y2="21" opacity="0.3" />
                  <line x1="1" y1="11" x2="4" y2="11" opacity="0.3" />
                  <line x1="18" y1="11" x2="21" y2="11" opacity="0.3" />
                </svg>
              </div>
              {/* Eyebrow */}
              <span className="block mb-2" style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.08em", color: "#7c3aed", textTransform: "uppercase" as const }}>
                Research Intelligence
              </span>
              {/* Title */}
              <h2 className="mb-2" style={{ fontSize: 26, fontWeight: 700, lineHeight: 1.2, letterSpacing: "-0.01em", color: "#1e1833" }}>
                Research Project
              </h2>
              {/* Description */}
              <p className="mb-6 leading-relaxed" style={{ fontSize: 15, color: "#6b6980", lineHeight: 1.6 }}>
                Turn a business question into structured research, evidence, insights and client-ready deliverables.
              </p>
              {/* Workflow steps */}
              <div className="flex items-center gap-2 mb-8" style={{ fontSize: 12, fontWeight: 500 }}>
                <span style={{ color: "#8b5cf6" }}>Brief</span>
                <span style={{ color: "#c4b5fd", fontSize: 10 }}>&rarr;</span>
                <span style={{ color: "#8b5cf6" }}>Research</span>
                <span style={{ color: "#c4b5fd", fontSize: 10 }}>&rarr;</span>
                <span style={{ color: "#8b5cf6" }}>Evidence</span>
                <span style={{ color: "#c4b5fd", fontSize: 10 }}>&rarr;</span>
                <span style={{ color: "#8b5cf6" }}>Insights</span>
                <span style={{ color: "#c4b5fd", fontSize: 10 }}>&rarr;</span>
                <span style={{ color: "#8b5cf6" }}>Deliverables</span>
              </div>
              {/* Metric */}
              {counts.research > 0 && (
                <p className="mb-5" style={{ fontSize: 12, color: "#a5a3b3" }}>
                  {counts.research} project{counts.research !== 1 ? "s" : ""}
                </p>
              )}
              {/* CTA */}
              <div className="mt-auto flex items-center gap-2 transition-all duration-200" style={{
                fontSize: 14, fontWeight: 600, color: "#7c3aed",
              }}>
                <span
                  className="px-4 py-2 rounded-lg transition-all duration-200"
                  style={{
                    backgroundColor: "rgba(91,44,157,0.08)",
                    border: "1px solid rgba(91,44,157,0.12)",
                  }}
                >
                  Start Research Project
                </span>
                <svg
                  className="transition-transform duration-200 group-hover:translate-x-0.5"
                  width="16" height="16" viewBox="0 0 24 24" fill="none"
                  stroke="#7c3aed" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                >
                  <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
                </svg>
              </div>
            </button>

            {/* QC card */}
            <button
              onClick={() => handleWorkflow("monitoring_qc")}
              className="group text-left flex flex-col transition-all duration-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50 focus-visible:ring-offset-2"
              style={{
                borderRadius: 22,
                padding: "36px 32px 32px",
                backgroundColor: "#ffffff",
                border: "1px solid rgba(15,123,108,0.08)",
                boxShadow: "0 1px 2px rgba(15,123,108,0.04), 0 4px 24px rgba(15,123,108,0.06)",
              }}
              onMouseEnter={(e) => {
                const el = e.currentTarget;
                el.style.transform = "translateY(-4px)";
                el.style.borderColor = "rgba(15,123,108,0.18)";
                el.style.boxShadow = "0 2px 4px rgba(15,123,108,0.06), 0 12px 40px rgba(15,123,108,0.1), 0 0 0 1px rgba(15,123,108,0.04)";
              }}
              onMouseLeave={(e) => {
                const el = e.currentTarget;
                el.style.transform = "translateY(0)";
                el.style.borderColor = "rgba(15,123,108,0.08)";
                el.style.boxShadow = "0 1px 2px rgba(15,123,108,0.04), 0 4px 24px rgba(15,123,108,0.06)";
              }}
            >
              {/* Icon */}
              <div className="mb-6 flex items-center justify-center rounded-2xl" style={{
                width: 56, height: 56,
                background: "linear-gradient(135deg, rgba(15,123,108,0.1) 0%, rgba(20,184,166,0.06) 100%)",
                border: "1px solid rgba(15,123,108,0.1)",
              }}>
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#0F7B6C" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                  <polyline points="9 12 11 14 15 10" />
                </svg>
              </div>
              {/* Eyebrow */}
              <span className="block mb-2" style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.08em", color: "#0F7B6C", textTransform: "uppercase" as const }}>
                Quality Assurance
              </span>
              {/* Title */}
              <h2 className="mb-2" style={{ fontSize: 26, fontWeight: 700, lineHeight: 1.2, letterSpacing: "-0.01em", color: "#1e1833" }}>
                Monitoring Quality Check
              </h2>
              {/* Description */}
              <p className="mb-6 leading-relaxed" style={{ fontSize: 15, color: "#6b6980", lineHeight: 1.6 }}>
                Validate monitoring reports for accuracy, completeness and delivery readiness before they reach the client.
              </p>
              {/* Workflow steps */}
              <div className="flex items-center gap-2 mb-8" style={{ fontSize: 12, fontWeight: 500 }}>
                <span style={{ color: "#0d9488" }}>Upload</span>
                <span style={{ color: "#99f6e4", fontSize: 10 }}>&rarr;</span>
                <span style={{ color: "#0d9488" }}>Validate</span>
                <span style={{ color: "#99f6e4", fontSize: 10 }}>&rarr;</span>
                <span style={{ color: "#0d9488" }}>Review</span>
                <span style={{ color: "#99f6e4", fontSize: 10 }}>&rarr;</span>
                <span style={{ color: "#0d9488" }}>Export</span>
              </div>
              {/* Metric */}
              {counts.qc > 0 && (
                <p className="mb-5" style={{ fontSize: 12, color: "#a5a3b3" }}>
                  {counts.qc} report{counts.qc !== 1 ? "s" : ""} checked
                </p>
              )}
              {/* CTA */}
              <div className="mt-auto flex items-center gap-2 transition-all duration-200" style={{
                fontSize: 14, fontWeight: 600, color: "#0F7B6C",
              }}>
                <span
                  className="px-4 py-2 rounded-lg transition-all duration-200"
                  style={{
                    backgroundColor: "rgba(15,123,108,0.08)",
                    border: "1px solid rgba(15,123,108,0.12)",
                  }}
                >
                  Run Quality Check
                </span>
                <svg
                  className="transition-transform duration-200 group-hover:translate-x-0.5"
                  width="16" height="16" viewBox="0 0 24 24" fill="none"
                  stroke="#0F7B6C" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                >
                  <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
                </svg>
              </div>
            </button>
          </div>

          {/* ── Recent Projects ── */}
          {!loading && recent.length > 0 && (
            <section className="animate-fade-in-2" style={{ maxWidth: 880, margin: "0 auto" }}>
              <div className="mb-5">
                <h2 className="mb-1" style={{ fontSize: 20, fontWeight: 650, color: "#1e1833" }}>
                  Continue where you left off
                </h2>
                <p style={{ fontSize: 13, color: "#9896a6" }}>
                  Your most recently accessed projects.
                </p>
              </div>
              <div className="rounded-2xl overflow-hidden" style={{
                backgroundColor: "#ffffff",
                border: "1px solid rgba(30,24,51,0.06)",
                boxShadow: "0 1px 3px rgba(30,24,51,0.04), 0 4px 16px rgba(30,24,51,0.03)",
              }}>
                {recent.map((proj, i) => {
                  const isQC = proj.project_type === "monitoring_qc";
                  return (
                    <button
                      key={proj.id}
                      onClick={() => handleSelectRecent(proj)}
                      className="group w-full flex items-center gap-4 px-5 py-4 text-left transition-all duration-200 focus:outline-none"
                      style={{
                        borderTop: i > 0 ? "1px solid rgba(30,24,51,0.05)" : "none",
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "rgba(91,44,157,0.03)"; }}
                      onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "transparent"; }}
                    >
                      {/* Icon */}
                      <div
                        className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                        style={{
                          backgroundColor: isQC ? "rgba(15,123,108,0.08)" : "rgba(91,44,157,0.08)",
                          border: `1px solid ${isQC ? "rgba(15,123,108,0.12)" : "rgba(91,44,157,0.12)"}`,
                        }}
                      >
                        {isQC ? (
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0F7B6C" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" />
                          </svg>
                        ) : (
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
                          </svg>
                        )}
                      </div>
                      {/* Info */}
                      <div className="flex-1 min-w-0">
                        <p className="truncate" style={{ fontSize: 15, fontWeight: 600, color: "#2d2545" }}>
                          {proj.project_name}
                        </p>
                        <p style={{ fontSize: 12, color: "#9896a6", marginTop: 2 }}>
                          {isQC ? "Monitoring Quality Check" : "Research Project"}
                        </p>
                      </div>
                      {/* Date */}
                      <span style={{ fontSize: 12, color: "#b0aebf", whiteSpace: "nowrap" as const }}>
                        Updated {formatDate(proj.updated_at)}
                      </span>
                      {/* Badge */}
                      <span className="shrink-0 rounded-md px-2.5 py-1" style={{
                        fontSize: 11, fontWeight: 600,
                        backgroundColor: isQC ? "rgba(15,123,108,0.08)" : "rgba(91,44,157,0.08)",
                        color: isQC ? "#0F7B6C" : "#7c3aed",
                        border: `1px solid ${isQC ? "rgba(15,123,108,0.1)" : "rgba(91,44,157,0.1)"}`,
                      }}>
                        {isQC ? "Monitoring QC" : "Research"}
                      </span>
                      {/* Chevron */}
                      <svg
                        className="shrink-0 transition-transform duration-200 group-hover:translate-x-0.5"
                        width="16" height="16" viewBox="0 0 24 24" fill="none"
                        stroke="#c4c2d0" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                      >
                        <polyline points="9 18 15 12 9 6" />
                      </svg>
                    </button>
                  );
                })}
              </div>
            </section>
          )}
        </div>
      </div>

      {/* ── Footer ── */}
      <div className="relative z-10 text-center py-5">
        <p style={{ fontSize: 11, color: "#b0aebf" }}>
          InfoVision, Inc. &middot; Human Wisdom. AI Precision.
        </p>
      </div>
    </div>
  );
}

import { useEffect, useState, type ReactNode } from "react";
import { Settings, api } from "../services/api";

type TextKey = "repo_dir" | "briefs_dir" | "output_dir";

const TEXT_FIELDS: { key: TextKey; label: string }[] = [
  { key: "repo_dir", label: "Repository folder (past project decks)" },
  { key: "briefs_dir", label: "Briefs inbox (watched folder)" },
  { key: "output_dir", label: "Output folder" },
];

const INPUT = "w-full text-sm px-2.5 py-1.5 border border-slate-200 rounded-md focus:outline-none focus:ring-1 focus:ring-[#5B2C9D]";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block mb-3">
      <span className="block text-xs font-medium text-slate-500 mb-1">{label}</span>
      {children}
    </label>
  );
}

/** Brief-to-Deck agent settings (folders, models), persisted to agent/data/settings.json. */
export function SettingsPanel({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getSettings().then(setSettings).catch((e) => setError(e instanceof Error ? e.message : "Could not load settings"));
  }, []);

  const set = <K extends keyof Settings>(key: K, value: Settings[K]) =>
    setSettings((s) => (s ? { ...s, [key]: value } : s));

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    setError("");
    try {
      await api.saveSettings(settings);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save settings");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40" onClick={onClose}>
      <div className="w-full max-w-lg max-h-[85vh] overflow-y-auto rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-base font-semibold text-slate-900 mb-4">Settings</h2>
        {error && <p className="mb-3 text-xs text-red-600">{error}</p>}
        {!settings && !error && <p className="text-sm text-slate-500">Loading…</p>}

        {settings && (
          <>
            {TEXT_FIELDS.map(({ key, label }) => (
              <Field key={key} label={label}>
                <input className={INPUT} value={settings[key]} onChange={(e) => set(key, e.target.value)} />
              </Field>
            ))}
            <Field label="Ignore patterns (comma-separated)">
              <input
                className={INPUT}
                value={settings.ignore_patterns.join(", ")}
                onChange={(e) => set("ignore_patterns", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
              />
            </Field>
            <Field label="Candidate slides to consider (top K)">
              <input
                className={INPUT}
                type="number"
                value={settings.top_k_candidates}
                onChange={(e) => set("top_k_candidates", parseInt(e.target.value || "8", 10))}
              />
            </Field>
          </>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button className="px-3 py-1.5 text-sm rounded-lg text-slate-600 hover:bg-slate-100" onClick={onClose}>
            Cancel
          </button>
          <button
            className="px-3 py-1.5 text-sm rounded-lg text-white bg-[#5B2C9D] hover:bg-[#4a2380] disabled:opacity-50"
            onClick={save}
            disabled={saving || !settings}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

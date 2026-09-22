import React, { useEffect, useState } from "react";
import { Settings, api } from "../lib/api";

export function SettingsPanel({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.getSettings().then(setSettings);
  }, []);

  if (!settings) return null;

  const set = (key: keyof Settings, value: any) => setSettings({ ...settings, [key]: value });

  const save = async () => {
    setSaving(true);
    try {
      await api.saveSettings(settings);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-title">Settings</div>

        <div className="field-group">
          <label className="field-label">Repository folder (past project decks)</label>
          <input value={settings.repo_dir} onChange={(e) => set("repo_dir", e.target.value)} />
        </div>
        <div className="field-group">
          <label className="field-label">Briefs inbox (watched folder)</label>
          <input value={settings.briefs_dir} onChange={(e) => set("briefs_dir", e.target.value)} />
        </div>
        <div className="field-group">
          <label className="field-label">Output folder</label>
          <input value={settings.output_dir} onChange={(e) => set("output_dir", e.target.value)} />
        </div>
        <div className="field-group">
          <label className="field-label">Ignore patterns (comma-separated)</label>
          <input
            value={settings.ignore_patterns.join(", ")}
            onChange={(e) => set("ignore_patterns", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
          />
        </div>
        <div className="field-group">
          <label className="field-label">Ollama host</label>
          <input value={settings.ollama_host} onChange={(e) => set("ollama_host", e.target.value)} />
        </div>
        <div className="field-group">
          <label className="field-label">Embedding model</label>
          <input value={settings.embed_model} onChange={(e) => set("embed_model", e.target.value)} />
        </div>
        <div className="field-group">
          <label className="field-label">Chat / reasoning model</label>
          <input value={settings.chat_model} onChange={(e) => set("chat_model", e.target.value)} />
        </div>
        <div className="field-group">
          <label className="field-label">Candidate slides to consider (top K)</label>
          <input
            type="number"
            value={settings.top_k_candidates}
            onChange={(e) => set("top_k_candidates", parseInt(e.target.value || "8", 10))}
          />
        </div>

        <div className="modal-actions">
          <button className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

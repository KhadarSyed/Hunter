import { useState } from "react";
import { Icon } from "@iconify/react";
import { intelApi } from "../../services/intel-api";
import type { UploadedFile } from "../../types/dataset";

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

/** One small chip per uploaded file (type icon, articles added, remove); details in the tooltip. */
export function UploadedFiles({ projectId, files, onRemoved }: {
  projectId: number; files: UploadedFile[]; onRemoved: () => void;
}) {
  const [confirm, setConfirm] = useState<{ file: UploadedFile; articles: number; approved: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (files.length === 0) return null;

  const ask = async (f: UploadedFile) => {
    setError(null);
    try { setConfirm({ file: f, ...(await intelApi.datasetFileImpact(projectId, f.id)) }); }
    catch (e) { setError(errMsg(e, "Could not check this file")); }
  };
  const remove = async () => {
    if (!confirm) return;
    setBusy(true);
    try { await intelApi.deleteDatasetFile(projectId, confirm.file.id); setConfirm(null); onRemoved(); }
    catch (e) { setError(errMsg(e, "Could not remove the file")); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-2">
      <ul className="flex flex-wrap gap-2" aria-label="Uploaded files">
        {files.map((f) => {
          const csv = f.file_name.toLowerCase().endsWith(".csv");
          const tip = `${f.file_name} · ${f.rows_read ?? 0} rows · ${f.added ?? 0} added · ${f.duplicates ?? 0} duplicates${f.error ? ` · ${f.error}` : ""}`;
          return (
            <li key={f.id} title={tip}
              className={`inline-flex items-center gap-1.5 rounded-full border bg-white py-1 pl-2 pr-1 text-xs ${f.error ? "border-red-200" : "border-slate-200"}`}>
              <Icon icon={f.error ? "lucide:file-warning" : csv ? "lucide:file-text" : "lucide:file-spreadsheet"} width={14} aria-hidden
                className={f.error ? "text-red-500" : csv ? "text-slate-500" : "text-emerald-600"} />
              <span className="font-semibold tabular-nums text-slate-700">{(f.added ?? 0).toLocaleString()}</span>
              <span className="sr-only">{f.file_name}</span>
              <button type="button" onClick={() => void ask(f)} aria-label={`Remove ${f.file_name}`}
                className="rounded-full p-0.5 text-slate-400 hover:bg-red-50 hover:text-red-600">
                <Icon icon="lucide:x" width={12} aria-hidden />
              </button>
            </li>
          );
        })}
      </ul>
      {confirm && (
        <div role="alertdialog" aria-label="Remove file" className="flex flex-wrap items-center gap-3 rounded-lg border border-red-100 bg-red-50 px-4 py-2 text-sm text-red-800">
          <span>Remove <b>{confirm.file.file_name}</b>? {confirm.articles.toLocaleString()} articles ({confirm.approved.toLocaleString()} approved) leave the data set.</span>
          <span className="ml-auto flex gap-2">
            <button type="button" onClick={() => setConfirm(null)} className="rounded-lg px-3 py-1 text-xs font-medium text-slate-600 hover:bg-white">Cancel</button>
            <button type="button" disabled={busy} onClick={() => void remove()} className="rounded-lg bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50">
              {busy ? "Removing…" : "Remove"}
            </button>
          </span>
        </div>
      )}
      {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
    </div>
  );
}

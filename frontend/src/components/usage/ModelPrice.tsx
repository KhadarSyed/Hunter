import { useState } from "react";
import { intelApi } from "../../services/intel-api";
import type { UsagePrice, UsagePrices } from "../../types/usage";

const FIELDS = [
  ["input_per_m", "Input"],
  ["cached_per_m", "Cached input"],
  ["output_per_m", "Output"],
] as const;
type PriceKey = (typeof FIELDS)[number][0];

const today = () => new Date().toISOString().slice(0, 10);   // UTC day, as the backend dates prices

/** The price in force today, matched like the backend: exact model first, else the longest stored prefix. */
export function priceFor(all: UsagePrices, provider: string, model: string): UsagePrice | undefined {
  const dep = provider === "azure_openai" ? all.deployment_type : "";
  const rows = all.prices
    .filter((p) => p.provider === provider && (p.deployment_type === dep || p.deployment_type === "") && p.effective_from <= today())
    .sort((a, b) => b.effective_from.localeCompare(a.effective_from));
  return rows.find((p) => p.model === model)
    ?? rows.filter((p) => model.startsWith(p.model)).sort((a, b) => b.model.length - a.model.length)[0];
}

const usd = (n: number) => `$${n.toFixed(n > 0 && n < 0.1 ? 3 : 2)}`;

type Props = { provider: string; model: string; prices: UsagePrices; canEdit: boolean; onSaved: () => void };

/** One model's price per 1M tokens (what the Usage page costs its calls at); a saved edit applies from today. */
export function ModelPrice({ provider, model, prices, canEdit, onSaved }: Props) {
  const current = priceFor(prices, provider, model);
  const [draft, setDraft] = useState<Record<PriceKey, string> | null>(null);
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  const open = () => {
    setError("");
    setDraft({
      input_per_m: String(current?.input_per_m ?? ""), cached_per_m: String(current?.cached_per_m ?? ""),
      output_per_m: String(current?.output_per_m ?? ""),
    });
  };
  const save = async () => {
    if (!draft) return;
    const valid = FIELDS.every(([k]) => draft[k].trim() !== "" && Number.isFinite(Number(draft[k])) && Number(draft[k]) >= 0);
    if (!valid) {
      setError("Enter all three prices as numbers of 0 or more.");
      return;
    }
    setIsSaving(true); setError("");
    try {
      await intelApi.setUsagePrice({
        provider, model, deployment_type: provider === "azure_openai" ? prices.deployment_type : "",
        input_per_m: Number(draft.input_per_m), cached_per_m: Number(draft.cached_per_m),
        output_per_m: Number(draft.output_per_m), effective_from: today(),
      });
      setDraft(null);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the price");
    } finally {
      setIsSaving(false);
    }
  };

  if (draft) {
    return (
      <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3">
        <div className="mb-2 text-xs font-medium text-slate-700">
          Price per 1M tokens for <span className="font-mono">{model}</span> (USD; {current ? "applies to calls from today" : "the first price also costs this model's earlier calls"})
        </div>
        <div className="flex flex-wrap items-end gap-2">
          {FIELDS.map(([k, label]) => (
            <label key={k} className="text-xs text-slate-600">{label}
              <input type="number" min={0} step="0.001" inputMode="decimal" value={draft[k]}
                     onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
                     className="mt-1 block w-28 rounded-lg border border-slate-200 px-2 py-1.5 text-sm" />
            </label>
          ))}
          <button type="button" onClick={save} disabled={isSaving}
                  className="rounded-lg bg-[#5B2C9D] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#4a2380] disabled:opacity-50">
            {isSaving ? "Saving…" : "Save price"}
          </button>
          <button type="button" onClick={() => setDraft(null)}
                  className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">Cancel</button>
        </div>
        {error && <p role="alert" className="mt-2 text-xs text-red-600">{error}</p>}
      </div>
    );
  }
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-600">
      <span className="font-medium text-slate-700">Price / 1M tokens:</span>
      {current ? (
        <>
          <span>Input {usd(current.input_per_m)}</span>
          <span>Cached {usd(current.cached_per_m)}</span>
          <span>Output {usd(current.output_per_m)}</span>
          <span className="text-slate-400">since {current.effective_from}</span>
        </>
      ) : <span className="text-amber-700">not set (calls are costed at $0)</span>}
      {canEdit && (
        <button type="button" onClick={open} className="font-medium text-[#5B2C9D] hover:underline">
          {current ? "Edit" : "Set price"}
        </button>
      )}
    </div>
  );
}

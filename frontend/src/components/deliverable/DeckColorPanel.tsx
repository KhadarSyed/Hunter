import { useEffect, useState } from "react";
import { Icon } from "@iconify/react";
import { intelApi } from "../../services/intel-api";
import type { DeckDesign, DeckDesignResult } from "../../services/intel-api";

type Field = "primary" | "accent";
type Busy = "preview" | "apply" | "reset" | null;

const FIELD_LABEL: Record<Field, string> = { primary: "Primary", accent: "Accent" };
// The server's contrast guard, in words: primary sits under white header text, accent is text on the page
const WHY: Record<Field, string> = {
  primary: "too light for the white text on headers and covers; pick a darker shade",
  accent: "too light to read as text on the page; pick a darker shade",
};
const HEX = /^[0-9A-Fa-f]{6}$/;

function rejectedMessage(result: DeckDesignResult): string {
  return (Object.keys(result.rejected) as Field[])
    .map((k) => `${FIELD_LABEL[k] ?? k} ${result.rejected[k] === "fails the contrast guard" ? WHY[k] : result.rejected[k]}`)
    .join(". ");
}

type ColorFieldProps = { field: Field; value: string; isActive: boolean; onFocus: () => void; onChange: (hex: string) => void };

function ColorField({ field, value, isActive, onFocus, onChange }: ColorFieldProps) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <div className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 ${isActive ? "border-[#5B2C9D] ring-1 ring-[#5B2C9D]" : "border-slate-200"}`}
      onClick={onFocus}>
      <input type="color" aria-label={`${FIELD_LABEL[field]} colour`} value={`#${value}`} onFocus={onFocus}
        onChange={(e) => onChange(e.target.value.slice(1).toUpperCase())}
        className="h-7 w-7 cursor-pointer rounded border-0 bg-transparent p-0" />
      <span className="text-xs font-semibold text-slate-700">{FIELD_LABEL[field]}</span>
      <input aria-label={`${FIELD_LABEL[field]} hex`} value={text} maxLength={7} onFocus={onFocus}
        onChange={(e) => {
          const hex = e.target.value.replace("#", "").toUpperCase();
          setText(hex);
          if (HEX.test(hex)) onChange(hex);
        }}
        className="w-20 rounded border border-slate-200 px-1.5 py-0.5 font-mono text-xs uppercase text-slate-700" />
    </div>
  );
}

type Props = {
  projectId: number;
  runId: number;
  /** Shows a deck file in the preview: "preview.html" after a preview, "deck.html" otherwise (re-fetched). */
  onShow: (file: string) => void;
};

/** Pick the deck's brand colours after it is built: preview them on every slide, then apply to the downloads. */
export function DeckColorPanel({ projectId, runId, onShow }: Props) {
  const [design, setDesign] = useState<DeckDesign | null>(null);
  const [colors, setColors] = useState<Record<Field, string>>({ primary: "", accent: "" });
  const [active, setActive] = useState<Field>("primary");
  const [busy, setBusy] = useState<Busy>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "warn" | "error"; text: string } | null>(null);

  useEffect(() => {
    let ignore = false;
    intelApi.deckDesign(projectId, runId)
      .then((d) => {
        if (ignore) return;
        setDesign(d);
        setColors({ primary: d.primary, accent: d.accent });
      })
      .catch(() => { if (!ignore) setDesign(null); });   // runs without a studio deck: no panel
    return () => { ignore = true; };
  }, [projectId, runId]);

  if (!design) return null;
  const isChanged = colors.primary !== design.primary || colors.accent !== design.accent;
  const change = { primary: colors.primary, accent: colors.accent };

  const run = async (kind: Exclude<Busy, null>) => {
    setBusy(kind);
    setMessage(null);
    try {
      const result = kind === "preview" ? await intelApi.deckDesignPreview(projectId, runId, change)
        : kind === "apply" ? await intelApi.deckDesignApply(projectId, runId, change)
        : await intelApi.deckDesignReset(projectId, runId);
      const rejected = rejectedMessage(result);
      if (kind === "preview") {
        setIsPreviewing(result.applied.length > 0);
        onShow(result.applied.length > 0 ? "preview.html" : "deck.html");
      } else {
        const fresh = await intelApi.deckDesign(projectId, runId);
        setDesign(fresh);
        setColors({ primary: fresh.primary, accent: fresh.accent });
        setIsPreviewing(false);
        onShow("deck.html");
      }
      const done = kind === "preview" ? "Preview shows the new colours on every slide; Apply to update the downloads."
        : kind === "apply" ? "Applied: the .pptx and .pdf downloads now use these colours."
        : "Back to the deck's original colours.";
      setMessage(rejected ? { kind: "warn", text: rejected } : result.applied.length ? { kind: "ok", text: done }
        : { kind: "warn", text: "Nothing changed." });
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof Error ? e.message.replace(/^\d+: /, "") : "Request failed" });
    } finally {
      setBusy(null);
    }
  };

  const cancelPreview = () => {
    setColors({ primary: design.primary, accent: design.accent });
    setIsPreviewing(false);
    setMessage(null);
    onShow("deck.html");
  };

  const messageStyle = { ok: "text-emerald-700", warn: "text-amber-700", error: "text-red-700" };
  const isBusy = busy !== null;
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-slate-800">
          <Icon icon="lucide:palette" width={16} className="text-[#5B2C9D]" /> Brand colours
        </p>
        {(["primary", "accent"] as const).map((f) => (
          <ColorField key={f} field={f} value={colors[f]} isActive={active === f} onFocus={() => setActive(f)}
            onChange={(hex) => setColors((c) => ({ ...c, [f]: hex }))} />
        ))}
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={`Brand swatches, sets ${FIELD_LABEL[active]}`}>
          {design.swatches.map((s) => (
            <button key={s} type="button" title={`#${s} → ${FIELD_LABEL[active]}`} aria-label={`Use #${s} as ${FIELD_LABEL[active]}`}
              onClick={() => setColors((c) => ({ ...c, [active]: s }))}
              className={`h-6 w-6 rounded-full border-2 transition hover:scale-110 ${colors[active] === s ? "border-slate-900" : "border-white shadow"}`}
              style={{ backgroundColor: `#${s}` }} />
          ))}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" disabled={!isChanged || isBusy} onClick={() => run("preview")}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[#5B2C9D] px-3 py-1.5 text-xs font-semibold text-[#5B2C9D] disabled:opacity-50">
          <Icon icon={busy === "preview" ? "lucide:loader-circle" : "lucide:eye"} width={14} className={busy === "preview" ? "animate-spin" : ""} />
          {busy === "preview" ? "Rendering..." : "Preview"}
        </button>
        <button type="button" disabled={!isChanged || isBusy} onClick={() => run("apply")}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[#5B2C9D] px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#4a2380] disabled:opacity-50">
          <Icon icon={busy === "apply" ? "lucide:loader-circle" : "lucide:check"} width={14} className={busy === "apply" ? "animate-spin" : ""} />
          {busy === "apply" ? "Re-exporting the deck (about a minute)..." : "Apply to deck"}
        </button>
        {isPreviewing && !isBusy && (
          <button type="button" onClick={cancelPreview} className="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900">
            Cancel preview
          </button>
        )}
        {design.can_reset && (
          <button type="button" disabled={isBusy} onClick={() => run("reset")}
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 disabled:opacity-50">
            <Icon icon={busy === "reset" ? "lucide:loader-circle" : "lucide:rotate-ccw"} width={14} className={busy === "reset" ? "animate-spin" : ""} />
            {busy === "reset" ? "Restoring..." : "Reset to original"}
          </button>
        )}
        {message && <p role="status" className={`text-xs ${messageStyle[message.kind]}`}>{message.text}</p>}
      </div>
    </div>
  );
}

import { Icon } from "@iconify/react";
import { providerLabel } from "./format";

const PROVIDER_ICONS: Record<string, string> = { azure_openai: "logos:microsoft-azure", nvidia: "logos:nvidia" };

/** The provider's logo (plus the OpenAI mark for GPT models) beside the full model name. Logos are decorative:
 * the provider is named in the title and the model name is always visible. `nameless` shows the logos only. */
export function ProviderLogo({ provider, model, size = 16, nameless = false }:
  { provider: string; model: string; size?: number; nameless?: boolean }) {
  const icon = PROVIDER_ICONS[provider] ?? "lucide:cpu";
  const isGpt = /^gpt|^o\d/i.test(model);
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5" title={`${providerLabel(provider)} · ${model}`}>
      <Icon icon={icon} width={size} height={size} aria-hidden className="shrink-0" />
      {isGpt && <Icon icon="simple-icons:openai" width={size} height={size} aria-hidden className="shrink-0 text-slate-800" />}
      {nameless ? <span className="sr-only">{model}</span> : <span className="truncate font-medium text-slate-800">{model}</span>}
    </span>
  );
}

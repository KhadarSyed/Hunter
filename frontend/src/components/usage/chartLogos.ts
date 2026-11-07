import * as am5 from "@amcharts/amcharts5";

/** Provider logos for amCharts `Picture` sprites, matching ProviderLogo: the provider mark, plus the OpenAI mark for GPT models. */
const PROVIDER_LOGO_URLS: Record<string, string> = {
  azure_openai: "https://api.iconify.design/logos/microsoft-azure.svg",
  nvidia: "https://api.iconify.design/logos/nvidia.svg",
  anthropic: "https://api.iconify.design/simple-icons/anthropic.svg",
  gemini: "https://api.iconify.design/logos/google-gemini.svg",
};
const OPENAI_LOGO_URL = "https://api.iconify.design/simple-icons/openai.svg";

export function logoUrls(provider: string, model: string): string[] {
  const urls = PROVIDER_LOGO_URLS[provider] ? [PROVIDER_LOGO_URLS[provider]] : [];
  if (/^gpt|^o\d/i.test(model)) urls.push(OPENAI_LOGO_URL);
  return urls;
}

/** A row of logos; a logo that fails to load just leaves its slot empty, the text beside it still names the model. */
export function logoRow(root: am5.Root, urls: string[], size: number, settings: am5.IContainerSettings = {}): am5.Container {
  const row = am5.Container.new(root, { layout: root.horizontalLayout, ...settings });
  for (const src of urls) {
    row.children.push(am5.Picture.new(root, { src, width: size, height: size, marginRight: 3, centerY: am5.p50, y: am5.p50 }));
  }
  return row;
}

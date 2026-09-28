import { Icon } from "@iconify/react";

/**
 * Geographies offered on the New Project form, with ISO 3166-1 alpha-2 codes for
 * Iconify's `circle-flags` set. `code: null` = multi-country scope (globe icon).
 */
export const GEOGRAPHIES: { name: string; code: string | null }[] = [
  { name: "Global", code: null },
  { name: "United States", code: "us" },
  { name: "United Kingdom", code: "gb" },
  { name: "Canada", code: "ca" },
  { name: "India", code: "in" },
  { name: "Australia", code: "au" },
  { name: "Germany", code: "de" },
  { name: "France", code: "fr" },
  { name: "Spain", code: "es" },
  { name: "Italy", code: "it" },
  { name: "Netherlands", code: "nl" },
  { name: "Singapore", code: "sg" },
  { name: "Japan", code: "jp" },
  { name: "United Arab Emirates", code: "ae" },
  { name: "Brazil", code: "br" },
  { name: "Mexico", code: "mx" },
];

const ALIASES: Record<string, string> = { usa: "us", us: "us", uk: "gb", "great britain": "gb", uae: "ae" };

/** ISO code for a country name ("Global"/unknown → null). */
export function countryCode(country: string): string | null {
  const key = country.trim().toLowerCase();
  if (!key) return null;
  return ALIASES[key] ?? GEOGRAPHIES.find((g) => g.name.toLowerCase() === key)?.code ?? null;
}

interface CountryFlagProps {
  country: string;
  size?: number;
  /** Render the country name next to the flag. */
  showLabel?: boolean;
  className?: string;
}

/** Circular country flag (Iconify circle-flags); a globe for Global/multi-country scope. */
export function CountryFlag({ country, size = 16, showLabel = false, className = "" }: CountryFlagProps) {
  if (!country.trim()) return null;
  const code = countryCode(country);
  const icon = code ? `circle-flags:${code}` : "mdi:earth";
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`} title={country}>
      <Icon icon={icon} width={size} height={size} className={code ? "" : "text-sky-600"} aria-hidden />
      {showLabel && <span>{country}</span>}
    </span>
  );
}

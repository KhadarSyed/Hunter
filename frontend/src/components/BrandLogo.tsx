import { useEffect, useState } from "react";
import { intelApi } from "../services/intel-api";

// Module-level cache so navigating between pages / re-rendering the same brand
// name doesn't re-fetch every time. Frontend-side complement to the backend's
// own process-lifetime cache. Deliberately minimal — no external state library.
const logoCache = new Map<string, string | null>();
// brands whose logo is white: drawn on a dark chip, or it vanishes on the light page
const lightLogos = new Set<string>();
// project logos that are a photo of the brief's theme (no client brand logo): cropped to fill, never letterboxed
const themePhotos = new Set<string>();

const MONOGRAM_COLORS = [
  "bg-violet-100 text-violet-700",
  "bg-sky-100 text-sky-700",
  "bg-emerald-100 text-emerald-700",
  "bg-amber-100 text-amber-700",
  "bg-rose-100 text-rose-700",
  "bg-teal-100 text-teal-700",
];

function monogramClasses(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return MONOGRAM_COLORS[hash % MONOGRAM_COLORS.length];
}

interface BrandLogoProps {
  brandName: string;
  size?: number;
  className?: string;
  /** Corner style of the logo/monogram (default: circle). */
  rounded?: "full" | "lg";
  /** The project whose own logo this is: its client brand's logo, else a photo of its brief's main theme. */
  projectId?: number | null;
}

export function BrandLogo({ brandName, size = 20, className = "", rounded = "full", projectId }: BrandLogoProps) {
  const radius = rounded === "full" ? "rounded-full" : "rounded-lg";
  const cacheKey = projectId ? `project:${projectId}:${brandName}` : brandName;
  const [logoUrl, setLogoUrl] = useState<string | null | undefined>(() =>
    logoCache.get(cacheKey)
  );
  const [imgFailed, setImgFailed] = useState(false);

  useEffect(() => {
    setImgFailed(false);

    if (!brandName.trim() && !projectId) {
      setLogoUrl(null);
      return;
    }

    if (logoCache.has(cacheKey)) {
      setLogoUrl(logoCache.get(cacheKey) ?? null);
      return;
    }

    let cancelled = false;
    setLogoUrl(undefined); // undefined = loading

    const lookup = projectId
      ? intelApi.getProjectLogo(projectId)
      : intelApi.getBrandLogo(brandName).then((res) => ({ ...res, source: "brand" }));
    lookup
      .then((res) => {
        if (cancelled) return;
        logoCache.set(cacheKey, res.logo_url);
        if (res.is_light) lightLogos.add(cacheKey);
        if (res.source === "theme") themePhotos.add(cacheKey);
        setLogoUrl(res.logo_url);
      })
      .catch(() => {
        if (cancelled) return;
        logoCache.set(cacheKey, null);
        setLogoUrl(null);
      });

    return () => {
      cancelled = true;
    };
  }, [brandName, cacheKey, projectId]);

  const dimension = { width: size, height: size };

  // Loading: neutral placeholder, no layout shift.
  if (logoUrl === undefined) {
    return (
      <span
        className={`inline-block ${radius} bg-slate-100 shrink-0 ${className}`}
        style={dimension}
        aria-hidden="true"
      />
    );
  }

  // Success: real logo image, falls back to monogram on load failure.
  if (logoUrl && !imgFailed) {
    return (
      <img
        src={logoUrl}
        alt={`${brandName} logo`}
        className={`${radius} ${rounded === "full" || themePhotos.has(cacheKey) ? "object-cover" : "object-contain"} shrink-0 ${lightLogos.has(cacheKey) ? "bg-[#5B2C9D] p-[8%]" : ""} ${className}`}
        style={dimension}
        onError={() => setImgFailed(true)}
      />
    );
  }

  // Failure (no logo_url, network error, or broken image): monogram fallback.
  const initial = brandName.trim().charAt(0).toUpperCase() || "?";
  return (
    <span
      className={`inline-flex items-center justify-center ${radius} font-semibold shrink-0 ${monogramClasses(brandName)} ${className}`}
      style={{ ...dimension, fontSize: Math.max(9, size * 0.5) }}
      aria-hidden="true"
    >
      {initial}
    </span>
  );
}

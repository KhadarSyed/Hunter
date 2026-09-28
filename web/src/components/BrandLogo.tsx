import { useEffect, useState } from "react";
import { intelApi } from "../services/intel-api";

// Module-level cache so navigating between pages / re-rendering the same brand
// name doesn't re-fetch every time. Frontend-side complement to the backend's
// own process-lifetime cache. Deliberately minimal — no external state library.
const logoCache = new Map<string, string | null>();

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
}

export function BrandLogo({ brandName, size = 20, className = "", rounded = "full" }: BrandLogoProps) {
  const radius = rounded === "full" ? "rounded-full" : "rounded-lg";
  const [logoUrl, setLogoUrl] = useState<string | null | undefined>(() =>
    logoCache.get(brandName)
  );
  const [imgFailed, setImgFailed] = useState(false);

  useEffect(() => {
    setImgFailed(false);

    if (!brandName.trim()) {
      setLogoUrl(null);
      return;
    }

    if (logoCache.has(brandName)) {
      setLogoUrl(logoCache.get(brandName) ?? null);
      return;
    }

    let cancelled = false;
    setLogoUrl(undefined); // undefined = loading

    intelApi
      .getBrandLogo(brandName)
      .then((res) => {
        if (cancelled) return;
        logoCache.set(brandName, res.logo_url);
        setLogoUrl(res.logo_url);
      })
      .catch(() => {
        if (cancelled) return;
        logoCache.set(brandName, null);
        setLogoUrl(null);
      });

    return () => {
      cancelled = true;
    };
  }, [brandName]);

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
        className={`${radius} ${rounded === "full" ? "object-cover" : "object-contain"} shrink-0 ${className}`}
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

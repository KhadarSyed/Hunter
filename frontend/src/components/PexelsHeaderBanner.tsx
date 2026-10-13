import { useEffect, useState } from "react";
import { intelApi } from "../services/intel-api";
import { BrandLogo } from "./BrandLogo";

interface Props {
  /** Brand/project name used as the Pexels search query — pass
   * `activeProject?.brand || activeProject?.name`. */
  brandName: string | undefined;
  className?: string;
  /** "banner" (default): a small h-40 rounded card, as used at the top of every stage
   * page. "fullscreen": fills the nearest `relative` ancestor edge-to-edge — for a
   * single prominent empty/call-to-action state (e.g. Search Strategy's "Generate
   * Strategy" screen) rather than a persistent header; render it as that state's own
   * background instead of alongside a small banner. */
  variant?: "banner" | "fullscreen";
}

/** Branded background (Pexels video, falling back to a still photo) — same visual
 * language as Brief & Scope's header and Background Research's per-section video
 * banner, extracted here so every other stage page/state gets it with one line
 * instead of duplicating the fetch + markup. */
export function PexelsHeaderBanner({ brandName, className = "", variant = "banner" }: Props) {
  const [bgImage, setBgImage] = useState<string | null>(null);
  const [bgVideo, setBgVideo] = useState<string | null>(null);
  const [sourceUrl, setSourceUrl] = useState<string | null>(null);

  useEffect(() => {
    setBgImage(null);
    setBgVideo(null);
    setSourceUrl(null);
    if (!brandName?.trim()) return;
    let cancelled = false;
    // "company" disambiguates a brand name that's also a common dictionary word (Apple,
    // Dove, Target, Shell...) away from Pexels' literal stock photos for that word —
    // confirmed live ("Apple" alone surfaced fruit photography).
    intelApi.getPexelsImage(`${brandName} company`).then((res) => {
      if (cancelled) return;
      setBgImage(res.image_url);
      setBgVideo(res.video_url);
      setSourceUrl(res.source_url);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [brandName]);

  if (!bgImage && !bgVideo) return null;

  const isFullscreen = variant === "fullscreen";

  return (
    <div
      className={`${isFullscreen ? "absolute inset-0" : "relative h-40 shrink-0 rounded-2xl border border-slate-200"} overflow-hidden bg-slate-900 ${className}`}
    >
      {bgVideo ? (
        <video
          src={bgVideo}
          poster={bgImage || undefined}
          autoPlay muted loop playsInline
          className="absolute inset-0 w-full h-full object-cover"
          aria-hidden="true"
        />
      ) : (
        <img src={bgImage!} alt="" className="absolute inset-0 w-full h-full object-cover" aria-hidden="true" />
      )}
      <div
        className={isFullscreen
          ? "absolute inset-0 bg-black/45"
          : "absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent"}
      />
      {!isFullscreen && brandName && (
        <div className="absolute bottom-3 left-4 flex items-center gap-2">
          <BrandLogo brandName={brandName} size={28} rounded="lg" className="shadow-lg" />
          <span className="text-white text-sm font-semibold" style={{ textShadow: "0 1px 3px rgba(0,0,0,0.6)" }}>
            {brandName}
          </span>
        </div>
      )}
      {sourceUrl && (
        <a
          href={sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="absolute bottom-2 right-3 text-[10px] text-white/70 hover:text-white transition-colors z-10"
        >
          {bgVideo ? "Video via Pexels" : "Photo via Pexels"}
        </a>
      )}
    </div>
  );
}

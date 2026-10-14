import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

// The 60-second how-to guide, built with HyperFrames from docs/video-guide/ and copied into public/videos/.
const GUIDE_VIDEO_SRC = "/videos/hunter-how-to-60s.mp4";

/** Sidebar "?" button that opens the how-to video in a popup. */
export function HelpVideoButton() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="Help: how to use Hunter (60-second video)"
        aria-label="Help video"
        className="w-10 h-10 flex items-center justify-center rounded-lg text-slate-400 hover:bg-slate-50 hover:text-slate-600 transition-colors"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      </button>

      {open && createPortal(
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/70 p-6 backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="help-video-title"
            className="w-full max-w-5xl overflow-hidden rounded-2xl bg-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
              <div>
                <h2 id="help-video-title" className="text-base font-bold text-slate-900">How to use Hunter</h2>
                <p className="text-xs text-slate-500">From a client brief to a branded deck in eight steps · 60 seconds</p>
              </div>
              <button
                onClick={() => setOpen(false)}
                aria-label="Close help video"
                className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            <video
              src={GUIDE_VIDEO_SRC}
              controls
              autoPlay
              playsInline
              className="block aspect-video w-full bg-black"
            >
              Your browser can’t play this video. <a href={GUIDE_VIDEO_SRC}>Download it instead.</a>
            </video>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}

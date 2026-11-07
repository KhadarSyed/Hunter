import type { ReactNode } from "react";

/** A progress / share ring: `value` 0-100 fills the arc; the centre shows `children`, else the rounded %.
 * Used everywhere a percentage is drawn (projects, usage shares, run progress, page progress). */
export function Donut({ value, size = 36, color = "#5B2C9D", track = "#EEF0F4", spin = false, title, children, className = "" }: {
  value: number; size?: number; color?: string; track?: string; spin?: boolean; title?: string; children?: ReactNode;
  className?: string;
}) {
  const v = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  const stroke = Math.max(3, Math.round(size / 9));
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const centre = children ?? (size >= 28 ? `${Math.round(v)}${size >= 44 ? "%" : ""}` : null);
  return (
    <span className={`relative inline-flex shrink-0 items-center justify-center ${className}`} style={{ width: size, height: size }}
          role="img" aria-label={title ?? `${Math.round(v)}%`} title={title}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className={`-rotate-90 ${spin ? "animate-spin [animation-duration:1.4s]" : ""}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={track} strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
                strokeDasharray={circ} strokeDashoffset={circ * (1 - v / 100)}
                style={{ transition: "stroke-dashoffset 600ms ease-out" }} />
      </svg>
      {centre !== null && (
        <span className="absolute inset-0 flex items-center justify-center font-bold tabular-nums leading-none text-slate-800"
              style={{ fontSize: Math.max(8, Math.round(size * 0.28)) }}>
          {centre}
        </span>
      )}
    </span>
  );
}

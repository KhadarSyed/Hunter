import { useEffect, useRef } from "react";
import type { DeliverableLogLine } from "../../services/intel-api";

const time = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** The run's progress lines as they stream in, newest at the bottom and kept in view while the run is live. */
export function RunLog({ lines, isLive }: { lines: DeliverableLogLine[]; isLive: boolean }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (isLive) end.current?.scrollIntoView({ block: "nearest" });
  }, [lines.length, isLive]);
  if (!lines.length) return null;
  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2 text-xs font-semibold text-slate-600">
        {isLive && <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />}
        {isLive ? "Live log" : "Run log"}
        <span className="font-normal text-slate-400">{lines.length} steps</span>
      </div>
      <div className="max-h-64 overflow-y-auto px-4 py-2 font-mono text-[11px] leading-5">
        {lines.map((l, i) => (
          <div key={`${l.ts}-${i}`} className={l.message.startsWith("Failed") ? "text-red-600" : "text-slate-600"}>
            <span className="mr-2 text-slate-400">{time(l.ts)}</span>{l.message}
          </div>
        ))}
        <div ref={end} />
      </div>
    </div>
  );
}

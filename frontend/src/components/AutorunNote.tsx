import type { Autorun } from "../services/intel-api";

/** Why autorun stopped at this stage (e.g. research flagged a wrong brand): the analyst reviews and approves here. */
export function AutorunNote({ autorun, steps }: { autorun: Autorun | null; steps: Autorun["step"][] }) {
  if (autorun?.status !== "blocked" || !steps.includes(autorun.step)) return null;
  return (
    <div className="shrink-0 mx-8 mt-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800">
      Automatic approval stopped here: {autorun.error || "a check did not pass"}. Review this stage and approve it to continue.
    </div>
  );
}

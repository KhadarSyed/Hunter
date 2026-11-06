import type { RowRelations } from "../services/intel-api";
import type { RelationKind } from "./RelatedArticlesDrawer";

/** The Syndicated / Similar count button: opens the related-articles drawer. */
type CountProps = {
  relations: Record<string, RowRelations> | null | undefined;
  rowKey: string;
  kind: RelationKind;
  onOpen: () => void;
};

export function RelationCount({ relations, rowKey, kind, onOpen }: CountProps) {
  if (relations === undefined) return <span className="text-slate-300" title="Finding related articles…">…</span>;
  if (relations === null) return <span className="text-slate-300" title="Could not load">—</span>;
  const count = relations[rowKey]?.[kind]?.length ?? 0;
  if (count === 0) return <span className="text-slate-300">0</span>;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="px-1.5 py-0.5 rounded bg-violet-50 text-[#5B2C9D] font-semibold hover:bg-violet-100 hover:underline"
      aria-label={`${count} ${kind} article${count === 1 ? "" : "s"}`}
    >
      {count}
    </button>
  );
}

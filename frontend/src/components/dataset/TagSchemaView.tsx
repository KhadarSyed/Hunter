import type { TagSchemaField } from "../../types/dataset";

/** Read-only view of a question's tag schema: field, type and the values it may take. */
export function TagSchemaView({ fields }: { fields: TagSchemaField[] }) {
  if (fields.length === 0) return <p className="text-xs text-slate-400">No tag schema yet; it is built at the first tagging run.</p>;
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
      {fields.map((f) => (
        <div key={f.name} className="contents">
          <dt className="font-medium text-slate-700">{f.name} <span className="font-normal text-slate-400">· {f.type}</span></dt>
          <dd className="truncate text-slate-500" title={f.values.join(", ")}>{f.values.length ? f.values.join(", ") : "free text"}</dd>
        </div>
      ))}
    </dl>
  );
}

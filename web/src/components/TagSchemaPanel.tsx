import type { TagSchemas } from "../services/intel-api";

/** Each research question's dynamic tag schema and how every tag maps to the Review table. Points and weights are
 * the Review table's own: this panel only shows where a tag lands, or that no Review column records it. */
export function TagSchemaPanel({ schemas }: { schemas?: TagSchemas }) {
  const entries = Object.entries(schemas || {}).sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }));
  if (entries.length === 0) return null;
  const unmapped = entries.reduce((n, [, s]) => n + s.review_mapping.filter((m) => m.mapping_status !== "MAPPED").length, 0);
  return (
    <details className="mb-4 rounded-lg border border-indigo-100 bg-indigo-50/30">
      <summary className="cursor-pointer select-none px-4 py-2.5 text-xs font-semibold text-indigo-900">
        Question-driven tag schemas ({entries.length} questions)
        {unmapped > 0 && <span className="ml-2 font-medium text-amber-700">{unmapped} tag(s) UNMAPPED_REVIEW_CRITERION</span>}
      </summary>
      <div className="space-y-4 px-4 pb-4">
        {entries.map(([rq, { schema, review_mapping }]) => {
          const mapping = new Map(review_mapping.map((m) => [m.tag_name, m]));
          return (
            <div key={rq} className="rounded-lg border border-slate-200 bg-white">
              <div className="border-b border-slate-100 px-3 py-2">
                <div className="text-xs font-semibold text-slate-800">{rq} · {schema.question}</div>
                <div className="text-[11px] text-slate-500">Intent: {schema.question_intent}</div>
              </div>
              <table className="w-full text-[11px]">
                <thead className="text-left text-slate-500">
                  <tr>
                    <th className="px-3 py-1.5">Tag</th><th className="px-3 py-1.5">Type</th>
                    <th className="px-3 py-1.5">Allowed values</th><th className="px-3 py-1.5">Definition / extraction rule</th>
                    <th className="px-3 py-1.5">Review criterion</th><th className="px-3 py-1.5">Points / weight</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {schema.required_tags.map((t) => {
                    const m = mapping.get(t.tag_name);
                    return (
                      <tr key={t.tag_name} className="align-top">
                        <td className="px-3 py-1.5 font-mono text-slate-800">{t.tag_name}</td>
                        <td className="px-3 py-1.5 text-slate-600">{t.tag_type}</td>
                        <td className="px-3 py-1.5 text-slate-600">{t.allowed_values.join(" / ") || "extracted"}</td>
                        <td className="px-3 py-1.5 text-slate-600">{t.definition}<div className="text-slate-400">{t.extraction_rule}</div></td>
                        <td className="px-3 py-1.5">
                          {m?.mapping_status === "MAPPED"
                            ? <span className="rounded bg-emerald-50 px-1.5 py-0.5 font-medium text-emerald-700">{m.review_criterion}</span>
                            : <span className="rounded bg-amber-50 px-1.5 py-0.5 font-medium text-amber-700">UNMAPPED_REVIEW_CRITERION</span>}
                        </td>
                        <td className="px-3 py-1.5 text-slate-400">{m?.points ?? "READ_FROM_REVIEW_TABLE"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          );
        })}
      </div>
    </details>
  );
}

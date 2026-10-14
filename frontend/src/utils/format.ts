/** US-English display formatting. Everything is pinned to "en-US" so the UI
 * reads the same regardless of the viewer's browser locale (en-IN / en-GB
 * would otherwise show DD/MM/YYYY). Use these for anything shown to the user;
 * never for values sent to the API or used as keys. */

const LOCALE = "en-US";

export type DateInput = Date | string | number;

const ISO_DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_DATE_TIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/;

/** Accepts a Date, an ISO string ("2026-10-14" or a full ISO timestamp), or
 * epoch milliseconds. A bare YYYY-MM-DD is read as a local calendar date so
 * it never shifts a day across time zones. Non-ISO strings (free-text dates
 * from source data) are not guessed at — callers fall back to the raw text. */
function toDate(value: DateInput): Date | null {
  if (value instanceof Date) return isNaN(value.getTime()) ? null : value;
  if (typeof value === "string") {
    const s = value.trim();
    const m = ISO_DATE_ONLY.exec(s);
    let d: Date;
    if (m) d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    else if (ISO_DATE_TIME.test(s)) d = new Date(s.replace(" ", "T"));
    else return null;
    return isNaN(d.getTime()) ? null : d;
  }
  const d = new Date(value);
  return isNaN(d.getTime()) ? null : d;
}

/** Converts a Unix timestamp in seconds to a Date input. */
export const fromUnix = (seconds: number): Date => new Date(seconds * 1000);

/** "Oct 14, 2026". Falls back to the raw input when it is not a valid date. */
export function formatDate(value: DateInput | null | undefined, opts?: Intl.DateTimeFormatOptions): string {
  if (value === null || value === undefined || value === "") return "";
  const d = toDate(value);
  if (!d) return String(value);
  return d.toLocaleDateString(LOCALE, opts ?? { year: "numeric", month: "short", day: "numeric" });
}

/** "Oct 14, 2026, 3:05 PM". */
export function formatDateTime(value: DateInput | null | undefined, opts?: Intl.DateTimeFormatOptions): string {
  if (value === null || value === undefined || value === "") return "";
  const d = toDate(value);
  if (!d) return String(value);
  return d.toLocaleString(
    LOCALE,
    opts ?? { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" },
  );
}

/** "3:05 PM" (pass `{ seconds: true }` for "3:05:09 PM"). */
export function formatTime(value: DateInput, { seconds = false }: { seconds?: boolean } = {}): string {
  const d = toDate(value);
  if (!d) return String(value);
  return d.toLocaleTimeString(LOCALE, {
    hour: "numeric",
    minute: "2-digit",
    ...(seconds ? { second: "2-digit" } : {}),
  });
}

/** British-spelled API enum values (statuses, insight types, module types)
 * rewritten for display only. The underlying values stay untouched — use
 * this on the text a badge or option shows, never on the value compared. */
const US_SPELLINGS: [RegExp, string][] = [
  [/cancelled/gi, "canceled"],
  [/behaviour/gi, "behavior"],
  [/visualis/gi, "visualiz"],
  [/analys(e|ed|ing)\b/gi, "analyz$1"],
  [/colour/gi, "color"],
];

export function usSpelling(text: string): string {
  return US_SPELLINGS.reduce(
    (out, [re, us]) =>
      out.replace(re, (match, ...groups) => {
        const replaced = typeof groups[0] === "string" ? us.replace("$1", groups[0]) : us;
        return match[0] === match[0].toUpperCase() ? replaced[0].toUpperCase() + replaced.slice(1) : replaced;
      }),
    text,
  );
}

/** "1,234,567" (en-US grouping). Returns "" for null/undefined. */
export function formatNumber(value: number | null | undefined, opts?: Intl.NumberFormatOptions): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  return value.toLocaleString(LOCALE, opts);
}

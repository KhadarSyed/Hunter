/** The password policy, mirrored from the server (domains/auth/service.password_problems): the server is the judge,
 * this only shows the user what is still missing while they type. */
const RULES: { label: string; ok: (pw: string, email: string) => boolean; needsEmail?: boolean }[] = [
  { label: "At least 12 characters", ok: (pw) => pw.length >= 12 },
  { label: "An upper-case letter", ok: (pw) => /[A-Z]/.test(pw) },
  { label: "A lower-case letter", ok: (pw) => /[a-z]/.test(pw) },
  { label: "A digit", ok: (pw) => /\d/.test(pw) },
  { label: "A symbol (e.g. ! @ # $ %)", ok: (pw) => /[^A-Za-z0-9]/.test(pw) },
  {
    label: "No part of your email address",
    needsEmail: true,
    ok: (pw, email) => {
      const name = email.split("@")[0].toLowerCase();
      return name.length < 3 || !pw.toLowerCase().includes(name);
    },
  },
];

export function passwordMeetsPolicy(pw: string, email = ""): boolean {
  return RULES.every((r) => r.ok(pw, email));
}

export function PasswordRules({ password, email = "" }: { password: string; email?: string }) {
  return (
    <ul className="mb-5 space-y-1 text-xs" aria-label="Password requirements">
      {RULES.filter((r) => !r.needsEmail || email).map((r) => {
        const met = r.ok(password, email);
        return (
          <li key={r.label} className={`flex items-center gap-2 ${met ? "text-emerald-700" : "text-slate-500"}`}>
            <span aria-hidden className={`inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold ${
              met ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-400"}`}>{met ? "✓" : "•"}</span>
            {r.label}<span className="sr-only">{met ? " (met)" : " (not met yet)"}</span>
          </li>
        );
      })}
    </ul>
  );
}

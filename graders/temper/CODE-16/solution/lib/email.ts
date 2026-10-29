// Lenient in, strict out: forgive what people type (spaces, capitals), save one canonical form.
const LOCAL = /^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$/;
const LABEL = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/;

/** The canonical (trimmed, lowercased) address, or null when it isn't a valid email. */
export function normalizeEmail(input: string): string | null {
  const email = input.trim().toLowerCase();
  const at = email.lastIndexOf("@");
  if (at < 1 || email.indexOf("@") !== at || email.length > 254) return null;
  const local = email.slice(0, at);
  const labels = email.slice(at + 1).split(".");
  if (local.length > 64 || !LOCAL.test(local) || labels.length < 2) return null;
  if (!labels.every((l) => l.length <= 63 && LABEL.test(l))) return null;
  return /^[a-z]{2,}$/.test(labels[labels.length - 1]) ? email : null;
}

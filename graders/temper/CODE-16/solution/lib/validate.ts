import { normalizeEmail } from "./email";
import type { Lead } from "./leads";

export type LeadErrors = Partial<Record<keyof Lead, string>>;

/** The lead as it should be saved, or the errors to show for each field. */
export function validateLead(input: Partial<Record<keyof Lead, unknown>>):
  { lead: Lead; errors?: undefined } | { lead?: undefined; errors: LeadErrors } {
  const text = (v: unknown) => (typeof v === "string" ? v.trim() : "");
  const name = text(input.name), rawEmail = typeof input.email === "string" ? input.email : "";
  const company = text(input.company), message = text(input.message);
  const errors: LeadErrors = {};
  if (!name) errors.name = "Enter your name.";
  const email = normalizeEmail(rawEmail);
  if (!rawEmail.trim()) errors.email = "Enter your email address.";
  else if (!email) errors.email = "Enter a valid email address, like name@example.com.";
  if (!message) errors.message = "Tell us what you need.";
  return Object.keys(errors).length ? { errors } : { lead: { name, email: email!, company, message } };
}

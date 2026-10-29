"use client";

import { useRef, useState, type FormEvent } from "react";
import type { Lead } from "@/lib/leads";
import { validateLead, type LeadErrors } from "@/lib/validate";

const FIELDS = ["name", "email", "company", "message"] as const;

export default function LeadForm() {
  const [values, setValues] = useState<Lead>({ name: "", email: "", company: "", message: "" });
  const [errors, setErrors] = useState<LeadErrors>({});
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "failed">("idle");
  const refs = useRef<Partial<Record<keyof Lead, HTMLInputElement | HTMLTextAreaElement | null>>>({});

  const set = (field: keyof Lead) => (e: { target: { value: string } }) =>
    setValues((v) => ({ ...v, [field]: e.target.value }));

  function showErrors(next: LeadErrors) {
    setErrors(next);
    const first = FIELDS.find((f) => next[f]);
    if (first) refs.current[first]?.focus();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = validateLead(values);
    if (result.errors) return showErrors(result.errors);
    setErrors({});
    setStatus("sending");
    try {
      const res = await fetch("/api/leads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(result.lead),
      });
      if (res.ok) return setStatus("sent");
      const body = await res.json().catch(() => ({}));
      setStatus("failed");
      if (body.errors) showErrors(body.errors);
    } catch {
      setStatus("failed");
    }
  }

  if (status === "sent") {
    return <p id="lead-success" role="status">Thanks! We'll call you back within one business day.</p>;
  }

  const field = (name: keyof Lead) => ({
    id: `lead-${name}`,
    name,
    value: values[name],
    onChange: set(name),
    ref: (el: HTMLInputElement | HTMLTextAreaElement | null) => { refs.current[name] = el; },
    "aria-invalid": errors[name] ? true : undefined,
    "aria-describedby": errors[name] ? `lead-${name}-error` : undefined,
  });
  const error = (name: keyof Lead) =>
    errors[name] ? <p id={`lead-${name}-error`} role="alert">{errors[name]}</p> : null;

  return (
    <form id="lead-form" noValidate onSubmit={handleSubmit}>
      {status === "failed" && !Object.keys(errors).length && (
        <p id="lead-form-error" role="alert">Something went wrong. Please try again.</p>
      )}
      <div>
        <label htmlFor="lead-name">Full name</label>
        <input {...field("name")} autoComplete="name" />
        {error("name")}
      </div>
      <div>
        <label htmlFor="lead-email">Email</label>
        <input {...field("email")} type="email" autoComplete="email" />
        {error("email")}
      </div>
      <div>
        <label htmlFor="lead-company">Company (optional)</label>
        <input {...field("company")} autoComplete="organization" />
      </div>
      <div>
        <label htmlFor="lead-message">What can we help with?</label>
        <textarea {...field("message")} />
        {error("message")}
      </div>
      <button id="lead-submit" type="submit" disabled={status === "sending"}>Request a quote</button>
    </form>
  );
}

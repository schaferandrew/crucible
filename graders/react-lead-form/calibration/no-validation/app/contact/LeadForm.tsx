"use client";

import { useState, type FormEvent } from "react";

// Calibration: the form works and submits, but checks nothing and the API is left as seeded
export default function LeadForm() {
  const [values, setValues] = useState({ name: "", email: "", company: "", message: "" });
  const [sent, setSent] = useState(false);
  const set = (field: keyof typeof values) => (e: { target: { value: string } }) =>
    setValues((v) => ({ ...v, [field]: e.target.value }));

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const res = await fetch("/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });
    if (res.ok) setSent(true);
  }

  if (sent) return <p id="lead-success">Thanks!</p>;
  return (
    <form id="lead-form" onSubmit={handleSubmit}>
      <label htmlFor="lead-name">Full name</label>
      <input id="lead-name" name="name" value={values.name} onChange={set("name")} />
      <label htmlFor="lead-email">Email</label>
      <input id="lead-email" name="email" value={values.email} onChange={set("email")} />
      <label htmlFor="lead-company">Company (optional)</label>
      <input id="lead-company" name="company" value={values.company} onChange={set("company")} />
      <label htmlFor="lead-message">What can we help with?</label>
      <textarea id="lead-message" name="message" value={values.message} onChange={set("message")} />
      <button id="lead-submit" type="submit">Request a quote</button>
    </form>
  );
}

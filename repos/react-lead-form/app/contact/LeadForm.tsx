import type { FormEvent } from "react";

const values = { name: "", email: "", company: "", message: "" };

export default function LeadForm() {
  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await fetch("/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });
  }

  return (
    <form id="lead-form" onSubmit={handleSubmit}>
      <div>
        <label htmlFor="lead-name">Full name</label>
        <input id="lead-name" name="name" value={values.name}
          onChange={(e) => { values.name = e.target.value; }} />
      </div>
      <div>
        <label htmlFor="lead-email">Email</label>
        <input id="lead-email" name="email" value={values.email}
          onChange={(e) => { values.email = e.target.value; }} />
      </div>
      <div>
        <label htmlFor="lead-company">Company (optional)</label>
        <input id="lead-company" name="company" value={values.company}
          onChange={(e) => { values.company = e.target.value; }} />
      </div>
      <div>
        <label htmlFor="lead-message">What can we help with?</label>
        <textarea id="lead-message" name="message" value={values.message}
          onChange={(e) => { values.message = e.target.value; }} />
      </div>
      <button id="lead-submit" type="submit">Request a quote</button>
    </form>
  );
}

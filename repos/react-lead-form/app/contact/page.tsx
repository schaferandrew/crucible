import LeadForm from "./LeadForm";

export const metadata = { title: "Get a free quote | Brightline Windows" };

export default function ContactPage() {
  return (
    <main>
      <h1>Get a free quote</h1>
      <p>Tell us about your project and we'll call you back within one business day.</p>
      <LeadForm />
    </main>
  );
}

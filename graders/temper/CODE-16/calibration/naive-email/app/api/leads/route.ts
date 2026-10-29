import { saveLead } from "@/lib/leads";
import { validateLead } from "@/lib/validate";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ errors: { form: "Expected a JSON body." } }, { status: 400 });
  }
  const result = validateLead(body && typeof body === "object" ? body : {});
  if (result.errors) return Response.json({ errors: result.errors }, { status: 422 });
  return Response.json({ lead: await saveLead(result.lead) }, { status: 201 });
}

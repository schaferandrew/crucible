import { saveLead } from "@/lib/leads";

export async function POST(request: Request) {
  const body = await request.json();
  const lead = await saveLead(body);
  return Response.json({ lead }, { status: 201 });
}

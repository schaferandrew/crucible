import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

export interface Lead {
  name: string;
  email: string;
  company: string;
  message: string;
}

export interface SavedLead extends Lead {
  id: number;
  receivedAt: string;
}

/** Where leads are stored: LEADS_FILE, or data/leads.json in the project. */
export function leadsFile(): string {
  return process.env.LEADS_FILE || path.join(process.cwd(), "data", "leads.json");
}

export async function readLeads(): Promise<SavedLead[]> {
  try {
    return JSON.parse(await readFile(leadsFile(), "utf8"));
  } catch {
    return [];
  }
}

/** Append a lead to the store and return it as saved. */
export async function saveLead(lead: Lead): Promise<SavedLead> {
  const leads = await readLeads();
  const saved: SavedLead = { ...lead, id: leads.length + 1, receivedAt: new Date().toISOString() };
  await mkdir(path.dirname(leadsFile()), { recursive: true });
  await writeFile(leadsFile(), JSON.stringify([...leads, saved], null, 2) + "\n");
  return saved;
}

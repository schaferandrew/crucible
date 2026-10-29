// Hidden acceptance tests for CODE-16 (React lead form). Never copied into the model's workspace:
// the grader copies them into test/hidden/ of a grading copy (seeded repo + the model's source)
// and runs them with the seeded vitest config.
//
// The groups climb in difficulty, and each is scored on its own, so a form that submits but
// validates badly still earns the levels it reached:
//   level 2 typing       -> level 3 submit -> level 4 required fields
//   level 5 bad email    -> level 6 email rules (accept what people type, save it strictly)
// Level 1 (the page builds and serves) is in build.grader.test.ts.
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LeadForm from "../../app/contact/LeadForm";
import { POST } from "../../app/api/leads/route";

// Fresh values every run, so nothing can be hard-coded to the grader's data
const nonce = Math.random().toString(36).slice(2, 8);
const lead = {
  name: `Jordan Reyes ${nonce}`,
  email: `jordan.${nonce}@example.com`,
  company: `Reyes Builders ${nonce}`,
  message: `Six double-hung windows, ref ${nonce}`,
};

let dir: string;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(async () => {
  dir = await mkdtemp(path.join(tmpdir(), "crucible-leads-"));
  process.env.LEADS_FILE = path.join(dir, "leads.json");
  fetchMock = vi.fn(async () => Response.json({ lead: { id: 1 } }, { status: 201 }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(async () => {
  cleanup();
  vi.unstubAllGlobals();
  delete process.env.LEADS_FILE;
  await rm(dir, { recursive: true, force: true });
});

const el = <T extends HTMLElement = HTMLInputElement>(id: string) => {
  const found = document.getElementById(id);
  if (!found) throw new Error(`#${id} isn't on the page`);
  return found as T;
};
const field = (name: string) => el<HTMLInputElement | HTMLTextAreaElement>(`lead-${name}`);

/** Render the form and type each given field (missing ones stay empty). */
async function fill(values: Partial<typeof lead>) {
  const user = userEvent.setup();
  render(<LeadForm />);
  for (const [name, value] of Object.entries(values)) {
    if (value) await user.type(field(name), value);
  }
  return user;
}

async function submit(values: Partial<typeof lead>) {
  const user = await fill(values);
  await user.click(el("lead-submit"));
  return user;
}

/** Route the form's fetch to the real POST /api/leads handler. */
function useRealApi() {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    expect(String(url)).toMatch(/\/api\/leads$/);
    return POST(new Request("http://localhost/api/leads", init));
  });
}

const post = (body: unknown) => POST(new Request("http://localhost/api/leads", {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
}));

async function saved(): Promise<Array<Record<string, unknown>>> {
  try {
    return JSON.parse(await readFile(process.env.LEADS_FILE!, "utf8"));
  } catch {
    return [];
  }
}

function sentBody() {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(String(url)).toMatch(/\/api\/leads$/);
  expect(init?.method).toBe("POST");
  return JSON.parse(String(init?.body));
}

const noErrors = () => ["name", "email", "message"].forEach((f) =>
  expect(document.getElementById(`lead-${f}-error`)).toBeNull());

describe("level 2: typing", () => {
  it("every field shows what is typed into it", async () => {
    await fill(lead);
    for (const [name, value] of Object.entries(lead)) expect(field(name).value).toBe(value);
  });

  it("tab moves through the fields in order, and typing lands where focus is", async () => {
    const user = userEvent.setup();
    render(<LeadForm />);
    field("name").focus();
    for (const next of ["email", "company", "message"]) {
      await user.tab();
      expect(document.activeElement?.id).toBe(`lead-${next}`);
      await user.keyboard(nonce);
      expect(field(next).value).toBe(nonce);
    }
    await user.tab();
    expect(document.activeElement?.id).toBe("lead-submit");
  });
});

describe("level 3: submit", () => {
  it("posts the lead as JSON to /api/leads and shows the success message", async () => {
    await submit(lead);
    await waitFor(() => expect(document.getElementById("lead-success")).not.toBeNull());
    const body = sentBody();
    for (const [name, value] of Object.entries(lead)) expect(String(body[name]).trim()).toBe(value);
  });

  it("pressing Enter in a field submits the form", async () => {
    const user = await fill(lead);
    field("name").focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(document.getElementById("lead-success")).not.toBeNull());
    expect(sentBody().name.trim()).toBe(lead.name);
  });

  it("doesn't show success when the server refuses the lead", async () => {
    fetchMock.mockImplementation(async () => Response.json({ errors: { form: "down" } }, { status: 500 }));
    await submit(lead);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await new Promise((r) => setTimeout(r, 50));
    expect(document.getElementById("lead-success")).toBeNull();
    expect(field("name").value).toBe(lead.name);
  });

  it("the API saves a valid lead with every field trimmed", async () => {
    const res = await post({ name: `  ${lead.name} `, email: lead.email, company: ` ${lead.company}  `, message: `\n${lead.message}  ` });
    expect(res.status).toBe(201);
    const [row] = await saved();
    expect(row).toMatchObject(lead);
  });

  it("the company field is optional, and saved as an empty string when left out", async () => {
    const { company, ...rest } = lead;
    const res = await post(rest);
    expect(res.status).toBe(201);
    expect((await saved())[0]).toMatchObject({ ...rest, company: "" });
  });
});

describe("level 4: required fields", () => {
  for (const missing of ["name", "email", "message"] as const) {
    it(`a missing ${missing} shows its error, keeps what was typed and sends nothing`, async () => {
      const values = { ...lead, [missing]: "" };
      await submit(values);
      const error = await waitFor(() => el(`lead-${missing}-error`));
      expect(error.textContent?.trim()).not.toBe("");
      expect(field(missing).getAttribute("aria-invalid")).toBe("true");
      expect(field(missing).getAttribute("aria-describedby") ?? "").toContain(`lead-${missing}-error`);
      expect(fetchMock).not.toHaveBeenCalled();
      for (const [name, value] of Object.entries(values)) expect(field(name).value).toBe(value);
      expect(document.getElementById("lead-success")).toBeNull();
    });
  }

  it("whitespace alone doesn't count as filled in", async () => {
    await submit({ ...lead, name: "   " });
    await waitFor(() => el("lead-name-error"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("focus jumps to the first field with an error", async () => {
    await submit({ name: lead.name, company: lead.company });
    await waitFor(() => el("lead-email-error"));
    expect(document.activeElement?.id).toBe("lead-email");
  });

  it("fixing the field and resubmitting clears the error and sends", async () => {
    const user = await submit({ ...lead, message: "" });
    await waitFor(() => el("lead-message-error"));
    await user.type(field("message"), lead.message);
    await user.click(el("lead-submit"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(document.getElementById("lead-message-error")).toBeNull();
  });

  it("the API refuses a lead missing a required field with 422 and saves nothing", async () => {
    for (const missing of ["name", "email", "message"]) {
      const res = await post({ ...lead, [missing]: " " });
      expect(res.status).toBe(422);
      expect((await res.json()).errors?.[missing]).toBeTruthy();
    }
    expect(await saved()).toEqual([]);
  });
});

describe("level 5: badly formed email", () => {
  for (const email of ["jordan", "jordan@", "@example.com", "jordan example.com"]) {
    it(`the form refuses "${email}" with an email error`, async () => {
      await submit({ ...lead, email });
      await waitFor(() => el("lead-email-error"));
      expect(field("email").getAttribute("aria-invalid")).toBe("true");
      expect(fetchMock).not.toHaveBeenCalled();
      expect(field("email").value).toBe(email);
    });
  }

  it("the API refuses a badly formed email with 422 and saves nothing", async () => {
    const res = await post({ ...lead, email: "jordan@" });
    expect(res.status).toBe(422);
    expect((await res.json()).errors?.email).toBeTruthy();
    expect(await saved()).toEqual([]);
  });
});

// Lenient in: what real people type into an email box
const ACCEPT: Array<[typed: string, saved: string]> = [
  [`  jordan.${nonce}@example.com  `, `jordan.${nonce}@example.com`],
  [`Jordan.Reyes@Example.COM`, `jordan.reyes@example.com`],
  [`jordan+quotes@example.com`, `jordan+quotes@example.com`],
  [`j.o.r.d.a.n@mail.example.co.uk`, `j.o.r.d.a.n@mail.example.co.uk`],
  [`o'neil_${nonce}@reyes-builders.com`, `o'neil_${nonce}@reyes-builders.com`],
  [`jordan@studio.photography`, `jordan@studio.photography`],
  [`2024@example.io`, `2024@example.io`],
];
// Strict out: never saved, whatever the form let through
const REJECT = [
  "jordan@example",            // no top-level domain
  "jordan@@example.com",       // two @
  "jordan@exa mple.com",       // space inside
  "jordan..reyes@example.com", // consecutive dots
  ".jordan@example.com",       // leading dot
  "jordan.@example.com",       // trailing dot before @
  "jordan@example..com",       // empty domain label
  "jordan@-example.com",       // label starting with a hyphen
  "jordan@example.c",          // one-letter top-level domain
  "jordan@example.com.",       // trailing dot
  "jordan@exam_ple.com",       // underscore in the domain
  "jordan@example.123",        // numeric top-level domain
];

describe("level 6: email accepted as typed", () => {
  for (const [typed] of ACCEPT) {
    it(`the form accepts "${typed.replaceAll(nonce, "<random>")}"`, async () => {
      await submit({ ...lead, email: typed });
      await waitFor(() => expect(document.getElementById("lead-success")).not.toBeNull());
      expect(fetchMock).toHaveBeenCalledTimes(1);
      noErrors();
    });
  }
});

describe("level 6: email saved strictly", () => {
  it("the API saves each accepted address trimmed and lowercased", async () => {
    for (const [typed, canonical] of ACCEPT) {
      const res = await post({ ...lead, email: typed });
      expect(res.status, typed).toBe(201);
      expect((await res.json()).lead?.email, typed).toBe(canonical);
    }
    expect((await saved()).map((row) => row.email)).toEqual(ACCEPT.map(([, canonical]) => canonical));
  });

  for (const email of REJECT) {
    it(`the API refuses "${email}" and saves nothing`, async () => {
      const res = await post({ ...lead, email });
      expect(res.status).toBe(422);
      expect((await res.json()).errors?.email).toBeTruthy();
      expect(await saved()).toEqual([]);
    });
  }

  it("a lead typed into the form is saved in canonical form", async () => {
    useRealApi();
    await submit({ ...lead, name: `  ${lead.name}`, email: `  Jordan.${nonce}+Quote@Example.COM ` });
    await waitFor(() => expect(document.getElementById("lead-success")).not.toBeNull());
    const rows = await saved();
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ ...lead, email: `jordan.${nonce}+quote@example.com` });
  });

  it("the API refuses fields that aren't strings", async () => {
    const res = await post({ ...lead, email: ["jordan@example.com"] });
    expect(res.status).toBe(422);
    expect(await saved()).toEqual([]);
  });
});

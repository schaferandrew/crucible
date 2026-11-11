// The tool collection and its JSON file. Listeners hear about every change the service makes.

import fs from "node:fs";
import type { Tool, ToolEvent, ToolListener } from "./types.js";
import { normalizeTool } from "./validate.js";

interface StoredFile {
  nextId?: number;
  tools?: unknown[];
}

export class ToolStore {
  file: string;
  tools: Tool[];
  nextId: number;
  listeners: ToolListener[];

  constructor(file: string) {
    this.file = file;
    this.tools = [];
    this.nextId = 1;
    this.listeners = [];
  }

  load(): this {
    let raw: StoredFile;
    try {
      raw = JSON.parse(fs.readFileSync(this.file, "utf8")) as StoredFile;
    } catch (err) {
      const failure = err as NodeJS.ErrnoException;
      if (failure.code === "ENOENT") {
        this.tools = [];
        this.nextId = 1;
        return this;
      }
      throw new Error(`cannot read ${this.file}: ${failure.message}`);
    }
    this.tools = (raw.tools || []).map(normalizeTool);
    const highest = this.tools.reduce((max, tool) => Math.max(max, tool.id), 0);
    this.nextId = raw.nextId || highest + 1;
    return this;
  }

  save(): void {
    const body = JSON.stringify({ nextId: this.nextId, tools: this.tools }, null, 2);
    fs.writeFileSync(this.file, `${body}\n`);
  }

  get(id: number): Tool | undefined {
    return this.tools.find((tool) => tool.id === id);
  }

  insert(fields: Record<string, unknown>): Tool {
    const tool = normalizeTool({ ...fields, id: this.nextId, status: "available" });
    this.nextId += 1;
    this.tools.push(tool);
    return tool;
  }

  // Returns a function that stops listening.
  on(listener: ToolListener): () => void {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== listener);
    };
  }

  emit(event: ToolEvent): void {
    for (const listener of this.listeners) listener(event);
  }
}

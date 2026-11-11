// The tool collection and its JSON file. Listeners hear about every change the service makes.

import fs from "node:fs";
import { normalizeTool } from "./validate.js";

export class ToolStore {
  constructor(file) {
    this.file = file;
    this.tools = [];
    this.nextId = 1;
    this.listeners = [];
  }

  load() {
    let raw;
    try {
      raw = JSON.parse(fs.readFileSync(this.file, "utf8"));
    } catch (err) {
      if (err.code === "ENOENT") {
        this.tools = [];
        this.nextId = 1;
        return this;
      }
      throw new Error(`cannot read ${this.file}: ${err.message}`);
    }
    this.tools = (raw.tools || []).map(normalizeTool);
    const highest = this.tools.reduce((max, tool) => Math.max(max, tool.id), 0);
    this.nextId = raw.nextId || highest + 1;
    return this;
  }

  save() {
    const body = JSON.stringify({ nextId: this.nextId, tools: this.tools }, null, 2);
    fs.writeFileSync(this.file, `${body}\n`);
  }

  get(id) {
    return this.tools.find((tool) => tool.id === id);
  }

  insert(fields) {
    const tool = normalizeTool({ ...fields, id: this.nextId, status: "available" });
    this.nextId += 1;
    this.tools.push(tool);
    return tool;
  }

  // Returns a function that stops listening.
  on(listener) {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== listener);
    };
  }

  emit(event) {
    for (const listener of this.listeners) listener(event);
  }
}

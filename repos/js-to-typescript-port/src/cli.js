// Argument parsing and the commands. `main` never touches process.argv or process.exit, so tests can call it.

import { ToolStore } from "./store.js";
import { addTool, auditLines, findTools, loanTool, overdueTools, retireTool, returnTool } from "./tools.js";
import { formatSummary, formatTable, summarize } from "./report.js";

export function parseArgs(argv) {
  const positional = [];
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg.startsWith("--")) {
      const name = arg.slice(2);
      const next = argv[i + 1];
      if (next !== undefined && !next.startsWith("--")) {
        flags[name] = next;
        i++;
      } else {
        flags[name] = true;
      }
    } else {
      positional.push(arg);
    }
  }
  return { command: positional[0], args: positional.slice(1), flags };
}

class UsageError extends Error {}

function wantId(text) {
  const id = Number(text);
  if (!text || !Number.isInteger(id) || id < 1) throw new UsageError(`"${text}" is not a tool id`);
  return id;
}

function wantText(value, what) {
  if (typeof value !== "string" || !value.trim()) throw new UsageError(`${what} is required`);
  return value;
}

function runCommand(store, command, args, flags, today, print) {
  switch (command) {
    case "list": {
      const tools = findTools(store, { text: flags.search, status: flags.status, tag: flags.tag });
      print(formatTable(tools));
      return;
    }
    case "add": {
      const name = wantText(args[0], "a tool name");
      const category = wantText(flags.category, "--category");
      const cost = flags.cost === undefined ? undefined : Number(flags.cost);
      if (cost !== undefined && (Number.isNaN(cost) || cost < 0)) throw new UsageError(`bad cost "${flags.cost}"`);
      const tags = typeof flags.tags === "string" ? flags.tags.split(",").map((t) => t.trim()).filter(Boolean) : [];
      const tool = addTool(store, { name, category, tags, replacementCost: cost });
      print(`added #${tool.id} ${tool.name}`);
      return;
    }
    case "loan": {
      const days = flags.days === undefined ? 7 : Number(flags.days);
      const tool = loanTool(store, wantId(args[0]), wantText(args[1], "a borrower"), days, today);
      print(`#${tool.id} ${tool.name} loaned to ${tool.borrower} until ${tool.dueDate}`);
      return;
    }
    case "return": {
      const { tool, lateDays } = returnTool(store, wantId(args[0]), today);
      print(lateDays > 0 ? `#${tool.id} ${tool.name} returned ${lateDays} days late` : `#${tool.id} ${tool.name} returned`);
      return;
    }
    case "retire": {
      const tool = retireTool(store, wantId(args[0]), wantText(flags.reason, "--reason"));
      print(`#${tool.id} ${tool.name} retired: ${tool.retiredReason}`);
      return;
    }
    case "overdue": {
      print(formatTable(overdueTools(store, today)));
      return;
    }
    case "report": {
      print(formatSummary(summarize(store, today)));
      return;
    }
    default:
      throw new UsageError(command ? `unknown command "${command}"` : "no command given");
  }
}

export function main(argv, { file = "data/tools.json", today, out = console.log, audit } = {}) {
  const { command, args, flags } = parseArgs(argv);
  const day = today || new Date().toISOString().slice(0, 10);
  try {
    const store = new ToolStore(file).load();
    const lines = auditLines(store);
    runCommand(store, command, args, flags, day, out);
    if (lines.length > 0) {
      store.save();
      if (audit) lines.forEach((line) => audit(line));
    }
    return 0;
  } catch (err) {
    out(`error: ${err.message}`);
    return err instanceof UsageError ? 2 : 1;
  }
}

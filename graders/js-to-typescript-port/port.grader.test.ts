// @vitest-environment node
// Hidden tests for js-to-typescript-port. Three groups, every test weighs the same:
//   toolchain: a TypeScript port exists, tsconfig is strict, the project type-checks, no `any` escapes
//   types:     the exported shapes are typed the way the data really is (unions, nullables, no any)
//   behavior:  the port does exactly what the JavaScript did, recorded from the seeded code (GOLDEN)
// Behavior tests import the .ts files explicitly, so they fail on the seeded JavaScript.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterAll, describe, expect, it } from "vitest";

const root = path.resolve(__dirname, "../..");
const src = path.join(root, "src");
const tsc = path.join(root, "node_modules", ".bin", "tsc");
const DUMP = process.env.GOLDEN_DUMP;
const EXT = DUMP ? "js" : "ts";
const MODULES = ["dates", "validate", "store", "tools", "report", "cli"];
const DUMPED: Record<string, unknown> = {};

afterAll(() => {
  if (DUMP) fs.writeFileSync(DUMP, JSON.stringify(DUMPED, null, 2));
});

// ---------------------------------------------------------------- toolchain helpers

function tsFiles(dir: string): string[] {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return tsFiles(p);
    return /\.(ts|mts|cts)$/.test(e.name) && !e.name.endsWith(".d.ts") ? [p] : [];
  });
}

function runTsc(args: string[]) {
  const r = spawnSync(tsc, [...args, "--pretty", "false"], { cwd: root, encoding: "utf8", timeout: 120_000 });
  return { ok: r.status === 0, output: `${r.stdout}${r.stderr}`.trim() };
}

function requireSome() {
  if (tsFiles(src).length === 0) throw new Error("no TypeScript files in src");
}

function requirePort(modules = MODULES) {
  const missing = modules.filter((m) => !fs.existsSync(path.join(src, `${m}.ts`)));
  if (missing.length) throw new Error(`no TypeScript source for: ${missing.join(", ")}`);
}

const FORCED = {
  compilerOptions: {
    target: "ES2022", module: "ESNext", moduleResolution: "Bundler", strict: true, noEmit: true,
    skipLibCheck: true, types: ["node"],
  },
  include: ["src/**/*.ts", "__shape.ts"],
};

// One compile of a file of type assertions; each assertion is attributed to a test by its line.
const SHAPES: [string, string][] = [
  ["status", `type _status = Expect<Equal<Tool["status"], "available" | "loaned" | "retired">>;`],
  ["nullable", `type _borrower = Expect<Equal<Tool["borrower"], string | null>>;`],
  ["nullable", `type _due = Expect<Equal<Tool["dueDate"], string | null>>;`],
  ["nullable", `type _reason = Expect<Equal<Tool["retiredReason"], string | null>>;`],
  ["nullable", `type _cost = Expect<Equal<Tool["replacementCost"], number | null>>;`],
  ["get", `type _get = Expect<Equal<ReturnType<ToolStore["get"]>, Tool | undefined>>;`],
  ["event", `type _kinds = Expect<Equal<Ev["type"], "added" | "loaned" | "returned" | "retired">>;`],
  ["event", `type _loaned = Expect<Equal<Extract<Ev, { type: "loaned" }>["dueDate"], string>>;`],
  ["event", `type _returned = Expect<Equal<Extract<Ev, { type: "returned" }>["lateDays"], number>>;`],
  ["noany", `type _tool = Expect<Equal<IsAny<Tool>, false>>;`],
  ["noany", `type _ev = Expect<Equal<IsAny<Ev>, false>>;`],
  ["noany", `type _tools = Expect<Equal<IsAny<ToolStore["tools"]>, false>>;`],
  ["noany", `type _next = Expect<Equal<ToolStore["nextId"], number>>;`],
  ["noany", `type _main = Expect<Equal<ReturnType<typeof main>, number>>;`],
  ["noany", `type _parse = Expect<Equal<IsAny<ReturnType<typeof parseArgs>["flags"]>, false>>;`],
];
const SHAPE_HEAD = [
  `import { ToolStore } from "./src/store";`,
  `import { main, parseArgs } from "./src/cli";`,
  `type Tool = ToolStore["tools"][number];`,
  `type Ev = Parameters<Parameters<ToolStore["on"]>[0]>[0];`,
  `type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;`,
  `type Expect<T extends true> = T;`,
  `type IsAny<T> = 0 extends 1 & T ? true : false;`,
];
let shapeFailures: Map<string, string[]> | undefined;
function shapeResult(id: string): string[] {
  requirePort(["store", "cli"]);
  if (!shapeFailures) {
    shapeFailures = new Map();
    fs.writeFileSync(path.join(root, "__shape.ts"), [...SHAPE_HEAD, ...SHAPES.map(([, l]) => l)].join("\n") + "\n");
    fs.writeFileSync(path.join(root, "tsconfig.grader.json"), JSON.stringify(FORCED));
    const r = runTsc(["-p", "tsconfig.grader.json"]);
    for (const line of r.output.split("\n")) {
      const m = /^__shape\.ts\((\d+),/.exec(line);
      const hit = m && SHAPES[Number(m[1]) - SHAPE_HEAD.length - 1];
      if (hit) shapeFailures.set(hit[0], [...(shapeFailures.get(hit[0]) ?? []), line]);
    }
    fs.rmSync(path.join(root, "__shape.ts"), { force: true });
    fs.rmSync(path.join(root, "tsconfig.grader.json"), { force: true });
  }
  return shapeFailures.get(id) ?? [];
}

// ---------------------------------------------------------------- toolchain

describe("toolchain", () => {
  it("every module has a TypeScript source", () => {
    requirePort();
  });

  it("tsconfig.json turns strict mode on", () => {
    const ts = require(path.join(root, "node_modules", "typescript"));
    const file = path.join(root, "tsconfig.json");
    expect(fs.existsSync(file), "tsconfig.json is missing").toBe(true);
    const read = ts.readConfigFile(file, ts.sys.readFile);
    expect(read.error, "tsconfig.json does not parse").toBeUndefined();
    const parsed = ts.parseJsonConfigFileContent(read.config, ts.sys, root);
    const o = parsed.options;
    expect(o.strict).toBe(true);
    for (const flag of ["noImplicitAny", "strictNullChecks", "useUnknownInCatchVariables", "strictFunctionTypes"]) {
      expect(o[flag], `${flag} switched off`).not.toBe(false);
    }
    expect(o.checkJs).not.toBe(true);
  });

  it("the project type-checks with its own tsconfig", () => {
    requireSome();
    const r = runTsc(["-p", "tsconfig.json", "--noEmit"]);
    expect(r.output).toBe("");
    expect(r.ok).toBe(true);
  });

  it("the sources type-check under strict settings of our own", () => {
    requireSome();
    fs.writeFileSync(path.join(root, "tsconfig.grader.json"), JSON.stringify({ ...FORCED, include: ["src/**/*.ts"] }));
    try {
      const r = runTsc(["-p", "tsconfig.grader.json"]);
      expect(r.output).toBe("");
    } finally {
      fs.rmSync(path.join(root, "tsconfig.grader.json"), { force: true });
    }
  });

  it("no explicit any in the sources", () => {
    requireSome();
    const bad: string[] = [];
    for (const file of tsFiles(src)) {
      const code = fs.readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
      const noStrings = code.replace(/"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`/g, '""');
      if (/(:|\bas|<|,|\|)\s*any\b|\bany\s*(\[\]|>|\||,|\))|\bArray<any\b/.test(noStrings)) bad.push(path.relative(root, file));
    }
    expect(bad).toEqual([]);
  });

  it("no type-check suppression comments", () => {
    requireSome();
    const bad = tsFiles(src).filter((f) => /@ts-(ignore|nocheck|expect-error)/.test(fs.readFileSync(f, "utf8")));
    expect(bad.map((f) => path.relative(root, f))).toEqual([]);
  });
});

// ---------------------------------------------------------------- types

describe("types", () => {
  it("a tool's status is the union of its three values, not string", () => {
    expect(shapeResult("status")).toEqual([]);
  });
  it("borrower, due date, retired reason and cost are typed as nullable", () => {
    expect(shapeResult("nullable")).toEqual([]);
  });
  it("looking a tool up can give undefined", () => {
    expect(shapeResult("get")).toEqual([]);
  });
  it("change listeners receive a union of events that narrows on its type", () => {
    expect(shapeResult("event")).toEqual([]);
  });
  it("nothing the modules export is any", () => {
    expect(shapeResult("noany")).toEqual([]);
  });
});

// ---------------------------------------------------------------- behavior (recorded from the JavaScript)

const GOLDEN: Record<string, unknown> = /*GOLDEN*/{
 "list filters by status, tag and text": [
  {
   "code": 0,
   "lines": [
    "#1  Cordless drill  power    loaned     mina, due 2025-03-03\n#2  Orbital sander  power    available\n#3  Claw hammer     hand     available\n#4  Tile saw        power    loaned     oskar, due 2025-03-14\n#5  Socket set      hand     available\n#6  Garden fork     garden   retired    snapped handle\n#7  Stud finder     measure  loaned     priya, due 2025-03-01\n#8  Router table    power    available\n#9  Level           measure  loaned     zed, due 2025-03-01"
   ]
  },
  {
   "code": 0,
   "lines": [
    "#1  Cordless drill  power    loaned  mina, due 2025-03-03\n#4  Tile saw        power    loaned  oskar, due 2025-03-14\n#7  Stud finder     measure  loaned  priya, due 2025-03-01\n#9  Level           measure  loaned  zed, due 2025-03-01"
   ]
  },
  {
   "code": 0,
   "lines": [
    "#4  Tile saw      power  loaned     oskar, due 2025-03-14\n#8  Router table  power  available"
   ]
  },
  {
   "code": 0,
   "lines": [
    "#1  Cordless drill  power  loaned     mina, due 2025-03-03\n#2  Orbital sander  power  available\n#4  Tile saw        power  loaned     oskar, due 2025-03-14\n#8  Router table    power  available"
   ]
  },
  {
   "code": 0,
   "lines": [
    "#6  Garden fork  garden  retired  snapped handle"
   ]
  },
  {
   "code": 0,
   "lines": [
    "no tools"
   ]
  },
  {
   "code": 0,
   "lines": [
    "#8  Router table  power  available"
   ]
  }
 ],
 "loan saves the due date, trims the borrower and logs the change": {
  "a": {
   "code": 0,
   "lines": [
    "#2 Orbital sander loaned to ana until 2025-03-15"
   ],
   "audit": [
    "loaned #2 to ana until 2025-03-15"
   ]
  },
  "b": {
   "code": 0,
   "lines": [
    "#3 Claw hammer loaned to bo until 2025-03-17"
   ],
   "audit": [
    "loaned #3 to bo until 2025-03-17"
   ]
  },
  "c": {
   "code": 1,
   "lines": [
    "error: tool 2 is loaned, not available"
   ]
  },
  "d": {
   "code": 1,
   "lines": [
    "error: tool 6 is retired, not available"
   ]
  },
  "e": {
   "code": 1,
   "lines": [
    "error: no tool with id 99"
   ]
  },
  "file": {
   "nextId": 10,
   "tools": [
    {
     "id": 1,
     "name": "Cordless drill",
     "category": "power",
     "tags": [
      "drill",
      "cordless"
     ],
     "status": "loaned",
     "borrower": "mina",
     "dueDate": "2025-03-03",
     "retiredReason": null,
     "replacementCost": 89.5
    },
    {
     "id": 2,
     "name": "Orbital sander",
     "category": "power",
     "tags": [
      "sanding"
     ],
     "status": "loaned",
     "borrower": "ana",
     "dueDate": "2025-03-15",
     "retiredReason": null,
     "replacementCost": 64
    },
    {
     "id": 3,
     "name": "Claw hammer",
     "category": "hand",
     "tags": [
      "striking"
     ],
     "status": "loaned",
     "borrower": "bo",
     "dueDate": "2025-03-17",
     "retiredReason": null,
     "replacementCost": 18.25
    },
    {
     "id": 4,
     "name": "Tile saw",
     "category": "power",
     "tags": [
      "cutting",
      "wet"
     ],
     "status": "loaned",
     "borrower": "oskar",
     "dueDate": "2025-03-14",
     "retiredReason": null,
     "replacementCost": 240
    },
    {
     "id": 5,
     "name": "Socket set",
     "category": "hand",
     "tags": [],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": null
    },
    {
     "id": 6,
     "name": "Garden fork",
     "category": "garden",
     "tags": [
      "digging"
     ],
     "status": "retired",
     "borrower": null,
     "dueDate": null,
     "retiredReason": "snapped handle",
     "replacementCost": 22
    },
    {
     "id": 7,
     "name": "Stud finder",
     "category": "measure",
     "tags": [],
     "status": "loaned",
     "borrower": "priya",
     "dueDate": "2025-03-01",
     "retiredReason": null,
     "replacementCost": null
    },
    {
     "id": 8,
     "name": "Router table",
     "category": "power",
     "tags": [
      "woodwork",
      "cutting"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 310.99
    },
    {
     "id": 9,
     "name": "Level",
     "category": "measure",
     "tags": [],
     "status": "loaned",
     "borrower": "zed",
     "dueDate": "2025-03-01",
     "retiredReason": null,
     "replacementCost": 12.1
    }
   ]
  }
 },
 "return reports lateness and frees the tool": {
  "out": [
   {
    "code": 0,
    "lines": [
     "#1 Cordless drill returned 7 days late"
    ],
    "audit": [
     "returned #1 from mina (7d late)"
    ]
   },
   {
    "code": 0,
    "lines": [
     "#4 Tile saw returned"
    ],
    "audit": [
     "returned #4 from oskar"
    ]
   },
   {
    "code": 1,
    "lines": [
     "error: tool 2 is available, not on loan"
    ]
   },
   {
    "code": 1,
    "lines": [
     "error: no tool with id 99"
    ]
   },
   {
    "code": 0,
    "lines": [
     "#7 Stud finder returned 9 days late"
    ],
    "audit": [
     "returned #7 from priya (9d late)"
    ]
   }
  ],
  "file": {
   "nextId": 10,
   "tools": [
    {
     "id": 1,
     "name": "Cordless drill",
     "category": "power",
     "tags": [
      "drill",
      "cordless"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 89.5
    },
    {
     "id": 2,
     "name": "Orbital sander",
     "category": "power",
     "tags": [
      "sanding"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 64
    },
    {
     "id": 3,
     "name": "Claw hammer",
     "category": "hand",
     "tags": [
      "striking"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 18.25
    },
    {
     "id": 4,
     "name": "Tile saw",
     "category": "power",
     "tags": [
      "cutting",
      "wet"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 240
    },
    {
     "id": 5,
     "name": "Socket set",
     "category": "hand",
     "tags": [],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": null
    },
    {
     "id": 6,
     "name": "Garden fork",
     "category": "garden",
     "tags": [
      "digging"
     ],
     "status": "retired",
     "borrower": null,
     "dueDate": null,
     "retiredReason": "snapped handle",
     "replacementCost": 22
    },
    {
     "id": 7,
     "name": "Stud finder",
     "category": "measure",
     "tags": [],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": null
    },
    {
     "id": 8,
     "name": "Router table",
     "category": "power",
     "tags": [
      "woodwork",
      "cutting"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 310.99
    },
    {
     "id": 9,
     "name": "Level",
     "category": "measure",
     "tags": [],
     "status": "loaned",
     "borrower": "zed",
     "dueDate": "2025-03-01",
     "retiredReason": null,
     "replacementCost": 12.1
    }
   ]
  }
 },
 "return counts late days across a month end": [
  {
   "code": 0,
   "lines": [
    "#5 Socket set loaned to kim until 2025-03-15"
   ],
   "audit": [
    "loaned #5 to kim until 2025-03-15"
   ]
  },
  {
   "code": 0,
   "lines": [
    "#5 Socket set returned 5 days late"
   ],
   "audit": [
    "returned #5 from kim (5d late)"
   ]
  }
 ],
 "retire needs a reason and refuses tools that are out or already retired": {
  "out": [
   {
    "code": 0,
    "lines": [
     "#3 Claw hammer retired: bent frame"
    ],
    "audit": [
     "retired #3: bent frame"
    ]
   },
   {
    "code": 1,
    "lines": [
     "error: tool 1 is on loan to mina"
    ]
   },
   {
    "code": 1,
    "lines": [
     "error: tool 6 is already retired"
    ]
   },
   {
    "code": 2,
    "lines": [
     "error: --reason is required"
    ]
   },
   {
    "code": 1,
    "lines": [
     "error: no tool with id 99"
    ]
   }
  ],
  "file": {
   "nextId": 10,
   "tools": [
    {
     "id": 1,
     "name": "Cordless drill",
     "category": "power",
     "tags": [
      "drill",
      "cordless"
     ],
     "status": "loaned",
     "borrower": "mina",
     "dueDate": "2025-03-03",
     "retiredReason": null,
     "replacementCost": 89.5
    },
    {
     "id": 2,
     "name": "Orbital sander",
     "category": "power",
     "tags": [
      "sanding"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 64
    },
    {
     "id": 3,
     "name": "Claw hammer",
     "category": "hand",
     "tags": [
      "striking"
     ],
     "status": "retired",
     "borrower": null,
     "dueDate": null,
     "retiredReason": "bent frame",
     "replacementCost": 18.25
    },
    {
     "id": 4,
     "name": "Tile saw",
     "category": "power",
     "tags": [
      "cutting",
      "wet"
     ],
     "status": "loaned",
     "borrower": "oskar",
     "dueDate": "2025-03-14",
     "retiredReason": null,
     "replacementCost": 240
    },
    {
     "id": 5,
     "name": "Socket set",
     "category": "hand",
     "tags": [],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": null
    },
    {
     "id": 6,
     "name": "Garden fork",
     "category": "garden",
     "tags": [
      "digging"
     ],
     "status": "retired",
     "borrower": null,
     "dueDate": null,
     "retiredReason": "snapped handle",
     "replacementCost": 22
    },
    {
     "id": 7,
     "name": "Stud finder",
     "category": "measure",
     "tags": [],
     "status": "loaned",
     "borrower": "priya",
     "dueDate": "2025-03-01",
     "retiredReason": null,
     "replacementCost": null
    },
    {
     "id": 8,
     "name": "Router table",
     "category": "power",
     "tags": [
      "woodwork",
      "cutting"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 310.99
    },
    {
     "id": 9,
     "name": "Level",
     "category": "measure",
     "tags": [],
     "status": "loaned",
     "borrower": "zed",
     "dueDate": "2025-03-01",
     "retiredReason": null,
     "replacementCost": 12.1
    }
   ]
  }
 },
 "add assigns ids, tags and costs": {
  "out": [
   {
    "code": 0,
    "lines": [
     "added #10 Spirit level"
    ],
    "audit": [
     "added #10 Spirit level"
    ]
   },
   {
    "code": 0,
    "lines": [
     "added #11 Hacksaw"
    ],
    "audit": [
     "added #11 Hacksaw"
    ]
   },
   {
    "code": 0,
    "lines": [
     "#4   Tile saw  power  loaned     oskar, due 2025-03-14\n#11  Hacksaw   hand   available"
    ]
   },
   {
    "code": 0,
    "lines": [
     "11 tools: 6 available, 4 loaned, 1 retired\ncategories: garden 1, hand 3, measure 3, power 4\noverdue: 3\ninsured value: 747.34 (3 without a price)"
    ]
   }
  ],
  "file": {
   "nextId": 12,
   "tools": [
    {
     "id": 1,
     "name": "Cordless drill",
     "category": "power",
     "tags": [
      "drill",
      "cordless"
     ],
     "status": "loaned",
     "borrower": "mina",
     "dueDate": "2025-03-03",
     "retiredReason": null,
     "replacementCost": 89.5
    },
    {
     "id": 2,
     "name": "Orbital sander",
     "category": "power",
     "tags": [
      "sanding"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 64
    },
    {
     "id": 3,
     "name": "Claw hammer",
     "category": "hand",
     "tags": [
      "striking"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 18.25
    },
    {
     "id": 4,
     "name": "Tile saw",
     "category": "power",
     "tags": [
      "cutting",
      "wet"
     ],
     "status": "loaned",
     "borrower": "oskar",
     "dueDate": "2025-03-14",
     "retiredReason": null,
     "replacementCost": 240
    },
    {
     "id": 5,
     "name": "Socket set",
     "category": "hand",
     "tags": [],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": null
    },
    {
     "id": 6,
     "name": "Garden fork",
     "category": "garden",
     "tags": [
      "digging"
     ],
     "status": "retired",
     "borrower": null,
     "dueDate": null,
     "retiredReason": "snapped handle",
     "replacementCost": 22
    },
    {
     "id": 7,
     "name": "Stud finder",
     "category": "measure",
     "tags": [],
     "status": "loaned",
     "borrower": "priya",
     "dueDate": "2025-03-01",
     "retiredReason": null,
     "replacementCost": null
    },
    {
     "id": 8,
     "name": "Router table",
     "category": "power",
     "tags": [
      "woodwork",
      "cutting"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 310.99
    },
    {
     "id": 9,
     "name": "Level",
     "category": "measure",
     "tags": [],
     "status": "loaned",
     "borrower": "zed",
     "dueDate": "2025-03-01",
     "retiredReason": null,
     "replacementCost": 12.1
    },
    {
     "id": 10,
     "name": "Spirit level",
     "category": "measure",
     "tags": [
      "spirit",
      "bubble"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 12.5
    },
    {
     "id": 11,
     "name": "Hacksaw",
     "category": "hand",
     "tags": [],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": null
    }
   ]
  }
 },
 "bad arguments give the same messages and exit codes": {
  "out": [
   {
    "argv": [],
    "code": 2,
    "lines": [
     "error: no command given"
    ]
   },
   {
    "argv": [
     "bogus"
    ],
    "code": 2,
    "lines": [
     "error: unknown command \"bogus\""
    ]
   },
   {
    "argv": [
     "loan"
    ],
    "code": 2,
    "lines": [
     "error: \"undefined\" is not a tool id"
    ]
   },
   {
    "argv": [
     "loan",
     "abc",
     "x"
    ],
    "code": 2,
    "lines": [
     "error: \"abc\" is not a tool id"
    ]
   },
   {
    "argv": [
     "loan",
     "2"
    ],
    "code": 2,
    "lines": [
     "error: a borrower is required"
    ]
   },
   {
    "argv": [
     "loan",
     "2",
     "ana",
     "--days",
     "0"
    ],
    "code": 1,
    "lines": [
     "error: loans run 1 to 28 days, not 0"
    ]
   },
   {
    "argv": [
     "loan",
     "2",
     "ana",
     "--days",
     "29"
    ],
    "code": 1,
    "lines": [
     "error: loans run 1 to 28 days, not 29"
    ]
   },
   {
    "argv": [
     "loan",
     "2",
     "ana",
     "--days",
     "2.5"
    ],
    "code": 1,
    "lines": [
     "error: loans run 1 to 28 days, not 2.5"
    ]
   },
   {
    "argv": [
     "loan",
     "2",
     "ana",
     "--days",
     "soon"
    ],
    "code": 1,
    "lines": [
     "error: loans run 1 to 28 days, not NaN"
    ]
   },
   {
    "argv": [
     "add"
    ],
    "code": 2,
    "lines": [
     "error: a tool name is required"
    ]
   },
   {
    "argv": [
     "add",
     "Level"
    ],
    "code": 2,
    "lines": [
     "error: --category is required"
    ]
   },
   {
    "argv": [
     "add",
     "Level",
     "--category",
     "m",
     "--cost",
     "-3"
    ],
    "code": 2,
    "lines": [
     "error: bad cost \"-3\""
    ]
   },
   {
    "argv": [
     "add",
     "Level",
     "--category",
     "m",
     "--cost",
     "abc"
    ],
    "code": 2,
    "lines": [
     "error: bad cost \"abc\""
    ]
   },
   {
    "argv": [
     "list",
     "--status",
     "broken"
    ],
    "code": 1,
    "lines": [
     "error: unknown status \"broken\""
    ]
   },
   {
    "argv": [
     "return"
    ],
    "code": 2,
    "lines": [
     "error: \"undefined\" is not a tool id"
    ]
   },
   {
    "argv": [
     "return",
     "0"
    ],
    "code": 2,
    "lines": [
     "error: \"0\" is not a tool id"
    ]
   },
   {
    "argv": [
     "return",
     "1.5"
    ],
    "code": 2,
    "lines": [
     "error: \"1.5\" is not a tool id"
    ]
   },
   {
    "argv": [
     "retire",
     "1.5",
     "--reason",
     "x"
    ],
    "code": 2,
    "lines": [
     "error: \"1.5\" is not a tool id"
    ]
   }
  ],
  "file": {
   "nextId": 10,
   "tools": [
    {
     "id": 1,
     "name": "Cordless drill",
     "category": "power",
     "tags": [
      "drill",
      "Cordless"
     ],
     "status": "loaned",
     "borrower": "mina",
     "dueDate": "2025-03-03",
     "replacementCost": 89.5
    },
    {
     "id": 2,
     "name": "Orbital sander",
     "category": "power",
     "tags": [
      "sanding"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "replacementCost": 64
    },
    {
     "id": 3,
     "name": "Claw hammer",
     "category": "hand",
     "tags": [
      "striking"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "replacementCost": 18.25
    },
    {
     "id": 4,
     "name": "Tile saw",
     "category": "power",
     "tags": [
      "cutting",
      "wet"
     ],
     "status": "loaned",
     "borrower": "oskar",
     "dueDate": "2025-03-14",
     "replacementCost": 240
    },
    {
     "id": 5,
     "name": "Socket set",
     "category": "hand",
     "status": "available"
    },
    {
     "id": 6,
     "name": "Garden fork",
     "category": "garden",
     "tags": [
      "digging"
     ],
     "status": "retired",
     "retiredReason": "snapped handle",
     "replacementCost": 22
    },
    {
     "id": 7,
     "name": "Stud finder",
     "category": "measure",
     "tags": [],
     "status": "loaned",
     "borrower": "priya",
     "dueDate": "2025-03-01"
    },
    {
     "id": 8,
     "name": "Router table",
     "category": "power",
     "tags": [
      "woodwork",
      "cutting"
     ],
     "status": "available",
     "replacementCost": 310.99
    },
    {
     "id": 9,
     "name": "Level",
     "category": "measure",
     "status": "loaned",
     "borrower": "zed",
     "dueDate": "2025-03-01",
     "replacementCost": 12.1
    }
   ]
  }
 },
 "report and overdue summarise the fixture": [
  {
   "code": 0,
   "lines": [
    "9 tools: 4 available, 4 loaned, 1 retired\ncategories: garden 1, hand 2, measure 2, power 4\noverdue: 3\ninsured value: 734.84 (2 without a price)"
   ]
  },
  {
   "code": 0,
   "lines": [
    "#7  Stud finder     measure  loaned  priya, due 2025-03-01\n#9  Level           measure  loaned  zed, due 2025-03-01\n#1  Cordless drill  power    loaned  mina, due 2025-03-03"
   ]
  },
  {
   "code": 0,
   "lines": [
    "#7  Stud finder  measure  loaned  priya, due 2025-03-01\n#9  Level        measure  loaned  zed, due 2025-03-01"
   ]
  },
  {
   "code": 0,
   "lines": [
    "no tools"
   ]
  },
  {
   "code": 0,
   "lines": [
    "9 tools: 4 available, 4 loaned, 1 retired\ncategories: garden 1, hand 2, measure 2, power 4\noverdue: 0\ninsured value: 734.84 (2 without a price)"
   ]
  }
 ],
 "loading handles missing files, odd records and bad data": [
  {
   "code": 0,
   "lines": [
    "no tools"
   ]
  },
  {
   "code": 1,
   "prefix": "error: cannot read"
  },
  {
   "code": 1,
   "lines": [
    "error: tool 1: bad status \"lost\""
   ]
  },
  {
   "code": 1,
   "lines": [
    "error: tool 1: a loaned tool needs a borrower and a due date"
   ]
  },
  {
   "code": 1,
   "lines": [
    "error: tool 1: a loaned tool needs a borrower and a due date"
   ]
  },
  {
   "code": 1,
   "lines": [
    "error: bad tool id \"x\""
   ]
  },
  {
   "code": 1,
   "lines": [
    "error: tool 2: name is required"
   ]
  },
  {
   "code": 1,
   "lines": [
    "error: tool record must be an object"
   ]
  },
  {
   "code": 1,
   "lines": [
    "error: tool 1: bad status undefined"
   ]
  },
  {
   "code": 0,
   "lines": [
    "#3  Pliers  general  available\n#7  Awl     general  retired    unknown"
   ]
  },
  {
   "code": 0,
   "lines": [
    "added #8 Tongs"
   ],
   "audit": [
    "added #8 Tongs"
   ]
  },
  {
   "nextId": 9,
   "tools": [
    {
     "id": 3,
     "name": "Pliers",
     "category": "general",
     "tags": [
      "1",
      "x"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": null
    },
    {
     "id": 7,
     "name": "Awl",
     "category": "general",
     "tags": [],
     "status": "retired",
     "borrower": null,
     "dueDate": null,
     "retiredReason": "unknown",
     "replacementCost": null
    },
    {
     "id": 8,
     "name": "Tongs",
     "category": "kitchen",
     "tags": [],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": null
    }
   ]
  }
 ],
 "the store and tools API return and emit the same things": {
  "seen": [
   {
    "type": "added",
    "tool": {
     "id": 10,
     "name": "Mallet",
     "category": "hand",
     "tags": [],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 9
    }
   },
   {
    "type": "loaned",
    "tool": {
     "id": 10,
     "name": "Mallet",
     "category": "hand",
     "tags": [],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 9
    },
    "borrower": "Tess",
    "dueDate": "2025-03-13"
   },
   {
    "type": "returned",
    "tool": {
     "id": 10,
     "name": "Mallet",
     "category": "hand",
     "tags": [],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 9
    },
    "borrower": "Tess",
    "lateDays": 0
   },
   {
    "type": "loaned",
    "tool": {
     "id": 2,
     "name": "Orbital sander",
     "category": "power",
     "tags": [
      "sanding"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 64
    },
    "borrower": "Uma",
    "dueDate": "2025-03-11"
   },
   {
    "type": "returned",
    "tool": {
     "id": 2,
     "name": "Orbital sander",
     "category": "power",
     "tags": [
      "sanding"
     ],
     "status": "available",
     "borrower": null,
     "dueDate": null,
     "retiredReason": null,
     "replacementCost": 64
    },
    "borrower": "Uma",
    "lateDays": 4
   },
   {
    "type": "retired",
    "tool": {
     "id": 3,
     "name": "Claw hammer",
     "category": "hand",
     "tags": [
      "striking"
     ],
     "status": "retired",
     "borrower": null,
     "dueDate": null,
     "retiredReason": "unknown",
     "replacementCost": 18.25
    },
    "reason": "unknown"
   }
  ],
  "lines": [
   "added #10 Mallet",
   "loaned #10 to Tess until 2025-03-13",
   "returned #10 from Tess",
   "loaned #2 to Uma until 2025-03-11",
   "returned #2 from Uma (4d late)",
   "retired #3: unknown",
   "retired #5: lost"
  ],
  "added": {
   "id": 10,
   "name": "Mallet",
   "category": "hand",
   "tags": [],
   "status": "available",
   "borrower": null,
   "dueDate": null,
   "retiredReason": null,
   "replacementCost": 9
  },
  "loaned": {
   "id": 10,
   "name": "Mallet",
   "category": "hand",
   "tags": [],
   "status": "available",
   "borrower": null,
   "dueDate": null,
   "retiredReason": null,
   "replacementCost": 9
  },
  "early": {
   "tool": {
    "id": 10,
    "name": "Mallet",
    "category": "hand",
    "tags": [],
    "status": "available",
    "borrower": null,
    "dueDate": null,
    "retiredReason": null,
    "replacementCost": 9
   },
   "lateDays": 0
  },
  "late": {
   "tool": {
    "id": 2,
    "name": "Orbital sander",
    "category": "power",
    "tags": [
     "sanding"
    ],
    "status": "available",
    "borrower": null,
    "dueDate": null,
    "retiredReason": null,
    "replacementCost": 64
   },
   "lateDays": 4
  },
  "retired": {
   "id": 3,
   "name": "Claw hammer",
   "category": "hand",
   "tags": [
    "striking"
   ],
   "status": "retired",
   "borrower": null,
   "dueDate": null,
   "retiredReason": "unknown",
   "replacementCost": 18.25
  },
  "errors": [
   "a tool needs a name",
   "tool 3 is retired, not available",
   "a loan needs a borrower",
   "no tool with id 99"
  ],
  "count": 1,
  "next": 11
 },
 "findTools, overdueTools and summarize on a custom store": {
  "all": [
   1,
   2,
   3,
   4,
   5,
   6,
   7,
   8,
   9
  ],
  "combined": [
   8
  ],
  "overdue": [
   [
    7,
    "2025-03-01"
   ],
   [
    9,
    "2025-03-01"
   ],
   [
    1,
    "2025-03-03"
   ]
  ],
  "summary": {
   "total": 9,
   "byStatus": {
    "available": 4,
    "loaned": 4,
    "retired": 1
   },
   "byCategory": {
    "power": 4,
    "hand": 2,
    "garden": 1,
    "measure": 2
   },
   "overdue": 3,
   "unpriced": 2,
   "insuredValue": 734.84
  },
  "table": "#1  Cordless drill  power    loaned  mina, due 2025-03-03\n#4  Tile saw        power    loaned  oskar, due 2025-03-14\n#7  Stud finder     measure  loaned  priya, due 2025-03-01\n#9  Level           measure  loaned  zed, due 2025-03-01",
  "empty": "no tools",
  "text": "9 tools: 4 available, 4 loaned, 1 retired\ncategories: garden 1, hand 2, measure 2, power 4\noverdue: 3\ninsured value: 734.84 (2 without a price)",
  "noTools": "0 tools: 0 available, 0 loaned, 0 retired\ncategories: none\noverdue: 0\ninsured value: 0.00 (0 without a price)"
 },
 "date helpers handle leap days and invalid dates": {
  "add": [
   "2024-03-01",
   "2025-03-01",
   "2026-01-01",
   "2025-03-10"
  ],
  "between": [
   2,
   -9,
   0
  ],
  "valid": [
   false,
   false,
   true,
   false,
   false,
   false,
   true
  ],
  "other": [
   false,
   false,
   false
  ]
 }
}/*END*/;

const FIXTURE = {
  nextId: 10,
  tools: [
    { id: 1, name: "Cordless drill", category: "power", tags: ["drill", "Cordless"], status: "loaned", borrower: "mina", dueDate: "2025-03-03", replacementCost: 89.5 },
    { id: 2, name: "Orbital sander", category: "power", tags: ["sanding"], status: "available", borrower: null, dueDate: null, replacementCost: 64 },
    { id: 3, name: "Claw hammer", category: "hand", tags: ["striking"], status: "available", borrower: null, dueDate: null, replacementCost: 18.25 },
    { id: 4, name: "Tile saw", category: "power", tags: ["cutting", "wet"], status: "loaned", borrower: "oskar", dueDate: "2025-03-14", replacementCost: 240 },
    { id: 5, name: "Socket set", category: "hand", status: "available" },
    { id: 6, name: "Garden fork", category: "garden", tags: ["digging"], status: "retired", retiredReason: "snapped handle", replacementCost: 22 },
    { id: 7, name: "Stud finder", category: "measure", tags: [], status: "loaned", borrower: "priya", dueDate: "2025-03-01" },
    { id: 8, name: "Router table", category: "power", tags: ["woodwork", "cutting"], status: "available", replacementCost: 310.99 },
    { id: 9, name: "Level", category: "measure", status: "loaned", borrower: "zed", dueDate: "2025-03-01", replacementCost: 12.1 },
  ],
};

const load = (m: string) => import(/* @vite-ignore */ `../../src/${m}.${EXT}`);

function tmpFile(data: unknown | string = FIXTURE): string {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "port-")), "tools.json");
  fs.writeFileSync(file, typeof data === "string" ? data : JSON.stringify(data));
  return file;
}

async function cli(argv: string[], file: string, today = "2025-03-10") {
  const { main } = await load("cli");
  const lines: string[] = [];
  const audit: string[] = [];
  const code = main(argv, { file, today, out: (l: string) => lines.push(String(l).split(file).join("<file>")), audit: (l: string) => audit.push(l) });
  return audit.length ? { code, lines, audit } : { code, lines };
}

const saved = (file: string) => JSON.parse(fs.readFileSync(file, "utf8"));

function behave(name: string, fn: () => unknown | Promise<unknown>) {
  it(name, async () => {
    const got = JSON.parse(JSON.stringify(await fn()));
    if (DUMP) { DUMPED[name] = got; return; }
    expect(got).toEqual(GOLDEN[name]);
  });
}

describe("behavior", () => {
  behave("list filters by status, tag and text", async () => {
    const file = tmpFile();
    const out: unknown[] = [];
    for (const argv of [["list"], ["list", "--status", "loaned"], ["list", "--tag", "CUTTING"], ["list", "--search", "POWER"],
      ["list", "--status", "retired", "--search", "fork"], ["list", "--search", "zzz"], ["list", "--status", "available", "--tag", "cutting"]]) {
      out.push(await cli(argv, file));
    }
    return out;
  });

  behave("loan saves the due date, trims the borrower and logs the change", async () => {
    const file = tmpFile();
    const a = await cli(["loan", "2", "  ana ", "--days", "5"], file);
    const b = await cli(["loan", "3", "bo"], file);
    const c = await cli(["loan", "2", "bob"], file);
    const d = await cli(["loan", "6", "bob"], file);
    const e = await cli(["loan", "99", "bob"], file);
    return { a, b, c, d, e, file: saved(file) };
  });

  behave("return reports lateness and frees the tool", async () => {
    const file = tmpFile();
    const out = [];
    for (const argv of [["return", "1"], ["return", "4"], ["return", "2"], ["return", "99"], ["return", "7"]]) out.push(await cli(argv, file));
    return { out, file: saved(file) };
  });

  behave("return counts late days across a month end", async () => {
    const file = tmpFile();
    return [await cli(["loan", "5", "kim", "--days", "28"], file, "2025-02-15"), await cli(["return", "5"], file, "2025-03-20")];
  });

  behave("retire needs a reason and refuses tools that are out or already retired", async () => {
    const file = tmpFile();
    const out = [];
    for (const argv of [["retire", "3", "--reason", " bent frame "], ["retire", "1", "--reason", "worn"], ["retire", "6", "--reason", "again"],
      ["retire", "2"], ["retire", "99", "--reason", "x"]]) out.push(await cli(argv, file));
    return { out, file: saved(file) };
  });

  behave("add assigns ids, tags and costs", async () => {
    const file = tmpFile();
    const out = [];
    for (const argv of [["add", "Spirit level", "--category", "measure", "--tags", "Spirit, bubble ,,", "--cost", "12.5"],
      ["add", "Hacksaw", "--category", "hand"], ["list", "--search", "saw"], ["report"]]) out.push(await cli(argv, file));
    return { out, file: saved(file) };
  });

  behave("bad arguments give the same messages and exit codes", async () => {
    const file = tmpFile();
    const out = [];
    for (const argv of [[], ["bogus"], ["loan"], ["loan", "abc", "x"], ["loan", "2"], ["loan", "2", "ana", "--days", "0"],
      ["loan", "2", "ana", "--days", "29"], ["loan", "2", "ana", "--days", "2.5"], ["loan", "2", "ana", "--days", "soon"], ["add"],
      ["add", "Level"], ["add", "Level", "--category", "m", "--cost", "-3"], ["add", "Level", "--category", "m", "--cost", "abc"],
      ["list", "--status", "broken"], ["return"], ["return", "0"], ["return", "1.5"], ["retire", "1.5", "--reason", "x"]]) {
      out.push({ argv, ...(await cli(argv, file)) });
    }
    return { out, file: saved(file) };
  });

  behave("report and overdue summarise the fixture", async () => {
    const file = tmpFile();
    const out = [];
    for (const [argv, today] of [[["report"], "2025-03-10"], [["overdue"], "2025-03-10"], [["overdue"], "2025-03-02"],
      [["overdue"], "2025-02-01"], [["report"], "2025-03-01"]] as [string[], string][]) out.push(await cli(argv, file, today));
    return out;
  });

  behave("loading handles missing files, odd records and bad data", async () => {
    const out: unknown[] = [];
    out.push(await cli(["list"], path.join(os.tmpdir(), "no-such-dir-port", "tools.json")));
    const corrupt = await cli(["list"], tmpFile("{ not json"));
    out.push({ code: corrupt.code, prefix: corrupt.lines[0].slice(0, 18) });
    const bad = (tools: unknown[]) => cli(["list"], tmpFile({ tools }));
    out.push(await bad([{ id: 1, name: "Saw", status: "lost" }]));
    out.push(await bad([{ id: 1, name: "Saw", status: "loaned", borrower: "x" }]));
    out.push(await bad([{ id: 1, name: "Saw", status: "loaned", borrower: "x", dueDate: "2025-02-30" }]));
    out.push(await bad([{ id: "x", name: "Saw", status: "available" }]));
    out.push(await bad([{ id: 2, name: "  ", status: "available" }]));
    out.push(await bad([null]));
    out.push(await bad([{ id: 1, name: "Saw" }]));
    const sparse = tmpFile({ tools: [{ id: 3, name: " Pliers ", tags: [1, "X"], status: "available" }, { id: 7, name: "Awl", status: "retired" }] });
    out.push(await cli(["list"], sparse));
    out.push(await cli(["add", "Tongs", "--category", "kitchen"], sparse));
    out.push(saved(sparse));
    return out;
  });

  behave("the store and tools API return and emit the same things", async () => {
    const { ToolStore } = await load("store");
    const t = await load("tools");
    const store = new ToolStore(tmpFile()).load();
    const seen: unknown[] = [];
    const stop = store.on((e: unknown) => seen.push(e));
    const lines = t.auditLines(store);
    const added = t.addTool(store, { name: "Mallet", category: "hand", replacementCost: 9 });
    const loaned = t.loanTool(store, added.id, " Tess ", 3, "2025-03-10");
    const early = t.returnTool(store, added.id, "2025-03-12");
    t.loanTool(store, 2, "Uma", 1, "2025-03-10");
    const late = t.returnTool(store, 2, "2025-03-15");
    const retired = t.retireTool(store, 3, undefined);
    stop();
    t.retireTool(store, 5, "lost");
    const errors = [] as string[];
    for (const fn of [() => t.addTool(store, { name: "  " }), () => t.loanTool(store, 3, "x", 1, "2025-03-10"), () => t.loanTool(store, 2, " ", 1, "2025-03-10"),
      () => t.retireTool(store, 99, "x")]) {
      try { fn(); errors.push("no error"); } catch (e) { errors.push((e as Error).message); }
    }
    return { seen, lines, added, loaned, early, late, retired, errors, count: store.listeners.length, next: store.nextId };
  });

  behave("findTools, overdueTools and summarize on a custom store", async () => {
    const { ToolStore } = await load("store");
    const t = await load("tools");
    const r = await load("report");
    const store = new ToolStore(tmpFile()).load();
    const ids = (tools: { id: number }[]) => tools.map((x) => x.id);
    return {
      all: ids(t.findTools(store)),
      combined: ids(t.findTools(store, { text: "cut", status: "available", tag: "woodwork" })),
      overdue: t.overdueTools(store, "2025-03-10").map((x: { id: number; dueDate: string }) => [x.id, x.dueDate]),
      summary: r.summarize(store, "2025-03-10"),
      table: r.formatTable(t.findTools(store, { status: "loaned" })),
      empty: r.formatTable([]),
      text: r.formatSummary(r.summarize(store, "2025-03-10")),
      noTools: r.formatSummary(r.summarize(new ToolStore("/nonexistent/x.json").load(), "2025-03-10")),
    };
  });

  behave("date helpers handle leap days and invalid dates", async () => {
    const d = await load("dates");
    return {
      add: [d.addDays("2024-02-28", 2), d.addDays("2025-02-28", 1), d.addDays("2025-12-31", 1), d.addDays("2025-03-10", 0)],
      between: [d.daysBetween("2024-02-28", "2024-03-01"), d.daysBetween("2025-03-10", "2025-03-01"), d.daysBetween("2025-03-01", "2025-03-01")],
      valid: ["2025-02-30", "2025-2-3", "2024-02-29", "2025-13-01", "20250101", "", "2025-03-10"].map((x) => d.isIsoDate(x)),
      other: [d.isIsoDate(20250101), d.isIsoDate(null), d.isIsoDate(undefined)],
    };
  });
});

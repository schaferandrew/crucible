/**
 * Crucible's per-run pi extension.
 *
 * Loaded with `pi -e <this file>` for every benchmark run, so nothing lands in
 * the user's global ~/.pi/agent config. Configuration arrives as JSON in the
 * CRUCIBLE_PI_CONFIG env var:
 *
 *   {
 *     "providers": { "<name>": { baseUrl, api, apiKey, compat?, models: [{ id }] } },
 *     "mcpServers": { "<name>": { "command": ["python", "/path/server.py"] } },
 *     "timingFile": "/run/dir/pi-timing.ndjson"
 *   }
 *
 * - providers: local OpenAI-compatible endpoints (ollama, LM Studio) pi has no
 *   built-in entry for; model defaults are filled in here.
 * - mcpServers: pi has no MCP support, so each stdio MCP server is spawned and
 *   its tools are registered as native pi tools that proxy tools/call.
 * - timingFile: one NDJSON line per model response with epoch-ms timestamps
 *   for request sent, first streamed token and response end, so crucible can
 *   report time to first token (headless and TUI runs alike).
 */
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { appendFileSync } from "node:fs";
import { createInterface } from "node:readline";

type Json = any;

interface McpServerConfig {
	command: string[];
	env?: Record<string, string>;
}

class StdioMcpClient {
	private proc: ChildProcessWithoutNullStreams;
	private nextId = 1;
	private pending = new Map<number, { resolve: (v: Json) => void; reject: (e: Error) => void }>();

	constructor(readonly name: string, config: McpServerConfig) {
		const [cmd, ...args] = config.command;
		this.proc = spawn(cmd, args, {
			env: { ...process.env, ...(config.env ?? {}) },
			stdio: ["pipe", "pipe", "pipe"],
			windowsHide: true,
		});
		this.proc.on("error", (err) => this.failAll(err));
		this.proc.on("exit", (code) => this.failAll(new Error(`MCP server ${name} exited (${code})`)));
		this.proc.stderr.on("data", () => {}); // drain so the server never blocks
		createInterface({ input: this.proc.stdout }).on("line", (line) => {
			let msg: Json;
			try {
				msg = JSON.parse(line);
			} catch {
				return; // not protocol output
			}
			const waiter = typeof msg?.id === "number" ? this.pending.get(msg.id) : undefined;
			if (!waiter) return;
			this.pending.delete(msg.id);
			if (msg.error) waiter.reject(new Error(msg.error.message ?? JSON.stringify(msg.error)));
			else waiter.resolve(msg.result);
		});
	}

	private failAll(err: Error) {
		for (const waiter of this.pending.values()) waiter.reject(err);
		this.pending.clear();
	}

	request(method: string, params: Json = {}, timeoutMs = 30000): Promise<Json> {
		const id = this.nextId++;
		return new Promise((resolve, reject) => {
			const timer = setTimeout(() => {
				this.pending.delete(id);
				reject(new Error(`MCP ${this.name} ${method} timed out`));
			}, timeoutMs);
			this.pending.set(id, {
				resolve: (v) => (clearTimeout(timer), resolve(v)),
				reject: (e) => (clearTimeout(timer), reject(e)),
			});
			this.proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
		});
	}

	notify(method: string, params: Json = {}) {
		this.proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", method, params }) + "\n");
	}

	close() {
		if (this.proc.exitCode === null) this.proc.kill();
	}
}

function withModelDefaults(model: Json): Json {
	return {
		name: model.id,
		reasoning: false,
		input: ["text"],
		cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
		contextWindow: 128000,
		maxTokens: 16384,
		...model,
	};
}

export default async function crucible(pi: any) {
	let config: Json = {};
	try {
		config = JSON.parse(process.env.CRUCIBLE_PI_CONFIG || "{}");
	} catch (err) {
		console.error(`[crucible] invalid CRUCIBLE_PI_CONFIG: ${err}`);
	}

	for (const [name, provider] of Object.entries<Json>(config.providers ?? {})) {
		pi.registerProvider(name, { ...provider, models: (provider.models ?? []).map(withModelDefaults) });
	}

	const clients: StdioMcpClient[] = [];
	for (const [name, server] of Object.entries<McpServerConfig>(config.mcpServers ?? {})) {
		const client = new StdioMcpClient(name, server);
		try {
			await client.request("initialize", {
				protocolVersion: "2024-11-05",
				capabilities: {},
				clientInfo: { name: "crucible-pi", version: "1.0.0" },
			});
			client.notify("notifications/initialized");
			const { tools = [] } = (await client.request("tools/list")) ?? {};
			for (const tool of tools) {
				pi.registerTool({
					name: tool.name,
					label: `${name}: ${tool.name}`,
					description: tool.description ?? tool.name,
					promptSnippet: tool.description ?? tool.name,
					parameters: tool.inputSchema ?? { type: "object", properties: {} },
					async execute(_toolCallId: string, params: Json) {
						const result = await client.request("tools/call", { name: tool.name, arguments: params ?? {} }, 120000);
						const content = (result?.content ?? []).filter((c: Json) => c?.type === "text" || c?.type === "image");
						if (result?.isError) throw new Error(content.map((c: Json) => c.text ?? "").join("\n") || "MCP tool error");
						return { content, details: { server: name } };
					},
				});
			}
			clients.push(client);
		} catch (err) {
			console.error(`[crucible] MCP server ${name} unavailable: ${err}`);
			client.close();
		}
	}

	if (config.timingFile) recordTiming(pi, config.timingFile);

	const closeAll = () => clients.forEach((c) => c.close());
	pi.on("session_shutdown", closeAll);
	process.once("exit", closeAll);
}

function recordTiming(pi: any, file: string) {
	let requestStart: number | null = null;
	let firstToken: number | null = null;
	pi.on("before_provider_request", () => {
		requestStart = Date.now();
		firstToken = null;
	});
	pi.on("message_update", (event: Json) => {
		// Any streamed delta (text, thinking, tool-call arguments) is a token
		if (firstToken === null && String(event?.assistantMessageEvent?.type ?? "").endsWith("_delta")) {
			firstToken = Date.now();
		}
	});
	pi.on("message_end", (event: Json) => {
		if (event?.message?.role !== "assistant" || requestStart === null) return;
		const record = {
			request_start: requestStart,
			first_token: firstToken,
			end: Date.now(),
			stop_reason: event.message.stopReason ?? null,
		};
		try {
			appendFileSync(file, JSON.stringify(record) + "\n");
		} catch (err) {
			console.error(`[crucible] cannot write timing: ${err}`);
		}
		requestStart = firstToken = null;
	});
}

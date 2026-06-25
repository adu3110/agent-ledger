/**
 * State Machine Agent Ledger — from scratch (TypeScript).
 *
 * Append-only, hash-chained LEDGER.md coordination protocol for multi-agent
 * systems. Agents communicate only by writing to / reading from the Ledger.
 * Every action is typed, timestamped, and hashed for tamper detection.
 * Replay the ledger line-by-line to reconstruct any past state.
 *
 * Run:
 *   npx ts-node ledger.ts
 *   OPENAI_API_KEY=sk-... npx ts-node ledger.ts   (explicit override)
 *
 * API key resolution order:
 *   1. OPENAI_API_KEY environment variable
 *   2. .env or .env.local in this directory or any parent
 *
 * Output: LEDGER.md
 *
 * Dependencies: stdlib (fs, crypto, https, path) only.
 */

import * as fs     from "fs";
import * as crypto from "crypto";
import * as https  from "https";
import * as path   from "path";

// ──────────────────────────────────────────────────────────────────────────────
// Env-file loader
// ──────────────────────────────────────────────────────────────────────────────
function loadEnvFiles(): void {
  let dir = __dirname;
  const visited = new Set<string>();
  while (dir && !visited.has(dir)) {
    visited.add(dir);
    for (const name of [".env.local", ".env"]) {
      const filePath = path.join(dir, name);
      if (fs.existsSync(filePath)) {
        for (const raw of fs.readFileSync(filePath, "utf-8").split("\n")) {
          const line = raw.trim();
          if (!line || line.startsWith("#") || !line.includes("=")) continue;
          const eqIdx = line.indexOf("=");
          const key   = line.slice(0, eqIdx).trim();
          const val   = line.slice(eqIdx + 1).trim().replace(/^["']|["']$/g, "");
          if (key && !(key in process.env)) process.env[key] = val;
        }
      }
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
}

loadEnvFiles();

const API_KEY = process.env.OPENAI_API_KEY ?? "";
const MODEL   = process.env.LEDGER_MODEL   ?? "gpt-4o-mini";

if (!API_KEY) {
  console.error(
    "OPENAI_API_KEY not found.\n" +
    "Set it in your environment or create a .env / .env.local file:\n" +
    "  OPENAI_API_KEY=sk-..."
  );
  process.exit(1);
}

const LEDGER_FILE = path.join(__dirname, "LEDGER.md");

// ──────────────────────────────────────────────────────────────────────────────
// Entry types
// ──────────────────────────────────────────────────────────────────────────────
type EntryType =
  | "PLAN" | "TOOL_CALL" | "OBSERVATION"
  | "CONFLICT" | "RESOLUTION" | "CHECKPOINT" | "ANSWER";

interface LedgerEntry {
  seq:       number;
  timestamp: string;
  agent:     string;
  etype:     EntryType;
  content:   Record<string, unknown>;
  hash:      string;
}

function computeHash(seq: number, prevHash: string, content: Record<string, unknown>): string {
  const payload = `${seq}|${prevHash}|${JSON.stringify(content, Object.keys(content).sort())}`;
  return crypto.createHash("sha256").update(payload).digest("hex").slice(0, 16);
}

function entryToMarkdown(e: LedgerEntry): string {
  const lines: string[] = [
    `## [${String(e.seq).padStart(4, "0")}] ${e.etype}  ·  ${e.agent}  ·  ${e.timestamp}`,
    `<!-- hash:${e.hash} -->`,
  ];
  for (const [k, v] of Object.entries(e.content)) {
    if (typeof v === "string") {
      lines.push(`**${k}:** ${v}`);
    } else {
      lines.push(`**${k}:**\n\`\`\`json\n${JSON.stringify(v, null, 2)}\n\`\`\``);
    }
  }
  lines.push("");
  return lines.join("\n") + "\n---\n";
}

// ──────────────────────────────────────────────────────────────────────────────
// Ledger — append-only, hash-chained
// ──────────────────────────────────────────────────────────────────────────────
class Ledger {
  private entries: LedgerEntry[] = [];
  private prevHash = "genesis";

  constructor(private filePath: string) {
    if (!fs.existsSync(filePath)) {
      fs.writeFileSync(filePath, "# Agent Ledger\n\nAppend-only transaction log.\n\n---\n\n", "utf-8");
    }
  }

  append(agent: string, etype: EntryType, content: Record<string, unknown>): LedgerEntry {
    const seq  = this.entries.length + 1;
    const ts   = new Date().toISOString().replace(/(\.\d{3})Z$/, "$1Z");
    const hash = computeHash(seq, this.prevHash, content);
    this.prevHash = hash;
    const entry: LedgerEntry = { seq, timestamp: ts, agent, etype, content, hash };
    this.entries.push(entry);
    fs.appendFileSync(this.filePath, entryToMarkdown(entry), "utf-8");
    return entry;
  }

  getEntries(): LedgerEntry[] { return this.entries; }

  state(): Record<string, unknown> {
    const s: Record<string, unknown> = {};
    for (const e of this.entries) {
      if (e.etype === "CHECKPOINT") {
        Object.assign(s, (e.content.snapshot as Record<string, unknown>) ?? {});
      } else if (e.etype === "OBSERVATION") {
        s[e.content.key as string] = e.content.value;
      } else if (e.etype === "ANSWER") {
        s.final_answer = e.content.answer;
      } else if (e.etype === "RESOLUTION") {
        s.conflict_resolved = e.content.resolution;
      }
    }
    return s;
  }

  verifyChain(): boolean {
    let prev = "genesis";
    for (const e of this.entries) {
      if (computeHash(e.seq, prev, e.content) !== e.hash) return false;
      prev = e.hash;
    }
    return true;
  }

  detectConflicts(): Array<[LedgerEntry, LedgerEntry]> {
    const obs = new Map<string, LedgerEntry>();
    const conflicts: Array<[LedgerEntry, LedgerEntry]> = [];
    for (const e of this.entries) {
      if (e.etype !== "OBSERVATION") continue;
      const key = e.content.key as string;
      const prev = obs.get(key);
      if (prev && prev.content.value !== e.content.value) conflicts.push([prev, e]);
      obs.set(key, e);
    }
    return conflicts;
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// LLM interface
// ──────────────────────────────────────────────────────────────────────────────
function callLLM(
  prompt: string,
  system = "You are a concise technical expert. Answer in 1-2 sentences."
): Promise<string> {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      model:       MODEL,
      messages:    [{ role: "system", content: system }, { role: "user", content: prompt }],
      temperature: 0.3,
      max_tokens:  200,
    });
    const buf  = Buffer.from(body, "utf-8");
    const opts: https.RequestOptions = {
      hostname: "api.openai.com",
      path:     "/v1/chat/completions",
      method:   "POST",
      headers:  {
        "Content-Type":   "application/json",
        "Authorization":  `Bearer ${API_KEY}`,
        "Content-Length": buf.length,
      },
    };
    const req = https.request(opts, res => {
      let raw = "";
      res.on("data", c => raw += c);
      res.on("end", () => {
        try {
          const data = JSON.parse(raw);
          if (data.error) { reject(new Error(data.error.message)); return; }
          resolve(data.choices[0].message.content.trim());
        } catch (e) { reject(e); }
      });
    });
    req.on("error", reject);
    req.write(buf);
    req.end();
  });
}

// ──────────────────────────────────────────────────────────────────────────────
// Agent
// ──────────────────────────────────────────────────────────────────────────────
class Agent {
  constructor(protected name: string, protected ledger: Ledger) {}

  plan(goal: string): LedgerEntry {
    return this.ledger.append(this.name, "PLAN", { goal });
  }

  async callTool(tool: string, args: Record<string, unknown>): Promise<LedgerEntry> {
    const result = await this.toolDispatch(tool, args);
    const entry  = this.ledger.append(this.name, "TOOL_CALL", { tool, args, result });
    this.observe(`${tool}_result`, result);
    return entry;
  }

  observe(key: string, value: unknown): LedgerEntry {
    return this.ledger.append(this.name, "OBSERVATION", { key, value });
  }

  answer(answer: string): LedgerEntry {
    return this.ledger.append(this.name, "ANSWER", { answer });
  }

  checkpoint(): LedgerEntry {
    return this.ledger.append(this.name, "CHECKPOINT", { snapshot: this.ledger.state() });
  }

  protected async toolDispatch(tool: string, args: Record<string, unknown>): Promise<unknown> {
    if (tool === "search_codebase") return { files: ["services/payments.ts", "webhooks/stripe.ts"] };
    if (tool === "read_file")       return { content: "export function processPayment(event: Event) { charge(event.amount); }" };
    if (tool === "llm_reason")      return callLLM((args.prompt as string) ?? "");
    return { status: "ok" };
  }
}

class ResolverAgent extends Agent {
  async resolve(conflict: [LedgerEntry, LedgerEntry]): Promise<LedgerEntry> {
    const [a, b] = conflict;
    const reasoning = await callLLM(
      `Two agents disagree on '${a.content.key}': '${a.content.value}' vs '${b.content.value}'. Which is correct and why? Reply in one sentence.`
    );
    const resolution = `Resolution: ${reasoning}`;
    this.ledger.append(this.name, "CONFLICT", {
      key:     a.content.key,
      agent_a: a.agent,
      value_a: String(a.content.value),
      agent_b: b.agent,
      value_b: String(b.content.value),
    });
    return this.ledger.append(this.name, "RESOLUTION", { resolution, reasoning });
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// Main demo
// ──────────────────────────────────────────────────────────────────────────────
async function main(): Promise<void> {
  if (fs.existsSync(LEDGER_FILE)) fs.unlinkSync(LEDGER_FILE);

  const ledger    = new Ledger(LEDGER_FILE);
  const diagnoser = new Agent("DiagnoserAgent", ledger);
  const fixer     = new Agent("FixerAgent",     ledger);
  const resolver  = new ResolverAgent("ResolverAgent", ledger);

  const problem = "Duplicate charges occur when a Stripe webhook is retried.";
  const HR = "=".repeat(65);
  console.log(HR);
  console.log(`  State Machine Agent Ledger  (TypeScript · ${MODEL})`);
  console.log(HR);
  console.log(`\nProblem: ${problem}\n`);

  // DiagnoserAgent
  console.log("[DiagnoserAgent] Planning…");
  diagnoser.plan(`Diagnose: ${problem}`);
  await diagnoser.callTool("search_codebase", { query: "payment webhook" });
  await diagnoser.callTool("read_file", { path: "webhooks/stripe.ts" });
  await diagnoser.callTool("llm_reason", { prompt: "Why do duplicate charges occur in a webhook-based payments service?" });
  diagnoser.observe("root_cause", "No idempotency check on webhook events");
  diagnoser.checkpoint();

  // FixerAgent
  console.log("[FixerAgent] Planning…");
  fixer.plan("Design a fix for the idempotency gap.");
  await fixer.callTool("llm_reason", { prompt: "What is the minimal fix for duplicate webhook charges that requires no schema migration?" });
  fixer.observe("fix_approach", "Store event_id in KV; skip if already processed");

  // Conflict
  fixer.observe("requires_migration", "no");
  diagnoser.observe("requires_migration", "yes");

  // Conflict detection & resolution
  const conflicts = ledger.detectConflicts();
  if (conflicts.length) {
    console.log(`\n[ResolverAgent] ${conflicts.length} conflict(s) detected — resolving…`);
    for (const c of conflicts) await resolver.resolve(c);
  }

  // Final answer
  await fixer.callTool("llm_reason", {
    prompt: "Write a final 2-sentence implementation plan for an idempotency fix in a payments webhook handler."
  });
  const finalAnswer = (ledger.state()["llm_reason_result"] as string) ?? "See ledger for details.";
  fixer.answer(finalAnswer);

  // Report
  const entries = ledger.getEntries();
  console.log(`\n${HR}`);
  console.log(`  Ledger written to: ${LEDGER_FILE}`);
  console.log(`  Total entries    : ${entries.length}`);
  console.log(`  Hash chain valid : ${ledger.verifyChain()}`);
  console.log(HR);

  const state = ledger.state();
  console.log("\nReconstructed state (from replay):");
  Object.entries(state).forEach(([k, v]) => console.log(`  ${k}: ${String(v).slice(0, 120)}`));

  console.log(`\n${HR}`);
  console.log("  Replay (all entries):");
  console.log(HR);
  entries.forEach(e => {
    console.log(`  [${String(e.seq).padStart(4,"0")}] ${e.etype.padEnd(12)} ${e.agent.padEnd(18)} hash=${e.hash}`);
  });

  console.log(`\nOpen LEDGER.md to read the full human-readable log.`);
}

main().catch(e => { console.error(e); process.exit(1); });

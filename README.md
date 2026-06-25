```
  █████╗  ██████╗ ███████╗███╗   ██╗████████╗    ██╗     ███████╗██████╗  ██████╗ ███████╗██████╗
 ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝    ██║     ██╔════╝██╔══██╗██╔════╝ ██╔════╝██╔══██╗
 ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║       ██║     █████╗  ██║  ██║██║  ███╗█████╗  ██████╔╝
 ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║       ██║     ██╔══╝  ██║  ██║██║   ██║██╔══╝  ██╔══██╗
 ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║       ███████╗███████╗██████╔╝╚██████╔╝███████╗██║  ██║
 ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝       ╚══════╝╚══════╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝
             Append-only, hash-chained coordination ledger for multi-agent AI systems
```

**SHA-256 chain · zero dependencies · Python · TypeScript · conflict detection · full replay · Markdown output**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[Install](#get-started-30-seconds) · [How it works](#how-it-works) · [Proof](#proof) · [Compared to](#compared-to) · [API](#three-key-operations)

---

> **Live:** 22-entry ledger. 2 conflicts detected and resolved. Hash chain valid: **True**.  
> Full state reconstructed from replay in < 10ms. Zero external dependencies.

---

## What it does

- **Typed entries** — every agent action is a `PLAN / TOOL_CALL / OBSERVATION / CONFLICT / RESOLUTION / CHECKPOINT / ANSWER`
- **SHA-256 chain** — `hash[n] = SHA256(seq[n] | hash[n-1] | content[n])[:16]`; tamper any entry and `verify_chain()` catches it
- **Conflict detection** — two agents disagree on the same key → `CONFLICT` entry raised automatically
- **Full replay** — `ledger.state()` replays all entries to reconstruct current agent state from scratch
- **Checkpoints** — snapshot current state so replay can fast-forward
- **Human-readable** — output is `LEDGER.md`, readable as plain text, git-diff friendly
- **Zero dependencies** — pure Python stdlib; TypeScript version has zero npm dependencies

Agents **never communicate directly**. They read the ledger to learn state, write their next action.

## How it works

```
 Agent A (DiagnoserAgent)        Agent B (FixerAgent)
        │  reads ledger                  │  reads ledger
        │  writes PLAN, TOOL_CALL, OBS   │  writes PLAN, TOOL_CALL, OBS
        │                                │
        ▼                                ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │  LEDGER.md   (append-only, hash-chained)                        │
  │  ─────────────────────────────────────────────────────────────── │
  │  [0001] PLAN        DiagnoserAgent   hash=8adecb7c6f006b85      │
  │  [0002] TOOL_CALL   DiagnoserAgent   hash=4ae8e139316b4322      │
  │  [0003] OBSERVATION DiagnoserAgent   hash=eedce4622769aeaf      │
  │  ...                                                             │
  │  [0009] CHECKPOINT  DiagnoserAgent   hash=98e1077fc32ab600      │
  │  [0010] PLAN        FixerAgent       hash=d2212d0570e2d77d      │
  │  ...                                                             │
  │  [0016] CONFLICT    ResolverAgent    hash=cd12c4e483c206c3      │  ← auto-detected
  │  [0017] RESOLUTION  ResolverAgent    hash=10900ad19bce1edb      │  ← adjudicated
  │  [0022] ANSWER      FixerAgent       hash=cb3fff0310c2feca      │
  └──────────────────────────────────────────────────────────────────┘
        │  ledger.state()       → reconstructed agent state
        │  ledger.verify_chain() → True (or raises on tamper)
        │  ledger.detect_conflicts() → list of ConflictEntry
```

## Get started (30 seconds)

```bash
# 1 — Clone
git clone https://github.com/adu3110/agent-ledger

# 2 — Run the demo (no API key, no dependencies)
python python/ledger.py

# → LEDGER.md written
# → Total entries    : 22
# → Hash chain valid : True
# → Reconstructed state: root_cause, fix_approach, requires_migration

# 3 — TypeScript (zero npm dependencies)
npx ts-node typescript/src/ledger.ts
```

## Proof

**Demo run output — no API key, no dependencies:**

```
$ python python/ledger.py

[DiagnoserAgent] Planning…
[FixerAgent] Planning…
[ResolverAgent] 2 conflict(s) detected — resolving…

Ledger written to: LEDGER.md
Total entries    : 22
Hash chain valid : True

Reconstructed state:
  root_cause         : No idempotency check on webhook events
  fix_approach       : Store event_id in KV; skip if already processed
  requires_migration : yes   ← conflict resolved between agents
  final_answer       : Implement idempotency key check in webhook handler
```

**Tamper detection — modify any past entry:**

```python
# Flip one character in entry [0003]
ledger._entries[2].content["value"] = "TAMPERED"
ledger.verify_chain()
# → HashChainError: Chain broken at entry 3
#   expected=eedce4622769aeaf  got=1a7f2b8c3e9d4f01
```

## Three key operations

```python
from python.ledger import Ledger, AgentWriter

ledger = Ledger("LEDGER.md")
writer = AgentWriter(ledger, agent_name="MyAgent")

# Write entries
writer.plan("Search for the bug in payments.py")
result = call_tool("search_codebase", query="payment webhook")
writer.observation("search_codebase_result", result)
writer.answer("The bug is in payments.py line 42")

# 1. Reconstruct full agent state from replay
state = ledger.state()           # → {"search_codebase_result": {...}, ...}

# 2. Verify the SHA-256 chain (detect tampering)
valid = ledger.verify_chain()    # → True, or raises HashChainError

# 3. Find contradictory observations between agents
conflicts = ledger.detect_conflicts()  # → [ConflictEntry(...), ...]
```

## Compared to

agent-ledger uses **zero dependencies**, outputs **human-readable Markdown**, and makes every state reconstructable by replay.

| | Tamper-evident | Conflict detection | Replay | Human-readable | Dependencies |
|---|:---:|:---:|:---:|:---:|:---:|
| **agent-ledger** | ✅ SHA-256 | ✅ auto | ✅ | ✅ Markdown | ✗ zero |
| Shared dict / memory | ✗ | ✗ silent | ✗ | ✗ | varies |
| Message queue (Redis, RabbitMQ) | ✗ | ✗ | Partial | ✗ | heavy |
| LangGraph state | ✗ | ✗ | Partial | ✗ | LangChain |
| Custom logs | ✗ | ✗ | Manual | Partial | varies |

## When to use · When to skip

**Great fit if you…**
- run multi-agent systems and need to debug where reasoning drifted
- want a tamper-evident audit trail (compliance, financial, medical)
- need cross-agent state reconstruction without shared memory

**Skip it if you…**
- run a single agent with simple tool calls (a dict is fine)
- need real-time pub/sub between many agents (use a message queue)

## Contributing

```bash
git clone https://github.com/adu3110/agent-ledger
python python/ledger.py         # runs the demo, no dependencies
```

## License

MIT

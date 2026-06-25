# agent-ledger

Append-only, hash-chained coordination ledger for multi-agent AI systems. No vector database. No message queue. No shared memory. Agents communicate only through `LEDGER.md`.

Multi-agent systems are hard to debug because state lives in memory and reasoning is hidden in console logs. This protocol treats agent coordination like accounting — every action is an immutable, auditable transaction.

---

## The protocol

Every agent action is appended as a typed, timestamped, hash-chained entry:

```
[0001] PLAN         DiagnoserAgent   Diagnose: duplicate charges on webhook retry
[0002] TOOL_CALL    DiagnoserAgent   search_codebase(query="payment webhook")
[0003] OBSERVATION  DiagnoserAgent   search_codebase_result = {files: [...]}
[0004] TOOL_CALL    DiagnoserAgent   llm_reason("Why do duplicate charges occur?")
[0005] OBSERVATION  DiagnoserAgent   root_cause = "No idempotency check"
[0006] CHECKPOINT   DiagnoserAgent   ← snapshot current state for fast-forward replay

[0007] PLAN         FixerAgent       Design a fix for the idempotency gap
[0008] TOOL_CALL    FixerAgent       llm_reason("What is the minimal fix?")
[0009] OBSERVATION  FixerAgent       requires_migration = "no"
[0010] OBSERVATION  DiagnoserAgent   requires_migration = "yes"   ← CONFLICT

[0011] CONFLICT     ResolverAgent    key=requires_migration, A="no", B="yes"
[0012] RESOLUTION   ResolverAgent    ← LLM adjudicates, explains reasoning

[0013] ANSWER       FixerAgent       Store event_id as idempotency key...
```

**Agents never communicate directly.** They read the ledger to learn the current state, then write their next action.

---

## Hash chaining

Each entry includes a SHA-256 hash of its content plus the previous entry's hash:

```
hash[n] = SHA256( seq[n] | hash[n-1] | content[n] )[:16]
```

This makes the ledger tamper-evident — modifying any past entry breaks every hash that follows. `ledger.verify_chain()` catches it instantly.

---

## Three key operations

```python
ledger.state()              # replay all entries → reconstruct current agent state
ledger.verify_chain()       # check SHA-256 chain → detect tampered entries
ledger.detect_conflicts()   # find OBSERVATION entries with contradictory values
```

---

## Run

```bash
# Python
python python/ledger.py
# → writes python/LEDGER.md

# TypeScript
npx ts-node typescript/ledger.ts
# → writes typescript/LEDGER.md
```

API key is read automatically from `.env` or `.env.local` anywhere in the directory tree:

```
OPENAI_API_KEY=sk-...
LEDGER_MODEL=gpt-4o-mini    # optional
```

### Sample output

```
=================================================================
  State Machine Agent Ledger (gpt-4o-mini)
=================================================================
[DiagnoserAgent] Planning…
[FixerAgent] Planning…
[ResolverAgent] 2 conflict(s) detected — resolving…

Ledger written to: python/LEDGER.md
Total entries    : 22
Hash chain valid : True

Reconstructed state (from replay):
  root_cause:       No idempotency check on webhook events
  fix_approach:     Store event_id in KV; skip if already processed
  conflict_resolved: Resolution: The correct value depends on context...
  final_answer:     Implement a unique identifier for each payment request...
```

---

## LEDGER.md format

Every entry is human-readable markdown, git-diffable, and requires no tooling to inspect:

```markdown
## [0012] RESOLUTION  ·  ResolverAgent  ·  2026-06-25T05:47:13.021Z
<!-- hash:c39f6724c08323f3 -->
**resolution:** Adopting 'no' from FixerAgent (more specific, consistent with KV approach)
**reasoning:** The fix uses an existing KV store; no schema migration is needed.
```

---

## Entry types

| Type | Written by | Meaning |
|------|-----------|---------|
| `PLAN` | Any agent | Goal for this agent's current task |
| `TOOL_CALL` | Any agent | Tool invoked + result |
| `OBSERVATION` | Any agent | A key-value fact derived from tool output |
| `CHECKPOINT` | Any agent | Snapshot of full state at this point |
| `CONFLICT` | ResolverAgent | Two agents disagree on the same key |
| `RESOLUTION` | ResolverAgent | LLM-adjudicated resolution of a conflict |
| `ANSWER` | Any agent | Final answer to the original problem |

---

## Files

```
agent-ledger/
├── python/ledger.py        Ledger, Agent, ResolverAgent, hash chain, replay
└── typescript/ledger.ts    same protocol, stdlib crypto + https only
```

---

## Related concepts

- **Event sourcing** — the architectural pattern this is based on
- **Kafka / append-only logs** — same immutability guarantee, applied to agent state
- **OpenAI Swarm / LangGraph** — production frameworks solving the same coordination problem with heavier infrastructure

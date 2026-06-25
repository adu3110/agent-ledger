# agent-ledger

Append-only, hash-chained coordination ledger for multi-agent AI systems.

Instead of agents sharing fragile in-memory state, this protocol records every agent action as an immutable transaction in `LEDGER.md` — like event sourcing for agents. Any failure can be replayed line-by-line to find exactly where reasoning drifted.

## How it works

Agents communicate only by writing to / reading from the Ledger. Every entry is:

- **Typed** — one of `PLAN / TOOL_CALL / OBSERVATION / CONFLICT / RESOLUTION / CHECKPOINT / ANSWER`
- **Timestamped** — ISO 8601 with milliseconds
- **Hash-chained** — SHA-256(seq + prev_hash + content) detects tampering

```
DiagnoserAgent  →  PLAN
DiagnoserAgent  →  TOOL_CALL: search_codebase(...)
DiagnoserAgent  →  OBSERVATION: root_cause = "..."
DiagnoserAgent  →  CHECKPOINT  ← snapshot for fast-forward replay

FixerAgent      →  PLAN
FixerAgent      →  OBSERVATION: fix = "..."
FixerAgent      →  OBSERVATION: requires_migration = "no"
DiagnoserAgent  →  OBSERVATION: requires_migration = "yes"  ← CONFLICT detected

ResolverAgent   →  CONFLICT + RESOLUTION  ← LLM adjudicates

FixerAgent      →  ANSWER
```

## Run

```bash
# Python
python python/ledger.py
# → writes python/LEDGER.md

# TypeScript
npx ts-node typescript/ledger.ts
# → writes typescript/LEDGER.md
```

API key loaded automatically from `.env` / `.env.local`:

```bash
OPENAI_API_KEY=sk-... python python/ledger.py
```

## Features

| Feature | Method |
|---------|--------|
| Reconstruct current state | `ledger.state()` — replays all entries |
| Detect tampered entries | `ledger.verify_chain()` — SHA-256 chain |
| Find contradictions | `ledger.detect_conflicts()` — key-value conflicts |
| Debug past failures | `ledger.replay(up_to_seq=N)` — partial replay |

## Config

| Variable | Default | Meaning |
|----------|---------|---------|
| `OPENAI_API_KEY` | (required) | API key |
| `LEDGER_MODEL` | `gpt-4o-mini` | Model for agent reasoning |

## Dependencies

- Python: stdlib only (`hashlib`, `json`, `urllib`, `pathlib`)
- TypeScript: stdlib only (`fs`, `crypto`, `https`, `path`)

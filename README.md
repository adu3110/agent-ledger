# agent-ledger

> **22-entry, SHA-256 hash-chained audit log. Hash chain valid: True.**  
> Multi-agent systems fail silently — state lives in memory, reasoning in logs.  
> `agent-ledger` gives every action an immutable, tamper-evident record. Zero dependencies.

Agents communicate only through `LEDGER.md`. Every action is typed, timestamped, and hash-chained. Conflicts are automatically detected. The full state can be reconstructed from scratch by replaying the ledger. No shared memory. No message queue. No database.

```bash
git clone https://github.com/adu3110/agent-ledger
python python/ledger.py
# → LEDGER.md written. 22 entries. Hash chain valid: True
```

---

## See it work

```
$ python python/ledger.py

[DiagnoserAgent] Planning…
[FixerAgent] Planning…
[ResolverAgent] 2 conflict(s) detected — resolving…

Ledger written to: LEDGER.md
Total entries    : 22
Hash chain valid : True

Reconstructed state (from replay):
  root_cause     : No idempotency check on webhook events
  fix_approach   : Store event_id in KV; skip if already processed
  requires_migration : yes [conflict resolved]
  final_answer   : Implement idempotency key check in webhook handler
```

The output is a human-readable `LEDGER.md`:

```
[0001] PLAN         DiagnoserAgent     hash=8adecb7c6f006b85
[0002] TOOL_CALL    DiagnoserAgent     hash=4ae8e139316b4322
[0003] OBSERVATION  DiagnoserAgent     hash=eedce4622769aeaf
...
[0009] CHECKPOINT   DiagnoserAgent     hash=98e1077fc32ab600
[0010] PLAN         FixerAgent         hash=d2212d0570e2d77d
...
[0016] CONFLICT     ResolverAgent      hash=cd12c4e483c206c3
[0017] RESOLUTION   ResolverAgent      hash=10900ad19bce1edb
...
[0022] ANSWER       FixerAgent         hash=cb3fff0310c2feca
```

---

## Why LEDGER.md beats shared memory

| Property | Shared memory / logs | agent-ledger |
|----------|---------------------|--------------|
| Tamper detection | ✗ | ✓ SHA-256 chain |
| State reconstruction | ✗ manual | ✓ `ledger.state()` |
| Conflict detection | ✗ silent | ✓ raised as `CONFLICT` entry |
| Human readable | ✗ | ✓ Markdown |
| Git diff-able | ✗ | ✓ |
| Dependencies | varies | ✗ zero |

---

## Three key operations

```python
from python.ledger import Ledger

ledger = Ledger("LEDGER.md")

# 1. Reconstruct full state from all entries
state = ledger.state()        # → dict of all key/value observations

# 2. Verify the SHA-256 hash chain (detect tampering)
valid = ledger.verify_chain() # → True / raises on tampered entry

# 3. Find contradictory observations between agents
conflicts = ledger.detect_conflicts()  # → list of ConflictEntry
```

---

## The ledger protocol

Every agent writes typed entries:

| Entry type | Written by | Meaning |
|------------|-----------|---------|
| `PLAN` | Any agent | Goal statement for this agent's turn |
| `TOOL_CALL` | Any agent | A tool invocation (with args) |
| `OBSERVATION` | Any agent | Result of a tool call or LLM inference |
| `CHECKPOINT` | Any agent | Snapshot of current state for fast-forward replay |
| `CONFLICT` | Resolver | Two agents disagree on the same key |
| `RESOLUTION` | Resolver | LLM adjudication of a conflict |
| `ANSWER` | Any agent | Final task output |

Agents **never communicate directly** — they read the ledger to learn state, then write their next action.

---

## Hash chaining

```
hash[n] = SHA256( seq[n] | hash[n-1] | content[n] )[:16]
```

Modifying any past entry breaks every hash that follows. `ledger.verify_chain()` catches it instantly.

---

## Integrate into your agent

```python
from python.ledger import Ledger, AgentWriter

ledger = Ledger("LEDGER.md")
writer = AgentWriter(ledger, agent_name="MyAgent")

# Each action is one line in the ledger
writer.plan("Search for the bug in payments.py")
result = my_tool("search_codebase", query="payment webhook")
writer.observation("search_codebase_result", result)
writer.answer("The bug is in payments.py line 42")

print(ledger.state())       # → full reconstructed state
print(ledger.verify_chain()) # → True
```

---

## TypeScript version

```bash
npx ts-node typescript/src/ledger.ts
# → LEDGER.md
```

---

## Related

- [memcell-rl](https://github.com/adu3110/memcell-rl) — RL-native memory control for agents
- [stateful-agent-lab](https://github.com/adu3110/stateful-agent-lab) — typed memory, tool calls, trajectory scoring
- Paper: [Event Sourcing (Fowler)](https://martinfowler.com/eaaDev/EventSourcing.html) — the distributed systems pattern this implements for agents

---

## License

MIT

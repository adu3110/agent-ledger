"""
State Machine Agent Ledger — implemented from scratch.

What this demonstrates
----------------------
Multi-agent systems are hard to debug because state lives in memory or
scattered logs. The Ledger protocol records every agent action as an
immutable, append-only transaction to LEDGER.md — like event sourcing
for agents. Any failure can be replayed line-by-line to find exactly
where reasoning drifted.

Concepts
--------
- Agents communicate only by writing to / reading from the Ledger
- Every entry is a typed transaction: PLAN / TOOL_CALL / OBSERVATION /
  CONFLICT / RESOLUTION / CHECKPOINT / ANSWER
- Conflict detection: if two agents write contradictory states, the
  Ledger raises a ConflictEntry that a Resolver agent must adjudicate
- Replay: reprocess the Ledger entry-by-entry to reconstruct any past state
- Checkpoints: snapshot current state so replay can fast-forward

This is entirely stdlib — no LLM required to see the coordination protocol.
Swap _mock_llm_call for a real API call to power real agents.

Run
---
    python ledger.py

Output: LEDGER.md  (human-readable, git-diff friendly)
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any


# ──────────────────────────────────────────────────────────────────────────────
# Env-file loader (no python-dotenv required)
# ──────────────────────────────────────────────────────────────────────────────
def _load_env_files() -> None:
    here = Path(__file__).resolve().parent
    for directory in [here, *here.parents]:
        for name in (".env.local", ".env"):
            path = directory / name
            if path.is_file():
                with path.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, _, val = line.partition("=")
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = val


_load_env_files()

API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL   = os.environ.get("LEDGER_MODEL", "gpt-4o-mini")

if not API_KEY:
    raise SystemExit(
        "OPENAI_API_KEY not found.\n"
        "Set it in your environment or create a .env / .env.local file:\n"
        "  OPENAI_API_KEY=sk-..."
    )

LEDGER_FILE = Path(__file__).parent / "LEDGER.md"


# ──────────────────────────────────────────────────────────────────────────────
# Entry types
# ──────────────────────────────────────────────────────────────────────────────
class EntryType(str, Enum):
    PLAN        = "PLAN"
    TOOL_CALL   = "TOOL_CALL"
    OBSERVATION = "OBSERVATION"
    CONFLICT    = "CONFLICT"
    RESOLUTION  = "RESOLUTION"
    CHECKPOINT  = "CHECKPOINT"
    ANSWER      = "ANSWER"


@dataclass
class LedgerEntry:
    seq:       int
    timestamp: str
    agent:     str
    etype:     EntryType
    content:   dict[str, Any]
    hash:      str = ""          # SHA-256 of (seq + prev_hash + content)

    def compute_hash(self, prev_hash: str) -> str:
        payload = f"{self.seq}|{prev_hash}|{json.dumps(self.content, sort_keys=True)}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_markdown(self) -> str:
        lines = [
            f"## [{self.seq:04d}] {self.etype.value}  ·  {self.agent}  ·  {self.timestamp}",
            f"<!-- hash:{self.hash} -->",
        ]
        for k, v in self.content.items():
            if isinstance(v, str):
                lines.append(f"**{k}:** {v}")
            else:
                lines.append(f"**{k}:**\n```json\n{json.dumps(v, indent=2)}\n```")
        lines.append("")
        return "\n".join(lines) + "\n---\n"


# ──────────────────────────────────────────────────────────────────────────────
# Ledger — append-only, hash-chained
# ──────────────────────────────────────────────────────────────────────────────
class Ledger:
    def __init__(self, path: Path = LEDGER_FILE) -> None:
        self.path    = path
        self.entries: list[LedgerEntry] = []
        self._prev_hash = "genesis"

        if not path.exists():
            path.write_text(
                "# Agent Ledger\n\nAppend-only transaction log. Do not edit manually.\n\n---\n\n",
                encoding="utf-8",
            )

    def append(
        self,
        agent: str,
        etype: EntryType,
        content: dict[str, Any],
    ) -> LedgerEntry:
        seq   = len(self.entries) + 1
        ts    = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        entry = LedgerEntry(seq=seq, timestamp=ts, agent=agent, etype=etype, content=content)
        entry.hash     = entry.compute_hash(self._prev_hash)
        self._prev_hash = entry.hash

        self.entries.append(entry)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(entry.to_markdown())

        return entry

    def state(self) -> dict[str, Any]:
        """Reconstruct current agent state by replaying all entries."""
        s: dict[str, Any] = {}
        for e in self.entries:
            if e.etype == EntryType.CHECKPOINT:
                s = dict(e.content.get("snapshot", {}))
            elif e.etype == EntryType.OBSERVATION:
                key = e.content.get("key", e.agent)
                s[key] = e.content.get("value")
            elif e.etype == EntryType.ANSWER:
                s["final_answer"] = e.content.get("answer")
            elif e.etype == EntryType.RESOLUTION:
                s["conflict_resolved"] = e.content.get("resolution")
        return s

    def replay(self, up_to_seq: int | None = None) -> list[LedgerEntry]:
        """Return entries up to (and including) seq, for replay / debugging."""
        entries = self.entries if up_to_seq is None else self.entries[:up_to_seq]
        return entries

    def verify_chain(self) -> bool:
        """Verify hash chain integrity — detects tampered entries."""
        prev = "genesis"
        for e in self.entries:
            expected = e.compute_hash(prev)
            if expected != e.hash:
                return False
            prev = e.hash
        return True

    def detect_conflicts(self) -> list[tuple[LedgerEntry, LedgerEntry]]:
        """Find pairs of OBSERVATION entries that claim contradictory values for the same key."""
        obs: dict[str, LedgerEntry] = {}
        conflicts: list[tuple[LedgerEntry, LedgerEntry]] = []
        for e in self.entries:
            if e.etype != EntryType.OBSERVATION:
                continue
            key = e.content.get("key", "")
            if key in obs and obs[key].content.get("value") != e.content.get("value"):
                conflicts.append((obs[key], e))
            obs[key] = e
        return conflicts


# ──────────────────────────────────────────────────────────────────────────────
# LLM interface
# ──────────────────────────────────────────────────────────────────────────────
def _llm_call(prompt: str, system: str = "You are a concise technical expert. Answer in 1-2 sentences.") -> str:
    """Call the OpenAI chat completions API and return the reply text."""
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens":  200,
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()


# ──────────────────────────────────────────────────────────────────────────────
# Agent base class
# ──────────────────────────────────────────────────────────────────────────────
class Agent:
    def __init__(self, name: str, ledger: Ledger) -> None:
        self.name   = name
        self.ledger = ledger

    def plan(self, goal: str) -> LedgerEntry:
        return self.ledger.append(self.name, EntryType.PLAN, {"goal": goal})

    def call_tool(self, tool: str, args: dict) -> LedgerEntry:
        result = self._tool_dispatch(tool, args)
        entry  = self.ledger.append(
            self.name, EntryType.TOOL_CALL,
            {"tool": tool, "args": args, "result": result},
        )
        self.observe(f"{tool}_result", result)
        return entry

    def observe(self, key: str, value: Any) -> LedgerEntry:
        return self.ledger.append(self.name, EntryType.OBSERVATION, {"key": key, "value": value})

    def answer(self, answer: str) -> LedgerEntry:
        return self.ledger.append(self.name, EntryType.ANSWER, {"answer": answer})

    def checkpoint(self) -> LedgerEntry:
        snap = self.ledger.state()
        return self.ledger.append(self.name, EntryType.CHECKPOINT, {"snapshot": snap})

    def _tool_dispatch(self, tool: str, args: dict) -> Any:
        if tool == "search_codebase":
            # Static result — real impl would call a code-search API or grep
            return {"files": ["services/payments.py", "webhooks/stripe.py"]}
        if tool == "read_file":
            # Static result — real impl would open the file
            return {"content": "def process_payment(event): charge(event.amount)"}
        if tool == "llm_reason":
            return _llm_call(args.get("prompt", ""))
        return {"status": "ok"}


class ResolverAgent(Agent):
    """Specialised agent that mediates CONFLICT entries."""

    def resolve(self, conflict: tuple[LedgerEntry, LedgerEntry]) -> LedgerEntry:
        a, b = conflict
        reasoning = _llm_call(
            f"Two agents disagree on key '{a.content.get('key')}': "
            f"'{a.content.get('value')}' vs '{b.content.get('value')}'. "
            f"Which is correct and why? Reply in one sentence."
        )
        resolution = f"Resolution: {reasoning}"
        self.ledger.append(
            self.name,
            EntryType.CONFLICT,
            {
                "key":     a.content.get("key"),
                "agent_a": a.agent,
                "value_a": str(a.content.get("value")),
                "agent_b": b.agent,
                "value_b": str(b.content.get("value")),
            },
        )
        return self.ledger.append(
            self.name,
            EntryType.RESOLUTION,
            {"resolution": resolution, "reasoning": reasoning},
        )


# ──────────────────────────────────────────────────────────────────────────────
# Demo: two agents coordinate to diagnose + fix a payments bug
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    if LEDGER_FILE.exists():
        LEDGER_FILE.unlink()      # fresh ledger for demo

    ledger   = Ledger()
    diagnoser = Agent("DiagnoserAgent", ledger)
    fixer     = Agent("FixerAgent",     ledger)
    resolver  = ResolverAgent("ResolverAgent", ledger)

    problem = "Duplicate charges occur when a Stripe webhook is retried."
    print("=" * 65)
    print("  State Machine Agent Ledger")
    print("=" * 65)
    print(f"\nProblem: {problem}\n")

    # ── DiagnoserAgent ────────────────────────────────────────────────────────
    print("[DiagnoserAgent] Planning…")
    diagnoser.plan(f"Diagnose: {problem}")
    diagnoser.call_tool("search_codebase", {"query": "payment webhook"})
    diagnoser.call_tool("read_file", {"path": "webhooks/stripe.py"})
    diagnoser.call_tool("llm_reason", {
        "prompt": "Why do duplicate charges occur in a webhook-based payments service?"
    })
    diagnoser.observe("root_cause", "No idempotency check on webhook events")
    diagnoser.checkpoint()

    # ── FixerAgent ────────────────────────────────────────────────────────────
    print("[FixerAgent] Planning…")
    fixer.plan("Design a fix for the idempotency gap.")
    fixer.call_tool("llm_reason", {
        "prompt": "What is the minimal fix for duplicate webhook charges that requires no schema migration?"
    })
    fixer.observe("fix_approach", "Store event_id in KV; skip if already processed")

    # Introduce a deliberate conflict to demonstrate resolution
    fixer.observe("requires_migration", "no")
    diagnoser.observe("requires_migration", "yes")   # contradicts FixerAgent

    # ── Conflict detection & resolution ───────────────────────────────────────
    conflicts = ledger.detect_conflicts()
    if conflicts:
        print(f"\n[ResolverAgent] {len(conflicts)} conflict(s) detected — resolving…")
        for c in conflicts:
            resolver.resolve(c)

    # ── Final answer ──────────────────────────────────────────────────────────
    final = fixer.call_tool("llm_reason", {
        "prompt": "Write a final 2-sentence implementation plan for an idempotency fix in a payments webhook handler."
    })
    answer_text = ledger.state().get("llm_reason_result", "See ledger for details.")
    fixer.answer(str(answer_text))

    # ── Report ────────────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  Ledger written to: {LEDGER_FILE.resolve()}")
    print(f"  Total entries    : {len(ledger.entries)}")
    print(f"  Hash chain valid : {ledger.verify_chain()}")
    print(f"{'='*65}")

    state = ledger.state()
    print("\nReconstructed state (from replay):")
    for k, v in state.items():
        print(f"  {k}: {v}")

    print(f"\n{'='*65}")
    print("  Replay (all entries):")
    print(f"{'='*65}")
    for e in ledger.replay():
        print(f"  [{e.seq:04d}] {e.etype.value:<12} {e.agent:<18} hash={e.hash}")

    print(f"\nOpen {LEDGER_FILE} to read the full human-readable log.")


if __name__ == "__main__":
    main()

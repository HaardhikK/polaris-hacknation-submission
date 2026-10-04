"""Gatekeeper for one ``codex_run.sh`` call: the events log and the answer.

Fails closed. A run passes only if every event and item type is on the
allowlist (no tool of any kind), the answer parses, and it matches the step's
JSON schema. Called by ``codex_run.sh``; exit code 0 means clean.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

ALLOWED_EVENT_TYPES = {
    "thread.started",
    "turn.started",
    "turn.completed",
    "item.started",
    "item.updated",
    "item.completed",
}
ALLOWED_ITEM_TYPES = {"agent_message", "reasoning"}


def check_events(events_path: Path) -> list[str]:
    problems: list[str] = []
    for n, line in enumerate(events_path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f"line {n}: not JSON")
            continue
        event_type = event.get("type")
        if event_type not in ALLOWED_EVENT_TYPES:
            problems.append(f"line {n}: event type {event_type!r} not allowed")
        item_type = (event.get("item") or {}).get("type")
        if item_type is not None and item_type not in ALLOWED_ITEM_TYPES:
            problems.append(f"line {n}: item type {item_type!r} not allowed (tool use)")
    if not problems and "turn.completed" not in events_path.read_text():
        problems.append("no turn.completed event: the run did not finish")
    return problems


def check_answer(answer_path: Path, schema_path: Path) -> list[str]:
    try:
        answer = json.loads(answer_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"answer: {exc.__class__.__name__}"]
    schema = json.loads(schema_path.read_text())
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(answer), key=str)
    return [f"answer: {e.message}" for e in errors]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: codex_check <events.jsonl> <answer.json> <schema.json>", file=sys.stderr)
        return 2
    events, answer, schema = (Path(a) for a in argv)
    problems = check_events(events) + check_answer(answer, schema)
    for problem in problems:
        print(f"codex_check: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

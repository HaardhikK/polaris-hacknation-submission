import json
from pathlib import Path

from pipeline.codex_check import check_answer, check_events

SCHEMA = Path(__file__).parent.parent / "prompts" / "dry_run.schema.json"


def events_file(tmp_path, lines):
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


def test_clean_log_passes(tmp_path):
    path = events_file(
        tmp_path,
        [
            {"type": "thread.started"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "reasoning"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}},
            {"type": "turn.completed"},
        ],
    )
    assert check_events(path) == []


def test_unknown_event_or_item_type_fails_closed(tmp_path):
    path = events_file(
        tmp_path,
        [
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "custom_tool_call"}},
            {"type": "error", "message": "x"},
            {"type": "turn.completed"},
        ],
    )
    problems = check_events(path)
    assert any("custom_tool_call" in p for p in problems)
    assert any("'error'" in p for p in problems)


def test_unfinished_turn_fails(tmp_path):
    path = events_file(tmp_path, [{"type": "turn.started"}])
    assert check_events(path) == ["no turn.completed event: the run did not finish"]


def test_answer_is_validated_against_the_schema(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"items": [{"id": "a", "word_count": 2}]}))
    assert check_answer(good, SCHEMA) == []
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"items": [{"id": "a", "extra": 1}]}))
    assert check_answer(bad, SCHEMA)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert check_answer(broken, SCHEMA) == ["answer: JSONDecodeError"]

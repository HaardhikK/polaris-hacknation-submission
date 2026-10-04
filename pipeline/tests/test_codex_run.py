"""codex_run.sh is exercised with a stub `codex` in a temp folder, so the tests run offline
and never touch node_modules. The real end-to-end call is `make codex-dry-run`.
"""

import json
import os
import stat
import subprocess
import uuid
from pathlib import Path

import pytest

from pipeline.schema import Provenance

REPO = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO / "pipeline" / "codex_run.sh"
CLEAN_EVENTS = [
    {"type": "thread.started", "thread_id": "t"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "i", "type": "agent_message", "text": "{}"}},
    {"type": "turn.completed", "usage": {}},
]


def stub_codex(tmp_path: Path, events: list[dict], answer: dict | None) -> Path:
    """A fake codex binary that records argv and env and writes canned output."""
    stub = tmp_path / "codex"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "--version" ]; then echo codex-cli 0.0.0-fake; exit 0; fi\n'
        f"printf '%s\\n' \"$@\" > '{tmp_path}/argv.txt'\n"
        f"env > '{tmp_path}/env.txt'\n"
        "cat > /dev/null\n"
        "out=''; prev=''\n"
        'for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done\n'
        + (f"printf '%s' '{json.dumps(answer)}' > \"$out\"\n" if answer is not None else "")
        + "".join(f"echo '{json.dumps(e)}'\n" for e in events)
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub


@pytest.fixture
def work_out():
    """A per-test output path inside the repo's gitignored work/ folder."""
    folder = REPO / "work" / f"test-{uuid.uuid4().hex}"
    yield folder / "out.json"
    if folder.exists():
        for child in folder.iterdir():
            child.unlink()
        folder.rmdir()


def run(tmp_path: Path, stub: Path, out: str, **extra_env):
    runs_dir = tmp_path / "runs"
    env = {**os.environ, "CODEX_RUNS_DIR": str(runs_dir), "CODEX_BIN": str(stub), **extra_env}
    proc = subprocess.run(
        [str(SCRIPT), "dry_run", str(REPO / "pipeline/prompts/dry_run.input.json"), out],
        env=env,
        capture_output=True,
        text=True,
        cwd=tmp_path,  # not the repo root: the script must find its own files
    )
    return proc, runs_dir


def test_clean_run_writes_answer_and_provenance_with_a_stripped_environment(tmp_path, work_out):
    stub = stub_codex(tmp_path, CLEAN_EVENTS, {"items": [{"id": "a", "word_count": 1}]})
    proc, runs_dir = run(
        tmp_path, stub, str(work_out), OPENAI_API_KEY="sk-never-reaches-codex", NCBI_EMAIL="x@y.org"
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(work_out.read_text())["items"][0]["id"] == "a"

    argv = (tmp_path / "argv.txt").read_text().split("\n")
    for flag in (
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "read-only",
        "approval_policy=never",
        "web_search=disabled",
        "shell_environment_policy.inherit=none",
        "--output-schema",
        "gpt-6-astra",
    ):
        assert flag in argv, flag

    env_seen = dict(line.split("=", 1) for line in (tmp_path / "env.txt").read_text().splitlines())
    assert "OPENAI_API_KEY" not in env_seen
    assert "NCBI_EMAIL" not in env_seen
    assert set(env_seen) <= {"PATH", "HOME", "CODEX_HOME", "PWD", "SHLVL", "_", "OLDPWD"}

    meta = json.loads(next(runs_dir.glob("*.meta.json")).read_text())
    provenance = Provenance.model_validate(meta)
    assert provenance.step == "dry_run"
    assert provenance.tool_version == "0.0.0-fake"


@pytest.mark.parametrize(
    "tool", ["command_execution", "file_change", "web_search", "mcp_tool_call", "collab_tool_call"]
)
def test_any_tool_item_rejects_the_whole_batch(tmp_path, work_out, tool):
    events = (
        CLEAN_EVENTS[:2] + [{"type": "item.completed", "item": {"type": tool}}] + CLEAN_EVENTS[3:]
    )
    proc, _ = run(tmp_path, stub_codex(tmp_path, events, {"items": []}), str(work_out))
    assert proc.returncode == 3
    assert "REJECTED" in proc.stderr
    assert not work_out.exists()


def test_answer_not_matching_the_schema_is_rejected(tmp_path, work_out):
    proc, _ = run(
        tmp_path, stub_codex(tmp_path, CLEAN_EVENTS, {"items": [{"id": "a"}]}), str(work_out)
    )
    assert proc.returncode == 3
    assert "word_count" in proc.stderr


def test_missing_answer_is_rejected(tmp_path, work_out):
    proc, _ = run(tmp_path, stub_codex(tmp_path, CLEAN_EVENTS, None), str(work_out))
    assert proc.returncode == 3


@pytest.mark.parametrize(
    "out", ["pipeline/seed/claims.yaml", "work/../pipeline/seed/claims.yaml", "/tmp/out.json"]
)
def test_output_outside_work_or_data_raw_is_refused(tmp_path, out):
    stub = stub_codex(tmp_path, CLEAN_EVENTS, {"items": []})
    proc, _ = run(tmp_path, stub, out)
    assert proc.returncode == 2
    assert not (tmp_path / "argv.txt").exists()  # codex was never called


@pytest.mark.parametrize("runs_dir", [None, "data/raw/codex-runs", "data/raw/../raw/codex-runs"])
def test_stub_binary_is_refused_unless_runs_dir_is_outside_data(tmp_path, runs_dir):
    stub = stub_codex(tmp_path, CLEAN_EVENTS, {"items": []})
    env = {**os.environ, "CODEX_BIN": str(stub)}
    env.pop("CODEX_RUNS_DIR", None)
    if runs_dir:
        env["CODEX_RUNS_DIR"] = runs_dir
    proc = subprocess.run(
        [str(SCRIPT), "dry_run", str(REPO / "pipeline/prompts/dry_run.input.json"), "work/x.json"],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert proc.returncode == 2
    assert "CODEX_RUNS_DIR" in proc.stderr
    assert not (tmp_path / "argv.txt").exists()


def test_real_codex_link_is_untouched_by_the_suite():
    link = REPO / "node_modules" / ".bin" / "codex"
    assert link.is_symlink()
    assert link.resolve().name == "codex.js"


def test_usage_error_without_three_arguments():
    proc = subprocess.run([str(SCRIPT), "dry_run"], capture_output=True, text=True)
    assert proc.returncode == 2

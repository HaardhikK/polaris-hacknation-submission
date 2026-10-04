"""``make critique`` (Codex handoff 5): one ``codex_run.sh`` call per screened line.

Builds the batch from the funnel result, runs the locked-down script, reads its provenance
sidecar, post-checks every sentence and commits only the checked text to
``pipeline/screen/cache/critique.json``. The cache binds the text to its run: the sidecar
must name this step, and ``items_sha256`` (canonical JSON of the checked items and the
provenance; a guard against accidental edits, not a signature) is written here and verified
again by ``make screen``. A rejected or missing run is recorded by a reason code, so the cards
ship with evidence only; nothing is invented.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from pipeline.fetch import REPO
from pipeline.schema import Provenance
from pipeline.screen import funnel, postcheck
from pipeline.screen.batches import BATCH_DIR, write_batch
from pipeline.screen.build import (
    CRITIQUE_CACHE,
    items_sha256,
    load_evidence,
    load_graph,
    load_pool,
    pool_names,
    screen_lines,
)
from pipeline.screen.config import CRITIQUE_STEP

RUNS_DIR = REPO / "data" / "raw" / "codex-runs"
REJECTED = "rejected_by_code_check"  # a reason code; build.py maps it to its fixed sentence


def run_line(batch: Path) -> tuple[dict, Provenance] | tuple[None, str]:
    """One codex_run.sh call. Returns (answer, provenance) or (None, reason)."""
    out = BATCH_DIR / batch.name.replace(".input.json", ".out.json")
    proc = subprocess.run(
        [str(REPO / "pipeline" / "codex_run.sh"), CRITIQUE_STEP, str(batch), str(out)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    if proc.returncode != 0:
        return None, REJECTED
    words = proc.stdout.strip().split()
    if len(words) < 3 or words[0] != "codex_run:":
        return None, REJECTED
    meta = json.loads((RUNS_DIR / f"{words[2]}.meta.json").read_text())
    provenance = Provenance.model_validate(meta)
    if provenance.step != CRITIQUE_STEP or provenance.agent != "codex":
        return None, REJECTED
    return json.loads(out.read_text()), provenance


def main() -> int:
    graph = load_graph()
    pool = load_pool()
    evidence = load_evidence()
    lines, _ = screen_lines(graph)
    names = pool_names(pool)
    approved_names = pool.get("approved_names", [])
    titles = evidence.get("titles", {})  # shown to the model, never a fact of the post-check
    cache = {"lines": {}}
    for line in lines:
        result = funnel.screen_line(line, pool, evidence)
        if result["status"] != "screened" or not result["cards"]:
            print(f"{line['key']}: no cards to critique")
            continue
        batch = write_batch(result, titles)
        answer, provenance = run_line(batch)
        if answer is None:
            cache["lines"][line["key"]] = {"unavailable": provenance}
            print(f"{line['key']}: {provenance}")
            continue
        checked, report = postcheck.check_answer(
            answer, result["cards"], line, names, approved_names
        )
        items = {k: checked[k] for k in sorted(checked)}
        provenance_json = json.loads(provenance.model_dump_json())
        cache["lines"][line["key"]] = {
            "provenance": provenance_json,
            "items": items,
            "items_sha256": items_sha256(items, provenance_json),
            "report": dict(sorted(report.items())),
        }
        print(f"{line['key']}: {dict(sorted(report.items()))}")
    CRITIQUE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(cache, indent=1, sort_keys=True, ensure_ascii=False)
    CRITIQUE_CACHE.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

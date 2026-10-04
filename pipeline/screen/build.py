"""``make screen``: ``web/public/screen.json`` from committed files only. No network, no model.

Refuses to build when ``graph.json`` is not real data, when a cache lacks its release or
``retrieved`` date, when any input path lies under ``tests/``, or when the committed critique
does not match its own digest or names another step. A critique whose facts changed since the
model run (the batch no longer hashes to the run's ``input_manifest_sha256``) is dropped with
that reason, never shown. The committed critique is post-checked again here, so whatever is in
the cache, no sentence reaches the file without passing the code check. Output is
byte-reproducible (sorted keys, no timestamps).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from pydantic import ValidationError

from pipeline.fetch import REPO
from pipeline.schema import Direction, Provenance
from pipeline.screen import funnel, postcheck
from pipeline.screen.batches import batch_sha256
from pipeline.screen.config import (
    ABSENT_LINE_GLOSS,
    ALREADY_STUDIED_CAPTION,
    CRITIQUE_REASONS,
    CRITIQUE_STEP,
    DIRECTION_FILTER_NOTE,
    DOUBT_KIND_LABELS,
    EVIDENCE_READ,
    FAMILY_COVERAGE_NOTE,
    FAMILY_DIRECTION_NOTE,
    FAMILY_LABEL,
    HYPOTHESIS_LABEL,
    INTERSTITIAL,
    INTERSTITIAL_BACK,
    INTERSTITIAL_CONTINUE,
    NEW_CANDIDATES_NOTE,
    NEXT_TEST_LABELS,
    ORDERING_RULE,
    PROVENANCE_MODELS,
    PUBMED_QUERY_NOTE,
    REMOVED_COUNTS_NOTE,
    RULE_VERSION,
    SANITY_CHECK_NOTE,
    SCREEN_LINE_GENES,
    SCREEN_LINE_KEYS,
    SCREEN_LINE_LABELS,
    SODIUM_CHANNEL_FAMILY,
    SOURCES,
    TARGET_CAPTION,
    TARGET_LEVEL,
)
from pipeline.screen.evidence import EVIDENCE_CACHE
from pipeline.screen.models import Screen
from pipeline.screen.opentargets import CACHE_DIR, POOL_CACHE

GRAPH = REPO / "web" / "public" / "graph.json"
SCREEN_OUT = REPO / "web" / "public" / "screen.json"
CRITIQUE_CACHE = CACHE_DIR / "critique.json"
BADGE = "Found by AI, checked by code"
MEDICATION_WARNING = (
    "Not medical advice. Never change or stop a medication without your child's neurologist."
)
# Researcher-page gloss per direction: states the mechanism without clinical wording.
GLOSS = {
    Direction.GAIN.value: "gain of function: the channel is too active",
    Direction.LOSS.value: "loss of function: the channel is not active enough",
}
CRITIQUE_MISSING = CRITIQUE_REASONS["no_run"]
CRITIQUE_NO_ITEM = CRITIQUE_REASONS["no_item"]
CRITIQUE_STALE = CRITIQUE_REASONS["facts_changed"]
# Provenance strings are identifiers, never prose: a known model name, a version, a run id.
PROVENANCE_SHAPES = {
    "model": re.compile("^(?:" + "|".join(re.escape(m) for m in sorted(PROVENANCE_MODELS)) + ")$"),
    "tool_version": re.compile(r"^\d+\.\d+\.\d+$"),
    "extractor_run_id": re.compile(r"^\d{8}T\d{6}Z-critique_candidates-\d+$"),
}


class BuildRefused(RuntimeError):
    """The build must not happen with these inputs; the message says why."""


def refuse_test_paths(*paths: Path) -> None:
    for path in paths:
        if "tests" in path.resolve().parts:
            raise BuildRefused(f"input under tests/ is never built into the site: {path.name}")


def load_graph(path: Path = GRAPH) -> dict:
    graph = json.loads(path.read_text())
    if (graph.get("meta") or {}).get("source") != "real":
        raise BuildRefused("graph.json meta.source is not 'real'")
    return graph


def load_pool(path: Path = POOL_CACHE) -> dict:
    pool = json.loads(path.read_text())
    if not pool.get("release") or not pool.get("retrieved"):
        raise BuildRefused("drug pool cache lacks its Open Targets release or retrieved date")
    if not pool.get("approved_total_method") or not pool.get("chembl_version"):
        raise BuildRefused("drug pool cache lacks its approved-total method or ChEMBL version")
    return pool


def load_evidence(path: Path = EVIDENCE_CACHE) -> dict:
    evidence = json.loads(path.read_text())
    if not evidence.get("retrieved"):
        raise BuildRefused("evidence cache lacks its retrieved date")
    return evidence


def items_sha256(items: dict, provenance: dict) -> str:
    """Canonical-JSON digest of the checked items and their provenance: a guard against
    accidental edits of the cache (unkeyed, so not a signature)."""
    payload = {"items": items, "provenance": provenance}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def check_provenance(key: str, raw: object) -> Provenance:
    """A valid, identifier-shaped provenance of this step, or a refusal."""
    try:
        provenance = Provenance.model_validate(raw)
    except ValidationError as exc:
        raise BuildRefused(f"critique for {key} has no valid provenance") from exc
    if provenance.step != CRITIQUE_STEP or provenance.agent != "codex":
        raise BuildRefused(f"critique for {key} comes from another step or agent")
    for field, shape in PROVENANCE_SHAPES.items():
        if not shape.match(getattr(provenance, field)):
            raise BuildRefused(f"critique for {key} has a provenance {field} that is not an id")
    return provenance


def load_critique(path: Path = CRITIQUE_CACHE) -> dict:
    """The committed critique, refused unless every run is bound to this step and its digest
    and every unavailable line carries a known reason code."""
    if not path.exists():
        return {}
    lines = json.loads(path.read_text()).get("lines", {})
    for key, cached in lines.items():
        if "items" not in cached:
            if cached.get("unavailable") not in CRITIQUE_REASONS:
                raise BuildRefused(f"critique for {key} has an unknown unavailable reason")
            continue
        check_provenance(key, cached.get("provenance"))
        if cached.get("items_sha256") != items_sha256(cached["items"], cached["provenance"]):
            raise BuildRefused(f"critique for {key} does not match its items_sha256")
    return lines


def _graph_line_rows(graph: dict) -> list[dict]:
    lines = graph.get("lines") or []
    if isinstance(lines, dict):
        lines = [{"key": k, **v} for k, v in lines.items()]
    return [row for row in lines if isinstance(row, dict) and row.get("key")]


def known_direction_evidence() -> dict[str, dict | None]:
    """Fallback when graph.json carries no ``direction_evidence``: the engine's own rule."""
    from pipeline.seed_check import load_seed
    from pipeline.transfer import direction_support, known_direction, load_accepted_claims

    seed, _ = load_seed()
    claims = load_accepted_claims()
    out: dict[str, dict | None] = {}
    for line in seed.lines:
        direction = known_direction(line, claims)
        support = (
            direction_support(line, claims) if direction in (Direction.GAIN, Direction.LOSS) else []
        )
        out[line.key] = (
            {"level": "checked by code", "pmid": support[0].pmid, "variant": support[0].variant}
            if support
            else None
        )
    return out


def screen_lines(graph: dict) -> tuple[list[dict], str]:
    """Every line the screen reports on, with its direction evidence, and where that came from.

    Scope lines come first in the fixed order (a scope line missing from ``graph.json`` is
    listed with ``in_graph: False`` so it is refused with that reason); every other graph line
    follows and is refused as not a channel line or out of scope.
    """
    rows = {r["key"]: r for r in _graph_line_rows(graph)}
    source = "graph_direction_evidence"
    if not rows or not any("direction_evidence" in r for r in rows.values()):
        source = "known_direction"
        from pipeline.seed_check import load_seed

        seed, _ = load_seed()
        fallback = known_direction_evidence()
        rows = {
            line.key: {
                "key": line.key,
                "gene": line.gene,
                "mechanism": line.mechanism,
                "mechanism_family": line.mechanism_family.value,
                "direction": line.direction.value,
                "label": line.label,
                "direction_evidence": fallback.get(line.key),
            }
            for line in seed.lines
        }
    lines = []
    for key in [*SCREEN_LINE_KEYS, *(k for k in rows if k not in SCREEN_LINE_KEYS)]:
        row = rows.get(key)
        if row is None:
            lines.append(
                {
                    "key": key,
                    "gene": SCREEN_LINE_GENES[key],
                    "mechanism": None,
                    "mechanism_family": None,
                    "direction": Direction.UNKNOWN.value,
                    "label": SCREEN_LINE_LABELS[key],
                    "gloss": ABSENT_LINE_GLOSS,
                    "direction_evidence": None,
                    "in_graph": False,
                }
            )
            continue
        lines.append(
            {
                "key": key,
                "gene": row["gene"],
                "mechanism": row.get("mechanism"),
                "mechanism_family": row.get("mechanism_family"),
                "direction": row.get("direction"),
                "label": row.get("label") or key,
                "gloss": GLOSS.get(row.get("direction"), row.get("gloss") or key),
                "direction_evidence": _strip_evidence(row.get("direction_evidence")),
                "in_graph": True,
            }
        )
    return lines, source


def _strip_evidence(evidence: object) -> dict | None:
    if not isinstance(evidence, dict) or not evidence.get("pmid"):
        return None
    return {
        "level": str(evidence.get("level") or "checked by code"),
        "pmid": str(evidence["pmid"]),
        "variant": evidence.get("variant"),
    }


def pool_names(pool: dict) -> dict[str, set[str]]:
    return {d["drug_id"]: {d["name"], *d.get("synonyms", [])} for d in pool["drugs"]}


def _unavailable(line: dict, code: str) -> None:
    """Every card gets the fixed sentence for a reason code; free text never reaches the file."""
    for card in line["cards"]:
        card["critique"] = {"status": "not_available", "reason": CRITIQUE_REASONS[code]}


def attach_critique(
    line: dict, cached: dict | None, names: dict, titles: dict, approved_names: list[str]
) -> None:
    """Add the post-checked critique to each card, or the reason there is none."""
    if not cached or "items" not in cached:
        _unavailable(line, (cached or {}).get("unavailable") or "no_run")
        return
    provenance = check_provenance(line["key"], cached["provenance"])
    if provenance.input_manifest_sha256 != batch_sha256(line, titles):
        _unavailable(line, "facts_changed")
        return
    provenance_json = json.loads(provenance.model_dump_json())
    answer = {
        "items": [
            {
                "drug_id": drug_id,
                "why": item.get("why", []),
                "doubts": item.get("doubts", [])
                + [{"text": t, "pmid": None} for t in item.get("unchecked_reasoning", [])],
                "next_test": item.get("next_test"),
            }
            for drug_id, item in cached["items"].items()
        ]
    }
    checked, _ = postcheck.check_answer(answer, line["cards"], line, names, approved_names)
    for card in line["cards"]:
        fields = checked.get(card["drug_id"])
        if fields is None:
            card["critique"] = {"status": "not_available", "reason": CRITIQUE_NO_ITEM}
        else:
            card["critique"] = {
                "status": "checked_by_code",
                "provenance": provenance_json,
                "evidence_read": EVIDENCE_READ,
                **fields,
            }


def studies_found(evidence: dict) -> int:
    return sum(len(pair.get("studies", [])) for pair in evidence.get("pairs", {}).values())


def build(
    graph_path: Path = GRAPH,
    pool_path: Path = POOL_CACHE,
    evidence_path: Path = EVIDENCE_CACHE,
    critique_path: Path = CRITIQUE_CACHE,
) -> Screen:
    refuse_test_paths(graph_path, pool_path, evidence_path, critique_path)
    graph = load_graph(graph_path)
    pool = load_pool(pool_path)
    evidence = load_evidence(evidence_path)
    critique = load_critique(critique_path)
    lines, source = screen_lines(graph)
    names = pool_names(pool)
    approved_names = list(pool.get("approved_names", []))
    results = []
    for line in lines:
        result = funnel.screen_line(line, pool, evidence)
        if result["status"] == "screened":
            attach_critique(
                result,
                critique.get(line["key"]),
                names,
                evidence.get("titles", {}),
                approved_names,
            )
        results.append(result)
    in_family, _ = funnel.family_filter(funnel.approved_only(pool["drugs"]), SODIUM_CHANNEL_FAMILY)
    effects = funnel.family_effects(in_family, SODIUM_CHANNEL_FAMILY)
    return Screen.model_validate(
        {
            "meta": {
                "source": "real",
                "open_targets_release": pool["release"],
                "retrieved": pool["retrieved"],
                "evidence_retrieved": evidence["retrieved"],
                "rule_version": RULE_VERSION,
                "family_label": FAMILY_LABEL,
                "family_genes": sorted(SODIUM_CHANNEL_FAMILY),
                "target_level": TARGET_LEVEL,
                "target_caption": TARGET_CAPTION,
                "direction_source": source,
                "direction_filter_note": DIRECTION_FILTER_NOTE,
                "family_effects": effects,
                "family_direction_note": FAMILY_DIRECTION_NOTE.format(
                    family=len(in_family), **effects
                ),
                "approved_total_method": pool["approved_total_method"],
                "chembl_version": pool["chembl_version"],
                "removed_counts_note": REMOVED_COUNTS_NOTE,
                "sanity_check_note": SANITY_CHECK_NOTE,
                "new_candidates_note": NEW_CANDIDATES_NOTE,
                "family_coverage_note": FAMILY_COVERAGE_NOTE.format(release=pool["release"]),
                "ordering_rule": ORDERING_RULE,
                "pubmed_query_form": evidence.get("pubmed_query_form", ""),
                "pubmed_query_note": PUBMED_QUERY_NOTE,
                "studies_found": studies_found(evidence),
                "evidence_read": EVIDENCE_READ,
                "next_test_labels": dict(NEXT_TEST_LABELS),
                "doubt_kind_labels": dict(DOUBT_KIND_LABELS),
                "interstitial": INTERSTITIAL,
                "interstitial_continue": INTERSTITIAL_CONTINUE,
                "interstitial_back": INTERSTITIAL_BACK,
                "medication_warning": (graph.get("meta") or {}).get("medication_warning")
                or MEDICATION_WARNING,
                "hypothesis_label": HYPOTHESIS_LABEL,
                "already_studied_caption": ALREADY_STUDIED_CAPTION,
                "badge": BADGE,
                "sources": list(SOURCES),
            },
            "lines": results,
        }
    )


def dumps(screen: Screen) -> str:
    payload = json.loads(screen.model_dump_json(exclude_none=False))
    return json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    try:
        screen = build()
    except BuildRefused as exc:
        print(f"make screen: refused: {exc}", file=sys.stderr)
        return 1
    SCREEN_OUT.write_text(dumps(screen))
    for line in screen.lines:
        if line.status == "refused":
            print(f"{line.key}: refused ({line.refusal_reason})")
            continue
        f, sanity = line.funnel, line.sanity_check
        tried = (
            f"already studied {sanity.surfaced} of {sanity.already_tried_total}"
            if sanity.applicable
            else "sanity check not applicable"
        )
        print(
            f"{line.key}: approved {f.approved} -> family {f.family} -> direction"
            f" {f.direction_pass} -> pair paper {f.with_pair_paper}, mechanism reference only"
            f" {f.with_mechanism_reference_only}, no paper {f.without_paper}; new candidates"
            f" {line.new_candidates}; cards {len(line.cards)} (+{line.cards_not_shown} not"
            f" shown); {tried}"
        )
    print(f"screen.json: {len(screen.lines)} lines, direction from {screen.meta.direction_source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

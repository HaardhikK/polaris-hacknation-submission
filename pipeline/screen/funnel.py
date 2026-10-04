"""The screen as pure functions: eligibility, family filter, direction filter, evidence join.

No network, no model, no I/O. Inputs are plain dicts from the committed caches, so the tests
run on small fixtures and the build runs on the real files through the same code.

Removed drugs leave only counts behind: nothing here returns a removed drug's name.
"""

from __future__ import annotations

from collections import Counter
from typing import get_args

from pipeline.screen.config import (
    APPROVED_STAGES,
    CARDS_NOT_SHOWN_REASON,
    EFFECT_BY_ACTION,
    FAMILY_BY_MECHANISM,
    KEEP_EFFECT,
    MAX_CARDS_PER_LINE,
    SCREEN_LINE_KEYS,
    TARGET_LEVEL,
)
from pipeline.screen.models import CardState

CARD_STATES: tuple[str, ...] = get_args(CardState)


# --- Eligibility ------------------------------------------------------------------


def eligibility(line: dict, evidence: dict | None = None) -> str | None:
    """None when the line may be screened, else the refusal reason shown to the researcher."""
    if line.get("in_graph") is False:
        return "line_not_in_graph"
    if line.get("mechanism_family") != "ion_channel" or line.get("mechanism") not in (
        FAMILY_BY_MECHANISM
    ):
        return "not_a_channel_line"
    if line.get("key") not in SCREEN_LINE_KEYS:
        return "line_not_in_screen_scope"
    if line.get("direction") not in KEEP_EFFECT:
        return "direction_mixed_or_unknown"
    support = line.get("direction_evidence")
    if not isinstance(support, dict) or not support.get("pmid"):
        return "direction_not_confirmed"
    if evidence is not None and line.get("gene") not in evidence.get("genes", []):
        return "evidence_not_fetched"  # no PubMed / CT.gov pairs for this gene yet
    return None


# --- Filters ----------------------------------------------------------------------


def approved_only(pool: list[dict]) -> list[dict]:
    return [d for d in pool if d.get("max_stage") in APPROVED_STAGES]


def family_filter(drugs: list[dict], family: frozenset[str]) -> tuple[list[dict], int]:
    """Drugs with at least one mechanism on a family target; the rest become one count."""
    kept = [d for d in drugs if family_mechanisms(d, family)]
    return kept, len(drugs) - len(kept)


def family_mechanisms(drug: dict, family: frozenset[str]) -> list[dict]:
    return [
        m for m in drug.get("mechanisms", []) if any(g in family for g in m.get("target_genes", []))
    ]


def effects_on_family(drug: dict, family: frozenset[str]) -> set[str]:
    """The mapped effects of the drug's family mechanisms; unmapped action types are 'unclear'."""
    return {
        EFFECT_BY_ACTION.get(str(m.get("action_type", "")).upper(), "unclear")
        for m in family_mechanisms(drug, family)
    }


def family_effects(drugs: list[dict], family: frozenset[str]) -> dict[str, int]:
    """How many family drugs reduce, increase, or have no single mapped effect (counts only)."""
    out = Counter({"reduces": 0, "increases": 0, "unclear": 0})
    for drug in drugs:
        effects = effects_on_family(drug, family)
        if effects == {"reduces"} or effects == {"increases"}:
            out[next(iter(effects))] += 1
        else:
            out["unclear"] += 1
    return dict(out)


def direction_filter(
    drugs: list[dict], direction: str, family: frozenset[str]
) -> tuple[list[dict], dict[str, int]]:
    """Keep a drug only if one family mechanism has the kept effect and none the opposite.

    A drug whose family mechanisms are all unmapped, or that both reduces and increases, is
    counted as ``action_unclear``; a drug with only the opposite effect as ``wrong_direction``.
    """
    keep = KEEP_EFFECT[direction]
    opposite = {"reduces": "increases", "increases": "reduces"}[keep]
    kept: list[dict] = []
    removed: Counter[str] = Counter({"wrong_direction": 0, "action_unclear": 0})
    for drug in drugs:
        effects = effects_on_family(drug, family)
        if keep in effects and opposite not in effects:
            kept.append(drug)
        elif opposite in effects and keep not in effects:
            removed["wrong_direction"] += 1
        else:
            removed["action_unclear"] += 1
    return kept, dict(removed)


# --- Evidence join ----------------------------------------------------------------


def pair_key(drug_id: str, gene: str) -> str:
    return f"{drug_id}|{gene}"


def pair_evidence(drug: dict, gene: str, evidence: dict) -> dict:
    pair = evidence.get("pairs", {}).get(pair_key(drug["drug_id"], gene)) or {}
    return {
        "pmids": list(pair.get("pmids", [])),
        "pubmed_count": int(pair.get("pubmed_count", 0)),
        "studies": list(pair.get("studies", [])),
    }


def already_studied(drug: dict, gene: str, evidence: dict) -> bool:
    pair = pair_evidence(drug, gene, evidence)
    return bool(pair["pmids"] or pair["studies"])


def card_for(drug: dict, gene: str, direction: str, family: frozenset[str], evidence: dict) -> dict:
    keep = KEEP_EFFECT[direction]
    kept_mechanisms = [
        m
        for m in family_mechanisms(drug, family)
        if EFFECT_BY_ACTION.get(str(m.get("action_type", "")).upper()) == keep
    ]
    targets = sorted({g for m in kept_mechanisms for g in m.get("target_genes", []) if g in family})
    ot_pmids = sorted({p for m in kept_mechanisms for p in m.get("pmids", [])})
    pair = pair_evidence(drug, gene, evidence)
    if pair["pmids"] or pair["studies"]:
        state = "already_studied"
    elif ot_pmids:
        state = "paper_found"
    else:
        state = "no_paper_found"
    return {
        "drug_id": drug["drug_id"],
        "name": drug["name"],
        "action_type": kept_mechanisms[0]["action_type"],
        "effect": keep,
        "targets": targets,
        "target_level": TARGET_LEVEL,
        "on_line_gene": gene in targets,
        "max_stage": drug["max_stage"],
        "state": state,
        "evidence": {**pair, "opentargets_pmids": ot_pmids},
    }


def join_evidence(
    drugs: list[dict], gene: str, direction: str, family: frozenset[str], evidence: dict
) -> list[dict]:
    return [card_for(d, gene, direction, family, evidence) for d in drugs]


def order(cards: list[dict]) -> list[dict]:
    """Fixed rule: papers pairing drug and gene (desc), then name. Never by expected benefit."""
    return sorted(cards, key=lambda c: (-c["evidence"]["pubmed_count"], c["name"]))


# --- One line ---------------------------------------------------------------------


def screen_line(line: dict, pool: dict, evidence: dict) -> dict:
    """The line's result without model text: counts by reason, ordered cards, sanity check."""
    base = {
        "key": line["key"],
        "label": line["label"],
        "gloss": line["gloss"],
        "gene": line["gene"],
        "direction": line["direction"],
    }
    reason = eligibility(line, evidence)
    if reason:
        return {**base, "status": "refused", "refusal_reason": reason}
    family = FAMILY_BY_MECHANISM[line["mechanism"]]
    approved = approved_only(pool["drugs"])
    in_family, _ = family_filter(approved, family)
    # The pool holds only drugs listed on family targets; everything else approved is outside.
    outside = int(pool["approved_total"]) - len(in_family)
    if outside < 0:
        raise ValueError("the family pool holds more approved drugs than the approved total")
    passed, removed = direction_filter(in_family, line["direction"], family)
    cards = order(join_evidence(passed, line["gene"], line["direction"], family, evidence))
    states = Counter(c["state"] for c in cards)
    tried_total = sum(already_studied(d, line["gene"], evidence) for d in in_family)
    shown = cards[:MAX_CARDS_PER_LINE]
    hidden = cards[MAX_CARDS_PER_LINE:]
    hidden_states = Counter(c["state"] for c in hidden)
    return {
        **base,
        "status": "screened",
        "direction_evidence": line["direction_evidence"],
        "funnel": {
            "approved": int(pool["approved_total"]),
            "family": len(in_family),
            "direction_pass": len(passed),
            "with_pair_paper": states["already_studied"],
            "with_mechanism_reference_only": states["paper_found"],
            "without_paper": states["no_paper_found"],
            "on_line_gene": sum(c["on_line_gene"] for c in cards),
        },
        "removed_by_reason": {"outside_the_channel_family": outside, **removed},
        "sanity_check": {
            "applicable": bool(passed),
            "surfaced": states["already_studied"],
            "already_tried_total": tried_total,
        },
        "new_candidates": len(passed) - states["already_studied"],
        "new_candidates_on_line_gene": sum(
            c["on_line_gene"] and c["state"] != "already_studied" for c in cards
        ),
        "cards": shown,
        "cards_not_shown": len(hidden),
        "cards_not_shown_by_state": {s: hidden_states[s] for s in CARD_STATES},
        "cards_not_shown_reason": (
            CARDS_NOT_SHOWN_REASON.format(cap=MAX_CARDS_PER_LINE, n=len(hidden)) if hidden else None
        ),
    }

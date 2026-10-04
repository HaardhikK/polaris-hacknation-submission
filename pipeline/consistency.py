"""``make consistency``: does the share-or-block rule agree with one expert decision?

EMBOLD (NCT05818553, started 2023-08-02) is the one registered trial in the slice that a
sponsor set up across two genes by mechanism and direction (SCN2A and SCN8A, early-onset
encephalopathies). This check hides EMBOLD and everything dated after its start, asks the
rule which other channel line ``scn2a_gain`` could share a trial with, and compares the
answer with the genes EMBOLD names. n = 1: the result shows agreement with one decision,
not discovery, and the title on screen says so.

Temporal hold-out: papers by publication year (strictly before the trial's start year),
ClinicalTrials.gov records by ``start_date``; ontology and annotation files are static
background; ``co_listed_in`` edges are listed separately because the record does not say
when each gene was added. Reads committed files only.
"""

from __future__ import annotations

import json
import sys
from datetime import date

import yaml

from pipeline.schema import CHANNEL_GENES, AcceptedClaim, Direction, Line, Paper
from pipeline.seed_check import Seed, load_seed
from pipeline.transfer import CACHE, CTGOV_CACHE, known_direction, load_accepted_claims

PAPERS_CACHE = CACHE / "papers.yaml"

HELD_OUT_NCT = "NCT05818553"
HELD_OUT_LINE = "scn2a_gain"
TITLE = (
    "Consistency check: our rule agrees with one expert decision (EMBOLD), n=1. Shows"
    " agreement, not discovery"
)


def trial_start(nct: str) -> date:
    doc = yaml.safe_load(CTGOV_CACHE.read_text()) or {}
    record = next(s for s in doc.get("studies", []) if s["nct"] == nct)
    return date.fromisoformat(record["start_date"][:10])


def claims_before(claims: list[AcceptedClaim], papers: dict[str, Paper], year: int) -> list:
    """Claims whose paper was published strictly before ``year`` (undated papers excluded)."""
    return [c for c in claims if (papers.get(c.pmid) and papers[c.pmid].year or 9999) < year]


def predicted_partners(target: Line, seed: Seed, claims: list[AcceptedClaim]) -> list[str]:
    """Lines the rule would let ``target`` share a trial with: same mechanism, same known
    direction, another gene (the positive gate of the transfer engine)."""
    mine = known_direction(target, claims)
    if mine not in (Direction.GAIN, Direction.LOSS):
        return []
    return sorted(
        line.key
        for line in seed.lines
        if line.gene != target.gene
        and line.gene in CHANNEL_GENES
        and line.mechanism == target.mechanism
        and known_direction(line, claims) is mine
    )


def run(seed: Seed | None = None, claims: list[AcceptedClaim] | None = None) -> dict:
    seed = seed or load_seed()[0]
    claims = claims if claims is not None else load_accepted_claims()
    rows = (yaml.safe_load(PAPERS_CACHE.read_text()) or {}).get("papers", [])
    papers = {p.pmid: p for p in (Paper.model_validate(r) for r in rows)}
    start = trial_start(HELD_OUT_NCT)
    doc = yaml.safe_load(CTGOV_CACHE.read_text()) or {}
    held_study = next(s for s in doc["studies"] if s["nct"] == HELD_OUT_NCT)
    named = sorted(
        {
            s.genes_named[i]
            for s in seed.studies
            if s.nct == HELD_OUT_NCT
            for i in range(len(s.genes_named))
        }
    )
    before = claims_before(claims, papers, start.year)
    target = next(line for line in seed.lines if line.key == HELD_OUT_LINE)
    partners = predicted_partners(target, seed, before)
    partner_genes = sorted({next(ln.gene for ln in seed.lines if ln.key == k) for k in partners})
    pool = sorted(
        line.key for line in seed.lines if line.gene != target.gene and line.gene in CHANNEL_GENES
    )
    other_genes = sorted({ln.gene for ln in seed.lines if ln.gene != target.gene})
    hit = [g for g in partner_genes if g in named and g != target.gene]
    co_listed = sorted({e["line"] for e in doc.get("co_listed_in", []) if e["nct"] == HELD_OUT_NCT})
    studies_before = sorted(
        s["nct"]
        for s in doc["studies"]
        if s["nct"] != HELD_OUT_NCT
        and s.get("start_date")
        and date.fromisoformat((s["start_date"] + "-01-01")[:10]) < start
    )
    return {
        "title": TITLE,
        "held_out": {
            "nct": HELD_OUT_NCT,
            "name": next(s.name for s in seed.studies if s.nct == HELD_OUT_NCT),
            "start_date": held_study["start_date"],
            "genes_named": named,
        },
        "question": (
            f"With EMBOLD hidden and only papers published before {start.year} and studies"
            f" started before {start.isoformat()}, which other channel line could"
            f" {target.label} share a trial with under our rule?"
        ),
        "prediction": {"lines": partners, "genes": partner_genes},
        "agreement": {
            "matched_genes": hit,
            "k": 1,
            "hits": 1 if hit else 0,
            "sentence": (
                f"The rule names {', '.join(partner_genes) or 'no gene'}; EMBOLD names"
                f" {', '.join(g for g in named if g != target.gene)}. "
                + ("Agreement: 1 of 1." if hit else "No agreement.")
            ),
        },
        "pool": {
            "channel_lines_considered": pool,
            "size": len(pool),
            "random_baseline": round(1 / len(pool), 3) if pool else None,
            "other_genes_on_the_map": other_genes,
        },
        "inputs": {
            "papers_used": sorted({c.pmid for c in before}),
            "papers_cutoff": f"published before {start.year}",
            "claims_used": len(before),
            "studies_before_start": studies_before,
            "studies_before_start_note": (
                "records started before the trial, listed for context; the rule reads"
                " papers only, so they are not used by the rule"
            ),
            "static_background": [
                "HPO phenotype.hpoa and hp.obo (v2026-09-01)",
                "Orphadata product6 (direction labels)",
                "Gene2Phenotype entries",
            ],
        },
        "co_listings_note": (
            "co_listed_in edges are reported separately: a record does not say when each gene was"
            " added, so their date is unknown for this gene. Lines co-listed in EMBOLD today: "
            + ", ".join(co_listed)
            + "."
        ),
        "caveat": (
            "One decision, one trial sponsor, one slice: this shows that the rule reproduces a"
            " choice an expert team made, not that it discovers anything."
        ),
    }


def main() -> int:
    print(json.dumps(run(), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

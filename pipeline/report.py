"""``make report``: the direction evidence behind every seeded line, in plain words.

For each line it lists the code-checked functional-assay claims of that gene whose
direction agrees with the line and the ones that disagree. Nothing here changes
data; it reads what ``validate.py`` accepts.
"""

from __future__ import annotations

import sys
from collections import defaultdict

from pipeline.schema import CHANNEL_GENES, AcceptedClaim, Basis, Direction, Line
from pipeline.seed_check import load_seed
from pipeline.transfer import variant_on_line, variant_verdicts
from pipeline.validate import (
    Checked,
    canonical_variant,
    check_signatures,
    claim_flags,
    load_verifications,
    validate_claims,
)

CHECK_LEVEL = {True: "checked by a person", False: "checked by code"}
GLOSS_WORDS = {Direction.GAIN: "works too strongly", Direction.LOSS: "works too weakly"}


def line_evidence(line: Line, accepted: list[Checked], signed: set[str]) -> dict:
    """Agreeing, disagreeing and gene-level assay claims for one line."""
    gene, direction = line.gene, line.direction
    agree, disagree, gene_level = [], [], []
    rows = [
        AcceptedClaim.model_validate(
            {
                **c.claim,
                "variant": canonical_variant(c.claim["variant"] or "")
                if c.claim.get("variant")
                else None,
                "claim_id": c.claim_id,
                "extractor_run_id": c.provenance.get("extractor_run_id", "run"),
                "agent": c.provenance.get("agent", "codex"),
                "model": c.provenance.get("model", "model"),
                "flags": claim_flags(c.claim),
            }
        )
        for c in accepted
    ]
    verdicts = variant_verdicts(rows, gene)
    for c in accepted:
        k = c.claim
        if k["gene"] != gene or k["basis"] != Basis.FUNCTIONAL_ASSAY:
            continue
        canon = canonical_variant(k["variant"] or "") if k.get("variant") else None
        if not k.get("variant"):
            gene_level.append(c)
        elif (
            Direction(k["direction"]) is direction
            and k["stance"] == "supports"
            and not any(f.startswith("hedged") for f in claim_flags(k))
            and verdicts.get(canon) is direction
            and variant_on_line(line, k["variant"])
        ):
            agree.append(c)  # the same rule the transfer engine applies (unhedged, uncontested)
        elif verdicts.get(canon) in (Direction.GAIN, Direction.LOSS, Direction.MIXED):
            disagree.append(c)  # grouped by the engine's verdict below, not the claim's words
    return {
        "agree": agree,
        "disagree": disagree,
        "gene_level": gene_level,
        "verdicts": verdicts,  # transfer.variant_verdicts, the engine's own reading
        "person_signed": any(c.claim_id in signed for c in agree),
    }


def main() -> int:
    seed, problems = load_seed()
    if problems:
        print("report: fix the seed first (make validate)")
        return 1
    checked, fatal, _ = validate_claims()
    if fatal:
        print("report: claims file is not valid (make validate)")
        return 1
    accepted = [c for c in checked if c.accepted]
    verifications, _ = load_verifications()
    signed, _, _ = check_signatures(checked, verifications)

    print("direction evidence per line (functional-assay claims accepted by the validator)")
    for line in seed.lines:
        if line.gene not in CHANNEL_GENES:
            print(f"- {line.key}: gain/loss not used for {line.gene}")
            print(f"    {line.mechanism_label}")
            continue
        ev = line_evidence(line, accepted, signed)
        level = CHECK_LEVEL[ev["person_signed"]]
        variants = sorted(
            {canonical_variant(c.claim["variant"]) or c.claim["variant"] for c in ev["agree"]}
        )
        pmids = sorted({c.pmid for c in ev["agree"]})
        n, papers = len(ev["agree"]), len({c.pmid for c in ev["agree"]})
        print(
            f"- {line.key}: {GLOSS_WORDS[line.direction]}; {n} lab-study"
            f" {'quote agrees' if n == 1 else 'quotes agree'}"
            f" ({papers} {'paper' if papers == 1 else 'papers'}), found by AI, {level}"
        )
        if variants:
            print(f"    variants: {', '.join(variants)}; PMIDs: {', '.join(pmids)}")
        else:
            print("    no agreeing functional-assay claim yet: the direction stays a hand label")
        print(
            "    engine verdicts (transfer.variant_verdicts): "
            + ", ".join(f"{v} {d.value}" for v, d in sorted(ev["verdicts"].items()))
        )
        other = defaultdict(set)
        for c in ev["disagree"]:  # grouped by the engine's verdict for the variant
            canon = canonical_variant(c.claim["variant"]) or c.claim["variant"]
            other[ev["verdicts"][canon].value].add(canon)
        for direction, vs in sorted(other.items()):
            names = ", ".join(sorted(vs))
            label = (
                "contested or mixed, not used"
                if direction == "mixed"
                else f"other {direction} variants"
            )
            print(f"    {label} for {line.gene} (not this line): {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

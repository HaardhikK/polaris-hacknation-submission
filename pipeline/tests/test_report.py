"""The report says what each line's direction rests on, without inventing a signer."""

from pipeline.report import CHECK_LEVEL, line_evidence
from pipeline.schema import Direction, Line
from pipeline.validate import Checked, claim_id

CLAIM = {
    "pmid": "34287911",
    "gene": "SCN2A",
    "claim_level": "variant",
    "variant": "p.Arg853Gln",
    "direction": "loss",
    "stance": "supports",
    "basis": "functional-assay",
    "evidence_quote": "R853Q channels exhibit an overall loss-of-function in HEK cells.",
}


def checked(claim):
    return Checked(claim_id(claim), claim, claim["pmid"], 0, [], {})


def test_line_evidence_sorts_agreeing_and_disagreeing_assay_claims():
    loss = checked(CLAIM)
    gain = checked({**CLAIM, "variant": "p.Arg1882Gln", "direction": "gain"})
    review = checked({**CLAIM, "basis": "review"})
    gene_level = checked({**CLAIM, "claim_level": "gene", "variant": None})
    line = Line.model_construct(
        key="scn2a_loss",
        gene="SCN2A",
        direction=Direction.LOSS,
        sources=[],
        variant_aliases_from_sources_only=False,
    )
    ev = line_evidence(line, [loss, gain, review, gene_level], set())
    assert ev["agree"] == [loss] and ev["disagree"] == [gain] and ev["gene_level"] == [gene_level]
    assert ev["person_signed"] is False
    assert CHECK_LEVEL[False] == "checked by code"
    ev2 = line_evidence(line, [loss], {loss.claim_id})
    assert ev2["person_signed"] is True


def test_report_runs_on_the_committed_data(capsys):
    from pipeline.report import main

    assert main() == 0
    out = capsys.readouterr().out
    assert "scn2a_loss: works too weakly" in out
    assert "checked by code" in out
    assert "person" not in out

"""The JSON schema the model is held to and the pydantic models must agree."""

import json
from datetime import date
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from pipeline.schema import (
    Asset,
    AssetType,
    Basis,
    ClaimLevel,
    Direction,
    Edge,
    ExtractedClaim,
    Line,
    MechanismFamily,
    Scope,
    Source,
    Stance,
    Station,
)

SCHEMA = json.loads(
    (Path(__file__).parent.parent / "prompts" / "extract_claims.schema.json").read_text()
)

GOOD_CLAIM = {
    "pmid": "34287911",
    "gene": "SCN2A",
    "claim_level": "variant",
    "variant": "p.Arg853Gln",
    "direction": "loss",
    "stance": "supports",
    "basis": "functional-assay",
    "evidence_quote": (
        "Heterologously expressed R853Q channels exhibit an overall loss-of-function."
    ),
}
GENE_CLAIM = {**GOOD_CLAIM, "claim_level": "gene", "variant": None}


def schema_accepts(claim: dict) -> bool:
    try:
        jsonschema.validate({"claims": [claim]}, SCHEMA)
    except jsonschema.ValidationError:
        return False
    return True


@pytest.mark.parametrize("claim", [GOOD_CLAIM, GENE_CLAIM])
def test_pydantic_accepts_well_formed_rows_the_schema_allows(claim):
    assert schema_accepts(claim)
    ExtractedClaim.model_validate(claim)


@pytest.mark.parametrize(
    "claim",
    [
        {**GOOD_CLAIM, "variant": None},  # variant level without a variant
        {**GENE_CLAIM, "variant": "p.Arg853Gln"},  # gene level naming a variant
        {**GENE_CLAIM, "variant": ""},  # empty string is not a variant
    ],
)
def test_level_variant_mismatches_pass_the_schema_but_fail_pydantic(claim):
    """The JSON schema is the model's output contract; the cross-field rule lives in code."""
    assert schema_accepts(claim)
    with pytest.raises(ValidationError):
        ExtractedClaim.model_validate(claim)


@pytest.mark.parametrize(
    "field", ["verified_by", "verified_at", "verified_hash", "abstract_sha256"]
)
def test_sign_off_fields_are_rejected_by_both(field):
    claim = {**GOOD_CLAIM, field: "anything"}
    assert not schema_accepts(claim)
    with pytest.raises(ValidationError):
        ExtractedClaim.model_validate(claim)


def test_every_schema_property_is_required_and_nothing_extra():
    item = SCHEMA["properties"]["claims"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == set(item["properties"])
    assert set(item["properties"]) == set(ExtractedClaim.model_fields)


def test_schema_enums_match_the_python_enums():
    props = SCHEMA["properties"]["claims"]["items"]["properties"]
    assert props["direction"]["enum"] == [d.value for d in Direction]
    assert props["stance"]["enum"] == [s.value for s in Stance]
    assert props["basis"]["enum"] == [b.value for b in Basis]
    assert props["claim_level"]["enum"] == [c.value for c in ClaimLevel]


def test_quote_is_capped_at_one_sentence_length():
    with pytest.raises(ValidationError):
        ExtractedClaim.model_validate({**GOOD_CLAIM, "evidence_quote": "x" * 301})


def line(**overrides) -> Line:
    base = {
        "key": "scn2a_loss",
        "gene": "SCN2A",
        "mechanism": "sodium_channel",
        "mechanism_family": MechanismFamily.ION_CHANNEL,
        "direction": Direction.LOSS,
        "label": "SCN2A loss of function",
        "gloss": "loss of function — the channel works too weakly",
        "sources": [
            Source(
                label="PMID 34287911",
                url="https://pubmed.ncbi.nlm.nih.gov/34287911/",
                retrieved=date(2026, 10, 4),
            )
        ],
    }
    return Line.model_validate({**base, **overrides})


def test_line_direction_key_is_lowercase_snake():
    assert line().key == "scn2a_loss"
    with pytest.raises(ValidationError):
        line(key="SCN2A-loss")


NON_CHANNEL = dict(
    key="stxbp1",
    gene="STXBP1",
    mechanism="synaptic_protein",
    mechanism_family=MechanismFamily.NON_CHANNEL,
    direction=Direction.NOT_APPLICABLE,
    mechanism_label="loss of protein function — database label (Gene2Phenotype), not lab-checked",
)


def test_non_channel_line_cannot_carry_a_direction():
    line(**NON_CHANNEL)
    with pytest.raises(ValidationError):
        line(**{**NON_CHANNEL, "direction": Direction.LOSS})


def test_mechanism_family_must_agree_with_the_gene():
    with pytest.raises(ValidationError):
        line(**{**NON_CHANNEL, "mechanism_family": MechanismFamily.ION_CHANNEL})
    with pytest.raises(ValidationError):
        line(mechanism_family=MechanismFamily.NON_CHANNEL, direction=Direction.NOT_APPLICABLE)
    with pytest.raises(ValidationError):
        line(direction=Direction.NOT_APPLICABLE)  # SCN2A must say gain/loss/mixed/unknown


def test_unknown_keys_are_rejected_everywhere():
    with pytest.raises(ValidationError):
        line(scope="gene")


SOURCE = Source(
    label="ClinicalTrials.gov NCT01238250",
    url="https://clinicaltrials.gov/study/NCT01238250",
    retrieved=date(2026, 10, 4),
)


def asset(**overrides) -> Asset:
    base = dict(
        id="nct01238250",
        type=AssetType.REGISTRY,
        station=Station.REGISTRY,
        scope=Scope.GENE,
        owner_gene="SCN2A",
        label="Simons Searchlight",
        source=SOURCE,
        last_verified=date(2026, 10, 4),
    )
    return Asset.model_validate({**base, **overrides})


def test_asset_scope_names_its_owner():
    asset()
    asset(
        type=AssetType.TRIAL,
        station=Station.TRIAL,
        scope=Scope.LINE,
        owner_line="scn2a_gain",
        direction=Direction.GAIN,
        direction_basis="stated_in_record",
    )
    with pytest.raises(ValidationError):
        asset(scope=Scope.LINE)  # line scope without owner_line
    with pytest.raises(ValidationError):
        asset(owner_line="scn2a_gain")  # gene scope with an owner_line


def test_edge_retrieved_date_comes_from_its_source():
    edge = Edge(
        subject="scn2a_loss",
        predicate="co_listed_in",
        object="nct01238250",
        source=SOURCE,
        tier=2,
        knowledge_level="observation",
        agent_type="manual_agent",
    )
    assert edge.retrieved == date(2026, 10, 4)
    assert edge.model_dump()["retrieved"] == date(2026, 10, 4)


def test_plain_text_fields_reject_markup_and_links():
    with pytest.raises(ValidationError, match="markup, link or e-mail"):
        line(label="<b>SCN2A</b>")
    with pytest.raises(ValidationError, match="markup, link or e-mail"):
        line(gloss="see https://example.com")

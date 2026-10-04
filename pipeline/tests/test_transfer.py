"""Every transfer rule, plus the golden demo card for scn2a_loss."""

import json
from pathlib import Path

import pytest

from pipeline.denylist import DRUG_TERMS, denied_terms
from pipeline.schema import (
    AcceptedClaim,
    Asset,
    AssetType,
    Direction,
    DirectionBasis,
    Line,
    MechanismFamily,
    Scope,
    Source,
    Station,
    TransferStatus,
)
from pipeline.seed_check import Seed, load_seed
from pipeline.transfer import (
    CLAIMS_CACHE,
    card,
    known_direction,
    load_accepted_claims,
    note_stopped_studies,
    station_map,
    summary,
    transfers_for,
)

GOLDEN = Path(__file__).parent / "golden" / "scn2a_loss_transfers.json"
SRC = Source(label="x", url="https://clinicaltrials.gov/study/NCT00000001")
SRC2 = Source(label="y", url="https://www.jax.org/strain/000001")
SRC3 = Source(label="z", url="https://clinicaltrials.gov/study/NCT00000002")
PMID9 = Source(label="PMID 9", url="https://pubmed.ncbi.nlm.nih.gov/9/")
ION, NON = MechanismFamily.ION_CHANNEL, MechanismFamily.NON_CHANNEL
STUDIES = {"NCT00000001": {"lead_sponsor": "Some Hospital", "overall_status": "RECRUITING"}}


def line(key, gene, mechanism, family, direction, label=None, sources=(SRC,)) -> Line:
    return Line(
        key=key,
        gene=gene,
        mechanism=mechanism,
        mechanism_family=family,
        direction=direction,
        label=key,
        gloss="g",
        mechanism_label=label,
        sources=list(sources),
    )


def asset(id, type, station, owner_gene, scope=Scope.GENE, owner_line=None, **kw) -> Asset:
    return Asset(
        id=id,
        type=type,
        station=station,
        scope=scope,
        owner_gene=owner_gene,
        owner_line=owner_line,
        direction=kw.get("direction", Direction.NOT_APPLICABLE),
        direction_basis=kw.get("basis"),
        label=id,
        source=kw.get("source", SRC),
    )


def gain_trial(id="gain_trial", gene="SCN2A", owner="scn2a_gain", basis=DirectionBasis.ONSET_PROXY):
    return asset(
        id,
        AssetType.TRIAL,
        Station.TRIAL,
        gene,
        Scope.LINE,
        owner,
        direction=Direction.GAIN,
        basis=basis,
    )


def claim(gene, variant, direction, pmid="1", stance="supports", flags=()) -> AcceptedClaim:
    return AcceptedClaim(
        pmid=pmid,
        gene=gene,
        claim_level="variant",
        variant=variant,
        direction=direction,
        stance=stance,
        basis="functional-assay",
        evidence_quote=f"{variant} channels showed a clear {direction} of function in cells.",
        claim_id=f"{pmid}:{gene}:{variant}:{direction}:deadbeef",
        extractor_run_id="run",
        agent="codex",
        model="m",
        flags=list(flags),
    )


LINES = [
    line("scn2a_gain", "SCN2A", "sodium_channel", ION, Direction.GAIN),
    line("scn2a_loss", "SCN2A", "sodium_channel", ION, Direction.LOSS),
    line("scn8a_dee", "SCN8A", "sodium_channel", ION, Direction.GAIN),
    line("kcnq2_dee", "KCNQ2", "potassium_channel", ION, Direction.LOSS),
    line("stxbp1", "STXBP1", "synaptic_protein", NON, Direction.NOT_APPLICABLE, "db label"),
]
CLAIMS = [
    claim("SCN2A", "p.Arg853Gln", "loss"),
    claim("SCN2A", "p.Arg1882Gln", "gain"),
    claim("SCN8A", "p.Asn1768Asp", "gain"),
    claim("KCNQ2", "p.Glu130Lys", "loss"),
]


def rows(target, assets, claims=CLAIMS, lines=LINES):
    seed = Seed(lines=lines, assets=assets)
    return {t.asset_id: t for t in transfers_for(target, seed, claims, STUDIES)}


# --- Direction -----------------------------------------------------------------------------


def test_known_direction_needs_an_unhedged_supporting_assay_claim():
    assert known_direction(LINES[1], CLAIMS) is Direction.LOSS
    assert known_direction(LINES[1], []) is Direction.UNKNOWN
    assert known_direction(LINES[4], CLAIMS) is Direction.NOT_APPLICABLE
    contradicting = [claim("SCN2A", "p.Arg853Gln", "loss", stance="contradicts")]
    assert known_direction(LINES[1], contradicting) is Direction.UNKNOWN
    hedged = [claim("SCN2A", "p.Arg853Gln", "loss", flags=["hedged wording in the quote"])]
    assert known_direction(LINES[1], hedged) is Direction.UNKNOWN


def test_a_variant_with_assays_in_both_directions_cannot_confirm_a_line():
    both = [claim("SCN2A", "p.Arg853Gln", "loss"), claim("SCN2A", "p.Arg853Gln", "gain", pmid="2")]
    assert known_direction(LINES[1], both) is Direction.UNKNOWN
    with_other = both + [
        claim("SCN2A", "p.Lys156Asn", "loss", pmid="3"),
        claim("SCN2A", "p.Arg1882Gln", "gain", pmid="4"),
    ]
    assert known_direction(LINES[1], with_other) is Direction.LOSS
    t = rows("scn2a_loss", [gain_trial()], with_other)["gain_trial"]
    assert t.blocked and t.cited_pmid == "3"  # never the contested variant


def test_citation_is_stable_and_prefers_a_pmid_from_the_lines_own_sources():
    own = line("scn2a_loss", "SCN2A", "sodium_channel", ION, Direction.LOSS, sources=(PMID9,))
    claims = [
        claim("SCN2A", "p.Lys156Asn", "loss", pmid="1"),
        claim("SCN2A", "p.Arg853Gln", "loss", pmid="9"),
        claim("SCN2A", "p.Arg1882Gln", "gain", pmid="2"),
    ]
    for order in (claims, claims[::-1]):
        t = rows("scn2a_loss", [gain_trial()], order, lines=[LINES[0], own])["gain_trial"]
        assert t.cited_pmid == "9" and t.evidence_claim_ids[0].startswith("9:")


# --- Gate and blocks -------------------------------------------------------------------------


def test_gene_scope_assets_are_already_open_never_borrowed_between_scn2a_lines():
    a = asset("searchlight", AssetType.REGISTRY, Station.REGISTRY, "SCN2A")
    for target in ("scn2a_gain", "scn2a_loss"):
        t = rows(target, [a])["searchlight"]
        assert t.status is TransferStatus.ALREADY_OPEN
        assert "Open to SCN2A families" in t.reason


def test_the_same_resource_is_never_both_open_and_a_borrow():
    mine = asset("searchlight_scn2a", AssetType.REGISTRY, Station.REGISTRY, "SCN2A")
    theirs = asset("searchlight_stxbp1", AssetType.REGISTRY, Station.REGISTRY, "STXBP1")
    result = rows("scn2a_loss", [mine, theirs])
    assert set(result) == {"searchlight_scn2a"}
    assert result["searchlight_scn2a"].status is TransferStatus.ALREADY_OPEN
    assert "Also open to STXBP1 families" in result["searchlight_scn2a"].reason


def test_same_gene_opposite_direction_trial_is_blocked_with_the_claim_and_banner_copy():
    t = rows("scn2a_loss", [gain_trial()])["gain_trial"]
    assert t.status is TransferStatus.NOT_SHARED and t.blocked and t.crosses_direction
    assert t.reason.startswith("Same gene, opposite problem: not matched to your child's form.")
    assert t.banner.startswith("Same gene, opposite problem: your variant makes the channel")
    assert "Registries and care networks can still be shared." in t.banner
    assert "inferred, not lab-tested" in t.basis_note
    assert "PMID 1" in t.reason and t.cited_pmid == "1" and t.evidence_level == "checked by code"
    assert t.evidence_claim_ids == ["1:SCN2A:p.Arg853Gln:loss:deadbeef"] and t.check_first == []
    assert t.direction_basis is DirectionBasis.ONSET_PROXY


def test_same_channel_family_same_direction_trial_needs_expert_check():
    trial = gain_trial("scn8a_trial", "SCN8A", "scn8a_dee", DirectionBasis.STATED_IN_RECORD)
    t = rows("scn2a_gain", [trial])["scn8a_trial"]
    assert t.status is TransferStatus.NEEDS_EXPERT_CHECK and "for SCN8A only" in t.reason
    assert "your child" not in t.reason and "an expert can say" in t.reason
    assert not t.blocked and t.check_first
    loss_view = rows("scn2a_loss", [trial])["scn8a_trial"]
    assert loss_view.status is TransferStatus.NOT_SHARED and loss_view.blocked
    assert loss_view.banner.startswith("Same channel family, opposite problem")


def test_different_channel_mechanism_is_not_matched_and_not_a_block():
    trial = asset("kcnq2_trial", AssetType.TRIAL, Station.TRIAL, "KCNQ2", Scope.LINE, "kcnq2_dee",
                  direction=Direction.LOSS, basis=DirectionBasis.STATED_IN_RECORD)  # fmt: skip
    t = rows("scn2a_loss", [trial])["kcnq2_trial"]
    assert t.status is TransferStatus.NOT_SHARED and not t.blocked
    assert "different channel mechanism" in t.reason


def test_non_channel_gated_assets_are_not_matched_and_never_blocked():
    stxbp1_trial = asset(
        "stxbp1_gene_therapy", AssetType.TRIAL, Station.TRIAL, "STXBP1", Scope.LINE, "stxbp1"
    )
    t = rows("scn2a_loss", [stxbp1_trial])["stxbp1_gene_therapy"]
    assert t.status is TransferStatus.NOT_SHARED and not t.blocked
    assert t.reason.startswith("STXBP1 works through different biology from SCN2A")
    scn2a_model = asset(
        "scn2a_model",
        AssetType.MODEL,
        Station.MODEL,
        "SCN2A",
        Scope.LINE,
        "scn2a_loss",
        direction=Direction.LOSS,
        basis=DirectionBasis.FUNCTIONAL_ASSAY,
    )
    t = rows("stxbp1", [scn2a_model])["scn2a_model"]
    assert (
        t.status is TransferStatus.NOT_SHARED and not t.blocked and "different biology" in t.reason
    )


def test_mixed_or_unknown_target_direction_fails_the_gate_but_keeps_registries():
    trial = gain_trial("scn8a_trial", "SCN8A", "scn8a_dee", DirectionBasis.STATED_IN_RECORD)
    registry = asset("scn8a_registry", AssetType.REGISTRY, Station.REGISTRY, "SCN8A", source=SRC2)
    result = rows("scn2a_gain", [trial, registry], claims=[])  # nothing confirms scn2a_gain
    assert result["scn8a_trial"].status is TransferStatus.NOT_SHARED
    assert result["scn8a_registry"].status is TransferStatus.VIABLE
    mixed = [line("scn2a_gain", "SCN2A", "sodium_channel", ION, Direction.MIXED), *LINES[1:]]
    t = rows("scn2a_gain", [trial], lines=mixed)["scn8a_trial"]
    assert t.status is TransferStatus.NOT_SHARED and "disagree" in t.reason and not t.blocked


def test_unknown_owner_direction_on_a_gated_asset_is_not_matched():
    model = asset("scn8a_model", AssetType.MODEL, Station.MODEL, "SCN8A", Scope.LINE, "scn8a_dee",
                  direction=Direction.UNKNOWN)  # fmt: skip
    t = rows("scn2a_gain", [model])["scn8a_model"]
    assert t.status is TransferStatus.NOT_SHARED and "have not established" in t.reason


def test_registries_and_outcome_measures_cross_genes_and_directions_with_facts():
    measure = asset(
        "gain_measure",
        AssetType.OUTCOME_MEASURE,
        Station.OUTCOME_MEASURE,
        "SCN2A",
        Scope.LINE,
        "scn2a_gain",
    )
    t = rows("scn2a_loss", [measure])["gain_measure"]
    assert t.status is TransferStatus.VIABLE and t.crosses_direction and not t.crosses_gene
    assert "opposite direction" in t.reason and t.check_first and t.cited_pmid == "1"
    assert any(d.startswith("direction: in your child's form") for d in t.what_differs)
    nh = asset("nh", AssetType.NATURAL_HISTORY, Station.NATURAL_HISTORY, "STXBP1")
    t = rows("scn2a_loss", [nh])["nh"]
    assert t.status is TransferStatus.VIABLE and t.crosses_gene and t.fills_missing_station
    assert t.owner_org == "Some Hospital" and t.nct == "NCT00000001"
    assert "run by Some Hospital" in t.reason
    assert any(d.startswith("mechanism: STXBP1 is g") for d in t.what_differs)
    assert "age range: not stated in the study record" in t.what_differs


def test_ranking_puts_borrows_for_missing_stations_first_then_blocks_before_other_not_shared():
    held = asset("own_registry", AssetType.REGISTRY, Station.REGISTRY, "SCN2A")
    other_registry = asset(
        "stxbp1_registry", AssetType.REGISTRY, Station.REGISTRY, "STXBP1", source=SRC2
    )
    nh = asset(
        "stxbp1_nh", AssetType.NATURAL_HISTORY, Station.NATURAL_HISTORY, "STXBP1", source=SRC3
    )
    stxbp1_model = asset("stxbp1_model", AssetType.MODEL, Station.MODEL, "STXBP1", source=SRC2)
    seed = Seed(lines=LINES, assets=[held, other_registry, nh, gain_trial(), stxbp1_model])
    ranked = [t.asset_id for t in transfers_for("scn2a_loss", seed, CLAIMS, STUDIES)]
    assert ranked == ["stxbp1_nh", "stxbp1_registry", "own_registry", "gain_trial", "stxbp1_model"]


# --- Stations and copy ----------------------------------------------------------------------


def test_station_map_distinguishes_have_missing_and_unknown():
    seed = Seed(
        lines=LINES, assets=[asset("own_registry", AssetType.REGISTRY, Station.REGISTRY, "SCN2A")]
    )
    states = {k: v["state"] for k, v in station_map(LINES[1], seed, CLAIMS).items()}
    assert states["registry"] == "have" and states["mechanism"] == "have"
    assert states["trial"] == "missing"
    assert station_map(LINES[1], seed, [])["mechanism"]["state"] == "unknown"
    assert station_map(LINES[4], seed, [])["mechanism"] == {"state": "have", "why": "db label"}


def test_stopped_or_paused_registry_and_trial_do_not_count_as_held_steps():
    """A paused registry or a stopped trial is "Tried before", not a step held today."""
    paused = asset("own_registry", AssetType.REGISTRY, Station.REGISTRY, "SCN2A", source=SRC3)
    live = asset("live_registry", AssetType.REGISTRY, Station.REGISTRY, "SCN2A")
    stopped_trial = gain_trial()
    studies = {
        **STUDIES,
        "NCT00000002": {"lead_sponsor": "Some Hospital", "overall_status": "SUSPENDED"},
    }
    seed = Seed(lines=LINES, assets=[paused, stopped_trial])
    stations = station_map(LINES[0], seed, CLAIMS, studies)
    assert stations["registry"] == {
        "state": "missing",
        "why": "own_registry is paused; not counted as a step held today",
        "halted": "paused",
    }
    assert stations["trial"]["state"] == "have"  # the record of the trial is RECRUITING
    # one live record beside a paused one keeps the station held, naming the live one only
    both = station_map(LINES[0], Seed(lines=LINES, assets=[paused, live]), CLAIMS, studies)
    assert both["registry"] == {"state": "have", "why": "live_registry"}
    studies["NCT00000001"] = {"lead_sponsor": "Some Hospital", "overall_status": "TERMINATED"}
    stations = station_map(LINES[0], seed, CLAIMS, studies)
    assert stations["trial"] == {
        "state": "missing",
        "why": "gain_trial is stopped; not counted as a step held today",
        "halted": "stopped",
    }
    assert stations["model"]["why"] == "none found yet" and "halted" not in stations["model"]
    assert stations["registry"]["halted"] == "paused" and stations["trial"]["halted"] == "stopped"
    c = card("scn2a_gain", seed, CLAIMS, studies)
    assert "registry" in c["steps"]["missing"] and "trial" in c["steps"]["missing"]
    assert "a registry (yours is paused) and a trial (yours is stopped)" in c["steps"]["sentence"]
    # a terminated natural-history study is not held either; a live one beside it still is
    ended = asset("own_nh", AssetType.NATURAL_HISTORY, Station.NATURAL_HISTORY, "SCN2A")
    live_nh = asset(
        "live_nh", AssetType.NATURAL_HISTORY, Station.NATURAL_HISTORY, "SCN2A", source=SRC3
    )
    studies["NCT00000002"] = {"lead_sponsor": "Some Hospital", "overall_status": "RECRUITING"}
    nh = station_map(LINES[0], Seed(lines=LINES, assets=[ended]), CLAIMS, studies)
    assert (
        nh["natural_history"]["state"] == "missing" and nh["natural_history"]["halted"] == "stopped"
    )
    nh = station_map(LINES[0], Seed(lines=LINES, assets=[ended, live_nh]), CLAIMS, studies)
    assert nh["natural_history"] == {"state": "have", "why": "live_nh"}


def test_a_co_listed_stopped_trial_is_named_instead_of_none_found_yet():
    stations = station_map(LINES[4], Seed(lines=LINES, assets=[]), [], {})
    assert stations["trial"] == {"state": "missing", "why": "none found yet"}
    rows = [
        {"nct": "NCT00000003", "name": "Rare-epilepsies trial", "kind": "trial", "state": "stopped"}
    ]
    noted = note_stopped_studies(stations, rows)
    assert noted["trial"] == {
        "state": "missing",
        "why": "Rare-epilepsies trial (NCT00000003) is stopped; not counted as a step held today",
        "halted": "stopped",
    }
    # a held station, a station of another kind, or a non-study kind is never touched
    held = {
        "registry": {"state": "have", "why": "x"},
        "trial": {"state": "missing", "why": "none found yet"},
    }
    rows = [
        {"nct": "N", "name": "r", "kind": "registry", "state": "paused"},
        {"nct": "M", "name": "b", "kind": "biorepository", "state": "stopped"},
    ]
    assert note_stopped_studies(dict(held), rows) == held


def test_who_the_study_is_for_appears_only_with_the_record_population_line():
    nh = asset("stxbp1_nh", AssetType.NATURAL_HISTORY, Station.NATURAL_HISTORY, "STXBP1")
    bare = rows("scn2a_loss", [nh])["stxbp1_nh"]
    assert bare.study_population is None
    assert not any(d.startswith("who the study is for") for d in bare.what_differs)
    with_pop = {
        "NCT00000001": {
            "lead_sponsor": "Some Hospital",
            "overall_status": "RECRUITING",
            "study_population": "Children with a confirmed STXBP1 variant",
        }
    }
    seed = Seed(lines=LINES, assets=[nh])
    t = {x.asset_id: x for x in transfers_for("scn2a_loss", seed, CLAIMS, with_pop)}["stxbp1_nh"]
    assert t.study_population.startswith("Children") and any(
        d.startswith("who the study is for") for d in t.what_differs
    )


def test_card_steps_count_only_viable_borrows_for_missing_stations():
    nh = asset("stxbp1_nh", AssetType.NATURAL_HISTORY, Station.NATURAL_HISTORY, "STXBP1")
    c = card("scn2a_loss", Seed(lines=LINES, assets=[nh]), CLAIMS, STUDIES)
    assert c["steps"]["total"] == 7 and "natural_history" in c["steps"]["borrowable"]
    assert c["direction"] == "loss"


def test_every_family_facing_string_passes_the_deny_list_and_names_no_drug():
    seed, _ = load_seed()
    claims = load_accepted_claims(CLAIMS_CACHE)
    for key in ("scn2a_gain", "scn2a_loss", "syngap1"):
        for t in transfers_for(key, seed, claims):
            for text in [t.reason, *t.check_first, *t.what_differs]:
                assert denied_terms(text) == [], (key, t.asset_id, text)
                assert not any(d in text.lower() for d in DRUG_TERMS), (key, t.asset_id, text)


def test_missing_claims_cache_is_an_error_not_silence(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_accepted_claims(tmp_path / "nope.yaml")


# --- The demo card, pinned -------------------------------------------------------------------


def test_golden_scn2a_loss_transfers():
    """Regenerate with `make golden`, then read the diff: the golden file is a reviewed artefact."""
    seed, problems = load_seed()
    assert problems == []
    got = summary(card("scn2a_loss", seed, load_accepted_claims(CLAIMS_CACHE)))
    assert json.loads(GOLDEN.read_text()) == got
    by_id = {t["asset_id"]: t for t in got["transfers"]}
    first = got["transfers"][0]
    # dated, recruiting, shared by two communities: the plan's demo card stays first
    assert first["asset_id"] == "stxbp1_syngap1_natural_history" and first["status"] == "viable"
    assert first["crosses_gene"] is True and first["crosses_direction"] is False
    assert first["owner_org"] == "Children's Hospital of Philadelphia"
    assert first["nct"] == "NCT06555965"
    demo = first
    assert by_id["simons_searchlight_scn2a"]["status"] == "already_open"
    assert "simons_searchlight_syngap1" not in by_id and "citizen_health_syngap1" not in by_id
    for trial in ("embold_trial", "nct07019922_trial", "nct05737784_trial"):
        assert by_id[trial]["status"] == "not_shared" and by_id[trial]["blocked"] is True
        assert by_id[trial]["cited_pmid"] == "34287911"
    assert not any(t["blocked"] for t in got["transfers"] if t["asset_id"].endswith("syngap1"))
    assert got["stations"]["mechanism"] == "have" and got["stations"]["trial"] == "missing"
    assert demo["reason"].startswith(
        "STXBP1 and SYNGAP1 natural-history study (NCT06555965), run by"
    )
    assert by_id["embold_trial"]["reason"].startswith("Same gene, opposite problem: not matched")
    assert by_id["embold_trial"]["banner"].startswith("Same gene, opposite problem: your variant")
    assert by_id["rare_x_syngap1"]["status"] == "already_open"
    assert got["steps"]["missing"] == ["model", "trial"] and got["steps"]["borrowable"] == []
    assert got["steps"]["held"] == 5 and got["steps"]["mode"] == "steps"
    assert got["steps"]["sentence"].startswith("Your community already has 5 of 7 steps.")


def test_contradicting_assay_claim_contests_its_variant():
    claims = [
        claim("SCN8A", "p.Arg223Gly", "loss"),
        claim("SCN8A", "p.Arg223Gly", "gain", pmid="2", stance="contradicts"),
    ]
    scn8a_loss = line("scn8a_loss", "SCN8A", "sodium_channel", ION, Direction.LOSS)
    assert known_direction(scn8a_loss, claims) is Direction.UNKNOWN


def test_mixed_detection_works_across_variant_spellings():
    claims = [
        claim("SCN2A", "p.Arg853Gln", "loss"),
        claim("SCN2A", "R853Q", "gain", pmid="2"),
        claim("SCN2A", "p.R853Q", "loss", pmid="3"),
    ]
    assert known_direction(LINES[1], claims) is Direction.UNKNOWN


def test_platform_open_to_all_is_never_a_borrow():
    platform = Asset(
        id="rare_x",
        type=AssetType.REGISTRY,
        station=Station.REGISTRY,
        scope=Scope.GENE,
        owner_gene="STXBP1",
        label="RARE-X",
        open_to_all=True,
        source=SRC2,
    )
    t = rows("scn2a_loss", [platform])["rare_x"]
    assert t.status is TransferStatus.ALREADY_OPEN and "open to any rare-disease group" in t.reason


def test_every_transfer_string_is_short_enough_for_the_site():
    seed, _ = load_seed()
    claims = load_accepted_claims(CLAIMS_CACHE)
    for key in ("scn2a_gain", "scn2a_loss", "syngap1"):
        for t in transfers_for(key, seed, claims):
            for text in [
                t.reason,
                t.banner or "",
                t.basis_note or "",
                *t.check_first,
                *t.what_differs,
            ]:
                assert len(text) <= 400, (key, t.asset_id, len(text))

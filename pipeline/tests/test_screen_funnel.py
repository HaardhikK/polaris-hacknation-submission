"""The screen's pure rules on small fixtures: eligibility, family and direction filters,
evidence join, ordering, counts only."""

import json
from pathlib import Path

import pytest

from pipeline.screen import funnel
from pipeline.screen.config import SODIUM_CHANNEL_FAMILY

FIXTURES = Path(__file__).parent / "fixtures" / "screen"


@pytest.fixture
def pool():
    return json.loads((FIXTURES / "drug_pool.json").read_text())


@pytest.fixture
def evidence():
    return json.loads((FIXTURES / "evidence.json").read_text())


@pytest.fixture
def lines():
    return {row["key"]: row for row in json.loads((FIXTURES / "graph.json").read_text())["lines"]}


def names(cards):
    return [c["name"] for c in cards]


# --- Eligibility ------------------------------------------------------------------


def test_channel_line_with_direction_evidence_is_eligible(lines):
    assert funnel.eligibility(lines["scn2a_gain"]) is None
    assert funnel.eligibility(lines["scn2a_loss"]) is None


def test_non_channel_line_is_refused(lines):
    assert funnel.eligibility(lines["syngap1"]) == "not_a_channel_line"
    stxbp1 = {**lines["syngap1"], "key": "scn8a_dee"}
    assert funnel.eligibility(stxbp1) == "not_a_channel_line"


def test_scope_line_missing_from_the_graph_is_refused_with_that_reason(lines):
    absent = {**lines["scn2a_gain"], "key": "dravet", "in_graph": False}
    assert funnel.eligibility(absent) == "line_not_in_graph"


def test_line_whose_gene_has_no_fetched_evidence_is_refused(lines, pool, evidence):
    scn8a = {**lines["scn2a_gain"], "key": "scn8a_dee", "gene": "SCN8A"}
    assert funnel.eligibility(scn8a, evidence) == "evidence_not_fetched"
    assert funnel.screen_line(scn8a, pool, evidence)["refusal_reason"] == "evidence_not_fetched"
    assert funnel.eligibility(lines["scn2a_gain"], evidence) is None


def test_scn7a_is_not_in_the_family():
    assert "SCN7A" not in SODIUM_CHANNEL_FAMILY and len(SODIUM_CHANNEL_FAMILY) == 9


@pytest.mark.parametrize("direction", ["mixed", "unknown", "not_applicable"])
def test_mixed_or_unknown_direction_is_refused(lines, direction):
    line = {**lines["scn2a_gain"], "direction": direction}
    assert funnel.eligibility(line) == "direction_mixed_or_unknown"


def test_direction_without_code_checked_claim_is_refused(lines):
    assert funnel.eligibility(lines["scn8a_dee"]) == "direction_not_confirmed"
    line = {**lines["scn2a_gain"], "direction_evidence": {"level": "x", "pmid": ""}}
    assert funnel.eligibility(line) == "direction_not_confirmed"


def test_out_of_scope_key_is_refused_even_when_channel(lines):
    line = {**lines["scn2a_gain"], "key": "scn2a_other"}
    assert funnel.eligibility(line) == "line_not_in_screen_scope"


# --- Filters ----------------------------------------------------------------------


def test_family_filter_counts_non_family_drugs(pool):
    approved = funnel.approved_only(pool["drugs"])
    assert "PHASETWOINE" not in [d["name"] for d in approved]
    kept, removed = funnel.family_filter(approved, SODIUM_CHANNEL_FAMILY)
    assert removed == 1
    assert "OTHERGENIN" not in [d["name"] for d in kept]


def test_gain_line_keeps_blockers_and_removes_openers(pool):
    kept, removed = funnel.direction_filter(
        funnel.approved_only(pool["drugs"]), "gain", SODIUM_CHANNEL_FAMILY
    )
    assert sorted(d["name"] for d in kept) == ["ABLOCKER", "BLOCKADINE", "ZBLOCKER"]
    assert removed == {"wrong_direction": 1, "action_unclear": 3}


def test_loss_line_keeps_openers_and_removes_blockers(pool):
    in_family, _ = funnel.family_filter(funnel.approved_only(pool["drugs"]), SODIUM_CHANNEL_FAMILY)
    kept, removed = funnel.direction_filter(in_family, "loss", SODIUM_CHANNEL_FAMILY)
    assert [d["name"] for d in kept] == ["OPENOL"]
    assert removed == {"wrong_direction": 3, "action_unclear": 2}


def test_loss_line_with_only_blockers_passes_nothing(pool):
    blockers = [d for d in pool["drugs"] if d["name"] in ("BLOCKADINE", "ZBLOCKER")]
    kept, removed = funnel.direction_filter(blockers, "loss", SODIUM_CHANNEL_FAMILY)
    assert kept == []
    assert removed == {"wrong_direction": 2, "action_unclear": 0}


def test_modulator_only_is_action_unclear(pool):
    modulin = [d for d in pool["drugs"] if d["name"] == "MODULIN"]
    kept, removed = funnel.direction_filter(modulin, "gain", SODIUM_CHANNEL_FAMILY)
    assert kept == [] and removed["action_unclear"] == 1


def test_blocker_and_activator_on_family_targets_is_action_unclear(pool):
    mixamide = [d for d in pool["drugs"] if d["name"] == "MIXAMIDE"]
    for direction in ("gain", "loss"):
        kept, removed = funnel.direction_filter(mixamide, direction, SODIUM_CHANNEL_FAMILY)
        assert kept == [] and removed["action_unclear"] == 1


def test_unmapped_action_type_fails_closed():
    drug = {
        "drug_id": "CHEMBL9",
        "name": "NEWTYPE",
        "max_stage": "APPROVAL",
        "mechanisms": [{"action_type": "STABILISER", "target_genes": ["SCN2A"], "pmids": []}],
    }
    kept, removed = funnel.direction_filter([drug], "gain", SODIUM_CHANNEL_FAMILY)
    assert kept == [] and removed == {"wrong_direction": 0, "action_unclear": 1}


# --- Evidence join and ordering -----------------------------------------------------


def test_already_studied_when_a_pmid_or_nct_pairs_drug_and_gene(pool, evidence):
    by_name = {d["name"]: d for d in pool["drugs"]}
    card = funnel.card_for(by_name["BLOCKADINE"], "SCN2A", "gain", SODIUM_CHANNEL_FAMILY, evidence)
    assert card["state"] == "already_studied"
    assert card["evidence"]["pmids"] == ["222", "333"]
    assert card["evidence"]["studies"][0]["nct"] == "NCT00000001"
    assert card["evidence"]["opentargets_pmids"] == ["111"]
    nct_only = {"pairs": {"CHEMBL7|SCN2A": {"pubmed_count": 0, "pmids": [], "studies": [{}]}}}
    assert funnel.already_studied(by_name["ZBLOCKER"], "SCN2A", nct_only)


def test_paper_found_and_no_paper_found_states(pool, evidence):
    by_name = {d["name"]: d for d in pool["drugs"]}
    zblocker = funnel.card_for(
        by_name["ZBLOCKER"], "SCN2A", "gain", SODIUM_CHANNEL_FAMILY, evidence
    )
    assert zblocker["state"] == "no_paper_found"
    ot_only = {**by_name["ZBLOCKER"]}
    ot_only["mechanisms"] = [{**ot_only["mechanisms"][0], "pmids": ["555"]}]
    assert funnel.card_for(ot_only, "SCN2A", "gain", SODIUM_CHANNEL_FAMILY, evidence)["state"] == (
        "paper_found"
    )


def test_ordering_is_paper_count_then_name_never_benefit(pool, evidence):
    passed, _ = funnel.direction_filter(
        funnel.approved_only(pool["drugs"])[::-1], "gain", SODIUM_CHANNEL_FAMILY
    )
    cards = funnel.join_evidence(passed, "SCN2A", "gain", SODIUM_CHANNEL_FAMILY, evidence)
    assert names(cards) != ["BLOCKADINE", "ABLOCKER", "ZBLOCKER"]
    assert names(funnel.order(cards)) == ["BLOCKADINE", "ABLOCKER", "ZBLOCKER"]


def test_card_targets_are_the_kept_mechanisms_family_targets(pool, evidence):
    blockadine = next(d for d in pool["drugs"] if d["name"] == "BLOCKADINE")
    card = funnel.card_for(blockadine, "SCN2A", "gain", SODIUM_CHANNEL_FAMILY, evidence)
    assert card["targets"] == ["SCN1A", "SCN2A"] and card["effect"] == "reduces"
    assert card["target_level"] == "protein_family" and card["on_line_gene"] is True
    other_gene = funnel.card_for(blockadine, "SCN8A", "gain", SODIUM_CHANNEL_FAMILY, evidence)
    assert other_gene["on_line_gene"] is False


def test_family_effects_are_counts_by_mapped_effect(pool):
    in_family, _ = funnel.family_filter(funnel.approved_only(pool["drugs"]), SODIUM_CHANNEL_FAMILY)
    assert funnel.family_effects(in_family, SODIUM_CHANNEL_FAMILY) == {
        "reduces": 3,
        "increases": 1,
        "unclear": 2,
    }


# --- Whole line -------------------------------------------------------------------


def test_screened_line_has_counts_by_reason_and_no_removed_names(lines, pool, evidence):
    result = funnel.screen_line(lines["scn2a_gain"], pool, evidence)
    assert result["status"] == "screened"
    assert result["funnel"] == {
        "approved": 4000,
        "family": 6,
        "direction_pass": 3,
        "with_pair_paper": 2,
        "with_mechanism_reference_only": 0,
        "without_paper": 1,
        "on_line_gene": 3,
    }
    assert result["removed_by_reason"] == {
        "outside_the_channel_family": 3994,
        "wrong_direction": 1,
        "action_unclear": 2,
    }
    assert result["sanity_check"] == {"applicable": True, "surfaced": 2, "already_tried_total": 2}
    assert result["new_candidates"] == 1
    assert names(result["cards"]) == ["BLOCKADINE", "ABLOCKER", "ZBLOCKER"]
    assert result["cards_not_shown"] == 0 and result["cards_not_shown_reason"] is None
    assert result["cards_not_shown_by_state"] == {
        "already_studied": 0,
        "paper_found": 0,
        "no_paper_found": 0,
    }
    text = json.dumps(result)
    for removed in ("OPENOL", "MODULIN", "MIXAMIDE", "OTHERGENIN", "PHASETWOINE"):
        assert removed not in text


def test_loss_line_result_shows_the_direction_filter(lines, pool, evidence):
    result = funnel.screen_line(lines["scn2a_loss"], pool, evidence)
    assert result["funnel"]["direction_pass"] == 1
    assert names(result["cards"]) == ["OPENOL"]
    assert result["cards"][0]["state"] == "no_paper_found"
    assert result["new_candidates"] == 1
    assert "BLOCKADINE" not in json.dumps(result)


def test_a_pool_larger_than_the_approved_total_is_refused(lines, pool, evidence):
    with pytest.raises(ValueError, match="approved total"):
        funnel.screen_line(lines["scn2a_gain"], {**pool, "approved_total": 2}, evidence)


def test_sanity_check_is_not_applicable_when_nothing_passes(lines, pool, evidence):
    blockers_only = {**pool, "drugs": [d for d in pool["drugs"] if d["name"] != "OPENOL"]}
    result = funnel.screen_line(lines["scn2a_loss"], blockers_only, evidence)
    assert result["funnel"]["direction_pass"] == 0
    assert result["sanity_check"] == {"applicable": False, "surfaced": 0, "already_tried_total": 2}
    assert result["cards"] == [] and result["new_candidates"] == 0


def test_refused_line_has_reason_and_nothing_else(lines, pool, evidence):
    result = funnel.screen_line(lines["scn8a_dee"], pool, evidence)
    assert result["status"] == "refused"
    assert result["refusal_reason"] == "direction_not_confirmed"
    assert "cards" not in result and "funnel" not in result


def test_card_cap_reports_how_many_are_not_shown_and_counts_all_passing(
    lines, pool, evidence, monkeypatch
):
    monkeypatch.setattr(funnel, "MAX_CARDS_PER_LINE", 1)
    result = funnel.screen_line(lines["scn2a_gain"], pool, evidence)
    assert len(result["cards"]) == 1 and result["cards_not_shown"] == 2
    assert result["cards_not_shown_by_state"] == {
        "already_studied": 1,
        "paper_found": 0,
        "no_paper_found": 1,
    }
    assert "capped at 1 per line" in result["cards_not_shown_reason"]
    assert "same number of papers" in result["cards_not_shown_reason"]
    assert "the 2 not shown" in result["cards_not_shown_reason"]
    # the sanity check and the funnel count every passing drug, not only the shown cards
    assert result["sanity_check"]["surfaced"] == 2
    assert result["funnel"]["with_pair_paper"] == 2

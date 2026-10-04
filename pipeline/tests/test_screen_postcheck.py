"""Every rule of the post-check on crafted model answers: deny-list, other drug names,
uncited sentences moved, length, links, invented capitalised tokens, unknown items."""

import json

import pytest

from pipeline.denylist import SCREEN
from pipeline.screen import postcheck

LINE = {"key": "scn2a_gain", "gene": "SCN2A", "label": "SCN2A gain of function", "gloss": "g"}
CARD = {
    "drug_id": "CHEMBL1",
    "name": "BLOCKADINE",
    "action_type": "BLOCKER",
    "targets": ["SCN1A", "SCN2A"],
    "evidence": {
        "pmids": ["222", "333"],
        "opentargets_pmids": ["111"],
        "studies": [{"nct": "NCT00000001", "status": "TERMINATED"}],
    },
}
POOL_NAMES = {
    "CHEMBL1": {"BLOCKADINE", "Blockadine", "BKD", "blockadine 300 mg/5ml oral suspension"},
    "CHEMBL2": {"OPENOL", "Openol", "OPN", "openol 10 mg tablet"},
    "CHEMBL5": {"OTHERGENIN"},
}
APPROVED_NAMES = [
    "blockadine",
    "openol",
    "othergenin",
    "farawayzole",
    "vernakalant",
    "calcium",
    "tegretol",
    "tegretol xr",
]


def answer(why, doubts=None, drug_id="CHEMBL1", next_test="heterologous_channel_assay"):
    return {
        "items": [{"drug_id": drug_id, "why": why, "doubts": doubts or [], "next_test": next_test}]
    }


def check(ans):
    return postcheck.check_answer(ans, [CARD], LINE, POOL_NAMES, APPROVED_NAMES)


def problem(text):
    _, report = check(answer([{"text": text, "pmid": "222"}]))
    return next((k[len("rejected_") :] for k in report if k.startswith("rejected_")), None)


def test_clean_cited_sentences_pass_unchanged():
    ans = answer(
        [{"text": "Blockadine reduces Nav1.2 currents in heterologous cells.", "pmid": "222"}],
        [{"text": "The paper studied SCN1A rather than SCN2A.", "pmid": "333"}],
    )
    checked, report = check(ans)
    item = checked["CHEMBL1"]
    assert item["why"] == [
        {"text": "Blockadine reduces Nav1.2 currents in heterologous cells.", "pmid": "222"}
    ]
    assert item["doubts"][0]["pmid"] == "333"
    assert item["unchecked_reasoning"] == []
    assert item["next_test"] == "heterologous_channel_assay"
    assert report["kept"] == 2 and report["rejected"] == 0 and report["moved"] == 0


@pytest.mark.parametrize("term", SCREEN)
def test_every_screen_deny_list_word_rejects_the_sentence(term):
    text = f"The mechanism is {term} in the cited paper."
    checked, report = check(answer([{"text": text, "pmid": "222"}]))
    assert checked["CHEMBL1"]["why"] == [], term
    assert report["rejected_denied_word"] == 1


def test_sentence_naming_another_pool_drug_is_rejected_even_when_cited():
    for other in ("Openol", "OPENOL", "othergenin"):
        text = f"Unlike {other}, this mechanism lowers the current."
        checked, report = check(answer([{"text": text, "pmid": "222"}]))
        assert checked["CHEMBL1"]["why"] == [], other
        assert report["rejected_other_drug_named"] == 1


def test_sentence_naming_any_approved_or_blocklisted_drug_is_rejected():
    for other in ("farawayzole", "Farawayzole", "cannabidiol", "PRAX-222", "valproic acid"):
        text = f"The effect resembles {other} in the cited cells."
        checked, report = check(answer([{"text": text, "pmid": "222"}]))
        assert checked["CHEMBL1"]["why"] == [], other
        assert report["rejected_other_drug_named"] == 1


def test_generic_substances_in_the_approved_list_do_not_block_sentences():
    text = "The current fell with less calcium entry in the cited cells."
    checked, report = check(answer([{"text": text, "pmid": "222"}]))
    assert report["rejected_other_drug_named"] == 0 and len(checked["CHEMBL1"]["why"]) == 1


def test_three_letter_synonyms_and_dose_strings_do_not_block_sentences():
    text = "The opn channel current fell in the cited cells."
    checked, report = check(answer([{"text": text, "pmid": "222"}]))
    assert report["rejected_other_drug_named"] == 0
    assert len(checked["CHEMBL1"]["why"]) == 1
    assert not postcheck.drug_shaped("OPN")
    assert not postcheck.drug_shaped("openol 10 mg tablet")
    assert postcheck.drug_shaped("Openol")


def test_dose_string_synonyms_contribute_their_brand_word():
    others = postcheck.other_drug_names("CHEMBL1", POOL_NAMES, APPROVED_NAMES)
    assert "openol" in others and "openol 10 mg tablet" not in others
    assert "tegretol" in others and "blockadine" not in others


def test_own_name_and_synonyms_are_allowed():
    text = "Blockadine, also listed as BKD, lowers the current in Nav1.2 cells."
    checked, _ = check(answer([{"text": text, "pmid": "222"}]))
    assert len(checked["CHEMBL1"]["why"]) == 1


def test_uncited_or_wrongly_cited_sentences_move_to_unchecked_reasoning():
    ans = answer(
        [
            {"text": "A gain variant may respond differently from the wild type.", "pmid": None},
            {"text": "The current was lower in the cited cells.", "pmid": "999"},
        ]
    )
    checked, report = check(ans)
    item = checked["CHEMBL1"]
    assert item["why"] == []
    assert item["unchecked_reasoning"] == [
        "A gain variant may respond differently from the wild type.",
        "The current was lower in the cited cells.",
    ]
    assert report["moved"] == 2


def test_opentargets_reference_pmid_counts_as_cited():
    checked, _ = check(answer([{"text": "The current was lower.", "pmid": "111"}]))
    assert checked["CHEMBL1"]["why"][0]["pmid"] == "111"


def test_long_sentence_and_links_are_rejected():
    long = "The current was lower " * 30
    for text in (long, "See https://example.org for the data.", "See www.example.org now."):
        checked, report = check(answer([{"text": text, "pmid": "222"}]))
        assert checked["CHEMBL1"]["why"] == []
        assert report["rejected_length_or_link"] == 1
    checked, report = check(answer([{"text": "Markup <b>here</b> in the text.", "pmid": "222"}]))
    assert report["rejected_length_or_link"] == 1


def test_capitalised_token_not_in_the_facts_is_rejected():
    text = "The Smithfield assay showed lower current."
    checked, report = check(answer([{"text": text, "pmid": "222"}]))
    assert checked["CHEMBL1"]["why"] == []
    assert report["rejected_unknown_capitalised_token"] == 1


def test_capitalised_tokens_from_names_targets_family_and_line_are_allowed():
    text = "Under Blockadine, Nav1.2, SCN2A-related and SCN8A currents fell in HEK293 cells."
    checked, _ = check(answer([{"text": text, "pmid": "222"}]))
    assert len(checked["CHEMBL1"]["why"]) == 1


def test_title_words_are_not_facts_and_all_caps_or_mixed_case_tokens_are_checked():
    assert problem("The current fell in Heterologous cells.") == "unknown_capitalised_token"
    assert problem("The current fell with KEPPRA.") == "unknown_capitalised_token"
    assert problem("The current fell, said McDonald.") == "unknown_capitalised_token"
    assert problem("The current fell. Then it rose.") == "unknown_capitalised_token"  # one sentence
    assert problem("The current fell, e.g. Zorvex does too.") == "unknown_capitalised_token"
    assert problem("Results by J. Smith suggest a lower current.") == "unknown_capitalised_token"
    assert problem("As reported by Wu the current fell.") == "unknown_capitalised_token"


def test_round_two_bypasses_are_closed():
    assert problem("Parents could give two tablets of it.") == "denied_word"
    assert problem("Give 10 milligrams nightly to lower the current.") == "denied_word"
    assert problem("It is well tolerated in infants.") == "denied_word"
    assert problem("Unlike zorbatri\u034fgine, it blocks the channel.") == "non_ascii"
    assert problem("The current fell with ope'nol.") == "other_drug_named"
    assert problem("The current fell with xen 1101.") == "other_drug_named"
    assert problem("The current fell with bexicaserin.") == "other_drug_named"
    assert problem("Call 555 123 4567 for the data.") == "length_or_link"
    assert problem("See info at scn2a dot org for the data.") == "denied_word"
    assert problem("[click](javascript:alert(1)) lowers the current.") == "length_or_link"
    assert problem("The current fell in murine slices and peptide assays today.") is None


def test_person_titles_and_name_like_pairs_are_rejected():
    assert problem("As Dr. Smith showed, the current fell.") == "person_like"
    assert problem("The current fell. Prof. Alan Turing agreed.") == "person_like"
    assert problem("The study by Jane Doe found lower current.") == "person_like"
    assert problem("Open Targets lists the mechanism as a blocker.") is None


def test_ids_outside_the_card_evidence_are_rejected():
    assert problem("In the trial NCT05737784 the current fell.") == "unknown_id"
    assert problem("In the trial NCT00000001 the current fell.") is None
    assert problem("As PMID 12345678 shows, the current fell.") == "unknown_id"


def test_look_alike_and_zero_width_text_is_rejected():
    assert problem("The current fell with Op\u200benol.") == "non_ascii"
    assert problem("The current fell with Op\u0435nol.") == "non_ascii"  # Cyrillic e
    assert problem("Ｏpenol lowers the current.") == "other_drug_named"  # NFKC folds it


def test_names_split_by_hyphens_spaces_or_trailing_digits_are_caught():
    assert problem("The current fell with Open-ol.") == "other_drug_named"
    assert problem("The current fell with Open ol.") == "other_drug_named"
    assert problem("The current fell with openol2.") == "other_drug_named"
    assert problem("The current fell with Tegretol XR.") == "other_drug_named"
    assert problem("The current fell with tegretol.") == "other_drug_named"


def test_drug_shaped_tokens_and_development_codes_are_rejected_unless_own():
    assert problem("The current fell with azetukalner.") == "other_drug_named"
    assert problem("The current fell with lamotrigine.") == "other_drug_named"
    assert problem("The current fell with XEN-1101.") == "other_drug_named"
    assert problem("The current fell with ab12345.") == "other_drug_named"
    assert problem("Blockadine lowers the current in HEK293 cells.") is None


def test_bare_domains_and_lay_dosing_words_are_rejected():
    assert problem("See scn2a.org/contact for details.") == "length_or_link"
    assert problem("Parents may give two tablets twice daily at home.") == "denied_word"


def test_kept_sentences_start_with_a_capital_letter():
    checked, _ = check(answer([{"text": "the current fell in Nav1.2 cells.", "pmid": "222"}]))
    assert checked["CHEMBL1"]["why"][0]["text"] == "The current fell in Nav1.2 cells."


def test_doubt_kind_is_kept_when_fixed_and_defaults_to_other():
    doubts = [
        {"text": "The paper studied SCN1A rather than SCN2A.", "pmid": "333", "kind": "x"},
        {
            "text": "The title does not state the direction.",
            "pmid": "333",
            "kind": "no_direction_in_source",
        },
    ]
    checked, report = check(answer([], doubts))
    kinds = [d["kind"] for d in checked["CHEMBL1"]["doubts"]]
    assert kinds == ["other", "no_direction_in_source"]
    assert report["doubt_kind_defaulted"] == 1
    assert "kind" not in checked["CHEMBL1"]["why"]  # why sentences carry no kind


def test_item_for_a_drug_not_on_a_card_is_dropped():
    checked, report = check(answer([{"text": "x y z.", "pmid": "222"}], drug_id="CHEMBL2"))
    assert checked == {} and report["items_dropped"] == 1


def test_next_test_outside_the_fixed_list_is_dropped():
    checked, report = check(answer([], next_test="ask_a_clinician"))
    assert checked["CHEMBL1"]["next_test"] is None and report["next_test_dropped"] == 1


def test_report_is_counts_only():
    checked, report = check(answer([{"text": "Unlike Openol, no.", "pmid": "222"}]))
    assert all(isinstance(v, int) for v in report.values())
    assert "Openol" not in json.dumps(report)

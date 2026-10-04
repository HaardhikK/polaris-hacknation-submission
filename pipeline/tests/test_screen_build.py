"""The build's refusals and invariants, on fixtures copied to a temp folder (the build itself
refuses any path under tests/)."""

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipeline.denylist import denied_terms
from pipeline.screen import build, funnel
from pipeline.screen.batches import batch_sha256
from pipeline.screen.models import Card, Critique, Screen, ScreenLine

build.CRITIQUE_REASONS = build.CRITIQUE_REASONS  # re-exported constant used below

FIXTURES = Path(__file__).parent / "fixtures" / "screen"
REMOVED = ("OPENOL", "MODULIN", "MIXAMIDE", "OTHERGENIN", "PHASETWOINE")
EXEMPT_META = {"interstitial", "medication_warning"}


def bind_critique(paths: dict) -> None:
    """Point the fixture critique at the batch the fixture caches produce (as a real run would)."""
    graph = json.loads(paths["graph.json"].read_text())
    pool = json.loads(paths["drug_pool.json"].read_text())
    evidence = json.loads(paths["evidence.json"].read_text())
    lines, _ = build.screen_lines(graph)
    gain = next(line for line in lines if line["key"] == "scn2a_gain")
    result = funnel.screen_line(gain, pool, evidence)
    critique = json.loads(paths["critique.json"].read_text())
    line = critique["lines"]["scn2a_gain"]
    line["provenance"]["input_manifest_sha256"] = batch_sha256(result, evidence["titles"])
    line["items_sha256"] = build.items_sha256(line["items"], line["provenance"])
    paths["critique.json"].write_text(json.dumps(critique))


@pytest.fixture
def inputs(tmp_path):
    """Fixture files copied outside tests/, keyed by name, with the critique bound to its batch."""
    paths = {}
    for name in (
        "graph.json",
        "graph_mock.json",
        "drug_pool.json",
        "evidence.json",
        "critique.json",
    ):
        paths[name] = tmp_path / name
        shutil.copy(FIXTURES / name, paths[name])
    bind_critique(paths)
    return paths


def run(inputs, graph="graph.json", pool="drug_pool.json", evidence="evidence.json"):
    return build.build(inputs[graph], inputs[pool], inputs[evidence], inputs["critique.json"])


def edit_critique(inputs, change):
    critique = json.loads(inputs["critique.json"].read_text())
    change(critique["lines"]["scn2a_gain"])
    inputs["critique.json"].write_text(json.dumps(critique))


# --- Refusals -----------------------------------------------------------------------


def test_refuses_a_graph_that_is_not_real_data(inputs):
    with pytest.raises(build.BuildRefused, match="not 'real'"):
        run(inputs, graph="graph_mock.json")


def test_refuses_any_input_path_under_tests(inputs):
    with pytest.raises(build.BuildRefused, match="tests/"):
        build.build(
            FIXTURES / "graph.json",
            inputs["drug_pool.json"],
            inputs["evidence.json"],
            inputs["critique.json"],
        )


@pytest.mark.parametrize("missing", ["release", "retrieved"])
def test_refuses_a_pool_cache_without_release_or_retrieved(inputs, missing):
    pool = json.loads(inputs["drug_pool.json"].read_text())
    pool.pop(missing)
    inputs["drug_pool.json"].write_text(json.dumps(pool))
    with pytest.raises(build.BuildRefused, match="release or retrieved"):
        run(inputs)


@pytest.mark.parametrize("missing", ["approved_total_method", "chembl_version"])
def test_refuses_a_pool_cache_without_its_method_or_chembl_version(inputs, missing):
    pool = json.loads(inputs["drug_pool.json"].read_text())
    pool.pop(missing)
    inputs["drug_pool.json"].write_text(json.dumps(pool))
    with pytest.raises(build.BuildRefused, match="method or ChEMBL"):
        run(inputs)


def test_refuses_an_evidence_cache_without_retrieved(inputs):
    evidence = json.loads(inputs["evidence.json"].read_text())
    del evidence["retrieved"]
    inputs["evidence.json"].write_text(json.dumps(evidence))
    with pytest.raises(build.BuildRefused, match="retrieved"):
        run(inputs)


def test_refuses_a_critique_whose_items_were_edited(inputs):
    def edit(line):
        line["items"]["CHEMBL1"]["why"][0]["text"] = "Blockadine is the best choice."

    edit_critique(inputs, edit)
    with pytest.raises(build.BuildRefused, match="items_sha256"):
        run(inputs)


def test_refuses_a_critique_without_its_digest(inputs):
    edit_critique(inputs, lambda line: line.pop("items_sha256"))
    with pytest.raises(build.BuildRefused, match="items_sha256"):
        run(inputs)


@pytest.mark.parametrize("field,value", [("step", "extract_claims"), ("agent", "gpt-oss-20b")])
def test_refuses_a_critique_from_another_step_or_agent(inputs, field, value):
    def edit(line):
        line["provenance"][field] = value
        line["items_sha256"] = build.items_sha256(line["items"], line["provenance"])

    edit_critique(inputs, edit)
    with pytest.raises(build.BuildRefused, match="another step or agent"):
        run(inputs)


def test_refuses_a_critique_whose_provenance_was_edited_or_is_prose(inputs):
    edit_critique(
        inputs, lambda line: line["provenance"].__setitem__("run_at", "2026-10-04T07:00:01Z")
    )
    with pytest.raises(build.BuildRefused, match="items_sha256"):
        run(inputs)

    def prose(line):
        line["provenance"]["model"] = "gpt Jane Doe <script>"
        line["items_sha256"] = build.items_sha256(line["items"], line["provenance"])

    edit_critique(inputs, prose)
    with pytest.raises(build.BuildRefused, match="not an id"):
        run(inputs)
    edit_critique(inputs, lambda line: line.pop("provenance"))
    with pytest.raises(build.BuildRefused, match="no valid provenance"):
        run(inputs)


def test_unavailable_reason_is_a_code_mapped_to_a_fixed_sentence(inputs):
    critique = json.loads(inputs["critique.json"].read_text())
    critique["lines"]["scn2a_gain"] = {"unavailable": "rejected_by_code_check"}
    inputs["critique.json"].write_text(json.dumps(critique))
    gain = next(line for line in run(inputs).lines if line.key == "scn2a_gain")
    assert gain.cards[0].critique.reason == build.CRITIQUE_REASONS["rejected_by_code_check"]
    critique["lines"]["scn2a_gain"] = {"unavailable": "see https://x.org or call Dr. Doe"}
    inputs["critique.json"].write_text(json.dumps(critique))
    with pytest.raises(build.BuildRefused, match="unknown unavailable reason"):
        run(inputs)


def test_critique_whose_facts_changed_is_dropped_with_the_reason(inputs):
    evidence = json.loads(inputs["evidence.json"].read_text())
    evidence["titles"]["222"] = "A new title for the same paper"
    inputs["evidence.json"].write_text(json.dumps(evidence))
    screen = run(inputs)
    gain = next(line for line in screen.lines if line.key == "scn2a_gain")
    assert all(card.critique.status == "not_available" for card in gain.cards)
    assert gain.cards[0].critique.reason == build.CRITIQUE_STALE


def _reasons(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "reason" and isinstance(v, str):
                yield v
            else:
                yield from _reasons(v)
    elif isinstance(node, list):
        for v in node:
            yield from _reasons(v)


def test_reasons_are_reader_sentences_not_developer_instructions(inputs):
    """No fallback reason tells the reader to run a command, here or in the shipped file."""
    shipped = build.SCREEN_OUT
    sources = [
        list(build.CRITIQUE_REASONS.values()),
        list(_reasons(json.loads(build.dumps(run(inputs))))),
    ]
    if shipped.exists():
        sources.append(list(_reasons(json.loads(shipped.read_text()))))
    for reasons in sources:
        for reason in reasons:
            assert "make " not in reason and "re-run" not in reason.lower(), reason
            assert "\u2014" not in reason, reason
    for sentence in build.CRITIQUE_REASONS.values():
        assert sentence[0].isupper() and sentence.endswith("."), sentence


# --- Output -----------------------------------------------------------------------


def test_output_validates_is_real_and_reproducible(inputs):
    first = build.dumps(run(inputs))
    second = build.dumps(run(inputs))
    assert first == second
    screen = Screen.model_validate(json.loads(first))
    assert screen.meta.source == "real"
    assert screen.meta.open_targets_release == "26.09"
    assert screen.meta.direction_source == "graph_direction_evidence"
    assert [line.key for line in screen.lines] == [
        "scn2a_gain",
        "scn2a_loss",
        "scn8a_dee",
        "dravet",
        "syngap1",
    ]


def test_meta_labels_the_file_with_the_plan_copy_and_the_method(inputs):
    meta = run(inputs).meta
    assert meta.interstitial.startswith("This page lists approved medicines")
    assert meta.medication_warning.startswith("Not medical advice.")
    assert meta.hypothesis_label == "Hypothesis for laboratory testing, not medical advice"
    assert meta.already_studied_caption == "Already studied for this gene: not a new idea"
    assert meta.evidence_read == "title only"
    assert meta.target_level == "protein_family" and "SCN7A" not in meta.family_genes
    assert meta.approved_total_method.startswith("fixture") and meta.chembl_version == "ChEMBL_37"
    assert meta.family_effects.model_dump() == {"reduces": 3, "increases": 1, "unclear": 2}
    assert meta.family_direction_note.startswith("Of the 6 approved medicines")
    assert meta.studies_found == 1
    assert "esters are separate molecules" not in meta.approved_total_method  # fixture text
    assert meta.sanity_check_note.startswith("already_tried_total counts")
    assert "lower bound" in meta.family_coverage_note
    assert set(meta.next_test_labels) == {
        "heterologous_channel_assay",
        "patient_derived_neuron_electrophysiology",
        "mouse_model_seizure_assay",
        "literature_review_first",
    }
    assert set(meta.doubt_kind_labels) == {
        "no_direction_in_source",
        "different_gene_of_family",
        "different_variant_direction",
        "model_system_or_species",
        "not_a_drug_test",
        "other",
    }
    assert "not by expected benefit" in meta.ordering_rule
    assert any("ChEMBL" in s for s in meta.sources)


def test_no_drug_removed_by_a_line_is_named_in_that_line(inputs):
    screen = run(inputs)
    removed_by_line = {
        "scn2a_gain": REMOVED,
        "scn2a_loss": ("BLOCKADINE", "ZBLOCKER", "ABLOCKER") + REMOVED[1:],
    }
    for line in screen.lines:
        text = line.model_dump_json().upper()
        for name in removed_by_line.get(line.key, REMOVED):
            assert name not in text, (line.key, name)
    assert "FARAWAYZOLE" not in build.dumps(screen).upper()  # the global list is never emitted


def test_refused_lines_carry_a_reason_and_no_cards(inputs):
    screen = run(inputs)
    by_key = {line.key: line for line in screen.lines}
    assert by_key["scn8a_dee"].refusal_reason == "direction_not_confirmed"
    assert by_key["dravet"].refusal_reason == "line_not_in_graph"
    assert by_key["dravet"].gene == "SCN1A" and by_key["dravet"].direction.value == "unknown"
    assert by_key["dravet"].label == "Dravet syndrome (SCN1A)"
    assert by_key["dravet"].gloss == "not in the shipped graph file yet"
    assert by_key["syngap1"].refusal_reason == "not_a_channel_line"
    for key in ("scn8a_dee", "dravet", "syngap1"):
        assert by_key[key].status == "refused"
        assert by_key[key].cards == [] and by_key[key].funnel is None


def test_every_card_pmid_comes_from_the_evidence_or_open_targets(inputs):
    evidence = json.loads(inputs["evidence.json"].read_text())
    pool = json.loads(inputs["drug_pool.json"].read_text())
    known = {p for pair in evidence["pairs"].values() for p in pair["pmids"]}
    known |= {p for d in pool["drugs"] for m in d["mechanisms"] for p in m["pmids"]}
    for line in run(inputs).lines:
        for card in line.cards:
            cited = set(card.evidence.pmids) | set(card.evidence.opentargets_pmids)
            cited |= {s.pmid for s in card.critique.why + card.critique.doubts}
            assert cited <= known, card.name


def test_committed_critique_is_post_checked_again_at_build(inputs):
    screen = run(inputs)
    gain = next(line for line in screen.lines if line.key == "scn2a_gain")
    blockadine = next(card for card in gain.cards if card.name == "BLOCKADINE")
    critique = blockadine.critique
    assert critique.status == "checked_by_code" and critique.provenance.agent == "codex"
    assert critique.evidence_read == "title only"
    assert [s.text for s in critique.why] == [
        "Blockadine reduces Nav1.2 currents in heterologous cells."
    ]  # the sentence naming another pool drug is gone
    assert critique.doubts[0].kind == "different_gene_of_family"
    assert critique.unchecked_reasoning == [
        "A gain variant may respond differently from the wild type channel."
    ]
    assert critique.next_test == "heterologous_channel_assay"
    others = [card for card in gain.cards if card.name != "BLOCKADINE"]
    assert all(card.critique.status == "not_available" for card in others)
    assert all(card.critique.reason for card in others)


def test_cards_carry_target_level_and_on_line_gene(inputs):
    gain = next(line for line in run(inputs).lines if line.key == "scn2a_gain")
    by_name = {card.name: card for card in gain.cards}
    assert all(card.target_level == "protein_family" for card in gain.cards)
    assert by_name["BLOCKADINE"].on_line_gene is True


def test_lines_without_a_critique_run_say_so(inputs):
    screen = run(inputs)
    loss = next(line for line in screen.lines if line.key == "scn2a_loss")
    assert loss.cards[0].critique.status == "not_available"
    assert loss.cards[0].critique.reason == build.CRITIQUE_MISSING


def walk(node, path="$", key=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}", k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]", key)
    elif isinstance(node, str):
        yield path, key, node


def test_no_screen_deny_list_word_outside_the_exempt_paths(inputs):
    payload = json.loads(build.dumps(run(inputs)))
    for path, key, text in walk(payload):
        if key == "why_stopped" or (path.startswith("$.meta.") and key in EXEMPT_META):
            continue
        assert denied_terms(text, "screen") == [], (path, text)


def test_build_falls_back_to_the_engine_rule_when_graph_has_no_direction_evidence(
    inputs, monkeypatch
):
    graph = json.loads(inputs["graph.json"].read_text())
    for line in graph["lines"]:
        line.pop("direction_evidence", None)
    inputs["graph.json"].write_text(json.dumps(graph))
    monkeypatch.setattr(
        build,
        "known_direction_evidence",
        lambda: {"scn2a_gain": {"level": "checked by code", "pmid": "31558572", "variant": "x"}},
    )
    screen = run(inputs)
    assert screen.meta.direction_source == "known_direction"
    by_key = {line.key: line for line in screen.lines}
    assert by_key["scn2a_gain"].status == "screened"
    assert by_key["scn2a_loss"].status == "refused"


# --- Models -----------------------------------------------------------------------


def test_models_reject_unknown_keys_and_bad_shapes():
    with pytest.raises(ValidationError):
        Card.model_validate({"drug_id": "CHEMBL1", "unknown": 1})
    with pytest.raises(ValidationError, match="names its reason"):
        ScreenLine.model_validate(
            {
                "key": "scn2a_gain",
                "label": "x",
                "gloss": "x",
                "gene": "SCN2A",
                "direction": "gain",
                "status": "refused",
            }
        )
    with pytest.raises(ValidationError):
        Critique.model_validate({"status": "checked_by_code", "next_test": "ask_a_clinician"})
    with pytest.raises(ValidationError, match="carries no text"):
        Critique.model_validate(
            {"status": "not_available", "reason": "x", "unchecked_reasoning": ["y"]}
        )


# --- check-public on screen.json ------------------------------------------------------


def test_check_public_exempts_only_the_verbatim_and_fixed_copy_paths(tmp_path):
    from pipeline import check_public

    doc = {
        "meta": {
            "interstitial": "Never start, stop or change a medicine.",
            "medication_warning": "Never change or stop a medication.",
            "ordering_rule": "ordered by a fixed rule, not by expected benefit",
        },
        "lines": [
            {
                "cards": [
                    {
                        "evidence": {"studies": [{"why_stopped": "Sponsor safety decision"}]},
                        "critique": {"why": [{"text": "The safety was not assessed."}]},
                    }
                ],
                "why_stopped": "safety",  # the key alone does not exempt a string
            }
        ],
    }
    path = tmp_path / "screen.json"
    path.write_text(json.dumps(doc))
    problems = check_public.check_file(path, [])
    denied = [p for p in problems if "denied word" in p]
    assert len(denied) == 2
    assert any("$.lines[0].cards[0].critique.why[0].text" in p for p in denied)
    assert any("$.lines[0].why_stopped" in p for p in denied)


# --- evidence stripping ------------------------------------------------------------


def test_stop_reasons_that_may_name_a_person_are_withheld():
    from pipeline.screen.evidence import looks_like_a_name, strip_study

    assert looks_like_a_name("Dr. Smith left the site")
    assert looks_like_a_name("Jane Doe moved")
    assert looks_like_a_name("PI JANE DOE LEFT")
    assert not looks_like_a_name("Sponsor decision")
    assert not looks_like_a_name("Inclusion Criteria changed")
    record = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000001", "officialTitle": "x"},
            "statusModule": {
                "overallStatus": "TERMINATED",
                "whyStopped": "Investigator Jane Doe retired",
                "startDateStruct": {"date": "2019-01"},
                "lastUpdatePostDateStruct": {"date": "2021-03-02"},
            },
            "contactsLocationsModule": {"centralContacts": [{"name": "x"}]},
        }
    }
    study = strip_study(record)
    assert study == {
        "nct": "NCT00000001",
        "status": "TERMINATED",
        "why_stopped": None,
        "why_stopped_withheld": True,
        "start_date": "2019-01",
        "last_update": "2021-03-02",
    }

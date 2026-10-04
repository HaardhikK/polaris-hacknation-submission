"""graph.json: the contract, its invariants, reproducibility and the demo-path data."""

import json
from datetime import date
from pathlib import Path

import jsonschema
import pytest

from pipeline.denylist import denied_terms
from pipeline.explain import facts_sha256
from pipeline.graph import (
    BADGE,
    GRAPH_FILE,
    SCHEMA_FILE,
    GraphFile,
    build_cards,
    build_graph,
    cluster_groups,
    dump,
    emitted_aliases,
    render,
    render_schema,
    symptom_aliases,
    texts_for,
)
from pipeline.schema import (
    DIRECTION_GATED_TYPES,
    AcceptedClaim,
    Alias,
    AliasKind,
    Direction,
    SymptomRow,
)
from pipeline.seed_check import load_seed
from pipeline.transfer import load_accepted_claims


@pytest.fixture(scope="module")
def graph() -> GraphFile:
    return build_graph()


@pytest.fixture(scope="module")
def doc(graph) -> dict:
    return dump(graph)


def claim(pmid="34287911", variant="p.Arg853Gln", direction=Direction.LOSS, **kw) -> AcceptedClaim:
    base = dict(
        pmid=pmid,
        gene="SCN2A",
        claim_level="variant",
        variant=variant,
        direction=direction,
        stance="supports",
        basis="functional-assay",
        evidence_quote="x" * 20,
        claim_id=f"{pmid}:{variant}:{direction}",
        extractor_run_id="r",
        agent="codex",
        model="m",
    )
    return AcceptedClaim(**{**base, **kw})


def test_committed_graph_and_schema_are_current(graph):
    assert GRAPH_FILE.read_text() == render(graph), "run make build"
    assert SCHEMA_FILE.read_text() == render_schema(), "run make build"


def test_render_is_byte_reproducible():
    assert render(build_graph()) == render(build_graph())


def test_graph_matches_its_own_json_schema(doc):
    schema = json.loads(render_schema())
    jsonschema.Draft202012Validator(schema).validate(doc)


def test_meta_is_real_and_counts_match(doc):
    meta = doc["meta"]
    assert meta["source"] == "real" and meta["generator"] == "polaris pipeline"
    assert meta["badge"] == BADGE
    assert date.fromisoformat(meta["built"]) <= date.today()
    assert date.fromisoformat(meta["pre_computed"]) >= date.fromisoformat(meta["built"])
    c = meta["counts"]
    assert c["lines"] == len(doc["lines"]) == 7
    assert c["claims"] == len(doc["claims"]) == 51
    assert c["papers"] == len(doc["papers"])
    assert c["edges"] == len(doc["edges"])
    assert c["texts_codex"] + c["texts_template"] == len(doc["texts"])
    assert {s["key"] for s in meta["sources"]} == {"pubmed", "ctgov", "hpo", "orphadata", "g2p"}
    assert "Not medical advice" in meta["footer"] and meta["pre_computed"] in meta["footer"]
    assert meta["about_notice"] == (
        f"Not medical advice. Data and AI text pre-computed {meta['pre_computed']}."
    )


def test_cluster_groups_follow_the_state_copy_table(doc):
    groups = {g["key"]: g for g in doc["meta"]["cluster_groups"]}
    assert groups["sodium_channel_loss"]["line_keys"] == ["dravet", "scn2a_loss"]
    assert groups["sodium_channel_gain"]["line_keys"] == ["scn2a_gain", "scn8a_dee"]
    assert groups["sodium_channel_gain"]["label"] == "Sodium channel: works too strongly"
    assert groups["non_channel"]["line_keys"] == ["cdkl5", "stxbp1", "syngap1"]
    assert all(g["caption"].startswith("Groups set by hand") for g in groups.values())
    assert [g["key"] for g in doc["meta"]["cluster_groups"]] == [
        "sodium_channel_gain",
        "sodium_channel_loss",
        "non_channel",
    ]


def test_direction_evidence_shape_and_non_channel_null(doc):
    lines = {ln["key"]: ln for ln in doc["lines"]}
    ev = lines["scn2a_loss"]["direction_evidence"]
    assert set(ev) == {"level", "pmid", "variant", "quote", "claim_id"}
    assert ev["level"] == "checked by code"
    assert ev["pmid"] == "34287911" and ev["variant"] == "p.Arg853Gln"
    assert lines["scn2a_loss"]["direction_known"] == "loss"
    assert lines["scn2a_gain"]["direction_evidence"]["pmid"] in {"20956790", "38544375"}
    assert lines["syngap1"]["direction_evidence"] is None
    assert lines["syngap1"]["direction_known"] == "not_applicable"
    assert "database label" in lines["syngap1"]["mechanism_label"]
    assert lines["scn2a_loss"]["direction_step"] and not lines["syngap1"]["direction_step"]


def test_coverage_counts_every_fetched_paper_naming_the_gene(doc):
    lines = {ln["key"]: ln for ln in doc["lines"]}
    cov = lines["scn2a_loss"]["coverage"]
    assert cov["esearch_term"].startswith("SCN2A[Title/Abstract]")
    assert "34287911" in cov["pmids_searched"] and "36027690" in cov["pmids_searched"]
    assert cov["papers_mentioning_gene"] == len(cov["pmids_searched"]) >= 40
    assert 0 < cov["papers_extracted"] <= cov["papers_mentioning_gene"]
    assert lines["syngap1"]["coverage"]["esearch_term"] is None
    assert lines["syngap1"]["coverage"]["papers_mentioning_gene"] >= 1


def test_paper_nodes_cover_every_cited_pmid_and_hold_no_abstract(doc):
    pmids = {p["pmid"] for p in doc["papers"]}
    assert {c["pmid"] for c in doc["claims"]} <= pmids
    assert "34287911" in pmids and "40336930" in pmids  # claim PMID; asset paper
    for p in doc["papers"]:
        assert set(p) <= {"pmid", "title", "journal", "year", "doi", "genes_mentioned", "retrieved"}


def test_demo_card_data_is_in_the_graph(doc):
    card = doc["transfers"]["scn2a_loss"]
    assert card["direction"] == "loss"
    assert card["steps"]["held"] == 5 and card["steps"]["missing"] == ["model", "trial"]
    assert card["steps"]["borrowable"] == [] and card["steps"]["mode"] == "steps"
    assert "5 of 7" in card["steps"]["sentence"]
    assert card["banner"].startswith("Same gene, opposite problem")
    assert card["banner_parts"]["heading"] == "Same gene, opposite problem"
    assert card["banner_parts"]["body"].startswith("Your variant makes the channel work too weakly")
    assert card["banner_parts"]["body"].endswith(
        "Registries and care networks can still be shared."
    )
    # dated and recruiting records first, then resources shared by more communities: the plan's
    # demo card leads; stopped studies never show
    assert card["top_cards"] == [
        "stxbp1_syngap1_natural_history",
        "stxbp1_european_readiness_study",
        "cdd_hand_measure",
    ]
    assert [t["card_type"] for t in card["top_cards_typed"]] == ["borrow"] * 3
    viable = [t["asset_id"] for t in card["transfers"] if t["status"] == "viable"]
    assert "stxbp1_syngap1_natural_history" in viable
    assert "envision_natural_history" not in viable  # terminated: Level 2 only
    # another community's stopped study is its own "Tried before", never a row on this card
    assert "envision_natural_history" not in {t["asset_id"] for t in card["transfers"]}
    assert "NCT04537832" in {r["nct"] for r in doc["tried_before"]["dravet"]}
    assert "NCT04537832" not in {r["nct"] for r in doc["tried_before"]["scn2a_loss"]}
    assert card["named_in_same_study"] == ["NCT01238250", "NCT06967727"]
    blocked = [t for t in card["transfers"] if t["blocked"]]
    assert {t["nct"] for t in blocked} == {"NCT05818553", "NCT05737784", "NCT07019922"}
    assert all(t["cited_pmid"] == "34287911" for t in blocked)
    nh = next(t for t in card["transfers"] if t["asset_id"] == "stxbp1_syngap1_natural_history")
    assert "ages in the study record: children, adults and older adults" in nh["what_differs"]
    assert "STXBP1 or SYNGAP1" in nh["study_population"]
    assert "diagnosis" not in " ".join(nh["what_differs"])
    # "Named in the same study" lists only studies that name another community's gene: EMBOLD
    # (SCN2A + SCN8A) counts, the SCN2A-only trials do not
    named = doc["transfers"]["scn2a_gain"]["named_in_same_study"]
    assert "NCT05818553" in named and "NCT07019922" not in named


def test_station_copy_is_deny_list_clean(doc):
    for key, card in doc["transfers"].items():
        for station, state in card["stations"].items():
            assert denied_terms(state["why"], "family") == [], (key, station)
        assert denied_terms(card["steps"]["sentence"], "family") == []


def test_unknown_direction_cards_hold_allowed_rows_only(doc):
    unknown = {k: v for k, v in doc["transfers"].items() if k.endswith("_unknown")}
    assert set(unknown) == {"scn2a_unknown", "scn8a_unknown", "scn1a_unknown"}
    gated = {t.value for t in DIRECTION_GATED_TYPES}
    for key, card in unknown.items():
        assert card["direction"] == "unknown"
        assert not any(t["asset_type"] in gated for t in card["transfers"]), key
        assert not any(t["blocked"] for t in card["transfers"])
        assert card["banner"] is None
    scn2a = unknown["scn2a_unknown"]
    assert "simons_searchlight_scn2a" in {t["asset_id"] for t in scn2a["transfers"]}
    assert "until a lab study shows the direction" in scn2a["steps"]["sentence"]
    scn8a = unknown["scn8a_unknown"]
    for t in scn8a["transfers"]:  # a stopped registry is refused with the fixed sentence
        ok = t["status"] in ("viable", "already_open")
        assert ok or "stopped study" in t["reason"] or "is paused" in t["reason"], t
    assert {t["asset_type"] for t in scn8a["transfers"]} <= {"registry", "outcome_measure"}
    ids = [t["asset_id"] for t in scn8a["transfers"]]
    assert "simons_searchlight_syngap1" not in ids  # one row per real resource
    assert "scn8a_unknown:simons_searchlight_scn2a" in doc["texts"]
    assert doc["texts"]["scn8a_unknown:rare_x_syngap1"]["text"].startswith(
        "This registry is open to any rare-disease group, including SCN8A families."
    )
    own = next(t for t in scn8a["transfers"] if t["asset_id"] == "scn8a_registry")
    assert own["status"] == "already_open"


def test_every_line_card_has_a_text_with_provenance_and_codex_cards_are_on_the_path(doc):
    keys = {
        f"{line}:{t['asset_id']}" for line, c in doc["transfers"].items() for t in c["transfers"]
    }
    keys |= {f"{line}:block" for line, c in doc["transfers"].items() if c["banner"]}
    assert keys == set(doc["texts"])
    demo = doc["transfers"]["scn2a_loss"]
    on_path = set(demo["top_cards"]) | {t["asset_id"] for t in demo["transfers"] if t["blocked"]}
    for key, text in doc["texts"].items():
        assert text["card_key"] == key and text["text"]
        assert text["source"] in ("codex", "template")
        assert "rejected_reason" not in text
        assert (text["provenance"] is not None) == (text["source"] == "codex")
        assert isinstance(text["citations"], list)
        if text["proposal"]:
            assert text["addressee"]
            if text["source"] == "template":
                assert text["proposal"].startswith(f"To {text['addressee']}:")
            assert text["proposal"].endswith(("who can take part.", "can be reused."))
        if text["source"] == "codex":
            assert key.split(":", 1)[0] == "scn2a_loss" and key.split(":", 1)[1] in on_path
            assert text["provenance"]["model"] == "gpt-6-astra"
            assert text["provenance_line"].startswith("Written by gpt-6-astra at build time on")
        assert text["provenance_line"].endswith("checked by code.")
        assert "<name>" not in text["provenance_line"]
        for field in ("text", "proposal"):
            if text[field]:
                assert denied_terms(text[field], "family") == [], (key, field)
                assert len(text[field]) <= 400
    assert doc["meta"]["counts"]["texts_codex"] == 4
    block = doc["texts"]["scn2a_loss:block"]
    assert block["text"] == demo["banner"] and block["source"] == "template"


def test_stale_or_failing_codex_text_falls_back_to_the_template():
    seed, _ = load_seed()
    claims = load_accepted_claims()
    cards = build_cards(seed, claims, [])
    key = "scn2a_loss:simons_searchlight_scn2a"
    row = {
        "source": "codex",
        "text": "The Simons Searchlight registry (NCT01238250) is open to SCN2A families.",
        "provenance": {"model": "gpt-6-astra"},
        "proposal": None,
        "facts_sha256": "0" * 64,
        "provenance_line": "x",
    }
    stale = texts_for(cards, seed, claims, {key: row})[key]
    assert stale.source == "template"
    # the right hash but a text that no longer passes (a denied word) also falls back

    from pipeline.explain import facts_for
    from pipeline.schema import Transfer

    lines = {ln.key: ln for ln in seed.lines}
    labels = {a.id: a.label for a in seed.assets}
    c = cards["scn2a_loss"]
    held = [st for st, v in c["stations"].items() if v["state"] == "have"]
    t = next(
        Transfer.model_validate(r)
        for r in c["transfers"]
        if r["asset_id"] == "simons_searchlight_scn2a"
    )
    row["facts_sha256"] = facts_sha256(
        facts_for(t, lines["scn2a_loss"], lines, labels, claims, held)
    )
    row["text"] = "This registry is a cure for SCN2A families."
    assert texts_for(cards, seed, claims, {key: row})[key].source == "template"


def test_eligibility_only_co_listings_carry_the_caption(doc):
    rows = [e for e in doc["co_listings"] if e["nct"] == "NCT06967727"]
    assert rows and all(
        r["human_check"] or r["matched_field"] != "eligibility_inclusion" for r in rows
    )
    assert any(r["tier"] == 3 and r["human_check"] for r in rows)
    assert all(r["caveat"].endswith("checked by code only") for r in rows)
    assert not any("person" in r["caveat"] for r in rows)


def test_studies_merge_seed_and_record_and_nest_drug_bearing_fields(doc):
    study = next(s for s in doc["studies"] if s["nct"] == "NCT06555965")
    assert study["name"].startswith("STXBP1 and SYNGAP1") and study["kind"] == "natural_history"
    assert study["overall_status"] and study["lead_sponsor"]
    assert "note" not in study and "eligibility_criteria" not in study
    assert isinstance(study["stopped"], bool)
    nested = {"brief_title", "keywords", "interventions", "outcome_measures"}
    assert set(study["researcher"]) == nested and not nested & set(study)
    assert study["std_ages"] == ["CHILD", "ADULT", "OLDER_ADULT"]
    # data minimisation: study sites, phases and enrolment figures stay in the cache only
    assert not {"locations", "phases", "enrollment_count", "enrollment_type"} & set(study)
    # a stopped co-listed trial names itself on the station instead of "none found yet"
    trial = doc["transfers"]["cdkl5"]["stations"]["trial"]
    assert (
        trial["state"] == "missing"
        and "NCT03635073" in trial["why"]
        and trial["halted"] == "stopped"
    )
    assert "ENVISION" not in doc["transfers"]["dravet"]["stations"]["natural_history"]["why"]
    assert "(yours is paused)" in doc["transfers"]["cdkl5"]["steps"]["sentence"]
    assert not any("locations" in s for s in doc["studies"])
    # the mechanism view's institution list still reads the cached sites
    assert any("study site" in i["roles"] for v in doc["mechanism_view"] for i in v["institutions"])
    assert all("note" not in a for a in doc["assets"])
    assert set(doc["tried_before"]) == {ln["key"] for ln in doc["lines"]}


def test_edges_name_their_source_and_the_demo_relations(doc):
    ids = {f"line:{ln['key']}" for ln in doc["lines"]}
    ids |= {f"org:{o['key']}" for o in doc["organisations"]}
    ids |= {f"study:{s['nct']}" for s in doc["studies"]}
    ids |= {f"asset:{a['id']}" for a in doc["assets"]}
    ids |= {f"paper:{p['pmid']}" for p in doc["papers"]}
    ids |= {f"conflict:{c['id']}" for c in doc["conflicts"]}
    for e in doc["edges"]:
        assert e["source_id"] in ids and e["target_id"] in ids, e
        assert e["pmid"] or e["nct"] or e["source_url"], e
    kinds = {(e["source_id"], e["target_id"], e["kind"]) for e in doc["edges"]}
    assert ("line:scn2a_loss", "line:scn2a_gain", "blocked") in kinds
    assert ("line:scn2a_loss", "line:syngap1", "viable") in kinds
    assert ("line:scn2a_loss", "study:NCT01238250", "co_listed_in") in kinds
    assert ("line:scn2a_loss", "paper:34287911", "claim") in kinds
    assert ("line:scn2a_loss", "org:familiescn2a", "organisation") in kinds
    claim_edges = [e for e in doc["edges"] if e["kind"].startswith("claim")]
    assert all(e["claim_id"] for e in claim_edges)
    model_edges = [
        e for e in doc["edges"] if e["asset_id"] in ("jax_029303_syngap1", "mmrrc_069939_syngap1")
    ]
    assert len({e["asset_id"] for e in model_edges if e["source_id"] == "line:scn2a_loss"}) == 2
    full = {
        (
            e["source_id"],
            e["target_id"],
            e["kind"],
            e["pmid"],
            e["nct"],
            e["asset_id"],
            e["claim_id"],
        )
        for e in doc["edges"]
    }
    assert len(full) == len(doc["edges"])  # no duplicates


def test_symptom_aliases_never_route_to_a_direction_line(doc):
    symptoms = [a for a in doc["aliases"] if a["kind"] == "symptom"]
    assert symptoms
    terms = [a["term"].lower() for a in symptoms]
    assert len(terms) == len(set(terms))  # one alias per term
    assert not any(a["line"] in ("scn2a_loss", "scn2a_gain") for a in symptoms)
    spasms = next(a for a in symptoms if a["term"] == "Infantile spasms")
    assert "SCN2A" in (spasms["genes"] or [spasms["gene"]]) and spasms["line"] is None
    curated_only = [a for a in symptoms if a["pmid"]]
    assert all(a["direction_step"] and "Polaris annotation" in a["note"] for a in curated_only)
    for term in (
        "Seizure",
        "Autism",
        "Hypotonia",
        "Epileptic encephalopathy",
        "Global developmental delay",
    ):
        shared = next(a for a in symptoms if a["term"] == term)
        assert {"SCN2A", "SYNGAP1"} <= set(shared["genes"]) and shared["line"] is None, term
        assert not shared["direction_step"]
    # every symptom alias lists exactly the seeded genes phenotype.hpoa annotates with its term
    import yaml

    rows = yaml.safe_load(Path("pipeline/cache/symptoms.yaml").read_text())["symptoms"]
    by_id: dict[str, set[str]] = {}
    for r in rows:
        by_id.setdefault(r["hpo_id"], set()).add(r["gene"])
    for a in symptoms:
        if a["pmid"]:
            continue  # a curated term of one line may be absent from phenotype.hpoa
        assert set(a["genes"] or [a["gene"]]) == by_id[a["hpo_id"]], a["term"]
    line_of = {ln["gene"]: ln["key"] for ln in doc["lines"]}
    single = [a for a in symptoms if a["gene"] and not a["direction_step"]]
    assert single and all(a["line"] == line_of[a["gene"]] for a in single)
    per_gene: dict[str, int] = {}
    for a in symptoms:
        for g in a["genes"] or [a["gene"]]:
            per_gene[g] = per_gene.get(g, 0) + 1
    assert max(per_gene.values()) <= 15 * len(doc["lines"])  # SYMPTOMS_PER_GENE x genes


def test_symptom_alias_builder_merges_terms_across_genes():
    seed, _ = load_seed()
    rows = [
        SymptomRow(
            hpo_id="HP:0001250",
            label="Seizure",
            gene="SCN2A",
            diseases=3,
            retrieved=date(2026, 10, 4),
        ),
        SymptomRow(
            hpo_id="HP:0001250",
            label="Seizure",
            gene="SYNGAP1",
            diseases=1,
            retrieved=date(2026, 10, 4),
        ),
        SymptomRow(
            hpo_id="HP:0000001",
            label="Ataxia",
            gene="KCNQ2",
            diseases=1,
            retrieved=date(2026, 10, 4),
        ),
        SymptomRow(
            hpo_id="HP:0000002",
            label="Hypotonia",
            gene="SYNGAP1",
            diseases=2,
            retrieved=date(2026, 10, 4),
        ),
    ]
    out = symptom_aliases(seed, rows)
    by_term = {a.term: a for a in out}
    assert len(by_term) == len(out)
    assert by_term["Seizure"].genes == ["SCN2A", "SYNGAP1"] and by_term["Seizure"].line is None
    assert "disagree" not in (by_term.get("Seizure").note or "")
    assert by_term["Hypotonia"].line == "syngap1" and by_term["Hypotonia"].gene == "SYNGAP1"
    assert (
        by_term["Infantile spasms"].direction_step and by_term["Infantile spasms"].gene == "SCN2A"
    )
    assert "Ataxia" not in by_term  # KCNQ2 has no seeded line


def test_variant_aliases_follow_code_checked_claims():
    seed, _ = load_seed()
    only_r853q = emitted_aliases(seed, [claim()])
    terms = {a.term for a in only_r853q if a.kind is AliasKind.VARIANT}
    assert "SCN2A R853Q" in terms and "SCN2A R1882Q" not in terms
    assert not {a.term for a in emitted_aliases(seed, []) if a.kind is AliasKind.VARIANT}
    # the right PMID and variant but the other direction: the alias follows the claim, never
    # the hand-written line
    wrong = {a.term: a for a in emitted_aliases(seed, [claim(direction=Direction.GAIN)])}
    assert wrong["SCN2A R853Q"].line == "scn2a_gain" and wrong["SCN2A R853Q"].pmid == "34287911"
    # a hedged claim does not count; a review does not count
    hedged = emitted_aliases(seed, [claim(flags=["hedged wording in the quote"])])
    assert "SCN2A R853Q" not in {a.term for a in hedged}
    review = emitted_aliases(seed, [claim(basis="review")])
    assert "SCN2A R853Q" not in {a.term for a in review}
    # the real cache: every code-checked SCN2A assay variant gets its three spellings
    real = {a.term: a for a in emitted_aliases(seed, load_accepted_claims())}
    for term, line in {
        "SCN2A R1882Q": "scn2a_gain",
        "SCN2A p.Arg1882Gln": "scn2a_gain",
        "SCN2A A1773T": "scn2a_loss",
        "SCN2A S863F": "scn2a_loss",
        "SCN2A M1879T": "scn2a_gain",
        "SCN2A K1933M": "scn2a_gain",
        "SCN2A N1662D": "scn2a_gain",
    }.items():
        assert real[term].line == line, term
    assert real["SCN2A R1882Q"].pmid == "38544375"
    assert (
        real["SCN2A C258R"].variant_direction is Direction.MIXED
        and real["SCN2A C258R"].line is None
    )
    assert "SCN2A K156N" not in real  # stance unclear, hedged: never a line


def test_symptom_alias_schema_rules():
    with pytest.raises(ValueError):
        Alias(term="Seizure", kind=AliasKind.SYMPTOM, line="scn2a_loss")  # no hpo_id
    with pytest.raises(ValueError):
        Alias(
            term="SCN2A",
            kind=AliasKind.GENE,
            gene="SCN2A",
            direction_step=True,
            hpo_id="HP:0000001",
        )


def test_cluster_groups_are_ordered_gain_loss_non_channel_and_cover_every_line():
    seed, _ = load_seed()
    groups = cluster_groups(seed)
    assert [g.key for g in groups] == ["sodium_channel_gain", "sodium_channel_loss", "non_channel"]
    assert sorted(k for g in groups for k in g.line_keys) == sorted(ln.key for ln in seed.lines)


def test_no_person_is_named_as_checker(doc):
    text = json.dumps(doc, ensure_ascii=False)
    assert "checked by a person" not in text
    assert "not yet by a person" not in text
    assert "Checked by <" not in text

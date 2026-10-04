"""The committed study cache keeps allow-listed fields only; co-listing matches where allowed."""

from datetime import date

import pytest

from pipeline.ctgov import co_listings, inclusion_text, strip_record
from pipeline.schema import MatchedField
from pipeline.seed_check import SEED, load_seed

RETRIEVED = date(2026, 10, 4)


def record(**overrides) -> dict:
    base = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000001", "briefTitle": "A study"},
            "statusModule": {
                "overallStatus": "RECRUITING",
                "startDateStruct": {"date": "2023-08-30"},
                "lastUpdatePostDateStruct": {"date": "2025-10-29"},
                "whyStopped": None,
            },
            "conditionsModule": {
                "conditions": ["SYNGAP1-Related Intellectual Disability"],
                "keywords": ["STXBP1"],
            },
            "descriptionModule": {
                "detailedDescription": "Compare with CDKL5 cohorts (Smith et al.)."
            },
            "eligibilityModule": {
                "eligibilityCriteria": (
                    "Inclusion Criteria:\n* SCN2A variant\n\nExclusion Criteria:\n* SCN8A variant"
                ),
                "minimumAge": "1 Year",
            },
            "contactsLocationsModule": {
                "centralContacts": [{"name": "Jane Doe", "email": "jane@example.org"}],
                "overallOfficials": [{"name": "Dr. Who"}],
                "locations": [
                    {
                        "facility": "Children's Hospital",
                        "city": "Philadelphia",
                        "country": "United States",
                        "contacts": [{"name": "x"}],
                    }
                ],
            },
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": "Dr. Someone", "class": "INDIV"}
            },
        }
    }
    base["protocolSection"].update(overrides)
    return base


def test_strip_record_drops_everything_not_on_the_allowlist():
    stripped = strip_record(record(), RETRIEVED)
    dumped = stripped.model_dump_json()
    for forbidden in (
        "jane@example.org",
        "Dr. Who",
        "Smith et al",
        "eligibilityCriteria",
        "SCN2A variant",
        "contacts",
    ):
        assert forbidden not in dumped, forbidden
    assert stripped.lead_sponsor == "Individual investigator"
    assert stripped.locations[0].facility == "Children's Hospital"
    assert stripped.minimum_age == "1 Year" and stripped.retrieved == RETRIEVED


def test_person_titles_are_flagged_for_a_human_check():
    rec = record(statusModule={"overallStatus": "TERMINATED", "whyStopped": "Decision by Dr. X"})
    assert "why_stopped" in strip_record(rec, RETRIEVED).human_check


def test_inclusion_text_stops_at_the_exclusion_heading():
    text = inclusion_text(record())
    assert "SCN2A" in text and "SCN8A" not in text


def test_co_listing_matches_conditions_keywords_and_inclusion_only():
    seed, _ = load_seed(SEED)
    edges = {
        (e.line, e.matched_field, e.human_check)
        for e in co_listings(seed.lines, record(), RETRIEVED)
    }
    assert ("syngap1", MatchedField.CONDITIONS, False) in edges
    assert ("scn2a_loss", MatchedField.ELIGIBILITY_INCLUSION, True) in edges
    assert ("scn2a_gain", MatchedField.ELIGIBILITY_INCLUSION, True) in edges
    assert not any(e[0] == "cdkl5" for e in edges)  # CDKL5 appears only in the description


def test_gene_named_only_under_exclusion_never_matches():
    seed, _ = load_seed(SEED)
    rec = record(
        conditionsModule={"conditions": ["Epilepsy"], "keywords": []},
        eligibilityModule={
            "eligibilityCriteria": (
                "Inclusion Criteria:\n* epilepsy\n\nExclusion Criteria:\n* SYNGAP1 variant"
            )
        },
    )
    assert co_listings(seed.lines, rec, RETRIEVED) == []


def test_window_is_short_and_from_the_matched_field():
    seed, _ = load_seed(SEED)
    edge = next(e for e in co_listings(seed.lines, record(), RETRIEVED) if e.line == "syngap1")
    assert len(edge.window) <= 120 and "SYNGAP1" in edge.window


# --- Round-1 critic cases -------------------------------------------------------------------

INCLUDE_STXBP1_SYNGAP1 = (
    "Inclusion Criteria:\n* STXBP1 or SYNGAP1 variant\n\nExclusion Criteria:\n* none"
)
NO_GENES = {"conditions": ["Epilepsy"], "keywords": []}
PERSONAL = (
    "Inclusion Criteria:\n* Please contact study coordinator Jane Doe, mother of patient"
    " Tom Doe (DOB 2019), before screening. Pathogenic SYNGAP1 variant, confirmed.\n\n"
    "Exclusion Criteria:\n* none"
)
MEETS_NONE = (
    "Inclusion Criteria:\n* meets none of the exclusion criteria below\n* SYNGAP1 variant\n\n"
    "Exclusion Criteria:\n* none"
)
NAMED = (
    "Inclusion Criteria:\n* contact Jane Doe about SYNGAP1 variants\n\nExclusion Criteria:\n* none"
)


def with_criteria(criteria: str, conditions=None) -> dict:
    return record(
        conditionsModule=conditions or NO_GENES,
        eligibilityModule={"eligibilityCriteria": criteria},
    )


def test_nct06555965_shaped_record_never_matches_a_cdkl5_line():
    from pipeline.schema import Direction, Line, MechanismFamily, Source

    cdkl5 = Line(
        key="cdkl5",
        gene="CDKL5",
        mechanism="kinase",
        mechanism_family=MechanismFamily.NON_CHANNEL,
        direction=Direction.NOT_APPLICABLE,
        label="CDKL5",
        gloss="g",
        mechanism_label="db label",
        sources=[Source(label="x", url="https://clinicaltrials.gov/study/NCT06555965")],
    )
    rec = record(
        conditionsModule={
            "conditions": ["STXBP1 Encephalopathy", "SYNGAP1-Related ID"],
            "keywords": ["STXBP1"],
        },
        descriptionModule={"detailedDescription": "Methods follow the CDKL5 cohort (ref 12)."},
        referencesModule={"references": [{"citation": "CDKL5 deficiency disorder cohort, 2021"}]},
        eligibilityModule={"eligibilityCriteria": INCLUDE_STXBP1_SYNGAP1},
    )
    assert co_listings([cdkl5], rec, RETRIEVED) == []


@pytest.mark.parametrize(
    "criteria",
    [
        "Inclusion Criteria:\n* epilepsy\n\nEXCLUSION CRITERIA:\n* SYNGAP1 variant",
        "Inclusion Criteria:\n* epilepsy\n\nExclusions:\n* SYNGAP1 variant",
        "Inclusion Criteria:\n* epilepsy\n\nExclusion:\n* SYNGAP1 variant",
        "Inclusion: epilepsy. Patients excluded: SYNGAP1 variant carriers.",
        "Inclusion Criteria:\n* epilepsy not caused by SYNGAP1\n\nExclusion Criteria:\n* none",
        "Inclusion Criteria:\n* any gene excluding SYNGAP1\n\nExclusion Criteria:\n* none",
    ],
)
def test_exclusion_headings_and_negations_never_yield_an_edge(criteria):
    seed, _ = load_seed(SEED)
    assert co_listings(seed.lines, with_criteria(criteria), RETRIEVED) == []


def test_meets_none_of_the_exclusion_criteria_below_does_not_cut_the_inclusion():
    seed, _ = load_seed(SEED)
    edges = co_listings(seed.lines, with_criteria(MEETS_NONE), RETRIEVED)
    assert [e.line for e in edges] == ["syngap1"]


def test_conditions_match_case_insensitively_and_whole_tokens_only():
    seed, _ = load_seed(SEED)
    both = {"conditions": ["scn2a encephalopathy", "SCN2A1 thing"], "keywords": []}
    lines = {e.line for e in co_listings(seed.lines, with_criteria("", both), RETRIEVED)}
    assert lines == {"scn2a_gain", "scn2a_loss"}
    only_token = {"conditions": ["SCN2A1 thing"], "keywords": []}
    assert co_listings(seed.lines, with_criteria("", only_token), RETRIEVED) == []


def test_window_is_a_phrase_and_personal_context_is_flagged():
    seed, _ = load_seed(SEED)
    edge = next(iter(co_listings(seed.lines, with_criteria(PERSONAL), RETRIEVED)))
    assert edge.window == "Pathogenic SYNGAP1 variant" and edge.human_check
    edge2 = next(iter(co_listings(seed.lines, with_criteria(NAMED), RETRIEVED)))
    assert edge2.human_check and edge2.window == "SYNGAP1"  # a name-like phrase keeps only the gene


def test_lead_sponsor_that_is_a_named_investigator_is_replaced():
    pi = {
        "leadSponsor": {"name": "John Smith", "class": "OTHER"},
        "responsibleParty": {
            "type": "PRINCIPAL_INVESTIGATOR",
            "investigatorFullName": "John Smith",
        },
    }
    stripped = strip_record(record(sponsorCollaboratorsModule=pi), RETRIEVED)
    assert stripped.lead_sponsor == "Individual investigator"
    official = record(
        sponsorCollaboratorsModule={"leadSponsor": {"name": "Jane Roe", "class": "OTHER"}},
        contactsLocationsModule={"overallOfficials": [{"name": "Jane Roe"}], "locations": []},
    )
    assert strip_record(official, RETRIEVED).lead_sponsor == "Individual investigator"
    stopped = record(statusModule={"overallStatus": "TERMINATED", "whyStopped": "Low enrolment"})
    assert "why_stopped" in strip_record(stopped, RETRIEVED).human_check


def test_esearch_term_is_read_from_the_pmid_list_header():
    from pipeline.build import esearch_term

    term = esearch_term()
    assert term.startswith("SCN2A[Title/Abstract] AND")
    assert term.endswith("NOT review[Publication Type]")
    assert "\n" not in term


def test_gene_symptoms_rank_by_disease_count_and_cap(tmp_path, monkeypatch):
    from pipeline import build

    hpo = tmp_path / "hpo"
    hpo.mkdir()
    (hpo / "genes_to_disease.txt").write_text(
        "ncbi_gene_id\tgene_symbol\tassociation_type\tdisease_id\tsource\n"
        "NCBIGene:1\tSCN2A\tMENDELIAN\tOMIM:1\tx\nNCBIGene:1\tSCN2A\tMENDELIAN\tOMIM:2\tx\n"
    )
    rows = [
        "#comment",
        "database_id\tdisease_name\tqualifier\thpo_id\tref\tev\ton\tfr\tsex\tmod\taspect\tbio",
    ]
    for disease, hp in (
        ("OMIM:1", "HP:0000001"),
        ("OMIM:2", "HP:0000001"),
        ("OMIM:1", "HP:0000002"),
    ):
        rows.append(f"{disease}\tD\t\t{hp}\tPMID:1\tPCS\t\t\t\t\tP\tcur")
    rows.append("OMIM:1\tD\tNOT\tHP:0000003\tPMID:1\tPCS\t\t\t\t\tP\tcur")  # negated: skipped
    rows.append("OMIM:1\tD\t\tHP:0000004\tPMID:1\tPCS\t\t\t\t\tI\tcur")  # inheritance: skipped
    rows.append("OMIM:9\tD\t\tHP:0000005\tPMID:1\tPCS\t\t\t\t\tP\tcur")  # other gene's disease
    (hpo / "phenotype.hpoa").write_text("\n".join(rows) + "\n")
    monkeypatch.setattr(build, "RAW", tmp_path)
    monkeypatch.setattr(build, "SYMPTOMS_PER_GENE", 1)
    labels = {"HP:0000001": "Seizure", "HP:0000002": "Ataxia", "HP:0000003": "X", "HP:0000005": "Y"}
    out = build.symptom_rows(["SCN2A"], labels)
    assert out == [{"hpo_id": "HP:0000001", "label": "Seizure", "gene": "SCN2A", "diseases": 2}]
    # a term chosen for one gene is emitted for every gene annotated with it (OMIM:9 is the
    # other gene's disease), so the alias builder sees the shared term and opens the picker
    g2d = (hpo / "genes_to_disease.txt").read_text()
    (hpo / "genes_to_disease.txt").write_text(g2d + "2\tSYNGAP1\tx\tOMIM:9\n")
    rows.append("OMIM:9\tD\t\tHP:0000001\tPMID:1\tPCS\t\t\t\t\tP\tcur")
    (hpo / "phenotype.hpoa").write_text("\n".join(rows) + "\n")
    out = build.symptom_rows(["SCN2A", "SYNGAP1"], labels)
    assert [(r["label"], r["gene"]) for r in out] == [("Seizure", "SCN2A"), ("Seizure", "SYNGAP1")]

import json

import pytest

from pipeline.check_public import PHONE, REPO, check_file, forbidden_keys
from pipeline.ctgov import CAVEATS


def write(tmp_path, name, doc):
    path = tmp_path / name
    path.write_text(json.dumps(doc))
    return path


def test_clean_file_has_no_problems(tmp_path):
    doc = {
        "nctId": "NCT01238250",
        "status": "RECRUITING",
        "retrieved": "2026-10-04",
        "run_at": "2026-10-04T01:06:40Z",
        "doi": "10.1038/s41586-021-03819-2",
        "variant": "p.Arg853Gln",
        "hpo": "HP:0001250",
        "verified_hash": "0" * 20 + "1234567890" * 4 + "abcd",
        "package": "pkg@1.2.3",
    }
    assert check_file(write(tmp_path, "ok.json", doc), secrets=[]) == []


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-04",
        "10.1038/s41586-021-03819-2",
        "NCT01238250",
        "1234567890abcdef" * 4,
        "2023-08-02T00:00:00Z",
    ],
)
def test_phone_pattern_ignores_dates_dois_ids_and_hashes(value):
    assert not PHONE.search(value)


@pytest.mark.parametrize(
    "value", ["+1 617 555 0199", "(617) 555-0199", "0351 123 4567", "+49.351.1234567"]
)
def test_phone_pattern_matches_real_numbers(value):
    assert PHONE.search(value)


@pytest.mark.parametrize(
    "key",
    [
        "AbstractText",
        "abstract_text",
        "phr_text",
        "AuthorList",
        "authors",
        "Affiliation",
        "overallOfficials",
        "centralContacts",
        "contacts",
        "pointOfContact",
        "contact_pi",
        "investigatorFullName",
        "principal_investigators",
        "contact_pi_name",
        "program_officers",
        "descriptionModule",
        "eligibilityCriteria",
        "passages",
        "orcid",
        "curator",
    ],
)
def test_strip_list_keys_are_forbidden(key):
    assert forbidden_keys({key}) == [key]


def test_allowed_keys_pass():
    allowed = {"briefTitle", "whyStopped", "leadSponsor", "facility", "measure", "contact_url"}
    assert forbidden_keys(allowed) == []


def test_phone_hidden_under_a_harmless_key_name_is_still_caught(tmp_path):
    problems = check_file(write(tmp_path, "x.json", {"trial_id": "+1 617-555-0123"}), secrets=[])
    assert problems == [f"{tmp_path / 'x.json'}: phone at $.trial_id"]


def test_forbidden_patterns_are_reported(tmp_path):
    doc = {
        "contacts": "someone@example.org",
        "note": "<abstract pmid=1>",
        "long": "y" * 401,
        "url": "https://x.org/?email%3Da%40b.org",
        "facility": "Clinic of Dr. Example",
        "phone": "+1 617 555 0199",
    }
    joined = "\n".join(check_file(write(tmp_path, "bad.json", doc), secrets=[]))
    for expected in (
        "forbidden key 'contacts'",
        "e-mail",
        "abstract tag",
        "string over 400 chars",
        "email= query",
        "person title in 'facility'",
        "phone at $.phone",
    ):
        assert expected in joined, expected


def test_env_literal_is_caught_in_any_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("token=abcdefghijklmnop")
    assert check_file(path, secrets=["abcdefghijklmnop"]) == [
        f"{path}: contains a literal value from .env"
    ]


def test_model_text_files_get_the_denylist(tmp_path):
    path = write(tmp_path, "texts.yaml", {"card": "This registry is a cure."})
    assert any("denied word 'cure'" in p for p in check_file(path, secrets=[]))


def test_cache_keys_markup_links_and_digit_runs_are_caught(tmp_path):
    doc = {
        "studies": [
            {
                "why_stopped": "Dr. Jane Doe left",
                "lead_sponsor": "Prof. John Smith",
                "brief_title": "<img src=x> see https://evil.example/x",
                "note": "call 6175550199",
            }
        ]
    }
    joined = "\n".join(check_file(write(tmp_path, "ctgov.yaml", doc), secrets=[]))
    for expected in (
        "person title in 'why_stopped'",
        "person title in 'lead_sponsor'",
        "markup or link in 'brief_title'",
        "long digit run in 'note'",
    ):
        assert expected in joined, expected
    ok = write(
        tmp_path,
        "ok.yaml",
        {"url": "https://clinicaltrials.gov/study/NCT1", "facility": "MDS Foundation"},
    )
    assert check_file(ok, secrets=[]) == []


def test_search_string_may_exceed_the_length_cap_but_prose_may_not(tmp_path):
    long = "x" * 401
    ok = write(tmp_path, "graph.json", {"meta": {"esearch_term": long}})
    assert check_file(ok, secrets=[]) == []
    bad = write(tmp_path, "graph.json", {"meta": {"footer": long}})
    assert any("over 400" in p for p in check_file(bad, secrets=[]))


def test_graph_json_denylist_scans_everything_except_level_two_paths(tmp_path):
    doc = {
        "texts": {"k": {"text": "This is a cure."}},
        "studies": [
            {
                "name": "a cure study",
                "researcher": {"interventions": [{"name": "carbamazepine"}]},
                "why_stopped": "enrolment failed",
                "study_population": "a diagnosis of X",
            }
        ],
        "papers": [{"title": "Carbamazepine in SCN2A", "journal": "x"}],
        "claims": [{"evidence_quote": "a safe cure", "gene": "a proven gene"}],
        "aliases": [{"term": "diagnosis", "note": "a diagnosis"}],
        "co_listings": [{"window": "enrolled", "caveat": CAVEATS["eligible_gene_list"]}],
        "lines": [{"gloss": "the channel works too weakly"}],
        "tried_before": {"cdkl5": [{"why_stopped": "Sponsor decision on TAK-935", "name": "x"}]},
        "transfers": {
            "scn2a_loss": {
                "stations": {"diagnosis": {"why": "a genetic diagnosis"}},
                "steps": {"missing": ["diagnosis"]},
                "transfers": [{"study_population": "enrolled with a diagnosis", "reason": "enrol"}],
            }
        },
    }
    problems = check_file(write(tmp_path, "graph.json", doc), secrets=[])
    found = sorted(p.split(": ", 1)[1] for p in problems if "denied word" in p)
    assert found == [
        "denied word 'cure' at $.studies[0].name",
        "denied word 'cure' at $.texts.k.text",
        "denied word 'diagnosis' at $.aliases[0].note",
        "denied word 'diagnosis' at $.transfers.scn2a_loss.stations.diagnosis.why",
        "denied word 'enrol' at $.transfers.scn2a_loss.transfers[0].reason",
        "denied word 'proven' at $.claims[0].gene",
    ]


def test_no_em_dash_in_site_copy_outside_verbatim_fields():
    """Plan owner, 2026-10-04 11:40: no em dashes in site copy. Quotes from abstracts and
    registry records (the deny-list exemption paths) are the only strings allowed to carry one."""
    from pipeline.check_public import DENYLIST_EXEMPT_PATHS, walk_strings

    for name in ("graph.json", "screen.json"):
        doc = json.loads((REPO / "web" / "public" / name).read_text())
        exempt = DENYLIST_EXEMPT_PATHS[name]
        hits = [
            where for where, _, text in walk_strings(doc) if "—" in text and not exempt.match(where)
        ]
        assert hits == [], (name, hits[:10])

"""A7 add-ons: the consistency check, the About counts, the mechanism view and RePORTER funding."""

import json
from datetime import date

import pytest

from pipeline.consistency import HELD_OUT_NCT, TITLE, claims_before, predicted_partners, run
from pipeline.denylist import denied_terms
from pipeline.graph import (
    FUNDING_CAPTION,
    GRAPH_FILE,
    funding_rows,
    multi_gene_studies,
    repository_id,
)
from pipeline.reporter import FundingRow, render_cache
from pipeline.schema import Direction, Paper
from pipeline.seed_check import load_seed
from pipeline.transfer import load_accepted_claims


@pytest.fixture(scope="module")
def doc() -> dict:
    return json.loads(GRAPH_FILE.read_text())


def test_consistency_check_holds_embold_out_and_reports_agreement_not_discovery(doc):
    result = run()
    assert result["title"] == TITLE and "not discovery" in result["title"]
    assert result["held_out"]["nct"] == HELD_OUT_NCT
    assert result["held_out"]["start_date"].startswith("2023-08")
    assert HELD_OUT_NCT not in result["inputs"]["studies_before_start"]
    assert all(int(p) for p in result["inputs"]["papers_used"])
    assert result["agreement"]["k"] == 1 and result["agreement"]["hits"] in (0, 1)
    assert result["pool"]["size"] >= 1 and 0 < result["pool"]["random_baseline"] <= 1
    assert "n=1" in result["title"] and result["caveat"]
    assert doc["meta"]["consistency_check"]["agreement"] == result["agreement"]
    assert "date is unknown for this gene" in result["co_listings_note"]


def test_consistency_prediction_uses_only_papers_before_the_cutoff():
    seed, _ = load_seed()
    claims = load_accepted_claims()
    papers = {
        c.pmid: Paper(pmid=c.pmid, title="t", year=2030, retrieved=date(2026, 10, 4))
        for c in claims
    }
    assert claims_before(claims, papers, 2023) == []  # every paper dated after the cutoff
    target = next(ln for ln in seed.lines if ln.key == "scn2a_gain")
    assert predicted_partners(target, seed, []) == []  # no claims, no known direction, no partner
    partners = predicted_partners(target, seed, claims)
    assert partners == ["scn8a_dee"]  # same mechanism, same code-checked direction, other gene


def test_how_it_grows_counts_come_from_the_committed_cache(doc):
    grows = doc["meta"]["how_it_grows"]
    assert grows["orphanet_entries"] > grows["orphanet_entries_with_a_gene"] > 1000
    assert grows["lines_covered"] == len(doc["lines"]) == 7 and grows["genes_covered"] == 6
    ncts = {s["nct"] for s in grows["studies_naming_two_or_more_seeded_genes"]}
    assert {"NCT01238250", "NCT06555965", "NCT05818553"} <= ncts
    assert all(len(s["genes"]) >= 2 for s in grows["studies_naming_two_or_more_seeded_genes"])
    assert grows["out_of_scope"].startswith("Investors, funders")
    assert any(r["id"] == "rare_x_syngap1" for r in grows["free_resources"])
    for key in ("out_of_scope", "burden_of_care"):
        assert denied_terms(grows[key], "family") == []


def test_mechanism_view_lists_clusters_ranked_by_shared_assets(doc):
    view = doc["mechanism_view"]
    assert [v["key"] for v in view] == sorted(
        (v["key"] for v in view),
        key=lambda k: (-next(x["shared_assets"] for x in view if x["key"] == k), k),
    )
    gain = next(v for v in view if v["key"] == "sodium_channel_gain")
    assert gain["lines"] == ["scn2a_gain", "scn8a_dee"] and gain["genes"] == ["SCN2A", "SCN8A"]
    assert any(
        s["nct"] == "NCT05818553" and s["lines"] == ["scn2a_gain", "scn8a_dee"]
        for s in gain["studies"]["active"]
    )
    assert all(
        inst["lines"] and len(inst["lines"]) >= 2 for v in view for inst in v["institutions"]
    )
    assert all("contact_page" in o for v in view for o in v["organisations"])
    stopped = [s for v in view for s in v["studies"]["stopped"]]
    assert stopped and all(s["why_stopped"] for s in stopped)
    non_channel = next(v for v in view if v["key"] == "non_channel")
    assert any(m["repository_id"] == "JAX:029303" for m in non_channel["models"])
    assert any(o["pmid"] == "35422141" for o in non_channel["outcome_measures"])
    for v in view:  # no person: contact is a page or a record, never a name
        text = json.dumps(v)
        assert "Dr " not in text and "M.D." not in text


def test_repository_ids():
    assert (
        repository_id("Syngap1 mouse line JAX 029303", "https://www.jax.org/strain/029303")
        == "JAX:029303"
    )
    assert (
        repository_id("Mouse line MMRRC:069939-JAX carrying x", "https://www.mmrrc.org/x")
        == "MMRRC:069939-JAX"
    )
    assert repository_id("a model", "https://example.org") is None


def test_funding_rows_keep_the_strip_list_fields_only(doc, tmp_path):
    shipped = set(FundingRow.model_fields) | {"direction_checked", "caption"}
    assert doc["funding"] and all(set(f) == shipped for f in doc["funding"])
    assert all(f["direction_checked"] is False for f in doc["funding"])
    assert all(f["caption"] == FUNDING_CAPTION for f in doc["funding"])
    assert "not checked" in FUNDING_CAPTION and denied_terms(FUNDING_CAPTION, "family") == []
    assert all(
        f["url"].startswith("https://reporter.nih.gov/project-details/") for f in doc["funding"]
    )
    raw = [
        {
            "appl_id": 1,
            "project_num": "1R01NS000001-01",
            "project_title": "A study of SCN2A",
            "organization": {"org_name": "Some University", "org_city": "X"},
            "fiscal_year": 2026,
            "project_start_date": "2025-01-01T00:00:00",
            "project_end_date": None,
            "principal_investigators": [{"full_name": "Jane Roe"}],
            "contact_pi_name": "ROE, JANE",
            "abstract_text": "secret",
        },
        {
            "appl_id": 1,
            "project_num": "1R01NS000001-01",
            "project_title": "dup",
            "fiscal_year": 2026,
        },
    ]
    import pipeline.reporter as rep

    (tmp_path / "SCN2A.json").write_text(json.dumps(raw))
    original = rep.RAW_DIR
    rep.RAW_DIR = tmp_path
    try:
        text, n = render_cache(["SCN2A"], date(2026, 10, 4))
    finally:
        rep.RAW_DIR = original
    assert n == 1 and "Jane" not in text and "ROE" not in text and "secret" not in text
    assert "1R01NS000001-01" in text and "Some University" in text


def test_funding_rows_naming_only_another_seeded_gene_are_dropped():
    genes = ["SCN1A", "SCN2A", "SCN8A"]
    rows = [
        {"gene": "SCN2A", "title": "SCN2A and SCN1A in epilepsy"},  # names its own gene: kept
        {"gene": "SCN2A", "title": "Nav1.6 in epilepsy"},  # names only SCN8A's channel: dropped
        {"gene": "SCN8A", "title": "Nav1.6 in epilepsy"},  # the same title under SCN8A: kept
        {"gene": "SCN2A", "title": "A cocaine project"},  # names no seeded gene: kept as cached
    ]
    kept = funding_rows(rows, genes)
    assert [(r["gene"], r["title"]) for r in kept] == [
        ("SCN2A", "SCN2A and SCN1A in epilepsy"),
        ("SCN8A", "Nav1.6 in epilepsy"),
        ("SCN2A", "A cocaine project"),
    ]


def test_multi_gene_study_count_agrees_with_the_hand_listed_genes(doc):
    """NCT03635073 names CDKL5 and SCN1A in the seed but not in the record text the cache
    counts; the About count merges both so it agrees with the co-listings."""
    grows = doc["meta"]["how_it_grows"]["studies_naming_two_or_more_seeded_genes"]
    by_nct = {row["nct"]: row["genes"] for row in grows}
    assert by_nct["NCT03635073"] == ["CDKL5", "SCN1A"]
    assert "KCNQ2" not in by_nct["NCT06967727"]  # an unseeded gene never counts
    seed, _ = load_seed()
    merged = multi_gene_studies(seed, [{"nct": "NCT06967727", "genes": ["SCN2A"]}])
    assert {"nct": "NCT03635073", "genes": ["CDKL5", "SCN1A"]} in merged
    assert all(len(r["genes"]) >= 2 for r in merged)


def test_funding_titles_are_level_two_only(doc):
    from pipeline.check_public import DENYLIST_EXEMPT_PATHS

    assert DENYLIST_EXEMPT_PATHS["graph.json"].match("$.funding[3].title")
    assert not DENYLIST_EXEMPT_PATHS["graph.json"].match("$.funding[3].organisation")
    assert Direction.GAIN  # the module imports stay used

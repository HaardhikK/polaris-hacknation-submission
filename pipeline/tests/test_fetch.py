"""Offline tests for the fetch module: parsing, normalisation, ID lists, manifest."""

import json
from pathlib import Path

import pytest

from pipeline import fetch
from pipeline.fetch import FetchError, normalise, parse_pubmed_xml, read_ids

FIXTURES = Path(__file__).parent / "fixtures"


def test_normalise_collapses_whitespace_and_unicode():
    assert normalise("a  b\n\tc") == "a b c"
    assert normalise("loss‑of‑function") == "loss-of-function"


def test_parse_pubmed_xml_builds_a_stub_with_a_normalised_abstract():
    stubs = parse_pubmed_xml((FIXTURES / "pubmed_good.xml").read_bytes())
    stub = stubs["34287911"]
    assert stub["title"] == "SCN2A R853Q study title"
    assert stub["journal"] == "Brain"
    assert stub["year"] == "2021"
    assert stub["doi"] == "10.1000/x"
    assert stub["publication_types"] == ["Journal Article"]
    assert stub["abstract"] == (
        "First part with inline markup. "
        "Heterologously expressed R853Q channels exhibit an overall loss-of-function."
    )
    assert len(stub["abstract_sha256"]) == 64


def test_missing_abstract_is_a_hard_error_naming_the_pmid():
    with pytest.raises(FetchError, match="11111111"):
        parse_pubmed_xml((FIXTURES / "pubmed_no_abstract.xml").read_bytes())


def test_read_ids_skips_comments_and_repeats_and_rejects_bad_ids(tmp_path):
    path = tmp_path / "ids.txt"
    path.write_text("# header\n34287911  # note\n\n34287911\nNCT01238250\n")
    with pytest.raises(FetchError, match="NCT01238250"):
        read_ids(path, r"[0-9]{1,9}")
    path.write_text("# header\n34287911  # note\n\n34287911\n20956790\n")
    assert read_ids(path, r"[0-9]{1,9}") == ["34287911", "20956790"]


def test_committed_id_lists_parse():
    pmids = read_ids(fetch.SEED / "pmids.txt", r"[0-9]{1,9}")
    ncts = read_ids(fetch.SEED / "ncts.txt", r"NCT[0-9]{8}")
    assert "34287911" in pmids and len(pmids) >= 60
    assert {"NCT01238250", "NCT06555965", "NCT05818553"} <= set(ncts)


def test_manifest_merges_sources_and_hashes_files_but_skips_codex_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "RAW", tmp_path)
    (tmp_path / "ctgov").mkdir()
    (tmp_path / "ctgov" / "NCT1.json").write_text("{}")
    (tmp_path / "codex-runs").mkdir()
    (tmp_path / "codex-runs" / "x.jsonl").write_text("{}")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"sources": {"hpo": {"retrieved": "2020-01-01", "release": "v1"}}, "files": {}})
    )
    assert fetch.write_manifest({"ctgov": "api v2"}) == 1
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert list(manifest["files"]) == ["ctgov/NCT1.json"]
    assert len(manifest["files"]["ctgov/NCT1.json"]["sha256"]) == 64
    assert manifest["sources"]["hpo"] == {"retrieved": "2020-01-01", "release": "v1"}  # kept
    assert manifest["sources"]["ctgov"]["release"] == "api v2"
    assert manifest["sources"]["ctgov"]["retrieved"][:2] == "20"
    (tmp_path / "manifest.json").write_text('{"retrieved": "old format"}')
    assert fetch.write_manifest({}) == 1  # an older manifest is tolerated


def test_main_rejects_unknown_source(capsys):
    assert fetch.main(["nope"]) == 2
    assert "unknown source" in capsys.readouterr().out


# --- Parser failure modes -----------------------------------------------------------


def test_structured_abstract_skips_funding_and_adds_sentence_boundaries():
    stub = parse_pubmed_xml((FIXTURES / "pubmed_structured.xml").read_bytes())["22222222"]
    assert stub["abstract"] == "We asked a question. Channels showed loss of function."
    assert stub["year"] == "2020"  # from ArticleDate when PubDate is empty


def test_retracted_record_is_refused():
    with pytest.raises(FetchError, match="33333333"):
        parse_pubmed_xml((FIXTURES / "pubmed_retracted.xml").read_bytes())


def test_ncbi_error_body_and_entities_are_refused():
    with pytest.raises(FetchError, match="NCBI returned an error"):
        parse_pubmed_xml(b"<eFetchResult><ERROR>Bad id</ERROR></eFetchResult>")
    with pytest.raises(FetchError, match="entity"):
        parse_pubmed_xml(b'<!DOCTYPE x [<!ENTITY a "b">]><PubmedArticleSet/>')


def test_missing_title_is_a_fetch_error_not_a_crash():
    xml = (FIXTURES / "pubmed_good.xml").read_bytes()
    xml = xml.replace(b"<ArticleTitle>SCN2A  <i>R853Q</i> study title</ArticleTitle>", b"")
    with pytest.raises(FetchError, match="no title for PMID 34287911"):
        parse_pubmed_xml(xml)


def test_normalise_drops_invisible_characters_and_folds_quotes():
    assert normalise("soft­hyphen​ „quote‟") == 'softhyphen "quote"'
    assert normalise(normalise("a‑b ’c")) == normalise("a‑b ’c")


def test_env_value_tolerates_spaces_and_export(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "REPO", tmp_path)
    (tmp_path / ".env").write_text("export NCBI_EMAIL = team@example.org  # note\nNCBI_API_KEY=\n")
    assert fetch.env_value("NCBI_EMAIL") == "team@example.org"
    assert fetch.env_value("NCBI_API_KEY") == ""


# --- HTTP client with a mocked session ------------------------------------------------


class FakeResponse:
    def __init__(self, status, content=b"{}", headers=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {}


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.headers = {}

    def get(self, url, params=None, data=None, timeout=None):
        self.calls += 1
        return self.responses.pop(0)

    post = get


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "REPO", tmp_path)  # no .env: the email warning is expected
    monkeypatch.setattr(fetch.time, "sleep", lambda seconds: None)
    with pytest.warns(UserWarning, match="NCBI_EMAIL"):
        c = fetch.Client()
    return c


def test_4xx_fails_at_once_with_host_and_status_and_no_url(client):
    client.session = FakeSession([FakeResponse(404)])
    with pytest.raises(FetchError, match=r"^clinicaltrials\.gov: HTTP 404$"):
        client.get("https://clinicaltrials.gov/api/v2/studies/NCT0?email=x@y.org")
    assert client.session.calls == 1


def test_5xx_and_429_are_retried_then_reported(client, monkeypatch):
    waits: list[int] = []
    monkeypatch.setattr(fetch.time, "sleep", waits.append)
    client.session = FakeSession(
        [
            FakeResponse(503),
            FakeResponse(429, headers={"Retry-After": "3600"}),
            FakeResponse(200, b"ok"),
        ]
    )
    assert client.get("https://example.org/x") == b"ok"
    assert waits == [1, fetch.MAX_RETRY_WAIT]  # backoff, then the capped Retry-After
    client.session = FakeSession([FakeResponse(500)] * fetch.RETRIES)
    with pytest.raises(FetchError, match="HTTP 500 after 4 attempts"):
        client.get("https://example.org/x")


def test_ctgov_names_the_nct_on_failure_and_on_id_mismatch(client, monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "RAW", tmp_path)
    client.session = FakeSession([FakeResponse(404)])
    with pytest.raises(
        FetchError, match="ClinicalTrials.gov NCT00000001: clinicaltrials.gov: HTTP 404"
    ):
        fetch.fetch_ctgov(client, ["NCT00000001"])
    body = b'{"protocolSection": {"identificationModule": {"nctId": "NCT00000002"}}}'
    client.session = FakeSession([FakeResponse(200, body)])
    with pytest.raises(FetchError, match="NCT00000001: record has a different id"):
        fetch.fetch_ctgov(client, ["NCT00000001"])


def test_pubmed_reports_a_pmid_missing_from_the_batch_and_removes_stale_stubs(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(fetch, "RAW", tmp_path / "raw")
    monkeypatch.setattr(fetch, "WORK", tmp_path / "work")
    good = (FIXTURES / "pubmed_good.xml").read_bytes()
    client.session = FakeSession([FakeResponse(200, good)])
    with pytest.raises(FetchError, match="no record returned for PMID\\(s\\) 99999999"):
        fetch.fetch_pubmed(client, ["34287911", "99999999"])
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "11111111.json").write_text("{}")  # no longer in the list
    client.session = FakeSession([FakeResponse(200, good)])
    assert fetch.fetch_pubmed(client, ["34287911"]) == 1
    assert sorted(p.name for p in (tmp_path / "work").iterdir()) == ["34287911.json"]


def test_g2p_refuses_pagination_and_foreign_genes(client, monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "RAW", tmp_path)
    client.session = FakeSession([FakeResponse(200, b'{"next": "page2", "results": []}')])
    with pytest.raises(FetchError, match="SCN2A: more than one page"):
        fetch.fetch_g2p(client, ("SCN2A",))
    client.session = FakeSession(
        [FakeResponse(200, b'{"next": null, "results": [{"gene": "SCN8A"}]}')]
    )
    with pytest.raises(FetchError, match="SCN2A: result for another gene"):
        fetch.fetch_g2p(client, ("SCN2A",))


def test_failed_source_is_not_recorded_as_retrieved(client, monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "RAW", tmp_path)
    monkeypatch.setattr(fetch, "SEED", FIXTURES.parent.parent / "seed")
    monkeypatch.setattr(fetch, "Client", lambda: client)
    client.session = FakeSession([FakeResponse(404)] * 50)
    assert fetch.main(["ctgov"]) == 1
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert "ctgov" not in manifest["sources"]


def test_non_json_200_response_names_the_id(client, monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "RAW", tmp_path)
    client.session = FakeSession([FakeResponse(200, b"<html>maintenance</html>")])
    with pytest.raises(FetchError, match="ClinicalTrials.gov NCT00000001: response is not JSON"):
        fetch.fetch_ctgov(client, ["NCT00000001"])

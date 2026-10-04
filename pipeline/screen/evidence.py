"""``make screen-fetch`` step 2: evidence pairing each approved family drug with each line gene.

PubMed E-utilities (count + up to five PMIDs for ``"<drug>"[tiab] AND "<GENE>"[tiab]``,
titles by esummary; the preferred name and the bare gene symbol only, so counts are lower
bounds) and ClinicalTrials.gov v2 (``query.intr`` = the drug, ``query.term`` = the gene: NCT,
status, verbatim ``whyStopped`` unless it may name a person, dates). The join was checked by
hand on 2026-10-04 against a pair known to have a record (an investigational SCN2A compound):
it returns that record, so an empty result for an approved drug is a real zero. Runs once at
fetch time with NCBI etiquette delays; the build never searches. Raw responses stay in
gitignored ``data/raw/screen/``; the cache keeps allow-listed fields and ``retrieved``.
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from pipeline.check_public import PERSON_TITLE
from pipeline.ctgov import NAME_HEADINGS, NAME_LIKE
from pipeline.fetch import RAW, SEED, Client, normalise
from pipeline.screen.config import MAX_PMIDS_PER_PAIR, SCREEN_LINE_KEYS, SODIUM_CHANNEL_FAMILY
from pipeline.screen.funnel import approved_only, family_filter, pair_key
from pipeline.screen.opentargets import CACHE_DIR, POOL_CACHE

EVIDENCE_CACHE = CACHE_DIR / "evidence.json"
RAW_DIR = RAW / "screen"
CTGOV_SEARCH = "https://clinicaltrials.gov/api/v2/studies"
CTGOV_FIELDS = "NCTId,OverallStatus,WhyStopped,StartDate,LastUpdatePostDate"
CTGOV_PAUSE_SECONDS = 0.3
PUBMED_QUERY_FORM = '"DRUG NAME"[tiab] AND "GENE"[tiab]'
TAG = re.compile(r"<[^>]+>")


def line_genes(lines_file: Path = SEED / "lines.yaml") -> list[str]:
    """Genes of the seeded lines in screen scope (the evidence is fetched per gene)."""
    rows = yaml.safe_load(lines_file.read_text()) or []
    return sorted({r["gene"] for r in rows if r.get("key") in SCREEN_LINE_KEYS})


def pubmed_pair(client: Client, name: str, gene: str) -> tuple[int, list[str], bytes]:
    term = f'"{name}"[tiab] AND "{gene}"[tiab]'
    raw = client.ncbi(
        "esearch.fcgi",
        {"db": "pubmed", "term": term, "retmax": MAX_PMIDS_PER_PAIR, "retmode": "json"},
    )
    result = json.loads(raw)["esearchresult"]
    pmids = [p for p in result.get("idlist", []) if p.isdigit()]
    return int(result.get("count", 0)), pmids, raw


def pubmed_titles(client: Client, pmids: list[str]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for start in range(0, len(pmids), 100):
        chunk = pmids[start : start + 100]
        params = {"db": "pubmed", "id": ",".join(chunk), "retmode": "json"}
        raw = client.ncbi("esummary.fcgi", params)
        result = json.loads(raw).get("result", {})
        for pmid in chunk:
            title = result.get(pmid, {}).get("title", "")
            if title:
                titles[pmid] = normalise(html.unescape(TAG.sub("", title)))[:300]
    return titles


ALL_CAPS_NAME = re.compile(
    r"\b[A-Z]{2,}\s+[A-Z]{2,}\s+[A-Z]{3,}\b"
)  # "PI JANE DOE", "WU XIAO LEFT"
INITIAL_SURNAME = re.compile(r"\b[A-Z]\.\s*[A-Z][a-z]+")  # "J. Smith"
ROLE_WORD = re.compile(r"\b(?:PI|investigator|study lead|sponsor contact|coordinator)\b", re.I)


def looks_like_a_name(text: str) -> bool:
    """A person's title, two capitalised non-institution words in a row (A5's heuristic), or
    three all-caps words in a row."""
    if PERSON_TITLE.search(text) or ALL_CAPS_NAME.search(text) or INITIAL_SURNAME.search(text):
        return True
    if ROLE_WORD.search(text):
        return True
    return any(m.group(0) not in NAME_HEADINGS for m in NAME_LIKE.finditer(text))


def strip_study(study: dict) -> dict:
    """Allow-listed fields only; the stop reason is withheld whenever it may name a person."""
    ident = study.get("protocolSection", {}).get("identificationModule", {})
    status = study.get("protocolSection", {}).get("statusModule", {})
    why = status.get("whyStopped")
    withheld = bool(why and looks_like_a_name(why))
    return {
        "nct": ident.get("nctId", ""),
        "status": status.get("overallStatus", "UNKNOWN"),
        "why_stopped": None if withheld or not why else normalise(why)[:400],
        "why_stopped_withheld": withheld,
        "start_date": (status.get("startDateStruct") or {}).get("date"),
        "last_update": (status.get("lastUpdatePostDateStruct") or {}).get("date"),
    }


def ctgov_pair(client: Client, name: str, gene: str) -> tuple[list[dict], bytes]:
    time.sleep(CTGOV_PAUSE_SECONDS)
    raw = client.get(
        CTGOV_SEARCH,
        {"query.intr": name, "query.term": gene, "fields": CTGOV_FIELDS, "pageSize": 50},
    )
    studies = [strip_study(s) for s in json.loads(raw).get("studies", [])]
    return sorted((s for s in studies if s["nct"]), key=lambda s: s["nct"]), raw


def fetch_evidence(client: Client, pool: dict, genes: list[str]) -> dict:
    drugs, _ = family_filter(approved_only(pool["drugs"]), SODIUM_CHANNEL_FAMILY)
    (RAW_DIR / "pubmed").mkdir(parents=True, exist_ok=True)
    (RAW_DIR / "ctgov").mkdir(parents=True, exist_ok=True)
    pairs: dict[str, dict] = {}
    for drug in drugs:
        for gene in genes:
            key = pair_key(drug["drug_id"], gene)
            count, pmids, raw = pubmed_pair(client, drug["name"], gene)
            (RAW_DIR / "pubmed" / f"{drug['drug_id']}_{gene}.json").write_bytes(raw)
            studies, raw = ctgov_pair(client, drug["name"], gene)
            (RAW_DIR / "ctgov" / f"{drug['drug_id']}_{gene}.json").write_bytes(raw)
            pairs[key] = {"pubmed_count": count, "pmids": pmids, "studies": studies}
    wanted = {p for pair in pairs.values() for p in pair["pmids"]}
    wanted |= {
        p
        for d in drugs
        for m in d["mechanisms"]
        if set(m["target_genes"]) & SODIUM_CHANNEL_FAMILY
        for p in m["pmids"]
    }
    titles = pubmed_titles(client, sorted(wanted))
    return {
        "sources": ["PubMed (NLM) E-utilities", "ClinicalTrials.gov API v2"],
        "retrieved": datetime.now(UTC).date().isoformat(),
        "pubmed_query_form": PUBMED_QUERY_FORM,
        "pmids_per_pair": MAX_PMIDS_PER_PAIR,
        "genes": genes,
        "pairs": {k: pairs[k] for k in sorted(pairs)},
        "titles": {k: titles[k] for k in sorted(titles)},
    }


def write_cache(evidence: dict, path: Path = EVIDENCE_CACHE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def main() -> int:
    pool = json.loads(POOL_CACHE.read_text())
    genes = line_genes()
    evidence = fetch_evidence(Client(), pool, genes)
    write_cache(evidence)
    pairs = evidence["pairs"]
    with_paper = sum(bool(p["pmids"]) for p in pairs.values())
    with_study = sum(bool(p["studies"]) for p in pairs.values())
    print(f"genes {genes}; pairs {len(pairs)}; with papers {with_paper}; with studies {with_study}")
    print(f"titles {len(evidence['titles'])}; retrieved {evidence['retrieved']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

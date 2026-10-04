"""``make fetch``: download every public input by the committed ID lists.

Everything lands in gitignored ``data/raw/``; PubMed abstracts become one stub per
PMID in gitignored ``work/``. Output is counts only, never a URL. A missing
abstract is a hard error, because every claim must be checkable against its
abstract. Stale outputs from an earlier, longer ID list are removed. The manifest
records, per source, the release that was downloaded and when.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import unicodedata
import warnings
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

import requests

REPO = Path(__file__).resolve().parent.parent
SEED = REPO / "pipeline" / "seed"
RAW = REPO / "data" / "raw"
WORK = REPO / "work"

GENES = ("SCN2A", "SCN8A", "SCN1A", "KCNQ2", "STXBP1", "CDKL5", "SYNGAP1")
HPO_RELEASE = "v2026-09-01"  # pinned so a re-fetch gets the same ontology
HPO_DOWNLOAD = (
    "https://github.com/obophenotype/human-phenotype-ontology/releases/download/" + HPO_RELEASE
)
ORPHADATA_PRODUCT6 = "https://www.orphadata.com/data/xml/en_product6.xml"
G2P_SEARCH = "https://www.ebi.ac.uk/gene2phenotype/api/search/"
CTGOV_STUDY = "https://clinicaltrials.gov/api/v2/studies/"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
PUBMED_BATCH = 100
NCBI_PAUSE_SECONDS = 0.4
RETRIES = 4
TIMEOUT = 60
MAX_RETRY_WAIT = 30  # seconds; a server's Retry-After beyond this is capped
# Abstract sections that are not findings and would only pad the quote search.
SKIPPED_ABSTRACT_LABELS = {"FUNDING", "CITATION", "DISCLOSURES", "CONFLICT OF INTEREST"}
RETRACTION_TYPES = {"Retracted Publication", "Retraction of Publication"}


class FetchError(RuntimeError):
    """A source could not be fetched completely. The message never contains a URL."""


# --- Normalisation (the only one; validate.py imports it) ---------------------------

# Characters NFKC leaves alone but that break substring matching: dash and quote variants
# become ASCII; soft hyphens, zero-width characters and the BOM are removed.
_FOLD = str.maketrans(
    {c: "-" for c in "‐‑‒–—―−"}
    | {c: "'" for c in "‘’‚‛"}
    | {c: '"' for c in "“”„‟"}
    | {c: None for c in "­​‌‍﻿"}
)


def normalise(text: str) -> str:
    """NFKC, dashes and quotes folded, invisible characters dropped, whitespace collapsed.

    A quote is a substring of its abstract exactly when both went through this function.
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).translate(_FOLD)).strip()


# --- Small helpers ---------------------------------------------------------------


def read_ids(path: Path, pattern: str) -> list[str]:
    """IDs from a committed list: one per line, ``#`` comments ignored, order kept, no repeats."""
    ids: list[str] = []
    for raw in path.read_text().splitlines():
        token = raw.split("#", 1)[0].strip()
        if not token:
            continue
        if not re.fullmatch(pattern, token):
            raise FetchError(f"{path.name}: bad id {token!r}")
        if token not in ids:
            ids.append(token)
    return ids


def env_value(name: str) -> str:
    """Read one variable from .env without exporting anything. Only Python touches .env."""
    env = REPO / ".env"
    if not env.exists():
        return ""
    for line in env.read_text().splitlines():
        m = re.match(rf"^\s*(?:export\s+)?{name}\s*=\s*[\"']?([^\"'#]*)", line)
        if m:
            return m.group(1).strip()
    return ""


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def remove_stale(folder: Path, keep: set[str], suffix: str) -> int:
    """Delete files in ``folder`` whose stem is not in ``keep``. Returns how many went."""
    gone = 0
    if folder.exists():
        for path in folder.glob(f"*{suffix}"):
            if path.stem not in keep:
                path.unlink()
                gone += 1
    return gone


class Client:
    """requests with retries and backoff; NCBI calls carry the etiquette parameters.

    4xx (other than 429) fails at once with the host and status, never a URL.
    """

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "polaris-pipeline/0.1 (research-planning tool)"
        self.ncbi_params = {"tool": "polaris-pipeline"}
        email = env_value("NCBI_EMAIL")
        if email:
            self.ncbi_params["email"] = email
        else:
            warnings.warn(
                "NCBI_EMAIL is empty in .env; NCBI asks for a contact address", stacklevel=2
            )
        api_key = env_value("NCBI_API_KEY")
        if api_key:
            self.ncbi_params["api_key"] = api_key

    def get(self, url: str, params: dict | None = None, *, post: bool = False) -> bytes:
        host = url.split("/")[2]
        for attempt in range(RETRIES):
            try:
                if post:
                    response = self.session.post(url, data=params, timeout=TIMEOUT)
                else:
                    response = self.session.get(url, params=params, timeout=TIMEOUT)
            except requests.RequestException as exc:
                if attempt == RETRIES - 1:
                    raise FetchError(f"{host}: {exc.__class__.__name__}") from exc
                time.sleep(2**attempt)
                continue
            if response.status_code < 400:
                return response.content
            if response.status_code != 429 and response.status_code < 500:
                raise FetchError(f"{host}: HTTP {response.status_code}")
            if attempt < RETRIES - 1:
                retry_after = response.headers.get("Retry-After", "")
                wait = int(retry_after) if retry_after.isdigit() else 2**attempt
                time.sleep(min(wait, MAX_RETRY_WAIT))
        raise FetchError(f"{host}: HTTP {response.status_code} after {RETRIES} attempts")

    def ncbi(self, endpoint: str, params: dict) -> bytes:
        time.sleep(NCBI_PAUSE_SECONDS)
        return self.get(EUTILS + endpoint, {**self.ncbi_params, **params}, post=True)


# --- PubMed ----------------------------------------------------------------------


def _text(element: ElementTree.Element | None) -> str:
    return normalise("".join(element.itertext())) if element is not None else ""


def parse_pubmed_xml(xml_bytes: bytes) -> dict[str, dict]:
    """PubMed efetch XML -> {pmid: stub}.

    Abstract text comes from ``itertext()`` so inline markup never splits a sentence;
    each labelled section ends with a sentence boundary. Raises FetchError for an NCBI
    error body, a retracted record, a record without a title or year, and names every
    PMID without an abstract.
    """
    if b"<!ENTITY" in xml_bytes:
        raise FetchError("PubMed: entity declarations in the response are not accepted")
    root = ElementTree.fromstring(xml_bytes)
    if root.tag == "eFetchResult" or root.find("ERROR") is not None:
        raise FetchError(f"PubMed: NCBI returned an error: {_text(root.find('ERROR'))[:120]}")
    stubs: dict[str, dict] = {}
    missing: list[str] = []
    for article in root.iter("PubmedArticle"):
        pmid = _text(article.find("MedlineCitation/PMID"))
        medline = article.find("MedlineCitation/Article")
        if medline is None or not pmid:
            raise FetchError("PubMed: a record without PMID or Article element")
        title = _text(medline.find("ArticleTitle"))
        if not title:
            raise FetchError(f"PubMed: no title for PMID {pmid}")
        publication_types = [
            _text(e) for e in medline.findall("PublicationTypeList/PublicationType")
        ]
        if RETRACTION_TYPES & set(publication_types):
            raise FetchError(f"PubMed: PMID {pmid} is a retraction or retracted")
        parts: list[str] = []
        for part in medline.findall("Abstract/AbstractText"):
            if (part.get("Label") or "").upper() in SKIPPED_ABSTRACT_LABELS:
                continue
            text = _text(part)
            if text:
                parts.append(text if text[-1] in ".!?" else text + ".")
        abstract = normalise(" ".join(parts))
        if not abstract:
            missing.append(pmid)
            continue
        year = (
            medline.findtext("Journal/JournalIssue/PubDate/Year")
            or medline.findtext("Journal/JournalIssue/PubDate/MedlineDate", "")[:4]
            or medline.findtext("ArticleDate/Year", "")
        )
        if not re.fullmatch(r"\d{4}", year or ""):
            raise FetchError(f"PubMed: no publication year for PMID {pmid}")
        doi = next(
            (
                normalise(e.text or "")
                for e in article.findall("PubmedData/ArticleIdList/ArticleId")
                if e.get("IdType") == "doi"
            ),
            None,
        )
        stubs[pmid] = {
            "pmid": pmid,
            "title": title,
            "journal": normalise(medline.findtext("Journal/Title", "")),
            "year": year,
            "doi": doi,
            "publication_types": publication_types,
            "abstract": abstract,
            "abstract_sha256": hashlib.sha256(abstract.encode()).hexdigest(),
        }
    if missing:
        raise FetchError(f"PubMed: no abstract for PMID(s) {', '.join(missing)}")
    return stubs


def fetch_pubmed(client: Client, pmids: list[str]) -> int:
    stubs: dict[str, dict] = {}
    batches = [pmids[i : i + PUBMED_BATCH] for i in range(0, len(pmids), PUBMED_BATCH)]
    for n, batch in enumerate(batches):
        xml_bytes = client.ncbi(
            "efetch.fcgi",
            {"db": "pubmed", "id": ",".join(batch), "rettype": "abstract", "retmode": "xml"},
        )
        save(RAW / "pubmed" / f"batch_{n:03d}.xml", xml_bytes)
        stubs.update(parse_pubmed_xml(xml_bytes))
    absent = [p for p in pmids if p not in stubs]
    if absent:
        raise FetchError(f"PubMed: no record returned for PMID(s) {', '.join(absent)}")
    remove_stale(RAW / "pubmed", {f"batch_{n:03d}" for n in range(len(batches))}, ".xml")
    WORK.mkdir(exist_ok=True)
    remove_stale(WORK, set(pmids), ".json")
    for pmid, stub in stubs.items():
        (WORK / f"{pmid}.json").write_text(json.dumps(stub, indent=2, ensure_ascii=False) + "\n")
    return len(stubs)


# --- Other sources ---------------------------------------------------------------


def fetch_hpo(client: Client) -> tuple[int, str]:
    for name in ("phenotype.hpoa", "hp.obo", "genes_to_disease.txt"):
        save(RAW / "hpo" / name, client.get(f"{HPO_DOWNLOAD}/{name}"))
    header = (RAW / "hpo" / "phenotype.hpoa").read_text(errors="replace")[:2000]
    version = re.search(r"^#version: (\S+)", header, re.M)
    return 3, f"{HPO_RELEASE} (hpoa {version.group(1) if version else 'unknown'})"


def fetch_orphadata(client: Client) -> tuple[int, str]:
    content = client.get(ORPHADATA_PRODUCT6)
    save(RAW / "orphadata" / "en_product6.xml", content)
    head = content[:1000].decode(errors="replace")
    version = re.search(r'<JDBOR[^>]*\bversion="([^"]+)"', head)
    dated = re.search(r'<JDBOR[^>]*\bdate="([^"]+)"', head)
    software = version.group(1) if version else "unknown"
    data_date = dated.group(1)[:10] if dated else "unknown"
    return 1, f"{software}, data dated {data_date}"


def fetch_g2p(client: Client, genes: tuple[str, ...] = GENES) -> int:
    for gene in genes:
        try:
            content = client.get(G2P_SEARCH, {"type": "gene", "query": gene})
            page = json.loads(content)
        except FetchError as exc:
            raise FetchError(f"Gene2Phenotype {gene}: {exc}") from exc
        except ValueError as exc:
            raise FetchError(f"Gene2Phenotype {gene}: response is not JSON") from exc
        if page.get("next"):
            raise FetchError(f"Gene2Phenotype {gene}: more than one page of results")
        if any(r.get("gene", gene) != gene for r in page.get("results", [])):
            raise FetchError(f"Gene2Phenotype {gene}: result for another gene")
        save(RAW / "g2p" / f"{gene}.json", content)
    remove_stale(RAW / "g2p", set(genes), ".json")
    return len(genes)


def fetch_ctgov(client: Client, ncts: list[str]) -> int:
    for nct in ncts:
        try:
            content = client.get(CTGOV_STUDY + nct)
            record = json.loads(content)
        except FetchError as exc:
            raise FetchError(f"ClinicalTrials.gov {nct}: {exc}") from exc
        except ValueError as exc:
            raise FetchError(f"ClinicalTrials.gov {nct}: response is not JSON") from exc
        if record.get("protocolSection", {}).get("identificationModule", {}).get("nctId") != nct:
            raise FetchError(f"ClinicalTrials.gov {nct}: record has a different id")
        save(RAW / "ctgov" / f"{nct}.json", content)
    remove_stale(RAW / "ctgov", set(ncts), ".json")
    return len(ncts)


# --- Manifest and entry point ----------------------------------------------------


def write_manifest(fetched: dict[str, str]) -> int:
    """Merge this run into ``data/raw/manifest.json``.

    ``fetched`` maps each source fetched in this run to its release label. Sources not
    fetched keep their earlier ``retrieved`` date and release. File hashes are always
    recomputed from disk, so the manifest matches the files even after a partial run.
    """
    path = RAW / "manifest.json"
    manifest = json.loads(path.read_text()) if path.exists() else {}
    manifest = {"sources": manifest.get("sources", {}), "files": {}}
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    for source, release in fetched.items():
        manifest["sources"][source] = {"retrieved": today, "release": release}
    manifest["files"] = {
        str(p.relative_to(RAW)): {"sha256": sha256_of(p), "bytes": p.stat().st_size}
        for p in sorted(RAW.rglob("*"))
        if p.is_file() and p.name != "manifest.json" and "codex-runs" not in p.parts
    }
    RAW.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return len(manifest["files"])


SOURCES = ("hpo", "orphadata", "g2p", "ctgov", "pubmed")


def main(argv: list[str]) -> int:
    chosen = argv or list(SOURCES)
    unknown = [s for s in chosen if s not in SOURCES]
    if unknown:
        print(f"fetch: unknown source(s) {', '.join(unknown)}; choose from {', '.join(SOURCES)}")
        return 2
    client = Client()
    pmids = read_ids(SEED / "pmids.txt", r"[0-9]{1,9}")
    ncts = read_ids(SEED / "ncts.txt", r"NCT[0-9]{8}")
    fetched: dict[str, str] = {}
    try:
        for source in chosen:
            if source == "hpo":
                count, fetched[source] = fetch_hpo(client)
                print(f"hpo: {count} files, release {fetched[source]}")
            elif source == "orphadata":
                count, fetched[source] = fetch_orphadata(client)
                print(f"orphadata: {count} file, version {fetched[source]}")
            elif source == "g2p":
                print(f"g2p: {fetch_g2p(client)} genes")
                fetched[source] = "api, undated"
            elif source == "ctgov":
                print(f"ctgov: {fetch_ctgov(client, ncts)} of {len(ncts)} records")
                fetched[source] = "api v2"
            elif source == "pubmed":
                print(f"pubmed: {fetch_pubmed(client, pmids)} of {len(pmids)} abstracts -> work/")
                fetched[source] = "efetch"
    except FetchError as exc:
        write_manifest(fetched)
        print(f"fetch: FAILED — {exc}")
        return 1
    print(f"manifest: {write_manifest(fetched)} files under data/raw/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

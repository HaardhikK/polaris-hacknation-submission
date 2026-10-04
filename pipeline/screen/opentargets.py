"""``make screen-fetch`` step 1: the drug pool from the Open Targets Platform (CC0 1.0).

Keyless GraphQL. For every gene in the sodium-channel family: the drugs and clinical
candidates listed on the target, collapsed to their ChEMBL parent molecule (salts count
once; esters are separate molecules), with only the allow-listed fields kept: ChEMBL id,
name, synonyms and trade names, clinical stage, mechanisms of action (action type, target
symbols, PubMed reference ids). The "approved
medicines" total is ChEMBL's approved-molecule id list checked against the platform's own
clinical stage and collapsed to ChEMBL parent molecules (salts count once, as in the family
pool; esters are separate molecules); their preferred and trade names are kept, lower-cased, so
the post-check can reject any sentence naming one.
Raw responses stay in gitignored ``data/raw/screen/``; the cache under
``pipeline/screen/cache/`` carries the release and the retrieval date. Output is counts only.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import requests

from pipeline.fetch import RAW, REPO, RETRIES, TIMEOUT, Client, FetchError, normalise
from pipeline.screen.config import APPROVED_STAGES, SODIUM_CHANNEL_FAMILY

GRAPHQL = "https://api.platform.opentargets.org/api/v4/graphql"
RAW_DIR = RAW / "screen" / "opentargets"
CACHE_DIR = REPO / "pipeline" / "screen" / "cache"
POOL_CACHE = CACHE_DIR / "drug_pool.json"
PAUSE_SECONDS = 0.3

DRUG_FIELDS = """
  id name maximumClinicalStage
  synonyms { label } tradeNames { label }
  mechanismsOfAction { rows { actionType targets { approvedSymbol } references { source ids } } }
"""
CANDIDATES_QUERY = (
    "query($id: String!) { target(ensemblId: $id) { approvedSymbol drugAndClinicalCandidates {"
    " count rows { id maxClinicalStage drug { "
    + DRUG_FIELDS
    + " parentMolecule { "
    + DRUG_FIELDS
    + " } } } } } }"
)
META_QUERY = "{ meta { dataVersion { year month } } }"
SEARCH_TARGET = (
    'query($q: String!) { search(queryString: $q, entityNames: ["target"],'
    " page: {index: 0, size: 5}) { hits { id name entity } } }"
)
DRUG_STAGES = (
    "query($ids: [String!]!) { drugs(chemblIds: $ids) { id name maximumClinicalStage"
    " tradeNames { label } parentMolecule { id name maximumClinicalStage tradeNames { label } } } }"
)
# The approved-medicine total: ChEMBL's approved-molecule id list (max_phase 4; the molecule
# endpoint, never document records) checked against the platform's own clinical stage, because
# the platform's search index cannot be paged past 10,000 hits.
CHEMBL_STATUS = "https://www.ebi.ac.uk/chembl/api/data/status.json"
CHEMBL_APPROVED = "https://www.ebi.ac.uk/chembl/api/data/molecule.json"
CHEMBL_PAGE = 1000
DRUGS_BATCH = 500


def graphql(client: Client, query: str, variables: dict | None = None) -> dict:
    """POST one GraphQL query with the client's retry policy. Errors never carry a URL."""
    payload = {"query": query, "variables": variables or {}}
    for attempt in range(RETRIES):
        try:
            response = client.session.post(GRAPHQL, json=payload, timeout=TIMEOUT)
        except requests.RequestException as exc:
            if attempt == RETRIES - 1:
                raise FetchError(f"opentargets: {exc.__class__.__name__}") from exc
            time.sleep(2**attempt)
            continue
        if response.status_code < 400:
            body = response.json()
            if body.get("errors"):
                raise FetchError(f"opentargets: GraphQL error: {body['errors'][0]['message']}")
            return body["data"]
        if response.status_code != 429 and response.status_code < 500:
            raise FetchError(f"opentargets: HTTP {response.status_code}")
        time.sleep(2**attempt)
    raise FetchError(f"opentargets: HTTP {response.status_code} after {RETRIES} attempts")


def release(client: Client) -> str:
    version = graphql(client, META_QUERY)["meta"]["dataVersion"]
    return f"{version['year']}.{version['month']}"


def resolve_gene(client: Client, symbol: str) -> str:
    hits = graphql(client, SEARCH_TARGET, {"q": symbol})["search"]["hits"]
    for hit in hits:
        if hit["entity"] == "target" and hit["name"] == symbol:
            return hit["id"]
    raise FetchError(f"opentargets: no target found for {symbol}")


def strip_drug(drug: dict) -> dict:
    """Keep only the allow-listed fields of one Open Targets drug record."""
    mechanisms = []
    for row in drug.get("mechanismsOfAction", {}).get("rows", []):
        pmids = sorted(
            {
                i
                for ref in row.get("references") or []
                if ref.get("source") == "PubMed"
                for i in ref.get("ids") or []
                if str(i).isdigit()
            }
        )
        mechanisms.append(
            {
                "action_type": str(row.get("actionType") or "").upper(),
                "target_genes": sorted({t["approvedSymbol"] for t in row.get("targets") or []}),
                "pmids": pmids,
            }
        )
    labels = (drug.get("synonyms") or []) + (drug.get("tradeNames") or [])
    synonyms = sorted({normalise(s["label"]) for s in labels if s.get("label")})
    return {
        "drug_id": drug["id"],
        "name": normalise(drug["name"]),
        "synonyms": synonyms,
        "max_stage": drug.get("maximumClinicalStage") or "UNKNOWN",
        "mechanisms": sorted(mechanisms, key=lambda m: (m["action_type"], m["target_genes"])),
    }


def collapse(rows: list[dict]) -> dict[str, dict]:
    """One record per parent molecule; a child's synonyms join the parent's."""
    pool: dict[str, dict] = {}
    for row in rows:
        drug = row["drug"]
        parent = drug.get("parentMolecule") or drug
        record = strip_drug(parent)
        child = strip_drug(drug)
        merged = pool.get(record["drug_id"], record)
        synonyms = set(merged["synonyms"]) | set(child["synonyms"])
        if child["drug_id"] != record["drug_id"]:
            synonyms.add(child["name"])
        merged = {**merged, "synonyms": sorted(synonyms)}
        if child["max_stage"] in APPROVED_STAGES:
            merged["max_stage"] = child["max_stage"]
        pool[record["drug_id"]] = merged
    return pool


def approved_total(client: Client, raw_dir: Path) -> dict:
    """The approved-medicine total and the names behind it.

    ChEMBL lists the approved molecules (max_phase 4; the molecule endpoint, never document
    records); the platform's ``maximumClinicalStage`` decides; salts collapse to their ChEMBL
    parent molecule (esters are separate molecules), as the family pool does, so the two counts
    are comparable. Names with upstream encoding damage (U+FFFD) are dropped.
    """
    status = json.loads(client.get(CHEMBL_STATUS))
    version = str(status.get("chembl_db_version", "unknown"))
    ids: list[str] = []
    offset = 0
    while True:
        raw = client.get(
            CHEMBL_APPROVED,
            {
                "max_phase": 4,
                "only": "molecule_chembl_id",
                "limit": CHEMBL_PAGE,
                "offset": offset,
            },
        )
        (raw_dir / f"chembl_approved_{offset:05d}.json").write_bytes(raw)
        page = json.loads(raw)
        ids.extend(m["molecule_chembl_id"] for m in page.get("molecules", []))
        if not page.get("page_meta", {}).get("next"):
            break
        offset += CHEMBL_PAGE
        time.sleep(PAUSE_SECONDS)
    approved: dict[str, str] = {}  # parent id -> name
    names: set[str] = set()  # preferred names and trade names of approved molecules
    resolved = 0
    for start in range(0, len(ids), DRUGS_BATCH):
        chunk = ids[start : start + DRUGS_BATCH]
        drugs = graphql(client, DRUG_STAGES, {"ids": chunk})["drugs"]
        (raw_dir / f"drug_stages_{start:05d}.json").write_text(json.dumps(drugs))
        resolved += len(drugs)
        for drug in drugs:
            parent = drug.get("parentMolecule") or drug
            stages = {drug.get("maximumClinicalStage"), parent.get("maximumClinicalStage")}
            if stages & APPROVED_STAGES:
                approved[parent["id"]] = normalise(parent.get("name") or drug.get("name") or "")
                for record in (drug, parent):
                    names.add(normalise(record.get("name") or ""))
                    names |= {normalise(t["label"]) for t in record.get("tradeNames") or []}
        time.sleep(PAUSE_SECONDS)
    return {
        "approved_total": len(approved),
        "approved_total_method": (
            "molecules with ChEMBL max_phase 4 whose Open Targets clinical stage is APPROVAL, "
            "collapsed to ChEMBL parent molecules (salts count once; esters are separate "
            "molecules)"
        ),
        "approved_names": sorted({n.lower() for n in names if n and "\ufffd" not in n}),
        "chembl_version": version,
        "chembl_approved_ids": len(ids),
        "chembl_ids_unresolved": len(ids) - resolved,  # ids the platform does not carry
    }


def fetch_pool(client: Client, genes: frozenset[str] = SODIUM_CHANNEL_FAMILY) -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    rel = release(client)
    rows: list[dict] = []
    for gene in sorted(genes):
        ensembl = resolve_gene(client, gene)
        data = graphql(client, CANDIDATES_QUERY, {"id": ensembl})["target"]
        (RAW_DIR / f"{gene}.json").write_text(json.dumps(data))
        rows.extend(data["drugAndClinicalCandidates"]["rows"])
        time.sleep(PAUSE_SECONDS)
    pool = collapse(rows)
    return {
        "source": "Open Targets Platform",
        "licence": "CC0 1.0",
        "release": rel,
        "retrieved": datetime.now(UTC).date().isoformat(),
        "family_genes": sorted(genes),
        **approved_total(client, RAW_DIR),
        "drugs": [pool[k] for k in sorted(pool)],
    }


def write_cache(pool: dict, path: Path = POOL_CACHE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pool, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def main() -> int:
    client = Client()
    pool = fetch_pool(client)
    write_cache(pool)
    actions = Counter(
        m["action_type"]
        for d in pool["drugs"]
        for m in d["mechanisms"]
        if set(m["target_genes"]) & SODIUM_CHANNEL_FAMILY
    )
    approved_family = sum(d["max_stage"] in APPROVED_STAGES for d in pool["drugs"])
    print(f"open targets release {pool['release']}, retrieved {pool['retrieved']}")
    print(
        f"approved total {pool['approved_total']} parent molecules (of"
        f" {pool['chembl_approved_ids']} approved ids in {pool['chembl_version']});"
        f" {len(pool['approved_names'])} names kept for the post-check"
    )
    print(f"family drugs {len(pool['drugs'])} (approved {approved_family})")
    print("action types seen:", dict(sorted(actions.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())

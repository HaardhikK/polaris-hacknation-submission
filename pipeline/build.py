"""``make caches``: the committed caches under ``pipeline/cache/``.

This is the one step that needs the fetched data (``data/raw/``, ``work/``). It turns
the raw records and the validator's result into allow-listed files: the stripped study
records, the ``co_listed_in`` edges, and the accepted claims. Everything after it, including
``make build`` (A6, ``graph.json``), reads committed files only. ``make validate`` fails
when a committed cache is stale.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import yaml

from pipeline.ctgov import CAVEATS, co_listings, load_raw, strip_record
from pipeline.fetch import GENES, RAW, REPO, WORK, read_ids
from pipeline.reporter import CACHE_FILE as REPORTER_CACHE
from pipeline.reporter import render_cache as render_reporter_cache
from pipeline.schema import DIRECTION_GATED_TYPES, AcceptedClaim, Paper, SymptomRow
from pipeline.seed_check import hpo_labels, load_seed
from pipeline.validate import canonical_variant, claim_flags, genes_named, validate_claims

CACHE = REPO / "pipeline" / "cache"
CTGOV_CACHE = CACHE / "ctgov.yaml"
CLAIMS_CACHE = CACHE / "claims_accepted.yaml"
PAPERS_CACHE = CACHE / "papers.yaml"
SYMPTOMS_CACHE = CACHE / "symptoms.yaml"
SOURCES_CACHE = CACHE / "sources.yaml"
COUNTS_CACHE = CACHE / "counts.yaml"
MANIFEST = RAW / "manifest.json"
PMIDS_FILE = REPO / "pipeline" / "seed" / "pmids.txt"
SYMPTOMS_PER_GENE = 15  # the most frequent HPO terms across a gene's diseases
# The data sources behind the site, for the About page: name, page and licence (DATA-LICENSE).
SOURCE_INFO = {
    "pubmed": (
        "PubMed (NLM)",
        "https://pubmed.ncbi.nlm.nih.gov/",
        "NLM terms; abstracts not redistributed",
    ),
    "ctgov": (
        "ClinicalTrials.gov (NLM)",
        "https://clinicaltrials.gov/",
        "public domain, no endorsement implied",
    ),
    "hpo": ("Human Phenotype Ontology", "https://hpo.jax.org/", "HPO licence (attribution)"),
    "orphadata": ("Orphadata (Orphanet)", "https://www.orpha.net/", "CC BY 4.0"),
    "g2p": (
        "Gene2Phenotype (EMBL-EBI)",
        "https://www.ebi.ac.uk/gene2phenotype/",
        "CC0 / EMBL-EBI terms",
    ),
}


def retrieved_on(source: str) -> date:
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    stamp = manifest.get("sources", {}).get(source, {}).get("retrieved")
    if not stamp:
        raise SystemExit(
            f"build: no retrieval date for {source} in data/raw/manifest.json (run make fetch)"
        )
    return date.fromisoformat(stamp)


def render_yaml(header: str, body: object) -> str:
    return header + yaml.safe_dump(body, allow_unicode=True, sort_keys=False)


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def render_ctgov_cache() -> tuple[str, int, int]:
    seed, problems = load_seed()
    if problems:
        raise SystemExit("build: fix the seed first (make validate)")
    retrieved = retrieved_on("ctgov")
    # A study that backs a direction-gated asset of one line (a trial) is named only for that
    # line: the opposite-direction line must never see it as "named in the same study".
    gated_owner: dict[str, set[str]] = {}
    for asset in seed.assets:
        if asset.type in DIRECTION_GATED_TYPES and asset.owner_line:
            for nct in re.findall(r"NCT\d{8}", f"{asset.label} {asset.source.url}"):
                gated_owner.setdefault(nct, set()).add(asset.owner_line)
    records, edges = [], []
    for study in seed.studies:
        raw = load_raw(study.nct)
        records.append(json.loads(strip_record(raw, retrieved).model_dump_json()))
        for edge in co_listings(seed.lines, raw, retrieved):
            if study.nct in gated_owner and edge.line not in gated_owner[study.nct]:
                continue
            row = json.loads(edge.model_dump_json())
            row["kind"] = study.kind.value
            row["retrieved"] = retrieved.isoformat()
            row["caveat"] = CAVEATS.get(study.kind.value, "")
            edges.append(row)
    text = render_yaml(
        "# Written by make caches from data/raw/ctgov/ (ClinicalTrials.gov v2, NLM). Allow-listed\n"
        "# fields only; eligibility text is never committed. Listing does not imply NLM\n"
        "# endorsement.\n",
        {"studies": records, "co_listed_in": edges},
    )
    return text, len(records), len(edges)


def render_claims_cache() -> tuple[str, int]:
    checked, fatal, _ = validate_claims()
    if fatal:
        raise SystemExit("build: claims file is not valid (make validate)")
    rows = []
    for c in checked:
        if not c.accepted:
            continue
        row = {
            **c.claim,
            "variant": canonical_variant(c.claim["variant"] or "")
            if c.claim.get("variant")
            else None,
            "claim_id": c.claim_id,
            "extractor_run_id": c.provenance["extractor_run_id"],
            "agent": c.provenance["agent"],
            "model": c.provenance["model"],
            "flags": claim_flags(c.claim),
        }
        rows.append(json.loads(AcceptedClaim.model_validate(row).model_dump_json()))
    text = render_yaml(
        "# Written by make caches: the claims validate.py accepted, with their run provenance.\n"
        "# Badge on the site: 'Found by AI — checked by code'. Quotes are one sentence each.\n",
        {"claims": rows},
    )
    return text, len(rows)


def render_papers_cache() -> tuple[str, int]:
    """Paper nodes from the fetched stubs: the PubMed strip-list fields, never the abstract.

    ``genes_mentioned`` (symbol in title or abstract) drives the per-line coverage statement.
    """
    retrieved = retrieved_on("pubmed")
    rows = []
    for pmid in read_ids(PMIDS_FILE, r"^[0-9]{1,9}$"):
        stub = json.loads((WORK / f"{pmid}.json").read_text())
        text = f"{stub['title']} {stub['abstract']}"
        named = genes_named(text)  # symbols and protein names (NaV1.2 -> SCN2A)
        genes = [
            g
            for g in GENES
            if g in named or re.search(rf"(?<![A-Za-z0-9]){g}(?![A-Za-z0-9])", text, re.I)
        ]
        paper = Paper(
            pmid=pmid,
            title=stub["title"][:300],
            journal=stub.get("journal") or None,
            year=int(stub["year"]) if str(stub.get("year", "")).isdigit() else None,
            doi=stub.get("doi") or None,
            genes_mentioned=genes,
            retrieved=retrieved,
        )
        rows.append(json.loads(paper.model_dump_json()))
    rows.sort(key=lambda r: r["pmid"])
    text = render_yaml(
        "# Written by make caches from work/<PMID>.json (PubMed efetch, NLM). Strip-list fields\n"
        "# only: PMID, title, journal, year, DOI. Abstracts are never committed.\n",
        {"papers": rows},
    )
    return text, len(rows)


def esearch_term(path: Path = PMIDS_FILE) -> str | None:
    """The one offline PubMed search recorded in the header of pmids.txt."""
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        if "exact term was" in line:
            term = []
            for raw in lines[i + 1 :]:
                if not raw.startswith("#") or raw.strip() == "#":
                    break
                term.append(raw.lstrip("# ").strip())
            return " ".join(term) or None
    return None


def gene_symptom_counts(gene: str) -> dict[str, set[str]]:
    """HPO term -> the diseases of ``gene`` (phenotype.hpoa, positive annotations) carrying it."""
    diseases: set[str] = set()
    for row in (RAW / "hpo" / "genes_to_disease.txt").read_text().splitlines():
        parts = row.split("\t")
        if len(parts) >= 4 and parts[1] == gene:
            diseases.add(parts[3])
    counts: dict[str, set[str]] = {}
    for row in (RAW / "hpo" / "phenotype.hpoa").read_text(errors="replace").splitlines():
        if row.startswith("#"):
            continue
        parts = row.split("\t")
        if len(parts) > 10 and parts[0] in diseases and parts[10] == "P" and not parts[2]:
            counts.setdefault(parts[3], set()).add(parts[0])
    return counts


def symptom_rows(genes: list[str], labels: dict[str, str]) -> list[dict]:
    """The most frequent terms per gene, each emitted for EVERY seeded gene annotated with it,
    so a shared symptom is never attributed to one gene because of the top-N cut."""
    counts = {g: gene_symptom_counts(g) for g in genes}
    seed, _ = load_seed()
    # A curated term of one line is looked up for every seeded gene too, so "Autism" (curated
    # for scn2a_loss) still opens the picker when phenotype.hpoa annotates it to SYNGAP1.
    chosen: set[str] = {t.id for line in seed.lines for t in line.hpo_terms if t.id in labels}
    for gene in genes:
        ranked = sorted(
            counts[gene].items(), key=lambda kv: (-len(kv[1]), labels.get(kv[0], ""), kv[0])
        )
        chosen |= {hp for hp, _ in ranked[:SYMPTOMS_PER_GENE] if hp in labels}
    rows = []
    for gene in genes:
        for hp in sorted(chosen, key=lambda h: labels[h]):
            if hp in counts[gene]:
                rows.append(
                    {
                        "hpo_id": hp,
                        "label": labels[hp],
                        "gene": gene,
                        "diseases": len(counts[gene][hp]),
                    }
                )
    return rows


def render_symptoms_cache() -> tuple[str, int]:
    """Symptom search terms per seeded gene from phenotype.hpoa, labelled from hp.obo."""
    seed, _ = load_seed()
    retrieved = retrieved_on("hpo")
    labels = hpo_labels(RAW / "hpo" / "hp.obo")
    genes = sorted({line.gene for line in seed.lines})
    rows = [
        json.loads(SymptomRow(**row, retrieved=retrieved).model_dump_json())
        for row in symptom_rows(genes, labels)
    ]
    text = render_yaml(
        "# Written by make caches from data/raw/hpo/ (HPO phenotype.hpoa + hp.obo). Per seeded\n"
        "# gene: the HPO terms most often annotated to its diseases, each listed for every seeded\n"
        "# gene that carries it. Official HPO annotations of the gene's diseases, not of one\n"
        "# direction line; the site says so.\n",
        {"symptoms": rows},
    )
    return text, len(rows)


def render_sources_cache() -> str:
    """Release and retrieval date per upstream source, from the fetch manifest."""
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    rows = []
    for key, (name, url, licence) in SOURCE_INFO.items():
        entry = manifest.get("sources", {}).get(key)
        if not entry:
            raise SystemExit(f"build: {key} missing from data/raw/manifest.json (run make fetch)")
        rows.append(
            {
                "key": key,
                "name": name,
                "release": entry["release"],
                "retrieved": entry["retrieved"],
                "url": url,
                "licence": licence,
            }
        )
    return render_yaml(
        "# Written by make caches from data/raw/manifest.json: what was downloaded and when.\n",
        {"sources": rows, "esearch_term": esearch_term()},
    )


def orphanet_direction_labels() -> dict:
    """How many Orphadata gene-disease links carry a gain- or loss-of-function label."""
    text = (RAW / "orphadata" / "en_product6.xml").read_text(encoding="utf-8", errors="replace")
    kinds = re.findall(r'<DisorderGeneAssociationType[^>]*>\s*<Name lang="en">([^<]+)<', text)
    gain = sum(1 for k in kinds if "gain of function" in k.lower())
    loss = sum(1 for k in kinds if "loss of function" in k.lower())
    return {"links": len(kinds), "gain_of_function": gain, "loss_of_function": loss}


def render_counts_cache() -> str:
    """ "How this grows": counts from the downloaded files for the About page. Orphanet entries
    that carry at least one disease-causing gene, and fetched studies naming two or more of the
    seeded genes anywhere in conditions, keywords or the inclusion text."""
    from pipeline.ctgov import inclusion_text
    from pipeline.seed_check import orphanet_genes

    seed, _ = load_seed()
    genes = sorted({line.gene for line in seed.lines})
    groups = orphanet_genes(RAW / "orphadata" / "en_product6.xml")
    multi = []
    for study in seed.studies:
        raw = load_raw(study.nct)
        cond = raw["protocolSection"].get("conditionsModule", {})
        text = (
            " ".join(cond.get("conditions", []) + cond.get("keywords", []))
            + " "
            + inclusion_text(raw)
        )
        named = [g for g in genes if re.search(rf"(?<![A-Za-z0-9]){g}(?![A-Za-z0-9])", text)]
        if len(named) >= 2:
            multi.append({"nct": study.nct, "genes": named})
    body = {
        "orphanet_entries": len(groups),
        "orphanet_entries_with_a_gene": sum(1 for g in groups.values() if g),
        "orphanet_direction_labels": orphanet_direction_labels(),
        "studies_fetched": len(seed.studies),
        "studies_naming_two_or_more_seeded_genes": multi,
        "retrieved": {
            "orphadata": retrieved_on("orphadata").isoformat(),
            "ctgov": retrieved_on("ctgov").isoformat(),
        },
    }
    return render_yaml(
        "# Written by make caches from data/raw/orphadata/ and data/raw/ctgov/: the counts behind\n"
        "# the About page's 'how this grows' line.\n",
        body,
    )


def render_all() -> dict[Path, str]:
    ctgov_text, _, _ = render_ctgov_cache()
    claims_text, _ = render_claims_cache()
    papers_text, _ = render_papers_cache()
    symptoms_text, _ = render_symptoms_cache()
    out = {
        CTGOV_CACHE: ctgov_text,
        CLAIMS_CACHE: claims_text,
        PAPERS_CACHE: papers_text,
        SYMPTOMS_CACHE: symptoms_text,
        SOURCES_CACHE: render_sources_cache(),
        COUNTS_CACHE: render_counts_cache(),
    }
    if (RAW / "reporter").exists():
        seed, _ = load_seed()
        text, _ = render_reporter_cache(
            sorted({ln.gene for ln in seed.lines}), retrieved_on("reporter")
        )
        out[REPORTER_CACHE] = text
    return out


def caches_are_current() -> list[str]:
    """Names of committed caches that differ from a fresh render (empty = current)."""
    return [
        path.name
        for path, text in render_all().items()
        if not path.exists() or path.read_text() != text
    ]


def main() -> int:
    for path, text in render_all().items():
        write_atomic(path, text)
        print(f"caches: -> {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

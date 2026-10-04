"""NIH RePORTER (keyless v2 API): active projects per gene as funding evidence.

``make reporter-fetch`` queries ``/v2/projects/search`` by gene term over recent fiscal
years and keeps the raw answers in gitignored ``data/raw/reporter/``; ``make caches``
renders ``pipeline/cache/reporter.yaml`` with the strip-list fields only (project number,
title, organisation name, fiscal year, dates, the project page URL). Never principal
investigators, programme officers, abstracts or public-health text
(the strip-list in ``pipeline/check_public.py``). Project titles may name medicines and are Level 2
("For researchers") only.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import requests
import yaml

from pipeline.fetch import RAW, REPO
from pipeline.schema import PLAIN_LABEL, Strict

REPORTER_SEARCH = "https://api.reporter.nih.gov/v2/projects/search"
RAW_DIR = RAW / "reporter"
CACHE_FILE = REPO / "pipeline" / "cache" / "reporter.yaml"
FISCAL_YEARS = [2024, 2025, 2026]
PAGE = 100
PAUSE_SECONDS = 1.0
TIMEOUT = 60
PROJECT_PAGE = "https://reporter.nih.gov/project-details/{appl_id}"
KEEP = [
    "ApplId",
    "ProjectNum",
    "ProjectTitle",
    "Organization",
    "FiscalYear",
    "ProjectStartDate",
    "ProjectEndDate",
]


GENE_WORDS = {
    "SCN1A": ("scn1a", "nav1.1", "dravet"),
    "SCN2A": ("scn2a", "nav1.2"),
    "SCN8A": ("scn8a", "nav1.6"),
    "STXBP1": ("stxbp1",),
    "CDKL5": ("cdkl5",),
    "SYNGAP1": ("syngap1", "syngap"),
    "KCNQ2": ("kcnq2", "kv7.2"),
}


FIELD_WORDS = re.compile(r"epilep|seizure|encephalopath|neurodevelop|autism|dravet|\bdee\b")


def names_gene(title: str, gene: str) -> bool:
    """The gene symbol or disease name in the title; a protein name alone (Nav1.6, Nav1.1)
    counts only beside a word of the field, so a cocaine or thermosensation project on the
    same channel is not shown as funding for the disease."""
    low = title.lower()
    words = GENE_WORDS.get(gene, (gene.lower(),))
    if words[0] in low or "dravet" in low and gene == "SCN1A":
        return True
    return any(w in low for w in words[1:]) and bool(FIELD_WORDS.search(low))


class FundingRow(Strict):
    gene: str
    appl_id: int
    project_num: str
    title: PLAIN_LABEL
    organisation: PLAIN_LABEL | None
    fiscal_year: int
    start_date: str | None
    end_date: str | None
    url: str


def fetch_gene(gene: str, session: requests.Session) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        body = {
            "criteria": {
                "advanced_text_search": {
                    "operator": "and",
                    "search_field": "projecttitle,terms",
                    "search_text": gene,
                },
                "fiscal_years": FISCAL_YEARS,
            },
            "include_fields": KEEP,
            "limit": PAGE,
            "offset": offset,
        }
        r = session.post(REPORTER_SEARCH, json=body, timeout=TIMEOUT)
        r.raise_for_status()
        answer = r.json()
        rows += answer.get("results", [])
        total = answer.get("meta", {}).get("total", 0)
        offset += PAGE
        if offset >= total:
            break
        if offset >= 500:
            print(f"reporter: {gene}: {total} records, only the first 500 kept")
            break
        time.sleep(PAUSE_SECONDS)
    return rows


def fetch(genes: list[str]) -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "polaris-pipeline (research planning; keyless)"
    n = 0
    for gene in genes:
        rows = fetch_gene(gene, session)
        (RAW_DIR / f"{gene}.json").write_text(json.dumps(rows, indent=1))
        n += len(rows)
        print(f"reporter: {gene}: {len(rows)} project record(s)")
        time.sleep(PAUSE_SECONDS)
    manifest = RAW / "manifest.json"
    doc = json.loads(manifest.read_text()) if manifest.exists() else {"sources": {}, "files": {}}
    doc.setdefault("sources", {})["reporter"] = {
        "retrieved": datetime.now(UTC).date().isoformat(),
        "release": f"api v2, fiscal years {FISCAL_YEARS[0]}-{FISCAL_YEARS[-1]}",
    }
    manifest.write_text(json.dumps(doc, indent=1))
    return n


def core_number(project_num: str) -> str:
    """``5R01NS000001-03`` -> ``R01NS000001``: one row per project across its yearly records."""
    m = re.match(r"^\d?([A-Z]\d{2}[A-Z]{2}\d{6})", project_num)
    return m.group(1) if m else project_num


def render_cache(genes: list[str], retrieved: date) -> tuple[str, int]:
    """The strip-list fields per project: one row per project core number, only projects whose
    end date is on or after the retrieval date and whose title names the gene (or its protein
    or disease name); a project found only through RePORTER's term index is not evidence."""
    rows: list[dict] = []
    for gene in genes:
        path = RAW_DIR / f"{gene}.json"
        if not path.exists():
            raise SystemExit(f"reporter: {gene} not fetched (make reporter-fetch)")
        seen: set[str] = set()
        raws = sorted(json.loads(path.read_text()), key=lambda r: -int(r.get("fiscal_year", 0)))
        for raw in raws:
            num = raw.get("project_num") or ""
            title = raw.get("project_title") or ""
            end = (raw.get("project_end_date") or "")[:10]
            if not num or core_number(num) in seen or not names_gene(title, gene):
                continue
            if end and end < retrieved.isoformat():
                continue
            seen.add(core_number(num))
            org = (raw.get("organization") or {}).get("org_name")
            row = FundingRow(
                gene=gene,
                appl_id=int(raw["appl_id"]),
                project_num=num,
                title=(raw.get("project_title") or "")[:200],
                organisation=org[:200] if org else None,
                fiscal_year=int(raw["fiscal_year"]),
                start_date=(raw.get("project_start_date") or "")[:10] or None,
                end_date=(raw.get("project_end_date") or "")[:10] or None,
                url=PROJECT_PAGE.format(appl_id=int(raw["appl_id"])),
            )
            rows.append(json.loads(row.model_dump_json()))
    rows.sort(key=lambda r: (r["gene"], -r["fiscal_year"], r["project_num"]))
    text = (
        "# Written by make caches from data/raw/reporter/ (NIH RePORTER v2, keyless). Strip-list\n"
        "# fields only: project number, title, organisation, fiscal year, dates, project page.\n"
        "# Never investigators or abstracts. Titles may name medicines: Level 2 only.\n"
        "# Kept: projects whose end date is on or after the retrieval date and whose title\n"
        "# names the gene.\n"
        + yaml.safe_dump(
            {"retrieved": retrieved.isoformat(), "projects": rows},
            allow_unicode=True,
            sort_keys=False,
        )
    )
    return text, len(rows)


def load_cache(path: Path = CACHE_FILE) -> list[dict]:
    if not path.exists():
        return []
    return (yaml.safe_load(path.read_text()) or {}).get("projects", [])


def main(argv: list[str]) -> int:
    from pipeline.seed_check import load_seed

    seed, _ = load_seed()
    genes = sorted({line.gene for line in seed.lines})
    n = fetch(argv or genes)
    print(f"reporter: {n} record(s) -> data/raw/reporter/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

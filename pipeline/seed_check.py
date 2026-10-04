"""Load the hand-curated seed through the schema and check that every reference resolves.

``make validate`` runs this (A3 adds the claim checks). Exit 1 lists every problem;
0 prints counts. The seed is the human-authored half of the dataset: lines,
organisations, studies, assets, aliases and recorded conflicts. Checks that need a
fetched file (hp.obo, Orphadata) run when the file is present and are reported as
skipped otherwise.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from pipeline.fetch import RAW, read_ids
from pipeline.schema import (
    CHANNEL_GENES,
    Alias,
    AliasKind,
    Asset,
    Conflict,
    Direction,
    Line,
    Organisation,
    Scope,
    Study,
)

SEED = Path(__file__).resolve().parent / "seed"
FILES = {
    "lines": ("lines.yaml", Line),
    "organisations": ("organisations.yaml", Organisation),
    "studies": ("studies.yaml", Study),
    "assets": ("assets.yaml", Asset),
    "aliases": ("aliases.yaml", Alias),
    "conflicts": ("conflicts.yaml", Conflict),
}


@dataclass
class Seed:
    lines: list[Line] = field(default_factory=list)
    organisations: list[Organisation] = field(default_factory=list)
    studies: list[Study] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    aliases: list[Alias] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {name: len(getattr(self, name)) for name in FILES}


def load_seed(folder: Path = SEED) -> tuple[Seed, list[str]]:
    """Parse every seed file. Returns the seed and a list of problems (empty when clean)."""
    seed = Seed()
    problems: list[str] = []
    for attr, (name, model) in FILES.items():
        try:
            rows = yaml.safe_load((folder / name).read_text()) or []
        except yaml.YAMLError as exc:
            problems.append(f"{name}: YAML error: {str(exc).splitlines()[0]}")
            continue
        if not isinstance(rows, list):
            problems.append(f"{name}: must be a list")
            continue
        for i, row in enumerate(rows):
            try:
                getattr(seed, attr).append(model.model_validate(row))
            except ValidationError as exc:
                label = row.get("key") or row.get("id") or row.get("nct") or row.get("term") or i
                for err in exc.errors():
                    where = ".".join(str(x) for x in err["loc"]) or "row"
                    problems.append(f"{name} [{label}] {where}: {err['msg']}")
    return seed, problems


def pmid_mentions(text: str) -> set[str]:
    return set(re.findall(r"\bPMID[ :]?(\d{1,9})\b", text))


def hpo_labels(obo: Path) -> dict[str, str]:
    """``{HP id: name}`` for non-obsolete terms in hp.obo."""
    labels: dict[str, str] = {}
    current: dict[str, str] = {}
    for line in obo.read_text(errors="replace").splitlines():
        if line == "[Term]":
            current = {}
        elif line.startswith("id: HP:"):
            current["id"] = line[4:]
        elif line.startswith("name: ") and "id" in current:
            labels[current["id"]] = line[6:]
        elif line.startswith("is_obsolete: true") and "id" in current:
            labels.pop(current["id"], None)
    return labels


DISEASE_CAUSING = "Disease-causing germline mutation(s)"


def orphanet_genes(product6: Path) -> dict[str, set[str]]:
    """``{ORPHA:code: disease-causing genes}`` from the Orphadata product6 file.

    Candidate, biomarker, modifier and susceptibility links are not counted.
    """
    text = product6.read_text(encoding="utf-8", errors="replace")
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"<OrphaCode>(\d+)</OrphaCode>(.*?)</Disorder>", text, re.S):
        genes: set[str] = set()
        for assoc in re.finditer(
            r"<DisorderGeneAssociation>(.*?)</DisorderGeneAssociation>", m.group(2), re.S
        ):
            symbol = re.search(r"<Symbol>([^<]+)</Symbol>", assoc.group(1))
            kind = re.search(
                r'<DisorderGeneAssociationType[^>]*>\s*<Name lang="en">([^<]+)<', assoc.group(1)
            )
            if symbol and kind and kind.group(1).startswith(DISEASE_CAUSING):
                genes.add(symbol.group(1))
        out[f"ORPHA:{m.group(1)}"] = genes
    return out


def check_references(seed: Seed, folder: Path = SEED, raw: Path = RAW) -> list[str]:
    """Every key, PMID, NCT, HPO term and group code the seed names must resolve."""
    problems: list[str] = []
    pmids = set(read_ids(folder / "pmids.txt", r"[0-9]{1,9}"))
    ncts = set(read_ids(folder / "ncts.txt", r"NCT[0-9]{8}"))
    lines = {line.key: line for line in seed.lines}
    orgs = {org.key: org for org in seed.organisations}
    genes = {line.gene for line in seed.lines}
    mechanisms = {line.mechanism for line in seed.lines}

    for name, keys in (
        ("line", [line.key for line in seed.lines]),
        ("organisation", [org.key for org in seed.organisations]),
        ("study", [study.nct for study in seed.studies]),
        ("asset", [asset.id for asset in seed.assets]),
        ("conflict", [c.id for c in seed.conflicts]),
        ("alias", [a.term.lower() for a in seed.aliases]),
    ):
        seen: set[str] = set()
        for key in keys:
            if key in seen:
                problems.append(f"duplicate {name} {key!r}")
            seen.add(key)

    obo = raw / "hpo" / "hp.obo"
    labels = hpo_labels(obo) if obo.exists() else None
    if labels is None:
        problems.append("skipped: hp.obo not fetched, HPO labels unchecked (run make fetch)")
    product6 = raw / "orphadata" / "en_product6.xml"
    groups = orphanet_genes(product6) if product6.exists() else None
    if groups is None:
        problems.append("skipped: Orphadata not fetched, group aliases unchecked (run make fetch)")

    step_terms = {a.term for a in seed.aliases if a.direction_step}
    for line in seed.lines:
        for org_key in line.organisations:
            if org_key not in orgs:
                problems.append(f"line {line.key}: unknown organisation {org_key!r}")
            elif line.key not in orgs[org_key].lines:
                problems.append(f"line {line.key}: organisation {org_key} does not list it back")
        for term in line.hpo_terms:
            if term.pmid not in pmids:
                problems.append(
                    f"line {line.key}: HPO {term.id} cites PMID {term.pmid} not in pmids.txt"
                )
            if labels is not None and labels.get(term.id) != term.label:
                found = labels.get(term.id)
                problems.append(f"line {line.key}: HPO {term.id} is {found!r}, not {term.label!r}")
        for source in line.sources:
            for pmid in pmid_mentions(source.label):
                if pmid not in pmids:
                    problems.append(f"line {line.key}: source cites PMID {pmid} not in pmids.txt")
        for key, value in line.xrefs.items():
            if key == "orpha_group":
                if groups is not None and line.gene not in groups.get(value, set()):
                    problems.append(f"line {line.key}: Orphanet {value} does not list {line.gene}")
            elif key == "orpha":
                if groups is not None and groups.get(value, set()) != {line.gene}:
                    problems.append(
                        f"line {line.key}: Orphanet {value} is not specific to {line.gene}"
                    )
            elif line.gene in CHANNEL_GENES and value not in step_terms:
                problems.append(f"line {line.key}: xref {value} has no direction-step alias")
    for org in seed.organisations:
        for key in org.lines:
            if key not in lines:
                problems.append(f"organisation {org.key}: unknown line {key!r}")
            elif org.key not in lines[key].organisations:
                problems.append(f"organisation {org.key}: line {key} does not list it back")
    for study in seed.studies:
        if study.nct not in ncts:
            problems.append(f"study {study.nct}: not in ncts.txt")
    for asset in seed.assets:
        if asset.owner_gene not in genes:
            problems.append(f"asset {asset.id}: owner_gene {asset.owner_gene} has no seeded line")
        if asset.scope is Scope.LINE:
            line = lines.get(asset.owner_line or "")
            if line is None:
                problems.append(f"asset {asset.id}: unknown owner_line {asset.owner_line!r}")
            else:
                if line.gene != asset.owner_gene:
                    problems.append(f"asset {asset.id}: owner_gene differs from line {line.key}")
                if asset.direction not in (line.direction, Direction.UNKNOWN):
                    problems.append(f"asset {asset.id}: direction differs from line {line.key}")
        for nct in re.findall(r"NCT\d{8}", asset.label + asset.source.label):
            if nct not in ncts:
                problems.append(f"asset {asset.id}: cites {nct} not in ncts.txt")
        for pmid in pmid_mentions(asset.source.label):
            if pmid not in pmids:
                problems.append(f"asset {asset.id}: cites PMID {pmid} not in pmids.txt")
    for alias in seed.aliases:
        line = lines.get(alias.line) if alias.line else None
        if alias.kind is AliasKind.SYMPTOM:
            problems.append(f"alias {alias.term!r}: symptom aliases are derived at build time")
        if alias.line and line is None:
            problems.append(f"alias {alias.term!r}: unknown line {alias.line!r}")
        elif line is not None and alias.gene and alias.gene != line.gene:
            problems.append(f"alias {alias.term!r}: gene differs from line {line.key}")
        elif line is not None and line.gene in CHANNEL_GENES:
            line_pmids = {p for s in line.sources for p in pmid_mentions(s.label)}
            if alias.kind not in (AliasKind.VARIANT, AliasKind.DISEASE, AliasKind.ORGANISATION):
                problems.append(
                    f"alias {alias.term!r}: a gene name or ID of a split gene never leads to a line"
                )
            elif alias.kind is not AliasKind.VARIANT and not alias.gene:
                problems.append(f"alias {alias.term!r}: name its gene")
            elif alias.gene != line.gene:
                problems.append(f"alias {alias.term!r}: gene differs from line {line.key}")
            elif alias.kind is AliasKind.VARIANT and alias.pmid not in line_pmids:
                problems.append(
                    f"alias {alias.term!r}: PMID {alias.pmid} is not a source of {line.key}"
                )
        if alias.pmid and alias.pmid not in pmids:
            problems.append(f"alias {alias.term!r}: PMID {alias.pmid} not in pmids.txt")
        if alias.mechanism and alias.mechanism not in mechanisms:
            problems.append(f"alias {alias.term!r}: unknown mechanism {alias.mechanism!r}")
        for gene in alias.genes:
            if gene not in genes:
                problems.append(f"alias {alias.term!r}: group gene {gene} has no seeded line")
        if alias.kind is AliasKind.GROUP and groups is not None:
            entry = groups.get(alias.orpha or "", set())
            for gene in alias.genes:
                if gene not in entry:
                    problems.append(
                        f"alias {alias.term!r}: {alias.orpha} has no disease-causing {gene}"
                    )
            if alias.group_size != len(entry):
                size, found = alias.group_size, len(entry)
                problems.append(
                    f"alias {alias.term!r}: group_size {size} but {alias.orpha} has {found}"
                )
    for conflict in seed.conflicts:
        if conflict.line and conflict.line not in lines:
            problems.append(f"conflict {conflict.id}: unknown line {conflict.line!r}")
        for side in conflict.sides:
            for pmid in pmid_mentions(side.source.label):
                if pmid not in pmids:
                    problems.append(f"conflict {conflict.id}: cites PMID {pmid} not in pmids.txt")
    return problems


def rows_awaiting_dates(seed: Seed) -> list[str]:
    """Rows a person still has to open and date (the human URL check)."""
    waiting: list[str] = []
    for org in seed.organisations:
        if org.last_verified is None:
            waiting.append(f"organisation {org.key}")
    for study in seed.studies:
        if study.last_verified is None:
            waiting.append(f"study {study.nct}")
    for asset in seed.assets:
        if asset.last_verified is None or asset.source.retrieved is None:
            waiting.append(f"asset {asset.id}")
    return waiting


def main(strict: bool = False) -> int:
    """``strict`` fails on skipped checks and on rows without verification dates (freeze)."""
    seed, problems = load_seed()
    if not problems:
        problems = check_references(seed)
    skipped = [p for p in problems if p.startswith("skipped:")]
    problems = [p for p in problems if not p.startswith("skipped:")]
    waiting = rows_awaiting_dates(seed) if not problems else []
    for note in skipped:
        print(f"seed: {note}")
    if waiting:
        print(f"seed: {len(waiting)} row(s) await a human verification date: {', '.join(waiting)}")
    if strict:
        problems += skipped + [f"not yet verified by a person: {w}" for w in waiting]
    for problem in problems:
        print(f"seed: {problem}")
    if problems:
        print(f"seed-check: {len(problems)} problem(s)")
        return 1
    counts = ", ".join(f"{n} {name}" for name, n in seed.counts().items())
    print(
        f"seed-check: ok — {counts}" + ("" if not (skipped or waiting) else " (not a full check)")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(strict=os.environ.get("STRICT") == "1"))

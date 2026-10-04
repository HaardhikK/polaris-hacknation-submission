"""``make build``: ``web/public/graph.json``, the one file the site reads.

Reads committed files only (the seed, ``pipeline/cache/``, ``seed/texts.yaml``) and
writes a byte-reproducible JSON document that ``GraphFile`` describes. The JSON schema of
that model is dumped to ``pipeline/graph.schema.json`` for the website. Field names are a
contract with Lane B: changes are additive only.

Nothing here is computed at request time, nothing is mocked: every node and edge traces
back to a seed row with a source URL, a committed cache row with a retrieval date, or a
validator-accepted claim with its Codex provenance.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Literal

import yaml

from pipeline.consistency import run as consistency_check
from pipeline.ctgov import CAVEATS
from pipeline.explain import PROVENANCE_LINE, check_row, facts_for, facts_sha256
from pipeline.fetch import REPO, SEED
from pipeline.reporter import load_cache as load_funding
from pipeline.reporter import names_gene
from pipeline.schema import (
    CHANNEL_GENES,
    HPO_ANNOTATION_LABEL,
    PMID,
    AcceptedClaim,
    Alias,
    AliasKind,
    AssetType,
    CoListing,
    Conflict,
    Direction,
    DirectionBasis,
    HpoAnnotation,
    Intervention,
    Line,
    MechanismFamily,
    Paper,
    Provenance,
    Scope,
    Station,
    Strict,
    StudyKind,
    StudyRecord,
    SymptomRow,
    Transfer,
    TransferStatus,
)
from pipeline.seed_check import Seed, load_seed
from pipeline.texts import (
    PROVENANCE_TEMPLATE,
    block_key,
    card_key,
    proposal_addressee,
    proposal_citations,
    template_proposal,
    template_text,
)
from pipeline.transfer import (
    CLAIMS_CACHE,
    CTGOV_CACHE,
    card,
    claim_usable,
    direction_support,
    known_direction,
    load_accepted_claims,
    note_stopped_studies,
    source_variants,
    unknown_card,
    unknown_key,
    unknown_target,
    variant_on_line,
    variant_verdicts,
)
from pipeline.validate import THREE_TO_ONE, canonical_variant

CACHE = REPO / "pipeline" / "cache"
PAPERS_CACHE = CACHE / "papers.yaml"
SYMPTOMS_CACHE = CACHE / "symptoms.yaml"
SOURCES_CACHE = CACHE / "sources.yaml"
COUNTS_CACHE = CACHE / "counts.yaml"
TEXTS_FILE = SEED / "texts.yaml"
OUT_OF_SCOPE = (
    "Investors, funders and requests for applications that signal money are out of scope for"
    " this map; it shows what communities already built and what the rule lets them borrow."
)
BURDEN_OF_CARE = (
    "What the map does for families today: the free shared resources any rare-disease group"
    " can join are listed on every result page and here, with their registration record where"
    " one exists."
)
GRAPH_FILE = REPO / "web" / "public" / "graph.json"
SCHEMA_FILE = REPO / "pipeline" / "graph.schema.json"
GENERATOR = "polaris pipeline"
BADGE = "Found by AI, checked by code"
CLUSTER_CAPTION = "Groups set by hand from cited lab studies."
FOOTER = (
    "Research-planning tool. Not medical advice. Do not change treatment based on this site."
    " Data and AI text pre-computed {date}."
)
MEDICATION_WARNING = (
    "Not medical advice. Never change or stop a medication without your child's neurologist."
)
# The About page's notice (plan owner, 2026-10-04 11:05: no persistent footer; ``footer`` stays
# in the file for the pages that still read it).
ABOUT_NOTICE = "Not medical advice. Data and AI text pre-computed {date}."
FUNDING_CAPTION = (
    "Matched by the gene name in the project title only; whether the project concerns a gain or"
    " a loss of function is not checked, so a project may concern the other form of this gene."
)
CLUSTER_LABELS = {
    ("sodium_channel", Direction.GAIN): "Sodium channel: works too strongly",
    ("sodium_channel", Direction.LOSS): "Sodium channel: works too weakly",
    ("potassium_channel", Direction.GAIN): "Potassium channel: works too strongly",
    ("potassium_channel", Direction.LOSS): "Potassium channel: works too weakly",
}
NON_CHANNEL_CLUSTER = ("non_channel", "Synapse and signalling genes: gain/loss not used here")
# Display order of the cluster groups on the mini diagram: gain, loss, then non-channel.
CLUSTER_ORDER = {Direction.GAIN.value: 0, Direction.LOSS.value: 1}
STOPPED = ("TERMINATED", "WITHDRAWN", "SUSPENDED")
# The provenance line names the model; only a model id from the Codex recipe may appear there.
CODEX_MODEL = re.compile(r"^gpt-[a-z0-9.-]+$")
LIVE_FOR_VIEW = (
    "RECRUITING",
    "ENROLLING_BY_INVITATION",
    "NOT_YET_RECRUITING",
    "ACTIVE_NOT_RECRUITING",
)
GENERIC_SITE = re.compile(r"\b(?:research site|study site|site \d+|investigational site)\b", re.I)


# --- The contract ----------------------------------------------------------------------


class DataSource(Strict):
    key: str
    name: str
    release: str
    retrieved: date
    url: str
    licence: str


class ClusterGroup(Strict):
    key: str
    label: str
    line_keys: list[str]
    caption: str = CLUSTER_CAPTION


class Counts(Strict):
    lines: int
    genes: int
    organisations: int
    studies: int
    assets: int
    papers: int
    claims: int
    conflicts: int
    aliases: int
    co_listings: int
    transfers: int
    edges: int
    texts_codex: int
    texts_template: int


class HowItGrows(Strict):
    """About-page counts from the downloaded files, with the fixed scope sentences."""

    orphanet_entries: int
    orphanet_entries_with_a_gene: int
    orphanet_direction_labels: dict  # links, gain_of_function, loss_of_function
    studies_fetched: int
    studies_naming_two_or_more_seeded_genes: list[dict]
    lines_covered: int
    genes_covered: int
    free_resources: list[dict]  # open-to-all platforms: id, label, nct, url
    out_of_scope: str = OUT_OF_SCOPE
    burden_of_care: str = BURDEN_OF_CARE
    retrieved: dict[str, str]


class Meta(Strict):
    """``medication_warning``, ``footer`` and every ``transfers.*.banner`` are rendered verbatim
    by the site; ``papers[].title`` and ``claims[].evidence_quote`` never appear at Level 0."""

    source: Literal["real"] = "real"
    built: date  # the latest data retrieval date
    pre_computed: date  # the later of data retrieval and the Codex text run (footer date)
    generator: str = GENERATOR
    schema_version: int = 1
    counts: Counts
    sources: list[DataSource]
    esearch_term: str | None
    cluster_groups: list[ClusterGroup]
    badge: str = BADGE
    footer: str
    about_notice: str  # the About page's two sentences: not medical advice; pre-computed date
    medication_warning: str = MEDICATION_WARNING
    hpo_annotation_label: str = HPO_ANNOTATION_LABEL
    steps_total: int = len(Station)
    consistency_check: dict  # pipeline.consistency.run(): n = 1, agreement not discovery
    how_it_grows: HowItGrows


class DirectionEvidence(Strict):
    """The code-checked functional-assay claim that confirms a channel line's hand label."""

    level: Literal["checked by code"] = "checked by code"
    pmid: PMID
    variant: str
    quote: str
    claim_id: str


class Coverage(Strict):
    """ "What we searched and when" for one line: every fetched paper that names the gene."""

    pmids_searched: list[PMID]
    papers_mentioning_gene: int
    papers_extracted: int  # fetched papers of this gene that yielded an accepted claim
    esearch_term: str | None
    retrieved: date


class LineNode(Strict):
    key: str
    gene: str
    mechanism: str
    mechanism_family: MechanismFamily
    direction: Direction  # the hand label
    direction_known: Direction  # what the engine acts on (confirmed by a claim, or unknown)
    direction_evidence: DirectionEvidence | None
    label: str
    gloss: str
    mechanism_label: str | None
    xrefs: dict[str, str]
    sources: list[SourceRef]
    hpo_terms: list[HpoAnnotation]
    organisations: list[str]
    cluster_group: str
    coverage: Coverage
    direction_step: bool  # gene-only searches ask "Which direction?"


class SourceRef(Strict):
    label: str
    url: str
    retrieved: date | None


class OrganisationNode(Strict):
    key: str
    name: str
    lines: list[str]
    url: str
    contact_page: str | None
    last_verified: date | None


class ResearcherFields(Strict):
    """Record fields that carry drug names by design: Level 2 ("For researchers") only."""

    brief_title: str
    keywords: list[str]
    interventions: list[Intervention]
    outcome_measures: list[str]


class StudyNode(Strict):
    """The seed row (display name, kind, genes) merged with the stripped record. The display
    title is the seed ``name``; ``researcher`` holds the fields the family path never shows."""

    nct: str
    name: str
    kind: StudyKind
    genes_named: list[str]
    source: SourceRef
    last_verified: date | None
    overall_status: str
    stopped: bool  # "Tried before": shown only behind "For researchers"
    start_date: str | None
    last_update_date: str | None
    why_stopped: str | None
    conditions: list[str]
    minimum_age: str | None
    maximum_age: str | None
    std_ages: list[str]
    study_population: str | None
    lead_sponsor: str | None
    retrieved: date
    human_check: list[str]
    researcher: ResearcherFields


# Cached record fields no view reads, left out of graph.json (data minimisation): study sites
# stay in pipeline/cache/ctgov.yaml for the mechanism view's institution list only.
STUDY_FIELDS_NOT_SHIPPED = ("locations", "phases", "enrollment_count", "enrollment_type")


class AssetNode(Strict):
    id: str
    type: AssetType
    station: Station
    scope: Scope
    label: str
    owner_gene: str
    owner_line: str | None
    direction: Direction
    direction_basis: DirectionBasis | None
    open_to_all: bool
    source: SourceRef
    last_verified: date | None
    nct: str | None
    pmid: str | None


class CoListingEdge(CoListing):
    kind: StudyKind
    retrieved: date
    caveat: str


class StationState(Strict):
    state: Literal["have", "missing", "unknown"]
    why: str
    halted: Literal["stopped", "paused"] | None = None  # the step's own study is not running


class Steps(Strict):
    total: int
    held: int
    unknown: int
    missing: list[str]
    borrowable: list[str]
    mode: Literal["steps"] = "steps"
    sentence: str


class BannerParts(Strict):
    heading: str
    body: str


class TopCard(Strict):
    asset_id: str
    card_type: Literal["borrow", "already_open"]


class Card(Strict):
    """Everything the result page needs for one line (or for a "gene_unknown" card)."""

    line: str
    direction: Direction
    stations: dict[str, StationState]
    steps: Steps
    transfers: list[Transfer]
    banner: str | None  # "Heading: body", rendered verbatim
    banner_parts: BannerParts | None
    named_in_same_study: list[str]  # NCTs naming this line and another community's gene
    top_cards: list[str]  # asset ids of the first three borrow/already-open cards
    top_cards_typed: list[TopCard]


class TextProvenance(Provenance):
    checker: str


class Text(Strict):
    card_key: str
    text: str
    proposal: str | None
    check_first: list[str]
    citations: list[str]  # NCT / PMID identifiers the card rests on
    addressee: str | None  # who a proposal is addressed to
    source: Literal["codex", "template"]
    provenance: TextProvenance | None
    provenance_line: str


class GraphEdge(Strict):
    source_id: str
    target_id: str
    kind: str
    pmid: str | None = None
    nct: str | None = None
    asset_id: str | None = None
    claim_id: str | None = None
    source_url: str | None = None
    retrieved: date | None = None


class TriedBefore(Strict):
    """A stopped or paused study naming the line: Level 2 only, the sponsor's reason verbatim.
    ``state`` is "paused" for a SUSPENDED record (the registry says it may resume), else
    "stopped"; the fixed sentence about stopped studies applies to both."""

    nct: str
    name: str
    overall_status: str
    state: str  # stopped | paused
    why_stopped: str | None
    last_update_date: str | None


class FundingRow(Strict):
    """An NIH RePORTER project naming the gene: funding evidence, Level 2 (titles may name
    medicines). Matched by gene name in the title only, never by direction: ``direction_checked``
    is always false and ``caption`` says so beside every row."""

    gene: str
    appl_id: int
    project_num: str
    title: str
    organisation: str | None
    fiscal_year: int
    start_date: str | None
    end_date: str | None
    url: str
    direction_checked: Literal[False] = False
    caption: str = FUNDING_CAPTION


class MechanismStudy(Strict):
    nct: str
    name: str
    kind: str
    overall_status: str
    state: str  # active | finished_or_unknown | stopped | paused
    caveat: str | None  # the fixed caption of an eligible-gene list, never dropped
    why_stopped: str | None
    lines: list[str]


class MechanismView(Strict):
    """One mechanism x direction cluster for researchers and scouts: who is in it, what they
    hold, and the institutions running studies for two or more of its lines. Contact = the
    organisations' own pages and the study records, never a named person."""

    key: str
    label: str
    lines: list[str]
    genes: list[str]
    organisations: list[dict]  # key, name, url, contact_page
    studies: dict[str, list[MechanismStudy]]  # active | finished_or_unknown | stopped
    models: list[dict]  # id, label, repository_id, owner_gene, url
    outcome_measures: list[dict]  # id, label, pmid, owner_gene
    institutions: list[dict]  # name, roles, lines (two or more of this cluster's lines; never
    # through an eligible-gene list alone)
    shared_assets: int  # resources used by two or more lines of the cluster
    funding_projects: int


class GraphFile(Strict):
    meta: Meta
    lines: list[LineNode]
    organisations: list[OrganisationNode]
    studies: list[StudyNode]
    assets: list[AssetNode]
    papers: list[Paper]
    claims: list[AcceptedClaim]
    conflicts: list[Conflict]
    aliases: list[Alias]
    co_listings: list[CoListingEdge]
    transfers: dict[str, Card]
    texts: dict[str, Text]
    edges: list[GraphEdge]
    tried_before: dict[str, list[TriedBefore]]
    mechanism_view: list[MechanismView]
    funding: list[FundingRow]


# --- Inputs (committed files only) -------------------------------------------------------


def load_yaml(path: Path, key: str) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"{path.relative_to(REPO)} is missing: run make caches")
    return (yaml.safe_load(path.read_text()) or {}).get(key, [])


def load_texts(path: Path = TEXTS_FILE) -> dict[str, dict]:
    if not path.exists():
        return {}
    return (yaml.safe_load(path.read_text()) or {}).get("texts", {})


def dump(model: Strict) -> dict:
    return json.loads(model.model_dump_json())


def source_ref(source) -> SourceRef:
    return SourceRef(label=source.label, url=str(source.url), retrieved=source.retrieved)


# --- Pieces ------------------------------------------------------------------------------


def site_copy(text: str | None) -> str | None:
    """No em dashes in site copy (plan owner, 2026-10-04 11:40): a seed gloss or label written
    "loss of function — the channel works too weakly" is emitted with a colon. The seed keeps
    the dash because ``texts.yaml`` binds the committed Codex texts to a hash of the seed facts."""
    return None if text is None else text.replace(" — ", ": ").replace("—", ",")


def cluster_key(line: Line) -> str:
    if line.gene in CHANNEL_GENES:
        return f"{line.mechanism}_{line.direction.value}"
    return NON_CHANNEL_CLUSTER[0]


def cluster_groups(seed: Seed) -> list[ClusterGroup]:
    groups: dict[str, list[str]] = {}
    for line in seed.lines:
        groups.setdefault(cluster_key(line), []).append(line.key)
    out = []
    for key, keys in groups.items():
        if key == NON_CHANNEL_CLUSTER[0]:
            label = NON_CHANNEL_CLUSTER[1]
        else:
            line = next(ln for ln in seed.lines if ln.key == keys[0])
            label = CLUSTER_LABELS.get((line.mechanism, line.direction), key)
        out.append(ClusterGroup(key=key, label=label, line_keys=sorted(keys)))
    return sorted(out, key=lambda g: (CLUSTER_ORDER.get(g.key.rsplit("_", 1)[-1], 2), g.key))


def direction_evidence(line: Line, claims: list[AcceptedClaim]) -> DirectionEvidence | None:
    if known_direction(line, claims) not in (Direction.GAIN, Direction.LOSS):
        return None
    top = direction_support(line, claims)[0]
    return DirectionEvidence(
        pmid=top.pmid, variant=top.variant or "", quote=top.evidence_quote, claim_id=top.claim_id
    )


def line_nodes(
    seed: Seed, claims: list[AcceptedClaim], papers: list[Paper], esearch: str | None
) -> list[LineNode]:
    """One node per line; coverage counts every fetched paper naming the gene, not only the
    cited ones, and dates it by those papers' retrieval."""
    step_genes = {a.gene for a in seed.aliases if a.direction_step}
    out = []
    for line in seed.lines:
        mine = [p for p in papers if line.gene in p.genes_mentioned]
        mentioning = sorted(p.pmid for p in mine)
        extracted = {c.pmid for c in claims if c.gene == line.gene} & set(mentioning)
        retrieved = max((p.retrieved for p in mine), default=date(1970, 1, 1))
        out.append(
            LineNode(
                key=line.key,
                gene=line.gene,
                mechanism=line.mechanism,
                mechanism_family=line.mechanism_family,
                direction=line.direction,
                direction_known=known_direction(line, claims),
                direction_evidence=direction_evidence(line, claims),
                label=line.label,
                gloss=site_copy(line.gloss),
                mechanism_label=site_copy(line.mechanism_label),
                xrefs=dict(line.xrefs),
                sources=[source_ref(s) for s in line.sources],
                hpo_terms=list(line.hpo_terms),
                organisations=list(line.organisations),
                cluster_group=cluster_key(line),
                coverage=Coverage(
                    pmids_searched=mentioning,
                    papers_mentioning_gene=len(mentioning),
                    papers_extracted=len(extracted),
                    esearch_term=esearch if line.gene == "SCN2A" else None,
                    retrieved=retrieved,
                ),
                direction_step=line.gene in step_genes,
            )
        )
    return out


def study_nodes(seed: Seed, records: dict[str, dict]) -> list[StudyNode]:
    out = []
    for study in seed.studies:
        record = records.get(study.nct)
        if record is None:
            raise SystemExit(
                f"build: {study.nct} is not in pipeline/cache/ctgov.yaml (make caches)"
            )
        rec = StudyRecord.model_validate(record)
        body = dump(rec)
        for field in STUDY_FIELDS_NOT_SHIPPED:
            body.pop(field)
        researcher = ResearcherFields(
            brief_title=body.pop("brief_title"),
            keywords=body.pop("keywords"),
            interventions=[Intervention.model_validate(i) for i in body.pop("interventions")],
            outcome_measures=body.pop("outcome_measures"),
        )
        out.append(
            StudyNode(
                **body,
                name=study.name,
                kind=study.kind,
                genes_named=list(study.genes_named),
                source=source_ref(study.source),
                last_verified=study.last_verified,
                stopped=rec.overall_status in STOPPED,
                researcher=researcher,
            )
        )
    return out


def asset_nodes(seed: Seed) -> list[AssetNode]:
    out = []
    for a in seed.assets:
        text = f"{a.label} {a.source.url}"
        nct = next(iter(re.findall(r"NCT\d{8}", text)), None)
        pmid = next(iter(re.findall(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", text)), None)
        out.append(
            AssetNode(
                id=a.id,
                type=a.type,
                station=a.station,
                scope=a.scope,
                label=a.label,
                owner_gene=a.owner_gene,
                owner_line=a.owner_line,
                direction=a.direction,
                direction_basis=a.direction_basis,
                open_to_all=a.open_to_all,
                source=source_ref(a.source),
                last_verified=a.last_verified,
                nct=nct,
                pmid=pmid,
            )
        )
    return out


def symptom_aliases(seed: Seed, symptoms: list[SymptomRow]) -> list[Alias]:
    """Symptom search terms, one alias per term.

    A term known for one seeded gene leads to that gene: the direction step for a split gene
    (SCN2A, SCN8A, SCN1A), the line otherwise. A term shared by several seeded genes lists
    them in ``genes`` and opens the gene picker. A symptom therefore never routes a family to
    one direction line: the curated terms of ``scn2a_loss`` go through "Which direction?" too.
    """
    seeded = {line.gene for line in seed.lines}
    step_genes = {a.gene for a in seed.aliases if a.direction_step} & seeded
    gene_line = {line.gene: line.key for line in seed.lines if line.gene not in step_genes}
    terms: dict[str, dict] = {}  # lower-cased label -> {label, hpo_id, genes: {gene: note}, pmid}
    for line in seed.lines:
        for term in line.hpo_terms:
            entry = terms.setdefault(
                term.label.lower(), {"label": term.label, "hpo_id": term.id, "genes": {}}
            )
            entry["genes"].setdefault(line.gene, f"{HPO_ANNOTATION_LABEL}, PMID {term.pmid}")
            entry.setdefault("pmid", term.pmid)
    for row in symptoms:
        if row.gene not in seeded:
            continue
        entry = terms.setdefault(
            row.label.lower(), {"label": row.label, "hpo_id": row.hpo_id, "genes": {}}
        )
        entries = "entry" if row.diseases == 1 else "entries"
        entry["genes"].setdefault(
            row.gene,
            f"HPO annotation of {row.diseases} {row.gene} disease {entries} (phenotype.hpoa)",
        )
    out: list[Alias] = []
    for key in sorted(terms):
        entry = terms[key]
        genes = sorted(entry["genes"])
        if len(genes) > 1:
            out.append(
                Alias(
                    term=entry["label"],
                    kind=AliasKind.SYMPTOM,
                    genes=genes,
                    hpo_id=entry["hpo_id"],
                    note=f"symptom listed for {len(genes)} seeded genes: pick the gene",
                )
            )
            continue
        gene = genes[0]
        note = entry["genes"][gene][:200]
        pmid = entry.get("pmid") if note.startswith(HPO_ANNOTATION_LABEL) else None
        if gene in step_genes:
            out.append(
                Alias(
                    term=entry["label"],
                    kind=AliasKind.SYMPTOM,
                    gene=gene,
                    direction_step=True,
                    hpo_id=entry["hpo_id"],
                    pmid=pmid,
                    note=note,
                )
            )
        else:
            out.append(
                Alias(
                    term=entry["label"],
                    kind=AliasKind.SYMPTOM,
                    gene=gene,
                    line=gene_line[gene],
                    hpo_id=entry["hpo_id"],
                    pmid=pmid,
                    note=note,
                )
            )
    return out


def _one_letter(canonical: str) -> str | None:
    """``p.Arg853Gln`` -> ``R853Q``; None for changes with no simple one-letter form."""
    m = re.fullmatch(r"p\.([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2}|Ter)", canonical)
    if not m or m.group(1) not in THREE_TO_ONE or m.group(3) not in THREE_TO_ONE:
        return None
    return f"{THREE_TO_ONE[m.group(1)]}{m.group(2)}{THREE_TO_ONE[m.group(3)]}"


def emitted_aliases(seed: Seed, claims: list[AcceptedClaim]) -> list[Alias]:
    """Seed aliases plus one variant alias per code-checked assay variant.

    A hand-written variant alias is kept only when an accepted, unhedged, supporting
    functional-assay claim of its PMID names that gene, that variant and the line's direction.
    Every other such claim of a seeded channel gene adds aliases of its own (three spellings),
    pointing at the line of its direction; a variant whose assays disagree gets a ``mixed``
    alias that opens the "Sources disagree" state. No person signs claims for this submission;
    every claim ships as checked by code.
    """
    lines = {line.key: line for line in seed.lines}
    by_gene_dir = {(line.gene, line.direction): line.key for line in seed.lines}
    verdicts = {g: variant_verdicts(claims, g) for g in {line.gene for line in seed.lines}}
    accepted: set[tuple[str, str, str, Direction]] = set()
    for c in claims:
        if claim_usable(c, c.gene):
            accepted.add((c.pmid, c.gene, canonical_variant(c.variant or "") or "", c.direction))
    out: list[Alias] = []
    seen: set[str] = set()
    for a in seed.aliases:
        if a.kind is AliasKind.VARIANT:
            line = lines.get(a.line or "")
            canon = canonical_variant(a.term.split(" ", 1)[-1]) or ""
            if line is None or (a.pmid, a.gene, canon, line.direction) not in accepted:
                continue
            if verdicts.get(a.gene, {}).get(canon) is not line.direction:
                continue  # the variant's assays disagree: the generated mixed alias wins
        out.append(a)
        seen.add(a.term.lower())
    generated: dict[tuple[str, str], tuple[Direction, str]] = {}  # (gene, canon) -> (dir, pmid)
    mixed_pmids: dict[tuple[str, str], set[str]] = {}
    for c in sorted(claims, key=lambda c: (c.pmid, c.claim_id)):
        if c.gene not in CHANNEL_GENES or c.gene not in verdicts or not c.variant:
            continue
        canon = canonical_variant(c.variant) or ""
        verdict = verdicts[c.gene].get(canon)
        if verdict is Direction.MIXED or (
            verdict in (Direction.GAIN, Direction.LOSS) and claim_usable(c, c.gene)
        ):
            generated.setdefault((c.gene, canon), (verdict, c.pmid))
        if verdict is Direction.MIXED:
            mixed_pmids.setdefault((c.gene, canon), set()).add(c.pmid)
    conflicts = {
        (c.gene, canonical_variant(c.variant or "") or ""): c for c in seed.conflicts if c.variant
    }
    for (gene, canon), (verdict, pmid) in sorted(generated.items()):
        pmids = sorted(mixed_pmids.get((gene, canon), set()))
        if (gene, canon) in conflicts:
            mixed_note = f"lab reports disagree on this variant: {conflicts[(gene, canon)].note}"[
                :200
            ]
        elif len(pmids) > 1:
            mixed_note = (
                f"lab studies disagree on this variant's direction (PMIDs {', '.join(pmids)})"
            )
        else:
            mixed_note = f"one lab study found effects in both directions (PMID {pmid})"
        one = _one_letter(canon)
        spellings = [f"{gene} {canon}"] + ([f"{gene} p.{one}", f"{gene} {one}"] if one else [])
        for term in spellings:
            if term.lower() in seen:
                continue
            seen.add(term.lower())
            if verdict is Direction.MIXED:
                out.append(
                    Alias(
                        term=term,
                        kind=AliasKind.VARIANT,
                        gene=gene,
                        pmid=pmid,
                        variant_direction=Direction.MIXED,
                        note=mixed_note,
                    )
                )
            elif (gene, verdict) in by_gene_dir and (
                not lines[by_gene_dir[(gene, verdict)]].variant_aliases_from_sources_only
                or canon in source_variants(lines[by_gene_dir[(gene, verdict)]])
            ):
                out.append(
                    Alias(
                        term=term,
                        kind=AliasKind.VARIANT,
                        gene=gene,
                        line=by_gene_dir[(gene, verdict)],
                        pmid=pmid,
                        note="emitted from a code-checked functional-assay claim",
                    )
                )
            else:
                # the direction is code-checked but no line of that form is shipped (or the
                # line's sources do not tie this variant to its disease): the gated route
                out.append(
                    Alias(
                        term=term,
                        kind=AliasKind.VARIANT,
                        gene=gene,
                        pmid=pmid,
                        variant_direction=verdict,
                        note="code-checked direction; no shipped form of this variant's disease",
                    )
                )
    return out


def texts_for(
    cards: dict[str, dict], seed: Seed, claims: list[AcceptedClaim], committed: dict[str, dict]
) -> dict[str, Text]:
    """One text per card: the committed Codex text when it still passes, else the template.

    A committed text is used only if its ``facts_sha256`` equals the hash of the card's current
    facts and the post-check passes again against those facts; otherwise the card has moved
    since ``make explain`` and the template stands in.
    """
    lines = {line.key: line for line in seed.lines}
    labels = {a.id: a.label for a in seed.assets}
    out: dict[str, Text] = {}
    for key, c in cards.items():
        target = lines.get(key)
        if target is None:  # a "gene_unknown" card: templates against the stand-in line
            target = unknown_target(key.split("_unknown")[0].upper(), seed)
        held = [s for s, v in c["stations"].items() if v["state"] == "have"]
        for raw in c["transfers"]:
            t = Transfer.model_validate(raw)
            ck = card_key(key, t.asset_id)
            facts = facts_for(t, target, lines, labels, claims, held)
            common = {
                "card_key": ck,
                "check_first": list(t.check_first),
                "citations": proposal_citations(t),
                "addressee": proposal_addressee(t, lines),
            }
            row = committed.get(ck)
            takes_proposal = t.status is TransferStatus.VIABLE
            if (
                row
                and row.get("source") == "codex"
                and row.get("facts_sha256") == facts_sha256(facts)
                and check_row(row["text"], row.get("proposal"), facts, takes_proposal) is None
                and CODEX_MODEL.match(str((row.get("provenance") or {}).get("model", "")))
            ):
                provenance = TextProvenance.model_validate(row["provenance"])
                out[ck] = Text(
                    **common,
                    text=row["text"],
                    proposal=row.get("proposal"),
                    source="codex",
                    provenance=provenance,
                    provenance_line=PROVENANCE_LINE.format(
                        model=provenance.model, date=provenance.run_at.date().isoformat()
                    ),
                )
            else:
                out[ck] = Text(
                    **common,
                    text=template_text(t, target, lines),
                    proposal=template_proposal(t, target, lines, held),
                    source="template",
                    provenance=None,
                    provenance_line=PROVENANCE_TEMPLATE,
                )
        if c.get("banner"):
            out[block_key(key)] = Text(
                card_key=block_key(key),
                text=c["banner"],
                proposal=None,
                check_first=[],
                citations=[f"PMID {t['cited_pmid']}" for t in c["transfers"] if t.get("banner")][
                    :1
                ],
                addressee=None,
                source="template",
                provenance=None,
                provenance_line=PROVENANCE_TEMPLATE,
            )
    return out


def banner_parts(banner: str | None) -> BannerParts | None:
    if not banner or ":" not in banner:
        return None
    heading, body = banner.split(":", 1)
    body = body.strip()
    return BannerParts(heading=heading.strip(), body=body[:1].upper() + body[1:])


def finish_card(c: dict, line_key: str, seed: Seed, co: list[CoListingEdge]) -> dict:
    """The fields the result page needs beyond the engine's output."""
    banner = next((t["banner"] for t in c["transfers"] if t.get("banner")), None)
    typed = [
        TopCard(
            asset_id=t["asset_id"],
            card_type="borrow" if t["status"] == TransferStatus.VIABLE.value else "already_open",
        )
        for t in c["transfers"]
        if t["status"] in (TransferStatus.VIABLE.value, TransferStatus.ALREADY_OPEN.value)
    ][:3]
    gene_of = {line.key: line.gene for line in seed.lines}
    genes_in_study: dict[str, set[str]] = {}
    for e in co:
        genes_in_study.setdefault(e.nct, set()).add(gene_of.get(e.line, e.gene))
    mine = {e.nct for e in co if e.line == line_key}
    for station in c["stations"].values():
        station["why"] = site_copy(station["why"])
    c["banner"] = banner
    c["banner_parts"] = dump(banner_parts(banner)) if banner_parts(banner) else None
    c["named_in_same_study"] = sorted(n for n in mine if len(genes_in_study.get(n, set())) > 1)
    c["top_cards"] = [t.asset_id for t in typed]
    c["top_cards_typed"] = [dump(t) for t in typed]
    return c


def build_cards(
    seed: Seed,
    claims: list[AcceptedClaim],
    co: list[CoListingEdge],
    stopped: dict[str, list[dict]] | None = None,
) -> dict:
    """A card per line, plus "gene_unknown" for every direction-step gene (the "Don't know"
    button and any direction without a shipped line): allowed rows only. ``stopped`` is
    ``tried_before``: a line's stopped studies name themselves on a station that would
    otherwise read "none found yet"."""
    cards = {}
    kinds = {s.nct: s.kind.value for s in seed.studies}
    for line in seed.lines:
        c = card(line.key, seed, claims)
        rows = [{**r, "kind": kinds.get(r["nct"], "")} for r in (stopped or {}).get(line.key, [])]
        c["stations"] = note_stopped_studies(c["stations"], rows)
        cards[line.key] = finish_card(c, line.key, seed, co)
    for gene in sorted({a.gene for a in seed.aliases if a.direction_step and a.gene}):
        key = unknown_key(gene)
        cards[key] = finish_card(unknown_card(gene, seed, claims), key, seed, co)
    return cards


def tried_before(seed: Seed, studies: list[StudyNode], co: list[CoListingEdge]) -> dict:
    """Per line: the stopped studies that name it (co-listing) or back one of its assets."""
    by_nct = {s.nct: s for s in studies}
    membership = study_lines(seed, co)
    out: dict[str, list[dict]] = {}
    for line in seed.lines:
        ncts = {nct for nct, keys in membership.items() if line.key in keys}
        rows = []
        for nct in sorted(ncts):
            s = by_nct.get(nct)
            if s and s.stopped:
                rows.append(
                    dump(
                        TriedBefore(
                            nct=nct,
                            name=s.name,
                            overall_status=s.overall_status,
                            state="paused" if s.overall_status == "SUSPENDED" else "stopped",
                            why_stopped=s.why_stopped,
                            last_update_date=s.last_update_date,
                        )
                    )
                )
        out[line.key] = rows
    return out


def edges_for(
    seed: Seed,
    claims: list[AcceptedClaim],
    co: list[CoListingEdge],
    cards: dict[str, dict],
    papers: dict[str, Paper],
) -> list[GraphEdge]:
    """Every edge names its source: a PMID, an NCT, or the page URL of the thing it points to."""
    edges: list[GraphEdge] = []
    orgs = {o.key: o for o in seed.organisations}
    verdicts = {g: variant_verdicts(claims, g) for g in {line.gene for line in seed.lines}}
    for line in seed.lines:
        lid = f"line:{line.key}"
        for org in line.organisations:
            edges.append(
                GraphEdge(
                    source_id=lid,
                    target_id=f"org:{org}",
                    kind="organisation",
                    source_url=str(orgs[org].url) if org in orgs else None,
                    retrieved=orgs[org].last_verified if org in orgs else None,
                )
            )
        for s in line.sources:
            for pmid in re.findall(r"PMID (\d+)", s.label):
                edges.append(
                    GraphEdge(
                        source_id=lid,
                        target_id=f"paper:{pmid}",
                        kind="cited_source",
                        pmid=pmid,
                        source_url=str(s.url),
                        retrieved=s.retrieved,
                    )
                )
        for a in seed.assets:
            if a.owner_gene == line.gene and (a.scope is Scope.GENE or a.owner_line == line.key):
                edges.append(
                    GraphEdge(
                        source_id=lid,
                        target_id=f"asset:{a.id}",
                        kind="holds_asset",
                        asset_id=a.id,
                        source_url=str(a.source.url),
                        retrieved=a.source.retrieved or a.last_verified,
                    )
                )
        for c in claims:
            if c.gene != line.gene:
                continue
            if line.gene in CHANNEL_GENES:
                # a lab-study edge stands for this line only when the engine could use the claim
                # (unhedged, supports) and reads the variant as this direction (uncontested),
                # and the variant may stand for this line; a variant-level review or clinical
                # inference needs the variant to stand for the line too
                if c.direction is not line.direction:
                    continue
                if c.variant and not variant_on_line(line, c.variant):
                    continue
                if c.basis.value == "functional-assay" and c.variant:
                    verdict = verdicts.get(line.gene, {}).get(canonical_variant(c.variant))
                    if verdict is not line.direction or not claim_usable(c, line.gene):
                        continue
            p = papers.get(c.pmid)
            edges.append(
                GraphEdge(
                    source_id=lid,
                    target_id=f"paper:{c.pmid}",
                    kind="claim"
                    if c.basis.value == "functional-assay"
                    else f"claim_{c.basis.value.replace('-', '_')}",
                    pmid=c.pmid,
                    claim_id=c.claim_id,
                    source_url=f"https://pubmed.ncbi.nlm.nih.gov/{c.pmid}/",
                    retrieved=p.retrieved if p else None,
                )
            )
        for conflict in seed.conflicts:
            if conflict.line == line.key or (conflict.line is None and conflict.gene == line.gene):
                edges.append(
                    GraphEdge(
                        source_id=lid,
                        target_id=f"conflict:{conflict.id}",
                        kind="conflict",
                        source_url=str(conflict.sides[0].source.url),
                        retrieved=conflict.sides[0].source.retrieved,
                    )
                )
    for e in co:
        edges.append(
            GraphEdge(
                source_id=f"line:{e.line}",
                target_id=f"study:{e.nct}",
                kind="co_listed_in",
                nct=e.nct,
                source_url=f"https://clinicaltrials.gov/study/{e.nct}",
                retrieved=e.retrieved,
            )
        )
    assets = {a.id: a for a in seed.assets}
    for key, c in cards.items():
        if key not in {line.key for line in seed.lines}:
            continue  # the unknown cards repeat the lines' relations
        for t in c["transfers"]:
            if not t["crosses_gene"] and t["owner_line"] in (None, key):
                continue
            others = (
                [t["owner_line"]]
                if t["owner_line"]
                else [ln.key for ln in seed.lines if ln.gene == t["owner_gene"]]
            )
            a = assets.get(t["asset_id"])
            for other in others:
                if other == key:
                    continue
                edges.append(
                    GraphEdge(
                        source_id=f"line:{key}",
                        target_id=f"line:{other}",
                        kind="blocked" if t["blocked"] else t["status"],
                        pmid=t["cited_pmid"],
                        nct=t["nct"],
                        asset_id=t["asset_id"],
                        source_url=str(a.source.url) if a else None,
                        retrieved=(a.source.retrieved or a.last_verified) if a else None,
                    )
                )
    unique = {
        (e.source_id, e.target_id, e.kind, e.pmid, e.nct, e.asset_id, e.claim_id): e for e in edges
    }
    return [unique[k] for k in sorted(unique, key=lambda k: tuple(str(x) for x in k))]


def funding_rows(rows: list[dict], genes: list[str]) -> list[dict]:
    """The cached RePORTER rows a line may show: a row whose title names only another seeded
    gene is dropped (the cache matches by title, but a title can name a gene other than the one
    searched for)."""
    return [
        r
        for r in rows
        if names_gene(r["title"], r["gene"])
        or not any(names_gene(r["title"], g) for g in genes if g != r["gene"])
    ]


def multi_gene_studies(seed: Seed, counted: list[dict]) -> list[dict]:
    """Studies naming two or more seeded genes: the record-text count from the cache merged with
    the seed's hand-listed ``genes_named`` (restricted to seeded genes), so the About count
    agrees with the co-listings a hand-listed study carries (NCT03635073: CDKL5 and SCN1A)."""
    seeded = {line.gene for line in seed.lines}
    from_text = {row["nct"]: set(row["genes"]) for row in counted}
    out = []
    for study in seed.studies:
        genes = from_text.get(study.nct, set()) | (set(study.genes_named) & seeded)
        if len(genes) >= 2:
            out.append({"nct": study.nct, "genes": sorted(genes)})
    return out


def how_it_grows(seed: Seed, records: dict[str, dict]) -> HowItGrows:
    counts = yaml.safe_load(COUNTS_CACHE.read_text()) if COUNTS_CACHE.exists() else None
    if not counts:
        raise FileNotFoundError("pipeline/cache/counts.yaml is missing: run make caches")
    free = []
    seen: set[str] = set()
    for a in seed.assets:
        if a.open_to_all and str(a.source.url) not in seen:
            seen.add(str(a.source.url))
            nct = next(iter(re.findall(r"NCT\d{8}", f"{a.label} {a.source.url}")), None)
            free.append({"id": a.id, "label": a.label, "nct": nct, "url": str(a.source.url)})
    return HowItGrows(
        orphanet_entries=counts["orphanet_entries"],
        orphanet_entries_with_a_gene=counts["orphanet_entries_with_a_gene"],
        orphanet_direction_labels=counts["orphanet_direction_labels"],
        studies_fetched=counts["studies_fetched"],
        studies_naming_two_or_more_seeded_genes=multi_gene_studies(
            seed, counts["studies_naming_two_or_more_seeded_genes"]
        ),
        lines_covered=len(seed.lines),
        genes_covered=len({line.gene for line in seed.lines}),
        free_resources=free,
        retrieved={k: str(v) for k, v in counts["retrieved"].items()},
    )


def repository_id(label: str, url: str) -> str | None:
    m = re.search(r"JAX (\d+)", label) or re.search(r"jax\.org/strain/(\d+)", url)
    if m:
        return f"JAX:{m.group(1)}"
    m = re.search(r"MMRRC:(\d+-[A-Z]+)", label)
    return f"MMRRC:{m.group(1)}" if m else None


def study_lines(seed: Seed, co: list[CoListingEdge]) -> dict[str, set[str]]:
    """NCT -> the lines a study belongs to: the lines it is co-listed on (the cache already
    drops a direction-gated trial from the opposite-direction line) plus the owner lines of
    the assets that cite it. Never by gene alone, so EMBOLD never lands on scn2a_loss."""
    out: dict[str, set[str]] = {}
    for e in co:
        out.setdefault(e.nct, set()).add(e.line)
    lines_per_gene = Counter(line.gene for line in seed.lines)
    for st in seed.studies:  # a hand-listed gene counts only when that gene has a single line
        for line in seed.lines:
            if line.gene in st.genes_named and lines_per_gene[line.gene] == 1:
                out.setdefault(st.nct, set()).add(line.key)
    for a in seed.assets:
        for nct in re.findall(r"NCT\d{8}", f"{a.label} {a.source.url}"):
            owners = (
                [ln.key for ln in seed.lines if ln.gene == a.owner_gene]
                if a.scope is Scope.GENE
                else [a.owner_line]
            )
            out.setdefault(nct, set()).update(o for o in owners if o)
    return out


def institution_name(name: str) -> str:
    return re.sub(r"^(?:The|the)\s+", "", name.strip())


def mechanism_view(
    seed: Seed,
    groups: list[ClusterGroup],
    studies: list[StudyNode],
    funding: list[dict],
    co: list[CoListingEdge],
    records: dict[str, dict],
) -> list[MechanismView]:
    """Same data as the family path, sorted for researchers: per cluster, ranked by the number
    of resources its lines already share. Study sites come from the cached records (``records``),
    which graph.json does not ship."""
    out = []
    line_by_key = {line.key: line for line in seed.lines}
    orgs = {o.key: o for o in seed.organisations}
    membership = study_lines(seed, co)
    eligibility_only = {s.nct for s in seed.studies if s.kind is StudyKind.ELIGIBLE_GENE_LIST}
    for g in groups:
        lines = [line_by_key[k] for k in g.line_keys]
        genes = sorted({line.gene for line in lines})
        lines_of_gene = {gene: [line.key for line in lines if line.gene == gene] for gene in genes}
        org_rows = []
        for key in sorted({o for line in lines for o in line.organisations}):
            o = orgs[key]
            org_rows.append(
                {
                    "key": key,
                    "name": o.name,
                    "url": str(o.url),
                    "contact_page": str(o.contact_page) if o.contact_page else None,
                }
            )
        active, finished, stopped = [], [], []
        institutions: dict[str, dict] = {}
        for s in studies:
            named = sorted(membership.get(s.nct, set()) & set(g.line_keys))
            if not named:
                continue
            if s.stopped:
                state = "paused" if s.overall_status == "SUSPENDED" else "stopped"
            elif s.overall_status in LIVE_FOR_VIEW:
                state = "active"
            else:
                state = "finished_or_unknown"
            row = MechanismStudy(
                nct=s.nct,
                name=s.name,
                kind=s.kind.value,
                overall_status=s.overall_status,
                state=state,
                caveat=CAVEATS.get(s.kind.value) if s.nct in eligibility_only else None,
                why_stopped=s.why_stopped if s.stopped else None,
                lines=named,
            )
            {"active": active, "finished_or_unknown": finished}.get(state, stopped).append(row)
            if s.nct in eligibility_only:
                continue  # a 107-gene eligibility list is not an institution working on a line
            names = []
            if s.lead_sponsor:
                names.append((s.lead_sponsor, "lead sponsor"))
            sites = records.get(s.nct, {}).get("locations", [])
            names += [(loc["facility"], "study site") for loc in sites if loc.get("facility")]
            for raw_name, role in names:
                if GENERIC_SITE.search(raw_name):
                    continue
                key = institution_name(raw_name).lower()
                entry = institutions.setdefault(
                    key, {"name": institution_name(raw_name), "roles": set(), "lines": set()}
                )
                entry["roles"].add(role)
                entry["lines"].update(named)
        shared_inst = sorted(
            (
                {"name": e["name"], "roles": sorted(e["roles"]), "lines": sorted(e["lines"])}
                for e in institutions.values()
                if len(e["lines"]) >= 2
            ),
            key=lambda r: (-len(r["lines"]), r["name"]),
        )
        models, measures = [], []
        for a in seed.assets:
            if a.owner_gene not in genes:
                continue
            if a.type is AssetType.MODEL:
                models.append(
                    {
                        "id": a.id,
                        "label": a.label,
                        "repository_id": repository_id(a.label, str(a.source.url)),
                        "owner_gene": a.owner_gene,
                        "url": str(a.source.url),
                    }
                )
            elif a.type is AssetType.OUTCOME_MEASURE:
                pmid = next(
                    iter(re.findall(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", str(a.source.url))), None
                )
                measures.append(
                    {"id": a.id, "label": a.label, "pmid": pmid, "owner_gene": a.owner_gene}
                )
        users: dict[str, set[str]] = {}
        for a in seed.assets:
            if a.owner_gene in genes:
                users.setdefault(str(a.source.url), set()).update(
                    lines_of_gene[a.owner_gene] if a.scope is Scope.GENE else [a.owner_line]
                )
        shared = sum(1 for keys in users.values() if len(keys) >= 2)
        shared += sum(1 for s in active + finished + stopped if len(s.lines) >= 2)
        out.append(
            MechanismView(
                key=g.key,
                label=g.label,
                lines=list(g.line_keys),
                genes=genes,
                organisations=org_rows,
                studies={"active": active, "finished_or_unknown": finished, "stopped": stopped},
                models=models,
                outcome_measures=measures,
                institutions=shared_inst,
                shared_assets=shared,
                funding_projects=sum(1 for f in funding if f["gene"] in genes),
            )
        )
    return sorted(out, key=lambda v: (-v.shared_assets, v.key))


# --- Assembly --------------------------------------------------------------------------------


def build_graph() -> GraphFile:
    seed, problems = load_seed()
    if problems:
        raise SystemExit("build: fix the seed first (make validate)")
    claims = load_accepted_claims(CLAIMS_CACHE)
    ctgov = yaml.safe_load(CTGOV_CACHE.read_text()) or {}
    records = {s["nct"]: s for s in ctgov.get("studies", [])}
    co = [CoListingEdge.model_validate(row) for row in ctgov.get("co_listed_in", [])]
    papers = [Paper.model_validate(p) for p in load_yaml(PAPERS_CACHE, "papers")]
    symptoms = [SymptomRow.model_validate(s) for s in load_yaml(SYMPTOMS_CACHE, "symptoms")]
    sources_doc = yaml.safe_load(SOURCES_CACHE.read_text()) if SOURCES_CACHE.exists() else None
    if not sources_doc:
        raise FileNotFoundError("pipeline/cache/sources.yaml is missing: run make caches")
    sources = [DataSource.model_validate(s) for s in sources_doc["sources"]]
    esearch = sources_doc.get("esearch_term")

    # Paper nodes: every PMID a claim or a seed source cites, plus the fetched asset papers.
    cited = {c.pmid for c in claims}
    for line in seed.lines:
        cited |= {p for s in line.sources for p in re.findall(r"PMID (\d+)", s.label)}
        cited |= {t.pmid for t in line.hpo_terms}
    for a in seed.assets:
        cited |= set(re.findall(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", str(a.source.url)))
    for conflict in seed.conflicts:
        cited |= {p for s in conflict.sides for p in re.findall(r"PMID (\d+)", s.source.label)}
    by_pmid = {p.pmid: p for p in papers}
    missing = sorted(cited - set(by_pmid))
    if missing:
        raise SystemExit(f"build: no paper row for PMID {', '.join(missing)} (make caches)")
    paper_nodes = sorted((by_pmid[p] for p in cited), key=lambda p: p.pmid)

    studies = study_nodes(seed, records)
    stopped = tried_before(seed, studies, co)
    cards = build_cards(seed, claims, co, stopped)
    committed = load_texts()
    texts = texts_for(cards, seed, claims, committed)
    aliases = emitted_aliases(seed, claims) + symptom_aliases(seed, symptoms)
    edges = edges_for(seed, claims, co, cards, by_pmid)
    conflicts = [
        c for c in seed.conflicts if c.gene in {line.gene for line in seed.lines}
    ]  # conflicts for unseeded genes wait for their lines
    built = max(
        [s.retrieved for s in sources]
        + [e.retrieved for e in co]
        + [p.retrieved for p in paper_nodes]
    )
    run_dates = [t.provenance.run_at.date() for t in texts.values() if t.provenance is not None]
    pre_computed = max([built] + run_dates)
    n_codex = sum(t.source == "codex" for t in texts.values())
    counts = Counts(
        lines=len(seed.lines),
        genes=len({line.gene for line in seed.lines}),
        organisations=len(seed.organisations),
        studies=len(seed.studies),
        assets=len(seed.assets),
        papers=len(paper_nodes),
        claims=len(claims),
        conflicts=len(conflicts),
        aliases=len(aliases),
        co_listings=len(co),
        transfers=sum(len(c["transfers"]) for c in cards.values()),
        edges=len(edges),
        texts_codex=n_codex,
        texts_template=len(texts) - n_codex,
    )
    funding = funding_rows(load_funding(), sorted({line.gene for line in seed.lines}))
    groups = cluster_groups(seed)
    meta = Meta(
        built=built,
        pre_computed=pre_computed,
        counts=counts,
        sources=sources,
        esearch_term=esearch,
        cluster_groups=groups,
        footer=FOOTER.format(date=pre_computed.isoformat()),
        about_notice=ABOUT_NOTICE.format(date=pre_computed.isoformat()),
        consistency_check=consistency_check(seed, claims),
        how_it_grows=how_it_grows(seed, records),
    )
    return GraphFile(
        meta=meta,
        lines=line_nodes(seed, claims, papers, esearch),
        organisations=[
            OrganisationNode(
                key=o.key,
                name=o.name,
                lines=list(o.lines),
                url=str(o.url),
                contact_page=str(o.contact_page) if o.contact_page else None,
                last_verified=o.last_verified,
            )
            for o in seed.organisations
        ],
        studies=studies,
        assets=asset_nodes(seed),
        papers=paper_nodes,
        claims=claims,
        conflicts=conflicts,
        aliases=aliases,
        co_listings=co,
        transfers={k: Card.model_validate(c) for k, c in cards.items()},
        texts=texts,
        edges=edges,
        tried_before=stopped,
        mechanism_view=mechanism_view(seed, groups, studies, funding, co, records),
        funding=[FundingRow.model_validate(f) for f in funding],
    )


def render(graph: GraphFile) -> str:
    """Canonical JSON: sorted keys, one-space indent, no timestamps. Byte-reproducible."""
    return json.dumps(dump(graph), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def render_schema() -> str:
    return json.dumps(GraphFile.model_json_schema(), indent=1, sort_keys=True) + "\n"


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def graph_is_current() -> list[str]:
    """Names of the built files that differ from a fresh render (empty = current)."""
    stale = []
    for path, text in ((GRAPH_FILE, render(build_graph())), (SCHEMA_FILE, render_schema())):
        if not path.exists() or path.read_text() != text:
            stale.append(path.name)
    return stale


def main() -> int:
    graph = build_graph()
    write_atomic(GRAPH_FILE, render(graph))
    write_atomic(SCHEMA_FILE, render_schema())
    c = graph.meta.counts
    print(
        f"build: {c.lines} lines, {c.organisations} organisations, {c.studies} studies,"
        f" {c.assets} assets, {c.papers} papers, {c.claims} claims, {c.aliases} aliases,"
        f" {c.co_listings} co-listings, {c.transfers} transfers, {c.edges} edges,"
        f" texts: {c.texts_codex} codex + {c.texts_template} template"
        f" -> {GRAPH_FILE.relative_to(REPO)} (meta.source: real, built {graph.meta.built},"
        f" pre-computed {graph.meta.pre_computed})"
    )
    print(f"build: schema -> {SCHEMA_FILE.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

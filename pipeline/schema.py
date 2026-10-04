"""The one schema contract both lanes read.

Every model forbids unknown keys, so a typo in seed YAML or a stray field in
model output is an error, never silently ignored. Entity keys are direction keys
(``scn2a_loss``); database IDs are cross-references, never primary keys.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    computed_field,
    model_validator,
)

GENE_KEY = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
GENE_SYMBOL = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9-]{1,14}$")]
PMID = Annotated[str, Field(pattern=r"^[0-9]{1,9}$")]
NCT_ID = Annotated[str, Field(pattern=r"^NCT[0-9]{8}$")]
SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
# Plain text for labels and cache strings: no markup, no links.
MARKUP_OR_LINK = re.compile(r"<[A-Za-z/]|https?://|www\.", re.I)


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}")


def plain_text(value: str) -> str:
    if MARKUP_OR_LINK.search(value) or EMAIL.search(value):
        raise ValueError("markup, link or e-mail in a plain-text field")
    return value


SHORT_TEXT = Annotated[str, Field(max_length=300), AfterValidator(plain_text)]
PLAIN_LABEL = Annotated[str, Field(min_length=1, max_length=200), AfterValidator(plain_text)]


class Strict(BaseModel):
    """Base for every model: unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# --- Enumerations ------------------------------------------------------------


class Direction(StrEnum):
    """Effect of a variant on its gene product. The only direction enum in the repo."""

    GAIN = "gain"
    LOSS = "loss"
    MIXED = "mixed"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class MechanismFamily(StrEnum):
    """Direction logic runs only for ``ION_CHANNEL`` lines."""

    ION_CHANNEL = "ion_channel"
    NON_CHANNEL = "non_channel"


# Genes whose lines may carry a direction. Hand-set from cited lab studies.
CHANNEL_GENES: frozenset[str] = frozenset({"SCN1A", "SCN2A", "SCN8A", "KCNQ2"})
# Mechanism code -> family. A line's family must agree with its mechanism.
MECHANISM_FAMILY: dict[str, MechanismFamily] = {
    "sodium_channel": MechanismFamily.ION_CHANNEL,
    "potassium_channel": MechanismFamily.ION_CHANNEL,
    "synaptic_protein": MechanismFamily.NON_CHANNEL,
    "kinase": MechanismFamily.NON_CHANNEL,
    "ras_gap": MechanismFamily.NON_CHANNEL,
}
XREF_PATTERNS: dict[str, str] = {
    "hgnc": r"^HGNC:\d+$",
    "omim": r"^OMIM:\d{6}$",
    "orpha": r"^ORPHA:\d+$",
    "orpha_group": r"^ORPHA:\d+$",  # an Orphanet entry that covers several genes
    "mondo": r"^MONDO:\d{7}$",
    "g2p": r"^G2P\d{5}$",
}


class ClaimLevel(StrEnum):
    VARIANT = "variant"
    GENE = "gene"


class Stance(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    UNCLEAR = "unclear"


class Basis(StrEnum):
    """Only ``FUNCTIONAL_ASSAY`` claims may confirm a line's direction (checked by code)."""

    FUNCTIONAL_ASSAY = "functional-assay"
    CLINICAL_INFERENCE = "clinical-inference"
    REVIEW = "review"


class Scope(StrEnum):
    """``GENE`` assets serve every line of a gene and are never a borrow between them."""

    GENE = "gene"
    LINE = "line"


class Station(StrEnum):
    """The seven things a community needs before a treatment is possible."""

    DIAGNOSIS = "diagnosis"
    REGISTRY = "registry"
    NATURAL_HISTORY = "natural_history"
    MECHANISM = "mechanism"
    MODEL = "model"
    OUTCOME_MEASURE = "outcome_measure"
    TRIAL = "trial"


class AssetType(StrEnum):
    REGISTRY = "registry"
    NATURAL_HISTORY = "natural_history"
    MODEL = "model"
    OUTCOME_MEASURE = "outcome_measure"
    TRIAL = "trial"
    BIOBANK = "biobank"
    CARE_NETWORK = "care_network"
    SCREENING = "screening"
    DRUG = "drug"


# Asset types the transfer gate decides by direction. Never gene-scoped for a channel gene.
DIRECTION_GATED_TYPES = frozenset({AssetType.MODEL, AssetType.TRIAL, AssetType.DRUG})


class DirectionBasis(StrEnum):
    """How an asset's direction was established."""

    STATED_IN_RECORD = "stated_in_record"  # the record names the direction
    ONSET_PROXY = "onset_proxy"  # enrols by age of onset: a clinical proxy, shown as inferred
    FUNCTIONAL_ASSAY = "functional_assay"  # the allele was tested in a lab


class KnowledgeLevel(StrEnum):
    """Biolink ``knowledge_level`` values: observed versus inferred."""

    KNOWLEDGE_ASSERTION = "knowledge_assertion"
    STATISTICAL_ASSOCIATION = "statistical_association"
    PREDICTION = "prediction"
    OBSERVATION = "observation"
    NOT_PROVIDED = "not_provided"


class AgentType(StrEnum):
    """Biolink ``agent_type`` values: who asserted the edge."""

    MANUAL_AGENT = "manual_agent"
    AUTOMATED_AGENT = "automated_agent"
    TEXT_MINING_AGENT = "text_mining_agent"
    MANUAL_VALIDATION_OF_AUTOMATED_AGENT = "manual_validation_of_automated_agent"
    NOT_PROVIDED = "not_provided"


class Extractor(StrEnum):
    """Models allowed to propose claims. Humans sign; they never appear here."""

    CODEX = "codex"
    GPT_OSS_20B = "gpt-oss-20b"


# --- URLs ----------------------------------------------------------------------

# Hosts a URL may point to: the safety set, the seed organisation domains, and three
# hosts added for the seed. Everything is
# https and built from IDs; user-typed text never enters a URL.
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "pubmed.ncbi.nlm.nih.gov",
        "pmc.ncbi.nlm.nih.gov",
        "clinicaltrials.gov",
        "www.orpha.net",
        "hpo.jax.org",
        "monarchinitiative.org",
        "zenodo.org",
        "doi.org",
        "www.uniprot.org",
        "www.findmice.org",
        "www.mmrrc.org",
        "www.jax.org",
        "www.scn2a.org",
        "curesyngap1.org",
        "bridgesyngap.org",
        "www.ebi.ac.uk",
        "www.citizen.health",
        "globalgenes.org",
        "rarediseases.org",  # NORD directory link on the "Not mapped yet" state
        # Seed organisation domains and registries of the A7 lines (Safety set: seed organisation
        # domains are allowed; the registry sites are linked, never fetched).
        "scn8aalliance.org",
        "thecutesyndrome.com",
        "scn8a.net",
        "dravetfoundation.org",
        "dravet.eu",
        "www.stxbp1disorders.org",
        "www.louloufoundation.org",
        "cdkl5.com",
        "reporter.nih.gov",  # NIH RePORTER project pages (funding evidence, Level 2)
    }
)
# Query strings are refused except these exact shapes.
ALLOWED_QUERIES: dict[str, str] = {"www.mmrrc.org": r"^mmrrc_id=\d+$"}
HPO_ANNOTATION_LABEL = "Polaris annotation using HPO terms (not an official HPO annotation)"


def check_url(url: HttpUrl) -> None:
    """https, allow-listed host, no userinfo, no port, no fragment, no free-text query."""
    if url.scheme != "https" or url.host not in ALLOWED_HOSTS:
        raise ValueError(f"host not allow-listed: {url.host}")
    if url.username or url.password or url.port not in (None, 443) or url.fragment:
        raise ValueError("URL must not carry userinfo, a port or a fragment")
    if url.query and not re.fullmatch(ALLOWED_QUERIES.get(url.host, "$^"), url.query):
        raise ValueError(f"query string not allowed on {url.host}")


# --- Evidence ----------------------------------------------------------------


class Source(Strict):
    """Where a fact came from and when we looked.

    ``retrieved`` is None for a page the pipeline has not fetched and a person has not
    opened yet; the site then says "not yet verified".
    """

    label: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    retrieved: date | None = None

    @model_validator(mode="after")
    def url_is_safe_and_matches_label(self) -> Source:
        check_url(self.url)
        segments = set((self.url.path or "").split("/"))
        for pattern in (r"PMID (\d{1,9})\b", r"\b(NCT\d{8})\b"):
            m = re.search(pattern, self.label)
            if m and m.group(1) not in segments:
                raise ValueError(f"label cites {m.group(1)} but the URL path does not")
        return self


class ExtractedClaim(Strict):
    """One row the extraction model proposes. Mirrors ``prompts/extract_claims.schema.json``.

    There are no sign-off fields here on purpose: signing happens in
    ``seed/verifications.yaml``, which no model ever writes.
    """

    pmid: PMID
    gene: GENE_SYMBOL
    claim_level: ClaimLevel
    variant: str | None = Field(default=None, min_length=1, max_length=40)
    direction: Direction
    stance: Stance
    basis: Basis
    evidence_quote: str = Field(min_length=20, max_length=300)

    @model_validator(mode="after")
    def variant_matches_level(self) -> ExtractedClaim:
        if self.claim_level is ClaimLevel.VARIANT and not self.variant:
            raise ValueError("variant-level claims need a variant")
        if self.claim_level is ClaimLevel.GENE and self.variant:
            raise ValueError("gene-level claims must not name a variant")
        return self


class Provenance(Strict):
    """Which model run produced a batch of claims. Never a request URL."""

    agent: Extractor
    model: str = Field(min_length=1, max_length=80)
    tool_version: str = Field(min_length=1, max_length=40)
    run_at: datetime
    prompt_sha256: SHA256
    input_manifest_sha256: SHA256
    extractor_run_id: str = Field(min_length=1, max_length=80)
    step: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    output_sha256: SHA256  # canonical JSON of the model's answer, written by codex_run.sh


class ExtractionBatch(Strict):
    """One ``codex_run.sh`` extraction batch as committed in ``claims_extracted.yaml``.

    Strict on purpose: a row or key that did not come through the schema is rejected
    with its whole batch, and ``output_sha256`` ties the rows to the model's answer.
    """

    provenance: Provenance
    pmids: list[PMID] = Field(min_length=1)
    abstract_sha256s: dict[PMID, SHA256]  # the stubs the batch was built from
    claims: list[ExtractedClaim]


class RejectedBatch(Strict):
    """A batch the run script refused (tool use, schema failure). Kept for the funnel."""

    pmids: list[PMID] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=300)


# --- Graph nodes -------------------------------------------------------------


class HpoAnnotation(Strict):
    """A hand-curated symptom term for a line that has no official HPO profile.

    The cited abstract must name the symptom; ``seed_check`` compares the label with hp.obo.
    """

    id: str = Field(pattern=r"^HP:[0-9]{7}$")
    label: str = Field(min_length=1, max_length=120)
    pmid: PMID
    annotation: Literal[HPO_ANNOTATION_LABEL] = HPO_ANNOTATION_LABEL


class Line(Strict):
    """A disease line: one gene in one mechanism direction.

    The five fields the screen reads are frozen here:
    ``key, gene, mechanism, mechanism_family, direction``.
    """

    key: GENE_KEY
    gene: GENE_SYMBOL
    mechanism: str = Field(pattern=r"^[a-z][a-z_]*$", max_length=40)
    mechanism_family: MechanismFamily
    direction: Direction
    label: Annotated[str, Field(min_length=1, max_length=120), AfterValidator(plain_text)]
    gloss: Annotated[str, Field(min_length=1, max_length=200), AfterValidator(plain_text)]
    mechanism_label: str | None = Field(default=None, max_length=200)
    xrefs: dict[str, str] = Field(default_factory=dict)
    sources: list[Source] = Field(min_length=1)
    hpo_terms: list[HpoAnnotation] = Field(default_factory=list)
    organisations: list[GENE_KEY] = Field(default_factory=list)
    # True when the gene's direction covers more than one disease (SCN1A loss: Dravet and
    # GEFS+): only variants the line's own sources tie to this disease get an alias; the other
    # code-checked variants of that direction lead to the direction step with their direction.
    variant_aliases_from_sources_only: bool = False

    @model_validator(mode="after")
    def family_matches_gene_and_direction(self) -> Line:
        is_channel = self.gene in CHANNEL_GENES
        if is_channel != (self.mechanism_family is MechanismFamily.ION_CHANNEL):
            raise ValueError(f"{self.gene}: mechanism_family does not match CHANNEL_GENES")
        if MECHANISM_FAMILY.get(self.mechanism) is not self.mechanism_family:
            raise ValueError(f"mechanism {self.mechanism!r} is not in {self.mechanism_family}")
        if is_channel and self.direction is Direction.NOT_APPLICABLE:
            raise ValueError("channel lines carry a direction (unknown if unsourced)")
        if not is_channel and self.direction is not Direction.NOT_APPLICABLE:
            raise ValueError("direction logic applies only to ion-channel lines")
        if not is_channel and not self.mechanism_label:
            raise ValueError("non-channel lines carry a mechanism_label")
        for key, value in self.xrefs.items():
            if key not in XREF_PATTERNS or not re.fullmatch(XREF_PATTERNS[key], value):
                raise ValueError(f"xref {key}={value!r} is not a known id shape")
        return self


class Organisation(Strict):
    """A patient organisation. Contact = its own pages, never a named person."""

    key: GENE_KEY
    name: str = Field(min_length=1, max_length=120)
    lines: list[GENE_KEY] = Field(min_length=1)
    url: HttpUrl
    contact_page: HttpUrl | None = None
    note: str | None = Field(default=None, max_length=300)
    last_verified: date | None = None

    @model_validator(mode="after")
    def urls_are_safe(self) -> Organisation:
        for url in (self.url, self.contact_page):
            if url is not None:
                check_url(url)
        return self


class StudyKind(StrEnum):
    REGISTRY = "registry"
    ELIGIBLE_GENE_LIST = "eligible_gene_list"
    NATURAL_HISTORY = "natural_history"
    TRIAL = "trial"
    BIOREPOSITORY = "biorepository"


class Study(Strict):
    """A ClinicalTrials.gov record we cite. Status and dates come from the fetched record
    at build time, never from this seed. ``note`` is for curators and is never emitted."""

    nct: NCT_ID
    name: str = Field(min_length=1, max_length=160)
    kind: StudyKind
    genes_named: list[GENE_SYMBOL] = Field(min_length=1)
    note: str | None = Field(default=None, max_length=300)
    source: Source
    last_verified: date | None = None


class AliasKind(StrEnum):
    DISEASE = "disease"
    GENE = "gene"
    VARIANT = "variant"
    ORGANISATION = "organisation"
    MECHANISM = "mechanism"
    ID = "id"
    GROUP = "group"  # a code or name that covers several genes: the user picks the gene
    SYMPTOM = "symptom"  # an HPO term; derived at build time, never hand-typed


class Alias(Strict):
    """One search term and where it leads.

    A term leads to exactly one of: a line, a direction step (one channel gene; the user
    picks gain or loss), a gene picker (an Orphanet entry covering several genes: the
    picker lists the seeded genes and always offers "my child's gene isn't listed"), or a
    mechanism. Gene names and IDs of direction-split genes always lead to the direction
    step, never to a line. A variant alias names its gene and the PMID of the claim that
    justifies its line; the build emits it only when a code-checked functional-assay claim
    of that PMID, gene, variant and direction exists (no person signs claims for this
    submission). A variant whose assays disagree carries ``variant_direction: mixed`` and
    leads to the "Sources disagree" state, never to a line. A symptom term shared by
    several seeded genes lists them in ``genes`` and opens the gene picker, so a symptom
    never routes a family to one direction line.
    """

    term: str = Field(min_length=1, max_length=120)
    kind: AliasKind
    line: GENE_KEY | None = None
    gene: GENE_SYMBOL | None = None
    direction_step: bool = False
    genes: list[GENE_SYMBOL] = Field(default_factory=list)
    orpha: str | None = Field(default=None, pattern=r"^ORPHA:\d+$")  # GROUP: the entry
    group_size: int | None = Field(default=None, ge=2)  # GROUP: disease-causing genes in it
    mechanism: str | None = Field(default=None, pattern=r"^[a-z][a-z_]*$")
    direction: Direction | None = None
    pmid: PMID | None = None
    hpo_id: str | None = Field(default=None, pattern=r"^HP:[0-9]{7}$")  # SYMPTOM: the term
    note: str | None = Field(default=None, max_length=200)  # SYMPTOM: where the term comes from
    # VARIANT without a line: mixed = "Sources disagree"; gain/loss = the direction is code-checked
    # but no line of that form is shipped ("This form isn't mapped yet", gated)
    variant_direction: Direction | None = None

    @model_validator(mode="after")
    def one_target(self) -> Alias:
        mixed = self.variant_direction is not None and self.line is None
        targets = (
            sum(x is not None for x in (self.line, self.mechanism))
            + self.direction_step
            + bool(self.genes)
            + mixed
        )
        if targets != 1:
            raise ValueError(f"alias {self.term!r} must lead to exactly one target")
        if self.direction_step and self.gene not in CHANNEL_GENES:
            raise ValueError(f"alias {self.term!r}: a direction step needs a channel gene")
        if self.genes and self.kind not in (AliasKind.GROUP, AliasKind.SYMPTOM):
            raise ValueError(f"alias {self.term!r}: only group and symptom aliases list genes")
        if self.kind is AliasKind.GROUP and not self.genes:
            raise ValueError(f"alias {self.term!r}: group aliases list genes")
        if self.kind is AliasKind.SYMPTOM and len(self.genes) == 1:
            raise ValueError(f"alias {self.term!r}: a symptom of one gene uses gene, not genes")
        if (self.kind is AliasKind.GROUP) != (
            self.orpha is not None and self.group_size is not None
        ):
            raise ValueError(f"alias {self.term!r}: group aliases carry orpha and group_size")
        if self.group_size is not None and len(self.genes) >= self.group_size:
            raise ValueError(f"alias {self.term!r}: a group lists fewer seeded genes than its size")
        if self.variant_direction is not None and (
            self.kind is not AliasKind.VARIANT
            or self.line is not None
            or self.variant_direction not in (Direction.GAIN, Direction.LOSS, Direction.MIXED)
        ):
            raise ValueError(
                f"alias {self.term!r}: variant_direction only on a variant with no line"
            )
        if self.kind is AliasKind.VARIANT and not (
            self.pmid and self.gene and (self.line or mixed)
        ):
            raise ValueError(f"alias {self.term!r}: a variant alias needs gene, pmid and a line")
        if (self.kind is AliasKind.SYMPTOM) != (self.hpo_id is not None):
            raise ValueError(f"alias {self.term!r}: symptom aliases carry hpo_id, others do not")
        if self.direction is not None:
            channel = MECHANISM_FAMILY.get(self.mechanism or "") is MechanismFamily.ION_CHANNEL
            if not channel or self.direction not in (Direction.GAIN, Direction.LOSS):
                raise ValueError(f"alias {self.term!r}: only a channel mechanism takes gain/loss")
        return self


class ConflictSide(Strict):
    says: str = Field(min_length=1, max_length=200)
    source: Source


class Conflict(Strict):
    """Two sources that disagree about a direction or mechanism. Both are shown."""

    id: GENE_KEY
    gene: GENE_SYMBOL
    variant: str | None = Field(default=None, max_length=40)
    line: GENE_KEY | None = None
    sides: list[ConflictSide] = Field(min_length=2)
    note: str | None = Field(default=None, max_length=300)


class Asset(Strict):
    """Something a community built: a registry, a model, an outcome measure.

    Drugs, trials and models of a channel gene belong to one direction line and say how
    that direction was established; they never get gene scope, so the transfer gate
    always sees them. ``note`` is for curators and is never emitted.
    """

    id: GENE_KEY
    type: AssetType
    station: Station
    scope: Scope
    label: PLAIN_LABEL
    owner_gene: GENE_SYMBOL
    owner_line: GENE_KEY | None = None
    direction: Direction = Direction.NOT_APPLICABLE
    direction_basis: DirectionBasis | None = None
    open_to_all: bool = False  # a platform any rare-disease group can join: never a borrow
    note: str | None = Field(default=None, max_length=300)
    source: Source
    last_verified: date | None = None

    @model_validator(mode="after")
    def scope_and_direction_are_consistent(self) -> Asset:
        if self.scope is Scope.LINE and not self.owner_line:
            raise ValueError("line-scope assets need owner_line")
        if self.scope is Scope.GENE and self.owner_line:
            raise ValueError("gene-scope assets have no owner_line")
        channel = self.owner_gene in CHANNEL_GENES
        if channel and self.type in DIRECTION_GATED_TYPES:
            if self.scope is not Scope.LINE or self.direction is Direction.NOT_APPLICABLE:
                raise ValueError("channel-gene drugs, trials and models need a line and direction")
            if self.direction is not Direction.UNKNOWN and self.direction_basis is None:
                raise ValueError("a known direction needs a direction_basis")
        if not channel and (self.direction is not Direction.NOT_APPLICABLE or self.direction_basis):
            raise ValueError("direction applies only to channel-gene assets")
        return self


# --- Committed caches (allow-listed fields only) --------------------------------


class Intervention(Strict):
    type: SHORT_TEXT
    name: SHORT_TEXT


class Location(Strict):
    facility: SHORT_TEXT | None = None
    city: SHORT_TEXT | None = None
    country: SHORT_TEXT | None = None


class StudyRecord(Strict):
    """A ClinicalTrials.gov record stripped to the strip-list (``pipeline/check_public.py``).

    Never holds eligibility text, contacts, officials or descriptions. ``human_check``
    lists fields whose value looks like a person's name or title.
    """

    nct: NCT_ID
    brief_title: SHORT_TEXT
    overall_status: str = Field(max_length=40)
    start_date: str | None = Field(default=None, max_length=10)
    last_update_date: str | None = Field(default=None, max_length=10)
    why_stopped: SHORT_TEXT | None = None
    conditions: list[SHORT_TEXT] = Field(default_factory=list)
    keywords: list[SHORT_TEXT] = Field(default_factory=list)
    interventions: list[Intervention] = Field(default_factory=list)
    phases: list[SHORT_TEXT] = Field(default_factory=list)
    enrollment_count: int | None = None
    enrollment_type: str | None = Field(default=None, max_length=20)
    minimum_age: str | None = Field(default=None, max_length=20)
    maximum_age: str | None = Field(default=None, max_length=20)
    std_ages: list[str] = Field(default_factory=list)  # CHILD | ADULT | OLDER_ADULT
    study_population: SHORT_TEXT | None = None  # the record's own words, shown in quotes
    outcome_measures: list[SHORT_TEXT] = Field(default_factory=list)
    lead_sponsor: SHORT_TEXT | None = None
    locations: list[Location] = Field(default_factory=list)
    retrieved: date
    human_check: list[str] = Field(default_factory=list)


class MatchedField(StrEnum):
    CONDITIONS = "conditions"
    KEYWORDS = "keywords"
    ELIGIBILITY_INCLUSION = "eligibility_inclusion"


class CoListing(Strict):
    """A line named in a study record: the ``co_listed_in`` edge, line -> study.

    Listing is not enrolment and not similarity; the copy on screen says so. An edge that
    rests on eligibility text alone is weaker and is flagged for a human check.
    """

    line: GENE_KEY
    gene: GENE_SYMBOL
    nct: NCT_ID
    matched_field: MatchedField
    window: str = Field(max_length=120)
    tier: int = Field(ge=1, le=3)
    human_check: bool


class Paper(Strict):
    """A paper node: the PubMed strip-list fields only (never the abstract or authors)."""

    pmid: PMID
    title: SHORT_TEXT
    journal: SHORT_TEXT | None = None
    year: int | None = Field(default=None, ge=1900, le=2100)
    doi: str | None = Field(default=None, max_length=100)
    genes_mentioned: list[GENE_SYMBOL] = Field(default_factory=list)
    retrieved: date


class SymptomRow(Strict):
    """One HPO term linked to a seeded gene through phenotype.hpoa (official annotations of
    the gene's diseases, counted across them)."""

    hpo_id: str = Field(pattern=r"^HP:[0-9]{7}$")
    label: PLAIN_LABEL
    gene: GENE_SYMBOL
    diseases: int = Field(ge=1)
    retrieved: date


class AcceptedClaim(ExtractedClaim):
    """A validator-accepted claim as committed for the site: the row plus its id and run."""

    claim_id: str = Field(min_length=1, max_length=160)
    extractor_run_id: str = Field(min_length=1, max_length=80)
    agent: Extractor
    model: str = Field(min_length=1, max_length=80)
    flags: list[str] = Field(default_factory=list)


# --- Transfers -----------------------------------------------------------------


class TransferStatus(StrEnum):
    VIABLE = "viable"  # "Borrow"
    NEEDS_EXPERT_CHECK = "needs_expert_check"
    NOT_SHARED = "not_shared"
    ALREADY_OPEN = "already_open"


class Transfer(Strict):
    """One asset judged for one target line, with the reason in facts."""

    target: GENE_KEY
    asset_id: GENE_KEY
    asset_type: AssetType
    station: Station
    owner_gene: GENE_SYMBOL
    owner_line: GENE_KEY | None
    status: TransferStatus
    crosses_gene: bool
    crosses_direction: bool
    fills_missing_station: bool
    evidence_level: str = Field(max_length=40)  # "checked by code" | "checked by a person" | ""
    cited_pmid: PMID | None = None
    reason: str = Field(max_length=400)
    check_first: list[str] = Field(default_factory=list)
    evidence_claim_ids: list[str] = Field(default_factory=list)
    rank: int = Field(ge=1)
    blocked: bool = False  # the look-alike with the opposite direction, and only that
    banner: str | None = Field(default=None, max_length=400)  # the block banner, once per line
    basis_note: str | None = Field(default=None, max_length=200)
    owner_org: str | None = Field(default=None, max_length=160)
    # the other genes whose communities use the same resource page (a shared registry)
    co_owner_genes: list[GENE_SYMBOL] = Field(default_factory=list)
    nct: NCT_ID | None = None
    study_status: str | None = Field(default=None, max_length=40)
    start_date: str | None = Field(default=None, max_length=10)
    last_update_date: str | None = Field(default=None, max_length=10)
    direction_basis: DirectionBasis | None = None
    what_differs: list[str] = Field(default_factory=list)
    source_pmid: PMID | None = None  # the paper an asset rests on, when it has no study record
    open_to_all: bool = False  # a platform any rare-disease group can join
    std_ages: list[str] = Field(default_factory=list)  # from the study record
    study_population: str | None = Field(default=None, max_length=300)  # verbatim, in quotes


class Edge(Strict):
    """A typed, sourced relationship. Every edge explains itself."""

    subject: str = Field(min_length=1, max_length=80)
    predicate: str = Field(pattern=r"^[a-z][a-z_]*$")
    object: str = Field(min_length=1, max_length=80)
    source: Source
    tier: int = Field(ge=1, le=3)
    knowledge_level: KnowledgeLevel
    agent_type: AgentType
    direction_qualifier: Direction | None = None
    note: str | None = Field(default=None, max_length=400)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def retrieved(self) -> date | None:
        return self.source.retrieved

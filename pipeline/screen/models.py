"""The ``screen.json`` contract. Strict: unknown keys, free-text links and long strings fail.

Every value is computed from committed caches and the post-checked Codex answer; the UI
renders it and adds nothing. The fixed copy in ``meta`` is the plan's wording, so the file
labels itself wherever it is opened.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from pipeline.schema import (
    GENE_KEY,
    GENE_SYMBOL,
    NCT_ID,
    PLAIN_LABEL,
    PMID,
    Direction,
    Provenance,
    Strict,
    plain_text,
)
from pipeline.screen.config import DOUBT_KINDS, EVIDENCE_READ, MAX_SENTENCE_CHARS, NEXT_TESTS

CHEMBL_ID = Annotated[str, Field(pattern=r"^CHEMBL\d+$")]
SENTENCE = Annotated[
    str, Field(min_length=1, max_length=MAX_SENTENCE_CHARS), AfterValidator(plain_text)
]
FIXED_COPY = Annotated[str, Field(min_length=1, max_length=400), AfterValidator(plain_text)]
NextTest = Literal[NEXT_TESTS]  # type: ignore[valid-type]
DoubtKind = Literal[DOUBT_KINDS]  # type: ignore[valid-type]
RefusalReason = Literal[
    "line_not_in_graph",
    "evidence_not_fetched",
    "not_a_channel_line",
    "line_not_in_screen_scope",
    "direction_mixed_or_unknown",
    "direction_not_confirmed",
]
CardState = Literal["already_studied", "paper_found", "no_paper_found"]


class Study(Strict):
    """One ClinicalTrials.gov record pairing the drug and the gene (allow-listed fields)."""

    nct: NCT_ID
    status: Annotated[str, Field(max_length=40), AfterValidator(plain_text)]
    why_stopped: SENTENCE | None = None  # verbatim; None when the record has none
    why_stopped_withheld: bool = False  # True when the text looked like a person's name
    start_date: Annotated[str, Field(pattern=r"^\d{4}(-\d{2}){0,2}$")] | None = None
    last_update: Annotated[str, Field(pattern=r"^\d{4}(-\d{2}){0,2}$")] | None = None


class Evidence(Strict):
    pmids: list[PMID]  # PubMed papers naming the drug and the gene (up to a fixed cap)
    pubmed_count: int = Field(ge=0)  # the full count behind those PMIDs
    studies: list[Study]
    opentargets_pmids: list[PMID]  # mechanism references from Open Targets for the family targets


class Sentence(Strict):
    text: SENTENCE
    pmid: PMID  # always one of the card's evidence PMIDs


class Doubt(Sentence):
    kind: DoubtKind  # the fixed kind the model chose; "other" when it chose none


class Critique(Strict):
    """The post-checked model text for one card, or the reason there is none."""

    status: Literal["checked_by_code", "not_available"]
    reason: SENTENCE | None = None
    why: list[Sentence] = Field(default_factory=list)
    doubts: list[Doubt] = Field(default_factory=list)
    unchecked_reasoning: list[SENTENCE] = Field(default_factory=list)
    next_test: NextTest | None = None
    evidence_read: Literal[EVIDENCE_READ] | None = None  # type: ignore[valid-type]
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def unavailable_is_empty(self) -> Critique:
        if self.status == "not_available":
            if self.why or self.doubts or self.unchecked_reasoning or self.next_test:
                raise ValueError("a critique that is not available carries no text")
            if not self.reason:
                raise ValueError("a critique that is not available names its reason")
        elif self.provenance is None or self.evidence_read is None:
            raise ValueError("checked model text carries its provenance and what the model read")
        return self


class Card(Strict):
    drug_id: CHEMBL_ID
    name: PLAIN_LABEL
    action_type: Annotated[str, Field(max_length=60), AfterValidator(plain_text)]
    effect: Literal["reduces", "increases"]
    targets: list[GENE_SYMBOL] = Field(min_length=1)  # family targets of the kept mechanism
    target_level: Literal["protein_family"]
    on_line_gene: bool  # True when the line's own gene is among the kept mechanism's targets
    max_stage: Annotated[str, Field(max_length=40), AfterValidator(plain_text)]
    state: CardState
    evidence: Evidence
    critique: Critique


class Funnel(Strict):
    """Counts only. ``with_pair_paper`` = a PMID or NCT pairs the drug with the line's gene;
    ``with_mechanism_reference_only`` = only Open Targets' family-level mechanism references."""

    approved: int = Field(ge=0)
    family: int = Field(ge=0)
    direction_pass: int = Field(ge=0)
    with_pair_paper: int = Field(ge=0)
    with_mechanism_reference_only: int = Field(ge=0)
    without_paper: int = Field(ge=0)
    on_line_gene: int = Field(ge=0)  # passed, with the line's own gene among the kept targets

    @model_validator(mode="after")
    def parts_sum(self) -> Funnel:
        total = self.with_pair_paper + self.with_mechanism_reference_only + self.without_paper
        if total != self.direction_pass:
            raise ValueError("the paper counts partition the drugs that passed the filter")
        if not self.approved >= self.family >= self.direction_pass >= self.on_line_gene:
            raise ValueError("the funnel narrows at every step")
        return self


class RemovedByReason(Strict):
    """Counts only. The drugs behind them are never named."""

    outside_the_channel_family: int = Field(ge=0)  # approved total minus family: arithmetic
    wrong_direction: int = Field(ge=0)
    action_unclear: int = Field(ge=0)


class SanityCheck(Strict):
    """Did the screen surface drugs already tried for this gene? Over every drug that passed the
    direction filter, not only the cards shown. Not applicable when nothing passed."""

    applicable: bool
    surfaced: int = Field(ge=0)
    already_tried_total: int = Field(ge=0)


class CardsNotShownByState(Strict):
    already_studied: int = Field(ge=0)
    paper_found: int = Field(ge=0)
    no_paper_found: int = Field(ge=0)


class DirectionEvidence(Strict):
    level: Annotated[str, Field(max_length=60), AfterValidator(plain_text)]
    pmid: PMID
    variant: Annotated[str, Field(max_length=40)] | None = None


class ScreenLine(Strict):
    key: GENE_KEY
    label: PLAIN_LABEL
    gloss: PLAIN_LABEL
    gene: GENE_SYMBOL
    direction: Direction
    status: Literal["screened", "refused"]
    refusal_reason: RefusalReason | None = None
    direction_evidence: DirectionEvidence | None = None
    funnel: Funnel | None = None
    removed_by_reason: RemovedByReason | None = None
    sanity_check: SanityCheck | None = None
    new_candidates: int | None = Field(default=None, ge=0)  # passed, not already studied
    new_candidates_on_line_gene: int | None = Field(default=None, ge=0)  # of those, on the gene
    cards: list[Card] = Field(default_factory=list)
    cards_not_shown: int = Field(default=0, ge=0)  # passed the filter but beyond the card cap
    cards_not_shown_by_state: CardsNotShownByState | None = None
    cards_not_shown_reason: FIXED_COPY | None = None

    @model_validator(mode="after")
    def status_shape(self) -> ScreenLine:
        if self.status == "refused":
            if self.refusal_reason is None:
                raise ValueError("a refused line names its reason")
            if self.cards or self.funnel is not None or self.new_candidates is not None:
                raise ValueError("a refused line has no funnel and no cards")
            if self.new_candidates_on_line_gene is not None:
                raise ValueError("a refused line has no funnel and no cards")
        else:
            if self.refusal_reason is not None:
                raise ValueError("a screened line has no refusal reason")
            if (
                self.funnel is None
                or self.removed_by_reason is None
                or self.sanity_check is None
                or self.new_candidates is None
                or self.new_candidates_on_line_gene is None
                or self.cards_not_shown_by_state is None
            ):
                raise ValueError("a screened line carries funnel, removed counts and sanity check")
            if self.direction_evidence is None:
                raise ValueError("a screened line carries its direction evidence")
            if (self.cards_not_shown > 0) != (self.cards_not_shown_reason is not None):
                raise ValueError("cards not shown carry the fixed reason, and only then")
            hidden = self.cards_not_shown_by_state
            if hidden.already_studied + hidden.paper_found + hidden.no_paper_found != (
                self.cards_not_shown
            ):
                raise ValueError("the hidden-card states partition the hidden cards")
            if len(self.cards) + self.cards_not_shown != self.funnel.direction_pass:
                raise ValueError("shown and hidden cards partition the drugs that passed")
        return self


class FamilyEffects(Strict):
    """How many approved family medicines reduce, increase or have no mapped effect."""

    reduces: int = Field(ge=0)
    increases: int = Field(ge=0)
    unclear: int = Field(ge=0)


class Meta(Strict):
    source: Literal["real"]
    open_targets_release: Annotated[str, Field(pattern=r"^\d{2}\.\d{2}$")]
    retrieved: date  # Open Targets pool
    evidence_retrieved: date  # PubMed and ClinicalTrials.gov pairs
    rule_version: Annotated[str, Field(max_length=40)]
    family_label: PLAIN_LABEL
    family_genes: list[GENE_SYMBOL] = Field(min_length=1)
    target_level: Literal["protein_family"]
    target_caption: FIXED_COPY
    direction_source: Literal["graph_direction_evidence", "known_direction"]
    direction_filter_note: FIXED_COPY
    family_effects: FamilyEffects
    family_direction_note: FIXED_COPY
    approved_total_method: FIXED_COPY
    chembl_version: Annotated[str, Field(max_length=40), AfterValidator(plain_text)]
    removed_counts_note: FIXED_COPY
    sanity_check_note: FIXED_COPY
    new_candidates_note: FIXED_COPY
    family_coverage_note: FIXED_COPY
    ordering_rule: FIXED_COPY
    pubmed_query_form: PLAIN_LABEL
    pubmed_query_note: FIXED_COPY
    studies_found: int = Field(ge=0)  # ClinicalTrials.gov records over every pair, all lines
    evidence_read: Literal[EVIDENCE_READ]  # type: ignore[valid-type]
    next_test_labels: dict[NextTest, PLAIN_LABEL]
    doubt_kind_labels: dict[DoubtKind, PLAIN_LABEL]
    interstitial: FIXED_COPY
    interstitial_continue: PLAIN_LABEL
    interstitial_back: PLAIN_LABEL
    medication_warning: FIXED_COPY  # the family path's sentence, repeated above the funnel
    hypothesis_label: PLAIN_LABEL
    already_studied_caption: PLAIN_LABEL
    badge: PLAIN_LABEL
    sources: list[FIXED_COPY] = Field(min_length=1)


class Screen(Strict):
    meta: Meta
    lines: list[ScreenLine]

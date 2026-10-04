"""Template texts: fixed sentences filled from card facts, so every card always has text.

The explanation model (Codex, ``make explain``) may replace a template for the demo-path
cards; a model text that fails the post-check falls back to the template written here.
Every sentence is built from fields of a ``Transfer`` and the line labels, never from free
text, and the result is checked against the FAMILY deny-list by the tests.
"""

from __future__ import annotations

from pipeline.schema import CHANNEL_GENES, AssetType, Line, Transfer, TransferStatus

PROVENANCE_TEMPLATE = "Fixed sentence filled from the cited facts at build time; checked by code."
KIND_WORDS: dict[AssetType, str] = {
    AssetType.REGISTRY: "registry",
    AssetType.NATURAL_HISTORY: "natural-history study",
    AssetType.MODEL: "lab model",
    AssetType.OUTCOME_MEASURE: "outcome measure",
    AssetType.TRIAL: "trial",
    AssetType.BIOBANK: "biobank",
    AssetType.CARE_NETWORK: "care network",
    AssetType.SCREENING: "screening programme",
    AssetType.DRUG: "medicine",
}


def card_key(line_key: str, asset_id: str) -> str:
    return f"{line_key}:{asset_id}"


def block_key(line_key: str) -> str:
    return f"{line_key}:block"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]  # str.capitalize would lower-case gene symbols


def _article(word: str) -> str:
    return "an" if word[:1] in "aeiou" else "a"


# What a community can honestly put on the table: its families' experience, and the measures
# and natural-history data it already takes part in. Never a registry or a mouse line it does
# not own.
STATION_OFFERS: dict[str, str] = {
    "natural_history": "the natural-history data our families contribute to",
    "outcome_measure": "the outcome measures we already use",
}
OPEN_STATUSES = ("RECRUITING", "ENROLLING_BY_INVITATION", "NOT_YET_RECRUITING")
STATUS_PLAIN = {
    "ACTIVE_NOT_RECRUITING": "not recruiting now",
    "COMPLETED": "it is completed and its data exist",
    "UNKNOWN": "status not confirmed recently in the record",
}
CLOSING_STUDY = "The study team decides who can take part."
CLOSING_DESIGN = "The study team decides how its design can be reused."
CLOSING_BUILT = "The team that built it decides how it can be reused."


def owner_words(t: Transfer, lines: dict[str, Line]) -> str:
    if len(t.co_owner_genes) > 1:  # a shared resource names every community that uses it
        return f"the {', '.join(t.co_owner_genes[:-1])} and {t.co_owner_genes[-1]} communities"
    if t.owner_line and t.owner_line in lines:
        return f"the {lines[t.owner_line].label} group"
    return f"the {t.owner_gene} community"


def run_verb(status: str | None, plural: bool = False) -> str:
    """The verb for a study by its registry status: a completed study "ran"; one the record
    says is recruiting "runs" (and ``status_tail`` adds that it is open); any other registered
    study was "registered" (and ``status_tail`` says it exists, with the record's status); a
    resource with no study record is "already run" by its community."""
    if status == "COMPLETED":
        return "ran"
    if status is None:
        return "already run" if plural else "already runs"
    if status in OPEN_STATUSES:
        return "run" if plural else "runs"
    return "registered"


def status_clause(status: str | None, crosses_gene: bool = False) -> str:
    """The clause that says what the record allows today: "it is open now" only for a record
    that says RECRUITING (on another gene's card: "open now to those families", since a design
    from another gene is compared with or copied, never joined); "it exists (<status>)" for
    any other registered record; nothing for a completed study or a resource without a record."""
    if status is None or status == "COMPLETED":
        return ""
    if status == "RECRUITING":
        return "it is open now to those families" if crosses_gene else "it is open now"
    return f"it exists ({STATUS_PLAIN.get(status, status.lower().replace('_', ' '))})"


def template_text(t: Transfer, target: Line, lines: dict[str, Line]) -> str:
    """Level 0: one plain sentence about this card."""
    kind = KIND_WORDS[t.asset_type]
    a = _article(kind)
    owner = owner_words(t, lines)
    built = t.asset_type is AssetType.OUTCOME_MEASURE
    plural = len(t.co_owner_genes) > 1  # "the X, Y and Z communities" is a plural subject
    verb = ("have built" if plural else "has built") if built else run_verb(t.study_status, plural)
    use = "compare with or adapt" if built else "compare with or copy"
    if t.status is TransferStatus.VIABLE:
        if t.asset_type is AssetType.REGISTRY and plural and not t.owner_org:
            # A shared registry page used by several communities, run by its own operator.
            return (
                f"This {kind} is used by {owner}; your community could ask about it. Being"
                " listed there is decided by the team running it."
            )
        if t.owner_org and t.asset_type is AssetType.REGISTRY:
            # A shared registry run by a third party: nobody "copies" it; ask about joining it.
            return (
                f"This {kind}, run by {t.owner_org}, is used by {owner}; your community"
                " could ask about it. Being listed there is decided by the team running it."
            )
        clause = "" if built else status_clause(t.study_status, t.crosses_gene)
        if t.owner_org and t.crosses_gene:
            today = f", and {clause}" if clause else ""
            return (
                f"{t.owner_org} {run_verb(t.study_status)} {a} {kind} used by {owner}{today};"
                f" your community could {use} its design. It comes from another gene; this kind"
                " of work does not depend on how the gene goes wrong."
            )
        today = f"; {clause}" if clause else ""
        if t.crosses_gene:
            # A design from another gene is compared with or copied, never joined.
            return (
                f"{_cap(owner)} {verb} {a} {kind} your community could {use}{today}. It comes"
                " from another gene; this kind of work does not depend on how the gene goes"
                " wrong."
            )
        return f"{_cap(owner)} {verb} {a} {kind} that your community could {use}{today}."
    if t.status is TransferStatus.ALREADY_OPEN:
        if t.open_to_all:
            return (
                f"This {kind} is open to any rare-disease group, including {target.gene} families."
            )
        if t.asset_type is AssetType.MODEL:
            return f"This {kind} is held for {target.gene} research."
        if t.nct and t.asset_type is AssetType.TRIAL:
            return (
                f"This {kind} is registered for {target.gene} ({t.nct}); the study team decides"
                " who can take part."
            )
        if t.nct and t.study_status in OPEN_STATUSES:
            return f"This {kind} is already open to {target.gene} families."
        if t.nct:
            plain = STATUS_PLAIN.get(t.study_status, "status not confirmed recently in the record")
            return f"This {kind} is registered for {target.gene} families ({t.nct}); {plain}."
        if t.source_pmid:
            return f"This {kind} already exists for {target.gene} (PMID {t.source_pmid})."
        return f"This {kind} is listed for {target.gene} families."
    if t.status is TransferStatus.NEEDS_EXPERT_CHECK:
        if t.crosses_gene:
            return (
                f"This {kind} is for {t.owner_gene} only; an expert can say whether its design"
                f" matters for {target.gene} research."
            )
        return (
            f"{_cap(owner)} {'have' if plural else 'has'} {a} {kind} for the same mechanism and"
            " direction as your child's form; an expert check comes first."
        )
    if t.blocked:
        return (
            f"This {kind} belongs to {owner}, where the channel has the opposite problem, so it"
            " is not matched to your child's form."
        )
    if t.study_status in ("TERMINATED", "WITHDRAWN"):
        return f"This {kind} is stopped; the record's own words are under 'For researchers'."
    if t.study_status == "SUSPENDED":
        return f"This {kind} is paused; the record's own words are under 'For researchers'."
    if (
        t.asset_type is AssetType.MODEL
        and t.direction_basis is None
        and t.owner_gene != target.gene
        and t.owner_gene in CHANNEL_GENES
        and target.gene in CHANNEL_GENES
    ):
        return (
            f"The direction of this mouse line's own {t.owner_gene} change has not been"
            " lab-tested yet, so it is not matched."
        )
    if t.owner_gene != target.gene and (
        t.owner_gene not in CHANNEL_GENES or target.gene not in CHANNEL_GENES
    ):
        return (
            f"This {kind} from {owner} works through different biology from {target.gene},"
            " so it is not matched."
        )
    return f"This {kind} from {owner} is not matched across genes."


def offer_words(held: list[str] | None) -> str:
    """What the target community can put on the table: its families' experience, plus only
    the stations it actually holds."""
    offers = ["our families' experience"]
    offers += [STATION_OFFERS[s] for s in STATION_OFFERS if held and s in held]
    return offers[0] if len(offers) == 1 else ", ".join(offers[:-1]) + " and " + offers[-1]


def closing_for(t: Transfer) -> str:
    """The fixed last sentence of a proposal: a registered study has a team that decides who
    takes part; a measure or design built elsewhere has a team that decides on reuse."""
    if not t.nct:
        return CLOSING_BUILT
    return CLOSING_DESIGN if t.crosses_gene else CLOSING_STUDY


def template_proposal(
    t: Transfer, target: Line, lines: dict[str, Line], held: list[str] | None = None
) -> str | None:
    """A two-way proposal, only for cards a community could act on."""
    if t.status is not TransferStatus.VIABLE:
        return None
    kind = KIND_WORDS[t.asset_type]
    study = f" ({t.nct})" if t.nct else ""
    ask = (
        "Could we compare designs and copy what fits our families?"
        if t.crosses_gene
        else f"Could we compare designs, and could families with {target.gene} changes take"
        " part or run a parallel arm?"
    )
    return (
        f"To {proposal_addressee(t, lines)}: the {target.label} community is looking at your"
        f" {kind}{study}. {ask} In return we can share {offer_words(held)}. {closing_for(t)}"
    )


def proposal_addressee(t: Transfer, lines: dict[str, Line]) -> str | None:
    """Who a proposal is addressed to: the organisation running the study, else the owner group."""
    if t.status is not TransferStatus.VIABLE:
        return None
    return t.owner_org or owner_words(t, lines)


def proposal_citations(t: Transfer) -> list[str]:
    """The identifiers a proposal rests on: the study record and the direction claim."""
    out = [x for x in (t.nct, t.source_pmid) if x]
    if t.cited_pmid and t.cited_pmid not in out:
        out.append(f"PMID {t.cited_pmid}")
    return [x if x.startswith(("NCT", "PMID")) else f"PMID {x}" for x in out]

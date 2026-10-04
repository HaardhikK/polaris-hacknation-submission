"""The transfer engine: what one line can borrow, what is blocked, and why.

Rules:

* Positive gate: drugs, trials and models transfer only between lines with the same
  mechanism AND the same known direction. ``mixed`` and ``unknown`` fail the gate.
* Registries, care networks, screening, outcome measures and natural-history study
  designs transfer across genes and across directions (natural-history designs by the
  plan's own demo card; recorded in Known issues).
* A resource open to a gene (gene scope) is "already open to you" on every line of that
  gene and is never a borrow, under any other community's name.
* A block is the explained subset of gate failures: same gene or same channel family,
  opposite direction, with the cited claim. Direction logic never runs for non-channel
  lines: their drugs, trials and models are simply not matched across genes, and that is
  said in plain words, never as a block.
* A line's direction counts as known only when a code-checked functional-assay claim of
  that gene, stance "supports", unhedged, and not contradicted for its variant, agrees
  with the hand label. Evidence is cited as "checked by code".
* Ranking is rule-based: borrows first, a missing station first, same mechanism before
  cross-mechanism, then asset type and label. Phenotype similarity is a later tie-break.

Reads only committed files: the seed and ``pipeline/cache/``.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from pipeline.ctgov import STD_AGE_WORDS
from pipeline.fetch import REPO
from pipeline.schema import (
    CHANNEL_GENES,
    DIRECTION_GATED_TYPES,
    AcceptedClaim,
    Asset,
    AssetType,
    Basis,
    Direction,
    DirectionBasis,
    Line,
    MechanismFamily,
    Scope,
    Stance,
    Station,
    Transfer,
    TransferStatus,
)
from pipeline.seed_check import Seed, load_seed
from pipeline.texts import KIND_WORDS
from pipeline.validate import canonical_variant

CACHE = REPO / "pipeline" / "cache"
CLAIMS_CACHE = CACHE / "claims_accepted.yaml"
CTGOV_CACHE = CACHE / "ctgov.yaml"
TRANSFERABLE = {
    AssetType.REGISTRY,
    AssetType.CARE_NETWORK,
    AssetType.SCREENING,
    AssetType.OUTCOME_MEASURE,
    AssetType.NATURAL_HISTORY,
}
# "Check first": a fixed list per asset type, never model-written, deny-list clean.
CHECK_FIRST: dict[AssetType, list[str]] = {
    AssetType.NATURAL_HISTORY: [
        "who the study accepts and its age range",
        "which measures it uses and whether they fit your condition",
        "its data-sharing and consent terms",
    ],
    AssetType.REGISTRY: [
        "which genes and conditions the registry accepts",
        "its consent and data-sharing terms",
    ],
    AssetType.OUTCOME_MEASURE: [
        "whether the measure has been used in your condition and age range",
    ],
    AssetType.CARE_NETWORK: ["which conditions the network accepts"],
    AssetType.SCREENING: ["which genes the screening covers"],
    AssetType.TRIAL: [
        "a lab test confirming the direction of your child's variant",
        "the study's own entry rules (the study team decides who can take part)",
    ],
    AssetType.MODEL: ["that the model's allele direction matches yours (lab-tested)"],
    AssetType.DRUG: [
        "a lab test confirming the direction of your child's variant",
        "your neurologist",
    ],
}
TYPE_ORDER = [
    AssetType.NATURAL_HISTORY,
    AssetType.REGISTRY,
    AssetType.OUTCOME_MEASURE,
    AssetType.BIOBANK,
    AssetType.CARE_NETWORK,
    AssetType.SCREENING,
    AssetType.TRIAL,
    AssetType.MODEL,
    AssetType.DRUG,
]
GLOSS = {Direction.GAIN: "work too strongly", Direction.LOSS: "work too weakly"}
STOPPED_STATUSES = ("TERMINATED", "WITHDRAWN", "SUSPENDED")
# Stations whose "have" rests on a study record, so a stopped or paused record cannot hold them.
STUDY_STATIONS = (Station.REGISTRY, Station.NATURAL_HISTORY, Station.TRIAL)
KIND_STATION = {
    "registry": Station.REGISTRY.value,
    "natural_history": Station.NATURAL_HISTORY.value,
    "trial": Station.TRIAL.value,
}
STATUS_WORDS = {"TERMINATED": "stopped", "WITHDRAWN": "withdrawn", "SUSPENDED": "paused"}
OPEN_STATUSES = ("RECRUITING", "ENROLLING_BY_INVITATION", "NOT_YET_RECRUITING")
LIVE_STATUSES = OPEN_STATUSES + ("ACTIVE_NOT_RECRUITING", "COMPLETED")
STATUS_PLAIN = {
    "ACTIVE_NOT_RECRUITING": "not recruiting now",
    "COMPLETED": "it is completed and its data exist",
    "UNKNOWN": "status not confirmed recently in the record",
}


def open_words(kind: str, gene: str, status: str | None, runner: str) -> str:
    """ "Open" only when the record says it is recruiting; a trial is never called open."""
    if kind == "trial":
        plain = STATUS_PLAIN.get(status, (status or "status unknown").lower().replace("_", " "))
        return (
            f"Registered for {gene} families{runner} ({plain}); the study team decides who can"
            " take part."
        )
    if status in OPEN_STATUSES:
        return f"Open to {gene} families{runner}; the team running it decides who can take part."
    plain = STATUS_PLAIN.get(status, (status or "status unknown").lower().replace("_", " "))
    return f"Registered for {gene} families{runner} ({plain})."


EVIDENCE_LEVEL = "checked by code"
# Plain words for a station in the steps sentence ("the 2 it is missing: a lab model and a trial").
STEP_WORDS: dict[Station, str] = {
    Station.DIAGNOSIS: "a genetic test result",
    Station.REGISTRY: "a registry",
    Station.NATURAL_HISTORY: "a natural-history study",
    Station.MECHANISM: "a lab study of the mechanism",
    Station.MODEL: "a lab model",
    Station.OUTCOME_MEASURE: "an outcome measure",
    Station.TRIAL: "a trial",
}
ONSET_NOTE = (
    " That study picks children by early seizure onset, which usually means the channel"
    " works too strongly: inferred, not lab-tested."
)


# --- Committed inputs ----------------------------------------------------------


def load_accepted_claims(path: Path = CLAIMS_CACHE) -> list[AcceptedClaim]:
    if not path.exists():
        raise FileNotFoundError(f"{path.name} is missing: run make caches")
    rows = yaml.safe_load(path.read_text()) or {}
    return [AcceptedClaim.model_validate(r) for r in rows.get("claims", [])]


def load_studies(path: Path = CTGOV_CACHE) -> dict[str, dict]:
    if not path.exists():
        return {}
    doc = yaml.safe_load(path.read_text()) or {}
    return {s["nct"]: s for s in doc.get("studies", [])}


# --- Direction -------------------------------------------------------------------


def claim_usable(c: AcceptedClaim, gene: str) -> bool:
    """A claim the engine may act on: this gene, functional assay, supports, a variant, unhedged."""
    return (
        c.gene == gene
        and c.basis is Basis.FUNCTIONAL_ASSAY
        and c.stance is Stance.SUPPORTS
        and bool(c.variant)
        and not any(f.startswith("hedged") for f in c.flags)
    )


def _canon(variant: str | None) -> str:
    return canonical_variant(variant or "") or (variant or "")


def source_variants(line: Line) -> set[str]:
    """Canonical variants the line's own source labels name (e.g. "L986F")."""
    out: set[str] = set()
    for src in line.sources:
        for tok in re.findall(
            r"\b(?:p\.)?[A-Z][a-z]{2}\d+[A-Z][a-z]{2}\b|\b[A-Z]\d{2,4}[A-Z*]\b", src.label
        ):
            canon = canonical_variant(tok)
            if canon:
                out.add(canon)
    return out


def variant_on_line(line: Line, variant: str | None) -> bool:
    """Whether a variant of the line's gene may stand for this line: always, unless the line
    says only the variants its own sources tie to its disease count (dravet: SCN1A loss of
    function also covers the milder GEFS+ and PEFS+, so only L986F confirms Dravet)."""
    if not line.variant_aliases_from_sources_only:
        return True
    return _canon(variant) in source_variants(line)


def variant_verdicts(claims: list[AcceptedClaim], gene: str) -> dict[str, Direction]:
    """canonical variant -> direction from unhedged assay claims; both directions = mixed.

    A functional-assay claim with stance "contradicts" contests its variant, so that variant
    can never confirm a line on its own (the plan's recorded SCN8A R223G conflict).
    """
    seen: dict[str, set[Direction]] = defaultdict(set)
    for c in claims:
        if claim_usable(c, gene):
            seen[_canon(c.variant)].add(c.direction)
        elif (
            c.gene == gene
            and c.basis is Basis.FUNCTIONAL_ASSAY
            and c.stance is Stance.CONTRADICTS
            and c.variant
        ):
            seen[_canon(c.variant)].add(Direction.MIXED)
    out: dict[str, Direction] = {}
    for variant, directions in seen.items():
        if {Direction.GAIN, Direction.LOSS} <= directions or Direction.MIXED in directions:
            out[variant] = Direction.MIXED
        elif len(directions) == 1:
            out[variant] = next(iter(directions))
        else:
            out[variant] = Direction.UNKNOWN
    return out


def direction_support(line: Line, claims: list[AcceptedClaim]) -> list[AcceptedClaim]:
    """Claims that confirm the line's hand label, best first.

    Kept: unhedged supporting functional-assay claims of the gene whose variant resolves to
    the line's direction (a variant with conflicting assays is dropped). Ordered so the
    citation is stable: a PMID named in the line's own sources first, then PMID, then id.
    """
    verdicts = variant_verdicts(claims, line.gene)
    source_pmids = {p for s in line.sources for p in re.findall(r"PMID (\d+)", s.label)}
    support = [
        c
        for c in claims
        if claim_usable(c, line.gene)
        and c.direction is line.direction
        and verdicts.get(_canon(c.variant)) is line.direction
        and variant_on_line(line, c.variant)
    ]
    named = set()
    for src in line.sources:
        for tok in re.findall(
            r"\b(?:p\.)?[A-Z][a-z]{2}\d+[A-Z][a-z]{2}\b|\b[A-Z]\d{2,4}[A-Z*]\b", src.label
        ):
            if canonical_variant(tok):
                named.add(canonical_variant(tok))
    support.sort(
        key=lambda c: (
            _canon(c.variant) not in named,  # a variant the line's own source names first
            c.pmid not in source_pmids,
            c.pmid,
            c.claim_id,
        )
    )
    return support


def known_direction(line: Line, claims: list[AcceptedClaim]) -> Direction:
    """The direction the engine may act on: the hand label, only once a claim confirms it."""
    if line.gene not in CHANNEL_GENES:
        return Direction.NOT_APPLICABLE
    if line.direction in (Direction.GAIN, Direction.LOSS) and direction_support(line, claims):
        return line.direction
    if line.direction is Direction.MIXED:
        return Direction.MIXED
    return Direction.UNKNOWN


# --- Stations ----------------------------------------------------------------------


def own_assets(target: Line, seed: Seed) -> list[Asset]:
    return [
        a
        for a in seed.assets
        if a.owner_gene == target.gene and (a.scope is Scope.GENE or a.owner_line == target.key)
    ]


def station_map(
    target: Line, seed: Seed, claims: list[AcceptedClaim], studies: dict[str, dict] | None = None
) -> dict[str, dict]:
    """have / missing / unknown per station, with the fact behind it ("unknown ≠ missing").

    A registry, natural-history study or trial whose record is stopped or paused is not a step
    the community holds today: it does not make its station ``have`` (its row is "Tried
    before"), and the station says so (``halted``: "stopped" or "paused", else None).
    """
    studies = studies if studies is not None else {}
    own = own_assets(target, seed)
    out: dict[str, dict] = {}
    for station in Station:
        held = [a.label for a in own if a.station is station]
        halted: list[str] = []
        if station in STUDY_STATIONS:
            status_of = {a.label: study_facts(a, studies)["study_status"] for a in own}
            halted = [
                f"{label} is {STATUS_WORDS[status_of[label]]}"
                for label in held
                if status_of[label] in STOPPED_STATUSES
            ]
            held = [label for label in held if status_of[label] not in STOPPED_STATUSES]
        if station is Station.DIAGNOSIS:
            out[station.value] = {
                "state": "have",
                "why": f"a genetic test result names {target.gene}",
            }
        elif station is Station.MECHANISM:
            if target.gene not in CHANNEL_GENES:
                why = target.mechanism_label or "database label"
                out[station.value] = {"state": "have", "why": why}
            elif support := direction_support(target, claims):
                top = support[0]
                why = f"lab study of {top.variant} (PMID {top.pmid}), {EVIDENCE_LEVEL}"
                out[station.value] = {"state": "have", "why": why}
            else:
                out[station.value] = {"state": "unknown", "why": "no lab study of this form found"}
        elif held:
            out[station.value] = {"state": "have", "why": ", ".join(held)}
        elif halted:
            out[station.value] = {
                "state": "missing",
                "why": f"{'; '.join(halted)}; not counted as a step held today",
                "halted": "paused" if all(h.endswith("paused") for h in halted) else "stopped",
            }
        else:
            out[station.value] = {"state": "missing", "why": "none found yet"}
    return out


def note_stopped_studies(stations: dict[str, dict], stopped: list[dict]) -> dict[str, dict]:
    """A stopped study that names the line through a co-listing (its "Tried before" row) is
    still a study somebody found: a station that would say "none found yet" names it instead
    of claiming nothing exists. ``stopped`` rows carry ``nct``, ``name``, ``kind`` and ``state``."""
    for row in stopped:
        key = KIND_STATION.get(row.get("kind") or "")
        if not key or key not in stations or stations[key]["state"] != "missing":
            continue
        if stations[key]["why"] != "none found yet":
            continue
        label = row["name"] if row["nct"] in row["name"] else f"{row['name']} ({row['nct']})"
        is_state = "" if row["state"] in row["name"].lower() else f" is {row['state']}"
        stations[key] = {
            "state": "missing",
            "why": f"{label}{is_state}; not counted as a step held today",
            "halted": row["state"],
        }
    return stations


# --- Judging one asset -----------------------------------------------------------------


def study_facts(asset: Asset, studies: dict[str, dict]) -> dict:
    """What the committed study cache knows about the study behind an asset, if any."""
    nct = next(iter(re.findall(r"NCT\d{8}", f"{asset.label} {asset.source.url}")), None)
    study = studies.get(nct or "", {})
    pmid = next(iter(re.findall(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", str(asset.source.url))), None)
    return {
        "nct": nct,
        "source_pmid": pmid,
        "owner_org": study.get("lead_sponsor"),
        "study_status": study.get("overall_status"),
        "start_date": study.get("start_date"),
        "last_update_date": study.get("last_update_date"),
        "age_range": (study.get("minimum_age"), study.get("maximum_age")),
        "std_ages": list(study.get("std_ages") or []),
        "study_population": study.get("study_population"),
    }


def judge(
    target: Line,
    asset: Asset,
    seed: Seed,
    claims: list[AcceptedClaim],
    studies: dict[str, dict],
) -> Transfer | None:
    """One asset for one target line, or None when the row is the target's own."""
    lines = {line.key: line for line in seed.lines}
    owner_line = lines.get(asset.owner_line or "")
    same_gene = asset.owner_gene == target.gene
    if same_gene and asset.scope is Scope.LINE and asset.owner_line == target.key:
        return None
    facts = study_facts(asset, studies)
    stations = station_map(target, seed, claims, studies)
    if facts.get("study_status") in STOPPED_STATUSES and not same_gene:
        return None  # another community's stopped study is its own "Tried before", not a row here
    if facts.get("study_status") in STOPPED_STATUSES:
        # A stopped study is "Tried before" (Level 2, the sponsor's reason verbatim); it is never
        # offered as a borrow and never called open.
        word = STATUS_WORDS[facts["study_status"]]
        whose = (
            "Your community's"
            if same_gene
            else f"The {owner_line.label if owner_line else asset.owner_gene + ' community'}'s"
        )
        tail = (
            " The record says it will resume."
            if facts["study_status"] == "SUSPENDED"
            else " A stopped study is not, by itself, a result about whether a treatment works."
        )
        verdict = _not_shared(
            f"{whose} {asset.label} is {word}; the sponsor's own words are shown under"
            f" 'For researchers'.{tail}",
            [],
        )

    elif asset.open_to_all:
        verdict = {
            "status": TransferStatus.ALREADY_OPEN,
            "reason": (
                f"{asset.label}: open to any rare-disease group, including {target.gene} families."
            ),
            "crosses_direction": False,
            "blocked": False,
            "cited_pmid": None,
            "evidence": [],
            "what_differs": [],
            "banner": None,
            "basis_note": None,
        }
    elif same_gene and asset.scope is Scope.GENE:
        also = sorted(
            {a.owner_gene for a in seed.assets if a.source.url == asset.source.url} - {target.gene}
        )
        runner = f", run by {facts['owner_org']}" if facts.get("owner_org") else ""
        # "open" only when the record says so (open_words); a page listing is "listed for"
        is_open = bool(facts.get("nct")) and facts.get("study_status") in OPEN_STATUSES
        word = "open to" if is_open else "listed for"
        shared = f" Also {word} {', '.join(also)} families." if also else ""
        kind = KIND_WORDS[asset.type]
        if asset.type is AssetType.MODEL:
            reason = f"Held for {target.gene} research; for researchers.{shared}"
        elif facts.get("nct"):
            reason = open_words(kind, target.gene, facts.get("study_status"), runner) + shared
        elif facts.get("source_pmid"):
            # A paper, not a registration: the resource exists; nobody "joins" it.
            reason = (
                f"Already exists for {target.gene} (PMID {facts['source_pmid']}):"
                f" {_article(kind)} {kind} your community can build on.{shared}"
            )
        else:
            reason = (
                f"Listed for {target.gene} families on {asset.source.label}; page date not yet"
                f" checked.{shared}"
            )
        verdict = {
            "status": TransferStatus.ALREADY_OPEN,
            "reason": reason,
            "crosses_direction": False,
            "blocked": False,
            "cited_pmid": None,
            "evidence": [],
            "what_differs": [],
            "banner": None,
            "basis_note": None,
        }
    else:
        verdict = judge_borrow(target, asset, owner_line, seed, claims, facts)
    status = verdict["status"]
    return Transfer(
        target=target.key,
        asset_id=asset.id,
        asset_type=asset.type,
        station=asset.station,
        owner_gene=asset.owner_gene,
        owner_line=asset.owner_line,
        status=status,
        crosses_gene=not same_gene,
        crosses_direction=verdict["crosses_direction"],
        fills_missing_station=stations[asset.station.value]["state"] == "missing",
        evidence_level=EVIDENCE_LEVEL if verdict["evidence"] else "",
        cited_pmid=verdict["cited_pmid"],
        reason=verdict["reason"],
        check_first=(
            CHECK_FIRST.get(asset.type, [])
            if status in (TransferStatus.VIABLE, TransferStatus.NEEDS_EXPERT_CHECK)
            else []
        ),
        evidence_claim_ids=verdict["evidence"],
        rank=1,
        blocked=verdict["blocked"],
        owner_org=facts.get("owner_org"),
        co_owner_genes=sorted(
            {a.owner_gene for a in seed.assets if a.source.url == asset.source.url} - {target.gene}
        )
        if asset.scope is Scope.GENE  # a shared page; a line's own resource keeps its line label
        else [],
        nct=facts.get("nct"),
        study_status=facts.get("study_status"),
        start_date=facts.get("start_date"),
        last_update_date=facts.get("last_update_date"),
        direction_basis=asset.direction_basis,
        what_differs=verdict["what_differs"],
        banner=verdict.get("banner"),
        basis_note=verdict.get("basis_note"),
        source_pmid=facts.get("source_pmid"),
        open_to_all=asset.open_to_all,
        std_ages=facts.get("std_ages", []),
        study_population=facts.get("study_population"),
    )


def _not_shared(reason: str, differs: list[str]) -> dict:
    return {
        "status": TransferStatus.NOT_SHARED,
        "reason": reason,
        "crosses_direction": False,
        "blocked": False,
        "cited_pmid": None,
        "evidence": [],
        "what_differs": differs,
        "banner": None,
        "basis_note": None,
    }


def _article(word: str) -> str:
    return "an" if word[:1] in "aeiou" else "a"


def judge_borrow(
    target: Line,
    asset: Asset,
    owner_line: Line | None,
    seed: Seed,
    claims: list[AcceptedClaim],
    facts: dict,
) -> dict:
    target_dir = known_direction(target, claims)
    owner_channel = asset.owner_gene in CHANNEL_GENES
    if owner_line is not None:
        owner_dir = known_direction(owner_line, claims)
    else:
        owner_dir = asset.direction if owner_channel else Direction.NOT_APPLICABLE
    if asset.direction is Direction.UNKNOWN:
        owner_dir = Direction.UNKNOWN
    support = direction_support(target, claims)
    evidence = [c.claim_id for c in support[:2]]
    cited = support[0].pmid if support else None
    crosses_dir = (
        target_dir in (Direction.GAIN, Direction.LOSS)
        and owner_dir in (Direction.GAIN, Direction.LOSS)
        and target_dir is not owner_dir
    )
    owner_name = owner_line.label if owner_line else f"the {asset.owner_gene} community"
    co_owners = sorted(
        {a.owner_gene for a in seed.assets if a.source.url == asset.source.url} - {target.gene}
    )
    if len(co_owners) > 1:
        owner_dir_for_name = owner_line.direction if owner_line else asset.direction
        labels = [
            ln.label
            for ln in seed.lines
            if ln.gene in co_owners
            and (ln.gene not in CHANNEL_GENES or ln.direction is owner_dir_for_name)
        ]
        owner_name = (
            _join(labels)
            if labels and owner_channel and owner_line is not None
            else f"the {_join(co_owners)} communities"
        )
    runner = f", run by {facts['owner_org']}" if facts.get("owner_org") else ""
    differs: list[str] = []
    if asset.owner_gene != target.gene:
        other = next((line for line in seed.lines if line.gene == asset.owner_gene), None)
        differs.append(f"gene: {target.gene} here, {asset.owner_gene} there")
        if other is not None and other.gene not in CHANNEL_GENES:
            differs.append(f"mechanism: {asset.owner_gene} is {other.gloss}")
    if crosses_dir:
        differs.append(
            "direction: in your child's form the channel "
            f"{GLOSS[target_dir].replace('work ', 'works ')}; in that group it "
            f"{GLOSS[owner_dir].replace('work ', 'works ')}"
        )
    if facts.get("nct"):
        lo, hi = facts["age_range"]
        groups = [STD_AGE_WORDS[a] for a in facts.get("std_ages", []) if a in STD_AGE_WORDS]
        if lo and hi:
            differs.append(f"age range in the study record: {lo} to {hi}")
        elif lo or hi:
            differs.append(
                f"age range in the study record: {'from ' + lo if lo else 'up to ' + hi}"
            )
        elif groups:
            differs.append(f"ages in the study record: {_join(groups)}")
        else:
            differs.append("age range: not stated in the study record")
        if facts.get("study_population"):
            differs.append("who the study is for: the record's own words are shown with this card")

    if asset.type in TRANSFERABLE:
        kind = KIND_WORDS[asset.type]
        crossing = []
        if asset.owner_gene != target.gene:
            crossing.append("another gene")
        if crosses_dir:
            crossing.append("the opposite direction")
        why = ""
        if crossing:
            why = (
                f" It comes from {' and '.join(crossing)}; {_article(kind)} {kind} can be shared"
                " because it does not depend on how the gene goes wrong."
            )
        return {
            "status": TransferStatus.VIABLE,
            "reason": f"{asset.label}{runner}, used by {owner_name}.{why}",
            "crosses_direction": crosses_dir,
            "blocked": False,
            "cited_pmid": cited if crosses_dir else None,
            "evidence": evidence if crosses_dir else [],
            "what_differs": differs,
            "banner": None,
            "basis_note": None,
        }

    if asset.type not in DIRECTION_GATED_TYPES:
        return _not_shared(f"{asset.label} is not matched across genes.", differs)
    if target.gene not in CHANNEL_GENES or not owner_channel:
        a, b = (asset.owner_gene, target.gene)
        return _not_shared(
            f"{a} works through different biology from {b}, so medicines, trials and mouse"
            " models are not matched between them.",
            differs,
        )
    if target_dir in (Direction.MIXED, Direction.UNKNOWN):
        word = "disagree on" if target_dir is Direction.MIXED else "have not established"
        return _not_shared(
            f"Lab studies {word} the direction of this form, so medicines, trials and models"
            " are not matched.",
            differs,
        )
    if owner_line is not None and owner_line.mechanism != target.mechanism:
        return _not_shared(
            f"{asset.owner_gene} is a different channel mechanism from {target.gene}, so this"
            f" {asset.type.value} is not matched.",
            differs,
        )
    if crosses_dir:
        head = "Same gene, opposite problem"
        if asset.owner_gene != target.gene:
            head = "Same channel family, opposite problem"
        proxy = ONSET_NOTE.strip() if asset.direction_basis is DirectionBasis.ONSET_PROXY else None
        return {
            "status": TransferStatus.NOT_SHARED,
            "reason": (
                f"{head}: not matched to your child's form. Why we say your child's form is"
                f" {target_dir.value} of function: a lab study of {target.gene}"
                f" {support[0].variant} (PMID {cited}), {EVIDENCE_LEVEL}."
            ),
            "banner": (
                f"{head}: your variant makes the channel {GLOSS[target_dir]}; in {owner_name}"
                f" it {GLOSS[owner_dir].replace('work ', 'works ')}. Medicines, trials and"
                f" models from {'those groups' if ' and ' in owner_name else 'that group'} are"
                " not matched here. Registries and care networks can still be shared."
            ),
            "basis_note": proxy,
            "crosses_direction": True,
            "blocked": True,
            "cited_pmid": cited,
            "evidence": evidence,
            "what_differs": differs,
        }
    if owner_dir in (Direction.MIXED, Direction.UNKNOWN):
        word = "disagree on" if owner_dir is Direction.MIXED else "have not established"
        return _not_shared(
            f"Lab studies {word} the direction behind this {asset.type.value}, so it is not"
            " matched.",
            differs,
        )
    basis = ""
    if asset.direction_basis is DirectionBasis.ONSET_PROXY:
        basis = " Its direction is inferred from early seizure onset, not lab-tested."
    return {
        "status": TransferStatus.NEEDS_EXPERT_CHECK,
        "reason": (
            f"{asset.label}{runner}{',' if runner else ''} is for {asset.owner_gene} only."
            f" Its design targets the same"
            f" mechanism and direction as this form; an expert can say whether that matters for"
            f" {target.gene} research."
            if asset.owner_gene != target.gene
            else f"{asset.label}{runner}: same mechanism and the same direction as this form."
            " Necessary, not sufficient: the study team decides who can take part."
        ),
        "basis_note": basis.strip() or None,
        "banner": None,
        "crosses_direction": False,
        "blocked": False,
        "cited_pmid": cited,
        "evidence": evidence,
        "what_differs": differs,
    }


# --- The card for one line ---------------------------------------------------------------


def transfers_for(
    target_key: str,
    seed: Seed,
    claims: list[AcceptedClaim],
    studies: dict[str, dict] | None = None,
) -> list[Transfer]:
    studies = studies if studies is not None else load_studies()
    target = next(line for line in seed.lines if line.key == target_key)
    return rank_transfers(target, judge_all(target, seed, claims, studies), seed)


def judge_all(
    target: Line, seed: Seed, claims: list[AcceptedClaim], studies: dict[str, dict]
) -> list[Transfer]:
    open_urls = {str(a.source.url) for a in own_assets(target, seed)}
    judged: list[Transfer] = []
    seen: set[tuple[str, AssetType]] = set()
    for asset in seed.assets:
        url = str(asset.source.url)
        if asset.owner_gene != target.gene and url in open_urls:
            continue  # the same real-world resource is already open to the target
        if asset.owner_gene != target.gene and (url, asset.type) in seen:
            continue  # one row per real resource, whichever community listed it first
        t = judge(target, asset, seed, claims, studies)
        if t is not None:
            judged.append(t)
            seen.add((url, asset.type))
    return judged


def rank_transfers(target: Line, judged: list[Transfer], seed: Seed) -> list[Transfer]:
    """Borrows first, a missing station first, same mechanism before cross-mechanism, blocked
    rows before other refusals, asset type order, dated assets before undated, then id."""
    dated = {a.id for a in seed.assets if a.last_verified or a.source.retrieved}
    assets = {a.id: a for a in seed.assets}
    users: dict[str, int] = {}
    for a in seed.assets:
        users[str(a.source.url)] = len(
            {b.owner_gene for b in seed.assets if b.source.url == a.source.url}
        )
    status_order = {
        TransferStatus.VIABLE: 0,
        TransferStatus.NEEDS_EXPERT_CHECK: 1,
        TransferStatus.ALREADY_OPEN: 2,
        TransferStatus.NOT_SHARED: 3,
    }
    judged.sort(
        key=lambda t: (
            status_order[t.status],
            not t.fills_missing_station,
            t.asset_id not in dated,  # a dated page before one nobody has opened
            bool(t.nct) and t.study_status not in LIVE_STATUSES,  # a live record before UNKNOWN
            -users.get(str(assets[t.asset_id].source.url), 1),  # shared by more communities first
            bool(t.nct) and t.study_status not in OPEN_STATUSES,  # recruiting before completed
            t.crosses_gene and seed_mechanism(seed, t.owner_gene) != target.mechanism,
            not t.blocked,
            TYPE_ORDER.index(t.asset_type),
            t.asset_id,
        )
    )
    return [t.model_copy(update={"rank": i + 1}) for i, t in enumerate(judged)]


def seed_mechanism(seed: Seed, gene: str) -> str:
    return next((line.mechanism for line in seed.lines if line.gene == gene), "")


def card(
    target_key: str,
    seed: Seed,
    claims: list[AcceptedClaim],
    studies: dict[str, dict] | None = None,
) -> dict:
    """Everything the result page needs for one line: stations and ranked transfers."""
    target = next(line for line in seed.lines if line.key == target_key)
    studies = studies if studies is not None else load_studies()
    transfers = transfers_for(target_key, seed, claims, studies)
    stations = station_map(target, seed, claims, studies)
    missing = {s for s, v in stations.items() if v["state"] == "missing"}
    borrowable = sorted(
        {
            t.station.value
            for t in transfers
            if t.status is TransferStatus.VIABLE and t.station.value in missing
        }
    )
    held = sum(v["state"] == "have" for v in stations.values())
    unknown = sum(v["state"] == "unknown" for v in stations.values())
    return {
        "line": target_key,
        "direction": known_direction(target, claims).value,
        "stations": stations,
        "steps": {
            "total": len(Station),
            "held": held,
            "unknown": unknown,
            "missing": sorted(missing),
            "borrowable": borrowable,
            "mode": "steps",
            "sentence": steps_sentence(
                target, held, unknown, sorted(missing), borrowable, halted_steps(stations)
            ),
        },
        "transfers": [json.loads(t.model_dump_json()) for t in transfers],
    }


def halted_steps(stations: dict[str, dict]) -> dict[str, str]:
    return {k: v["halted"] for k, v in stations.items() if v.get("halted")}


def unknown_key(gene: str) -> str:
    return f"{gene.lower()}_unknown"


def unknown_target(gene: str, seed: Seed) -> Line:
    """A stand-in line for "<gene>, direction not known" (the "Don't know" button and a
    direction with no shipped line). Never written to the seed; it only drives the gate."""
    own = [line for line in seed.lines if line.gene == gene]
    mechanism = own[0].mechanism if own else "sodium_channel"
    sources = own[0].sources if own else [a for a in seed.aliases if a.gene == gene][:0]
    return Line.model_construct(
        key=unknown_key(gene),
        gene=gene,
        mechanism=mechanism,
        mechanism_family=MechanismFamily.ION_CHANNEL,
        direction=Direction.UNKNOWN,
        label=gene,  # "the SCN8A community" in texts; the gloss says the direction is unknown
        gloss="direction not known: set by the specific variant; ask your geneticist",
        mechanism_label=None,
        xrefs={},
        sources=list(sources),
        hpo_terms=[],
        organisations=sorted({o for line in own for o in line.organisations}),
    )


def unknown_card(
    gene: str, seed: Seed, claims: list[AcceptedClaim], studies: dict[str, dict] | None = None
) -> dict:
    """The gated result for a channel gene whose direction is not known: registries, care
    networks, outcome measures and natural-history designs only. No medicine, trial or model
    row appears at all, not even as blocked (State copy table: "Don't know" = unknown, gated)."""
    studies = studies if studies is not None else load_studies()
    target = unknown_target(gene, seed)
    shipped = any(line.gene == gene for line in seed.lines)
    # "Don't know" on a shipped gene: registries, care networks, outcome measures (State copy
    # table); a direction-step gene with no shipped line: registries and care networks only.
    allowed = {AssetType.REGISTRY, AssetType.CARE_NETWORK, AssetType.SCREENING}
    if shipped:
        allowed.add(AssetType.OUTCOME_MEASURE)
    judged = [t for t in judge_all(target, seed, claims, studies) if t.asset_type in allowed]
    transfers = rank_transfers(target, judged, seed)
    stations = station_map(target, seed, claims, studies)
    for t in transfers:  # a platform open to everyone counts as held, and says so
        if t.open_to_all and stations[t.station.value]["state"] == "missing":
            stations[t.station.value] = {
                "state": "have",
                "why": f"open to any rare-disease group: {t.reason.split(':', 1)[0]}",
            }
    held = sum(v["state"] == "have" for v in stations.values())
    unknown = sum(v["state"] == "unknown" for v in stations.values())
    missing = sorted(s for s, v in stations.items() if v["state"] == "missing")
    borrowable = sorted(
        {t.station.value for t in transfers if t.status is TransferStatus.VIABLE} & set(missing)
    )
    return {
        "line": target.key,
        "direction": Direction.UNKNOWN.value,
        "stations": stations,
        "steps": {
            "total": len(Station),
            "held": held,
            "unknown": unknown,
            "missing": missing,
            "borrowable": borrowable,
            "mode": "steps",
            "sentence": steps_sentence(
                target, held, unknown, missing, borrowable, halted_steps(stations)
            ),
        },
        "transfers": [json.loads(t.model_dump_json()) for t in transfers],
    }


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def steps_sentence(
    target: Line,
    held: int,
    unknown: int,
    missing: list[str],
    borrowable: list[str],
    halted: dict[str, str] | None = None,
) -> str:
    """Steps mode: counts only, never years ("unknown" is not "missing"). A missing step whose
    own study is stopped or paused says so: "a registry (yours is paused)"."""
    halted = halted or {}
    total = len(Station)
    text = f"Your community already has {held} of {total} steps."
    if unknown:
        text += f" {unknown} {'is' if unknown == 1 else 'are'} not known either way."
    if not missing:
        return text
    n, k = len(missing), len(borrowable)
    names = _join(
        [
            STEP_WORDS[Station(m)] + (f" (yours is {halted[m]})" if m in halted else "")
            for m in missing
        ]
    )
    gated = all(Station(m) in (Station.MODEL, Station.TRIAL) for m in missing)
    if k:
        return (
            f"{text} Of the {n} it is missing ({names}), {k} could be borrowed from a"
            " look-alike group."
        )
    count = "one step" if n == 1 else str(n)
    if target.direction is Direction.UNKNOWN and gated:
        return (
            f"{text} The {count} it is missing, {names}, cannot be matched until a lab study"
            " shows the direction of your child's variant."
        )
    if target.gene in CHANNEL_GENES and gated:
        return (
            f"{text} The {count} it is missing, {names} matched to its direction, cannot be"
            " borrowed from the look-alike group."
        )
    return (
        f"{text} The {count} it is missing, {names}, cannot be borrowed from any group on this map."
    )


CARD_FACTS = (
    "rank",
    "asset_id",
    "status",
    "blocked",
    "crosses_gene",
    "crosses_direction",
    "fills_missing_station",
    "cited_pmid",
    "owner_org",
    "nct",
    "reason",
    "banner",
    "basis_note",
)


def summary(c: dict) -> dict:
    """The facts a judge checks, without claim-id hashes that change on re-extraction."""
    return {
        "direction": c["direction"],
        "stations": {k: v["state"] for k, v in c["stations"].items()},
        "steps": c["steps"],
        "transfers": [{k: t[k] for k in CARD_FACTS} for t in c["transfers"]],
    }


def main(argv: list[str]) -> int:
    seed, problems = load_seed()
    if problems:
        print("transfer: fix the seed first (make validate)")
        return 1
    claims = load_accepted_claims()
    keys = argv or [line.key for line in seed.lines]
    out = {
        key: unknown_card(key.split("_unknown")[0].upper(), seed, claims)
        if key.endswith("_unknown")
        else card(key, seed, claims)
        for key in keys
    }
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

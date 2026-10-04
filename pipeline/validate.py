"""``make validate``: the quality floor under every claim.

Checks every proposed claim against the abstract it cites: the quote must be one
whole sentence of that abstract, name the variant and the gene, and state the
claimed direction inside the clause that names the variant. Batches must carry
Codex provenance whose answer hash matches the committed rows. Human sign-off
binds to the exact claim through a hash over every extracted field. Prints the
funnel: proposed, accepted, rejected (with reasons), signed. Exit 1 if the seed
is broken, a batch was tampered with, or a signed claim no longer holds.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from pydantic import Field, ValidationError

from pipeline import seed_check
from pipeline.check_public import PHONE, env_values
from pipeline.extract import CLAIMS_FILE, batch_sha256, canonical_sha256, core_pmids
from pipeline.fetch import SEED, WORK, normalise
from pipeline.schema import (
    Basis,
    ClaimLevel,
    Direction,
    ExtractedClaim,
    Provenance,
    RejectedBatch,
    Strict,
)

VERIFICATIONS_FILE = SEED / "verifications.yaml"
VERIFIERS_FILE = SEED / "verifiers.txt"
MAX_CLAIMS_PER_PMID = 8
SIGN_OFF_FIELDS = {"verified_by", "verified_at", "verified_hash", "abstract_sha256"}
BOUND_FIELDS = (
    "pmid",
    "gene",
    "claim_level",
    "variant",
    "direction",
    "stance",
    "basis",
    "evidence_quote",
)

# --- Direction vocabulary ------------------------------------------------------
# Everything below is judged inside the clause that names the variant (or the gene for a
# gene-level claim). Strong terms decide; biophysics phrases carry a known sign; weak words
# count only when no strong term is present.
# A suspended hyphen names both directions at once.
BOTH_DIRECTIONS = re.compile(r"\b(?:gain|loss)-?\s*(?:and|or|/)\s*(?:loss|gain)-of-function\b")
# A strong term that is generic ("typical gain-of-function variants", "rather than
# gain-of-function") belongs to no named variant.
GENERIC_BEFORE = re.compile(
    r"(?:unlike|rather than|instead of|opposite to|in contrast to|contrasted with|typical|other"
    r"|previously reported|most|many|some|classic)\s+(?:\w+\s+){0,2}$",
    re.I,
)
GENERIC_AFTER = re.compile(
    r"^\s*(?:\w+\s+){0,1}(?:variants|mutations|alleles|effects|phenotypes)\b", re.I
)
HEDGE = re.compile(
    r"\b(?:may|might|could|predicted|whether|hypothesi[sz]e|hypothesis|suggest(?:s|ed|ing)?|possibl[ey]|likely|putative)\b",
    re.I,
)
STRONG_GAIN = (
    "gain of function",
    "gain-of-function",
    "re:\\bgof\\b",
    "hyperactiv",
    "hyperexcitab",
    "hypermorph",
)
STRONG_LOSS = (
    "loss of function",
    "loss-of-function",
    "re:\\blof\\b",
    "hypomorph",
    "nonfunctional",
    "non-functional",
    "no measurable",
    "no detectable current",
    "haploinsufficien",
    "truncat",
    "instab",
    "unstable",
    "abolish",
)
WEAK_GAIN = ("increas", "enhanc", "larger", "greater", "augment", "prolong", "potentiat")
WEAK_LOSS = ("reduc", "decreas", "smaller", "impair", "diminish", "lower")
# For sodium channels more inactivation means less current, so an inactivation verb carries the
# opposite sign; recovery from inactivation and voltage shifts have their own signs. Patterns are
# applied in order and each match is removed from the text before the next pattern runs, so one
# phrase can never count twice. "slow inactivation" and "fast inactivation" are nouns, so only
# verb forms (slowed, slowing) count as the modifier.
PHRASES: tuple[tuple[re.Pattern[str], Direction, str], ...] = (
    (
        re.compile(
            r"\b(accelerat|faster|enhanc|increas)\w*[^.;]{0,30}\brecovery from"
            r"[^.;]{0,25}inactivation"
        ),
        Direction.GAIN,
        "faster recovery from inactivation",
    ),
    (
        re.compile(
            r"\b(slowed|slowing|slower|delay|impair|reduc)\w*[^.;]{0,30}\brecovery from"
            r"[^.;]{0,25}inactivation"
        ),
        Direction.LOSS,
        "slower recovery from inactivation",
    ),
    (
        re.compile(r"\bdepolari[sz]\w*[^.;]{0,30}\bshift[^.;]{0,40}\binactivation"),
        Direction.GAIN,
        "depolarising shift of inactivation",
    ),
    (
        re.compile(r"\bhyperpolari[sz]\w*[^.;]{0,30}\bshift[^.;]{0,40}\binactivation"),
        Direction.LOSS,
        "hyperpolarising shift of inactivation",
    ),
    (
        re.compile(r"\bdepolari[sz]\w*[^.;]{0,30}\bshift[^.;]{0,40}\bactivation"),
        Direction.LOSS,
        "depolarising shift of activation",
    ),
    (
        re.compile(r"\bhyperpolari[sz]\w*[^.;]{0,30}\bshift[^.;]{0,40}\bactivation"),
        Direction.GAIN,
        "hyperpolarising shift of activation",
    ),
    (
        re.compile(r"\b(enhanc|increas|accelerat|faster|stabili[sz])\w*[^.;]{0,40}\binactivation"),
        Direction.LOSS,
        "inactivation enhanced",
    ),
    (
        re.compile(
            r"\b(impair|reduc|slowed|slowing|slower|prevent|incomplete|destabili[sz]|less|remov|abolish)\w*[^.;]{0,40}\binactivation"
        ),
        Direction.GAIN,
        "inactivation impaired",
    ),
)
# Words that show a sentence reports a measurement; required only when the evidence is weak.
ASSAY_WORDS = (
    "current", "express", "cell", "oocyte", "hek", "patch", "electrophysiolog", "firing",
    "conductance", "gating", "biophysic", "kinase", "phosphorylat", "binding", "stability",
    "in vitro", "channel propert", "voltage", "neuron", "functional", "defect", "inactivation",
    "activation", "shift", "density", "recovery",
)  # fmt: skip
# Clause boundaries are contrast points, not every comma: a verdict often follows its variant
# across a comma ("(R946H and F1765L) were detected, which were proven to cause loss of function").
CLAUSE_SPLIT = re.compile(r";|,\s*and\b|\b(?:whereas|while|but|although|unlike)\b")
NEGATION = re.compile(
    r"\b(no evidence|no change|unchanged|unaltered|did not|does not|do not|not|without|neither"
    r"|absence of|failed to|fail to|lack(?:ed|ing|s)?|(?:similar|comparable) to wild-?type)\b",
    re.I,
)
# Phrases that contain a negation word but do not negate the verdict.
NEGATION_EXEMPT = re.compile(r"\bnot only\b|\bwithout (?:affecting|altering|changing)\b", re.I)
GENE_SYMBOL = re.compile(
    r"\b(SCN\d+[AB]?|KCNQ\d|KCNT\d|STXBP1|CDKL5|SYNGAP1|GRIN\d[AB]?|PCDH19|GABR[AG]\d|FGF12)\b"
)
# Protein names: NaV1.2, Nav1.2, Na(v)1.2, Na(v) 1.2 …; Kv7.2 / Kv7.3.
SODIUM_ALIAS = re.compile(r"\bNa\(?v\)?\s?1\.(\d{1,2})\b", re.I)
SODIUM_GENES = {
    "1": "SCN1A",
    "2": "SCN2A",
    "3": "SCN3A",
    "4": "SCN4A",
    "5": "SCN5A",
    "6": "SCN8A",
    "7": "SCN9A",
    "8": "SCN10A",
    "9": "SCN11A",
}
POTASSIUM_ALIAS = re.compile(r"\bKv7\.([23])\b", re.I)
ABBREVIATIONS = (
    "et al.",
    "e.g.",
    "i.e.",
    "vs.",
    "fig.",
    "approx.",
    "ca.",
    "p.",
    "c.",
    "no.",
    "cf.",
)
FORBIDDEN = {
    "URL": re.compile(r"https?://|www\.", re.I),
    "e-mail": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}"),
    "markup": re.compile(r"<[a-zA-Z/]"),
    "code fence": re.compile(r"```"),
    "abstract tag": re.compile(r"<abstract", re.I),
    "injection phrase": re.compile(r"ignore (all |any )?(previous|prior|above)", re.I),
    "JWT": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "token word": re.compile(r"\b(api[_ -]?key|token|password|secret|bearer)\b", re.I),
    "key shape": re.compile(r"sk[-_][A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}"),
}
AMINO = {
    "A": "Ala", "R": "Arg", "N": "Asn", "D": "Asp", "C": "Cys", "Q": "Gln", "E": "Glu", "G": "Gly",
    "H": "His", "I": "Ile", "L": "Leu", "K": "Lys", "M": "Met", "F": "Phe", "P": "Pro", "S": "Ser",
    "T": "Thr", "W": "Trp", "Y": "Tyr", "V": "Val", "*": "Ter",
}  # fmt: skip
THREE_TO_ONE = {v: k for k, v in AMINO.items()}
HGVS = re.compile(
    r"^(?:p\.?)?\(?([A-Za-z]{1,3})(\d+)"
    r"([A-Za-z]{1,3}|\*|=|(?:[A-Za-z]{1,3})?fs(?:\*|Ter)?\d*|del|dup|ins)\)?$"
)


class Verification(Strict):
    """A human sign-off row. Written only by hand in verifications.yaml."""

    claim_id: str = Field(min_length=1, max_length=160)
    verified_by: str = Field(min_length=1, max_length=60)
    verified_at: date
    verified_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    abstract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass
class Checked:
    claim_id: str
    claim: dict
    pmid: str
    batch: int
    reasons: list[str]
    provenance: dict

    @property
    def accepted(self) -> bool:
        return not self.reasons


# --- Variants ----------------------------------------------------------------


def canonical_variant(variant: str) -> str | None:
    """``p.Arg853Gln`` for any accepted spelling; None when it is not a protein change.

    A bare position (``R853``) is not a variant; only an explicit ``=`` means synonymous.
    """
    m = HGVS.match(variant.strip())
    if not m:
        return None
    ref, pos, alt = m.group(1), m.group(2), m.group(3)
    ref3 = AMINO.get(ref.upper()) if len(ref) == 1 else ref.capitalize()
    if ref3 not in THREE_TO_ONE:
        return None
    if alt == "=":
        return f"p.{ref3}{pos}="
    if alt in ("*", "X", "x", "Ter", "ter"):
        return f"p.{ref3}{pos}Ter"
    low = alt.lower()
    if "fs" in low:
        fm = re.match(r"([A-Za-z]{1,3})?fs(?:\*|ter)?(\d*)$", low)
        ins = fm.group(1) or ""
        ins3 = (AMINO.get(ins.upper()) if len(ins) == 1 else ins.capitalize()) if ins else ""
        return f"p.{ref3}{pos}{ins3}fsTer{fm.group(2)}" if fm.group(2) else f"p.{ref3}{pos}{ins3}fs"
    if low in ("del", "dup", "ins"):
        return f"p.{ref3}{pos}{low}"
    alt3 = AMINO.get(alt.upper()) if len(alt) == 1 else alt.capitalize()
    if alt3 not in THREE_TO_ONE:
        return None
    return f"p.{ref3}{pos}{alt3}"


def variant_pattern(canonical: str) -> re.Pattern[str]:
    """Matches every spelling of a canonical protein change, as a whole token."""
    m = re.match(r"p\.([A-Z][a-z]{2})(\d+)(.*)$", canonical)
    ref3, pos, tail = m.group(1), m.group(2), m.group(3)
    ref1 = THREE_TO_ONE[ref3]
    if tail == "Ter":
        alts = ["Ter", r"\*", "X"]
    elif tail in THREE_TO_ONE:
        alts = [tail, THREE_TO_ONE[tail]]
    elif "fs" in tail.lower():
        alts = [r"\S*fs\S*"]
    else:
        alts = [re.escape(tail)]
    body = rf"(?:{ref3}|{ref1}){pos}(?:{'|'.join(alts)})"
    return re.compile(rf"(?<![A-Za-z0-9])(?:p\.)?\(?{body}\)?(?![A-Za-z0-9])", re.I)


# --- Quote, clause and direction ----------------------------------------------


def sentences(abstract: str) -> list[str]:
    """Split a normalised abstract into sentences, keeping common abbreviations intact."""
    guarded = abstract
    for abbr in ABBREVIATIONS:
        guarded = re.sub(re.escape(abbr), abbr.replace(".", "\u0000"), guarded, flags=re.I)
    guarded = re.sub(r"(\d)\.(\d)", lambda m: m.group(1) + "\u0000" + m.group(2), guarded)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])", guarded)
    return [p.replace("\u0000", ".").strip() for p in parts if p.strip()]


def quote_is_a_sentence(quote: str, abstract: str) -> bool:
    body = quote.rstrip(".!?").strip()
    return any(s.rstrip(".!?").strip() == body for s in sentences(abstract))


def clause_around(text: str, span: tuple[int, int]) -> tuple[int, int]:
    """Bounds of the comma/conjunction-delimited clause of ``text`` that contains ``span``."""
    start, end = 0, len(text)
    for m in CLAUSE_SPLIT.finditer(text):
        if m.end() <= span[0]:
            start = m.end()
        elif m.start() >= span[1]:
            end = m.start()
            break
    return start, end


def genes_named(text: str) -> set[str]:
    """Gene symbols and protein-name aliases in ``text``, as gene symbols."""
    found = set(GENE_SYMBOL.findall(text))
    found |= {
        SODIUM_GENES[m.group(1)] for m in SODIUM_ALIAS.finditer(text) if m.group(1) in SODIUM_GENES
    }
    found |= {f"KCNQ{m.group(1)}" for m in POTASSIUM_ALIAS.finditer(text)}
    return found


ANY_VARIANT = re.compile(
    r"(?<![A-Za-z0-9])(?:p\.)?\(?(?:[A-Z][a-z]{2}\d+(?:[A-Z][a-z]{2}|Ter|\*|=|\S*fs\S*)"
    r"|[A-Z]\d{2,4}(?:[A-Z]|\*|X)(?:fs\S*)?)\)?(?![A-Za-z0-9])"
)


def mentions(text: str) -> list[tuple[tuple[int, int], str | None]]:
    """(span, gene) for every variant token (gene None), gene symbol and protein alias."""
    found: list[tuple[tuple[int, int], str | None]] = [
        (m.span(), None) for m in ANY_VARIANT.finditer(text)
    ]
    found += [(m.span(), m.group(1)) for m in GENE_SYMBOL.finditer(text)]
    found += [(m.span(), SODIUM_GENES.get(m.group(1))) for m in SODIUM_ALIAS.finditer(text)]
    found += [(m.span(), f"KCNQ{m.group(1)}") for m in POTASSIUM_ALIAS.finditer(text)]
    return sorted(set(found))


LIST_GAP = re.compile(r"^\)?\s*(?:,|and|or|/|,\s*and|,\s*or)\s*\(?$")


def variant_groups(sentence: str) -> list[tuple[int, int]]:
    """Spans of variant lists: consecutive variant tokens joined by commas, and, or, /.

    A chain joined by commas alone ("…variant R1882Q, R853Q reduced…") is two clauses, not
    a list, so it is not merged; a chain needs at least one and/or/slash join.
    """
    spans = sorted(span for span, g in mentions(sentence) if g is None)
    chains: list[tuple[list[tuple[int, int]], bool]] = []  # members, has a non-comma join
    for span in spans:
        if chains:
            gap = sentence[chains[-1][0][-1][1] : span[0]]
            if LIST_GAP.match(gap):
                members, joined = chains[-1]
                chains[-1] = (members + [span], joined or bool(re.search(r"and|or|/", gap)))
                continue
        chains.append(([span], False))
    groups: list[tuple[int, int]] = []
    for members, joined in chains:
        if joined and len(members) > 1:
            groups.append((members[0][0], members[-1][1]))
        else:
            groups.extend(members)
    return groups


def competitors(
    sentence: str, anchor: tuple[int, int], gene: str, bounds: tuple[int, int]
) -> tuple[tuple[int, int], list[tuple[int, int]]]:
    """(effective anchor, mentions that can claim a signal instead of it).

    Competitors are other variants and other genes inside the clause. A variant listed
    together with others ("(R946H and F1765L)") is judged as that whole list. The claim's
    own gene (symbol or alias) never competes with its variant.
    """
    start, end = bounds
    group = next(
        (g for g in variant_groups(sentence) if g[0] <= anchor[0] and anchor[1] <= g[1]), anchor
    )
    out = [group]
    for span, span_gene in mentions(sentence):
        if span[0] < start or span[1] > end or (group[0] <= span[0] and span[1] <= group[1]):
            continue
        if span_gene is None or span_gene != gene:
            out.append(span)
    return group, sorted(set(out))


def nearest(pos: int, anchors: list[tuple[int, int]]) -> tuple[int, int] | None:
    """The mention closest to ``pos``; None on a tie between two different mentions."""
    best = sorted((min(abs(pos - a), abs(pos - b)), (a, b)) for a, b in anchors)
    if len(best) > 1 and best[0][0] == best[1][0] and best[0][1] != best[1][1]:
        return None
    return best[0][1] if best else None


def _term_pattern(term: str) -> str:
    return term[3:] if term.startswith("re:") else re.escape(term)


def _hits(text: str, skip_generic: bool = True) -> list[tuple[int, Direction, str]]:
    """(position, direction, why) for every direction signal in ``text``.

    A suspended hyphen ("gain- and loss-of-function") yields both directions. A strong term
    that is generic (next to plural "variants", or after "unlike", "rather than", "typical" …)
    belongs to no named variant and is skipped.
    """
    low = text.lower()
    hits: list[tuple[int, Direction, str]] = []
    for m in BOTH_DIRECTIONS.finditer(low):
        hits.append((m.start(), Direction.GAIN, "strong gain term"))
        hits.append((m.start(), Direction.LOSS, "strong loss term"))
    strong = (
        (STRONG_GAIN, Direction.GAIN, "strong gain term"),
        (STRONG_LOSS, Direction.LOSS, "strong loss term"),
    )
    for terms, direction, why in strong:
        for term in terms:
            for m in re.finditer(_term_pattern(term), low):
                before = low[max(0, m.start() - 40) : m.start()]
                after = low[m.end() : m.end() + 30]
                if skip_generic and (GENERIC_BEFORE.search(before) or GENERIC_AFTER.match(after)):
                    continue
                hits.append((m.start(), direction, why))
    rest = low
    for pattern, direction, why in PHRASES:
        m = pattern.search(rest)
        if m:
            hits.append((m.start(), direction, why))
            rest = rest[: m.start()] + " " * (m.end() - m.start()) + rest[m.end() :]
    weak = (
        (WEAK_GAIN, Direction.GAIN, "weak gain word"),
        (WEAK_LOSS, Direction.LOSS, "weak loss word"),
    )
    for terms, direction, why in weak:
        for term in terms:
            for m in re.finditer(re.escape(term), rest):
                hits.append((m.start(), direction, why))
    return hits


def direction_evidence(sentence: str, anchor: tuple[int, int], gene: str) -> dict[Direction, str]:
    """Which directions the sentence supports *for the mention at anchor*, and why.

    Every direction signal is assigned to the nearest named variant or gene; only signals
    that belong to the anchor count, and only inside its clause. Weak words count only
    when no strong term belongs to the anchor. Gain and loss together = ambiguous.
    """
    start, end = clause_around(sentence, anchor)
    is_variant = ANY_VARIANT.fullmatch(sentence[anchor[0] : anchor[1]]) is not None
    anchor, anchors = competitors(sentence, anchor, gene, (start, end))
    # Generic plural terms ("gain-of-function variants") name no variant, but they are the
    # normal phrasing of a gene-level claim, so they are skipped only for variant anchors.
    hits = _hits(sentence, skip_generic=is_variant)
    mine = [h for h in hits if start <= h[0] < end and nearest(h[0], anchors) == anchor]
    found: dict[Direction, str] = {}
    for _, direction, why in mine:
        if not why.startswith("weak"):
            found.setdefault(direction, why)
    if not any(why.startswith("strong") for why in found.values()):
        for _, direction, why in mine:
            if why.startswith("weak"):
                found.setdefault(direction, why)
    return found


def strip_strong_terms(text: str) -> str:
    """Blank strong terms so their own words ("no measurable") do not read as negation."""
    low = text.lower()
    for term in STRONG_GAIN + STRONG_LOSS:
        low = re.sub(_term_pattern(term), lambda m: " " * len(m.group(0)), low)
    return low


def negated(sentence: str, anchor: tuple[int, int], gene: str) -> bool:
    """A negation assigned to the anchor's mention inside its clause (strong terms removed)."""
    start, end = clause_around(sentence, anchor)
    text = strip_strong_terms(sentence)
    text = NEGATION_EXEMPT.sub(lambda m: " " * len(m.group(0)), text)
    anchor, anchors = competitors(sentence, anchor, gene, (start, end))
    for m in NEGATION.finditer(text):
        if start <= m.start() < end and nearest(m.start(), anchors) == anchor:
            return True
    return False


def claim_hash(claim: dict) -> str:
    """sha256 of canonical JSON of every extracted field, quote and variant normalised."""
    bound = {k: claim.get(k) for k in BOUND_FIELDS}
    bound["evidence_quote"] = normalise(claim.get("evidence_quote") or "")
    if bound.get("variant"):
        bound["variant"] = canonical_variant(bound["variant"]) or bound["variant"]
    return hashlib.sha256(
        json.dumps(bound, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def claim_id(claim: dict) -> str:
    """Stable, content-derived id: pmid:gene:variant-or-gene:direction:hash8."""
    variant = (
        canonical_variant(claim.get("variant") or "") or claim.get("variant") or claim.get("gene")
    )
    head = f"{claim.get('pmid')}:{claim.get('gene')}:{variant}:{claim.get('direction')}"
    return f"{head}:{claim_hash(claim)[:8]}"


def load_stub(pmid: str, work: Path = WORK) -> dict | None:
    path = work / f"{pmid}.json"
    return json.loads(path.read_text()) if path.exists() else None


def check_claim(raw: dict, stub: dict | None, secrets: list[str]) -> list[str]:
    """Every rejection reason for one proposed claim (empty = accepted)."""
    if not isinstance(raw, dict):
        return ["row is not a mapping"]
    if SIGN_OFF_FIELDS & set(raw):
        return ["model row carries sign-off fields"]
    try:
        claim = ExtractedClaim.model_validate(raw)
    except ValidationError as exc:
        return [f"schema: {exc.errors()[0]['msg']}"]
    if stub is None:
        return ["stub missing for this PMID (run make fetch)"]
    reasons: list[str] = []
    for field in ("variant", "evidence_quote", "gene"):
        value = raw.get(field) or ""
        for name, pattern in FORBIDDEN.items():
            if pattern.search(value):
                reasons.append(f"{name} in {field}")
        if PHONE.search(value):
            reasons.append(f"phone number in {field}")
        if any(secret in value for secret in secrets):
            reasons.append(f".env value in {field}")
    if reasons:
        return reasons

    quote = normalise(claim.evidence_quote)
    abstract = stub["abstract"]
    if quote not in abstract:
        return ["quote is not a substring of the abstract"]
    if not quote_is_a_sentence(quote, abstract):
        reasons.append("quote is not one whole sentence of the abstract")

    # Where in the sentence the claim lives: the variant, or the gene for gene-level claims.
    named = genes_named(quote)
    if claim.claim_level is ClaimLevel.VARIANT:
        canonical = canonical_variant(claim.variant or "")
        if canonical is None:
            return reasons + ["variant is not a protein change in HGVS form"]
        m = variant_pattern(canonical).search(quote)
        if m is None:
            return reasons + ["quote does not name the variant"]
        anchor = m.span()
        if named and claim.gene not in named:
            reasons.append(f"quote names {', '.join(sorted(named))}, not {claim.gene}")
        elif not named and claim.gene not in genes_named(stub.get("title", "") + " " + abstract):
            reasons.append(f"abstract never names {claim.gene}")
    else:
        gm = re.search(rf"\b{re.escape(claim.gene)}\b", quote)
        if gm is None:
            alias = next(
                (
                    m
                    for m in SODIUM_ALIAS.finditer(quote)
                    if SODIUM_GENES.get(m.group(1)) == claim.gene
                ),
                None,
            )
            gm = alias
        if gm is None:
            return reasons + ["quote does not name the gene"]
        anchor = gm.span()

    if negated(quote, anchor, claim.gene):
        reasons.append("negation in the clause that names the variant")

    evidence = direction_evidence(quote, anchor, claim.gene)
    wanted = Direction(claim.direction)
    if wanted is Direction.NOT_APPLICABLE:
        reasons.append("not_applicable is a line setting, not a claim")
    elif wanted is Direction.MIXED:
        if not ({Direction.GAIN, Direction.LOSS} <= set(evidence)):
            reasons.append("mixed needs both direction words in the variant's clause")
    elif wanted in (Direction.GAIN, Direction.LOSS):
        opposite = Direction.LOSS if wanted is Direction.GAIN else Direction.GAIN
        if wanted not in evidence:
            reasons.append(f"no {wanted.value}-of-function evidence in the variant's clause")
        elif opposite in evidence:
            reasons.append("direction ambiguous: the clause carries both directions")
    pub_types = " ".join(stub.get("publication_types", [])).lower()
    if claim.basis is Basis.FUNCTIONAL_ASSAY:
        if "review" in pub_types:
            reasons.append("functional-assay basis on a review article")
        weak_only = evidence and all(why.startswith("weak") for why in evidence.values())
        if weak_only and not any(w in quote.lower() for w in ASSAY_WORDS):
            reasons.append("functional-assay basis without an assay word in the quote")
    return reasons


SPLIT_GENES = {"SCN1A", "SCN2A", "SCN8A"}


def claim_flags(raw: dict) -> list[str]:
    """Non-blocking notes for the signer: hedged wording, gene-level direction on a split gene."""
    flags: list[str] = []
    quote = raw.get("evidence_quote") or ""
    if HEDGE.search(quote):
        flags.append("hedged wording in the quote: check the stance before signing")
    if (
        raw.get("claim_level") == "gene"
        and raw.get("gene") in SPLIT_GENES
        and raw.get("direction") in ("gain", "loss")
    ):
        flags.append("gene-level direction for a direction-split gene: never sets a line direction")
    return flags


def derive_mixed(accepted: list[Checked]) -> dict[tuple[str, str], Direction]:
    """(gene, canonical variant) -> direction from accepted assay claims; both = mixed."""
    seen: dict[tuple[str, str], set[Direction]] = defaultdict(set)
    for c in accepted:
        claim = c.claim
        if claim["basis"] == Basis.FUNCTIONAL_ASSAY and claim.get("variant"):
            key = (claim["gene"], canonical_variant(claim["variant"]) or claim["variant"])
            seen[key].add(Direction(claim["direction"]))
    out: dict[tuple[str, str], Direction] = {}
    for key, directions in seen.items():
        if {Direction.GAIN, Direction.LOSS} <= directions or Direction.MIXED in directions:
            out[key] = Direction.MIXED
        elif len(directions) == 1:
            out[key] = next(iter(directions))
        else:
            out[key] = Direction.UNKNOWN
    return out


# --- Batches and signatures ---------------------------------------------------

BATCH_KEYS = {"provenance", "pmids", "abstract_sha256s", "claims"}


def validate_claims(
    claims_file: Path = CLAIMS_FILE, work: Path = WORK
) -> tuple[list[Checked], list[str], list[str]]:
    """Check every batch. Returns (checked claims, fatal problems, warnings)."""
    fatal: list[str] = []
    warnings: list[str] = []
    checked: list[Checked] = []
    if not claims_file.exists():
        warnings.append("no claims file yet (run make extract)")
        return checked, fatal, warnings
    doc = yaml.safe_load(claims_file.read_text()) or {}
    if not isinstance(doc, dict) or set(doc) != {"batches", "rejected_batches"}:
        return checked, ["claims file must hold exactly batches and rejected_batches"], warnings
    secrets = env_values()
    extracted: set[str] = set()
    seen_ids: set[str] = set()
    for n, batch in enumerate(doc.get("batches", [])):
        if not isinstance(batch, dict) or set(batch) != BATCH_KEYS:
            fatal.append(f"batch {n}: not a plain provenance/pmids/abstract_sha256s/claims record")
            continue
        try:
            provenance = Provenance.model_validate(batch["provenance"])
        except ValidationError as exc:
            fatal.append(f"batch {n}: provenance invalid ({exc.errors()[0]['msg']})")
            continue
        pmids = [str(p) for p in batch["pmids"]]
        rows = batch["claims"]
        if canonical_sha256({"claims": rows}) != provenance.output_sha256:
            fatal.append(f"batch {n}: rows differ from the model's answer hash (edited by hand?)")
            continue
        if set(pmids) & extracted:
            fatal.append(
                f"batch {n}: PMID(s) already extracted in an earlier batch (replayed batch?)"
            )
            continue
        extracted |= set(pmids)
        recorded = batch["abstract_sha256s"]
        if not isinstance(recorded, dict) or set(recorded) != set(pmids):
            fatal.append(f"batch {n}: pmids and abstract_sha256s disagree (edited by hand?)")
            continue
        stubs = {p: load_stub(p, work) for p in pmids}
        if not all(stubs.values()):
            warnings.append(
                f"batch {n}: stub(s) missing, manifest hash not checked (run make fetch)"
            )
        elif provenance.input_manifest_sha256 != batch_sha256(pmids, work):
            changed = [p for p in pmids if stubs[p]["abstract_sha256"] != recorded[p]]
            if changed:
                warnings.append(
                    f"batch {n}: abstract(s) changed since the run ({', '.join(changed)})"
                )
            else:
                fatal.append(
                    f"batch {n}: manifest hash differs but no abstract changed (pmids edited?)"
                )
                continue
        per_pmid: Counter[str] = Counter()
        prov = json.loads(provenance.model_dump_json())
        for raw in rows:
            pmid = str(raw.get("pmid", "")) if isinstance(raw, dict) else ""
            reasons: list[str] = []
            if pmid not in pmids:
                reasons.append("PMID not in this batch's manifest")
            per_pmid[pmid] += 1
            if per_pmid[pmid] > MAX_CLAIMS_PER_PMID:
                reasons.append(f"more than {MAX_CLAIMS_PER_PMID} claims for one PMID")
            reasons += check_claim(raw, stubs.get(pmid), secrets)
            cid = claim_id(raw) if isinstance(raw, dict) else f"?:{n}"
            if cid in seen_ids:
                reasons.append("duplicate of an earlier claim")
            seen_ids.add(cid)
            checked.append(Checked(cid, raw, pmid, n, reasons, prov))
    for n, rej in enumerate(doc.get("rejected_batches", []) or []):
        try:
            r = RejectedBatch.model_validate(rej)
        except ValidationError:
            fatal.append(f"rejected batch {n}: malformed record")
            continue
        extracted |= set(r.pmids)
        warnings.append(
            f"batch rejected at run time ({r.reason}); not extracted: {', '.join(r.pmids)}"
        )
    if claims_file == CLAIMS_FILE:
        missing = [p for p in core_pmids() if p not in extracted]
        if missing:
            fatal.append(f"Core PMIDs in no batch and no rejected record: {', '.join(missing)}")
    return checked, fatal, warnings


def load_verifications() -> tuple[list[Verification], list[str]]:
    if not VERIFICATIONS_FILE.exists():
        return [], []
    rows = yaml.safe_load(VERIFICATIONS_FILE.read_text()) or []
    allowed = set()
    if VERIFIERS_FILE.exists():
        allowed = {
            line.strip()
            for line in VERIFIERS_FILE.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        }
    out: list[Verification] = []
    problems: list[str] = []
    for row in rows:
        try:
            v = Verification.model_validate(row)
        except ValidationError as exc:
            problems.append(f"verifications.yaml: {exc.errors()[0]['msg']}")
            continue
        if v.verified_by not in allowed:
            problems.append(
                f"verifications.yaml: {v.verified_by!r} is not on the verifier allowlist"
            )
            continue
        out.append(v)
    return out, problems


def check_signatures(
    checked: list[Checked], verifications: list[Verification], work: Path = WORK
) -> tuple[set[str], list[str], list[str]]:
    """Which claim ids are validly signed; fatal problems; warnings."""
    by_id = {c.claim_id: c for c in checked}
    signed: set[str] = set()
    problems: list[str] = []
    warnings: list[str] = []
    for v in verifications:
        c = by_id.get(v.claim_id)
        if c is None:
            problems.append(f"signed claim {v.claim_id} is not in claims_extracted.yaml")
            continue
        if not c.accepted:
            problems.append(f"signed claim {v.claim_id} is rejected: {'; '.join(c.reasons)}")
            continue
        if claim_hash(c.claim) != v.verified_hash:
            problems.append(
                f"signed claim {v.claim_id}: hash differs from the claim text (unverified)"
            )
            continue
        stub = load_stub(c.pmid, work)
        if stub and stub["abstract_sha256"] != v.abstract_sha256:
            if normalise(c.claim["evidence_quote"]) in stub["abstract"]:
                warnings.append(f"abstract {c.pmid} changed since signing; quote still present")
            else:
                problems.append(
                    f"signed claim {v.claim_id}: abstract changed and the quote is gone"
                )
                continue
        signed.add(v.claim_id)
    return signed, problems, warnings


def main(argv: list[str] | None = None) -> int:
    """``python -m pipeline.validate [claims-file]``; the default is the committed seed file."""
    claims_file = Path(argv[0]) if argv else CLAIMS_FILE
    seed, seed_problems = seed_check.load_seed()
    if not seed_problems:
        seed_problems = [
            p for p in seed_check.check_references(seed) if not p.startswith("skipped:")
        ]
    for p in seed_problems:
        print(f"seed: {p}")

    checked, fatal, warnings = validate_claims(claims_file)
    verifications, sign_problems = load_verifications()
    signed, bind_problems, bind_warnings = check_signatures(checked, verifications)
    accepted = [c for c in checked if c.accepted]
    rejected = [c for c in checked if not c.accepted]

    print(
        f"funnel: Codex proposed {len(checked)}, validator accepted {len(accepted)},"
        f" rejected {len(rejected)}"
    )
    for c in rejected:
        print(f"  rejected {c.claim_id}: {'; '.join(c.reasons)}")
    for key, direction in sorted(derive_mixed(accepted).items()):
        if direction is Direction.MIXED:
            print(f"  mixed in code: {key[0]} {key[1]} (accepted assays report both directions)")
    for w in warnings + bind_warnings:
        print(f"validate: warning — {w}")
    for p in fatal + sign_problems + bind_problems:
        print(f"validate: {p}")
    if accepted:
        print("accepted claims:")
        for c in accepted:
            k = c.claim
            stub = load_stub(c.pmid) or {}
            print(f"  {c.claim_id}")
            print(
                f"    {k['gene']} {k.get('variant') or '(gene level)'}"
                f" {k['direction']} {k['stance']} {k['basis']}"
            )
            print(f"    quote: {k['evidence_quote']}")
            for flag in claim_flags(k):
                print(f"    flag: {flag}")
            print(f"    verified_hash: {claim_hash(k)}")
            print(f"    abstract_sha256: {stub.get('abstract_sha256', '?')}")
    failed = seed_problems or fatal or sign_problems or bind_problems
    print(f"validate: {'FAILED' if failed else 'ok'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

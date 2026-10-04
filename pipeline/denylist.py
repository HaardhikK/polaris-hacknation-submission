"""Words that model-written text may never contain.

``FAMILY`` guards every patient-facing text (explanations, proposals, card
sentences). ``SCREEN`` guards the researcher screen. Lists live here, in one
place, so the post-check and ``make check-public`` agree. Matching is by stem:
"enrol" also catches "enrolling", "cure" catches "curative".
"""

from __future__ import annotations

import re

# Drug names, classes and abbreviations that appear in the slice's trials or papers.
DRUG_TERMS: tuple[str, ...] = (
    "sodium channel blocker",
    "sodium-channel blocker",
    "channel blocker",
    "antisense oligonucleotide",
    "anti-seizure medication",
    "antiseizure medication",
    "antiepileptic",
    "aso",
    "asm",
    "aed",
    "carbamazepine",
    "oxcarbazepine",
    "phenytoin",
    "lamotrigine",
    "lacosamide",
    "valproate",
    "topiramate",
    "clobazam",
    "stiripentol",
    "cannabidiol",
    "fenfluramine",
    "soticlestat",
    "ganaxolone",
    "relutrigine",
    "elsunersen",
    "retigabine",
    "ezogabine",
    "quinidine",
    "memantine",
    "ataluren",
    "l-serine",
    "prax-562",
    "prax-222",
    "xen496",
    "nbi-921352",
    "cap-002",
    "tak-935",
    "mexiletine",
    "lidocaine",
    "ranolazine",
    "levetiracetam",
    "ethosuximide",
    "everolimus",
    "vigabatrin",
    "acth",
    "prednisolone",
    "zonisamide",
    "clonazepam",
    "phenobarbital",
    "gabapentin",
    "steroid",
    "valproic",
    "cenobamate",
    "perampanel",
    "tiagabine",
    "primidone",
    "felbamate",
    "ketamine",
    "midazolam",
    "sulthiame",
    "cbd",
    "cannabis",
)

# Words that promise, judge or diagnose. Never in family-facing text.
FAMILY_TERMS: tuple[str, ...] = (
    "cure",
    "cur",  # curative, cured, cures
    "safe",
    "will help",
    "eligible",
    "eligibility",
    "enrol",
    "enroll",
    "fail",
    "unsuccessful",
    "safer",
    "safest",
    "benefit",
    "proven",
    "validat",
    "diagnos",
    "recommend",
)

FAMILY: tuple[str, ...] = DRUG_TERMS + FAMILY_TERMS

# Model-written explanations and proposals (``make explain``) are held to more than the fixed
# family copy: no talk of medicines or treatment at all, no advice verbs, no promises.
EXPLAIN_ONLY: tuple[str, ...] = (
    "medicine",
    "medication",
    "drug",
    "therap",
    "treat",
    "dose",
    "diet",
    "antisense",
    "blocker",
    "should",
    "switch",
    "stop",
    "effective",
    "harmless",
    "guarantee",
    "qualif",
    "best",
    "risk",
    "could help",
    "improve",
    "prove",
    "med",
    "prescri",
    "avoid",
    "unsafe",
    "danger",
    "harm",
    "worsen",
    "help",
    "reduce",
    "promising",
    "match for",
    "matches your",
    "right for",
    "suits",
    "fits your",
    "can join",
    "heal",
    "good match",
    "good fit",
    "worth a try",
    "respond",
    "got better",
    "went away",
    "lowers",
)
EXPLAIN: tuple[str, ...] = FAMILY + EXPLAIN_ONLY
# Word shapes that are almost always a medicine name, whatever the list says.
DRUG_SHAPE = re.compile(
    r"(?<![A-Za-z])[A-Za-z]{2,}(?:azepine|amide|zolamide|trigine|nersen|barbital|pam|mab"
    r"|etine|caine|azine|racetam|imide|olimus|batrin|sartan|statin|pril|olol|oxetine|tide"
    r"|bamate|gabine|azolam)(?![A-Za-z])",
    re.IGNORECASE,
)

# A development code such as PRAX-562 or TAK-935: two to five letters, a hyphen, three to six
# digits. Never an NCT or PMID (no hyphen), never a gene symbol (no digit run after a hyphen),
# never a repository or standard id (JAX-, MMRRC-, RBRC-, ISO-).
DRUG_CODE = re.compile(
    r"(?<![A-Za-z0-9])(?!(?:JAX|MMRRC|RBRC|ISO)-)[A-Za-z]{2,5}-\d{3,6}(?![A-Za-z0-9])", re.I
)

# The researcher screen adds everything that reads as clinical advice.
SCREEN: tuple[str, ...] = (
    "safe",
    "unsafe",
    "safety",
    "dangerous",
    "harmful",
    "worsen",
    "aggravat",
    "contraindicat",
    "avoid",
    "should",
    "stop",
    "start",
    "switch",
    "dose",
    "dosing",
    "mg",
    "prescri",
    "off-label",
    "treat",
    "therapy for",
    "cure",
    "cur",
    "effective",
    "work",
    "will help",
    "recommend",
    "promising",
    "best",
    "top pick",
    "candidate treatment",
    "for your child",
    "#1",
    "stopped because",
    "fail",
    "terminated due to",
)

# Inflections a stem may carry: "safely", "enrolment", "validated", "treatments", "curative",
# "curable", "diagnostic", "therapeutics".
_SUFFIX = (
    r"(?:s|es|d|ed|ing|ly|ment|ments|al|ally|ive|ative|ation|ations|ance|ence|is|ed"
    r"|able|ible|tic|tics|ic|ics|y|ies)?"
)


def _pattern(terms: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    # Word start may follow a digit ("10mg"); word end allows an inflection but no other letters,
    # so "unsafe" and "safeguard" do not match "safe".
    return re.compile(rf"(?<![A-Za-z])(?:{alternatives}){_SUFFIX}(?![A-Za-z])", re.IGNORECASE)


_FAMILY_RE = _pattern(FAMILY)
_EXPLAIN_RE = _pattern(EXPLAIN)
_SCREEN_RE = _pattern(SCREEN)
_LISTS = {
    "family": (_FAMILY_RE, DRUG_SHAPE, DRUG_CODE),
    "explain": (_EXPLAIN_RE, DRUG_SHAPE, DRUG_CODE),
    "screen": (_SCREEN_RE,),  # the researcher screen names medicines by design
}


def denied_terms(text: str, which: str = "family") -> list[str]:
    """Return the denied words found in ``text``, lower-cased, in order, without repeats."""
    seen: dict[str, None] = {}
    hits = []
    for pattern in _LISTS[which]:
        hits += [(m.start(), m.group(0).lower()) for m in pattern.finditer(text)]
    for _, word in sorted(hits):
        seen.setdefault(word, None)
    return list(seen)

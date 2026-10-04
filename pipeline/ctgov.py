"""ClinicalTrials.gov: the committed cache and the ``co_listed_in`` edges.

``strip_record`` keeps only the allow-listed fields of a fetched v2 record
(the strip-list in ``pipeline/check_public.py``). ``co_listings`` names a line in a study only
when its gene appears in the conditions, the keywords, or the inclusion part of
the eligibility text; the eligibility text itself is never committed, only the
field that matched and the phrase around the match, at most 120 characters.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from pipeline.fetch import RAW
from pipeline.schema import CoListing, Line, MatchedField, StudyRecord

# Case-sensitive on purpose: "do", "md" and "pc" are words; "M.D.", "D.O." and "PC" are titles.
# The comma-anchored suffixes also catch "Pittsburgh, PA": a false positive only sends the row to
# a person, the safe direction; check_public.py carries the same pattern without the bare PC.
PERSON_TITLE = re.compile(
    r"\b(?:Dr|Prof|dr|prof|DR|PROF)\.?\s|\b(?:M\.?D|m\.d|Ph\.?D|D\.O|MBBS|M\.B\.B\.S|PC|P\.C|PLLC)\b\.?"
    r"|,\s*(?:DO|RN|NP|PA|FRCP|Pharm\.?D)\b"
)
REFERS_BACK = re.compile(r"\b(?:above|below|specified|listed|these|following)\b", re.I)
# Fixed captions per study kind on a co_listed_in edge (the plan's label for eligible-gene lists).
# One home: build.py writes them into the cache and check_public allows them past the deny-list.
CAVEATS = {
    "eligible_gene_list": (
        "listed in an eligible-gene list of 107 genes; a movement disorder is required;"
        " checked by code only"
    ),
    "registry": "being listed does not mean families are enrolled",
    "natural_history": "being listed does not mean families are enrolled",
    "trial": "the study team decides who can take part",
    "biorepository": "being listed does not mean samples are held",
}
STD_AGE_WORDS = {"CHILD": "children", "ADULT": "adults", "OLDER_ADULT": "older adults"}
# Two capitalised words in a row that are not gene symbols or known headings: possibly a name.
NAME_LIKE = re.compile(r"\b(?![A-Z0-9]{3,}\b)[A-Z][a-z]{2,}\s+(?![A-Z0-9]{3,}\b)[A-Z][a-z]{2,}\b")
NAME_HEADINGS = {"Inclusion Criteria", "Exclusion Criteria", "United States", "United Kingdom"}
# Headings that start the exclusion part; everything from the first one on is dropped.
EXCLUSION_HEADING = re.compile(r"^\s*(?:key\s+)?exclusion(?:s|\s+criteria)?\s*:?\s*$", re.I | re.M)
EXCLUSION_WORD = re.compile(r"\bexclu", re.I)
# A gene mention preceded by a negation does not count as an inclusion.
NEGATED = re.compile(r"\b(?:not|no|without|except|excluding|other than)\b[^.;:]{0,40}$", re.I)
PHRASE_BREAK = re.compile(r"[,;:()\n]|\.\s")
WINDOW = 120


def _date(struct: dict | None) -> str | None:
    return (struct or {}).get("date")


DEGREES = re.compile(r"\b(md|phd|mbbs|do|msc|mph|frcp|prof\.?|dr\.?)\b\.?", re.I)


def _normalise_name(name: str) -> str:
    """Fold case, drop degree suffixes ("John Smith, MD" -> "john smith"), collapse spaces."""
    base = re.split(r"[,(]", name, maxsplit=1)[0]
    base = DEGREES.sub(" ", base)
    return re.sub(r"\s+", " ", base).strip().lower()


def _people_named(p: dict) -> set[str]:
    """Names the record carries for investigators and officials: read, compared, never kept."""
    names: set[str] = set()
    party = p.get("sponsorCollaboratorsModule", {}).get("responsibleParty") or {}
    if party.get("investigatorFullName"):
        names.add(party["investigatorFullName"])
    for official in p.get("contactsLocationsModule", {}).get("overallOfficials", []) or []:
        if official.get("name"):
            names.add(official["name"])
    return {_normalise_name(n) for n in names}


def strip_record(raw: dict, retrieved: date) -> StudyRecord:
    """The allow-listed fields of one fetched record; everything else is dropped."""
    p = raw["protocolSection"]
    ident, status = p.get("identificationModule", {}), p.get("statusModule", {})
    cond, design = p.get("conditionsModule", {}), p.get("designModule", {})
    arms, elig = p.get("armsInterventionsModule", {}), p.get("eligibilityModule", {})
    outcomes, sponsor = p.get("outcomesModule", {}), p.get("sponsorCollaboratorsModule", {})
    contacts = p.get("contactsLocationsModule", {})
    lead = sponsor.get("leadSponsor") or {}
    lead_name = lead.get("name")
    # A person as sponsor (class INDIV, or the sponsor name is an investigator's or official's
    # name) is never committed; an institution with a PI as responsible party keeps its name.
    if lead.get("class") == "INDIV" or _normalise_name(lead_name or "") in _people_named(p):
        lead_name = "Individual investigator"
    locations = [
        {
            # a private practice named after a person is never committed
            "facility": "private practice"
            if loc.get("facility") and PERSON_TITLE.search(loc["facility"])
            else loc.get("facility"),
            "city": loc.get("city"),
            "country": loc.get("country"),
        }
        for loc in contacts.get("locations", [])
    ]
    record = {
        "nct": ident["nctId"],
        "brief_title": ident.get("briefTitle", ""),
        "overall_status": status.get("overallStatus", "UNKNOWN"),
        "start_date": _date(status.get("startDateStruct")),
        "last_update_date": _date(status.get("lastUpdatePostDateStruct")),
        "why_stopped": status.get("whyStopped"),
        "conditions": cond.get("conditions", []),
        "keywords": cond.get("keywords", []),
        "interventions": [
            {"type": i.get("type", ""), "name": i.get("name", "")}
            for i in arms.get("interventions", [])
        ],
        "phases": design.get("phases", []),
        "enrollment_count": (design.get("enrollmentInfo") or {}).get("count"),
        "enrollment_type": (design.get("enrollmentInfo") or {}).get("type"),
        "minimum_age": elig.get("minimumAge"),
        "maximum_age": elig.get("maximumAge"),
        "std_ages": [a for a in elig.get("stdAges", []) or [] if a in STD_AGE_WORDS],
        "study_population": _population(elig.get("studyPopulation")),
        "outcome_measures": [
            o.get("measure", "")
            for key in ("primaryOutcomes", "secondaryOutcomes")
            for o in outcomes.get(key, [])
        ],
        "lead_sponsor": lead_name,
        "locations": locations,
        "retrieved": retrieved,
        "human_check": [],
    }
    if record["why_stopped"]:
        record["human_check"].append("why_stopped")  # always read by a person before display
    if record["study_population"] and _looks_personal(record["study_population"]):
        record["study_population"] = None  # a name-like phrase is never committed
    if record["lead_sponsor"] and PERSON_TITLE.search(record["lead_sponsor"]):
        record["human_check"].append("lead_sponsor")
    if any(loc["facility"] and PERSON_TITLE.search(loc["facility"]) for loc in locations):
        record["human_check"].append("locations.facility")
    return StudyRecord.model_validate(record)


def _population(text: str | None) -> str | None:
    """The record's own one-line description of who it is for: first sentence, at most 200
    characters, whitespace collapsed. Never the eligibility criteria."""
    if not text:
        return None
    first = re.split(r"(?<=[.;])\s", re.sub(r"\s+", " ", text).strip(), maxsplit=1)[0]
    if REFERS_BACK.search(first) or len(first) > 200 or not first.endswith((".", ";")):
        return None  # back-references and clipped sentences are never quoted
    return first


def inclusion_text(raw: dict) -> str:
    """The inclusion part of the eligibility text: everything before the exclusion heading.

    Without a heading, the text after the first "exclu…" word is dropped too, so a gene
    named only under an unlabelled exclusion list never counts.
    """
    text = raw["protocolSection"].get("eligibilityModule", {}).get("eligibilityCriteria", "") or ""
    m = EXCLUSION_HEADING.search(text)
    if m:
        return text[: m.start()]
    m = EXCLUSION_WORD.search(text)
    return text[: m.start()] if m else text


def _phrase(text: str, match: re.Match[str]) -> str:
    """The comma/semicolon/line-delimited phrase holding the match, at most WINDOW chars."""
    start = max((b.end() for b in PHRASE_BREAK.finditer(text[: match.start()])), default=0)
    end_match = PHRASE_BREAK.search(text, match.end())
    end = end_match.start() if end_match else len(text)
    phrase = re.sub(r"\s+", " ", text[start:end]).strip(" *-•\t")
    if len(phrase) > WINDOW:
        half = WINDOW // 2
        centre = match.start() - start
        phrase = phrase[max(0, centre - half) : centre + half].strip()
    return phrase


PERSON_CONTEXT = re.compile(
    r"\b(contact|coordinator|investigator|nurse|phone|mother|father|parent|patient named|dob)\b|@",
    re.I,
)


def _looks_personal(text: str) -> bool:
    """A title, or capitalised name-like words next to a person-context word."""
    if PERSON_TITLE.search(text):
        return True
    if not PERSON_CONTEXT.search(text):
        return False
    return any(m.group(0) not in NAME_HEADINGS for m in NAME_LIKE.finditer(text))


def co_listings(lines: list[Line], raw: dict, retrieved: date) -> list[CoListing]:
    """Every line whose gene the record names in conditions, keywords or inclusion text."""
    record = strip_record(raw, retrieved)
    inclusion = inclusion_text(raw)
    out: list[CoListing] = []
    for line in lines:
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(line.gene)}(?![A-Za-z0-9])", re.I)
        for field, texts, tier in (
            (MatchedField.CONDITIONS, record.conditions, 1),
            (MatchedField.KEYWORDS, record.keywords, 2),
            (MatchedField.ELIGIBILITY_INCLUSION, [inclusion], 3),
        ):
            found = None
            for text in texts:
                for m in pattern.finditer(text):
                    if not NEGATED.search(text[: m.start()]):
                        found = (text, m)
                        break
                if found:
                    break
            if found:
                text, m = found
                window = _phrase(text, m)
                personal = _looks_personal(window)
                if personal and not PERSON_TITLE.search(window):
                    window = m.group(0)  # a name-like phrase: keep the gene token only
                out.append(
                    CoListing(
                        line=line.key,
                        gene=line.gene,
                        nct=record.nct,
                        matched_field=field,
                        window=window,
                        tier=tier,
                        human_check=field is MatchedField.ELIGIBILITY_INCLUSION or personal,
                    )
                )
                break
    return out


def load_raw(nct: str, raw_dir: Path = RAW / "ctgov") -> dict:
    return json.loads((raw_dir / f"{nct}.json").read_text())

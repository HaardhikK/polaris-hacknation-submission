"""Code check of the model's critique before any sentence reaches ``screen.json``.

Per sentence, after NFKC normalisation, in this order:
1. Non-ASCII letters or invisible (format) characters -> rejected (look-alike names).
2. SCREEN deny-list word, or lay dosing / home-use wording -> rejected.
3. Names any drug other than the card's own -> rejected. "Any drug" is every approved
   medicine in Open Targets (preferred and trade names), every family-pool drug (names,
   drug-shaped synonyms, the leading word of dose-string synonyms) and the fixed blocklist of
   this slice's investigational drugs; matched case-insensitively, also with hyphens and
   spaces removed and trailing digits stripped.
4. A drug-shaped token (medicine suffix or development code) that is not the card's own
   drug -> rejected, whatever the list says.
5. Over the length cap, or holds markup, a link, a bare domain or an e-mail -> rejected.
6. A person's title or two capitalised words in a row -> rejected.
7. An NCT id or a 7–8-digit id that is not in the card's evidence -> rejected.
8. Any token of 3+ characters with an uppercase letter that is not in the card's facts ->
   rejected (no invented names). Only the sentence-initial token is exempt, and a full stop
   after "Dr", "Prof", "St", "Mr", "Ms" and the like does not start a new sentence. Paper
   titles are not facts.
9. ``pmid`` missing or not in the card's evidence set -> moved to "Model reasoning — not
   checked against a paper".
A doubt's ``kind`` must be one of the fixed kinds, else "other". Kept sentences start with a
capital letter. Items for a drug that is not on a card are dropped. The report is counts only.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from pipeline.ctgov import NAME_HEADINGS, NAME_LIKE
from pipeline.denylist import DRUG_SHAPE, denied_terms
from pipeline.schema import MARKUP_OR_LINK
from pipeline.screen.config import (
    ALWAYS_ALLOWED_TOKENS,
    DOUBT_KINDS,
    GENERIC_SUBSTANCES,
    MAX_SENTENCE_CHARS,
    MODEL_SENTENCE_DENIED,
    NEXT_TESTS,
    OTHER_DRUG_BLOCKLIST,
    SODIUM_CHANNEL_FAMILY,
)

WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9.'-]*")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]*")
ALPHA_PREFIX = re.compile(r"^[A-Za-z]+")
UPPER = re.compile(r"[A-Z]")
PERSON_TITLE = re.compile(r"\b(?:Dr|Prof|Mr|Ms|Mrs)\.?\s|\b(?:MD|PhD)\b")
DEV_CODE = re.compile(r"(?<![A-Za-z0-9])(?!NCT\d)[A-Za-z]{2,6}[-\s]?\d{2,}(?![A-Za-z0-9])", re.I)
# The full stop of an abbreviation or an initial does not end a sentence.
ABBREVIATION_END = re.compile(
    r"(?:\b(?:e\.g|i\.e|et al|vs|cf|fig|no|dr|prof|st|mr|ms|mrs)|\b[A-Z])\.$", re.IGNORECASE
)
PHONE = re.compile(r"(?<!\d)\+?\(?\d{2,4}\)?[\s.-]\d{2,4}[\s.-]\d{3,7}(?!\d)|(?<!\d)\d{9,}(?!\d)")
UNSAFE_LINK = re.compile(r"javascript:|data:|\]\(", re.IGNORECASE)
ALLOWED_NON_ASCII = frozenset("–—‘’“”°µ")
# Medicine-name endings beyond the shared DRUG_SHAPE list (INN stems seen in this slice's field).
DRUG_SUFFIX = re.compile(
    r"(?<![A-Za-z])[A-Za-z]{3,}(?:kalner|caine|tinib|prazole|sartan|oxetine|vastatin|olol"
    r"|tiracetam|gabine|zolam|zepam|semide|setron|mycin|cillin|cycline|floxacin|serin|prodil"
    r"|bamate|gabat|glurant|olone|stat|nersen|trigine)(?![A-Za-z])",
    re.IGNORECASE,
)
NCT = re.compile(r"NCT\d{8}", re.IGNORECASE)
LONG_ID = re.compile(r"(?<![A-Za-z0-9])\d{7,8}(?!\d)")
BARE_DOMAIN = re.compile(r"\b[a-z0-9-]+\.(?:org|com|net|edu|gov|io|info|de|uk|eu)\b", re.I)
# A synonym worth matching as a drug name: four or more characters, starts with a letter, and
# is not a dose string or formulation ("300 mg/5ml oral suspension").
DRUG_SHAPED = re.compile(r"^[A-Za-z][A-Za-z0-9 .'()-]{3,}$")
DOSE_OR_FORM = re.compile(r"\d\s*(mg|ml|mcg|%)|/", re.IGNORECASE)
MIN_NAME_CHARS = 4
MAX_NAME_WORDS = 3
# Capitalised word pairs that are not a person: the registry headings plus the data source.
NOT_NAMES = NAME_HEADINGS | {"Open Targets"}
_MODEL_DENIED = re.compile(
    r"(?<![A-Za-z])(?:"
    + "|".join(re.escape(t) for t in MODEL_SENTENCE_DENIED)
    + r")(?:s|es|ed|ing)?(?![A-Za-z])",
    re.IGNORECASE,
)


def normalise_sentence(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(text)).split())


def non_ascii(text: str) -> bool:
    """Any character outside ASCII except a few typographic marks (dashes, quotes, degree)."""
    return any(ord(ch) > 127 and ch not in ALLOWED_NON_ASCII for ch in text)


def _words(text: str) -> set[str]:
    """Lower-cased tokens plus each token's leading letters ("Nav1.2" also allows "Nav")."""
    words: set[str] = set()
    for token in WORD.findall(text):
        words.add(token.lower().strip(".'-"))
        prefix = ALPHA_PREFIX.match(token)
        if prefix:
            words.add(prefix.group(0).lower())
    return words


def squash(name: str) -> str:
    """Lower-case, no spaces or hyphens, trailing digits stripped: "PRAX-222" -> "prax"."""
    flat = re.sub(r"[\s\-']+", "", name.lower())
    return flat.rstrip("0123456789")


def drug_shaped(name: str) -> bool:
    name = name.strip()
    return (
        len(name) >= MIN_NAME_CHARS
        and bool(DRUG_SHAPED.match(name))
        and not DOSE_OR_FORM.search(name)
    )


def dose_leading_word(name: str) -> str | None:
    """The brand word of a dose-string synonym ("trileptal 300 mg/5ml ..." -> "trileptal")."""
    if not DOSE_OR_FORM.search(name):
        return None
    first = name.strip().split(" ")[0]
    return first if len(first) >= MIN_NAME_CHARS and first.isalpha() else None


def own_names(drug_id: str, card: dict, pool_names: dict[str, set[str]]) -> set[str]:
    return {n.lower().strip() for n in pool_names.get(drug_id, set())} | {card["name"].lower()}


def other_drug_names(
    drug_id: str, pool_names: dict[str, set[str]], approved_names: list[str] | None
) -> set[str]:
    """Every drug name a sentence about ``drug_id`` may not contain, lower-cased."""
    own = {n.lower().strip() for n in pool_names.get(drug_id, set())}
    others: set[str] = set()
    for other, names in pool_names.items():
        if other == drug_id:
            continue
        for name in names:
            others.add(name.lower().strip())
            brand = dose_leading_word(name.lower())
            if brand:
                others.add(brand)
    others |= {n.lower().strip() for n in approved_names or []}
    others |= {n.lower() for n in OTHER_DRUG_BLOCKLIST}
    return {n for n in others - own - GENERIC_SUBSTANCES if drug_shaped(n)}


class NameMatcher:
    """Whole-word match of any other-drug name, as written or squashed."""

    def __init__(self, names: set[str]) -> None:
        terms = sorted({n.strip() for n in names if n.strip()}, key=len, reverse=True)
        self.pattern = (
            re.compile(
                r"(?<![A-Za-z0-9])(?:"
                + "|".join(re.escape(t) for t in terms)
                + r")(?![A-Za-z0-9])",
                re.IGNORECASE,
            )
            if terms
            else None
        )
        squashed = {squash(t) for t in terms} | {re.sub(r"[\s\-']+", "", t) for t in terms}
        self.squashed = {s for s in squashed if len(s) >= MIN_NAME_CHARS}

    def search(self, text: str) -> bool:
        if self.pattern and self.pattern.search(text):
            return True
        tokens = TOKEN.findall(text)
        for i in range(len(tokens)):
            for n in range(1, MAX_NAME_WORDS + 1):
                window = "".join(tokens[i : i + n])
                if squash(window) in self.squashed or window.lower() in self.squashed:
                    return True
        return False


def card_facts(card: dict, line: dict) -> set[str]:
    """Lower-cased words the model may write with a capital: the card's own names, targets,
    action type, the line's label and gloss, study statuses. Never paper titles."""
    facts = set(ALWAYS_ALLOWED_TOKENS) | {g.lower() for g in SODIUM_CHANNEL_FAMILY}
    facts |= _words(card["name"]) | {s.lower() for s in card.get("synonyms", [])}
    for synonym in card.get("synonyms", []):
        facts |= _words(synonym)
    facts |= {t.lower() for t in card.get("targets", [])}
    facts |= _words(card.get("action_type", ""))
    facts |= _words(line.get("label", "")) | _words(line.get("gloss", "")) | {line["gene"].lower()}
    for study in card["evidence"].get("studies", []):
        facts |= _words(study.get("status", ""))
    return facts


def card_pmids(card: dict) -> set[str]:
    ev = card["evidence"]
    return set(ev.get("pmids", [])) | set(ev.get("opentargets_pmids", []))


def card_ncts(card: dict) -> set[str]:
    return {s.get("nct", "").upper() for s in card["evidence"].get("studies", [])}


def _is_fact(part: str, facts: set[str]) -> bool:
    part = part.lower().strip("'")
    return part in facts or squash(part) in facts


def unknown_token(text: str, facts: set[str]) -> bool:
    """A token of 2+ chars with an uppercase letter that is not a fact.

    Only the first token of the whole text is exempt; a full stop after an abbreviation or a
    single initial ("e.g.", "J.") does not start a new sentence, and a later sentence's first
    word is checked like any other. Hyphenated tokens are checked part by part ("SCN2A-related"
    passes on "scn2a").
    """
    for i, match in enumerate(TOKEN.finditer(text)):
        token = match.group(0)
        if i == 0:
            continue
        before = text[: match.start()].rstrip()
        new_sentence = before.endswith((".", "?", "!")) and not ABBREVIATION_END.search(before)
        if new_sentence and _is_fact(token, facts):
            continue
        for part in token.split("-"):
            if len(part) >= 2 and UPPER.search(part) and not _is_fact(part, facts):
                return True
    return False


def sentence_problem(
    text: str, others: NameMatcher | None, own: set[str], card: dict, facts: set[str]
) -> str | None:
    """Why a sentence is rejected, or None when it may be shown (subject to the PMID rule)."""
    if non_ascii(text):
        return "non_ascii"
    if denied_terms(text, "screen") or _MODEL_DENIED.search(text):
        return "denied_word"
    if others and others.search(text):
        return "other_drug_named"
    if (
        len(text) > MAX_SENTENCE_CHARS
        or MARKUP_OR_LINK.search(text)
        or UNSAFE_LINK.search(text)
        or BARE_DOMAIN.search(text)
        or PHONE.search(text)
        or "@" in text
    ):
        return "length_or_link"
    if any(m.group(0).upper() not in card_ncts(card) for m in NCT.finditer(text)):
        return "unknown_id"
    if any(m.group(0) not in card_pmids(card) for m in LONG_ID.finditer(text)):
        return "unknown_id"
    own_squashed = {squash(n) for n in own}
    for pattern in (DRUG_SHAPE, DRUG_SUFFIX, DEV_CODE):
        for match in pattern.finditer(text):
            token = match.group(0)
            if squash(token) not in own_squashed and token.lower() not in facts:
                return "other_drug_named"
    if PERSON_TITLE.search(text) or any(
        m.group(0) not in NOT_NAMES and not _sentence_start(text, m.start())
        for m in NAME_LIKE.finditer(text)
    ):
        return "person_like"
    if unknown_token(text, facts):
        return "unknown_capitalised_token"
    return None


def _sentence_start(text: str, pos: int) -> bool:
    """True at the start of the text or right after sentence punctuation (the unknown-token
    rule still checks the second word of such a pair)."""
    before = text[:pos].rstrip()
    return pos == 0 or before.endswith((".", "?", "!"))


def capitalise(text: str) -> str:
    return text[0].upper() + text[1:] if text else text


def check_item(
    item: dict, card: dict, others: NameMatcher | None, own: set[str], facts: set[str]
) -> tuple[dict, Counter[str]]:
    """One model item for one card -> post-checked critique fields and sentence counts."""
    report: Counter[str] = Counter()
    pmids = card_pmids(card)
    out: dict = {"why": [], "doubts": [], "unchecked_reasoning": []}
    for field in ("why", "doubts"):
        for sentence in item.get(field, []):
            text = normalise_sentence(sentence.get("text", ""))
            report["proposed"] += 1
            problem = sentence_problem(text, others, own, card, facts) if text else "empty"
            if problem:
                report["rejected"] += 1
                report[f"rejected_{problem}"] += 1
                continue
            text = capitalise(text)
            pmid = sentence.get("pmid")
            if pmid in pmids:
                kept = {"text": text, "pmid": pmid}
                if field == "doubts":
                    kind = sentence.get("kind")
                    kept["kind"] = kind if kind in DOUBT_KINDS else "other"
                    if kept["kind"] != kind:
                        report["doubt_kind_defaulted"] += 1
                out[field].append(kept)
                report["kept"] += 1
            else:
                out["unchecked_reasoning"].append(text)
                report["moved"] += 1
    next_test = item.get("next_test")
    out["next_test"] = next_test if next_test in NEXT_TESTS else None
    if out["next_test"] is None:
        report["next_test_dropped"] += 1
    return out, report


def check_answer(
    answer: dict,
    cards: list[dict],
    line: dict,
    pool_names: dict[str, set[str]],
    approved_names: list[str] | None = None,
) -> tuple[dict[str, dict], Counter[str]]:
    """Post-check a whole Codex answer for one line.

    ``pool_names`` maps every drug id in the family pool to its names and synonyms;
    ``approved_names`` lists every approved medicine's preferred and trade names. A sentence
    naming any drug other than the card's own (kept or removed, in the family or not) is
    rejected, so no removed drug is ever named.
    """
    by_id = {c["drug_id"]: c for c in cards}
    report: Counter[str] = Counter()
    checked: dict[str, dict] = {}
    for item in answer.get("items", []):
        drug_id = item.get("drug_id")
        card = by_id.get(drug_id)
        if card is None or drug_id in checked:
            report["items_dropped"] += 1
            continue
        own = own_names(drug_id, card, pool_names)
        others = NameMatcher(other_drug_names(drug_id, pool_names, approved_names))
        facts = card_facts({**card, "synonyms": sorted(own)}, line)
        fields, item_report = check_item(item, card, others, own, facts)
        checked[drug_id] = fields
        report.update(item_report)
    report["items_checked"] = len(checked)
    return checked, report

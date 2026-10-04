"""``make check-public``: refuse to ship personal data, raw text or secrets.

Walks the committed data folders, parses YAML and JSON (not grep only), and fails
on the strip-list conditions defined below. Exit code 1 lists every
finding; 0 means clean.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

from pipeline.ctgov import CAVEATS
from pipeline.denylist import denied_terms
from pipeline.schema import ALLOWED_HOSTS, Station, StudyKind

REPO = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("pipeline", "web/public")
SKIP_PARTS = {"node_modules", "__pycache__", ".venv", "tests", ".ruff_cache"}
SKIP_SUFFIXES = {".egg-info"}
DATA_SUFFIXES = {".yaml", ".yml", ".json"}
MAX_FILE_BYTES = 1_000_000
MAX_STRING_CHARS = 400
# Keys allowed past the length cap: a recorded PubMed search string is not prose.
LONG_TEXT_KEYS = {"esearch_term"}

# A key is forbidden if its lower-cased name contains one of these stems.
FORBIDDEN_KEY_STEMS = (
    "abstracttext",
    "abstract_text",
    "phr_text",
    "passages",
    "authorlist",
    "authors",
    "affiliation",
    "orcid",
    "official",
    "contacts",
    "pointofcontact",
    "contact_pi",
    "investigator",
    "program_officer",
    "descriptionmodule",
    "eligibilitycriteria",
    "curator",
    "contributor",
)
# Values that are ISO dates, datetimes or hex digests are never phone numbers.
DATE_OR_HASH_VALUE = re.compile(r"^(\d{4}-\d{2}-\d{2}([T ].*)?|[0-9a-f]{32,64})$")
FORBIDDEN_PATTERNS = {
    "abstract tag": re.compile(r"<abstract"),
    "e-mail": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}"),
    "email= query": re.compile(r"\bemail(?:=|%3D)", re.IGNORECASE),
    "api_key= query": re.compile(r"\bapi_key(?:=|%3D)", re.IGNORECASE),
    "JWT": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
}
# A phone number: optional +country, then digit groups joined by spaces, dots, dashes or
# parentheses, at least two separators. Dates, DOIs, NCT IDs and hashes do not match.
PHONE = re.compile(
    r"(?<![\w/.-])\+?\(?\d{2,4}\)?[\s.-]\d{2,4}[\s.-]\d{3,7}(?:[\s.-]\d{2,4})?(?![\w/-])"
)
# Values that look like a named person in a facility, stop-reason or model-text field: human check.
# Case-sensitive on purpose: "do" and "md" are words; "M.D." and "D.O." are titles.
PERSON_TITLE = re.compile(
    r"\b(?:Dr|Prof|dr|prof|DR|PROF)\.?\s|\b(?:M\.?D|m\.d|Ph\.?D|D\.O|MBBS|M\.B\.B\.S|P\.C|PLLC)\b\.?"
    r"|,\s*(?:DO|RN|NP|PA|FRCP|Pharm\.?D)\b"
)
PERSON_CHECK_KEYS = {
    "facility",
    "whystopped",
    "leadsponsor",
    "name",
    "window",
    "brieftitle",
    "studypopulation",
    "text",
    "proposal",
    "uncheckedreasoning",  # screen.json: list items keep the parent key
    "reason",
}
MARKUP_OR_LINK = re.compile(r"<[A-Za-z/]|https?://|www\.", re.I)
LINK_KEY = re.compile(r"(^\$schema$|url$|_page$|^link$)", re.I)  # keys that hold a link on purpose
SAFE_LINK = re.compile(
    r"^https://(" + "|".join(re.escape(h) for h in sorted(ALLOWED_HOSTS)) + r")(/|$)"
)
DIGIT_RUN = re.compile(r"(?<!\d)\d{10,15}(?!\d)")
# Files whose text is written by a model get the family deny-list as well. graph.json is scanned
# whole except the Level-2 paths below; screen.json except its verbatim and fixed-copy paths.
DENYLIST_FILES = {"texts.yaml": "family", "screen.json": "screen", "graph.json": "family"}
# Deny-list exemptions by (file, JSON path). screen.json: a registry's own stop reason, shown
# verbatim in quotes, and the plan's fixed interstitial and medication-warning copy in meta.
# graph.json: the researcher block of study records (drug names by design, Level 2 only) and
# their verbatim lines, claim quotes and paper titles
# (source text), search terms (what families type), co-listing windows and the recorded PubMed
# search, the record's own population line (verbatim, in quotes) and the stop reasons under
# "Tried before" (the sponsor's words, Level 2, always a human check).
DENYLIST_EXEMPT_PATHS = {
    "screen.json": re.compile(
        r"^\$\.(lines\[\d+\]\.cards\[\d+\]\.evidence\.studies\[\d+\]\.why_stopped"
        r"|meta\.(interstitial|medication_warning))$"
    ),
    "graph.json": re.compile(
        r"^\$\.(studies\[\d+\]\.(researcher\.|why_stopped$|study_population$)"
        r"|claims\[\d+\]\.evidence_quote$|papers\[\d+\]\.(title|journal)$"
        r"|aliases\[\d+\]\.term$|co_listings\[\d+\]\.(kind|matched_field|window)$"
        r"|meta\.esearch_term$|transfers\.[A-Za-z0-9_:]+\.transfers\[\d+\]\.study_population$"
        r"|funding\[\d+\]\.title$|mechanism_view\[\d+\]\.studies\.stopped\[\d+\]\.why_stopped$"
        r"|tried_before\.[a-z0-9_]+\[\d+\]\.why_stopped$)"
    ),
}
# Fixed copy that legitimately carries a denied stem (one home each; never model text): the
# co-listing captions, the station names and the study kinds.
FIXED_SENTENCES = (
    frozenset(CAVEATS.values()) | {s.value for s in Station} | {k.value for k in StudyKind}
)


def env_values() -> list[str]:
    """Secret values from .env (12+ chars) so a leaked literal is caught."""
    env = REPO / ".env"
    if not env.exists():
        return []
    values = []
    for line in env.read_text().splitlines():
        m = re.match(r"^(?:export +)?[A-Za-z_][A-Za-z0-9_]*=[\"']?([^\"' #]*)", line)
        if m and len(m.group(1)) >= 12:
            values.append(m.group(1))
    return values


def walk_strings(node: object, path: str = "$", key: str = "") -> list[tuple[str, str, str]]:
    """Yield (path, key, string) for every string in a parsed document."""
    found: list[tuple[str, str, str]] = []
    if isinstance(node, dict):
        for k, value in node.items():
            found.extend(walk_strings(value, f"{path}.{k}", str(k)))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found.extend(walk_strings(value, f"{path}[{i}]", key))
    elif isinstance(node, str):
        found.append((path, key, node))
    return found


def walk_keys(node: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(str(key))
            keys |= walk_keys(value)
    elif isinstance(node, list):
        for value in node:
            keys |= walk_keys(value)
    return keys


def forbidden_keys(keys: set[str]) -> list[str]:
    return sorted(k for k in keys if any(stem in k.lower() for stem in FORBIDDEN_KEY_STEMS))


def check_file(path: Path, secrets: list[str]) -> list[str]:
    problems: list[str] = []
    rel = path.relative_to(REPO) if path.is_relative_to(REPO) else path
    if path.stat().st_size > MAX_FILE_BYTES:
        problems.append(f"{rel}: larger than 1 MB")
    raw = path.read_text(errors="replace")
    for secret in secrets:
        if secret in raw:
            problems.append(f"{rel}: contains a literal value from .env")
    if path.suffix not in DATA_SUFFIXES:
        return problems
    try:
        doc = json.loads(raw) if path.suffix == ".json" else yaml.safe_load(raw)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        return problems + [f"{rel}: does not parse ({exc.__class__.__name__})"]
    for key in forbidden_keys(walk_keys(doc)):
        problems.append(f"{rel}: forbidden key '{key}'")
    which = DENYLIST_FILES.get(path.name)
    for where, key, text in walk_strings(doc):
        schema_doc = path.name.endswith(".schema.json") and key == "description"
        if len(text) > MAX_STRING_CHARS and key not in LONG_TEXT_KEYS and not schema_doc:
            problems.append(f"{rel}: string over {MAX_STRING_CHARS} chars at {where}")
        for name, pattern in FORBIDDEN_PATTERNS.items():
            if pattern.search(text):
                problems.append(f"{rel}: {name} at {where}")
        if not DATE_OR_HASH_VALUE.match(text) and PHONE.search(text):
            problems.append(f"{rel}: phone at {where}")
        plain_key = key.lower().replace("_", "")
        if plain_key in PERSON_CHECK_KEYS and PERSON_TITLE.search(text):
            problems.append(f"{rel}: person title in '{key}' at {where} (human check)")
        if LINK_KEY.search(key) and key != "$schema":
            if not SAFE_LINK.match(text):
                problems.append(
                    f"{rel}: link not https on an allow-listed host in '{key}' at {where}"
                )
        elif not LINK_KEY.search(key) and MARKUP_OR_LINK.search(text):
            problems.append(f"{rel}: markup or link in '{key}' at {where}")
        if not DATE_OR_HASH_VALUE.match(text) and DIGIT_RUN.search(text):
            problems.append(f"{rel}: long digit run in '{key}' at {where}")
        exempt = DENYLIST_EXEMPT_PATHS.get(path.name)
        if which and not (exempt and exempt.match(where)) and text not in FIXED_SENTENCES:
            for term in denied_terms(text, which):
                problems.append(f"{rel}: denied word '{term}' at {where}")
    return problems


def scan_paths() -> list[Path]:
    paths: list[Path] = []
    for folder in SCAN_DIRS:
        root = REPO / folder
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            parts = path.relative_to(REPO).parts
            skipped = (
                SKIP_PARTS & set(parts) and "golden" not in parts
            )  # golden files are site data
            if (
                path.is_file()
                and not skipped
                and not any(p.endswith(tuple(SKIP_SUFFIXES)) for p in parts)
            ):
                paths.append(path)
    return paths


def main() -> int:
    secrets = env_values()
    problems: list[str] = []
    for path in scan_paths():
        problems.extend(check_file(path, secrets))
    # The raw-HTML rule is checked where a call site would live: our own source. React DOM's
    # bundle contains the literal in its property table, so a built bundle can never be clean.
    web_src = REPO / "web" / "src"
    if web_src.exists():
        for path in web_src.rglob("*"):
            if path.suffix in (".ts", ".tsx", ".js", ".jsx") and (
                "dangerouslySetInnerHTML" in path.read_text(errors="replace")
            ):
                problems.append(f"{path.relative_to(REPO)}: dangerouslySetInnerHTML in web source")
    for problem in problems:
        print(problem)
    print(f"check-public: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

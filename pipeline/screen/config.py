"""Fixed facts and fixed copy the researcher screen is built from: nothing here is a count or an ID.

The gene family, the action-type → effect map and the direction rule are code, not model
output. Anything not mapped is ``unclear`` and is filtered out (fail closed). The copy below
is the project's fixed wording for the researcher view; it is emitted into
``screen.json`` → ``meta`` so the file labels itself wherever it is opened.
"""

from __future__ import annotations

# Voltage-gated sodium channel alpha subunits (Nav1.1–Nav1.9). SCN7A (Nax) is not voltage-gated
# and is left out. A drug is "in the family" when one of its mechanisms of action lists one of
# these genes as a target.
SODIUM_CHANNEL_FAMILY: frozenset[str] = frozenset(
    {"SCN1A", "SCN2A", "SCN3A", "SCN4A", "SCN5A", "SCN8A", "SCN9A", "SCN10A", "SCN11A"}
)
FAMILY_BY_MECHANISM: dict[str, frozenset[str]] = {"sodium_channel": SODIUM_CHANNEL_FAMILY}
FAMILY_LABEL = "voltage-gated sodium channel alpha subunits"
# Open Targets lists a mechanism against the protein family, not against one gene.
TARGET_LEVEL = "protein_family"

# The only lines the screen runs for, with their
# genes, so a line that is not in graph.json yet is still listed as refused with its reason.
SCREEN_LINE_GENES: dict[str, str] = {
    "scn2a_gain": "SCN2A",
    "scn2a_loss": "SCN2A",
    "scn8a_dee": "SCN8A",
    "dravet": "SCN1A",
}
SCREEN_LINE_KEYS: tuple[str, ...] = tuple(SCREEN_LINE_GENES)
# Label and gloss for a scope line that is not in graph.json yet (listed as refused).
SCREEN_LINE_LABELS: dict[str, str] = {
    "scn2a_gain": "SCN2A gain of function",
    "scn2a_loss": "SCN2A loss of function",
    "scn8a_dee": "SCN8A developmental and epileptic encephalopathy",
    "dravet": "Dravet syndrome (SCN1A)",
}
ABSENT_LINE_GLOSS = "not in the shipped graph file yet"

# Open Targets action types -> effect on the channel. Unmapped -> "unclear" -> removed.
EFFECT_BY_ACTION: dict[str, str] = {
    "BLOCKER": "reduces",
    "INHIBITOR": "reduces",
    "ANTAGONIST": "reduces",
    "NEGATIVE ALLOSTERIC MODULATOR": "reduces",
    "NEGATIVE MODULATOR": "reduces",
    "INVERSE AGONIST": "reduces",
    "OPENER": "increases",
    "ACTIVATOR": "increases",
    "AGONIST": "increases",
    "PARTIAL AGONIST": "increases",
    "POSITIVE ALLOSTERIC MODULATOR": "increases",
    "POSITIVE MODULATOR": "increases",
}
# The direction filter: a gain line keeps drugs that reduce channel activity, a loss line
# keeps drugs that increase it. A code rule, never a safety judgement.
KEEP_EFFECT: dict[str, str] = {"gain": "reduces", "loss": "increases"}

# Open Targets clinical stages that count as "approved medicine".
APPROVED_STAGES: frozenset[str] = frozenset({"APPROVAL"})

# The fixed next-test list. The model chooses one; it never writes its own.
NEXT_TESTS: tuple[str, ...] = (
    "heterologous_channel_assay",
    "patient_derived_neuron_electrophysiology",
    "mouse_model_seizure_assay",
    "literature_review_first",
)
NEXT_TEST_LABELS: dict[str, str] = {
    "heterologous_channel_assay": (
        "Patch-clamp assay of the patient variant expressed in a cell line, with and without the "
        "compound"
    ),
    "patient_derived_neuron_electrophysiology": (
        "Electrophysiology in patient-derived neurons carrying the variant"
    ),
    "mouse_model_seizure_assay": (
        "Seizure read-out in a mouse model carrying a variant of this direction"
    ),
    "literature_review_first": "A systematic literature review before any laboratory experiment",
}

# The fixed kinds a doubt may carry. The model picks one; anything else becomes "other".
DOUBT_KINDS: tuple[str, ...] = (
    "no_direction_in_source",
    "different_gene_of_family",
    "different_variant_direction",
    "model_system_or_species",
    "not_a_drug_test",
    "other",
)
DOUBT_KIND_LABELS: dict[str, str] = {
    "no_direction_in_source": "The source does not say which direction the variant has",
    "different_gene_of_family": "The source concerns another gene of the family",
    "different_variant_direction": "The source concerns variants of the other direction",
    "model_system_or_species": "The source is a model system or another species",
    "not_a_drug_test": "The source did not test the medicine",
    "other": "Another limitation",
}
# What the model was given to read. Titles only: no abstracts, no full texts.
EVIDENCE_READ = "title only"

# Drug names that are not approved medicines (so not in the approved-name list) but appear in
# this slice's trials and papers. A model sentence naming any of them is rejected.
OTHER_DRUG_BLOCKLIST: tuple[str, ...] = (
    "cannabidiol",
    "fenfluramine",
    "stiripentol",
    "clobazam",
    "valproate",
    "valproic acid",
    "soticlestat",
    "ganaxolone",
    "relutrigine",
    "elsunersen",
    "retigabine",
    "ezogabine",
    "memantine",
    "ataluren",
    "vixotrigine",
    "prax-562",
    "prax-222",
    "prax-628",
    "xen496",
    "xen1101",
    "nbi-921352",
    "cap-002",
    "bia 2-093",
)

# Words a model sentence may not contain even though the shared SCREEN deny-list allows them:
# lay dosing and home-use wording (checked on model sentences only; meta copy may say "parent
# molecule").
MODEL_SENTENCE_DENIED: tuple[str, ...] = (
    "tablet",
    "capsule",
    "daily",
    "twice",
    "nightly",
    "bedtime",
    "morning",
    "at home",
    "parent",
    "child",
    "children",
    "family member",
    "patient",
    "infant",
    "baby",
    "toddler",
    "kid",
    "milligram",
    "microgram",
    "gram",
    "per kg",
    "give",
    "giving",
    "take",
    "taking",
    "administer",
    "tolerat",
    "first-line",
    "neurologist",
    "doctor",
    "physician",
    "benefit",
    "control seizures",
    "controls seizures",
    "dot org",
    "dot com",
)
# Model names and run-id shapes the provenance may carry (identifiers, never prose).
PROVENANCE_MODELS: frozenset[str] = frozenset({"gpt-6-astra", "gpt-oss-20b"})
# Short abbreviations after which a full stop does not end a sentence.
NOT_SENTENCE_END: frozenset[str] = frozenset(
    {"dr", "prof", "st", "mr", "ms", "mrs", "vs", "al", "e.g", "i.e", "fig", "no", "cf"}
)
# Tokens the model may write in any case without them being a fact of the card.
ALWAYS_ALLOWED_TOKENS: frozenset[str] = frozenset(
    {
        "pubmed",
        "pmid",
        "nct",
        "open",
        "targets",
        "clinicaltrials",
        "chembl",
        "nav",
        "hek293",
        "hek293t",
        "cho",
        "xenopus",
        # ordinary science words the medicine-suffix and trade-name rules would otherwise hit
        "peptide",
        "polypeptide",
        "nucleotide",
        "oligonucleotide",
        "oligonucleotides",
        "amide",
        "murine",
        "today",
    }
)

# Approved "medicines" that are also ordinary words of a mechanism note (elements, gases,
# solvents, ions, endogenous molecules). Left out of the other-drug rule; everything else in
# the approved list blocks a sentence.
GENERIC_SUBSTANCES: frozenset[str] = frozenset(
    {
        "water",
        "oxygen",
        "nitrogen",
        "xenon",
        "talc",
        "sodium",
        "potassium",
        "calcium",
        "magnesium",
        "chloride",
        "copper",
        "zinc",
        "iron",
        "sulfur",
        "urea",
        "alcohol",
        "glucose",
        "glycine",
        "glutamate",
        "gaba",
        "dopamine",
        "serotonin",
        "histamine",
        "adenosine",
        "acetylcholine",
        # trade names that are ordinary English or science words
        "murine",
        "today",
        "choice",
        "success",
        "legend",
        "optimum",
        "sigma",
        "android",
        "depot",
        "balance",
        "clear",
        "focus",
        "relief",
        "total",
    }
)

MAX_CARDS_PER_LINE = 10
MAX_PMIDS_PER_PAIR = 5
MAX_SENTENCE_CHARS = 400
MAX_TITLE_CHARS = 200  # paper titles shown to the model are cut here
RULE_VERSION = "screen-rules-2"
CRITIQUE_STEP = "critique_candidates"

# Fixed copy (plan wording). The page renders these from meta; it never writes its own.
INTERSTITIAL = (
    "This page lists approved medicines that a computer filter matched to a protein mechanism. "
    "They are untested ideas for laboratory research, not treatments. Nothing here applies to "
    "any child's care. Never start, stop or change a medicine without your child's neurologist."
)
INTERSTITIAL_CONTINUE = "I'm a researcher, continue"
INTERSTITIAL_BACK = "Back to the family view"
HYPOTHESIS_LABEL = "Hypothesis for laboratory testing, not medical advice"
ALREADY_STUDIED_CAPTION = "Already studied for this gene: not a new idea"
TARGET_CAPTION = (
    "Open Targets lists these mechanisms against the sodium-channel family, not against a "
    "single gene; the family genes of each mechanism are shown as targets."
)
ORDERING_RULE = (
    "ordered by a fixed rule (number of papers pairing drug and gene, then name), not by "
    "expected benefit"
)
CARDS_NOT_SHOWN_REASON = (
    "Cards are capped at {cap} per line in the fixed order; the {n} not shown passed the same "
    "filter and come later in that order, so they have the same number of papers pairing them "
    "with the gene or fewer (ties are broken by name)."
)
NEW_CANDIDATES_NOTE = (
    "new_candidates counts the medicines that passed the direction filter and are not already "
    "paired with the gene by a paper or study; new_candidates_on_line_gene counts those whose "
    "Open Targets mechanism lists the line's own gene; the rest are listed on other family "
    "genes only, and some have no reference at all (see without_paper)."
)
SANITY_CHECK_NOTE = (
    "already_tried_total counts the approved family medicines that a paper or registered study "
    "already pairs with the gene, before the direction filter; surfaced counts those among the "
    "medicines that passed it."
)
FAMILY_COVERAGE_NOTE = (
    "Open Targets {release} lists some approved medicines without a mechanism-of-action row; "
    "such a medicine is counted in the approved total but cannot enter the family pool, so "
    "the family count is a lower bound."
)
# Reason code -> the sentence a reader sees when a card has no model notes. Reader language
# only: no commands, no file or target names (a test enforces it).
CRITIQUE_REASONS: dict[str, str] = {
    "no_run": "No model notes for this medicine in this build.",
    "rejected_by_code_check": (
        "The model's notes for this medicine did not pass the checks, so they are not shown."
    ),
    "no_item": "No model notes for this medicine in this build.",
    "facts_changed": (
        "The model's notes for this medicine were written before the facts were last updated, "
        "so they are not shown."
    ),
}
PUBMED_QUERY_NOTE = (
    "Each pair is searched once with the Open Targets preferred name and the bare gene symbol "
    "in title or abstract; synonyms, brand names and protein names such as Nav1.2 are not "
    "searched, so paper counts are lower bounds."
)
REMOVED_COUNTS_NOTE = (
    "The count outside the channel family is the approved total minus the family count, not a "
    "per-drug filter; the direction and action counts are per drug. Removed medicines are "
    "counted, never named."
)
FAMILY_DIRECTION_NOTE = (
    "Of the {family} approved medicines listed on this channel family, {reduces} reduce channel "
    "activity, {increases} increase it and {unclear} have no mapped direction; a "
    "loss-of-function line can pass only medicines that increase activity."
)
DIRECTION_FILTER_NOTE = (
    "The direction filter is a code rule matching each medicine's listed action type to the "
    "line's variant direction. It judges neither risk nor benefit and says nothing about any "
    "patient."
)
SOURCES = (
    "Drug and mechanism data: Open Targets Platform (CC0 1.0), which includes ChEMBL (EMBL-EBI)",
    "Approved-medicine id list: ChEMBL molecule endpoint (CC BY-SA 3.0), ids only",
    "Papers pairing drug and gene: PubMed (NLM) E-utilities, titles only",
    "Registered studies: ClinicalTrials.gov API v2",
)

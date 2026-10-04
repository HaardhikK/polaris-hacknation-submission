from pipeline.denylist import FAMILY, SCREEN, denied_terms


def test_family_catches_drug_names_and_promises():
    text = "Carbamazepine is safe and will help; you are eligible to enrol."
    assert denied_terms(text) == ["carbamazepine", "safe", "will help", "eligible", "enrol"]


def test_family_catches_inflections_plurals_and_abbreviations():
    text = (
        "Sodium channel blockers and ASOs are safely used; enrolling is recommended "
        "once diagnosed, a clinically-proven, FDA-validated and curative option."
    )
    found = denied_terms(text)
    for word in (
        "sodium channel blockers",
        "asos",
        "safely",
        "enrolling",
        "recommended",
        "diagnosed",
        "proven",
        "validated",
        "curative",
    ):
        assert word in found, word


def test_family_matches_whole_words_only():
    assert denied_terms("A safeguard, unsafe wiring, and a curated list.") == []
    assert denied_terms("Not a cure.") == ["cure"]


def test_screen_is_stricter_than_family_on_advice_words():
    text = "Promising treatments; stop the dose of 10mg and avoid treating."
    found = denied_terms(text, "screen")
    for word in ("promising", "treatments", "stop", "dose", "mg", "avoid", "treating"):
        assert word in found, word
    assert denied_terms(text, "family") == []


def test_clean_family_sentence_passes():
    sentence = (
        "SCN2A loss of function: the channel works too weakly. "
        "Registries and care networks can still be shared."
    )
    assert denied_terms(sentence) == []


def test_lists_have_no_duplicates():
    assert len(set(FAMILY)) == len(FAMILY)
    assert len(set(SCREEN)) == len(SCREEN)


def test_family_catches_development_codes_by_shape():
    assert denied_terms("The study of TAK-935 and PRAX-562 was stopped.") == ["tak-935", "prax-562"]
    assert denied_terms("XEN496 and ABC-1234 are codes.") == ["xen496", "abc-1234"]
    # identifiers that are not codes: NCT and PMID numbers, HPO and Orphanet ids, gene symbols
    assert denied_terms("NCT05818553, PMID 34287911, HP:0001250, ORPHA:1934, KCNQ2-related.") == []
    assert denied_terms("COVID-19 and SARS-CoV-2; CC BY 4.0.", "family") == []
    assert denied_terms("Mouse lines JAX-021967, MMRRC-050622 and RBRC-09420; ISO-9001.") == []
    assert denied_terms("TAK-935 shows no toxicity", "screen") == []  # the screen names medicines

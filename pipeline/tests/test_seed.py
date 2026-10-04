"""The committed seed loads clean, and the rules that make it safe hold."""

import shutil
from datetime import date

import pytest
import yaml
from pydantic import ValidationError

from pipeline.fetch import RAW
from pipeline.schema import (
    Alias,
    AliasKind,
    Asset,
    AssetType,
    Direction,
    DirectionBasis,
    Scope,
    Source,
    Station,
)
from pipeline.seed_check import SEED, check_references, load_seed

SPLIT_GENES = {"SCN2A", "SCN8A", "SCN1A"}


def real(problems: list[str]) -> list[str]:
    return [p for p in problems if not p.startswith("skipped:")]


def test_committed_seed_loads_and_every_reference_resolves():
    seed, problems = load_seed(SEED)
    assert problems == []
    assert real(check_references(seed, SEED)) == []
    assert {line.key for line in seed.lines} == {
        "scn2a_gain",
        "scn2a_loss",
        "syngap1",
        "scn8a_dee",
        "dravet",
        "stxbp1",
        "cdkl5",
    }


def test_split_gene_names_and_ids_never_lead_to_a_line():
    seed, _ = load_seed(SEED)
    for alias in seed.aliases:
        if alias.gene in SPLIT_GENES and alias.kind in (AliasKind.GENE, AliasKind.ID):
            assert alias.direction_step and alias.line is None, alias.term
        if alias.line and alias.kind in (AliasKind.GENE, AliasKind.ID):
            gene = next(ln.gene for ln in seed.lines if ln.key == alias.line)
            assert gene not in SPLIT_GENES, alias.term  # a gene name or ID never picks a line
    for term in ("OMIM:613721", "MONDO:1060245", "SCN2A", "SCN8A", "SCN1A"):
        alias = next(a for a in seed.aliases if a.term == term)
        assert alias.direction_step
    for term in ("ORPHA:1934", "ORPHA:178469", "ORPHA:306"):
        alias = next(a for a in seed.aliases if a.term == term)
        assert alias.kind is AliasKind.GROUP and alias.genes, term
        assert alias.group_size > len(alias.genes), term  # the picker always has an exit
    orpha_442835 = next(a for a in seed.aliases if a.term == "ORPHA:442835")
    assert orpha_442835.kind is AliasKind.GROUP and "SYNGAP1" not in orpha_442835.genes
    assert next(a for a in seed.aliases if a.term == "Dravet syndrome").line == "dravet"


def test_gene_scope_assets_are_shared_and_gated_types_are_line_scoped():
    seed, _ = load_seed(SEED)
    for asset in seed.assets:
        if asset.scope is Scope.GENE:
            assert asset.owner_line is None, asset.id
        if asset.owner_gene in SPLIT_GENES and asset.type in {AssetType.TRIAL, AssetType.MODEL}:
            assert asset.scope is Scope.LINE, asset.id
            # a known direction needs its basis; "unknown" fails the gate on purpose
            assert asset.direction_basis is not None or asset.direction.value == "unknown", asset.id


def test_scn2a_loss_hpo_terms_are_labelled_as_polaris_annotations():
    seed, _ = load_seed(SEED)
    loss = next(line for line in seed.lines if line.key == "scn2a_loss")
    assert 5 <= len(loss.hpo_terms) <= 8
    for term in loss.hpo_terms:
        assert term.annotation.startswith("Polaris annotation")


def test_unfetched_pages_carry_no_verification_date():
    seed, _ = load_seed(SEED)
    for asset in seed.assets:
        host = asset.source.url.host
        if host not in {"clinicaltrials.gov", "pubmed.ncbi.nlm.nih.gov"}:
            assert asset.source.retrieved is None and asset.last_verified is None, asset.id
    for org in seed.organisations:
        assert org.last_verified is None


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/x",
        "http://clinicaltrials.gov/x",
        "https://evil.com@clinicaltrials.gov/",
        "https://clinicaltrials.gov:8443/x",
        "https://pubmed.ncbi.nlm.nih.gov/?term=maria+smith",
        "https://clinicaltrials.gov/study/NCT1#frag",
    ],
)
def test_source_rejects_unsafe_urls(url):
    with pytest.raises(ValidationError):
        Source(label="x", url=url, retrieved=date(2026, 10, 4))


def test_source_label_id_must_match_url():
    with pytest.raises(ValidationError, match="label cites"):
        Source(label="PMID 1", url="https://pubmed.ncbi.nlm.nih.gov/2/")
    with pytest.raises(ValidationError, match="label cites"):
        Source(label="PMID 3428791", url="https://pubmed.ncbi.nlm.nih.gov/34287911/")
    Source(label="MMRRC", url="https://www.mmrrc.org/catalog/sds.php?mmrrc_id=69939")


def test_alias_leads_to_exactly_one_target():
    Alias(term="SCN2A", kind=AliasKind.GENE, gene="SCN2A", direction_step=True)
    with pytest.raises(ValidationError, match="exactly one target"):
        Alias(term="x", kind=AliasKind.DISEASE, line="syngap1", direction_step=True, gene="SCN2A")
    with pytest.raises(ValidationError, match="channel gene"):
        Alias(term="SYNGAP1", kind=AliasKind.GENE, gene="SYNGAP1", direction_step=True)
    with pytest.raises(ValidationError, match="gene, pmid and a line"):
        Alias(term="R853Q", kind=AliasKind.VARIANT, line="scn2a_loss", pmid="34287911")
    # a variant whose assays disagree has no line: it leads to the "Sources disagree" state
    Alias(
        term="SCN2A C258R",
        kind=AliasKind.VARIANT,
        gene="SCN2A",
        pmid="42774767",
        variant_direction=Direction.MIXED,
    )
    with pytest.raises(ValidationError, match="variant with no line"):
        Alias(
            term="x",
            kind=AliasKind.VARIANT,
            gene="SCN2A",
            pmid="1",
            line="scn2a_loss",
            variant_direction=Direction.LOSS,
        )
    # a symptom shared by several genes opens the picker; one gene uses gene, not genes
    Alias(term="Seizure", kind=AliasKind.SYMPTOM, genes=["SCN2A", "SYNGAP1"], hpo_id="HP:0001250")
    with pytest.raises(ValidationError, match="uses gene, not genes"):
        Alias(term="Seizure", kind=AliasKind.SYMPTOM, genes=["SCN2A"], hpo_id="HP:0001250")
    with pytest.raises(ValidationError, match="channel mechanism"):
        Alias(term="x", kind=AliasKind.MECHANISM, mechanism="ras_gap", direction=Direction.LOSS)
    with pytest.raises(ValidationError, match="list genes"):
        Alias(term="x", kind=AliasKind.ID, genes=["SCN2A"])
    with pytest.raises(ValidationError, match="fewer seeded genes"):
        Alias(term="x", kind=AliasKind.GROUP, orpha="ORPHA:1", group_size=2, genes=["A1", "B1"])


SOURCE = Source(label="JAX", url="https://www.jax.org/strain/029303")


def asset(**overrides) -> Asset:
    base = dict(
        id="a",
        type=AssetType.REGISTRY,
        station=Station.REGISTRY,
        scope=Scope.GENE,
        owner_gene="SCN2A",
        label="x",
        source=SOURCE,
    )
    return Asset.model_validate({**base, **overrides})


def test_channel_gene_gated_assets_cannot_hide_in_gene_scope():
    with pytest.raises(ValidationError, match="line and direction"):
        asset(type=AssetType.MODEL, station=Station.MODEL, direction=Direction.UNKNOWN)
    with pytest.raises(ValidationError, match="line and direction"):
        asset(
            type=AssetType.TRIAL, station=Station.TRIAL, scope=Scope.LINE, owner_line="scn2a_gain"
        )
    with pytest.raises(ValidationError, match="direction_basis"):
        asset(
            type=AssetType.TRIAL,
            station=Station.TRIAL,
            scope=Scope.LINE,
            owner_line="scn2a_gain",
            direction=Direction.GAIN,
        )
    assert asset(
        type=AssetType.MODEL,
        station=Station.MODEL,
        scope=Scope.LINE,
        owner_line="scn2a_gain",
        direction=Direction.UNKNOWN,
    )
    assert asset(
        type=AssetType.TRIAL,
        station=Station.TRIAL,
        scope=Scope.LINE,
        owner_line="scn2a_gain",
        direction=Direction.GAIN,
        direction_basis=DirectionBasis.ONSET_PROXY,
    )


def test_non_channel_assets_carry_no_direction():
    asset(owner_gene="SYNGAP1", type=AssetType.MODEL, station=Station.MODEL)
    with pytest.raises(ValidationError, match="only to channel-gene"):
        asset(owner_gene="SYNGAP1", direction=Direction.LOSS)


# --- check_references, one negative case per branch -------------------------------------


@pytest.fixture
def seed_copy(tmp_path):
    for path in SEED.iterdir():
        shutil.copy(path, tmp_path / path.name)
    return tmp_path


def edit(folder, name, fn):
    path = folder / name
    rows = yaml.safe_load(path.read_text())
    fn(rows)
    path.write_text(yaml.safe_dump(rows, allow_unicode=True))


def problems_after(folder, name, fn):
    edit(folder, name, fn)
    seed, load_problems = load_seed(folder)
    return load_problems + real(check_references(seed, folder, RAW))


def test_unknown_organisation_and_asymmetry_are_reported(seed_copy):
    problems = problems_after(
        seed_copy, "lines.yaml", lambda rows: rows[2]["organisations"].append("nobody")
    )
    assert any("unknown organisation 'nobody'" in p for p in problems)
    problems = problems_after(
        seed_copy, "organisations.yaml", lambda rows: rows[1]["lines"].append("scn2a_gain")
    )
    assert any("line scn2a_gain does not list it back" in p for p in problems)


def test_unlisted_pmid_and_nct_are_reported(seed_copy):
    problems = problems_after(
        seed_copy, "lines.yaml", lambda rows: rows[1]["hpo_terms"][0].__setitem__("pmid", "1")
    )
    assert any("PMID 1 not in pmids.txt" in p for p in problems)
    problems = problems_after(
        seed_copy, "studies.yaml", lambda rows: rows[0].__setitem__("nct", "NCT00000001")
    )
    assert any("NCT00000001: not in ncts.txt" in p for p in problems)


def test_asset_owner_mismatches_are_reported(seed_copy):
    def wrong_gene(rows):
        row = next(r for r in rows if r["id"] == "embold_trial")
        row["owner_gene"] = "SCN8A"

    problems = problems_after(seed_copy, "assets.yaml", wrong_gene)
    assert any("owner_gene differs from line scn2a_gain" in p for p in problems)

    def wrong_direction(rows):
        row = next(r for r in rows if r["id"] == "embold_trial")
        row["direction"] = "loss"

    problems = problems_after(seed_copy, "assets.yaml", wrong_direction)
    assert any("direction differs from line scn2a_gain" in p for p in problems)


def test_split_gene_line_cannot_be_reached_by_a_non_variant_alias(seed_copy):
    problems = problems_after(
        seed_copy,
        "aliases.yaml",
        lambda rows: rows.append({"term": "x", "kind": "id", "line": "scn2a_gain"}),
    )
    assert any("never leads to a line" in p for p in problems)


@pytest.mark.skipif(not (RAW / "hpo" / "hp.obo").exists(), reason="needs make fetch")
def test_wrong_hpo_label_is_reported(seed_copy):
    problems = problems_after(
        seed_copy,
        "lines.yaml",
        lambda rows: rows[1]["hpo_terms"][0].__setitem__("label", "Hypotonia"),
    )
    assert any("HP:0001250 is 'Seizure', not 'Hypotonia'" in p for p in problems)


@pytest.mark.skipif(not (RAW / "orphadata" / "en_product6.xml").exists(), reason="needs make fetch")
def test_group_alias_gene_must_be_in_the_orphanet_entry(seed_copy):
    row = {
        "term": "x",
        "kind": "group",
        "orpha": "ORPHA:442835",
        "group_size": 2,
        "genes": ["SYNGAP1"],
    }
    problems = problems_after(seed_copy, "aliases.yaml", lambda rows: rows.append(row))
    assert any("ORPHA:442835 has no disease-causing SYNGAP1" in p for p in problems)
    assert any("group_size 2 but ORPHA:442835 has" in p for p in problems)

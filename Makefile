# Polaris build pipeline. Everything runs from the repo's own .venv and node_modules.
# Targets that a later phase implements fail loudly until then, so nothing passes by accident.
# The Makefile never includes or exports .env; only Python loads it.

PY := .venv/bin/python
CODEX_RUN := pipeline/codex_run.sh

.PHONY: test lint format fetch validate caches build transfers golden check-public report extract reconcile explain codex-dry-run consistency reporter-fetch

test:
	$(PY) -m pytest -q pipeline/tests

lint:
	$(PY) -m ruff check pipeline
	$(PY) -m ruff format --check pipeline

format:
	$(PY) -m ruff format pipeline
	$(PY) -m ruff check --fix pipeline

check-public:
	$(PY) -m pipeline.check_public

# Proves the Codex recipe end to end on a toy input: no tools, strict schema, clean events log.
codex-dry-run:
	$(CODEX_RUN) dry_run pipeline/prompts/dry_run.input.json data/raw/codex-runs/dry_run.out.json
	$(PY) -c "import json; d=json.load(open('data/raw/codex-runs/dry_run.out.json')); assert {i['id'] for i in d['items']}=={'a','b'}, d; print('dry run ok:', d)"

# Downloads the public inputs by the committed ID lists into data/raw/ and work/ (both gitignored).
# `make fetch SOURCES="pubmed ctgov"` limits it to some sources.
fetch:
	$(PY) -m pipeline.fetch $(SOURCES)

# Seed check + claim check + cache staleness. `make validate STRICT=1` (freeze) also fails on
# skipped checks and on rows a person has not yet dated.
validate:
	STRICT=$(STRICT) $(PY) -m pipeline.seed_check
	$(PY) -m pipeline.validate
	$(PY) -c "from pipeline.build import caches_are_current as c; s = c(); print('caches:', 'current' if not s else 'STALE ' + ', '.join(s)); raise SystemExit(1 if s else 0)"
	$(PY) -c "from pipeline.graph import graph_is_current as c; s = c(); print('graph:', 'current' if not s else 'STALE ' + ', '.join(s)); raise SystemExit(1 if s else 0)"

# Codex handoff 1: abstracts -> proposed claims (unsigned), then the validator. N limits the PMIDs.
# SECTION="Later lines" (Codex handoff 4) appends one batch for that pmids.txt section's PMIDs that
# no committed batch holds yet; existing batches are never touched.
extract:
	SECTION="$(SECTION)" $(PY) -m pipeline.extract $(N)
	$(PY) -m pipeline.validate $(if $(N),work/extract/claims_smoke.yaml,)

# Codex handoff 2: seeded names -> identifier proposals, each checked against the downloaded files.
reconcile:
	$(PY) -m pipeline.reconcile

# Direction evidence per line, with the level of checking each rests on.
report:
	$(PY) -m pipeline.report

# Committed caches under pipeline/cache/ from the fetched data and the validator (needs make fetch):
# stripped study records + co_listed_in edges, accepted claims, paper nodes, symptom terms, sources.
caches:
	$(PY) -m pipeline.build

# web/public/graph.json + pipeline/graph.schema.json from committed files only (seed, pipeline/cache/,
# seed/texts.yaml). Byte-reproducible: `make build && git diff --exit-code web/public/graph.json`.
build:
	$(PY) -m pipeline.graph

# Consistency check: EMBOLD held out in time; does the rule name the gene EMBOLD names? (n=1)
consistency:
	$(PY) -m pipeline.consistency

# NIH RePORTER (keyless): project records per seeded gene into data/raw/reporter/ (make caches strips them).
reporter-fetch:
	$(PY) -m pipeline.reporter

# The transfer decision for one line, as the site will show it.
transfers:
	$(PY) -m pipeline.transfer $(LINE)

# The demo card as the engine computes it now, diffed against the reviewed golden file. Copy the
# candidate over the golden file only after reading the diff: the golden file is a reviewed artefact.
golden:
	$(PY) -c "import json; from pipeline.seed_check import load_seed; from pipeline.transfer import card, load_accepted_claims, summary; s,_=load_seed(); json.dump(summary(card('scn2a_loss', s, load_accepted_claims())), open('work/golden_candidate.json','w'), indent=1)"
	-diff -u pipeline/tests/golden/scn2a_loss_transfers.json work/golden_candidate.json && echo "golden: no change"
	@echo "candidate written to work/golden_candidate.json"

# Codex handoff 3: the facts of the demo-path cards -> plain-language texts, each post-checked with the
# family deny-list; a text that fails falls back to the template. Writes pipeline/seed/texts.yaml.
explain:
	$(PY) -m pipeline.explain

# --- Researcher screen (B6, data side): pipeline/screen/ -> web/public/screen.json -------------
.PHONY: screen-fetch screen-batches critique screen

# Network: the Open Targets drug pool, then PubMed and ClinicalTrials.gov evidence per drug x gene,
# into pipeline/screen/cache/ (allow-listed fields, release + retrieved) and gitignored data/raw/screen/.
screen-fetch:
	$(PY) -m pipeline.screen.opentargets
	$(PY) -m pipeline.screen.evidence

# One Codex input per screened line (facts only, wrapped as data) under work/screen/.
screen-batches:
	$(PY) -c "from pipeline.screen import build, funnel; from pipeline.screen.batches import write_batch; g=build.load_graph(); p=build.load_pool(); e=build.load_evidence(); ls,_=build.screen_lines(g); [print(write_batch(r, e.get('titles', {}))) for r in (funnel.screen_line(l, p, e) for l in ls) if r['status']=='screened' and r['cards']]"

# Codex handoff 5: one codex_run.sh call per screened line, post-checked, into pipeline/screen/cache/critique.json.
critique:
	$(PY) -m pipeline.screen.critique

# screen.json from committed caches only: no network, no model; refuses mock or test inputs.
screen:
	$(PY) -m pipeline.screen.build

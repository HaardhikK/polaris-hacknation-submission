<!-- Authored by: Haardhik · Last updated: 2026-10-04 -->
# Polaris

**Polaris shows a rare-disease community which research another community already built that it can borrow, and which look-alikes it must not, with the paper that says why.**

Hack-Nation 7, Challenge 05 (OpenAI × Buffalo Initiative), Dresden hub, 3 to 4 October 2026.

| | |
|---|---|
| Live site | https://hacknation-ivory.vercel.app/ |
| Demo video (1 minute) | _link added at submission_ |
| Technical video (how the dataset was made) | _link added at submission_ |
| Team video | _link added at submission_ |

> Research-planning tool. **Not medical advice.** Do not change treatment based on this site. Nothing here applies to any child's care.

## The problem
Every rare-disease community needs the same seven things before a treatment is possible: a diagnosis, a registry, a natural-history study, an understood mechanism, a lab model, a way to measure improvement, and a trial. Communities are organised by disease name, so a group rarely learns that a neighbour already built the step it is missing. Some neighbours are false friends: in genes such as SCN2A, one variant makes an ion channel work too strongly (gain of function) and another too weakly (loss of function). Same gene, opposite problem, opposite drug effect. Polaris links communities by mechanism and direction instead of by name, says what can be shared, blocks what cannot, and cites the sentence from the paper for every decision.

## What you see
- **Intro.** A short constellation animation lands on the wordmark and hands over to the map.
- **One search.** A single box takes a disease, gene, variant (`R853Q` or `p.Arg853Gln`), organisation, mechanism or symptom, resolved through a committed alias table with synonyms and identifiers. For SCN2A, SCN8A and SCN1A the site first asks **"Which direction?"**, because the answer depends on the variant. A search outside the slice gets an honest "not mapped yet" state.
- **The condition page**, in four tabs:
  - **Your condition**: the variant line with its cited lab study, the mechanism in plain words, and the steps the community already has.
  - **Share or block**: what can and cannot be shared with each look-alike, the block banner ("Same gene, opposite problem") and the studies that already list both conditions.
  - **Borrow**: cards for what another community built, each one plain sentence first, then "Why we think this" (quotes, PMIDs, provenance, what differs, what to check first), then "For researchers" (earlier studies with the sponsor's own stop reasons, funded projects).
  - **Next steps**: who already built the missing step and how to reach them through organisation pages and study records.
- **The map.** A 3D graph of the seven communities, their organisations, studies, papers and shared resources. The map animates to the searched condition's subgraph; click any node or edge and the panel explains it: relationship, source, identifier, how it was checked, and the date (or "date not checked" for pages the pipeline did not fetch).
- **Evidence index.** Every piece of evidence on the map in one list, each with its source and date.
- **About.** Method, the consistency check, how the map grows, sources and limitations.
- **Researcher view.** A separate page behind an interstitial, not indexed: for channel lines with a code-confirmed direction, a counts-only funnel from all approved medicines down to a short list of drug and mechanism hypotheses for laboratory research, each with its evidence and model-written doubts. Hypotheses, not treatments; drug names never appear in the family view.

Everything is read from two committed JSON files. Nothing calls a model when you click.

## How OpenAI Codex was used
Codex is the only model in Polaris, and it runs at **build time only**. It does four jobs:

| Step | Make target | What Codex does | What code checks |
|---|---|---|---|
| Extract | `make extract` | reads PubMed abstracts and proposes variant-direction claims, each with a verbatim quote | the quote must be one whole sentence of the cited abstract, name the variant and gene, and state the direction the claim gives |
| Reconcile | `make reconcile` | proposes identifiers for disease and gene names | every ID is checked against the downloaded Orphadata and HPO files and the seed |
| Explain | `make explain` | writes plain-language card texts from the facts | a deny-list post-check (drug names, "cure", "safe", "eligible", links and more); a failing sentence falls back to template text |
| Critique | `make critique` | writes the doubts on each researcher-view hypothesis | a second deny-list post-check |

- **One entry point.** Every call goes through `pipeline/codex_run.sh` (model `gpt-6-astra`): a scratch directory outside the repo, prompt and batch on standard input, read-only sandbox, approval policy never, web search off, environment stripped, no API key in the environment, and a strict JSON output schema. A whole batch is rejected if its event log shows any tool use, file change, web search or MCP call.
- **Committed prompts.** The prompts and their schemas live in `pipeline/prompts/`; each output records the model, CLI version, prompt hash and input hash.
- **Every output checked by code.** The extraction funnel: **81 claims proposed by Codex, 51 accepted by the validator, 30 rejected with the reason kept** in `pipeline/seed/claims_extracted.yaml`.
- **Fallback.** gpt-oss (OpenAI's open-weight model) is the documented fallback over the same inputs and the same validator.
- On screen every AI-found claim carries the badge "Found by AI, checked by code", and every model-written sentence says which model wrote it and when.

## How the dataset is made
```
pinned ID lists ──make fetch──▶ data/raw/ (PubMed, ClinicalTrials.gov, HPO, Orphadata, Gene2Phenotype, NIH RePORTER)
                                    │
             pipeline/codex_run.sh  ▼  (Codex: read-only, no tools, strict JSON schema)
   extract ─────▶ claims_extracted.yaml ──validate.py──▶ accepted claims
   reconcile ───▶ aliases_proposed.yaml ──ID check
   explain ─────▶ texts.yaml (post-checked; template text if a sentence fails)
   critique ────▶ researcher-view doubts (post-checked)
                                    │
   seed YAML (every row sourced) + caches + transfer rules ──make build──▶ web/public/graph.json (byte-identical on rebuild)
                                                           ──make screen──▶ web/public/screen.json
```
1. **Pinned ID lists** (`pipeline/seed/pmids.txt`, `ncts.txt`) fix exactly which papers and studies are read.
2. **Fetch** downloads the public inputs into gitignored `data/raw/`.
3. **Codex** proposes claims, identifiers and texts.
4. **The validator** accepts or rejects every proposal against the fetched sources.
5. **The rules** (`pipeline/transfer.py`) decide what transfers: drugs, trials and lab models never cross a gain/loss direction; registries, care networks, screening, outcome measures and natural-history designs may; a line with mixed or unknown direction gets no direction-gated transfers.
6. **`make build`** writes `web/public/graph.json` from committed files only; rebuilding gives a byte-identical file.

## What is in the dataset (built 2026-10-04)
| | |
|---|---|
| Disease lines | 7: SCN2A gain, SCN2A loss, SCN8A-DEE (gain), Dravet (SCN1A loss), STXBP1, CDKL5, SYNGAP1, over 6 genes |
| Direction evidence | 4 channel lines confirmed by code-checked lab claims (SCN2A gain: p.Ala263Val, PMID 20956790; SCN2A loss: p.Arg853Gln, PMID 34287911; SCN8A: p.Asn1768Asp, PMID 22365152; Dravet: p.Leu986Phe, PMID 14672992); the 3 non-channel lines carry database labels only |
| Graph | 10 organisations, 18 studies, 38 assets, 42 papers, 51 claims, 5 recorded source conflicts, 30 co-listings, 28 funded projects, 214 search aliases, 328 explained edges, 236 transfer decisions |
| Text | 4 sentences written by Codex (post-checked), 234 template sentences filled from facts |
| Consistency check | with the EMBOLD trial (NCT05818553) held out, the rule names the same second gene (SCN8A) the trial's sponsor chose: 1 of 1, agreement not discovery |
| Researcher view | 2,868 approved medicines (Open Targets 26.09, ChEMBL parent molecules) → 51 act on the sodium-channel family → direction filter: gain lines keep 51, loss lines keep 0; 10 cards shown per gain line |

## The brief, covered
- **A typed knowledge graph** of diseases, genes, variants, mechanisms, symptoms, patient organisations, papers, studies and shared assets, with a pydantic schema that forbids unknown fields.
- **Every edge cites its source**, identifier and retrieval date, and says how it was checked.
- **Observed and inferred are labelled apart**: lab-study claims, database labels, eligibility-only listings and Polaris annotations each carry their own tier.
- **One global search with synonyms**: diseases, genes, variants in one- and three-letter forms, organisations, mechanisms and symptoms (HPO).
- **What can be shared and what must not**, decided by code from the variant direction, with the paper sentence behind each block.
- **Who already built the missing step**: the seven-step map per community and the borrow cards that point to the community that has it.
- **Next steps** per condition, reached through organisation pages and study records.
- **A mechanism view**: every community under one mechanism and direction, with organisations, studies by state, models, outcome measures and institutions active on two or more of them.
- **Funding**: NIH RePORTER projects per gene (titles and organisations only).
- **How it grows**: counts from Orphadata and ClinicalTrials.gov show how many diseases carry a direction label and how many studies already name two or more genes.

## Architecture
| Part | Where | What |
|---|---|---|
| Pipeline | `pipeline/` | Python 3.12: schema, fetch, validate, reconcile, transfer rules, build, `check_public` |
| Model step | `pipeline/codex_run.sh`, `pipeline/prompts/` | the one Codex entry point, the committed prompts and their JSON schemas |
| Dataset | `pipeline/seed/`, `pipeline/cache/`, `pipeline/screen/cache/` | sourced seed rows, accepted claims, stripped ClinicalTrials.gov records, papers, HPO terms, NIH RePORTER projects, drug pool; allow-listed fields only |
| Researcher view data | `pipeline/screen/` | drug pool, direction filter, evidence and critique → `screen.json` |
| Site | `web/` | Vite + React + TypeScript static site; no backend, no analytics, no search text in URLs |
| Data files | `web/public/graph.json`, `web/public/screen.json` | everything the site shows |

## Run locally
Site only (reads the committed JSON files):
```bash
cd web && npm ci && npm run dev
```
Full checks:
```bash
cd web && npm run build && npm run lint && cd ..
python3.12 -m venv .venv && .venv/bin/python -m pip install -r pipeline/requirements.lock -e "pipeline[dev]"
make test lint check-public
```

## Reproduce the dataset
No OpenAI account is needed: the committed YAML and caches are the dataset.
```bash
python3.12 -m venv .venv && .venv/bin/python -m pip install -r pipeline/requirements.lock -e "pipeline[dev]"
cp .env.example .env     # optional NCBI_EMAIL, the contact address NCBI asks for; no API keys anywhere
make fetch               # public inputs by the committed ID lists into data/raw/ (gitignored)
make validate            # re-checks every committed claim against the fetched abstracts and prints the funnel
make build               # rebuilds web/public/graph.json; byte-identical to the committed file
make screen              # rebuilds web/public/screen.json from the committed caches
make test
```
Optional model steps (model output varies run to run):
```bash
npm ci                          # the Codex CLI as a dev dependency, nothing global
npx --no-install codex login    # one-time, interactive
make extract reconcile explain critique
```

## Deploy on Vercel
Import the repository, then set **Root Directory** `web`, **Framework** Vite, **Build Command** `npm run build`, **Output Directory** `dist`. No environment variables. `web/vercel.json` sets the security headers and keeps the researcher view out of search engines (`noindex`).

## Scope and limitations
Mechanism clusters are set by hand from cited lab studies, and the site says so. No claim was checked by a person; every claim is badged as checked by code. Phenotype similarity, a sourced time-saving comparison, funder signals and named contacts are not in this build. The researcher view ranks by a fixed rule (evidence count), never by expected benefit, and reads paper titles only. Pages the pipeline did not fetch are marked "date not checked". ClinVar significance is not used; direction comes from functional-assay papers only.

## Data sources and licences
| Source | Use | Attribution |
|---|---|---|
| PubMed / E-utilities (NLM) | PMIDs and one-sentence quotes | quotes are short excerpts; abstracts belong to their publishers |
| ClinicalTrials.gov v2 (NLM) | studies, co-listings, stop reasons | listing does not imply NLM endorsement or our evaluation of a study |
| Human Phenotype Ontology | symptom terms | HPO, hpo.jax.org (Gargano et al., NAR 2024); Polaris annotations are marked and are not part of HPO |
| Orphadata (INSERM) | disease and gene entries | free access data from Orphanet © INSERM 1999 (CC BY 4.0) |
| Gene2Phenotype (EMBL-EBI) | database direction labels, shown as inferred | retrieved on the date in each record |
| Open Targets Platform | drug pool for the researcher view | CC0 1.0, incl. ChEMBL (EMBL-EBI); no document records fetched |
| NIH RePORTER | funded projects per gene, titles and organisations only | keyless v2 API, no investigator names |
| Monarch DisMech | acknowledged as prior work, not used in this build | BSD-3 |

**Research-planning tool. Not medical advice.**

Code: MIT (`LICENSE`). Data notices: `DATA-LICENSE`.

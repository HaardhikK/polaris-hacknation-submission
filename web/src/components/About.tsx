// About: a grid of cards. First the two highlights (the researcher view, and how OpenAI Codex
// built the dataset), then one card per thing Polaris does, then the facts about this map. Every number is read from graph.json or screen.json; the two
// extraction counts the site cannot read are constants copied from the committed YAML.
import { useEffect, useState, type ReactNode } from "react";
import type { Graph } from "../types";
import { counts, lineByKey, preComputedDate, studyByNct } from "../data";
import { Ext, asOf } from "../shared/Layout";
import { nctUrl } from "../links";
import { AboutCard } from "./AboutCard";

/** pipeline/seed/claims_extracted.yaml: 7 batches over 57 abstracts, 81 rows proposed. */
const EXTRACT = { proposed: 81, abstracts: 57, batches: 7 };
/** pipeline/seed/aliases_proposed.yaml: 22 identifier proposals, waiting for a person. */
const RECONCILE_PROPOSALS = 22;

const LICENCES: [string, string, string][] = [
  [
    "HPO",
    "symptom terms",
    "Human Phenotype Ontology, hpo.jax.org; Gargano et al., NAR 2024. Polaris annotations are marked and are not part of HPO.",
  ],
  [
    "Orphadata product6",
    "direction labels, group entries",
    "Orphadata: free access data from Orphanet © INSERM 1999, orphadata.com (CC BY 4.0).",
  ],
  [
    "Monarch Initiative / DisMech",
    "acknowledgement: the model for quote-checked mechanism records",
    "Monarch Initiative; Disorder Mechanisms KB, monarch-initiative/dismech (BSD-3, pre-alpha).",
  ],
  [
    "ClinicalTrials.gov v2",
    "studies, co-listing, stop reasons",
    "Data from ClinicalTrials.gov (NLM). Listing does not imply NLM endorsement or our evaluation of the study.",
  ],
  [
    "PubMed / E-utilities",
    "PMIDs, one-sentence quotes",
    "Citations from PubMed (NLM). Quotes are short excerpts; abstracts © their publishers.",
  ],
  ["Gene2Phenotype", "inferred mechanism labels", "Gene2Phenotype (EMBL-EBI)."],
  [
    "HGNC / MONDO / OMIM IDs",
    "cross-references",
    "IDs only; one line each in the repository README.",
  ],
  [
    "IMSR / JAX / MMRRC",
    "mouse-line IDs",
    "Model availability per the repository; confirm with the repository.",
  ],
  [
    "NIH RePORTER",
    "funded projects per gene",
    "Keyless v2 API; project titles and organisations only, no investigator names.",
  ],
  [
    "Open Targets Platform (incl. ChEMBL)",
    "researcher view: approved medicines and their actions",
    "Open Targets (CC0 1.0); ChEMBL (EMBL-EBI, CC BY-SA 3.0), ids only.",
  ],
];

// The slice of web/public/screen.json the About page reads (full shape: web/src/researchers/screenTypes.ts).
interface ScreenLineLite {
  key: string;
  label: string;
  direction: string;
  status: "screened" | "refused";
  refusal_reason?: string | null;
  funnel?: { approved: number; family: number; direction_pass: number } | null;
  new_candidates?: number | null;
  cards: { state: string; critique?: { status?: string; why?: unknown[]; doubts?: unknown[] } }[];
  cards_not_shown?: number;
}
interface ScreenLite {
  meta: {
    open_targets_release?: string;
    chembl_version?: string;
    retrieved?: string;
    approved_total_method?: string;
    direction_filter_note?: string;
    family_direction_note?: string;
    family_label?: string;
    ordering_rule?: string;
    pubmed_query_note?: string;
    hypothesis_label?: string;
    medication_warning?: string;
    evidence_read?: string;
    studies_found?: number;
    sources?: string[];
  };
  lines: ScreenLineLite[];
}

function useScreen() {
  const [screen, setScreen] = useState<ScreenLite | null | "error">(null);
  useEffect(() => {
    let live = true;
    fetch(`${import.meta.env.BASE_URL}screen.json`, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((j: ScreenLite) => {
        if (live) setScreen(j?.meta && Array.isArray(j.lines) ? j : "error");
      })
      .catch(() => live && setScreen("error"));
    return () => {
      live = false;
    };
  }, []);
  return screen;
}

/** The model named in the file's own provenance rows; never guessed. */
function modelName(graph: Graph) {
  for (const byAsset of Object.values(graph.texts))
    for (const t of Object.values(byAsset)) if (t?.provenance?.model) return t.provenance.model;
  return graph.claims.find((c) => c.model)?.model ?? "the model named in the data file";
}

const n = (v: number | undefined | null) => (v ?? 0).toLocaleString("en-GB");
const plural = (v: number | undefined | null, one: string, many: string) => (v === 1 ? one : many);

function Bullets({ items }: { items: ReactNode[] }) {
  return (
    <ul className="list small">
      {items.map((it, i) => (
        <li key={i}>
          <span className="sign" aria-hidden="true">
            –
          </span>
          <span>{it}</span>
        </li>
      ))}
    </ul>
  );
}

function Grid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{children}</div>;
}

interface Capability {
  id: string;
  title: string;
  summary: ReactNode;
  more: ReactNode;
}

export function About({ graph }: { graph: Graph }) {
  const [open, setOpen] = useState<string | null>(null);
  const screen = useScreen();
  const c = counts(graph);
  const mc = graph.meta.counts ?? {};
  const date = preComputedDate(graph);
  const model = modelName(graph);
  const check = graph.meta.consistency_check;
  const grows = graph.meta.how_it_grows;
  const lineLabel = (k: string) => lineByKey(graph, k)?.label ?? k;
  const card = (id: string) => ({ id, open: open === id, onToggle: setOpen });

  const accepted = c.claims;
  const rejected = EXTRACT.proposed - accepted;
  const codexTexts =
    mc.texts_codex ??
    Object.values(graph.texts).reduce(
      (k, byAsset) => k + Object.values(byAsset).filter((t) => t?.source === "codex").length,
      0,
    );
  const templateTexts = mc.texts_template;
  const aliasesTotal = mc.aliases ?? graph.aliases.length;
  const groups = graph.meta.cluster_groups ?? [];
  const multiGene = grows?.studies_naming_two_or_more_seeded_genes ?? [];

  // Researcher view, from screen.json.
  const sc = screen && screen !== "error" ? screen : null;
  const screened = sc?.lines.filter((l) => l.status === "screened") ?? [];
  const gainLines = screened.filter((l) => l.direction === "gain");
  const lossLines = screened.filter((l) => l.direction === "loss");
  const refusedChannelless =
    sc?.lines.filter((l) => l.refusal_reason === "not_a_channel_line") ?? [];
  const funnel0 = screened.find((l) => l.funnel)?.funnel;
  const shownCards = screened.flatMap((l) => l.cards);
  const withCritique = shownCards.filter((k) => k.critique?.status === "checked_by_code").length;
  const critiqueWithheld = shownCards.length > 0 && withCritique === 0;
  const datedEdges = graph.edges.filter((e) => e.retrieved).length;
  const allShownStudied =
    gainLines.length > 0 &&
    gainLines.every(
      (l) => l.cards.length > 0 && l.cards.every((k) => k.state === "already_studied"),
    );

  // Consistency check: other genes on the map outside the pool and the trial's own genes.
  const poolGenes = new Set(
    (check?.pool?.channel_lines_considered ?? []).map((k) => lineByKey(graph, k)?.gene ?? k),
  );
  const otherGenes = (check?.pool?.other_genes_on_the_map ?? []).filter(
    (g) => !poolGenes.has(g) && !(check?.held_out?.genes_named ?? []).includes(g),
  );
  const heldOutLines = [
    ...new Set(
      graph.co_listings.filter((x) => x.nct === check?.held_out?.nct).map((x) => lineLabel(x.line)),
    ),
  ];

  const kindCount = (k: string) => graph.aliases.filter((a) => a.kind === k).length;
  const stepGenes = [
    ...new Set(graph.aliases.filter((a) => a.direction_step && a.gene).map((a) => a.gene!)),
  ].sort();
  const assetCount = (k: string) => graph.assets.filter((a) => a.type === k).length;
  const matched = (f: string) => graph.co_listings.filter((x) => x.matched_field === f).length;
  const allTexts = Object.values(graph.texts).flatMap((byAsset) => Object.values(byAsset));
  const proposals = allTexts.filter((t) => t?.proposal).length;
  const fundedGenes = new Set(graph.funding.map((f) => f.gene)).size;
  const channelGroups = groups.filter((g) => g.key.startsWith("sodium_channel"));

  const does: Capability[] = [
    {
      id: "d-search",
      title: "One search for every name a family might know",
      summary: (
        <p>
          Diseases, genes, variants, organisations, mechanisms and symptoms: {n(aliasesTotal)}{" "}
          search names with their synonyms, shared codes and the 1- and 3-letter forms of each
          variant.
        </p>
      ),
      more: (
        <>
          <Bullets
            items={[
              `${kindCount("variant")} variant names, ${kindCount("symptom")} symptom terms (HPO), ${kindCount("disease")} disease names, ${kindCount("organisation")} organisation names, ${kindCount("gene")} gene names and ${kindCount("mechanism")} mechanism phrases.`,
              `${kindCount("id")} identifiers (OMIM, MONDO, Orphanet) and ${kindCount("group")} shared group codes; a code that covers several genes opens a gene picker.`,
              "Variants are matched in the browser; the search text stays on the device.",
              "A search for a condition beyond this map gets the patient directories and the free shared resources any group can join.",
            ]}
          />
        </>
      ),
    },
    {
      id: "d-direction",
      title: `Asks the direction first for ${stepGenes.join(", ")}`,
      summary: (
        <p>
          In these genes, different variants make the channel work too strongly or too weakly.
          Polaris asks which applies before it shows anything that depends on it.
        </p>
      ),
      more: (
        <p className="small">
          The choice is set by the specific variant, so the step says to ask your geneticist. A
          variant with a lab study on the map answers the question by itself: the variant line shows
          the direction with its PMID.
        </p>
      ),
    },
    {
      id: "d-mechanism",
      title: "Links communities by mechanism and direction, not disease name",
      summary: (
        <p>
          Conditions are grouped by what goes wrong in the protein and in which direction, so look-
          alikes with the opposite problem sit apart.
        </p>
      ),
      more: (
        <Bullets
          items={channelGroups.map((g) => (
            <>
              {g.label}: {g.line_keys.map(lineLabel).join(", ")}
            </>
          ))}
        />
      ),
    },
    {
      id: "d-share",
      title: "Says what can be shared and what must not, with the paper that decides it",
      summary: (
        <p>
          Registries, care networks, outcome measures and natural-history designs can cross groups.
          Medicines, trials and lab models stay within one direction.
        </p>
      ),
      more: (
        <p className="small">
          The rules made {n(mc.transfers)} share-or-block decisions between conditions. Each block
          names the code-checked lab study behind it, and the block banner repeats the medication
          warning word for word: "{graph.meta.medication_warning}"
        </p>
      ),
    },
    {
      id: "d-differs",
      title: "Shows what differs and what to check first",
      summary: (
        <p>
          Each borrow card names the direction, how much the symptoms overlap, the eligibility
          differences in the study record, and the questions to settle before joining forces.
        </p>
      ),
      more: (
        <p className="small">
          Cards open in three levels: one plain sentence; "Why we think this" with quotes, PMIDs and
          "What differs"; and "For researchers" with earlier studies.{" "}
          {allTexts.filter((t) => t?.check_first?.length).length} cards carry a "Check first" list.
        </p>
      ),
    },
    {
      id: "d-builders",
      title: "Finds who already built the step you are missing",
      summary: (
        <p>
          {assetCount("registry")} registries, {assetCount("natural_history")} natural-history
          designs, {assetCount("outcome_measure")} outcome measures, {assetCount("model")} lab
          models and {assetCount("trial")} trials, each tied to the community that holds it.
        </p>
      ),
      more: (
        <p className="small">
          The steps timeline shows which of the {graph.meta.steps_total ?? 7} research steps a
          community already holds and which another community could lend, each step linked to its
          source.
        </p>
      ),
    },
    {
      id: "d-colisted",
      title: "Studies that already list two conditions together",
      summary: (
        <p>
          {graph.co_listings.length} listings tie mapped conditions to the study records that name
          them, with the field that matched, so one study listing several shows at a glance.
        </p>
      ),
      more: (
        <p className="small">
          Matched in the conditions field {matched("conditions")} times, in keywords{" "}
          {matched("keywords")} times and in the inclusion criteria{" "}
          {matched("eligibility_inclusion")} times, each with a short window of the matching text
          and the date the record was read. The study team decides who can take part.
        </p>
      ),
    },
    {
      id: "d-evidence",
      title: "Every link cites its source, ID and date",
      summary: (
        <p>
          Each of the {n(c.edges)} links carries the page it came from; click any link on the map to
          see its evidence.
        </p>
      ),
      more: (
        <p className="small">
          {n(datedEdges)} links also carry the date they were read. Claims carry their PMID and the
          exact sentence; studies their ClinicalTrials.gov number. Links are built from these IDs
          and open on PubMed, ClinicalTrials.gov, Orphanet, HPO and the organisations' own sites.
        </p>
      ),
    },
    {
      id: "d-observed",
      title: "Observed and inferred are labelled; disagreements sit side by side",
      summary: (
        <p>
          A direction from a lab study is marked as such; a database label is marked inferred. Where
          sources disagree, both quotes are shown.
        </p>
      ),
      more: (
        <p className="small">
          This build records {mc.conflicts ?? graph.conflicts.length} source conflicts, each with
          both sides and their references. Claims found by the model carry the badge "
          {graph.meta.badge ?? "Found by AI, checked by code"}".
        </p>
      ),
    },
    {
      id: "d-searched",
      title: "Says what was searched and when, for each condition",
      summary: (
        <p>
          Each condition lists the PubMed abstracts fetched, how many gave an accepted claim, the
          query that built the list and the date.
        </p>
      ),
      more: (
        <p className="small">
          The full table is in "What we searched and when" below, with every seed source and the
          date it was retrieved.
        </p>
      ),
    },
    {
      id: "d-next",
      title: "Next steps for families",
      summary: (
        <p>
          Join a shared resource, propose working together, check first, and ask your geneticist
          about the variant.
        </p>
      ),
      more: (
        <Bullets
          items={[
            <>
              Free shared resources to join today, linked on every result page
              {grows?.free_resources?.length
                ? `: ${grows.free_resources.map((r) => r.label).join(", ")}`
                : ""}
              .
            </>,
            "A drafted proposal to the community or study team that holds the step.",
            "The check-first list to take to the team.",
            "Questions to bring to the geneticist and neurologist.",
          ]}
        />
      ),
    },
    {
      id: "d-proposal",
      title: "A drafted two-way proposal to the study team",
      summary: (
        <p>
          {proposals} borrow cards carry a proposal that says what your community asks and what it
          offers in return, drafted from the cited facts.
        </p>
      ),
      more: (
        <p className="small">
          The proposal opens in a dialog to copy or download, with its citations. {codexTexts} of
          them were written by {model} at build time and checked by code; the rest are filled from
          fixed sentences.
        </p>
      ),
    },
    {
      id: "d-mechview",
      title: "Mechanism view for researchers",
      summary: (
        <p>
          Every condition on a mechanism, with its organisations, studies, models, outcome measures
          and the institutions it shares, ranked by shared assets.
        </p>
      ),
      more: (
        <Bullets
          items={graph.mechanism_view.map((m) => (
            <>
              {m.label.replace(/: gain\/loss not used here$/, "")}: {m.lines.length}{" "}
              {plural(m.lines.length, "condition", "conditions")}, {m.institutions.length}{" "}
              {plural(m.institutions.length, "institution", "institutions")} running studies for two
              or more of them
            </>
          ))}
        />
      ),
    },
    {
      id: "d-funding",
      title: "Funding: NIH projects per gene",
      summary: (
        <p>
          {graph.funding.length} NIH RePORTER projects across {fundedGenes} genes, with project
          number, title, organisation and year.
        </p>
      ),
      more: (
        <p className="small">
          They sit behind "For researchers" on each result page and in the mechanism view, each
          linked to its RePORTER record.
        </p>
      ),
    },
    {
      id: "d-grows",
      title: "Grows by data, not code",
      summary: (
        <p>
          A new condition goes through the same extraction, checks and rules, and the map picks it
          up on the next build.
        </p>
      ),
      more: (
        <p className="small">
          Room to grow: Orphanet lists {n(grows?.orphanet_entries)} rare disease entries,{" "}
          {n(grows?.orphanet_entries_with_a_gene)} with a disease-causing gene. The counts are in
          "How this map can grow" below.
        </p>
      ),
    },
    {
      id: "d-check",
      title: "A consistency check against a real expert decision",
      summary: (
        <p>
          With {check?.held_out?.name ?? "the trial"} hidden, the rule names the same second gene
          its team chose: {check?.agreement?.hits ?? "?"} of {check?.agreement?.k ?? "?"}.
        </p>
      ),
      more: (
        <p className="small">
          It uses only papers {check?.inputs?.papers_cutoff ?? "from before the trial"}, from a pool
          of {check?.pool?.size ?? "?"} conditions (chance {check?.pool?.random_baseline ?? "?"}).
          The full method is in "Consistency check" below.
        </p>
      ),
    },
    {
      id: "d-openai",
      title: "Built with OpenAI Codex",
      summary: (
        <p>
          {model} extracted the claims, reconciled names, wrote the card texts and critiqued the
          researcher candidates at build time. Code checked every output.
        </p>
      ),
      more: (
        <p className="small">
          The detail is in "How OpenAI Codex built the dataset" at the top of this page.
        </p>
      ),
    },
  ];

  return (
    <div className="stack">
      <section className="card">
        <h1>About Polaris</h1>
        <p>
          Polaris maps what rare-disease communities can borrow from each other and blocks what they
          must not, by mutation direction, with every link cited. Research-planning tool. Not
          medical advice. Do not change treatment based on this site.
        </p>
      </section>

      <h2 className="sr-only">Highlights</h2>
      <Grid>
        <AboutCard
          {...card("research")}
          tone="highlight"
          wide
          title="Accelerating the research"
          action={
            <a className="btn primary" href="/researchers/" rel="nofollow">
              Open the researcher view
            </a>
          }
          summary={
            sc && funnel0 ? (
              <>
                <p>
                  For each sodium-channel condition whose direction a code-checked lab study
                  confirms, the researcher view screens {n(funnel0.approved)} approved medicines to
                  the {funnel0.family} that act on the channel family, then keeps only those whose
                  action matches the condition's direction.
                </p>
                <p>
                  On the {gainLines.length} gain{" "}
                  {plural(gainLines.length, "condition", "conditions")},{" "}
                  {[...new Set(gainLines.map((l) => l.funnel?.direction_pass ?? 0))].join(" or ")}{" "}
                  medicines pass,
                  {allShownStudied
                    ? " and the first ones shown are the known channel blockers, marked already studied."
                    : " listed with the papers that pair drug and gene."}{" "}
                  On the {lossLines.length} loss{" "}
                  {plural(lossLines.length, "condition", "conditions")},{" "}
                  {lossLines.every((l) => (l.funnel?.direction_pass ?? 0) === 0)
                    ? "none pass, and the page says so."
                    : lossLines.map((l) => l.funnel?.direction_pass ?? 0).join(" and ") + " pass."}
                </p>
                <p className="font-semibold text-[var(--ink)]">
                  Hypotheses for laboratory testing, never treatment advice.
                </p>
              </>
            ) : (
              <p>
                {screen === "error"
                  ? "The researcher data file could not be loaded here; the researcher view reads it directly."
                  : "Loading the researcher figures."}
              </p>
            )
          }
        >
          {sc && funnel0 && (
            <>
              <p className="small">
                The screen starts from {n(funnel0.approved)} approved medicines (Open Targets{" "}
                {sc.meta.open_targets_release ?? "release not stated"}, {sc.meta.chembl_version}
                {sc.meta.retrieved ? `, retrieved ${sc.meta.retrieved}` : ""}):{" "}
                {sc.meta.approved_total_method}. Of those, {funnel0.family} act on the{" "}
                {sc.meta.family_label ?? "channel family"}.
              </p>
              <div
                className="table-wrap"
                tabIndex={0}
                role="region"
                aria-label="Researcher view funnel per condition"
              >
                <table>
                  <thead>
                    <tr>
                      <th>Condition</th>
                      <th>Direction</th>
                      <th>Pass the direction filter</th>
                      <th>Shown</th>
                      <th>Not yet paired with the gene</th>
                    </tr>
                  </thead>
                  <tbody>
                    {screened.map((l) => (
                      <tr key={l.key}>
                        <td>{l.label}</td>
                        <td>{l.direction}</td>
                        <td>
                          {l.funnel?.direction_pass ?? 0} of {l.funnel?.family ?? 0}
                        </td>
                        <td>
                          {l.cards.length}
                          {l.cards.length
                            ? `, ${l.cards.filter((k) => k.state === "already_studied").length} already studied`
                            : ""}
                        </td>
                        <td>{l.new_candidates ?? 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Bullets
                items={[
                  sc.meta.direction_filter_note,
                  sc.meta.family_direction_note,
                  `Cards are ${sc.meta.ordering_rule ?? "in a fixed order"}. Each lists the papers that already pair the medicine and the gene (${sc.meta.evidence_read ?? "titles"} read). ${sc.meta.pubmed_query_note ?? ""}`,
                  <>
                    Model-written reasons and doubts: each sentence must cite one of the card's
                    PMIDs and pass a code check.{" "}
                    {withCritique === 0
                      ? `In this build none of the ${shownCards.length} shown cards carry them: the facts changed after the model run, so each card says the critique is not available rather than show stale text.`
                      : withCritique < shownCards.length
                        ? `In this build ${withCritique} of ${shownCards.length} shown cards carry them; the others say the critique is not available, because the facts changed after the model run.`
                        : "Every shown card carries them, with the model and the date."}
                  </>,
                  `The screen runs on the sodium-channel conditions; the ${refusedChannelless.length} synapse and signalling ${plural(refusedChannelless.length, "condition stays", "conditions stay")} on the family view.`,
                  `Every card reads "${sc.meta.hypothesis_label ?? "Hypothesis for laboratory testing, not medical advice"}". The view opens behind its own notice, is not indexed and is never linked from a family result.`,
                ].filter(Boolean)}
              />
              {sc.meta.medication_warning && (
                <p className="small font-semibold">{sc.meta.medication_warning}</p>
              )}
            </>
          )}
        </AboutCard>

        <AboutCard
          {...card("codex")}
          tone="feature"
          wide
          kicker="Built with OpenAI"
          title="How OpenAI Codex built the dataset"
          summary={
            <>
              <p>
                OpenAI Codex ({model}) did four jobs at build time: extract claims from PubMed
                abstracts, reconcile names to identifiers, explain the borrow cards, and critique
                the researcher candidates. Code checked every output.
                {critiqueWithheld &&
                  " The critique is not shown in this build: the facts changed after its run."}
              </p>
              <p>
                {EXTRACT.proposed} claims proposed, {accepted} accepted, {rejected} rejected, each
                with the validator's reason. Nothing calls a model when you click.
              </p>
            </>
          }
        >
          <h4>Where it was used</h4>
          <Bullets
            items={[
              `Extract: ${EXTRACT.abstracts} PubMed abstracts in ${EXTRACT.batches} batches; each proposed claim names a variant, its direction and one quoted sentence.`,
              `Reconcile: ${RECONCILE_PROPOSALS} proposals linking names to identifiers, each checked against the downloaded Orphadata and HPO files; they stay proposals until a person moves them in.`,
              `Explain: ${codexTexts} borrow-card texts with their two-way proposals${templateTexts ? `; the other ${n(templateTexts)} card texts are fixed template sentences filled from the facts` : ""}.`,
              `Critique: reasons and doubts for the researcher view's candidate medicines on the gain conditions, each sentence tied to a PMID.${critiqueWithheld ? ` Not shown in this build: the facts changed after the run, so none of the ${shownCards.length} shown cards carry it until it is re-run.` : ""}`,
            ]}
          />
          <h4>How it was run</h4>
          <Bullets
            items={[
              "At build time only. The site reads one static file; nothing calls a model when you click.",
              "One committed script is the only way in. The prompt and the batch go in on standard input.",
              "Read-only sandbox, no tools, web search off, a stripped environment and a strict JSON output schema.",
              "A batch whose event log shows any tool use is rejected whole.",
              "Code checks every output: a quote must be one whole sentence of the cited abstract and name the variant and gene; family text passes a deny-list (no medicine names, no promises); researcher sentences pass a second deny-list and are shown as checked only when they cite a PMID of their card.",
            ]}
          />
          <h4>What came out</h4>
          <Bullets
            items={[
              `${EXTRACT.proposed} claims proposed, ${accepted} accepted, ${rejected} rejected; the rejected rows stay in the committed file and the validator prints each one's reason, so the count is honest.`,
              `Accepted claims carry the badge "${graph.meta.badge ?? "Found by AI, checked by code"}".`,
              `Each model-written text says "Written by ${model} at build time" with its date and that code checked it.`,
              "gpt-oss, OpenAI's open-weight model, is the documented fallback over the same inputs and the same checks; every model output in this build comes from Codex.",
            ]}
          />
        </AboutCard>
      </Grid>

      <section aria-labelledby="does-title" className="mt-4">
        <h2 id="does-title">What Polaris does</h2>
        <Grid>
          {does.map((d, i) => (
            <AboutCard
              key={d.id}
              {...card(d.id)}
              wide={i === does.length - 1 && does.length % 2 === 1}
              title={d.title}
              summary={d.summary}
            >
              {d.more}
            </AboutCard>
          ))}
        </Grid>
      </section>

      <section aria-labelledby="facts-title" className="mt-4">
        <h2 id="facts-title">About this map</h2>
        <Grid>
          <AboutCard
            {...card("f-map")}
            title="What is in this map"
            summary={
              <p>
                {c.lines} conditions, {c.genes} genes, {c.organisations} patient organisations,{" "}
                {c.studies} study records, {c.assets} research assets, {c.papers} papers, {c.claims}{" "}
                code-checked claims, {n(c.edges)} links.
              </p>
            }
          >
            <h4>Sources and the dates they were read</h4>
            {graph.meta.sources?.length ? (
              <Bullets
                items={graph.meta.sources.map((src) => (
                  <>
                    <Ext href={src.url}>{src.name}</Ext>
                    {src.release ? `, ${src.release}` : ""}
                    {src.licence ? `, ${src.licence}` : ""}; {asOf(src.retrieved)}
                  </>
                ))}
              />
            ) : (
              <p className="small muted">
                The data file names no source list; see the licence table.
              </p>
            )}
          </AboutCard>

          <AboutCard
            {...card("f-searched")}
            title="What we searched and when"
            summary={
              <p>
                For each condition: the PubMed abstracts fetched by a pinned ID list, how many gave
                an accepted claim, and the seed sources with their dates.
              </p>
            }
          >
            <div
              className="table-wrap"
              tabIndex={0}
              role="region"
              aria-label="What we searched per condition"
            >
              <table>
                <thead>
                  <tr>
                    <th>Condition</th>
                    <th>PubMed search</th>
                    <th>Seed sources</th>
                  </tr>
                </thead>
                <tbody>
                  {graph.lines.map((l) => (
                    <tr key={l.key}>
                      <td>{l.label}</td>
                      <td>
                        {l.coverage ? (
                          <>
                            {l.coverage.papers_mentioning_gene ?? "?"} fetched{" "}
                            {plural(l.coverage.papers_mentioning_gene, "abstract", "abstracts")}{" "}
                            {plural(l.coverage.papers_mentioning_gene, "mentions", "mention")}{" "}
                            {l.gene}; {l.coverage.papers_extracted ?? "?"} yielded an accepted claim
                            {l.coverage.retrieved ? ` (retrieved ${l.coverage.retrieved})` : ""}.
                            {l.coverage.esearch_term && (
                              <details className="small">
                                <summary>The PubMed query that built the ID list</summary>
                                <code className="wrap-any">{l.coverage.esearch_term}</code>
                              </details>
                            )}
                          </>
                        ) : (
                          "no search record in the data file"
                        )}
                      </td>
                      <td>
                        {l.sources.map((s, i) => (
                          <span key={i}>
                            {i > 0 && "; "}
                            <Ext href={s.url}>{s.label}</Ext> (
                            {s.retrieved ? `retrieved ${s.retrieved}` : "not yet verified"})
                          </span>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </AboutCard>

          <AboutCard
            {...card("f-check")}
            title="Consistency check"
            summary={
              <p>
                {check
                  ? `Our rule names the same second gene the ${check.held_out?.name ?? "trial"} team chose: ${check.agreement?.hits ?? "?"} of ${check.agreement?.k ?? "?"}, from a pool of ${check.pool?.size ?? "?"} (chance ${check.pool?.random_baseline ?? "?"}). Agreement, not discovery.`
                  : "Not in the data file for this build; nothing is claimed about agreement."}
              </p>
            }
          >
            {check ? (
              <>
                <p className="small">
                  The question: with {check.held_out?.name ?? "the trial"} hidden, and only papers{" "}
                  {check.inputs?.papers_cutoff ?? "published before the trial"} and study records
                  started before {check.held_out?.start_date ?? "its start"}, which other channel
                  condition does our rule say could join the trial's own condition in one trial?
                </p>
                <Bullets
                  items={[
                    <>
                      Held out: {check.held_out?.name ?? "the trial"}
                      {check.held_out?.nct && (
                        <>
                          {" "}
                          (<Ext href={nctUrl(check.held_out.nct)}>{check.held_out.nct}</Ext>)
                        </>
                      )}
                      {check.held_out?.start_date ? `, started ${check.held_out.start_date}` : ""}
                      {check.held_out?.genes_named?.length
                        ? `; the record names ${check.held_out.genes_named.join(" and ")}`
                        : ""}
                      .
                    </>,
                    <>
                      The rule's answer:{" "}
                      {check.prediction?.lines?.length
                        ? check.prediction.lines.map(lineLabel).join(", ")
                        : (check.prediction?.genes ?? []).join(", ") || "none"}
                      . {check.agreement?.sentence ?? ""}
                    </>,
                    <>
                      Pool: {check.pool?.size ?? "?"} channel{" "}
                      {plural(check.pool?.size, "condition", "conditions")} the rule could have
                      named
                      {check.pool?.channel_lines_considered?.length
                        ? ` (${check.pool.channel_lines_considered.map(lineLabel).join("; ")})`
                        : ""}
                      ; random baseline {check.pool?.random_baseline ?? "?"}
                      {otherGenes.length
                        ? `; other genes on the map: ${otherGenes.join(", ")}`
                        : ""}
                      .
                    </>,
                    <>
                      Inputs: {check.inputs?.claims_used ?? "?"} code-checked claims from{" "}
                      {check.inputs?.papers_used?.length ?? "?"} papers{" "}
                      {check.inputs?.papers_cutoff ?? ""}
                      {check.inputs?.static_background?.length
                        ? `; static background: ${check.inputs.static_background.join("; ")}`
                        : ""}
                      .
                    </>,
                  ]}
                />
                <p className="small muted">
                  "Named in the same study" listings are reported separately: each shows the study's
                  condition list on the date the record was read.
                  {heldOutLines.length
                    ? ` Conditions listed together in ${check.held_out?.name ?? "the trial"} today: ${heldOutLines.join(" and ")}.`
                    : ""}
                </p>
                {check.caveat && (
                  <p className="small">
                    <strong>Caveat:</strong> {check.caveat}
                  </p>
                )}
              </>
            ) : null}
          </AboutCard>

          <AboutCard
            {...card("f-grow")}
            title="How this map can grow"
            summary={
              <p>
                This build maps {grows?.lines_covered ?? c.lines} conditions of{" "}
                {grows?.genes_covered ?? c.genes} genes. Adding a condition is a data task, not new
                code.
              </p>
            }
          >
            {grows ? (
              <>
                <p className="small">
                  Orphanet lists {n(grows.orphanet_entries)} rare disease entries,{" "}
                  {n(grows.orphanet_entries_with_a_gene)} of them with a disease-causing gene
                  {grows.orphanet_direction_labels
                    ? `; of ${n(grows.orphanet_direction_labels.links)} gene-disease links in Orphanet, ${n(grows.orphanet_direction_labels.gain_of_function)} carry a gain-of-function label and ${n(grows.orphanet_direction_labels.loss_of_function)} a loss label`
                    : ""}
                  {grows.retrieved?.orphadata ? ` (retrieved ${grows.retrieved.orphadata})` : ""}.
                  Of the {grows.studies_fetched ?? c.studies} study records fetched,{" "}
                  {multiGene.length} name two or more of the mapped genes
                  {grows.retrieved?.ctgov ? ` (retrieved ${grows.retrieved.ctgov})` : ""}:
                </p>
                {multiGene.length ? (
                  <Bullets
                    items={multiGene.map((s) => (
                      <>
                        {studyByNct(graph, s.nct)?.name ?? s.nct} (
                        <Ext href={nctUrl(s.nct)}>{s.nct}</Ext>): {s.genes.join(", ")}
                      </>
                    ))}
                  />
                ) : null}
                {grows.free_resources?.length ? (
                  <p className="small">
                    <strong>Free shared resources any rare-disease group can join:</strong>{" "}
                    {grows.free_resources.map((r, i) => (
                      <span key={r.id}>
                        {i > 0 && ", "}
                        <Ext href={r.url}>{r.label}</Ext>
                        {r.nct && (
                          <>
                            {" "}
                            (<Ext href={nctUrl(r.nct)}>{r.nct}</Ext>)
                          </>
                        )}
                      </span>
                    ))}
                    . Each links to its owner's own page.
                  </p>
                ) : null}
                <p className="small">
                  Adding a condition is a data task, not new code: its papers, study records and
                  organisation go through the same extraction, checks and rules, and the map picks
                  it up on the next build.
                </p>
              </>
            ) : (
              <p className="small muted">No growth counts are in the data file for this build.</p>
            )}
          </AboutCard>

          <AboutCard
            {...card("f-limits")}
            title="Limitations"
            summary={
              <p>
                Not medical advice. Claims are checked by code, not by a person. One slice of
                epilepsy genetics: {c.lines} conditions of {c.genes} genes.
              </p>
            }
          >
            <Bullets
              items={[
                "Research-planning tool. Do not change treatment based on this site.",
                `Claims found by the model are checked by code against the cited abstract; no person has signed them, and the badge says "${graph.meta.badge ?? "Found by AI, checked by code"}".`,
                `The map covers ${c.lines} conditions of ${c.genes} epilepsy genes; a condition beyond them has simply not been checked yet.`,
              ]}
            />
          </AboutCard>

          <AboutCard
            {...card("f-licences")}
            title="Data sources and licences"
            summary={
              <p>
                Public sources only: PubMed, ClinicalTrials.gov, HPO, Orphadata, Gene2Phenotype, NIH
                RePORTER, Open Targets. Code: MIT.
              </p>
            }
          >
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Licences per source">
              <table>
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Used for</th>
                    <th>Attribution</th>
                  </tr>
                </thead>
                <tbody>
                  {LICENCES.map(([s, u, a]) => (
                    <tr key={s}>
                      <td>{s}</td>
                      <td>{u}</td>
                      <td>{a}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="small">
              Monarch's Disorder Mechanisms knowledge base (DisMech) already models per-disease
              mechanisms with curated, quote-checked evidence. Polaris borrows that idea and adds
              communities, assets, the borrow-or-block decision and the steps timeline.
            </p>
            <p className="small muted">Code: MIT. Data notices: DATA-LICENSE in the repository.</p>
          </AboutCard>
        </Grid>
      </section>

      <p className="small muted mt-2">
        {(graph.meta as { about_notice?: string }).about_notice ??
          `Not medical advice. Data and AI text pre-computed ${date || "(date not in the data file)"}.`}
      </p>
    </div>
  );
}

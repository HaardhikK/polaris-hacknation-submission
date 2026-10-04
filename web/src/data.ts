// Loads web/public/graph.json once and derives the lookups the screens use.
// Nothing here invents a fact: every derived value is a re-grouping of the file.
import type {
  Banner,
  DirectionEvidence,
  Asset,
  Card,
  CardText,
  Claim,
  Conflict,
  Direction,
  Edge,
  Graph,
  Line,
  Organisation,
  Paper,
  RawEdge,
  Source,
  Study,
  Transfer,
} from "./types";
import { nctUrl, pubmedUrl } from "./links";
import { canonicalVariant } from "./variants";

type Raw = Record<string, unknown>;
const obj = <T>(v: unknown): Record<string, T> =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, T>) : {};
const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

/** The pipeline's file (pipeline/graph.schema.json) with its edges lifted and texts nested. */
export function adapt(raw: Raw): Graph {
  // texts arrive keyed "<card>:<asset>" ("scn2a_loss:embold_trial", "scn2a_unknown:inchstone_measure");
  // split at the last colon so a card key may carry one itself.
  const texts: Record<string, Record<string, CardText>> = {};
  for (const [k, v] of Object.entries(obj<CardText>(raw.texts))) {
    const i = k.lastIndexOf(":");
    if (i < 0) continue;
    (texts[k.slice(0, i)] ??= {})[k.slice(i + 1)] = v;
  }
  const g: Graph = {
    meta: obj<never>(raw.meta) as Graph["meta"],
    lines: arr<Line>(raw.lines),
    organisations: arr<Organisation>(raw.organisations),
    studies: arr<Study>(raw.studies),
    assets: arr<Asset>(raw.assets),
    papers: arr<Paper>(raw.papers),
    claims: arr<Claim>(raw.claims),
    conflicts: arr<Conflict>(raw.conflicts),
    aliases: arr(raw.aliases),
    co_listings: arr(raw.co_listings),
    edges: [],
    cards: obj<Card>(raw.transfers),
    texts,
    tried_before: obj(raw.tried_before),
    mechanism_view: arr(raw.mechanism_view),
    funding: arr(raw.funding),
  };
  g.edges = arr<Edge | RawEdge>(raw.edges).map((e) => ("source_id" in e ? liftEdge(g, e) : e));
  return g;
}

/** The pipeline's edge (typed ids + PMID/NCT) lifted to a self-explaining edge. */
function liftEdge(g: Graph, e: RawEdge): Edge {
  const [tKind, tRef] = e.target_id.split(":", 2);
  const [, sRef] = e.source_id.split(":", 2);
  let source: Source | null = null;
  if (e.pmid)
    source = {
      label: `PMID ${e.pmid}`,
      url: pubmedUrl(e.pmid) ?? "",
      retrieved: e.retrieved ?? null,
    };
  else if (e.nct)
    source = {
      label: `ClinicalTrials.gov ${e.nct}`,
      url: nctUrl(e.nct) ?? "",
      retrieved: e.retrieved ?? null,
    };
  else if (tKind === "asset") {
    const a = g.assets.find((x) => x.id === tRef);
    if (a) source = { ...a.source, retrieved: a.source.retrieved ?? e.retrieved ?? null };
  } else if (tKind === "org") {
    const o = g.organisations.find((x) => x.key === tRef);
    if (o) source = { label: o.name, url: o.url, retrieved: o.last_verified ?? null };
  } else if (tKind === "study") {
    const st = g.studies.find((x) => x.nct === tRef);
    if (st)
      source = {
        label: `ClinicalTrials.gov ${st.nct}`,
        url: nctUrl(st.nct) ?? "",
        retrieved: st.retrieved ?? st.source?.retrieved ?? null,
      };
  } else if (tKind === "conflict") {
    const c = g.conflicts.find((x) => x.id === tRef);
    if (c) source = { ...c.sides[0].source };
  }
  if (!source)
    source = {
      label: "transfer rule over the committed seed and claims",
      url: "",
      retrieved: e.retrieved ?? null,
    };
  const note = tKind === "line" ? lineToLineNote(g, sRef, tRef, e.kind) : null;
  const claim = e.claim_id
    ? g.claims.find((c) => c.claim_id === e.claim_id)
    : e.pmid
      ? g.claims.find((c) => c.pmid === e.pmid && `line:${lineForClaim(g, c)?.key}` === e.source_id)
      : undefined;
  return {
    subject: e.source_id,
    predicate: e.kind,
    object: e.target_id,
    source,
    tier: e.kind === "co_listed_in" ? 2 : 1,
    knowledge_level: ["viable", "blocked", "not_shared", "already_open"].includes(e.kind)
      ? "prediction"
      : e.kind === "claim" || e.kind === "claim_review"
        ? "knowledge_assertion"
        : "observation",
    agent_type:
      e.kind === "claim" || e.kind === "claim_review" ? "text_mining_agent" : "automated_agent",
    direction_qualifier: claim?.direction ?? null,
    note:
      note ??
      (claim ? `${claim.variant ?? claim.gene}, ${claim.basis}, stance ${claim.stance}` : null),
    retrieved: e.retrieved ?? source.retrieved ?? null,
  };
}

function lineToLineNote(g: Graph, from: string, to: string, kind: string): string | null {
  const card = g.cards[from];
  const other = g.lines.find((l) => l.key === to);
  if (!card || !other) return null;
  const rows = card.transfers.filter(
    (t) =>
      (t.owner_line ? t.owner_line === to : t.owner_gene === other.gene) &&
      (kind === "blocked" ? t.blocked : t.status === kind),
  );
  if (rows.length === 0) return null;
  const names = rows.map((t) => assetById(g, t.asset_id)?.label ?? t.asset_id);
  return `${rows.length} asset${rows.length === 1 ? "" : "s"}: ${names.join("; ")}${rows[0].cited_pmid ? ` · lab study PMID ${rows[0].cited_pmid}` : ""}`;
}

function lineForClaim(g: Graph, c: Claim): Line | undefined {
  const same = g.lines.filter((l) => l.gene === c.gene);
  if (same.length === 1) return same[0];
  return same.find((l) => l.direction === c.direction);
}

/** The date the file was pre-computed (meta.pre_computed; meta.built as the older name). */
export const preComputedDate = (g: Graph) => g.meta.pre_computed ?? g.meta.built ?? "";

/** The card text for a card:asset pair, with the pipeline's "text" field as the explanation. */
export function explanationOf(t: CardText | undefined) {
  if (!t) return { sentence: undefined, model: false as const, provenance: undefined };
  const sentence = t.explanation ?? t.text;
  const model = t.source ? t.source !== "template" : !!t.provenance;
  return { sentence, model, provenance: t.provenance ?? undefined };
}

// --- Groups ----------------------------------------------------------------------------

export const GROUPS = [
  {
    id: "gain",
    title: "Sodium channel: works too strongly",
    test: (l: Line) => l.mechanism_family === "ion_channel" && l.direction === "gain",
  },
  {
    id: "loss",
    title: "Sodium channel: works too weakly",
    test: (l: Line) => l.mechanism_family === "ion_channel" && l.direction === "loss",
  },
  {
    id: "other",
    title: "Synapse and signalling genes: gain/loss not used here",
    test: (l: Line) => l.mechanism_family !== "ion_channel",
  },
  {
    id: "unsettled",
    title: "Sodium channel: direction not settled",
    test: (l: Line) =>
      l.mechanism_family === "ion_channel" &&
      (l.direction === "mixed" || l.direction === "unknown"),
  },
] as const;

export const groupOf = (l: Line) => GROUPS.find((g) => g.test(l)) ?? GROUPS[2];

export const DIRECTION_WORDS: Record<Direction, string> = {
  gain: "works too strongly",
  loss: "works too weakly",
  mixed: "sources disagree",
  unknown: "direction not known",
  not_applicable: "gain/loss not used here",
};

export const STATION_LABEL: Record<string, string> = {
  diagnosis: "Diagnosis",
  registry: "Registry",
  natural_history: "Natural-history study",
  mechanism: "Understood mechanism",
  model: "Animal or cell model",
  outcome_measure: "A way to measure improvement",
  trial: "Trial",
};

/**
 * Fixed pipeline phrases rendered in family words. Only exact template phrases are mapped;
 * model-written sentences are never edited.
 */
const PLAIN: [RegExp, string][] = [
  [/no asset of this kind in the seed/g, "none found yet"],
  [/not yet dated by a person/g, "page date not yet checked"],
  [/counts as loss of function/g, "counts as loss of function (the channel works too weakly)"],
  [/counts as gain of function/g, "counts as gain of function (the channel works too strongly)"],
];
export const plain = (s: string) => PLAIN.reduce((acc, [re, to]) => acc.replace(re, to), s);

export const STATUS_WORD: Record<string, { sign: string; word: string }> = {
  viable: { sign: "✓", word: "Borrow" },
  needs_expert_check: { sign: "○", word: "Needs expert check" },
  not_shared: { sign: "✕", word: "Not shared" },
  already_open: { sign: "✓", word: "Already open to you" },
};

// --- Lookups ------------------------------------------------------------------------------

export function lineByKey(g: Graph, key: string) {
  return g.lines.find((l) => l.key === key);
}
export function assetById(g: Graph, id: string) {
  return g.assets.find((a) => a.id === id);
}
export function studyByNct(g: Graph, nct: string) {
  return g.studies.find((s) => s.nct === nct);
}
export function claimsById(g: Graph, ids: string[]) {
  return ids.map((id) => g.claims.find((c) => c.claim_id === id)).filter((c): c is Claim => !!c);
}
export function orgsForLine(g: Graph, line: Line) {
  return g.organisations.filter((o) => o.lines.includes(line.key));
}
export function orgsForGene(g: Graph, gene: string) {
  const keys = new Set(g.lines.filter((l) => l.gene === gene).map((l) => l.key));
  return g.organisations.filter((o) => o.lines.some((k) => keys.has(k)));
}
export function conflictsForLine(g: Graph, line: Line) {
  return g.conflicts.filter((c) => c.line === line.key || (!c.line && c.gene === line.gene));
}
export function cardFor(g: Graph, key: string): Card | undefined {
  return g.cards[key];
}
export function textFor(g: Graph, cardKey: string, assetId: string) {
  return g.texts[cardKey]?.[assetId];
}

/** The code-checked claim the file names as the line's direction evidence, best first. */
export function directionEvidence(line: Line): DirectionEvidence[] {
  const given = line.direction_evidence;
  if (Array.isArray(given)) return given;
  return given?.pmid ? [given] : [];
}

/** The direction the pipeline confirmed for a line (line.direction_known, else the card's). */
export const knownDirection = (g: Graph, line: Line): Direction =>
  line.direction_known ??
  g.cards[line.key]?.direction ??
  (line.mechanism_family === "ion_channel" ? "unknown" : "not_applicable");

/**
 * The Borrow cards: the pipeline's top cards in its order, kept to rows a community can
 * borrow (viable, needs expert check). "Already open to you" rows stay in their own list.
 */
export function borrowCards(card: Card | undefined, n = 3): Transfer[] {
  if (!card) return [];
  const borrowable = (t: Transfer) => t.status === "viable" || t.status === "needs_expert_check";
  const named = card.top_cards_typed?.length ? card.top_cards_typed : card.top_cards;
  if (named?.length)
    return named
      .map((entry) => {
        const id = typeof entry === "string" ? entry : entry.asset_id;
        const t = card.transfers.find((x) => x.asset_id === id);
        if (!t) return undefined;
        const card_type =
          typeof entry === "string" ? t.card_type : (entry.card_type ?? t.card_type);
        return card_type ? { ...t, card_type } : t;
      })
      .filter((t): t is Transfer => !!t && borrowable(t))
      .slice(0, n);
  return card.transfers.filter(borrowable).slice(0, n);
}

/** The banner as {heading, body}: banner_parts when the file has it, else split the string. */
export function bannerParts(card: Card | undefined): Banner | null {
  if (!card) return null;
  if (card.banner_parts?.heading && card.banner_parts.body) return card.banner_parts;
  const b = card.banner;
  if (!b) return null;
  if (typeof b !== "string") return b.heading && b.body ? b : null;
  const i = b.indexOf(":");
  if (i < 0) return { heading: b, body: "" };
  const body = b.slice(i + 1).trim();
  return { heading: b.slice(0, i), body: body.charAt(0).toUpperCase() + body.slice(1) };
}

/**
 * The precomputed card for "<gene>, direction not known": transfers["scn2a_unknown"] in the
 * shipped file (the earlier "SCN2A:unknown" spelling is accepted too); its texts share the key.
 */
export function gatedCardKey(g: Graph, gene: string): string | undefined {
  return [`${gene.toLowerCase()}_unknown`, `${gene}:unknown`].find((k) => k in g.cards);
}
export function gatedCardFor(g: Graph, gene: string): Card | undefined {
  const k = gatedCardKey(g, gene);
  return k ? g.cards[k] : undefined;
}

/** A variant whose lab studies disagree, as the conflicts table records it. */
export function conflictForVariant(g: Graph, gene: string, canonical: string) {
  return g.conflicts.find(
    (c) => c.gene === gene && !!c.variant && canonicalVariant(c.variant) === canonical,
  );
}

/** Code-checked claims about one variant of a gene (any direction). */
export function claimsForVariant(g: Graph, gene: string, canonical: string) {
  return g.claims.filter(
    (c) => c.gene === gene && !!c.variant && canonicalVariant(c.variant) === canonical,
  );
}

/** The steps a card already holds, as labels, for the proposal's "what we offer" line. */
export const heldStations = (card: Card | undefined) =>
  Object.entries(card?.stations ?? {})
    .filter(([, st]) => st.state === "have")
    .map(([k]) => STATION_LABEL[k] ?? k);

/** Genes that ask "Which direction?" (alias table flag). */
export const isDirectionStepGene = (g: Graph, gene: string) =>
  g.aliases.some((a) => a.direction_step && a.gene === gene);

/** "Named in the same study" rows for a card: its own co-listings, grouped by study. */
export function coListingsFor(
  g: Graph,
  card: Card | undefined,
  lineKey: string | null,
  gene: string | null = null,
) {
  const named = card?.named_in_same_study ?? [];
  const sharedKind = (nct: string) =>
    ["registry", "eligible_gene_list", "natural_history"].includes(studyByNct(g, nct)?.kind ?? "");
  const mine = g.co_listings.filter((c) =>
    lineKey
      ? c.line === lineKey && named.includes(c.nct)
      : !!gene && c.gene === gene && sharedKind(c.nct),
  );
  const byNct = new Map<string, typeof mine>();
  for (const c of mine) byNct.set(c.nct, [...(byNct.get(c.nct) ?? []), c]);
  return [...byNct.entries()].map(([nct, rows]) => {
    const study = studyByNct(g, nct);
    const all = g.co_listings.filter((c) => c.nct === nct);
    // Where each gene is named in the record: the sentence says it field by field.
    const byField = new Map<string, string[]>();
    for (const c of all) {
      const list = byField.get(c.matched_field) ?? [];
      if (!list.includes(c.gene)) list.push(c.gene);
      byField.set(c.matched_field, list);
    }
    const genes = [...new Set(all.map((c) => c.gene))].sort();
    const fields = [...byField.entries()].map(([field, gs]) => ({ field, genes: gs.sort() }));
    const eligibilityAny = all.some((r) => r.matched_field === "eligibility_inclusion");
    const humanCheck = all.some((r) => r.human_check);
    const caveat = rows.find((r) => r.caveat)?.caveat ?? all.find((r) => r.caveat)?.caveat ?? null;
    const retrieved =
      rows.find((r) => r.retrieved)?.retrieved ??
      study?.retrieved ??
      study?.source?.retrieved ??
      null;
    const kind = rows.find((r) => r.kind)?.kind ?? study?.kind ?? null;
    return { nct, study, genes, fields, eligibilityAny, humanCheck, caveat, retrieved, kind };
  });
}

export const FIELD_PHRASE: Record<string, string> = {
  conditions: "its current condition list includes",
  keywords: "its keywords name",
  eligibility_inclusion: "its inclusion text names",
};

/** The pipeline's cluster a line belongs to (meta.cluster_groups / mechanism_view keys). */
export const clusterKeyOf = (g: Graph, line: Line) =>
  line.cluster_group ??
  g.meta.cluster_groups?.find((c) => c.line_keys.includes(line.key))?.key ??
  null;

/**
 * The clusters a mechanism search matches, ranked as the file ranks them (shared assets):
 * "sodium channel" alone matches both directions; a direction narrows to one.
 */
export function clustersForMechanism(g: Graph, mechanism: string, direction?: string | null) {
  const keys = new Set(
    g.lines
      .filter((l) => l.mechanism === mechanism && (!direction || l.direction === direction))
      .map((l) => clusterKeyOf(g, l))
      .filter((k): k is string => !!k),
  );
  return g.mechanism_view.filter((c) => keys.has(c.key));
}

/** Live NIH RePORTER projects whose title names the gene (titles and organisations only). */
export const fundingForGene = (g: Graph, gene: string) => g.funding.filter((f) => f.gene === gene);

export function counts(g: Graph) {
  const c = g.meta.counts ?? {};
  return {
    lines: c.lines ?? g.lines.length,
    genes: c.genes ?? new Set(g.lines.map((l) => l.gene)).size,
    organisations: c.organisations ?? g.organisations.length,
    studies: c.studies ?? g.studies.length,
    assets: c.assets ?? g.assets.length,
    papers: c.papers ?? g.papers.length,
    claims: c.claims ?? g.claims.length,
    edges: g.edges.length,
  };
}

export async function loadGraph(): Promise<Graph> {
  const res = await fetch(`${import.meta.env.BASE_URL}graph.json`, { cache: "no-cache" });
  if (!res.ok) throw new Error(`graph.json ${res.status}`);
  const raw = (await res.json()) as Raw;
  const g = adapt(raw);
  if (g.lines.length === 0) throw new Error("graph.json has no lines");
  return g;
}

// Turns graph.json into the node/link lists the canvas draws (web/src/graph/PolarisCanvas.tsx
// contract) and picks the subgraph a view shows. Node ids are the dataset's typed ids
// ("line:scn2a_loss", "org:familiescn2a", "study:NCT…", "asset:…", "paper:<pmid>",
// "conflict:<id>"); nothing here invents a relation.
import type { CanvasLink, CanvasNode } from "./graph/PolarisCanvas";
import type { Edge, Graph, Line } from "./types";
import { groupOf } from "./data";

export type NodeKind = CanvasNode["kind"];

export const KIND_WORD: Record<NodeKind, string> = {
  line: "Community (condition)",
  organisation: "Patient organisation",
  study: "Study record",
  asset: "Research asset",
  paper: "Paper",
  conflict: "Sources disagree",
};

const groupFor = (l: Line | undefined): CanvasNode["group"] => {
  if (!l) return "other";
  const g = groupOf(l).id;
  return g === "gain" || g === "loss" ? g : g === "other" ? "non_channel" : "other";
};

// The canvas's link vocabulary; kinds it does not name are passed through unchanged.
const LINK_KIND: Record<string, string> = {
  holds_asset: "owns",
  organisation: "owns",
  co_listed_in: "co_listed",
  conflict: "disputes",
  claim: "claim",
  claim_review: "claim",
  claim_clinical_inference: "claim",
  cited_source: "claim",
  needs_expert_check: "viable",
};

export interface CanvasModel {
  nodes: CanvasNode[];
  links: CanvasLink[];
  byId: Map<string, CanvasNode>;
  /** Every edge touching a node id, both directions. */
  edgesOf: Map<string, Edge[]>;
}

/** The line a satellite belongs to (first edge from a line hub to it). */
function lineKeyOf(g: Graph, id: string): string | undefined {
  const e = g.edges.find((e) => e.object === id && e.subject.startsWith("line:"));
  return e?.subject.slice(5);
}

export function buildCanvasModel(g: Graph): CanvasModel {
  const nodes = new Map<string, CanvasNode>();
  const lineOf = (key: string | undefined) => g.lines.find((l) => l.key === key);
  for (const l of g.lines)
    nodes.set(`line:${l.key}`, {
      id: `line:${l.key}`,
      kind: "line",
      label: l.label,
      group: groupFor(l),
      lineKey: l.key,
      direction: l.direction,
    });
  for (const o of g.organisations) {
    const id = `org:${o.key}`;
    const lk = o.lines[0];
    nodes.set(id, {
      id,
      kind: "organisation",
      label: o.name,
      group: groupFor(lineOf(lk)),
      lineKey: lk,
    });
  }
  for (const s of g.studies) {
    const id = `study:${s.nct}`;
    const lk = lineKeyOf(g, id);
    nodes.set(id, { id, kind: "study", label: s.name, group: groupFor(lineOf(lk)), lineKey: lk });
  }
  for (const a of g.assets) {
    const id = `asset:${a.id}`;
    const lk =
      a.owner_line ?? lineKeyOf(g, id) ?? g.lines.find((l) => l.gene === a.owner_gene)?.key;
    nodes.set(id, { id, kind: "asset", label: a.label, group: groupFor(lineOf(lk)), lineKey: lk });
  }
  for (const p of g.papers) {
    const id = `paper:${p.pmid}`;
    const lk = lineKeyOf(g, id);
    nodes.set(id, {
      id,
      kind: "paper",
      label: `PMID ${p.pmid}`,
      group: groupFor(lineOf(lk)),
      lineKey: lk,
    });
  }
  for (const c of g.conflicts) {
    const l = g.lines.find((x) => x.key === c.line) ?? g.lines.find((x) => x.gene === c.gene);
    if (!l) continue;
    const id = `conflict:${c.id}`;
    nodes.set(id, {
      id,
      kind: "conflict",
      label: `Sources disagree: ${c.gene}${c.variant ? " " + c.variant : ""}`,
      group: groupFor(l),
      lineKey: l.key,
    });
  }
  const links: CanvasLink[] = [];
  const seen = new Set<string>();
  const edgesOf = new Map<string, Edge[]>();
  for (const e of g.edges) {
    if (!nodes.has(e.subject) || !nodes.has(e.object)) continue;
    edgesOf.set(e.subject, [...(edgesOf.get(e.subject) ?? []), e]);
    edgesOf.set(e.object, [...(edgesOf.get(e.object) ?? []), e]);
    const k = `${e.subject}|${e.predicate}|${e.object}`;
    if (seen.has(k)) continue;
    seen.add(k);
    links.push({
      source: e.subject,
      target: e.object,
      kind: LINK_KIND[e.predicate] ?? e.predicate,
    });
  }
  // A node nothing links to would float alone: it is left off the canvas (hubs always stay).
  const linked = new Set(links.flatMap((l) => [l.source, l.target]));
  for (const [id, n] of nodes) if (n.kind !== "line" && !linked.has(id)) nodes.delete(id);
  return { nodes: [...nodes.values()], links, byId: nodes, edgesOf };
}

/** A node plus every node an edge connects it to. */
export function neighbourhood(m: CanvasModel, id: string): Set<string> {
  const out = new Set<string>([id]);
  for (const e of m.edgesOf.get(id) ?? []) {
    out.add(e.subject);
    out.add(e.object);
  }
  return out;
}

/** A form's subgraph: its hub, its satellites, and the hubs it has transfer edges with. */
export function subgraphForLine(m: CanvasModel, key: string): Set<string> {
  return neighbourhood(m, `line:${key}`);
}

/** The hubs of several lines with their satellites (a gene's forms, a cluster, a picker). */
export function subgraphForLines(m: CanvasModel, keys: string[]): Set<string> {
  const out = new Set<string>();
  for (const k of keys) for (const id of neighbourhood(m, `line:${k}`)) out.add(id);
  return out;
}

// --- Edge words --------------------------------------------------------------------------

export const EDGE_STYLE: Record<string, { word: string; short: string }> = {
  holds_asset: { word: "holds this asset", short: "holds" },
  organisation: { word: "patient organisation", short: "organisation" },
  viable: { word: "can borrow", short: "borrow" },
  needs_expert_check: { word: "could borrow after an expert check", short: "expert check" },
  already_open: { word: "already open to both", short: "already open" },
  claim: { word: "lab-study claim (found by AI, checked by code)", short: "lab claim" },
  claim_review: {
    word: "review-article claim (found by AI, checked by code)",
    short: "review claim",
  },
  claim_clinical_inference: {
    word: "clinical-inference claim (found by AI, checked by code)",
    short: "clinical claim",
  },
  blocked: { word: "blocked: opposite direction", short: "blocked" },
  not_shared: { word: "not shared (different biology)", short: "not shared" },
  co_listed_in: { word: "named in the same study", short: "named in" },
  cited_source: { word: "cited source", short: "cited" },
  conflict: { word: "sources disagree", short: "disputes" },
};
export const edgeStyle = (p: string) =>
  EDGE_STYLE[p] ?? { word: p.replace(/_/g, " "), short: p.replace(/_/g, " ") };

/** Plain words for an edge's provenance fields (never internal jargon). */
export const KNOWLEDGE_WORD: Record<string, string> = {
  prediction: "result of the share-or-block rule",
  observation: "read from the record",
  knowledge_assertion: "stated in the paper",
};
export const TIER_WORD: Record<number, string> = { 1: "direct source", 2: "listing only" };

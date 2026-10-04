// Search over the alias table. Matching happens in the browser; nothing is sent anywhere.
import type { Alias, Conflict, Graph } from "./types";
import { VARIANT_TOKEN, canonicalVariant } from "./variants";

export const norm = (s: string) =>
  s
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[‐-―]/g, "-")
    .replace(/\s+/g, " ")
    .trim()
    // "OMIM 613721", "orpha: 1934" → the ID form the alias table uses
    .replace(/^(omim|orpha|mondo|hgnc|hp|g2p)\s*:?\s*(\d+)$/, "$1:$2");

export type Resolution =
  | { kind: "line"; line: string; alias?: Alias }
  | { kind: "direction"; gene: string }
  | { kind: "picker"; alias: Alias }
  | { kind: "mechanism"; mechanism: string; direction?: string | null }
  | { kind: "unknown_variant"; gene: string; variant: string }
  | { kind: "mixed"; gene: string; variant: string; pmid?: string | null }
  | { kind: "gap"; query: string };

export interface Index {
  exact: Map<string, Alias>;
  variants: Map<string, Alias>; // "scn2a|r853q" -> alias
  byVariant: Map<string, Alias[]>; // "r853q" -> every gene's alias for that variant name
  genes: Map<string, Alias>; // "scn2a" -> the gene alias
  stepGenes: Set<string>; // genes that ask "Which direction?"
  conflicts: Map<string, Conflict>; // "scn2a|p1658s" -> a variant whose lab studies disagree
  all: Alias[];
}

const targetOf = (a: Alias) =>
  a.genes?.length
    ? `genes:${[...a.genes].sort().join(",")}`
    : a.line || a.gene || a.mechanism || "";

/**
 * Two aliases spelt the same but pointing at different targets never resolve first-wins:
 * they fold into one picker alias listing every gene involved.
 */
function merge(a: Alias, b: Alias): Alias {
  if (targetOf(a) === targetOf(b)) return a;
  const genes = new Set<string>([...(a.genes ?? []), ...(b.genes ?? [])]);
  if (a.gene) genes.add(a.gene);
  if (b.gene) genes.add(b.gene);
  return { term: a.term, kind: a.kind === b.kind ? a.kind : "symptom", genes: [...genes].sort() };
}

export function buildIndex(g: Graph): Index {
  const exact = new Map<string, Alias>();
  const variants = new Map<string, Alias>();
  const byVariant = new Map<string, Alias[]>();
  const genes = new Map<string, Alias>();
  const stepGenes = new Set(
    g.aliases.filter((a) => a.direction_step && a.gene).map((a) => a.gene!),
  );
  const put = (key: string, a: Alias) =>
    exact.set(key, exact.has(key) ? merge(exact.get(key)!, a) : a);
  for (const a of g.aliases) {
    put(norm(a.term), a);
    if (a.kind === "gene" && a.gene && !genes.has(norm(a.gene))) genes.set(norm(a.gene), a);
    if (a.kind === "variant" && a.gene) {
      const v = a.term.split(/\s+/).map(canonicalVariant).find(Boolean);
      if (v) {
        const k = `${norm(a.gene)}|${v}`;
        if (!variants.has(k)) {
          variants.set(k, a);
          byVariant.set(v, [...(byVariant.get(v) ?? []), a]);
        }
      }
    }
  }
  // Line keys, labels and gene symbols of lines are searchable too (dataset IDs, not typed text).
  for (const l of g.lines) {
    if (!genes.has(norm(l.gene))) {
      const a: Alias = {
        term: l.gene,
        kind: "gene",
        line: stepGenes.has(l.gene) ? null : l.key,
        gene: l.gene,
        direction_step: stepGenes.has(l.gene),
      };
      genes.set(norm(l.gene), a);
      put(norm(l.gene), a);
    }
    put(norm(l.label), { term: l.label, kind: "disease", line: l.key, gene: l.gene });
  }
  // Shared studies and assets by name: several forms may be named in one, so they open a picker
  // over the mapped genes (never a line directly).
  const mapped = new Set(g.lines.map((l) => l.gene));
  for (const st of g.studies) {
    const genes = (st.genes_named ?? []).filter((x) => mapped.has(x)).sort();
    if (genes.length) put(norm(st.name), { term: st.name, kind: "study", genes });
  }
  for (const a of g.assets) {
    const genes = a.open_to_all
      ? [...mapped].sort()
      : mapped.has(a.owner_gene)
        ? [a.owner_gene]
        : [];
    if (genes.length) put(norm(a.label), { term: a.label, kind: "study", genes });
  }
  for (const o of g.organisations) {
    const lines = g.lines.filter((l) => o.lines.includes(l.key));
    const gene = lines[0]?.gene ?? null;
    put(norm(o.name), {
      term: o.name,
      kind: "organisation",
      line: lines.length === 1 ? lines[0].key : null,
      gene,
      direction_step: lines.length > 1 || (!!gene && stepGenes.has(gene)),
    });
  }
  const conflicts = new Map<string, Conflict>();
  for (const c of g.conflicts) {
    const v = c.variant && canonicalVariant(c.variant);
    if (v) conflicts.set(`${norm(c.gene)}|${v}`, c);
  }
  return { exact, variants, byVariant, genes, stepGenes, conflicts, all: g.aliases };
}

/**
 * Where an alias leads. A gene that asks "Which direction?" is never skipped: only a
 * PMID-backed variant alias may land on a line of SCN2A, SCN8A or SCN1A directly.
 */
function fromAlias(idx: Index, a: Alias): Resolution {
  // An Orphanet group code always opens the picker, even when one of its genes is mapped: the
  // family's gene may be one of the others.
  if (a.genes?.length === 1 && !a.gene && a.kind !== "group")
    return fromAlias(idx, { ...a, genes: [], gene: a.genes[0] });
  if (a.genes?.length) return { kind: "picker", alias: a };
  const step = !!a.gene && idx.stepGenes.has(a.gene);
  if (a.kind === "variant" && a.gene && a.variant_direction === "mixed")
    return { kind: "mixed", gene: a.gene, variant: a.term.replace(/^\S+\s+/, ""), pmid: a.pmid };
  if (a.kind === "variant" && a.line && a.pmid) return { kind: "line", line: a.line, alias: a };
  // The names of one form of a split gene ("Dravet syndrome") lead to that line; gene names,
  // IDs and anything the table flags still ask "Which direction?".
  if (a.direction_step || (step && !a.line)) return { kind: "direction", gene: a.gene! };
  if (a.line) return { kind: "line", line: a.line };
  if (a.mechanism) return { kind: "mechanism", mechanism: a.mechanism, direction: a.direction };
  return { kind: "gap", query: a.term };
}

export function resolve(idx: Index, raw: string): Resolution {
  const q = norm(raw);
  if (!q) return { kind: "gap", query: raw };
  const hit = idx.exact.get(q);
  if (hit) return fromAlias(idx, hit);

  // Variant forms: "<gene> <variant>" in one- or three-letter notation, or a bare variant.
  const tokens = q.split(" ");
  const geneTok = tokens.find((t) => idx.genes.has(t));
  const varTok = tokens
    .filter((t) => t !== geneTok)
    .map((t) => t.match(VARIANT_TOKEN)?.[0])
    .find(Boolean);
  const canon = varTok ? canonicalVariant(varTok) : null;
  if (geneTok && canon) {
    const v = idx.variants.get(`${geneTok}|${canon}`);
    if (v) return fromAlias(idx, v);
    const geneAlias = idx.genes.get(geneTok)!;
    const conflict = idx.conflicts.get(`${geneTok}|${canon}`);
    if (conflict) {
      const gene = geneAlias.gene ?? geneTok.toUpperCase();
      // Gain/loss logic applies to channel genes only; a non-channel conflict opens the line.
      if (idx.stepGenes.has(gene)) return { kind: "mixed", gene, variant: conflict.variant! };
      if (geneAlias.line) return { kind: "line", line: geneAlias.line };
    }
    return {
      kind: "unknown_variant",
      gene: geneAlias.gene ?? geneTok.toUpperCase(),
      variant: varTok!.toUpperCase().replace(/^P\./, "p."),
    };
  }
  if (!geneTok && canon && tokens.length === 1) {
    const hits = idx.byVariant.get(canon) ?? [];
    if (hits.length === 1) return fromAlias(idx, hits[0]);
    if (hits.length > 1)
      return {
        kind: "picker",
        alias: {
          term: hits[0].term.replace(/^\S+\s+/, ""),
          kind: "variant",
          genes: [...new Set(hits.map((h) => h.gene!))].sort(),
        },
      };
  }
  if (geneTok && tokens.length === 1) return fromAlias(idx, idx.genes.get(geneTok)!);

  // A single alias term contained in the query ("my son has SCN2A").
  let best: Alias | null = null;
  for (const [term, a] of idx.exact) {
    if (term.length >= 4 && q.includes(term) && (!best || term.length > norm(best.term).length))
      best = a;
  }
  if (best) return fromAlias(idx, best);
  return { kind: "gap", query: raw };
}

/** Up to n suggestions for a typed prefix, distinct by target. */
export function suggest(idx: Index, raw: string, n = 8): Alias[] {
  const q = norm(raw);
  if (q.length < 2) return [];
  const out: Alias[] = [];
  const seen = new Set<string>();
  const push = (a: Alias) => {
    const k = `${a.kind}|${a.line ?? ""}|${a.gene ?? ""}|${a.mechanism ?? ""}|${a.orpha ?? ""}|${a.term}`;
    if (seen.has(k)) return;
    seen.add(k);
    out.push(a);
  };
  for (const [term, a] of idx.exact) if (term.startsWith(q)) push(a);
  for (const [term, a] of idx.exact) if (!term.startsWith(q) && term.includes(q)) push(a);
  return out.slice(0, n);
}

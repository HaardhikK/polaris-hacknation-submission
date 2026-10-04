// "Explain every edge": the facts of one node of the map and every link that touches it,
// grouped by relationship, each with its source, PMID / NCT and date. Paper titles and study
// record fields that may name a medicine are never shown here (family path).
import type { Graph } from "../types";
import { assetById, lineByKey, studyByNct } from "../data";
import { nctUrl, pubmedUrl } from "../links";
import { type CanvasModel, KIND_WORD, KNOWLEDGE_WORD, TIER_WORD, edgeStyle } from "../graphModel";
import { Ext, asOf } from "../shared/Layout";

const RULE_SOURCE = "transfer rule over the committed seed and claims";

/** The relationship as a sentence fragment about the other node, seen from this node. */
const phrase = (predicate: string, outgoing: boolean) => {
  switch (predicate) {
    case "viable":
      return outgoing ? "can borrow from" : "can borrow from this one:";
    case "needs_expert_check":
      return outgoing ? "could borrow after an expert check from" : "could borrow from this one:";
    case "already_open":
      return "already open to both:";
    case "blocked":
      return "blocked, opposite direction:";
    case "not_shared":
      return "not shared, different biology:";
    case "holds_asset":
      return outgoing ? "holds" : "held by";
    case "organisation":
      return outgoing ? "patient organisation" : "organisation of";
    case "co_listed_in":
      return outgoing ? "named in the same study" : "names";
    case "conflict":
      return outgoing ? "sources disagree" : "about";
    default:
      return edgeStyle(predicate).word;
  }
};

export function NodePanel({
  graph,
  model,
  id,
  onOpenNode,
  onOpenLine,
  onOpenEdge,
}: {
  graph: Graph;
  model: CanvasModel;
  id: string;
  onOpenNode: (id: string) => void;
  onOpenLine: (key: string) => void;
  onOpenEdge: (link: { source: string; target: string; kind: string }) => void;
}) {
  const node = model.byId.get(id);
  if (!node) return <p className="muted">This node is not in the data file.</p>;
  const ref = id.slice(id.indexOf(":") + 1);
  // One row per (other node, relationship): the pipeline writes one edge per asset.
  const seen = new Set<string>();
  const rows = (model.edgesOf.get(id) ?? []).filter((e) => {
    const k = `${e.subject}|${e.predicate}|${e.object}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  const groups = new Map<string, typeof rows>();
  for (const e of rows) groups.set(e.predicate, [...(groups.get(e.predicate) ?? []), e]);
  const nameOf = (nid: string) => model.byId.get(nid)?.label ?? nid;

  return (
    <div className="stack">
      <section>
        <p className="kicker">{KIND_WORD[node.kind]}</p>
        <h1>{node.label}</h1>
        <Facts graph={graph} kind={node.kind} refId={ref} onOpenLine={onOpenLine} />
      </section>
      <section aria-labelledby="edges-title">
        <h2 id="edges-title">
          {rows.length} link{rows.length === 1 ? "" : "s"} on the map
        </h2>
        {[...groups.entries()].map(([predicate, es]) => (
          <details className="level" key={predicate} open={groups.size <= 3}>
            <summary>
              {es.length} · {edgeStyle(predicate).short}
            </summary>
            <ul className="list small">
              {es.map((e, i) => {
                const outgoing = e.subject === id;
                const otherId = outgoing ? e.object : e.subject;
                const rule = e.source.label === RULE_SOURCE;
                return (
                  <li key={`${otherId}-${i}`}>
                    <span className="sign" aria-hidden="true">
                      ·
                    </span>
                    <span>
                      <span className="muted">{phrase(predicate, outgoing)}</span>{" "}
                      <button
                        type="button"
                        className="inline-flex min-h-11 cursor-pointer items-center border-0 bg-transparent p-0 text-left font-semibold text-accent underline underline-offset-2"
                        onClick={() => onOpenNode(otherId)}
                      >
                        {nameOf(otherId)}
                      </button>
                      {e.note && <span className="muted"> · {e.note}</span>}{" "}
                      <button
                        type="button"
                        className="inline-flex min-h-11 cursor-pointer items-center border-0 bg-transparent p-0 text-accent underline underline-offset-2"
                        onClick={() =>
                          onOpenEdge({ source: e.subject, target: e.object, kind: e.predicate })
                        }
                      >
                        Evidence
                      </button>
                      <br />
                      <span className="muted">
                        {rule ? (
                          "Share-or-block rule over the cited claims"
                        ) : (
                          <>
                            Source: <Ext href={e.source.url}>{e.source.label}</Ext>
                            {e.tier ? ` · ${TIER_WORD[e.tier] ?? ""}` : ""}
                            {e.knowledge_level
                              ? ` · ${KNOWLEDGE_WORD[e.knowledge_level] ?? ""}`
                              : ""}
                          </>
                        )}{" "}
                        · {asOf(e.retrieved)}
                      </span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </details>
        ))}
      </section>
    </div>
  );
}

function Facts({
  graph,
  kind,
  refId,
  onOpenLine,
}: {
  graph: Graph;
  kind: keyof typeof KIND_WORD;
  refId: string;
  onOpenLine: (key: string) => void;
}) {
  switch (kind) {
    case "line": {
      const l = lineByKey(graph, refId);
      if (!l) return null;
      return (
        <>
          <p>
            {l.gene} · {l.gloss}
          </p>
          <button type="button" className="btn primary" onClick={() => onOpenLine(l.key)}>
            Open this condition
          </button>
        </>
      );
    }
    case "organisation": {
      const o = graph.organisations.find((x) => x.key === refId);
      if (!o) return null;
      return (
        <p className="small">
          <Ext href={o.url}>Website</Ext>
          {o.contact_page && (
            <>
              {" "}
              · <Ext href={o.contact_page}>Contact page</Ext>
            </>
          )}{" "}
          · for {o.lines.map((k) => lineByKey(graph, k)?.label ?? k).join("; ")} ·{" "}
          {asOf(o.last_verified)}
        </p>
      );
    }
    case "study": {
      const s = studyByNct(graph, refId);
      if (!s) return null;
      return (
        <p className="small">
          <Ext href={nctUrl(s.nct)}>{s.nct}</Ext> · {s.kind.replace(/_/g, " ")}
          {s.overall_status ? ` · status ${s.overall_status.toLowerCase().replace(/_/g, " ")}` : ""}
          {s.start_date ? ` · started ${s.start_date}` : ""}
          {s.lead_sponsor ? ` · run by ${s.lead_sponsor}` : ""}
          {s.genes_named?.length ? ` · names ${s.genes_named.join(", ")}` : ""} ·{" "}
          {asOf(s.retrieved ?? s.source?.retrieved)}
        </p>
      );
    }
    case "asset": {
      const a = assetById(graph, refId);
      if (!a) return null;
      return (
        <p className="small">
          {a.type.replace(/_/g, " ")} · step: {a.station.replace(/_/g, " ")} · from the{" "}
          {a.owner_gene} community
          {a.scope === "gene" ? " (shared by every condition of the gene)" : ""} · Source:{" "}
          <Ext href={a.source.url}>{a.source.label}</Ext> ·{" "}
          {asOf(a.last_verified ?? a.source.retrieved)}
        </p>
      );
    }
    case "paper": {
      const p = graph.papers.find((x) => x.pmid === refId);
      return (
        <p className="small">
          <Ext href={pubmedUrl(refId)}>PMID {refId}</Ext>
          {p?.journal ? ` · ${p.journal}` : ""}
          {p?.year ? `, ${p.year}` : ""}
          {p?.genes_mentioned?.length ? ` · mentions ${p.genes_mentioned.join(", ")}` : ""} ·{" "}
          {asOf(p?.retrieved)}
        </p>
      );
    }
    case "conflict": {
      const c = graph.conflicts.find((x) => x.id === refId);
      if (!c) return null;
      return (
        <>
          <ul className="list small">
            {c.sides.map((s, i) => (
              <li key={i}>
                <span className="sign">–</span>
                <span>
                  {s.says} (<Ext href={s.source.url}>{s.source.label}</Ext>)
                </span>
              </li>
            ))}
          </ul>
          {c.note && <p className="small muted">{c.note}</p>}
        </>
      );
    }
  }
}

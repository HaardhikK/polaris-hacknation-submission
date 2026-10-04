// The rail's two index pages, for when nothing has been searched or selected yet:
// "Pick your condition" (the seven conditions as chips) and "Evidence on the map" (every
// community's links, grouped by relationship word, each row opening its evidence page).
import type { Graph } from "../types";
import { groupOf } from "../data";
import { type CanvasModel, edgeStyle } from "../graphModel";

export function ConditionPicker({
  graph,
  onPick,
}: {
  graph: Graph;
  onPick: (key: string) => void;
}) {
  return (
    <section aria-labelledby="pick-title">
      <h1 id="pick-title">Pick your condition</h1>
      <p className="small muted">Each chip opens that condition's page.</p>
      <div className="chips">
        {graph.lines.map((l) => (
          <button
            key={l.key}
            type="button"
            className="chip !h-auto py-2 text-left"
            onClick={() => onPick(l.key)}
          >
            <span className="grid">
              <span>{l.label}</span>
              <span className="text-xs font-normal text-ink-2">
                {l.gene} · {groupOf(l).title}
              </span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

const ORDER = [
  "blocked",
  "viable",
  "needs_expert_check",
  "already_open",
  "not_shared",
  "co_listed_in",
  "claim",
  "claim_review",
  "claim_clinical_inference",
  "cited_source",
  "holds_asset",
  "organisation",
  "conflict",
];

export function EvidenceIndex({
  graph,
  model,
  onOpenEdge,
}: {
  graph: Graph;
  model: CanvasModel;
  onOpenEdge: (link: { source: string; target: string; kind: string }) => void;
}) {
  const nameOf = (id: string) => model.byId.get(id)?.label ?? id;
  return (
    <section aria-labelledby="evidence-title">
      <h1 id="evidence-title">Evidence on the map</h1>
      <p className="small muted">
        Every link of every community, with its source. Open a community, then a link.
      </p>
      {graph.lines.map((l) => {
        const id = `line:${l.key}`;
        const seen = new Set<string>();
        const rows = (model.edgesOf.get(id) ?? []).filter((e) => {
          const k = `${e.subject}|${e.predicate}|${e.object}`;
          if (seen.has(k)) return false;
          seen.add(k);
          return true;
        });
        const groups = new Map<string, typeof rows>();
        for (const e of rows) groups.set(e.predicate, [...(groups.get(e.predicate) ?? []), e]);
        const keys = [...groups.keys()].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b));
        return (
          <details className="level" key={l.key}>
            <summary>
              {l.label}
              <span className="muted ml-2 font-normal">
                {rows.length} link{rows.length === 1 ? "" : "s"}
              </span>
            </summary>
            {keys.map((k) => (
              <div key={k} className="mt-1 mb-2">
                <p className="kicker m-0">
                  {edgeStyle(k).short} · {groups.get(k)!.length}
                </p>
                <ul className="list small">
                  {groups.get(k)!.map((e, i) => {
                    const other = e.subject === id ? e.object : e.subject;
                    return (
                      <li key={`${other}-${i}`}>
                        <span className="sign">·</span>
                        <button
                          type="button"
                          className="inline-flex min-h-11 cursor-pointer items-center border-0 bg-transparent p-0 text-left text-accent underline underline-offset-2"
                          onClick={() =>
                            onOpenEdge({ source: e.subject, target: e.object, kind: e.predicate })
                          }
                        >
                          {nameOf(other)}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </details>
        );
      })}
    </section>
  );
}

// The map as stacked lists, no SVG: on the home page and the condition page under 640 px,
// below the display-only canvas.
import type { Card, Graph, Line } from "../types";
import { GROUPS, STATION_LABEL, assetById, lineByKey, plain } from "../data";

export function StationList({ graph, card }: { graph: Graph; card: Card }) {
  return (
    <div>
      {[
        "diagnosis",
        "registry",
        "natural_history",
        "mechanism",
        "model",
        "outcome_measure",
        "trial",
      ]
        .filter((k) => k in card.stations)
        .map((key) => [key, card.stations[key]] as const)
        .map(([key, st]) => {
          const borrow = card.transfers.find((t) => t.status === "viable" && t.station === key);
          const owner =
            borrow &&
            (lineByKey(graph, borrow.owner_line ?? "")?.label ??
              `the ${borrow.owner_gene} community`);
          return (
            <div className="stacked-station" key={key}>
              <strong>{STATION_LABEL[key] ?? key}</strong>
              <div className="small">
                {st.state === "have" && (
                  <>
                    <span className="sign ok">✓</span> Have: {plain(st.why)}
                  </>
                )}
                {st.state === "missing" && (
                  <>
                    <span className="sign warn">○</span> Missing
                    {borrow
                      ? `: borrow from ${owner}: ${assetById(graph, borrow.asset_id)?.label ?? borrow.asset_id}`
                      : ""}
                  </>
                )}
                {st.state === "unknown" && (
                  <>
                    <span className="sign unknown">?</span> Not known: {plain(st.why)}
                  </>
                )}
              </div>
            </div>
          );
        })}
    </div>
  );
}

/** The cluster groups as headed lists: the user's group bold, the others dimmed. */
export function ClusterGroups({
  graph,
  me,
  meGene,
  onOpenLine,
}: {
  graph: Graph;
  me?: Line;
  meGene?: string; // direction not known: every form of this gene is "mine"
  onOpenLine?: (k: string) => void;
}) {
  const myGroup = me ? GROUPS.find((g) => g.test(me))?.id : null;
  const isMe = (l: Line) => me?.key === l.key || (!!meGene && l.gene === meGene);
  return (
    <div>
      <div className="cluster-groups">
        {GROUPS.map((g) => {
          const lines = graph.lines.filter(g.test);
          if (lines.length === 0) return null;
          const mine = g.id === myGroup || (!!meGene && lines.some(isMe));
          return (
            <section
              key={g.id}
              className={`group ${mine ? "me" : me || meGene ? "dim" : ""}`}
              aria-current={mine ? "true" : undefined}
            >
              <h3>
                <span
                  className="swatch"
                  style={{
                    background: `var(--${g.id === "other" ? "other" : g.id === "unsettled" ? "ink-3" : g.id})`,
                  }}
                  aria-hidden="true"
                />
                {g.title}
              </h3>
              {lines.map((l) =>
                onOpenLine ? (
                  <button
                    key={l.key}
                    type="button"
                    className={`line-pill ${isMe(l) ? "me" : ""}`}
                    onClick={() => onOpenLine(l.key)}
                    style={{ cursor: "pointer", minHeight: 44 }}
                  >
                    {isMe(l) ? "● " : ""}
                    {l.label}
                  </button>
                ) : (
                  <span key={l.key} className={`line-pill ${isMe(l) ? "me" : ""}`}>
                    {l.label}
                  </span>
                ),
              )}
            </section>
          );
        })}
      </div>
      <p className="muted small" style={{ marginTop: 8 }}>
        Groups set by hand from cited lab studies.
      </p>
    </div>
  );
}

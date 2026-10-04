// The mechanism view for researchers and scouts: every cluster (mechanism × direction) a
// search matches, ranked by shared assets as the data file ranks them. Same data as the
// family path, a different sort: organisations (contact pages, never named people),
// registered studies by state with the sponsor's verbatim stop reason, models with their
// repository IDs, outcome measures with PMIDs, and the institutions running studies for
// two or more of the cluster's forms. No medicine names; funded projects sit behind a
// "For researchers" disclosure because grant titles may name one.
import type { Graph, MechanismCluster } from "../types";
import { lineByKey } from "../data";
import { nctUrl, pubmedUrl, safeUrl } from "../links";
import { Ext, PAUSED_SENTENCE, STOPPED_SENTENCE, asOf } from "../shared/Layout";
import { FundingList } from "./FundingList";

const STATE_WORD: Record<string, string> = {
  active: "active",
  finished_or_unknown: "finished or status unknown",
  stopped: "stopped",
  paused: "paused",
};
const BUCKETS: [string, string][] = [
  ["active", "Active (recruiting, enrolling by invitation, not yet recruiting, or active)"],
  ["finished_or_unknown", "Finished, or status not stated"],
  ["stopped", "Stopped or paused"],
];

export function MechanismView({
  graph,
  clusters,
  title,
  onOpenLine,
}: {
  graph: Graph;
  clusters: MechanismCluster[];
  title: string;
  onOpenLine: (k: string) => void;
}) {
  const ranked = [...clusters].sort((a, b) => b.shared_assets - a.shared_assets);
  return (
    <div className="stack">
      <section className="card">
        <p className="kicker">For researchers · mechanism view</p>
        <h1>{title}</h1>
        <p>
          Every gene name this mechanism hides under, with who already works on it. Ranked by the
          number of resources the conditions in a group share. A way to reach a community is its
          organisation's own pages or the study record, never a named person.
        </p>
        <p className="small muted">
          Groups set by hand from cited lab studies. Nothing here is a treatment suggestion.
        </p>
      </section>
      {ranked.length === 0 && (
        <section className="card">
          <p className="muted">No mapped group works through this mechanism yet.</p>
        </section>
      )}
      {ranked.map((c, i) => (
        <ClusterCard
          key={c.key}
          graph={graph}
          cluster={c}
          rank={ranked.length > 1 ? i + 1 : null}
          onOpenLine={onOpenLine}
        />
      ))}
    </div>
  );
}

function ClusterCard({
  graph,
  cluster: c,
  rank,
  onOpenLine,
}: {
  graph: Graph;
  cluster: MechanismCluster;
  rank: number | null; // null when only one group is shown
  onOpenLine: (k: string) => void;
}) {
  const label = (k: string) => lineByKey(graph, k)?.label ?? k;
  const studyCount = Object.values(c.studies ?? {}).reduce((n, l) => n + l.length, 0);
  return (
    <section className="card" aria-labelledby={`cluster-${c.key}`}>
      <p className="kicker">
        {rank ? `Group ${rank} · ` : ""}
        {c.shared_assets} shared resource{c.shared_assets === 1 ? "" : "s"} · {c.genes.join(", ")}
      </p>
      <h2 id={`cluster-${c.key}`}>{c.label}</h2>

      <h3>Conditions in this group</h3>
      <div className="chips">
        {c.lines.map((k) => (
          <button key={k} type="button" className="chip" onClick={() => onOpenLine(k)}>
            {label(k)}
          </button>
        ))}
      </div>

      <h3>Patient organisations</h3>
      {c.organisations.length === 0 ? (
        <p className="small muted">No organisation recorded for this group.</p>
      ) : (
        <ul className="list small">
          {c.organisations.map((o) => (
            <li key={o.key}>
              <span className="sign">■</span>
              <span>
                <strong>{o.name}</strong>:{" "}
                {o.contact_page && safeUrl(o.contact_page) ? (
                  <>
                    <Ext href={o.contact_page}>contact page</Ext> · <Ext href={o.url}>website</Ext>
                  </>
                ) : (
                  <>
                    <Ext href={o.url}>website</Ext> (contact route: its home page; no contact page
                    recorded)
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3>Registered studies ({studyCount})</h3>
      {studyCount === 0 && (
        <p className="small muted">No study record is assigned to this group.</p>
      )}
      {BUCKETS.map(([bucket, heading]) => {
        const rows = c.studies?.[bucket] ?? [];
        if (rows.length === 0) return null;
        return (
          <div key={bucket}>
            <p className="small muted" style={{ margin: "8px 0 4px" }}>
              {heading}
            </p>
            <ul className="list small">
              {rows.map((s) => {
                const state = s.state ?? bucket;
                const rec = graph.studies.find((x) => x.nct === s.nct);
                return (
                  <li key={s.nct}>
                    <span className="sign">▲</span>
                    <span>
                      <strong>{s.name.replace(` (${s.nct})`, "")}</strong> (
                      <Ext href={nctUrl(s.nct)}>{s.nct}</Ext>) · {STATE_WORD[state] ?? state}
                      {s.overall_status
                        ? ` · record status '${s.overall_status.toLowerCase().replace(/_/g, " ")}'`
                        : ""}
                      {s.kind ? ` · ${s.kind.replace(/_/g, " ")}` : ""} · for{" "}
                      {s.lines.map(label).join("; ")}
                      {rec?.last_update_date ? ` · last updated ${rec.last_update_date}` : ""}
                      {rec ? ` · ${asOf(rec.retrieved ?? rec.source?.retrieved)}` : ""}.
                      {s.caveat && (
                        <>
                          {" "}
                          {s.caveat.charAt(0).toUpperCase()}
                          {s.caveat.slice(1)}.
                        </>
                      )}
                      {(state === "stopped" || state === "paused") && (
                        <details className="level">
                          <summary>For researchers: the sponsor's own words</summary>
                          <p className="small" style={{ margin: "4px 0 0" }}>
                            {s.why_stopped
                              ? `Reason in the sponsor's words: “${s.why_stopped}” `
                              : "No reason is given in the record. "}
                            {state === "paused" ? PAUSED_SENTENCE : STOPPED_SENTENCE}
                          </p>
                        </details>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}

      <h3>Lab models</h3>
      <p className="small muted" style={{ marginTop: 0 }}>
        Repository IDs only. Whether a model's own change matches a condition's direction is judged
        on each result page, not here.
      </p>
      {c.models.length === 0 ? (
        <p className="small muted">No mouse or cell model with a repository ID in this group.</p>
      ) : (
        <ul className="list small">
          {c.models.map((m) => (
            <li key={m.id}>
              <span className="sign">◆</span>
              <span>
                <Ext href={m.url}>{m.label}</Ext>
                {m.repository_id ? ` · ${m.repository_id}` : ""} · {m.owner_gene}
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3>Ways to measure improvement</h3>
      {c.outcome_measures.length === 0 ? (
        <p className="small muted">No outcome measure with a paper in this group.</p>
      ) : (
        <ul className="list small">
          {c.outcome_measures.map((m) => (
            <li key={m.id}>
              <span className="sign">◆</span>
              <span>
                {m.label} · {m.owner_gene}
                {m.pmid && (
                  <>
                    {" "}
                    · <Ext href={pubmedUrl(m.pmid)}>PMID {m.pmid}</Ext>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3>Institutions running studies for two or more of these conditions</h3>
      <p className="small muted" style={{ marginTop: 0 }}>
        Lead sponsors and study sites named in the ClinicalTrials.gov records; eligible-gene-list
        studies do not count.
      </p>
      {c.institutions.length === 0 ? (
        <p className="small muted">None in the records fetched.</p>
      ) : (
        <ul className="list small">
          {c.institutions.map((inst) => (
            <li key={inst.name}>
              <span className="sign">–</span>
              <span>
                <strong>{inst.name}</strong> · {inst.roles.join(", ")} · for{" "}
                {inst.lines.map(label).join("; ")}
              </span>
            </li>
          ))}
        </ul>
      )}

      <details className="level">
        <summary>For researchers: funded projects naming these genes (NIH RePORTER)</summary>
        <div className="small">
          {c.genes.map((gene) => (
            <FundingList key={gene} graph={graph} gene={gene} />
          ))}
        </div>
      </details>
    </section>
  );
}

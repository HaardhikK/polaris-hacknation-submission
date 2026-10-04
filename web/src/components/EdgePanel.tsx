// One edge of the map, as evidence: a plain sentence, a fact grid (relationship, source,
// retrieved, how it was checked), then the verbatim text behind it (claim quote, co-listing
// window, stop reason). Everything is read from graph.json; nothing is restated.
import type { Edge, Graph, Transfer } from "../types";
import { assetById, lineByKey, plain, studyByNct } from "../data";
import { nctUrl, pubmedUrl } from "../links";
import { type CanvasModel, edgeStyle } from "../graphModel";
import { Ext, asOf } from "../shared/Layout";

const RULE_SOURCE = "transfer rule over the committed seed and claims";
const refOf = (id: string) => id.slice(id.indexOf(":") + 1);
const list = (xs: string[]) =>
  xs.length <= 1 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;

export function EdgePanel({
  graph,
  model,
  source,
  target,
  kind,
  onOpenNode,
}: {
  graph: Graph;
  model: CanvasModel;
  source: string;
  target: string;
  kind: string;
  onOpenNode: (id: string) => void;
}) {
  const edges: Edge[] = (model.edgesOf.get(source) ?? []).filter(
    (e) => e.subject === source && e.object === target && e.predicate === kind,
  );
  const s = model.byId.get(source);
  const t = model.byId.get(target);
  if (!s || !t || edges.length === 0)
    return <p className="muted">This link is not in the data file.</p>;
  const e = edges[0];
  const sLine = source.startsWith("line:") ? lineByKey(graph, refOf(source)) : undefined;
  const tLine = target.startsWith("line:") ? lineByKey(graph, refOf(target)) : undefined;

  // Line-to-line rule edges: the transfers of the subject's card owned by the object line.
  const transfers: Transfer[] =
    sLine && tLine
      ? (graph.cards[sLine.key]?.transfers ?? []).filter(
          (x) =>
            (x.owner_line ? x.owner_line === tLine.key : x.owner_gene === tLine.gene) &&
            (kind === "blocked" ? x.blocked : x.status === kind),
        )
      : [];
  const assetNames = transfers.map((x) => assetById(graph, x.asset_id)?.label ?? x.asset_id);
  const claimIds = new Set(transfers.flatMap((x) => x.evidence_claim_ids));
  const pmid = /PMID (\d+)/.exec(e.source.label)?.[1] ?? null;
  // Claim edges: the code-checked claims of that paper about the subject line.
  const claims = graph.claims.filter((c) =>
    kind.startsWith("claim") && sLine && pmid
      ? c.pmid === pmid &&
        c.gene === sLine.gene &&
        (graph.lines.filter((l) => l.gene === sLine.gene).length === 1 ||
          c.direction === sLine.direction)
      : claimIds.has(c.claim_id),
  );
  const nct = target.startsWith("study:") ? refOf(target) : null;
  const coRows =
    kind === "co_listed_in" && sLine && nct
      ? graph.co_listings.filter((c) => c.nct === nct && c.line === sLine.key)
      : [];
  const coGenes = nct
    ? [...new Set(graph.co_listings.filter((c) => c.nct === nct).map((c) => c.gene))].sort()
    : [];
  const study = nct ? studyByNct(graph, nct) : undefined;
  const asset = target.startsWith("asset:") ? assetById(graph, refOf(target)) : undefined;
  const conflict = target.startsWith("conflict:")
    ? graph.conflicts.find((c) => c.id === refOf(target))
    : undefined;

  const sentence = (() => {
    const what = assetNames.length ? list(assetNames) : "its resources";
    switch (kind) {
      case "blocked":
        return `${s.label} cannot borrow ${what} from ${t.label}: the two work in opposite directions.`;
      case "not_shared":
        return `${s.label} does not share ${what} with ${t.label}: ${transfers[0] ? plain(transfers[0].reason) : "different biology."}`;
      case "viable":
        return `${s.label} can borrow ${what} from ${t.label}.`;
      case "needs_expert_check":
        return `${s.label} could borrow ${what} from ${t.label} after an expert check.`;
      case "already_open":
        return `${what} ${assetNames.length === 1 ? "is" : "are"} already open to ${s.label} and ${t.label}.`;
      case "co_listed_in":
        return coGenes.length > 1
          ? `${study?.name ?? t.label} names ${list(coGenes)} in one study record.`
          : `${study?.name ?? t.label} names ${coGenes[0] ?? sLine?.gene ?? ""} in its study record.`;
      case "claim":
      case "claim_review":
      case "claim_clinical_inference":
        return `A ${kind === "claim" ? "lab study" : kind === "claim_review" ? "review article" : "clinical report"} (PMID ${pmid ?? "?"}) supports the direction of ${s.label}.`;
      case "cited_source":
        return `${s.label} cites ${t.label} as a source.`;
      case "holds_asset":
        return `${s.label} holds ${t.label}.`;
      case "organisation":
        return `${t.label} is a patient organisation for ${s.label}.`;
      case "conflict":
        return `Sources disagree about ${s.label}.`;
      default:
        return `${s.label} ${edgeStyle(kind).word} ${t.label}.`;
    }
  })();

  const checked = (() => {
    switch (kind) {
      case "blocked":
        return "rule: opposite known directions (lab claim checked by code)";
      case "viable":
      case "needs_expert_check":
      case "already_open":
        return "rule: same mechanism, same known direction, or a resource open to both";
      case "not_shared":
        return "rule: different biology or direction";
      case "co_listed_in":
        return `study record, field: ${[...new Set(coRows.map((c) => c.matched_field.replace(/_/g, " ")))].join(", ") || "record"}`;
      case "claim":
        return "lab claim found by AI, checked by code";
      case "claim_review":
      case "claim_clinical_inference":
        return "claim found by AI, checked by code (not a lab assay)";
      default:
        return "read from the record or page";
    }
  })();

  const isRule = e.source.label === RULE_SOURCE;
  const cited = transfers.find((x) => x.cited_pmid)?.cited_pmid ?? null;
  const retrieved =
    edges
      .map((x) => x.retrieved)
      .filter(Boolean)
      .sort()
      .pop() ?? null;
  const nodeButton = (id: string, label: string) => (
    <button
      type="button"
      className="inline-flex min-h-11 cursor-pointer items-center border-0 bg-transparent p-0 text-left font-semibold text-accent underline underline-offset-2"
      onClick={() => onOpenNode(id)}
    >
      {label}
    </button>
  );

  return (
    <div className="stack">
      <section>
        <p className="kicker">Link · {edgeStyle(kind).short}</p>
        <h1 className="text-lg">{sentence}</h1>
        <p className="small">
          {nodeButton(source, s.label)} <span className="muted">→</span>{" "}
          {nodeButton(target, t.label)}
        </p>
      </section>
      <section className="card">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="muted">Relationship</dt>
          <dd className="m-0">{edgeStyle(kind).word}</dd>
          <dt className="muted">Source</dt>
          <dd className="m-0">
            {isRule ? (
              <>
                share-or-block rule over the cited claims
                {cited && (
                  <>
                    {" "}
                    · lab study <Ext href={pubmedUrl(cited)}>PMID {cited}</Ext>
                  </>
                )}
              </>
            ) : (
              <Ext href={e.source.url}>{e.source.label}</Ext>
            )}
          </dd>
          <dt className="muted">Retrieved</dt>
          <dd className="m-0">{asOf(retrieved)}</dd>
          <dt className="muted">Checked</dt>
          <dd className="m-0">{checked}</dd>
          {study?.overall_status && (
            <>
              <dt className="muted">Record status</dt>
              <dd className="m-0">
                {study.overall_status.toLowerCase().replace(/_/g, " ")}
                {study.last_update_date ? `, last updated ${study.last_update_date}` : ""}
              </dd>
            </>
          )}
        </dl>
      </section>
      {claims.length > 0 && (
        <section className="card">
          <h2>In the paper's own words</h2>
          {claims.map((c) => (
            <div key={c.claim_id}>
              <blockquote>{c.evidence_quote}</blockquote>
              <p className="small muted">
                <Ext href={pubmedUrl(c.pmid)}>PMID {c.pmid}</Ext> · {c.gene} {c.variant ?? ""} ·{" "}
                {c.direction} of function · {c.basis} · stance {c.stance}
              </p>
            </div>
          ))}
        </section>
      )}
      {coRows.length > 0 && (
        <section className="card">
          <h2>In the study record</h2>
          {coRows.map((c, i) => (
            <p className="small" key={i}>
              Field "{c.matched_field.replace(/_/g, " ")}"
              {c.window ? (
                <>
                  : <q>{c.window}</q>
                </>
              ) : (
                ""
              )}{" "}
              (<Ext href={nctUrl(c.nct)}>{c.nct}</Ext>
              {c.caveat ? `; ${c.caveat}` : ""}
              {c.human_check ? "; checked by code only" : ""}).
            </p>
          ))}
          {study?.why_stopped && (
            <p className="small">
              Reason the study stopped, in the sponsor's words: “{study.why_stopped}”
            </p>
          )}
        </section>
      )}
      {transfers.length > 0 && (
        <section className="card">
          <h2>
            {transfers.length} resource{transfers.length === 1 ? "" : "s"} behind this link
          </h2>
          <ul className="list small">
            {transfers.map((x) => {
              const a = assetById(graph, x.asset_id);
              return (
                <li key={x.asset_id}>
                  <span className="sign">·</span>
                  <span>
                    <strong>{a?.label ?? x.asset_id}</strong> · {plain(x.reason)}{" "}
                    {a && (
                      <span className="muted">
                        · <Ext href={a.source.url}>{a.source.label}</Ext> ·{" "}
                        {asOf(a.last_verified ?? a.source.retrieved)}
                      </span>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {asset && kind === "holds_asset" && (
        <section className="card">
          <p className="small">
            {asset.type.replace(/_/g, " ")} · step: {asset.station.replace(/_/g, " ")} ·{" "}
            <Ext href={asset.source.url}>{asset.source.label}</Ext> ·{" "}
            {asOf(asset.last_verified ?? asset.source.retrieved)}
          </p>
        </section>
      )}
      {conflict && (
        <section className="card">
          <h2>The two sides</h2>
          <ul className="list small">
            {conflict.sides.map((side, i) => (
              <li key={i}>
                <span className="sign">–</span>
                <span>
                  {side.says} (<Ext href={side.source.url}>{side.source.label}</Ext>)
                </span>
              </li>
            ))}
          </ul>
          {conflict.note && <p className="small muted">{conflict.note}</p>}
        </section>
      )}
    </div>
  );
}

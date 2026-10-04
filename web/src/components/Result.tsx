// The result panel: a fixed stack in progressive reveal.
// variant line → block banner → Can share / Can't share (short lists, "show all") → top Borrow
// cards → the seven steps → Named in the same study → "For researchers" disclosure.
// Two inputs: a shipped line, or a channel gene whose direction is not known (gated). The
// gated panel reads only the pipeline's "<gene>_unknown" card: no line's stations, steps,
// texts, trials, models or direction words ever reach it.
import { useState, type ReactNode } from "react";
import type { Card, Graph, Line, Transfer, TriedBefore } from "../types";
import type { ViaVariant } from "../App";
import {
  DIRECTION_WORDS,
  FIELD_PHRASE,
  STATION_LABEL,
  STATUS_WORD,
  assetById,
  bannerParts,
  borrowCards,
  cardFor,
  clusterKeyOf,
  fundingForGene,
  gatedCardFor,
  gatedCardKey,
  coListingsFor,
  conflictsForLine,
  directionEvidence,
  explanationOf,
  heldStations,
  knownDirection,
  lineByKey,
  orgsForGene,
  orgsForLine,
  plain,
  preComputedDate,
  studyByNct,
  textFor,
} from "../data";
import { nctUrl, pubmedUrl } from "../links";
import {
  Badge,
  Ext,
  MEDICATION_WARNING,
  PAUSED_SENTENCE,
  Provenance,
  STOPPED_SENTENCE,
  asOf,
} from "../shared/Layout";
import { BorrowCard, ConflictLine, ProposalDialog } from "./BorrowCard";
import { FundingList } from "./FundingList";

const STATION_ORDER = [
  "diagnosis",
  "registry",
  "natural_history",
  "mechanism",
  "model",
  "outcome_measure",
  "trial",
];
const orderedStations = (st: Record<string, { state: string; why: string }>) =>
  [
    ...STATION_ORDER.filter((k) => k in st),
    ...Object.keys(st).filter((k) => !STATION_ORDER.includes(k)),
  ].map((k) => [k, st[k]] as const);

const SHORT = 3; // rows shown before "Show all"
export type ResultTab = "condition" | "share" | "borrow" | "next";
export const RESULT_TABS: ResultTab[] = ["condition", "share", "borrow", "next"];
const TABS: [ResultTab, string][] = [
  ["condition", "Your condition"],
  ["share", "Share or block"],
  ["borrow", "Borrow"],
  ["next", "Next steps"],
];
const capital = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

// Asset types that never reach a family without a known direction, whatever the file says.
const DIRECTION_GATED_TYPES = new Set(["trial", "model", "drug"]);

type Props = {
  graph: Graph;
  onOpenCluster?: (key: string) => void; // "For researchers": the line's mechanism group
  via?: ViaVariant;
  phoneMap?: ReactNode; // under 640 px: the groups as a list, below the display-only map
  tab?: ResultTab; // the panel shows one section at a time
  onTab?: (t: ResultTab) => void;
  onSeeLinks?: () => void; // opens this form's node: its links on the map, by keyboard too
} & ({ line: Line; gene?: undefined } | { line?: undefined; gene: string });

/** A list that shows its first rows and a "Show all" control for the rest. */
function ShortList<T>({
  rows,
  render,
  label,
}: {
  rows: T[];
  render: (t: T) => ReactNode;
  label: string;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, SHORT);
  return (
    <>
      <ul className="list">{shown.map(render)}</ul>
      {rows.length > SHORT && !all && (
        <button type="button" className="btn quiet small !px-2" onClick={() => setAll(true)}>
          Show all {rows.length} {label}
        </button>
      )}
    </>
  );
}

export function Result({
  graph,
  line,
  gene: gatedGene,
  via,
  onOpenCluster,
  phoneMap,
  onSeeLinks,
  tab = "condition",
  onTab,
}: Props) {
  const gated = !line;
  const gene = line?.gene ?? gatedGene!;
  const card: Card | undefined = gated ? gatedCardFor(graph, gene) : cardFor(graph, line.key);
  const cardKey = gated ? (gatedCardKey(graph, gene) ?? `${gene.toLowerCase()}_unknown`) : line.key;
  const dir = gated ? "unknown" : knownDirection(graph, line);
  const evidence = gated ? [] : directionEvidence(line);
  const lineConflicts = gated ? [] : conflictsForLine(graph, line).filter((c) => !c.variant);
  const orgs = gated ? orgsForGene(graph, gene) : orgsForLine(graph, line);
  const date = preComputedDate(graph);
  const allowed = (t: { asset_type: string }) => !gated || !DIRECTION_GATED_TYPES.has(t.asset_type);
  const transfers = (card?.transfers ?? []).filter(allowed);
  const blockedRow = gated ? undefined : transfers.find((t) => t.blocked);
  const banner = gated ? null : bannerParts(card);
  const blockText = gated
    ? { sentence: undefined, model: false as const, provenance: undefined }
    : explanationOf(textFor(graph, cardKey, "block"));
  const medWarning = graph.meta.medication_warning ?? MEDICATION_WARNING;
  const canShare = transfers.filter(
    (t) => t.status === "viable" || t.status === "needs_expert_check",
  );
  // Stopped or paused studies are "Tried before": never a family-facing ✕ row, only the
  // researchers' disclosure with the sponsor's own words.
  const stoppedStudy = (t: Transfer) =>
    !!t.nct && /TERMINATED|SUSPENDED|WITHDRAWN/.test(t.study_status ?? "");
  const cantShare = transfers.filter((t) => t.status === "not_shared" && !stoppedStudy(t));
  // When every blocked row shares one reason, it is said once above the list.
  const reasons = [...new Set(cantShare.map((t) => t.reason))];
  const oneReason = reasons.length === 1 ? reasons[0] : null;
  const triedList: TriedBefore[] = gated ? [] : (graph.tried_before[line.key] ?? []);
  const triedRows = transfers.filter(
    (t) => t.status === "not_shared" && stoppedStudy(t) && !triedList.some((s) => s.nct === t.nct),
  );
  const triedCount = triedList.length + triedRows.length;
  const clusterKey = gated ? null : clusterKeyOf(graph, line);
  const isChannel = gated || line.mechanism_family === "ion_channel";
  // A channel line with a known direction always carries the block banner and the medication
  // warning, even when the file ships none: the opposite-direction forms are named.
  const mirror = (() => {
    if (gated || banner || !isChannel || (dir !== "gain" && dir !== "loss")) return null;
    const opposite = dir === "gain" ? "loss" : "gain";
    const sameGene = graph.lines.filter((l) => l.gene === gene && l.direction === opposite);
    const others = sameGene.length
      ? sameGene
      : graph.lines.filter((l) => l.mechanism_family === "ion_channel" && l.direction === opposite);
    if (others.length === 0) return null;
    const mine = DIRECTION_WORDS[dir].replace(/^works/, "work");
    const theirs = DIRECTION_WORDS[opposite];
    const names = others.map((l) => l.label).join(" and ");
    return {
      heading: sameGene.length
        ? "Same gene, opposite problem"
        : "Same channel family, opposite problem",
      body: `Your variant makes the channel ${mine}; in ${names} it ${theirs}. Medicines, trials and models from ${others.length === 1 ? "that group" : "those groups"} are not matched here. Registries and care networks can still be shared.`,
    };
  })();
  const funding = gated ? [] : fundingForGene(graph, gene);
  const offer = heldStations(card);
  const cited =
    via ?? (evidence[0] ? { variant: evidence[0].variant, pmid: evidence[0].pmid } : null);
  const alreadyOpen = transfers.filter((t) => t.status === "already_open");
  const borrows = borrowCards(card).filter(allowed);
  const coListings = coListingsFor(graph, card, gated ? null : line.key, gated ? gene : null)
    .filter((c) => c.genes.length > 1)
    .filter((c) => !gated || !(c.kind === "trial" || c.study?.kind === "trial"));
  const stations = card?.stations ?? {};
  const title = gated ? `${gene}, direction not known` : line.label;
  const fromLabel = gated
    ? `${gene} families (direction not known)`
    : `the ${line.label} community`;
  const ownerOf = (t: Transfer) =>
    lineByKey(graph, t.owner_line ?? "")?.label ?? `the ${t.owner_gene} community`;
  // Next steps, from the data file only, in a fixed order; a step with no data is skipped.
  const joinRow = alreadyOpen[0];
  const joinAsset = joinRow ? assetById(graph, joinRow.asset_id) : undefined;
  const joinUrl = joinRow?.nct ? nctUrl(joinRow.nct) : joinAsset?.source.url;
  const topBorrow = borrows[0];
  const topOwner = topBorrow ? (topBorrow.owner_org ?? ownerOf(topBorrow)) : null;
  const firstCheck = topBorrow
    ? (textFor(graph, cardKey, topBorrow.asset_id)?.check_first?.[0] ?? topBorrow.check_first[0])
    : null;
  const [proposalOpen, setProposalOpen] = useState(false);
  const openCheckFirst = () => {
    const d = document.getElementById("card-0-why") as HTMLDetailsElement | null;
    if (!d) return;
    d.open = true;
    d.scrollIntoView({ block: "start" });
  };

  return (
    <div className="stack">
      {/* 2. Block banner */}
      {banner && (
        <section className="banner" role="alert" aria-labelledby="banner-title">
          <h2 id="banner-title">
            <span aria-hidden="true">✕</span> {banner.heading}
          </h2>
          <p>{banner.body}</p>
          {blockedRow?.cited_pmid && (
            <p className="small">
              Lab study: {gene} {cited?.variant ?? ""} (
              <Ext href={pubmedUrl(cited?.pmid ?? blockedRow.cited_pmid)}>
                PMID {cited?.pmid ?? blockedRow.cited_pmid}
              </Ext>
              ), checked by code.
            </p>
          )}
          <p className="warning">{medWarning}</p>
          {blockText.sentence && blockText.model && (
            <details className="level">
              <summary>Why this is blocked</summary>
              <p className="small">{blockText.sentence}</p>
              <Provenance
                model={blockText.provenance?.model}
                date={blockText.provenance?.run_at?.slice(0, 10) ?? date}
              />
            </details>
          )}
        </section>
      )}
      {mirror && (
        <section className="banner" role="alert" aria-labelledby="banner-title">
          <h2 id="banner-title">
            <span aria-hidden="true">✕</span> {mirror.heading}
          </h2>
          <p>{mirror.body}</p>
          {cited && (
            <p className="small">
              Lab study: {gene} {cited.variant ?? ""} (
              <Ext href={pubmedUrl(cited.pmid)}>PMID {cited.pmid}</Ext>), checked by code.
            </p>
          )}
          <p className="warning">{medWarning}</p>
        </section>
      )}
      {(gated || dir === "mixed") && isChannel && (
        <section className="banner" role="alert">
          <h2>{dir === "mixed" ? "Sources disagree on gain vs loss" : "Direction not known"}</h2>
          <p>
            {dir === "mixed"
              ? "Until this is settled, we don't suggest sharing medicines, trials or models. Registries and care networks can still be shared."
              : "Without a lab study of the variant we don't suggest sharing medicines, trials or models. Registries and care networks can still be shared."}
          </p>
          <p className="warning">{medWarning}</p>
        </section>
      )}

      <div
        className="sticky top-0 z-10 -mx-4 flex gap-1 overflow-x-auto border-b border-hair bg-paper px-4 py-2"
        aria-label="Sections"
      >
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            aria-current={tab === key ? "page" : undefined}
            className={`chip !min-h-10 !px-3 ${tab === key ? "!border-accent !bg-accent !text-paper" : ""}`}
            onClick={() => onTab?.(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "condition" && (
        <>
          {/* 1. Variant line */}
          <section aria-labelledby="variant-line">
            <p className="kicker">
              {gene} ·{" "}
              <span className="as-is">
                {orgs.map((o) => o.name).join(" · ") || "no organisation recorded"}
              </span>
            </p>
            <h1 id="variant-line">{title}</h1>
            {onSeeLinks && (
              <button type="button" className="btn quiet small -ml-2 !px-2" onClick={onSeeLinks}>
                See its links on the map
              </button>
            )}
            <div className="variant-line">
              {!gated && isChannel && dir !== "unknown" && dir !== "mixed" ? (
                <>
                  <span className="gloss">{line.gloss}</span>
                  <span className="muted small">
                    · lab study{cited?.variant ? ` of ${cited.variant}` : ""},{" "}
                    {cited ? (
                      <Ext href={pubmedUrl(cited.pmid)}>PMID {cited.pmid}</Ext>
                    ) : (
                      "no PMID in the data file"
                    )}
                    , checked by code
                  </span>
                </>
              ) : isChannel ? (
                <>
                  <span className="gloss">
                    {gated ? "set by the specific variant" : `${gene}: ${DIRECTION_WORDS[dir]}`}
                  </span>
                  <span className="muted small">
                    ·{" "}
                    {gated
                      ? "ask your geneticist"
                      : "no lab study of this condition found in the data file"}
                  </span>
                </>
              ) : (
                <>
                  <span className="gloss">
                    {line.mechanism_label?.split(" — ")[0] ?? line.gloss}
                  </span>
                  <span className="muted small">
                    · {line.mechanism_label?.split(" — ").slice(1).join(" — ") || line.gloss}
                  </span>
                </>
              )}
            </div>
            {gated && (
              <p className="small mt-2">
                We only show registries, care networks and outcome measures for {gene} without a
                known direction: no medicines, trials or models.
              </p>
            )}
            {line &&
              lineConflicts.map((c) => {
                const differing = c.sides.filter(
                  (side) => !new RegExp(dir === "gain" ? "gain" : "loss", "i").test(side.says),
                ).length;
                return (
                  <details className="level conflict-chip" key={c.id}>
                    <summary>
                      <Badge kind="warn">Sources disagree</Badge>{" "}
                      <span className="muted small font-normal">
                        {differing === 1
                          ? `1 database label differs from the lab study`
                          : `${differing} other sources label ${gene} differently`}
                      </span>
                    </summary>
                    <ConflictLine conflict={c} line={line} labPmid={evidence[0]?.pmid} />
                  </details>
                );
              })}
            {!gated && line.hpo_terms && line.hpo_terms.length > 0 && (
              <p className="small muted mt-2">
                Symptoms we matched on: {line.hpo_terms.map((h) => h.label).join(", ")}.{" "}
                {line.hpo_terms[0].annotation ??
                  graph.meta.hpo_annotation_label ??
                  "Polaris annotation using HPO terms (not an official HPO annotation)"}
                .
              </p>
            )}
          </section>
        </>
      )}
      {tab === "share" && (
        <>
          {/* 3. Can share / Can't share */}
          <section aria-labelledby="share-title">
            <h2 id="share-title">Can share / Can't share</h2>
            <div className="two-col">
              <div className="card">
                <h3>
                  <span className="sign ok">✓</span> Can share
                </h3>
                {canShare.length === 0 && (
                  <p className="muted small">
                    Nothing in the data file can be shared with your community yet.
                  </p>
                )}
                <ShortList
                  rows={canShare}
                  label="shareable"
                  render={(t) => (
                    <li key={t.asset_id}>
                      <span
                        className={`sign ${t.status === "viable" ? "ok" : "warn"}`}
                        aria-hidden="true"
                      >
                        {STATUS_WORD[t.status].sign}
                      </span>
                      <span>
                        <strong>{assetById(graph, t.asset_id)?.label ?? t.asset_id}</strong>{" "}
                        <span className="muted small">
                          · {STATUS_WORD[t.status].word} · from {ownerOf(t)}
                        </span>
                      </span>
                    </li>
                  )}
                />
              </div>
              <div className="card">
                <h3>
                  <span className="sign no">✕</span> Can't share
                </h3>
                {gated && (
                  <ul className="list">
                    <li>
                      <span className="sign no" aria-hidden="true">
                        ✕
                      </span>
                      <span>
                        <strong>Medicines, trials and models</strong>{" "}
                        <span className="muted small">· Not shared · direction not known</span>
                      </span>
                    </li>
                  </ul>
                )}
                {!gated && cantShare.length === 0 && (
                  <p className="muted small">
                    Nothing is blocked for your community in the data file.
                  </p>
                )}
                {oneReason && <p className="small muted">{capital(plain(oneReason))}</p>}
                <ShortList
                  rows={cantShare}
                  label="not shared"
                  render={(t) => (
                    <li key={t.asset_id}>
                      <span className="sign no" aria-hidden="true">
                        ✕
                      </span>
                      <span>
                        <strong>{assetById(graph, t.asset_id)?.label ?? t.asset_id}</strong>{" "}
                        <span className="muted small">
                          · Not shared{oneReason ? "" : ` · ${plain(t.reason)}`}
                        </span>
                      </span>
                    </li>
                  )}
                />
              </div>
            </div>
            {alreadyOpen.length > 0 && (
              <div className="card mt-3">
                <h3>
                  <span className="sign ok">✓</span> Already open to you
                </h3>
                <ShortList
                  rows={alreadyOpen}
                  label="already open"
                  render={(t) => (
                    <li key={t.asset_id}>
                      <span className="sign ok" aria-hidden="true">
                        ✓
                      </span>
                      <span>
                        <strong>{assetById(graph, t.asset_id)?.label ?? t.asset_id}</strong>{" "}
                        <span className="muted small">· {plain(t.reason)}</span>
                      </span>
                    </li>
                  )}
                />
              </div>
            )}
          </section>
        </>
      )}
      {tab === "borrow" && (
        <>
          {/* 4. Top Borrow cards */}
          <section aria-labelledby="borrow-title">
            <h2 id="borrow-title">What this community can borrow</h2>
            {borrows.length === 0 && <NoTransfer graph={graph} title={title} gated={gated} />}
            {borrows.map((t, i) => (
              <BorrowCard
                key={t.asset_id}
                graph={graph}
                cardKey={cardKey}
                fromLabel={fromLabel}
                offer={offer}
                triedBefore={graph.tried_before[t.owner_line ?? ""] ?? []}
                transfer={t}
                index={i}
                gated={gated}
              />
            ))}
          </section>
        </>
      )}
      {tab === "next" && (
        <>
          {/* 7. Next steps */}
          <section className="card" aria-labelledby="next-title">
            <h2 id="next-title">Next steps</h2>
            <ol className="m-0 grid gap-2 pl-5">
              {joinRow && (
                <li>
                  Join what is already open to you:{" "}
                  <Ext href={joinUrl}>{joinAsset?.label ?? joinRow.asset_id}</Ext>.
                </li>
              )}
              {topBorrow && (
                <li>
                  <button
                    type="button"
                    className="inline cursor-pointer border-0 bg-transparent p-0 text-left text-accent underline underline-offset-2"
                    onClick={() => setProposalOpen(true)}
                  >
                    Propose sharing{" "}
                    {assetById(graph, topBorrow.asset_id)?.label ?? topBorrow.asset_id} with{" "}
                    {topOwner}
                  </button>
                  .
                </li>
              )}
              {firstCheck && (
                <li>
                  <button
                    type="button"
                    className="inline cursor-pointer border-0 bg-transparent p-0 text-left text-accent underline underline-offset-2"
                    onClick={openCheckFirst}
                  >
                    Check first: {firstCheck}
                  </button>
                </li>
              )}
              {gated && (
                <li>
                  Ask your geneticist whether this variant's function has been tested in a lab.
                </li>
              )}
              {!joinRow && !topBorrow && !gated && (
                <li>
                  Nothing in the data file is open to this condition yet; what would change this is
                  a lab study of a variant in it.
                </li>
              )}
            </ol>
            {proposalOpen && topBorrow && (
              <ProposalDialog
                graph={graph}
                cardKey={cardKey}
                fromLabel={fromLabel}
                offer={offer}
                transfer={topBorrow}
                onClose={() => setProposalOpen(false)}
              />
            )}
          </section>

          {/* 5. The seven steps */}
          <section className="card" aria-labelledby="timeline-title">
            <h2 id="timeline-title">The seven steps</h2>
            {card ? (
              <>
                <p>{card.steps.sentence ?? stepsSentence(card)}</p>
                <details className="level">
                  <summary>Step by step</summary>
                  <ol className="timeline" aria-label="Seven steps">
                    {orderedStations(stations).map(([key, st]) => (
                      <li key={key} className={`step ${st.state}`}>
                        <div className="sign" aria-hidden="true">
                          {st.state === "have" ? "✓" : st.state === "missing" ? "○" : "?"}
                        </div>
                        <strong>{STATION_LABEL[key] ?? key}</strong>
                        <div className="muted">
                          {st.state === "have"
                            ? "Have"
                            : st.state === "missing"
                              ? "Missing"
                              : "Not known"}
                          : {plain(st.why)}
                        </div>
                      </li>
                    ))}
                  </ol>
                  <p className="small muted mt-2">
                    Steps mode: counts of steps, not years. Years are shown only when every duration
                    on the path has its own source. Data pre-computed {date}.
                  </p>
                </details>
              </>
            ) : (
              <p className="muted">The data file carries no step map for this condition yet.</p>
            )}
          </section>

          {/* 6. Named in the same study */}
          <section aria-labelledby="named-title">
            <h2 id="named-title">Named in the same study</h2>
            {coListings.length === 0 && (
              <p className="card muted">
                No study record in the data file names this condition together with another.
              </p>
            )}
            {coListings.map(
              ({ nct, study, fields, eligibilityAny, humanCheck, caveat, retrieved }) => (
                <div className="card" key={nct}>
                  <p>
                    <strong>{study?.name ?? nct}</strong> (<Ext href={nctUrl(nct)}>{nct}</Ext>){" "}
                    {study?.start_date
                      ? `${study.overall_status === "RECRUITING" ? "is open since" : "started"} ${study.start_date}; `
                      : ": the record gives no start date; "}
                    {fields
                      .map(
                        (f) =>
                          `${FIELD_PHRASE[f.field] ?? `its ${f.field.replace(/_/g, " ")} names`} ${f.genes.join(", ")}`,
                      )
                      .join("; ")}{" "}
                    ({asOf(retrieved)}). Being listed doesn't mean these conditions are alike or
                    that families are enrolled. It means one study is already set up to include
                    them. Eligibility is decided by the study team.
                    {study?.overall_status
                      ? ` Status '${study.overall_status.toLowerCase().replace(/_/g, " ")}'`
                      : ""}
                    {study?.last_update_date
                      ? `, last updated ${study.last_update_date}.`
                      : study?.overall_status
                        ? "."
                        : ""}
                  </p>
                  {(eligibilityAny || humanCheck || study?.kind === "eligible_gene_list") && (
                    <p className="small muted m-0">
                      {caveat
                        ? `${caveat.charAt(0).toUpperCase()}${caveat.slice(1)}.`
                        : `${eligibilityAny ? "Some genes are named in the inclusion text only" : "Listing"}${humanCheck ? "; checked by code only." : "."}`}
                    </p>
                  )}
                </div>
              ),
            )}
          </section>

          {phoneMap && (
            <section aria-labelledby="cluster-title">
              <h2 id="cluster-title">Where this condition sits</h2>
              {phoneMap}
            </section>
          )}

          {/* 8. For researchers */}
          <section className="card">
            <details className="level !mt-0 !border-t-0 !pt-0">
              <summary>For researchers</summary>
              <div className="small">
                <h3 className="mt-2">Studies that stopped or paused ({triedCount})</h3>
                {triedCount === 0 && (
                  <p className="muted">
                    No stopped or paused study is recorded for this condition.
                  </p>
                )}
                {triedList.map((s) => (
                  <p key={s.nct}>
                    <strong>{(s.name ?? s.nct).replace(` (${s.nct})`, "")}</strong> ·{" "}
                    <Ext href={nctUrl(s.nct)}>{s.nct}</Ext> ·{" "}
                    {s.state === "paused" || /SUSPENDED/i.test(s.overall_status ?? "")
                      ? "paused"
                      : "stopped"}
                    {s.overall_status
                      ? ` · record status ${s.overall_status.toLowerCase().replace(/_/g, " ")}`
                      : ""}
                    {s.last_update_date ? ` · last updated ${s.last_update_date}` : ""}.{" "}
                    {s.why_stopped
                      ? `Reason in the sponsor's words: “${s.why_stopped}” `
                      : "No reason is given in the record. "}
                    {s.state === "paused" || /SUSPENDED/i.test(s.overall_status ?? "")
                      ? PAUSED_SENTENCE
                      : STOPPED_SENTENCE}
                  </p>
                ))}
                {triedRows.map((t) => {
                  const st = t.nct ? studyByNct(graph, t.nct) : undefined;
                  return (
                    <p key={t.asset_id}>
                      <strong>{assetById(graph, t.asset_id)?.label ?? t.asset_id}</strong> ·{" "}
                      <Ext href={nctUrl(t.nct!)}>{t.nct}</Ext> ·{" "}
                      {/SUSPENDED/.test(t.study_status ?? "") ? "paused" : "stopped"} · record
                      status {(t.study_status ?? "").toLowerCase().replace(/_/g, " ")}
                      {t.last_update_date ? ` · last updated ${t.last_update_date}` : ""}.{" "}
                      {st?.why_stopped
                        ? `Reason in the sponsor's words: “${st.why_stopped}” `
                        : "No reason is given in the record. "}
                      {/SUSPENDED/.test(t.study_status ?? "") ? PAUSED_SENTENCE : STOPPED_SENTENCE}
                    </p>
                  );
                })}
                {!gated && (
                  <>
                    <h3 className="mt-3">
                      Funded projects naming {gene} (NIH RePORTER, {funding.length})
                    </h3>
                    <FundingList graph={graph} gene={gene} />
                  </>
                )}
                {clusterKey &&
                  onOpenCluster &&
                  graph.mechanism_view.some((c) => c.key === clusterKey) && (
                    <div className="actions">
                      <button
                        type="button"
                        className="btn"
                        onClick={() => onOpenCluster(clusterKey)}
                      >
                        Everyone working on this mechanism
                      </button>
                    </div>
                  )}
              </div>
            </details>
          </section>
        </>
      )}
    </div>
  );
}

/** Fallback steps sentence from the counts when the file ships none. */
function stepsSentence(card: Card) {
  const have = Object.values(card.stations).filter((s) => s.state === "have").length;
  const total = card.steps.total ?? 7;
  const missing = card.steps.missing ?? [];
  const borrowable = card.steps.borrowable ?? [];
  if (missing.length === 0) return `Your community already has ${have} of ${total} steps.`;
  return `Your community already has ${have} of ${total} steps. ${borrowable.length} of ${missing.length} missing step${missing.length === 1 ? "" : "s"} could be borrowed instead of built.`;
}

/** "Line found, no transfer" state: the shared resources listed in the data file. */
function NoTransfer({ graph, title, gated }: { graph: Graph; title: string; gated: boolean }) {
  const shared = [
    ...graph.studies
      .filter((s) => s.kind === "registry" || s.kind === "eligible_gene_list")
      .map((s) => ({
        name: s.name,
        url: nctUrl(s.nct),
        date: s.retrieved ?? s.source?.retrieved ?? null,
      })),
    ...graph.assets
      .filter((a) => a.open_to_all)
      .map((a) => ({
        name: a.label,
        url: a.source.url,
        date: a.last_verified ?? a.source.retrieved ?? null,
      })),
  ];
  return (
    <div className="card">
      <h3>
        {gated
          ? "Nothing to borrow until the direction is known"
          : "Little has been published about this condition yet"}
      </h3>
      <p>
        {gated
          ? "Without a lab study of your child's variant we cannot match another community's work to it. That's a gap, not a dead end."
          : "We found no other community that holds a step you're missing and fits your child's direction. That's a gap, not a dead end."}
      </p>
      {shared.length > 0 && (
        <p className="small">
          <strong>Free shared resources you can join today:</strong>{" "}
          {shared.map((f, i) => (
            <span key={f.name}>
              {i > 0 && " · "}
              <Ext href={f.url}>{f.name}</Ext> <span className="muted">({asOf(f.date)})</span>
            </span>
          ))}
        </p>
      )}
      <p className="small">
        <strong>What would change this:</strong>{" "}
        {gated ? "a lab study of your child's variant." : `a lab study of a variant in ${title}.`}
      </p>
    </div>
  );
}

// One Borrow card: Level 0 (one sentence, ≤ 2 badges), Level 1 "Why we think this",
// Level 2 "For researchers". Drug names never appear here: the family path shows NCT,
// status and the sponsor's verbatim stop reason only.
import { useEffect, useRef, useState } from "react";
import type { Conflict, Graph, Line, Transfer, TriedBefore } from "../types";
import {
  STATUS_WORD,
  assetById,
  claimsById,
  explanationOf,
  lineByKey,
  plain,
  preComputedDate,
  textFor,
} from "../data";
import { nctUrl, pubmedUrl } from "../links";
import {
  AI_BADGE,
  Badge,
  Ext,
  PAUSED_SENTENCE,
  Provenance,
  STOPPED_SENTENCE,
  asOf,
} from "../shared/Layout";

interface Props {
  graph: Graph;
  cardKey: string; // the line key, or "<GENE>:unknown" for the gated page
  fromLabel: string; // "the SCN2A loss of function community" / "SCN2A families (direction not known)"
  offer: string[]; // the steps the sender already holds (for the proposal's return line)
  triedBefore: TriedBefore[];
  transfer: Transfer;
  index: number;
  gated?: boolean; // direction not known: no direction claims on the card
}

export function BorrowCard({
  graph,
  cardKey,
  fromLabel,
  offer,
  triedBefore,
  transfer: t,
  index,
  gated,
}: Props) {
  const asset = assetById(graph, t.asset_id);
  const text = textFor(graph, cardKey, t.asset_id);
  const owner = lineByKey(graph, t.owner_line ?? "");
  const ownerName = owner?.label ?? `the ${t.owner_gene} community`;
  const claims = gated ? [] : claimsById(graph, t.evidence_claim_ids);
  const status = STATUS_WORD[t.status];
  const expl = explanationOf(text);
  const full = expl.model ? expl.sentence! : plain(expl.sentence ?? t.reason);
  // Level 0 is one sentence; the rest of the text opens Level 1.
  const [sentence, ...rest] = full.split(/(?<=[.!?])\s+(?=[A-Z])/);
  const more = rest.join(" ");
  const checkFirst = text?.check_first?.length ? text.check_first : t.check_first;
  const tried = triedBefore.filter(
    (s) =>
      s.state || s.why_stopped || /TERMINATED|WITHDRAWN|SUSPENDED/i.test(s.overall_status ?? ""),
  );
  const [open, setOpen] = useState(false);
  const proposalButton = useRef<HTMLButtonElement>(null);
  const date = preComputedDate(graph);
  const lastVerified = asset?.last_verified ?? asset?.source.retrieved ?? null;

  return (
    <article className="card" aria-labelledby={`card-${index}`}>
      <p className="kicker">
        Card {index + 1} · {status.sign} {status.word} · {t.station.replace(/_/g, " ")}
        {t.fills_missing_station ? " · fills a missing step" : ""}
        {t.card_type && !["borrow", t.status].includes(t.card_type)
          ? ` · ${t.card_type.replace(/_/g, " ")}`
          : ""}
      </p>
      <h3 id={`card-${index}`}>{asset?.label ?? t.asset_id}</h3>
      <p>{sentence}</p>
      <div className="chips" style={{ gap: 6 }}>
        {t.evidence_level ? (
          <Badge kind="ok">{AI_BADGE}</Badge>
        ) : t.status === "already_open" ? null : (
          <Badge>Idea to test</Badge>
        )}
      </div>
      <Provenance
        template={!expl.model}
        model={expl.provenance?.model}
        date={expl.provenance?.run_at?.slice(0, 10) ?? date}
      />

      <details className="level" id={`card-${index}-why`}>
        <summary>Why we think this</summary>
        <div>
          {more && <p>{more}</p>}
          <p className="small">
            From {ownerName}
            {t.owner_org ? `, run by ${t.owner_org}` : ""}.{" "}
            {t.nct && (
              <>
                Record <Ext href={nctUrl(t.nct)}>{t.nct}</Ext>
                {t.study_status
                  ? `, status ${t.study_status.toLowerCase().replace(/_/g, " ")}`
                  : ""}
                {t.start_date ? `, started ${t.start_date}` : ""}
                {t.last_update_date ? `, last updated ${t.last_update_date}` : ""}.{" "}
              </>
            )}
            Source: <Ext href={asset?.source.url}>{asset?.source.label ?? "source"}</Ext> ·{" "}
            {asOf(lastVerified)}.
          </p>
          {t.basis_note && <p className="small muted">{t.basis_note}</p>}
          {claims.length > 0 && (
            <>
              <h3 style={{ fontSize: 15 }}>The lab evidence behind the direction</h3>
              {claims.map((c) => (
                <div key={c.claim_id}>
                  <blockquote>{c.evidence_quote}</blockquote>
                  <p className="small muted">
                    <Ext href={pubmedUrl(c.pmid)}>PMID {c.pmid}</Ext> · {c.gene} {c.variant ?? ""} ·{" "}
                    {c.basis} · {AI_BADGE} · found by {c.model ?? "the build-time model"}
                  </p>
                </div>
              ))}
            </>
          )}
          {!claims.length && !gated && t.cited_pmid && (
            <p className="small">
              Lab study: <Ext href={pubmedUrl(t.cited_pmid)}>PMID {t.cited_pmid}</Ext>, checked by
              code.
            </p>
          )}
          <h3 style={{ fontSize: 15 }}>What differs</h3>
          {t.what_differs.length ? (
            <ul className="list small">
              {t.what_differs.map((d) => (
                <li key={d}>
                  <span className="sign">–</span>
                  <span>
                    {plain(d)}
                    {t.study_population && /who the study is for/.test(d) && (
                      <>
                        {" "}
                        <q>{t.study_population}</q>
                      </>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="small muted">No difference is recorded in the data file for this pair.</p>
          )}
          <h3 style={{ fontSize: 15 }}>Check first</h3>
          {checkFirst.length ? (
            <ul className="list small">
              {checkFirst.map((c) => (
                <li key={c}>
                  <span className="sign">☐</span>
                  {c}
                </li>
              ))}
            </ul>
          ) : (
            <p className="small muted">No check-first list for this asset type.</p>
          )}
          {t.status !== "already_open" && (
            <div className="actions">
              <button
                type="button"
                className="btn"
                ref={proposalButton}
                onClick={() => setOpen(true)}
              >
                Draft a two-way proposal
              </button>
            </div>
          )}
        </div>
      </details>

      <details className="level">
        <summary>For researchers</summary>
        <div className="small">
          {tried.length === 0 && (
            <p className="muted">
              No earlier stopped study is recorded for this community in the data file.
            </p>
          )}
          {tried.map((s) => (
            <div key={s.nct} style={{ marginBottom: 8 }}>
              <strong>
                {s.state === "paused" || /SUSPENDED/i.test(s.overall_status ?? "")
                  ? "Study paused"
                  : "Earlier study, now stopped"}
              </strong>{" "}
              · <Ext href={nctUrl(s.nct)}>{s.nct}</Ext>
              {s.name ? ` · ${s.name.replace(` (${s.nct})`, "")}` : ""}
              {s.overall_status
                ? ` · record status ${s.overall_status.toLowerCase().replace(/_/g, " ")}`
                : ""}
              {s.last_update_date ? ` · last updated ${s.last_update_date}` : ""}
              <p style={{ margin: "4px 0 0" }}>
                {s.why_stopped ? (
                  <>Reason in the sponsor's words: “{s.why_stopped}” </>
                ) : (
                  "No reason is given in the record. "
                )}
                {s.state === "paused" || /SUSPENDED/i.test(s.overall_status ?? "")
                  ? PAUSED_SENTENCE
                  : STOPPED_SENTENCE}
              </p>
            </div>
          ))}
          <p className="muted">
            Asset id <span className="mono">{t.asset_id}</span> · rank {t.rank} · crosses gene:{" "}
            {t.crosses_gene ? "yes" : "no"} · crosses direction:{" "}
            {t.crosses_direction ? "yes" : "no"}
            {t.direction_basis && !gated
              ? ` · direction basis: ${t.direction_basis.replace(/_/g, " ")}`
              : ""}
          </p>
        </div>
      </details>

      {open && (
        <ProposalDialog
          graph={graph}
          cardKey={cardKey}
          fromLabel={fromLabel}
          offer={offer}
          transfer={t}
          onClose={() => {
            setOpen(false);
            // Return focus to the trigger once the dialog has left the tree.
            requestAnimationFrame(() => proposalButton.current?.focus());
          }}
        />
      )}
    </article>
  );
}

export function ConflictLine({
  conflict,
  line,
  labPmid,
}: {
  conflict: Conflict;
  line: Line;
  labPmid?: string | null; // the code-checked lab study the line's direction rests on
}) {
  const word = line.direction === "gain" ? "gain" : "loss";
  // The side that names the other direction (database labels, or a second lab study).
  const other = conflict.sides.find((s) => !new RegExp(word, "i").test(s.says));
  return (
    <div
      className="card"
      style={{ boxShadow: "none", background: "var(--warn-bg)", borderColor: "var(--warn)" }}
    >
      <strong>Sources disagree</strong>
      {labPmid && other ? (
        <p className="small" style={{ margin: "4px 0 0" }}>
          We use the lab study: {line.gloss.split(" — ")[0]} (
          <Ext href={pubmedUrl(labPmid)}>PMID {labPmid}</Ext>). Another source lists the other
          direction: {other.says} (<Ext href={other.source.url}>{other.source.label}</Ext>
          {other.source.retrieved ? `, retrieved ${other.source.retrieved}` : ""}). Both shown so
          you can check.
        </p>
      ) : (
        <ul className="list small" style={{ marginTop: 4 }}>
          {conflict.sides.map((s, i) => (
            <li key={i}>
              <span className="sign">–</span>
              <span>
                {s.says} · <Ext href={s.source.url}>{s.source.label}</Ext>
              </span>
            </li>
          ))}
        </ul>
      )}
      {conflict.note && (
        <p className="small muted" style={{ margin: "4px 0 0" }}>
          {conflict.note}
        </p>
      )}
    </div>
  );
}

/** Proposal text from the cited facts (model-written when the file has it, else a template). */
export function ProposalDialog({
  graph,
  cardKey,
  fromLabel,
  offer,
  transfer: t,
  onClose,
}: {
  graph: Graph;
  cardKey: string;
  fromLabel: string;
  offer: string[];
  transfer: Transfer;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const primary = useRef<HTMLButtonElement>(null);
  const asset = assetById(graph, t.asset_id);
  const text = textFor(graph, cardKey, t.asset_id);
  const owner = lineByKey(graph, t.owner_line ?? "");
  const [copied, setCopied] = useState(false);
  const date = preComputedDate(graph);
  const modelProposal = !!text?.proposal && text.source !== "template";
  const model = text?.provenance?.model ?? "the build-time model";
  // The frame (addresses, the shared step, sources, the disclaimer) is always built from the
  // facts; only the middle paragraph may be model-written.
  const body = [
    modelProposal
      ? `Two-way proposal (middle paragraph written by ${model} at build time from the cited facts; checked by code)`
      : `Two-way proposal (draft from cited facts; template text, not model-written)`,
    ``,
    `From: ${fromLabel}`,
    `To: ${owner?.label ?? `the ${t.owner_gene} community`}${t.owner_org ? ` (${t.owner_org})` : ""}`,
    ``,
    `Shared step: ${asset?.label ?? t.asset_id}${t.nct && !asset?.label.includes(t.nct) ? ` (${t.nct})` : ""}`,
    modelProposal ? text!.proposal! : `Why it could be shared: ${plain(t.reason)}`,
    t.what_differs.length ? `What differs: ${t.what_differs.map(plain).join("; ")}` : ``,
    t.study_population
      ? `Who the study is for, in the record's words: "${t.study_population}"`
      : ``,
    t.check_first.length ? `Check first: ${t.check_first.join("; ")}` : ``,
    offer.length
      ? `What we offer in return: the steps our community already holds (${offer.join(", ").toLowerCase()}) and a comparison of our records with yours.`
      : `What we offer in return: a comparison of our records with yours.`,
    ``,
    `Sources: ${[...new Set([asset?.source.label, t.cited_pmid ? `PMID ${t.cited_pmid}` : null, t.nct ? `ClinicalTrials.gov ${t.nct}` : null].filter(Boolean))].join("; ")}`,
    `Research-planning draft. Not medical advice. Data pre-computed ${date}.`,
  ]
    .filter((l) => l !== ``)
    .join("\n");

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (!d.open) d.showModal();
    primary.current?.focus();
    const onCancel = (e: Event) => {
      e.preventDefault();
      onClose();
    };
    d.addEventListener("cancel", onCancel);
    return () => d.removeEventListener("cancel", onCancel);
  }, [onClose]);

  const download = () => {
    const blob = new Blob([body], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `polaris-proposal-${cardKey.replace(/[^A-Za-z0-9_-]/g, "_")}-${t.asset_id}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <dialog
      className="proposal"
      ref={ref}
      aria-labelledby="proposal-title"
      onClick={(e) => e.target === ref.current && onClose()}
    >
      <div className="body">
        <h2 id="proposal-title">Two-way proposal</h2>
        <pre>{body}</pre>
        <Provenance
          template={!modelProposal}
          model={text?.provenance?.model}
          date={text?.provenance?.run_at?.slice(0, 10) ?? date}
        />
        <div className="actions">
          <button
            type="button"
            className="btn primary"
            ref={primary}
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(body);
                setCopied(true);
              } catch {
                setCopied(false);
              }
            }}
          >
            {copied ? "Copied" : "Copy text"}
          </button>
          <button type="button" className="btn" onClick={download}>
            Download .txt
          </button>
          <button type="button" className="btn" onClick={onClose}>
            Close (Esc)
          </button>
        </div>
      </div>
    </dialog>
  );
}

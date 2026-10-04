// The researcher page (B6): approved medicines a code filter matched to a protein mechanism,
// shown as hypotheses for laboratory testing. Separate entry, noindex, reached only through the
// "Researcher view" toggle and its interstitial. Three steps on one page (pick a condition, the
// filter as counts, a candidate table with one detail pane); "Method and sources" is its own view
// at #method. Everything on screen is read from web/public/screen.json; nothing is ranked by
// expected benefit; the gate is held in memory only.
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { Screen, ScreenCard, ScreenLine } from "./screenTypes";
import { nctUrl, pubmedUrl } from "../links";
import { RESEARCHER_HOSTS, openTargetsDrugUrl } from "./hosts";
import { Ext, Header, LoadError, Skeleton, STOPPED_SENTENCE } from "../shared/Layout";

// Fallbacks only: the file's own `meta` copy wins whenever it is present (the file labels itself).
const INTERSTITIAL =
  "This page lists approved medicines that a computer filter matched to a protein mechanism. They are untested ideas for laboratory research, not treatments. Nothing here applies to any child's care. Never start, stop or change a medicine without your child's neurologist.";
const CONTINUE = "I'm a researcher, continue";
const BACK = "Back to the family view";
const MEDICATION_WARNING =
  "Not medical advice. Never change or stop a medication without your child's neurologist.";
const HYPOTHESIS = "Hypothesis for laboratory testing, not medical advice";
const ALREADY_STUDIED = "Already studied for this gene: not a new idea";
const AI_BADGE = "Found by AI, checked by code";
const ORDERING = "ordered by a fixed rule (evidence count), not by expected benefit";
const LIST_SENTENCE =
  "Each row is one approved medicine whose action matches this condition's direction, listed with the papers that already pair it with the gene. These are ideas for laboratory testing, not medical advice.";
const ALREADY_SHORT = "Already studied";
// The side pane needs room for the table beside it; narrower screens get a full-width sheet.
const SHEET_QUERY = "(max-width: 899px)";
const UNCHECKED_HEADING = "Model reasoning, not checked against a paper";

const REFUSAL: Record<string, string> = {
  not_a_channel_line: "not a channel gene: the direction filter does not apply",
  direction_not_confirmed: "no code-checked lab study confirms a direction",
  direction_mixed_or_unknown: "direction mixed or not known",
  line_not_in_screen_scope: "outside the screen's scope",
  line_not_in_graph: "not in the shipped graph file yet",
  evidence_not_fetched: "no paper or study pairs fetched for this gene yet",
};
const NOT_SHOWN_LABEL: Record<string, string> = {
  already_studied: "already studied for this gene",
  paper_found: "with a family-level mechanism reference only",
  no_paper_found: "with no paper or study",
};
const REMOVED_LABEL: Record<string, string> = {
  outside_the_channel_family: "outside the channel family",
  wrong_direction: "recorded action goes the other way",
  action_unclear: "action type unclear",
};

const n = (v: number) => v.toLocaleString("en-GB");
const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const titleCase = (s: string) =>
  s.toLowerCase().replace(/(^|[\s-])([a-z])/g, (_m, a, b) => a + b.toUpperCase());
const sameSet = (a: string[], b?: string[]) =>
  !!b && a.length === b.length && [...a].sort().join() === [...b].sort().join();
// The two count notes in `meta` name their fields; shown with the fields in plain words.
const FIELD_WORDS: [RegExp, string | ((m: string) => string)][] = [
  [/already_tried_total counts/g, "The 'already tried' count is"],
  [/surfaced counts/g, "the 'surfaced' count is"],
  [/new_candidates_on_line_gene counts/g, "the 'not yet paired, on the line's gene' count is"],
  [/new_candidates counts/g, "the 'not yet paired' count is"],
  [/\(see without_paper\)/g, "(the 'no paper' count)"],
  [/[a-z_]+_[a-z_]+/g, (m: string) => m.replace(/_/g, " ")],
];
const plainNote = (t?: string) =>
  t ? capital(FIELD_WORDS.reduce((acc, [re, w]) => acc.replace(re, w as string), t)) : "";
const refusalText = (l: ScreenLine) =>
  REFUSAL[l.refusal_reason ?? ""] ?? l.refusal_reason ?? "no reason given";

// No em dashes in rendered copy (plan owner, 2026-10-04): the pipeline rewrites the meta
// captions at source; until that file lands, every string from the file is rendered with
// ", " in place of " — ". A verbatim sponsor `why_stopped` is the only text left untouched.
function scrub(v: unknown, key = ""): unknown {
  if (typeof v === "string") return key === "why_stopped" ? v : v.replace(/\s*—\s*/g, ", ");
  if (Array.isArray(v)) return v.map((x) => scrub(x));
  if (v && typeof v === "object")
    return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, scrub(x, k)]));
  return v;
}

async function loadScreen(): Promise<Screen> {
  const res = await fetch(`${import.meta.env.BASE_URL}screen.json`, { cache: "no-cache" });
  if (!res.ok) throw new Error(`screen.json ${res.status}`);
  const s = scrub(await res.json()) as Screen;
  if (!Array.isArray(s.lines) || !s.meta || typeof s.meta !== "object")
    throw new Error("screen.json has no lines or no meta");
  return s;
}

function Pmids({ ids }: { ids: string[] }) {
  return (
    <>
      {ids.map((p, i) => (
        <span key={p}>
          {i > 0 && ", "}
          <Ext href={pubmedUrl(p)}>PMID {p}</Ext>
        </span>
      ))}
    </>
  );
}

const actionWord = (c: ScreenCard) =>
  c.action_type ? capital(c.action_type.toLowerCase()) : "Action not stated";
const isMethodHash = () => window.location.hash === "#method";
// The data file's own cap note still says "cards" and "line"; the page shows rows per condition.
const rowsWording = (t: string) =>
  t
    .replace(/\bCards\b/g, "Rows")
    .replace(/\bcards\b/g, "rows")
    .replace(/per line\b/g, "per condition");

function useSheet() {
  const [sheet, setSheet] = useState(() => window.matchMedia(SHEET_QUERY).matches);
  useEffect(() => {
    const mq = window.matchMedia(SHEET_QUERY);
    const on = () => setSheet(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return sheet;
}

export default function ResearcherApp() {
  // Acceptance lives in memory only: not stored, not in the URL (rules).
  const [accepted, setAccepted] = useState(false);
  // A page restored from the back/forward cache shows the gate again.
  useEffect(() => {
    const onShow = (e: PageTransitionEvent) => {
      if (e.persisted) setAccepted(false);
    };
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);
  // After the gate, focus moves to the page content (the button that had focus is gone).
  useEffect(() => {
    if (accepted) document.getElementById("main")?.focus({ preventScroll: true });
  }, [accepted]);
  const [screen, setScreen] = useState<Screen | null>(null);
  const [error, setError] = useState(false);
  // Nothing is selected until the reader picks a condition.
  const [lineKey, setLineKey] = useState<string | null>(null);
  const [method, setMethod] = useState(isMethodHash);
  const cameFromPage = useRef(false);

  useEffect(() => {
    loadScreen()
      .then(setScreen)
      .catch(() => setError(true));
  }, []);
  useEffect(() => {
    const onHash = () => setMethod(isMethodHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  // Each view starts at its top; back on the main view, focus returns to the method link.
  useEffect(() => {
    if (!accepted) return;
    if (method) {
      window.scrollTo(0, 0);
      document.getElementById("method-title")?.focus({ preventScroll: true });
    } else if (cameFromPage.current) {
      document.getElementById("method-link")?.focus();
    }
  }, [method, accepted]);

  const closeMethod = () => {
    if (cameFromPage.current) window.history.back();
    else {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
      setMethod(false);
      setTimeout(() => document.getElementById("main")?.focus(), 0);
    }
  };

  const meta = screen?.meta;
  const shell = (children: ReactNode) => (
    <div className="app-page rs">
      <Header
        tag="researcher view"
        onHome={() => window.location.assign("/")}
        nav={
          <a className="btn quiet" href="/">
            <span aria-hidden="true">←</span> Back to the map
          </a>
        }
      />
      <main id="main" tabIndex={-1}>
        {children}
      </main>
    </div>
  );

  if (!accepted)
    return shell(
      <section className="rs-gate card" role="region" aria-labelledby="gate-title">
        <p className="kicker">Before you continue</p>
        <h1 id="gate-title">Research screen</h1>
        <p className="rs-lead">{meta?.interstitial ?? INTERSTITIAL}</p>
        <div className="actions">
          <button type="button" className="btn primary" autoFocus onClick={() => setAccepted(true)}>
            {meta?.interstitial_continue ?? CONTINUE}
          </button>
          <a className="btn" href="/">
            {meta?.interstitial_back ?? BACK}
          </a>
        </div>
      </section>,
    );

  if (error) return shell(<LoadError />);
  if (!screen) return shell(<Skeleton />);

  const line = screen.lines.find((l) => l.key === lineKey) ?? null;
  if (method) return shell(<Method screen={screen} line={line} onBack={closeMethod} />);

  const screened = line?.status === "screened";
  const hasCards = screened && line.cards.length > 0;
  const current = !line ? 1 : hasCards ? 3 : 2;
  return shell(
    <div className="stack rs-page">
      <header className="rs-head">
        <h1>Approved medicines matched to a channel direction</h1>
        <p className="text-ink-2">
          Untested ideas for laboratory research only. Runs only for channel conditions whose
          direction a code-checked lab study confirms.
        </p>
      </header>

      <Steps current={current} line={line} />

      <section id="step-1" aria-labelledby="pick-title" className="rs-step">
        <p className="kicker">Step 1 of 3</p>
        <h2 id="pick-title" className="rs-h2">
          Pick a condition
        </h2>
        <div className="rs-chips" role="group" aria-labelledby="pick-title">
          {screen.lines.map((l) => {
            const refused = l.status === "refused";
            return (
              <button
                key={l.key}
                type="button"
                className="rs-chip"
                aria-pressed={!refused && l.key === lineKey}
                aria-disabled={refused || undefined}
                onClick={() => {
                  if (refused) return;
                  setLineKey(l.key);
                  setTimeout(() =>
                    document
                      .getElementById("step-2")
                      ?.scrollIntoView({ behavior: "smooth", block: "start" }),
                  );
                }}
              >
                <span className="rs-chip-title">{l.label}</span>
                <span className="rs-chip-sub">
                  {refused ? (
                    <>
                      <span aria-hidden="true">✕ </span>Not screened: {refusalText(l)}
                    </>
                  ) : (
                    <>{l.gloss ?? l.direction}</>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      </section>

      {line && screened && <LineScreen key={line.key} line={line} screen={screen} />}

      <p className="rs-method-link small">
        <a
          id="method-link"
          href="#method"
          onClick={() => {
            cameFromPage.current = true;
          }}
        >
          Method and sources
        </a>
      </p>
    </div>,
  );
}

function Steps({ current, line }: { current: number; line: ScreenLine | null }) {
  const zero = !!line && line.status === "screened" && line.cards.length === 0;
  const items = [
    { n: 1, label: "Pick a condition", sub: line ? line.label : "nothing picked yet" },
    { n: 2, label: "The filter", sub: line ? "four counts" : "after step 1" },
    {
      n: 3,
      label: "Candidates",
      sub: zero ? "none passed the filter" : line ? `${line.cards.length} rows` : "after step 1",
    },
  ];
  return (
    <nav aria-label="Steps">
      <ol className="rs-steps">
        {items.map((it) => {
          const state = it.n < current ? "done" : it.n === current ? "current" : "todo";
          return (
            <li
              key={it.n}
              className={`rs-step-item is-${state}`}
              aria-current={state === "current" ? "step" : undefined}
            >
              <span className="rs-step-num" aria-hidden="true">
                {state === "done" ? "✓" : it.n}
              </span>
              <span>
                <span className="rs-step-label">
                  <span className="sr-only">Step {it.n}: </span>
                  {it.label}
                </span>
                <span className="rs-step-sub">{it.sub}</span>
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function LineScreen({ line, screen }: { line: ScreenLine; screen: Screen }) {
  const m = screen.meta;
  const f = line.funnel;
  const ev = line.direction_evidence;
  const sc = line.sanity_check;
  const shown = line.cards.length;
  const nonePassed = !f || f.direction_pass === 0;
  const notShownBits = line.cards_not_shown_by_state
    ? Object.entries(line.cards_not_shown_by_state)
        .filter(([, v]) => v)
        .map(([k, v]) => `${v} ${NOT_SHOWN_LABEL[k] ?? k.replace(/_/g, " ")}`)
        .join(", ")
    : "";
  return (
    <>
      <section id="step-2" aria-labelledby="filter-title" className="rs-step stack">
        <div>
          <p className="kicker">Step 2 of 3</p>
          <h2 id="filter-title" className="rs-h2">
            The filter for {line.label}
          </h2>
          <p className="small text-ink-2">
            {capital(line.gloss ?? line.direction)}
            {ev?.pmid ? (
              <>
                {" "}
                · direction from a lab study{ev.variant ? ` of ${ev.variant}` : ""},{" "}
                <Ext href={pubmedUrl(ev.pmid)}>PMID {ev.pmid}</Ext>, {ev.level ?? "checked by code"}
              </>
            ) : (
              " · no direction evidence in the data file"
            )}
          </p>
        </div>

        <p className="rs-warning" role="note">
          <span aria-hidden="true">!</span> {m.medication_warning ?? MEDICATION_WARNING}
        </p>

        {f ? (
          <ol className="rs-funnel" aria-label="The filter, as counts">
            <li>
              <span className="rs-count">≈{n(f.approved)}</span>
              <span className="rs-count-label">
                approved medicines in Open Targets{" "}
                {m.open_targets_release ?? "(release not stated)"}
              </span>
            </li>
            <li>
              <span className="rs-count">{n(f.family)}</span>
              <span className="rs-count-label">act on the sodium-channel family</span>
            </li>
            <li>
              <span className="rs-count">{n(f.direction_pass)}</span>
              <span className="rs-count-label">match this condition's direction (code rule)</span>
            </li>
            <li>
              <span className="rs-count">{n(f.with_pair_paper ?? 0)}</span>
              <span className="rs-count-label">
                already paired with {line.gene} in a paper or study
              </span>
            </li>
          </ol>
        ) : (
          <p className="small text-ink-2">The data file holds no funnel for this condition.</p>
        )}

        {shown > 0 ? (
          <p className="rs-explain">{LIST_SENTENCE}</p>
        ) : (
          <div className="rs-zero">
            <p className="rs-zero-title">
              No approved medicine passed the direction filter for this condition
            </p>
            {m.family_direction_note ? (
              <p className="small text-ink-2">{m.family_direction_note}</p>
            ) : f ? (
              <p className="small text-ink-2">
                {n(f.family)} approved medicines act on this channel family;{" "}
                {n(line.removed_by_reason?.wrong_direction ?? f.family)} were removed because their
                recorded action goes the other way from this condition's direction
                {line.removed_by_reason?.action_unclear
                  ? `, ${n(line.removed_by_reason.action_unclear)} because their action type is unclear`
                  : ""}
                . Counts only; names of removed medicines are not shown.
              </p>
            ) : null}
            <p className="small text-ink-2">There is no candidate list for this condition.</p>
          </div>
        )}

        <details className="rs-more small text-ink-2">
          <summary>More counts: what passed, what was removed, sanity check</summary>
          {f && f.direction_pass > 0 && (
            <p>
              Of the {n(f.direction_pass)} that pass: {n(f.with_pair_paper ?? 0)} have a paper or
              study pairing drug and gene, {n(f.with_mechanism_reference_only ?? 0)} only a
              family-level mechanism reference
              {typeof f.without_paper === "number" ? `, ${n(f.without_paper)} none` : ""}.
              {typeof f.on_line_gene === "number"
                ? ` ${n(f.on_line_gene)} list ${line.gene} itself among their targets; the rest are listed against other family genes only.`
                : ""}
            </p>
          )}
          {line.removed_by_reason && (
            <p>
              Removed, counts only:{" "}
              {Object.entries(line.removed_by_reason)
                .map(([k, v]) => `${REMOVED_LABEL[k] ?? k.replace(/_/g, " ")} ${n(v)}`)
                .join(" · ")}
              . Removed medicines are never named.
            </p>
          )}
          {sc && (
            <p>
              Sanity check:{" "}
              {sc.applicable === false || nonePassed
                ? `the filter removed all ${n(sc.already_tried_total)} family medicines that a paper or study already pairs with ${line.gene}; no medicine passed for this condition.`
                : `the filter surfaced ${n(sc.surfaced)} of ${n(sc.already_tried_total)} medicines already paired with ${line.gene} in a paper or study record.`}
            </p>
          )}
          {typeof line.new_candidates === "number" && line.new_candidates > 0 && (
            <p>
              Not yet paired with {line.gene} by any paper or study: {n(line.new_candidates)} of the
              medicines that passed
              {typeof line.new_candidates_on_line_gene === "number"
                ? ` (${n(line.new_candidates_on_line_gene)} list ${line.gene} among their targets)`
                : ""}
              {shown > 0 && line.cards.every((c) => c.state === "already_studied")
                ? "; none is among the rows shown, which are all already studied for this gene"
                : ""}
              .
            </p>
          )}
        </details>
      </section>

      {shown > 0 && (
        <Candidates line={line} screen={screen} notShownBits={notShownBits} shown={shown} />
      )}
    </>
  );
}

function Candidates({
  line,
  screen,
  notShownBits,
  shown,
}: {
  line: ScreenLine;
  screen: Screen;
  notShownBits: string;
  shown: number;
}) {
  const m = screen.meta;
  const [openId, setOpenId] = useState<string | null>(null);
  const open = line.cards.find((c) => c.drug_id === openId) ?? null;
  const openIndex = open ? line.cards.indexOf(open) : -1;
  const lastRow = useRef<string | null>(null);
  const sheet = useSheet();

  const close = useCallback(() => {
    setOpenId(null);
    const id = lastRow.current;
    if (id) setTimeout(() => document.getElementById(`row-${id}`)?.focus(), 0);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    // On a narrow screen the pane is a full-width dialog sheet: the page behind it neither
    // scrolls nor takes focus.
    const root = document.getElementById("root");
    if (sheet) {
      document.body.classList.add("rs-sheet-open");
      if (root) root.inert = true;
    }
    const title = document.getElementById("detail-title");
    title?.focus({ preventScroll: true });
    if (!sheet) document.getElementById("rs-detail")?.scrollIntoView({ block: "nearest" });
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.classList.remove("rs-sheet-open");
      if (root) root.inert = false;
    };
  }, [open, close, sheet]);

  return (
    <section id="step-3" aria-labelledby="cands-title" className="rs-step stack">
      <div>
        <p className="kicker">Step 3 of 3</p>
        <h2 id="cands-title" className="rs-h2">
          Candidates: {shown} of {n(line.funnel?.direction_pass ?? shown)} that matched
        </h2>
        <p className="small text-ink-3">{capital(m.ordering_rule ?? ORDERING)}.</p>
      </div>

      <ul className="rs-legend small" aria-label="What the two labels mean">
        <li>
          <span className="badge">{ALREADY_SHORT}</span>
          <span className="text-ink-2">
            a paper or study already pairs it with {line.gene}: not a new idea
          </span>
        </li>
        <li>
          <span className="badge warn">Hypothesis</span>
          <span className="text-ink-2">
            not yet paired with {line.gene} in a paper or study; an idea for laboratory testing only
          </span>
        </li>
      </ul>

      <div className={`rs-browse${open ? " has-open" : ""}`}>
        <div className="rs-table-wrap">
          <table className="rs-table">
            <caption className="sr-only">
              Candidates for {line.label}; choose a row to open its details
            </caption>
            <thead>
              <tr>
                <th scope="col" className="rs-col-num">
                  <span className="sr-only">Order</span>
                </th>
                <th scope="col">Medicine</th>
                <th scope="col">Action on the channel</th>
                <th scope="col" className="rs-col-papers">
                  Papers
                </th>
                <th scope="col">Label</th>
                <th scope="col" className="rs-col-chev">
                  <span className="sr-only">Open</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {line.cards.map((c, i) => {
                const isOpen = c.drug_id === openId;
                const already = c.state === "already_studied";
                return (
                  <tr key={c.drug_id} className={isOpen ? "is-open" : undefined}>
                    <td className="rs-col-num">{i + 1}</td>
                    <th scope="row" className="rs-col-name">
                      <button
                        type="button"
                        id={`row-${c.drug_id}`}
                        className="rs-row-btn"
                        aria-expanded={isOpen}
                        aria-controls="rs-detail"
                        onClick={() => {
                          lastRow.current = c.drug_id;
                          if (isOpen) close();
                          else setOpenId(c.drug_id);
                        }}
                      >
                        {titleCase(c.name)}
                      </button>
                    </th>
                    <td className="rs-col-action">
                      {actionWord(c)}
                      {c.effect ? <span className="rs-sub"> {c.effect} activity</span> : null}
                      <span className="rs-papers-inline">
                        {" "}
                        · {n(c.evidence.pubmed_count ?? 0)} paper
                        {(c.evidence.pubmed_count ?? 0) === 1 ? "" : "s"}
                      </span>
                    </td>
                    <td className="rs-col-papers">
                      {n(c.evidence.pubmed_count ?? 0)}
                      <span className="rs-sub rs-papers-word">
                        {" "}
                        paper{(c.evidence.pubmed_count ?? 0) === 1 ? "" : "s"}
                      </span>
                    </td>
                    <td className="rs-col-state">
                      {already ? (
                        <span className="badge">{ALREADY_SHORT}</span>
                      ) : (
                        <span className="badge warn">Hypothesis</span>
                      )}
                    </td>
                    <td className="rs-col-chev" aria-hidden="true">
                      {isOpen ? "‹" : "›"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {open &&
          (sheet ? (
            createPortal(
              <Detail
                card={open}
                index={openIndex}
                line={line}
                screen={screen}
                onClose={close}
                modal
              />,
              document.body,
            )
          ) : (
            <Detail card={open} index={openIndex} line={line} screen={screen} onClose={close} />
          ))}
      </div>
      {line.cards_not_shown ? (
        <p className="small text-ink-3">
          {n(line.cards_not_shown)} more matched and are not listed
          {notShownBits ? ` (${notShownBits})` : ""}.{" "}
          {rowsWording(
            line.cards_not_shown_reason ??
              "Rows are capped at 10 per condition in the fixed order.",
          )}
        </p>
      ) : null}
    </section>
  );
}

function Detail({
  card: c,
  index,
  line,
  screen,
  onClose,
  modal = false,
}: {
  card: ScreenCard;
  index: number;
  line: ScreenLine;
  screen: Screen;
  onClose: () => void;
  modal?: boolean;
}) {
  const m = screen.meta;
  const cr = c.critique;
  const prov = cr.provenance ?? null;
  const readFrom = cr.evidence_read ?? m.evidence_read ?? null;
  const nextLabel = cr.next_test ? (m.next_test_labels?.[cr.next_test] ?? cr.next_test) : null;
  const studies = c.evidence.studies ?? [];
  const already = c.state === "already_studied";
  // The model writes the card's own drug name in upper case (the Open Targets form); shown in
  // title case to match the heading. Only that exact token is changed, never other words.
  const ownName = (t: string) =>
    t
      .split(new RegExp(`\\b(${c.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})\\b`))
      .map((part) => (part === c.name ? titleCase(part) : part));
  const cited = (w: { text: string; pmid?: string | null }) => (
    <>
      {ownName(w.text)}
      {w.pmid ? (
        <span className="text-ink-3">
          {" "}
          (<Ext href={pubmedUrl(w.pmid)}>PMID {w.pmid}</Ext>)
        </span>
      ) : null}
    </>
  );
  return (
    <aside
      id="rs-detail"
      className={`rs-detail${modal ? " is-sheet" : ""}`}
      aria-labelledby="detail-title"
      role={modal ? "dialog" : undefined}
      aria-modal={modal || undefined}
    >
      <div className="rs-detail-bar">
        <button type="button" className="btn quiet rs-detail-close" onClick={onClose}>
          <span className="rs-back-word">
            <span aria-hidden="true">←</span> Back to the list
          </span>
          <span className="rs-close-word">
            Close <span aria-hidden="true">✕</span>
          </span>
        </button>
      </div>
      <div className="rs-detail-body">
        <p className="kicker">Row {index + 1} · details</p>
        <h3 id="detail-title" tabIndex={-1}>
          {titleCase(c.name)}
        </h3>
        <div className="rs-detail-badges">
          {already ? (
            <span className="badge">{m.already_studied_caption ?? ALREADY_STUDIED}</span>
          ) : null}
          <span className="badge warn">{m.hypothesis_label ?? HYPOTHESIS}</span>
        </div>
        <p className="small text-ink-2">
          <Ext href={openTargetsDrugUrl(c.drug_id)} extraHosts={RESEARCHER_HOSTS}>
            {c.drug_id}
          </Ext>
          {c.max_stage === "APPROVAL"
            ? " · approved (Open Targets)"
            : c.max_stage
              ? ` · Open Targets stage ${c.max_stage.toLowerCase()}`
              : ""}
          {" · "}
          {c.action_type ? c.action_type.toLowerCase() : "action not stated"}
          {c.effect ? `, ${c.effect} channel activity` : ""} · this condition: {line.direction}
          {c.targets?.length ? (
            <>
              {" · "}
              {sameSet(c.targets, m.family_genes)
                ? `targets all ${c.targets.length} family genes`
                : `targets ${c.targets.join(", ")}`}
              {c.on_line_gene === false ? ` (${line.gene} itself is not among them)` : ""}
            </>
          ) : null}
        </p>
        {m.target_caption ? <p className="small text-ink-3">{m.target_caption}</p> : null}

        <h4>Papers and registered studies</h4>
        <dl className="rs-facts small">
          <dt>Papers pairing it with {line.gene}</dt>
          <dd>
            {n(c.evidence.pubmed_count ?? 0)}
            {c.evidence.pmids?.length ? (
              <>
                {": "}
                <Pmids ids={c.evidence.pmids} />
              </>
            ) : (
              ": none"
            )}
          </dd>
          {c.evidence.opentargets_pmids?.length ? (
            <>
              <dt>Mechanism references (Open Targets, family level)</dt>
              <dd>
                <Pmids ids={c.evidence.opentargets_pmids} />
              </dd>
            </>
          ) : null}
          <dt>Registered studies pairing it with {line.gene}</dt>
          <dd>
            {studies.length === 0 ? "none found in the data file" : null}
            {studies.map((s) => (
              <span key={s.nct} className="block">
                <Ext href={nctUrl(s.nct)}>{s.nct}</Ext>
                {s.status ? ` · ${s.status.toLowerCase().replace(/_/g, " ")}` : ""}
                {s.start_date ? ` · began ${s.start_date}` : ""}
                {s.last_update ? ` · last updated ${s.last_update}` : ""}
                {s.why_stopped ? (
                  <>
                    {" "}
                    , reason in the sponsor's words: "{s.why_stopped}". {STOPPED_SENTENCE}
                  </>
                ) : s.why_stopped_withheld ? (
                  <>, stop reason withheld pending a human check. {STOPPED_SENTENCE}</>
                ) : null}
              </span>
            ))}
          </dd>
        </dl>

        {cr.status !== "checked_by_code" ? (
          <p className="small text-ink-2 rs-section">
            {cr.reason ?? "No model notes for this medicine in this build."}
          </p>
        ) : (
          <>
            <div className="rs-why">
              <div>
                <h4>{already ? "Why it matches this condition" : "Why it was proposed"}</h4>
                {cr.why?.length ? (
                  <ul className="rs-plain small">
                    {cr.why.map((w, i) => (
                      <li key={i}>{cited(w)}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="small text-ink-2">No sentence passed the code check.</p>
                )}
              </div>
              <div>
                <h4>Doubts</h4>
                {cr.doubts?.length ? (
                  <ul className="rs-plain small">
                    {cr.doubts.map((w, i) => (
                      <li key={i}>
                        {cited(w)}
                        {w.kind && m.doubt_kind_labels?.[w.kind] ? (
                          <span className="text-ink-3"> · {m.doubt_kind_labels[w.kind]}</span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="small text-ink-2">None recorded.</p>
                )}
              </div>
            </div>
            {cr.unchecked_reasoning?.length ? (
              <div className="rs-unchecked">
                <h4>{UNCHECKED_HEADING}</h4>
                <ul className="rs-plain small">
                  {cr.unchecked_reasoning.map((t, i) => (
                    <li key={i}>{ownName(t)}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            <p className="provenance">
              Written by {prov?.model ?? "the build-time model"} at build time
              {prov?.run_at ? ` on ${String(prov.run_at).slice(0, 10)}` : ""} from the cited paper
              titles; checked by code
              {readFrom
                ? ` (the model read paper ${readFrom.replace(/^title only$/, "titles only")})`
                : ""}
              .
            </p>
          </>
        )}

        <p className="small rs-next">
          <strong>Fixed next test:</strong> {nextLabel ?? "none recorded for this row"}{" "}
          <span className="text-ink-3">
            (one of four fixed laboratory steps; not a clinical step)
          </span>
        </p>
      </div>
    </aside>
  );
}

function Method({
  screen,
  line,
  onBack,
}: {
  screen: Screen;
  line: ScreenLine | null;
  onBack: () => void;
}) {
  const m = screen.meta;
  const model = line?.cards.find((c) => c.critique.provenance?.model)?.critique.provenance?.model;
  return (
    <article className="rs-method stack" aria-labelledby="method-title">
      <div>
        <button type="button" className="btn quiet rs-back" onClick={onBack}>
          <span aria-hidden="true">←</span> Back to the screen
        </button>
      </div>
      <div>
        <p className="kicker">
          Data: {m.source ?? "source not stated"} · Open Targets{" "}
          {m.open_targets_release ?? "release not stated"} · pool retrieved{" "}
          {m.retrieved ?? "date not stated"} · papers and studies retrieved{" "}
          {m.evidence_retrieved ?? "date not stated"}
        </p>
        <h1 id="method-title" tabIndex={-1}>
          Method and sources
        </h1>
      </div>
      <ol className="small">
        <li>
          <strong>Drug pool.</strong> The approved medicines in the Open Targets Platform{" "}
          {m.open_targets_release ?? ""} (CC0; includes ChEMBL
          {m.chembl_version ? ` ${m.chembl_version.replace(/^ChEMBL_?/i, "")}` : ""}), retrieved{" "}
          {m.retrieved ?? "date not stated"}.
          {m.approved_total_method
            ? ` Approved total: ${m.approved_total_method.replace("APPROVAL", "approval")}.`
            : ""}{" "}
          The family pool is the subset with a recorded mechanism of action against the{" "}
          {m.family_label ?? "channel family"}
          {m.family_genes?.length ? ` (${m.family_genes.join(", ")})` : ""}
          {m.family_effects
            ? `: ${n(m.family_effects.reduces ?? 0)} reduce channel activity, ${n(m.family_effects.increases ?? 0)} increase it, ${n(m.family_effects.unclear ?? 0)} have no mapped direction`
            : ""}
          .{m.family_coverage_note ? ` ${m.family_coverage_note}` : ""}
        </li>
        <li>
          <strong>Direction filter</strong> ({m.rule_version ?? "rule version not stated"}). The
          recorded action type must act against the condition's direction (a blocker for a
          gain-of-function condition). The direction comes from{" "}
          {m.direction_source === "graph_direction_evidence"
            ? "the code-checked lab study in the family map"
            : "the engine's known direction"}
          {line?.direction_evidence?.pmid ? ` (PMID ${line.direction_evidence.pmid})` : ""}.{" "}
          {m.direction_filter_note ?? ""} {m.removed_counts_note ?? ""}
        </li>
        <li>
          <strong>Papers and studies.</strong> PubMed query{" "}
          <code>{m.pubmed_query_form ?? "drug and gene in title/abstract"}</code> and
          ClinicalTrials.gov pairs, retrieved {m.evidence_retrieved ?? "date not stated"}; up to
          five PMIDs are listed per row, the full count is shown.
          {m.pubmed_query_note ? ` ${m.pubmed_query_note}` : ""}
          {typeof m.studies_found === "number"
            ? ` Registered studies found over every pair: ${n(m.studies_found)}.`
            : ""}{" "}
          {m.target_caption ?? ""}
        </li>
        <li>
          <strong>Counts.</strong> {plainNote(m.sanity_check_note)}{" "}
          {plainNote(m.new_candidates_note)}
        </li>
        <li>
          <strong>Model critique.</strong> {model ?? "The build-time model"} read the row facts and
          paper {m.evidence_read === "title only" ? "titles only" : (m.evidence_read ?? "titles")},
          as data, and wrote why and doubts; code kept only sentences that cite one of the row's
          PMIDs and contain no other drug name and no deny-listed word; the rest sits under "
          {UNCHECKED_HEADING}". The next test is picked from a closed list of four laboratory steps.
          Nothing calls a model when you click.
        </li>
        <li>
          <strong>Order.</strong> Rows are {m.ordering_rule ?? ORDERING}; a halted study is never a
          ranking signal and never part of the funnel. "
          {m.already_studied_caption ?? ALREADY_STUDIED}" marks a medicine that a paper or study
          already pairs with the gene.
        </li>
        <li>
          <strong>Scope and labels.</strong> Channel conditions with a code-checked direction only.{" "}
          {m.badge ?? AI_BADGE}: no person has signed any of this.{" "}
          {m.medication_warning ?? MEDICATION_WARNING}
        </li>
      </ol>
      <section aria-labelledby="sources-title">
        <h2 id="sources-title" className="rs-h2">
          Sources
        </h2>
        <ul className="small text-ink-2 rs-sources">
          {(
            m.sources ?? [
              `Drug and mechanism data: Open Targets Platform ${m.open_targets_release ?? ""} (CC0 1.0), incl. ChEMBL (EMBL-EBI)`,
              "Citations from PubMed (NLM)",
              "Data from ClinicalTrials.gov (NLM)",
            ]
          ).map((s) => (
            <li key={s}>{s}.</li>
          ))}
          <li>Listing does not imply NLM endorsement.</li>
        </ul>
      </section>
      <div>
        <button type="button" className="btn" onClick={onBack}>
          <span aria-hidden="true">←</span> Back to the screen
        </button>
      </div>
    </article>
  );
}

// Search and the routing states, with their fixed copy.
import { useId, useRef, useState } from "react";
import type { Alias, Graph } from "../types";
import { claimsForVariant, conflictForVariant, counts, preComputedDate } from "../data";
import { canonicalVariant } from "../variants";
import { DIRECTORIES, nctUrl, orphaUrl, pubmedUrl } from "../links";
import { type Index, type Resolution, resolve, suggest } from "../search";
import { Ext, asOf } from "../shared/Layout";

// --- Search --------------------------------------------------------------------------------

export function Search({
  index,
  onResolve,
  autoFocus,
  compact,
  initial,
  examples,
}: {
  index: Index;
  onResolve: (r: Resolution, raw: string) => void;
  autoFocus?: boolean;
  compact?: boolean; // the small box in the panel header: no button, no note
  initial?: string; // the last typed query, kept in memory only so a typo can be corrected
  examples?: string[]; // the slim bar: a focus dropdown with the hint, these chips and suggestions
}) {
  const [q, setQ] = useState(initial ?? "");
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(-1);
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const items = open ? suggest(index, q) : [];
  const bar = !!examples;
  const dropdown = bar && open;

  const go = (raw: string) => {
    if (!raw.trim()) return; // an empty box is not a search
    setOpen(false);
    onResolve(resolve(index, raw), raw);
  };

  return (
    <div className={`search ${compact ? "compact" : ""}`} role="search">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (cursor >= 0 && items[cursor]) go(items[cursor].term);
          else go(q);
        }}
      >
        <label className="sr-only" htmlFor={`${listId}-input`}>
          Search a disease, gene, variant, organisation, mechanism or symptom
        </label>
        {/* The input and its list share one box, so the list spans the input only. */}
        <div className="search-field">
          <input
            id={`${listId}-input`}
            ref={inputRef}
            type="search"
            autoComplete="off"
            maxLength={200}
            autoFocus={autoFocus}
            placeholder={
              compact || bar
                ? "Gene, diagnosis, variant or symptom"
                : "Disease, gene, variant (R853Q or p.Arg853Gln), organisation, symptom"
            }
            value={q}
            role="combobox"
            aria-expanded={items.length > 0}
            aria-autocomplete="list"
            aria-activedescendant={cursor >= 0 ? `${listId}-${cursor}` : undefined}
            onChange={(e) => {
              setQ(e.target.value);
              setOpen(true);
              setCursor(-1);
            }}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            aria-controls={dropdown ? `${listId}-drop` : listId}
            // Opens on a pointer click, on typing or on ArrowDown; never on focus alone, so a
            // programmatic focus (after the intro, after Back) does not drop the panel open.
            onPointerDown={() => setOpen(true)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                if (!open) setOpen(true);
                else setCursor((c) => Math.min(c + 1, items.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setCursor((c) => Math.max(c - 1, -1));
              } else if (e.key === "Escape") {
                // Close the list and keep the text (the native search field would clear it and
                // its input event would reopen the list).
                e.preventDefault();
                setOpen(false);
                setCursor(-1);
              }
            }}
          />
          {dropdown ? (
            <div className="suggest drop" id={`${listId}-drop`}>
              <p className="small muted m-0">
                Type your child's gene, diagnosis, variant or symptom.
              </p>
              {items.length === 0 && (
                <>
                  <p className="kicker mt-2 mb-1">Try</p>
                  <div className="chips">
                    {examples.map((t) => (
                      <button
                        key={t}
                        type="button"
                        className="chip"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => go(t)}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                </>
              )}
              {items.length > 0 && (
                <div className="mt-2">
                  <ul
                    className={dropdown ? "m-0 list-none p-0" : "suggest"}
                    id={listId}
                    role="listbox"
                  >
                    {items.map((a, i) => (
                      <li
                        key={`${a.kind}-${a.term}`}
                        role="option"
                        aria-selected={i === cursor}
                        id={`${listId}-${i}`}
                      >
                        <button
                          type="button"
                          aria-selected={i === cursor}
                          onMouseDown={(e) => e.preventDefault()}
                          onClick={() => go(a.term)}
                        >
                          <span>{a.term}</span>
                          <span className="kind">
                            {a.kind === "group"
                              ? "several genes"
                              : a.kind === "id"
                                ? "ID"
                                : a.kind === "study"
                                  ? "study or resource"
                                  : a.kind}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="small muted mt-2 mb-0">
                Variants are matched in your browser and never sent anywhere.
              </p>
            </div>
          ) : (
            items.length > 0 && (
              <ul className={dropdown ? "m-0 list-none p-0" : "suggest"} id={listId} role="listbox">
                {items.map((a, i) => (
                  <li
                    key={`${a.kind}-${a.term}`}
                    role="option"
                    aria-selected={i === cursor}
                    id={`${listId}-${i}`}
                  >
                    <button
                      type="button"
                      aria-selected={i === cursor}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => go(a.term)}
                    >
                      <span>{a.term}</span>
                      <span className="kind">
                        {a.kind === "group"
                          ? "several genes"
                          : a.kind === "id"
                            ? "ID"
                            : a.kind === "study"
                              ? "study or resource"
                              : a.kind}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )
          )}
        </div>
        {!compact && (
          <button type="submit" className="btn primary">
            Search
          </button>
        )}
      </form>
      {!compact && !bar && (
        <p className="small muted" style={{ marginTop: 8 }}>
          Variants are matched in your browser and never sent anywhere.
        </p>
      )}
    </div>
  );
}

// --- Which direction? ------------------------------------------------------------------------

export function DirectionStep({
  graph,
  gene,
  onPick,
}: {
  graph: Graph;
  gene: string;
  onPick: (d: "gain" | "loss" | "unknown") => void;
}) {
  const lines = graph.lines.filter((l) => l.gene === gene);
  const has = (d: string) => lines.some((l) => l.direction === d);
  return (
    <section className="card" aria-labelledby="dir-title">
      <p className="kicker">{gene}</p>
      <h1 id="dir-title">Which direction?</h1>
      <p>
        In {gene}, different variants cause opposite problems. Your child's specific variant decides
        which applies. Ask your geneticist.
      </p>
      <div className="chips" style={{ marginTop: 12 }}>
        <button type="button" className="btn" onClick={() => onPick("gain")}>
          <span className="swatch" style={{ background: "var(--gain)" }} aria-hidden="true" /> Too
          strong (gain)
        </button>
        <button type="button" className="btn" onClick={() => onPick("loss")}>
          <span className="swatch" style={{ background: "var(--loss)" }} aria-hidden="true" /> Too
          weak (loss)
        </button>
        <button type="button" className="btn" onClick={() => onPick("unknown")}>
          ? Don't know
        </button>
      </div>
      {(!has("gain") || !has("loss")) && (
        <p className="small muted" style={{ marginTop: 12 }}>
          {!has("gain") && !has("loss")
            ? `Neither direction of ${gene} is mapped yet: each choice shows registries and care networks only.`
            : `${!has("gain") ? "Gain" : "Loss"} of function in ${gene} isn't mapped yet: that choice shows registries and care networks only.`}
        </p>
      )}
    </section>
  );
}

/** A direction with no shipped line: registries and care networks only. */
export function FormNotMapped({
  graph,
  gene,
  direction,
  onBack,
}: {
  graph: Graph;
  gene: string;
  direction: string;
  onBack: () => void;
}) {
  const registries = graph.assets.filter(
    (a) =>
      (a.type === "registry" || a.type === "care_network") &&
      (a.owner_gene === gene || a.open_to_all),
  );
  const shownNcts = new Set(
    registries.map((a) => /NCT\d{8}/.exec(`${a.label} ${a.source.url}`)?.[0]).filter(Boolean),
  );
  const shared = graph.studies.filter(
    (s) =>
      (s.kind === "registry" || s.kind === "eligible_gene_list") &&
      s.genes_named?.includes(gene) &&
      !shownNcts.has(s.nct),
  );
  return (
    <section className="card">
      <p className="kicker">
        {gene} ·{" "}
        {direction === "gain"
          ? "too strong (gain)"
          : direction === "loss"
            ? "too weak (loss)"
            : "direction not known"}
      </p>
      <h1>This condition isn't mapped yet.</h1>
      <p>We only show registries and care networks for it: no medicines, trials or models.</p>
      {registries.length + shared.length === 0 ? (
        <p className="muted">No registry for {gene} is in the data file yet.</p>
      ) : (
        <ul className="list">
          {registries.map((a) => (
            <li key={a.id}>
              <span className="sign ok" aria-hidden="true">
                ✓
              </span>
              <span>
                <Ext href={a.source.url}>{a.label}</Ext>{" "}
                <span className="muted small">· {asOf(a.last_verified ?? a.source.retrieved)}</span>
              </span>
            </li>
          ))}
          {shared.map((s) => (
            <li key={s.nct}>
              <span className="sign ok" aria-hidden="true">
                ✓
              </span>
              <span>
                <Ext href={nctUrl(s.nct)}>
                  {s.name} ({s.nct})
                </Ext>{" "}
                <span className="muted small">
                  ·{" "}
                  {s.kind === "eligible_gene_list"
                    ? "an eligible-gene list; the study team decides who can take part"
                    : "registry"}
                  {" · "}
                  {asOf(s.retrieved ?? s.source?.retrieved)}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
      <h2 className="mt-3">Next steps</h2>
      <ol className="m-0 grid gap-1 pl-5 text-sm">
        {registries[0] && (
          <li>
            Join what is already open to you:{" "}
            <Ext href={registries[0].source.url}>{registries[0].label}</Ext>.
          </li>
        )}
        {!registries[0] && shared[0] && (
          <li>
            Join what is already open to you:{" "}
            <Ext href={nctUrl(shared[0].nct)}>{shared[0].name}</Ext>.
          </li>
        )}
        <li>Ask your geneticist whether this variant's function has been tested in a lab.</li>
      </ol>
      <div className="actions">
        <button type="button" className="btn" onClick={onBack}>
          Back to search
        </button>
      </div>
    </section>
  );
}

// --- Gene picker (Orphanet entries, symptoms and variant names shared by several genes) ------

const PICKER_COPY: Record<string, { heading: string; note: string }> = {
  group: {
    heading: "This code covers several genes. Which is yours?",
    note: "We list only the genes in this entry that Polaris has mapped.",
  },
  symptom: {
    heading: "Several conditions share this symptom. Which gene is your child's?",
    note: "A symptom alone does not point to one gene. We list only the genes Polaris has mapped.",
  },
  variant: {
    heading: "This variant name exists in several genes. Which is your child's?",
    note: "The same position can be written for different genes; the gene decides which condition applies.",
  },
  study: {
    heading: "Several conditions are named in this study or resource. Which gene is your child's?",
    note: "We list only the genes Polaris has mapped; the study team decides who can take part.",
  },
};

export function GenePicker({
  alias,
  onGene,
  onNotListed,
}: {
  alias: Alias;
  onGene: (g: string) => void;
  onNotListed: () => void;
}) {
  const copy = PICKER_COPY[alias.kind] ?? PICKER_COPY.symptom;
  return (
    <section className="card">
      <p className="kicker">
        {alias.orpha ? <Ext href={orphaUrl(alias.orpha)}>{alias.orpha}</Ext> : alias.term}
        {alias.group_size ? ` · ${alias.group_size} genes in this entry` : ""}
      </p>
      <h1>{copy.heading}</h1>
      <p className="small muted">{copy.note}</p>
      <div className="chips">
        {(alias.genes ?? []).map((g) => (
          <button key={g} type="button" className="chip" onClick={() => onGene(g)}>
            {g}
          </button>
        ))}
        <button type="button" className="chip" onClick={onNotListed}>
          My child's gene isn't listed
        </button>
      </div>
    </section>
  );
}

// --- Out of slice ----------------------------------------------------------------------------

export function GapState({
  graph,
  query,
  onOpenLine,
}: {
  graph: Graph;
  query: string;
  onOpenLine: (k: string) => void;
}) {
  const c = counts(graph);
  // The typed text is echoed once, capped, and goes nowhere else (no URL, no title, no request).
  const shown = query.trim().length > 60 ? `${query.trim().slice(0, 60)}…` : query.trim();
  return (
    <section className="card" aria-labelledby="gap-title">
      <h1 id="gap-title">Not mapped yet</h1>
      <p className="wrap-any">
        Polaris currently covers {c.lines} conditions of {c.genes} epilepsy gene
        {c.genes === 1 ? "" : "s"}.{" "}
        {shown ? (
          <>Not finding '{shown}' doesn't mean nothing exists, only that we haven't checked.</>
        ) : (
          <>Not finding a term here doesn't mean nothing exists, only that we haven't checked.</>
        )}{" "}
        Map built {preComputedDate(graph) || "(date not in the data file)"}.
      </p>
      <p className="small muted">
        Adding a condition is a data task, not new code: its papers, study records and organisation
        go through the same extraction, checks and rules, and the map picks it up on the next build.
      </p>
      <p className="kicker">Covered conditions</p>
      <div className="chips">
        {graph.lines.map((l) => (
          <button key={l.key} type="button" className="chip" onClick={() => onOpenLine(l.key)}>
            {l.label}
          </button>
        ))}
      </div>
      <h2 className="mt-4">Next steps</h2>
      <ol className="m-0 grid gap-1 pl-5 text-sm">
        {DIRECTORIES.map((d) => (
          <li key={d.name}>
            Look it up in <Ext href={d.url}>{d.name}</Ext>.
          </li>
        ))}
        <li>Send us a paper that tests a variant in this condition.</li>
      </ol>
    </section>
  );
}

// --- Unknown variant --------------------------------------------------------------------------

export function UnknownVariant({
  graph,
  gene,
  variant,
  onContinueGated,
  onContinueLine,
}: {
  graph: Graph;
  gene: string;
  variant: string;
  onContinueGated: () => void;
  onContinueLine: (k: string) => void;
}) {
  const lines = graph.lines.filter((l) => l.gene === gene);
  // A channel gene: a shipped channel line, or a gene the alias table sends to "Which direction?".
  const channel =
    lines.some((l) => l.mechanism_family === "ion_channel") ||
    graph.aliases.some((a) => a.direction_step && a.gene === gene);
  const condition = lines.length === 1 ? lines[0] : null;
  return (
    <section className="card">
      <p className="kicker">
        {gene} · <span className="as-is">{variant}</span>
      </p>
      <h1>We haven't found a lab study of this variant</h1>
      {channel ? (
        <p>
          So we can't tell whether it makes the channel work too strongly or too weakly, and we
          won't guess. This is set by the specific variant.
        </p>
      ) : (
        <p>For {gene}, we show what applies to the condition as a whole.</p>
      )}
      <p className="small muted">Variants are matched in your browser and never sent anywhere.</p>
      <p>
        <strong>Ask your geneticist:</strong> has this variant's function been tested in a lab?
      </p>
      <div className="actions">
        {channel ? (
          <button type="button" className="btn primary" onClick={onContinueGated}>
            Continue with {gene}, direction not known
          </button>
        ) : condition ? (
          <button
            type="button"
            className="btn primary"
            onClick={() => onContinueLine(condition.key)}
          >
            Continue to {condition.label}
          </button>
        ) : null}
      </div>
      {channel && (
        <p className="small muted">
          That path shows registries, care networks and outcome measures only.
        </p>
      )}
    </section>
  );
}

// --- Mixed direction: the lab studies of this variant disagree ----------------------------------

export function MixedVariant({
  graph,
  gene,
  variant,
  pmid,
  onContinueGated,
}: {
  graph: Graph;
  gene: string;
  variant: string;
  pmid?: string | null;
  onContinueGated: () => void;
}) {
  const canon = canonicalVariant(variant) ?? variant.toLowerCase();
  const conflict = conflictForVariant(graph, gene, canon);
  const claims = claimsForVariant(graph, gene, canon);
  const pmids = [...new Set([pmid, ...claims.map((c) => c.pmid)].filter(Boolean))] as string[];
  const registries = graph.studies.filter(
    (s) =>
      (s.kind === "registry" || s.kind === "eligible_gene_list") && s.genes_named?.includes(gene),
  );
  return (
    <section className="card" aria-labelledby="mixed-title">
      <p className="kicker">
        {gene} · <span className="as-is">{variant}</span>
      </p>
      <h1 id="mixed-title">Sources disagree on gain vs loss</h1>
      {claims.length ? (
        <ul className="list">
          {claims.map((c, i) => (
            <li key={c.claim_id}>
              <span className="sign">–</span>
              <span>
                Lab study {String.fromCharCode(65 + i)} says{" "}
                {c.direction === "mixed" ? "both gain and loss" : c.direction} of function: "
                {c.evidence_quote}" (<Ext href={pubmedUrl(c.pmid)}>PMID {c.pmid}</Ext>)
              </span>
            </li>
          ))}
        </ul>
      ) : conflict ? (
        <ul className="list">
          {conflict.sides.map((side, i) => {
            const pmid = /PMID (\d+)/.exec(side.source.label)?.[1];
            // A claim of the same paper whose sentence names this variant carries its quote.
            const short = canon.replace(/^p\./, "");
            const quoted = pmid
              ? graph.claims.find(
                  (c) =>
                    c.pmid === pmid &&
                    new RegExp(
                      `\\b(p\\.)?${short}\\b|${variant.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`,
                      "i",
                    ).test(c.evidence_quote),
                )
              : undefined;
            const word = /gain/i.test(side.says)
              ? "gain of function"
              : /loss/i.test(side.says)
                ? "loss of function"
                : side.says;
            return (
              <li key={i}>
                <span className="sign">–</span>
                <span>
                  Lab study {String.fromCharCode(65 + i)} says {word}
                  {quoted ? (
                    <>
                      : "{quoted.evidence_quote}" (
                      <Ext href={side.source.url}>{side.source.label}</Ext>)
                    </>
                  ) : (
                    <>
                      {" "}
                      (<Ext href={side.source.url}>{side.source.label}</Ext>; no quote in our data
                      {side.source.retrieved ? `, retrieved ${side.source.retrieved}` : ""})
                    </>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p>
          The lab studies of this variant reach opposite directions
          {pmids.length ? (
            <>
              {" "}
              (
              {pmids.map((p, i) => (
                <span key={p}>
                  {i > 0 && ", "}
                  <Ext href={pubmedUrl(p)}>PMID {p}</Ext>
                </span>
              ))}
              )
            </>
          ) : null}
          .
        </p>
      )}
      {conflict?.note && <p className="small muted">{conflict.note}</p>}
      <p>
        Until this is settled, we don't suggest sharing medicines, trials or models. Registries and
        care networks can still be shared.
      </p>
      <p className="small muted">Variants are matched in your browser and never sent anywhere.</p>
      <p>
        <strong>Questions to bring to your neurologist:</strong> which of these studies tested a
        variant like my child's, and in which direction? Has my child's own variant been tested in a
        lab?
      </p>
      <div className="actions">
        <button type="button" className="btn primary" onClick={onContinueGated}>
          Continue with {gene}, direction not known
        </button>
      </div>
      {registries.length > 0 && (
        <p className="small">
          <strong>Registries that name {gene}:</strong>{" "}
          {registries.map((s, i) => (
            <span key={s.nct}>
              {i > 0 && " · "}
              <Ext href={nctUrl(s.nct)}>
                {s.name} ({s.nct})
              </Ext>
              {s.kind === "eligible_gene_list"
                ? " (an eligible-gene list; the study team decides who can take part)"
                : ""}
            </span>
          ))}
        </p>
      )}
    </section>
  );
}

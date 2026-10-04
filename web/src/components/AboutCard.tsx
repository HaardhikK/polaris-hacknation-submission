// One About-page card: a short heading, two or three lines of key facts and a "More info"
// button that expands the card in place to the full width of the grid. The parent keeps
// which card is open (one at a time); Escape or "Less" collapses it and returns focus.
import { useEffect, useRef, type ReactNode } from "react";

const TONE = {
  plain: "border border-[var(--hair)] bg-[var(--paper)]",
  feature: "border border-[var(--accent)] bg-[var(--paper)]",
  highlight: "border-2 border-[var(--accent)] bg-[var(--paper)]",
};

export function AboutCard({
  id,
  title,
  summary,
  children,
  open,
  onToggle,
  tone = "plain",
  kicker,
  action,
  wide = false,
}: {
  id: string;
  title: string;
  /** Two or three short lines of the key facts, shown closed and open. */
  summary: ReactNode;
  /** The in-depth text, shown only when the card is open. */
  children: ReactNode;
  open: boolean;
  onToggle: (id: string | null) => void;
  tone?: keyof typeof TONE;
  kicker?: string;
  /** A second control beside "More info" (e.g. a link to another page). */
  action?: ReactNode;
  /** Full width even when closed. */
  wide?: boolean;
}) {
  const card = useRef<HTMLElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(open);

  // On open, bring the grown card into view; on close, put focus back on its button when
  // focus was inside the card (or lost to the page), so keyboard users keep their place.
  useEffect(() => {
    if (open && !wasOpen.current) {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      card.current?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
    }
    if (!open && wasOpen.current) {
      const a = document.activeElement;
      if (!a || a === document.body || card.current?.contains(a)) button.current?.focus();
    }
    wasOpen.current = open;
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) {
        e.preventDefault();
        button.current?.focus();
        onToggle(null);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onToggle]);

  const big = tone === "highlight";
  const span = open || wide ? "sm:col-span-2" : "";
  return (
    <article
      ref={card}
      aria-labelledby={`${id}-title`}
      className={`flex scroll-mt-4 flex-col rounded-[var(--radius)] ${TONE[tone]} ${span} ${
        big ? "p-5" : "p-4"
      } ${open ? "" : big ? "min-h-[180px]" : "min-h-[150px]"}`}
    >
      {kicker && <p className="kicker">{kicker}</p>}
      <h3
        id={`${id}-title`}
        className={`${big ? "text-[19px]" : "text-[15px]"} ${tone === "plain" ? "" : "text-[var(--accent-strong)]"}`}
      >
        {title}
      </h3>
      <div className={`${big ? "text-[15px]" : "text-[13px]"} text-[var(--ink-2)] [&>p]:mb-1.5`}>
        {summary}
      </div>
      <div
        id={`${id}-more`}
        hidden={!open}
        className="mt-3 border-t border-[var(--hair)] pt-3 text-[14px] text-[var(--ink)]"
      >
        {open && children}
      </div>
      <div className="mt-auto flex flex-wrap items-center justify-end gap-2 pt-3">
        <span className="flex flex-wrap items-center gap-2">
          {action}
          <button
            ref={button}
            type="button"
            className="btn"
            aria-expanded={open}
            aria-controls={`${id}-more`}
            onClick={() => onToggle(open ? null : id)}
          >
            {open ? "Less" : "More info"}
            <span className="sr-only">: {title}</span>
          </button>
        </span>
      </div>
    </article>
  );
}

// Shared chrome for every Polaris page (the map and the researcher screen): top bar,
// provenance labels, safe outbound links, loading and error states.
import { Component, useLayoutEffect, useRef, type CSSProperties, type ReactNode } from "react";
import { safeUrl } from "../links";

export const MEDICATION_WARNING =
  "Not medical advice. Never change or stop a medication without your child's neurologist.";
export const AI_BADGE = "Found by AI, checked by code";
export const STOPPED_SENTENCE =
  "A stopped study is not, by itself, a result about whether a treatment works.";
export const PAUSED_SENTENCE =
  "A paused study is not a result; the record gives the reason and says whether it will resume.";

/** Where the tittle of "i" sits relative to the glyph origin (px; y is negative above the
 * baseline), measured by drawing "i" and the dotless "ı" in the element's own font. */
function measureTittle(
  font: string,
  fontPx: number,
): { x: number; y: number; w: number; h: number } | null {
  const F = Math.max(8, Math.ceil(fontPx));
  const S = Math.min(8, Math.max(1, Math.round(128 / F))); // supersampling
  const c = document.createElement("canvas");
  c.width = 3 * F * S;
  c.height = 3 * F * S;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  const draw = (ch: string) => {
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.save();
    ctx.scale(S, S);
    ctx.font = font;
    ctx.textBaseline = "alphabetic";
    ctx.fillStyle = "#000";
    ctx.fillText(ch, F, 2 * F);
    ctx.restore();
    return ctx.getImageData(0, 0, c.width, c.height).data;
  };
  const dotted = draw("i");
  const dotless = draw("\u0131");
  let x0 = Infinity,
    y0 = Infinity,
    x1 = -Infinity,
    y1 = -Infinity;
  for (let y = 0; y < c.height; y++)
    for (let x = 0; x < c.width; x++) {
      const k = (y * c.width + x) * 4 + 3;
      if (dotted[k] - dotless[k] > 96) {
        x0 = Math.min(x0, x);
        x1 = Math.max(x1, x);
        y0 = Math.min(y0, y);
        y1 = Math.max(y1, y);
      }
    }
  if (!Number.isFinite(x0)) return null;
  return {
    x: x0 / S - F,
    y: y0 / S - 2 * F,
    w: (x1 - x0 + 1) / S,
    h: (y1 - y0 + 1) / S,
  };
}

/** "Polaris" with the dot of the i as its own element, placed exactly on the font's own
 * tittle (`data-wordmark-dot`): the header's dot is the accent colour; the intro's title card
 * lands its star on its own copy's dot. Visually the same word; read as "Polaris". */
export function Wordmark({
  className = "text-base font-extrabold tracking-tight",
  dotStyle = { background: "var(--accent)" },
}: {
  className?: string;
  dotStyle?: CSSProperties;
}) {
  const wrap = useRef<HTMLSpanElement>(null);
  const probe = useRef<HTMLSpanElement>(null);
  const dot = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const place = () => {
      const w = wrap.current;
      const p = probe.current;
      const d = dot.current;
      if (!w || !p || !d) return;
      const cs = getComputedStyle(w);
      const t = measureTittle(cs.font, parseFloat(cs.fontSize));
      const wr = w.getBoundingClientRect();
      const pr = p.getBoundingClientRect(); // a 0 x 0 inline-block: its bottom is the baseline
      if (!t) {
        Object.assign(d.style, { left: "50%", top: "0.1em", width: "0.2em", height: "0.2em" });
        d.style.transform = "translateX(-50%)";
        return;
      }
      const size = Math.max(t.w, t.h);
      d.style.left = `${pr.left - wr.left + t.x + (t.w - size) / 2}px`;
      d.style.top = `${pr.bottom - wr.top + t.y + (t.h - size) / 2}px`;
      d.style.width = `${size}px`;
      d.style.height = `${size}px`;
    };
    place();
    const fonts = document.fonts;
    fonts?.ready.then(place).catch(() => {});
    fonts?.addEventListener?.("loadingdone", place);
    return () => fonts?.removeEventListener?.("loadingdone", place);
  }, []);
  return (
    <span className={className}>
      <span className="sr-only">Polaris</span>
      <span aria-hidden="true">
        Polar
        <span ref={wrap} className="relative">
          <span ref={probe} className="inline-block h-0 w-0" />
          {"\u0131"}
          <span ref={dot} data-wordmark-dot="" className="absolute rounded-full" style={dotStyle} />
        </span>
        s
      </span>
    </span>
  );
}

export function Header({
  tag,
  nav,
  onHome,
}: {
  tag?: string;
  nav?: ReactNode;
  onHome?: () => void;
}) {
  return (
    <header className="relative z-40 flex h-14 shrink-0 items-center gap-3 border-b border-hair bg-paper px-4">
      <a
        className="skip"
        href="#main"
        onClick={(e) => {
          // Focus the main region without touching the hash (the hash is the router).
          e.preventDefault();
          const main = document.getElementById("main");
          main?.focus();
          main?.scrollIntoView();
        }}
      >
        Skip to content
      </a>
      <a
        className="flex min-h-11 items-center gap-2 text-ink no-underline"
        href="#/"
        onClick={(e) => {
          if (onHome) {
            e.preventDefault();
            onHome();
          }
        }}
      >
        <Wordmark />
        {tag && <span className="text-xs text-ink-3">{tag}</span>}
      </a>
      <nav aria-label="Site" className="ml-auto flex items-center gap-2">
        {nav}
      </nav>
    </header>
  );
}

/** The researcher page's footer: the date its data were pre-computed. The map has no footer. */
export function Footer({ date }: { date: string }) {
  return (
    <footer
      className="border-t border-hair bg-paper px-4 py-3 text-sm text-ink-2"
      role="contentinfo"
    >
      Data and AI text pre-computed{date ? ` ${date}` : " at build time"}.
    </footer>
  );
}

/** Label under every model-written sentence. Template text says so. */
export function Provenance({
  model,
  date,
  template,
}: {
  model?: string;
  date?: string;
  template?: boolean;
}) {
  if (template)
    return (
      <p className="provenance">
        Fixed sentence filled from the cited facts; not model-written; checked by code.
      </p>
    );
  return (
    <p className="provenance">
      Written by {model || "the build-time model"} at build time
      {date ? ` on ${date}` : ""} from the cited facts; checked by code.
    </p>
  );
}

/** An outbound link, rendered only when the URL passes the host allow-list; else plain text. */
export function Ext({
  href,
  children,
  className,
  extraHosts,
}: {
  href?: string | null;
  children: ReactNode;
  className?: string;
  extraHosts?: ReadonlySet<string>; // the researcher entry's additional ID-built hosts
}) {
  const url = safeUrl(href, extraHosts);
  if (!url) return <span className={className}>{children}</span>;
  return (
    <a className={className} href={url} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

export function Badge({ kind, children }: { kind?: "ok" | "warn" | "block"; children: ReactNode }) {
  return <span className={`badge ${kind ?? ""}`}>{children}</span>;
}

export function Skeleton() {
  return (
    <div className="skeleton" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading the map</span>
      <div className="bar" style={{ width: "40%" }} />
      <div className="bar" style={{ width: "80%" }} />
      <div className="bar" style={{ width: "65%" }} />
      <div className="bar" style={{ width: "90%", height: 120 }} />
    </div>
  );
}

export function LoadError() {
  return (
    <div className="card" role="alert">
      <h2>Couldn't load the atlas data. Reload.</h2>
      <button className="btn primary" type="button" onClick={() => window.location.reload()}>
        Reload
      </button>
    </div>
  );
}

export const asOf = (date?: string | null) => {
  if (!date) return "date not checked";
  const age = (Date.now() - new Date(date).getTime()) / 86400000;
  return age > 30 ? `status as of ${date}` : `retrieved ${date}`;
};

/** A bad row never leaves a white page: the error state renders with the chrome. */
export class ErrorBoundary extends Component<
  { children: ReactNode; tag?: string },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="app-page">
        <Header tag={this.props.tag} onHome={() => window.location.assign("/")} />
        <main id="main" tabIndex={-1}>
          <LoadError />
        </main>
      </div>
    );
  }
}

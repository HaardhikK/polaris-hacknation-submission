// Legend card for the canvas: a swatch and one or two words per row, nothing colour-only.
// The shell wraps it in a "Legend" chip; this is the card alone. Colours from the app tokens.
import { GROUP_COLORS, KIND_COLORS, LINK_COLORS, type CanvasNode } from "./PolarisCanvas";

const LINES: { group: CanvasNode["group"]; word: string }[] = [
  { group: "gain", word: "gain" },
  { group: "loss", word: "loss" },
  { group: "non_channel", word: "non-channel" },
];

const DOTS: { color: string; word: string }[] = [
  { color: KIND_COLORS.organisation, word: "organisation" },
  { color: KIND_COLORS.study, word: "study" },
  { color: KIND_COLORS.asset, word: "asset" },
  { color: KIND_COLORS.paper, word: "paper" },
  { color: KIND_COLORS.conflict, word: "disagreement" },
];

const STROKES: { color: string; word: string; dashed?: boolean; thin?: boolean }[] = [
  { color: LINK_COLORS.blocked, word: "blocked" },
  { color: LINK_COLORS.needs_expert_check, word: "expert check" },
  { color: LINK_COLORS.viable, word: "borrow" },
  { color: LINK_COLORS.already_open, word: "open to you" },
  { color: LINK_COLORS.co_listed_in, word: "same study", dashed: true },
  { color: LINK_COLORS.claim, word: "paper", thin: true },
];

const row: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 7,
  fontSize: 11,
  lineHeight: "14px",
  color: "var(--ink, #16181d)",
  whiteSpace: "nowrap",
};

const cell: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: 18,
  height: 14,
  flex: "0 0 auto",
};

function Disc({ color, size }: { color: string; size: number }) {
  return (
    <span aria-hidden="true" style={cell}>
      <span style={{ width: size, height: size, borderRadius: "50%", background: color }} />
    </span>
  );
}

function Stroke({ color, dashed, thin }: { color: string; dashed?: boolean; thin?: boolean }) {
  return (
    <span aria-hidden="true" style={cell}>
      <span
        style={{
          width: 18,
          borderTop: `${thin ? 1 : 2}px ${dashed ? "dashed" : "solid"} ${color}`,
        }}
      />
    </span>
  );
}

export function Legend({ className }: { className?: string }) {
  return (
    <div
      className={className}
      style={{
        display: "grid",
        gap: 4,
        padding: "8px 10px",
        maxWidth: 200,
        background: "var(--paper, #ffffff)",
        border: "1px solid var(--hair, #e3e6eb)",
        borderRadius: 8,
        fontFamily: "inherit",
      }}
    >
      {LINES.map(({ group, word }) => (
        <div key={group} style={row}>
          <Disc color={GROUP_COLORS[group]} size={12} />
          <span>{word}</span>
        </div>
      ))}
      {DOTS.map(({ color, word }) => (
        <div key={word} style={row}>
          <Disc color={color} size={7} />
          <span>{word}</span>
        </div>
      ))}
      {STROKES.map(({ color, word, dashed, thin }) => (
        <div key={word} style={row}>
          <Stroke color={color} dashed={dashed} thin={thin} />
          <span>{word}</span>
        </div>
      ))}
    </div>
  );
}

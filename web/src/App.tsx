// The map: the whole screen is the graph, with one panel over it on the left. The panel holds
// the search box, then, in its place, the state a search leads to (Which direction?, the gene
// picker, the result stack, Not mapped yet, …) or the facts of a clicked node. Routes live in
// the hash and carry only dataset IDs, never typed text. About is its own page (#/about).
import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  FileSearch,
  FlaskConical,
  HeartPulse,
  Info,
  Map as MapIcon,
} from "lucide-react";
import type { Alias, Graph } from "./types";
import { clustersForMechanism, counts, gatedCardFor, isDirectionStepGene, loadGraph } from "./data";
import { buildIndex, type Resolution } from "./search";
import { buildCanvasModel, neighbourhood, subgraphForLine, subgraphForLines } from "./graphModel";
import { useHash, useIsPhone } from "./hooks";
import { Header, LoadError, Skeleton } from "./shared/Layout";
import {
  DirectionStep,
  FormNotMapped,
  GapState,
  GenePicker,
  MixedVariant,
  Search,
  UnknownVariant,
} from "./components/States";
import { RESULT_TABS, Result, type ResultTab } from "./components/Result";
import { About } from "./components/About";
import { MechanismView } from "./components/MechanismView";
import { ClusterGroups } from "./components/StackedList";
import { NodePanel } from "./components/NodePanel";
import { EdgePanel } from "./components/EdgePanel";
import { ConditionPicker, EvidenceIndex } from "./components/IndexPanels";
import { Legend } from "./graph/Legend";
import { IntroOverlay, introMode, type IntroMode } from "./intro/IntroOverlay";

const PolarisCanvas = lazy(() =>
  import("./graph/PolarisCanvas").then((m) => ({ default: m.PolarisCanvas })),
);

type View =
  | { kind: "home" }
  | { kind: "about" }
  | { kind: "direction"; gene: string }
  | { kind: "not_mapped"; gene: string; direction: string }
  | { kind: "picker"; alias: Alias }
  | { kind: "line"; key: string; tab?: ResultTab }
  | { kind: "gated"; gene: string; tab?: ResultTab } // a channel gene whose direction is not known
  | { kind: "gap"; query: string }
  | { kind: "unknown_variant"; gene: string; variant: string }
  | { kind: "mixed"; gene: string; variant: string; pmid?: string | null }
  | { kind: "mechanism"; mechanism: string; direction?: string | null }
  | { kind: "cluster"; key: string } // one mechanism × direction group
  | { kind: "pick" } // the rail's "My condition" before any search: the seven conditions
  | { kind: "evidence" } // the rail's "Evidence" before any selection: every link, indexed
  | { kind: "node"; id: string } // any node of the map: its facts and its edges
  | { kind: "edge"; source: string; target: string; predicate: string }; // one link, as evidence

/** The variant alias a line was reached through: its own paper is cited on the variant line. */
export interface ViaVariant {
  variant: string;
  pmid: string;
}

const ID = /^[A-Za-z0-9_:.-]{1,60}$/;
const DIRECTIONS = ["gain", "loss", "unknown"];
// Asset types that never reach a view without a known direction (safety set).
const DIRECTION_GATED_TYPES = new Set(["trial", "model", "drug"]);
const PANEL = 460; // px, the panel's width on desktop
const EXAMPLES = ["SCN2A", "SCN2A R853Q", "Dravet syndrome", "SYNGAP1", "seizure", "ORPHA:1934"];
// The canvas's link vocabulary → the data file's edge kinds it may stand for.
const LINK_ALIAS: Record<string, string> = {
  holds_asset: "owns",
  organisation: "owns",
  co_listed_in: "co_listed",
  conflict: "disputes",
  claim_review: "claim",
  claim_clinical_inference: "claim",
  cited_source: "claim",
  needs_expert_check: "viable",
};
const PANEL_WIDE = 760;

const tabOf = (s?: string): ResultTab | undefined =>
  RESULT_TABS.includes(s as ResultTab) ? (s as ResultTab) : undefined;

/** Views reachable by hash. Everything in the hash is a dataset ID; typed text never is. */
function parseHash(hash: string, g: Graph, nodeIds: Set<string>): View {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const ok = (s?: string) => !!s && ID.test(s);
  switch (parts[0]) {
    case "about":
      return { kind: "about" };
    case "pick":
      return { kind: "pick" };
    case "evidence":
      return { kind: "evidence" };
    case "line":
      return ok(parts[1]) && g.lines.some((l) => l.key === parts[1])
        ? { kind: "line", key: parts[1], tab: tabOf(parts[2]) }
        : { kind: "home" };
    case "gene":
      // "#/gene/SCN2A" asks which direction; "#/gene/SCN2A/unknown" is the gated view.
      if (!ok(parts[1]) || !isDirectionStepGene(g, parts[1])) return { kind: "home" };
      if (parts[2] === "unknown") return { kind: "gated", gene: parts[1], tab: tabOf(parts[3]) };
      return parts[2] ? { kind: "home" } : { kind: "direction", gene: parts[1] };
    case "not-mapped":
      return ok(parts[1]) && isDirectionStepGene(g, parts[1]) && DIRECTIONS.includes(parts[2])
        ? { kind: "not_mapped", gene: parts[1], direction: parts[2] }
        : { kind: "home" };
    case "mechanism": {
      const m = ok(parts[1]) && g.lines.some((l) => l.mechanism === parts[1]) ? parts[1] : null;
      if (!m) return { kind: "home" };
      const d = DIRECTIONS.includes(parts[2]) ? parts[2] : null;
      return { kind: "mechanism", mechanism: m, direction: d };
    }
    case "cluster":
      return ok(parts[1]) && g.mechanism_view.some((c) => c.key === parts[1])
        ? { kind: "cluster", key: parts[1] }
        : { kind: "home" };
    case "node":
      return ok(parts[1]) && nodeIds.has(parts[1])
        ? { kind: "node", id: parts[1] }
        : { kind: "home" };
    case "edge":
      return ok(parts[1]) &&
        ok(parts[2]) &&
        ok(parts[3]) &&
        g.edges.some(
          (e) => e.subject === parts[1] && e.object === parts[2] && e.predicate === parts[3],
        )
        ? { kind: "edge", source: parts[1], target: parts[2], predicate: parts[3] }
        : { kind: "home" };
    default:
      return { kind: "home" };
  }
}

function hashFor(v: View): string {
  switch (v.kind) {
    case "home":
      return "#/";
    case "about":
      return "#/about";
    case "pick":
      return "#/pick";
    case "evidence":
      return "#/evidence";
    case "line":
      return `#/line/${v.key}${v.tab ? `/${v.tab}` : ""}`;
    case "gated":
      return `#/gene/${v.gene}/unknown${v.tab ? `/${v.tab}` : ""}`;
    case "direction":
      return `#/gene/${v.gene}`;
    case "not_mapped":
      return `#/not-mapped/${v.gene}/${v.direction}`;
    case "mechanism":
      return `#/mechanism/${v.mechanism}${v.direction ? `/${v.direction}` : ""}`;
    case "cluster":
      return `#/cluster/${v.key}`;
    case "node":
      return `#/node/${v.id}`;
    case "edge":
      return `#/edge/${v.source}/${v.target}/${v.predicate}`;
    default:
      return "#/_"; // views built from typed text (gap, unknown variant, picker) stay in memory
  }
}

/** The shell: the atlas, with the landing intro over it on a fresh load of the home route. */
export default function App() {
  const [intro, setIntro] = useState<IntroMode>(introMode);
  const endIntro = useCallback(() => setIntro("none"), []);
  return (
    <>
      <Atlas />
      {intro !== "none" && <IntroOverlay mode={intro} onDone={endIntro} />}
    </>
  );
}

function Atlas() {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [error, setError] = useState(false);
  const [memView, setMemView] = useState<View | null>(null);
  const [via, setVia] = useState<{ line: string; via: ViaVariant } | null>(null);
  const [lastQuery, setLastQuery] = useState(""); // memory only: lets a typo be corrected
  // The view a node was opened from: its subgraph stays on screen and "Back" returns to it.
  const [origin, setOrigin] = useState<View | null>(null);
  const [legendOpen, setLegendOpen] = useState(false);
  // Focus follows the Legend: into the open card's close control, back to the button on close.
  const legendButton = useRef<HTMLButtonElement>(null);
  const legendClose = useRef<HTMLButtonElement>(null);
  const legendWasOpen = useRef(false);
  useEffect(() => {
    if (legendOpen) legendClose.current?.focus();
    else if (legendWasOpen.current) legendButton.current?.focus();
    legendWasOpen.current = legendOpen;
    if (!legendOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setLegendOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [legendOpen]);
  // The rail's "My condition" and "Evidence" remember the last page of each job (memory only).
  const [rememberedCondition, setLastCondition] = useState<View | null>(null);
  const [rememberedDetail, setLastDetail] = useState<View | null>(null);
  const hash = useHash();
  const phone = useIsPhone();

  useEffect(() => {
    loadGraph()
      .then(setGraph)
      .catch(() => setError(true));
  }, []);

  const index = useMemo(() => (graph ? buildIndex(graph) : null), [graph]);
  const model = useMemo(() => (graph ? buildCanvasModel(graph) : null), [graph]);
  const nodeIds = useMemo(() => new Set(model?.nodes.map((n) => n.id) ?? []), [model]);

  const view: View = useMemo(() => {
    if (!graph) return { kind: "home" };
    if (memView && hash === "#/_") return memView;
    return parseHash(hash, graph, nodeIds);
  }, [graph, hash, memView, nodeIds]);

  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    panelRef.current?.scrollTo({ top: 0 });
  }, [view]);

  const nav = (v: View) => {
    const idHash = hashFor(v);
    if (v.kind === "line" || v.kind === "gated") setLastCondition(v);
    if (v.kind === "node" || v.kind === "edge") setLastDetail(v);
    // The searched variant is cited on its own line and across node round trips only.
    if (v.kind !== "node" && v.kind !== "edge" && !(v.kind === "line" && via?.line === v.key))
      setVia(null);
    setMemView(idHash === "#/_" ? v : null);
    if (v.kind !== "node" && v.kind !== "edge") setOrigin(null);
    if (window.location.hash !== idHash) window.location.hash = idHash;
  };
  const openLine = (key: string) => {
    setVia(null); // a line opened by anything but a variant search cites its own paper
    nav({ kind: "line", key });
  };
  // Stable across renders so the canvas never sees a new callback (and never resets).
  const viewRef = useRef(view);
  const nodeIdsRef = useRef(nodeIds);
  const graphRef = useRef(graph);
  useEffect(() => {
    viewRef.current = view;
    nodeIdsRef.current = nodeIds;
    graphRef.current = graph;
  }, [view, nodeIds, graph]);
  const detail = (v: View) => v.kind === "node" || v.kind === "edge";
  const openNode = useCallback((id: string | null) => {
    if (!id || !nodeIdsRef.current.has(id)) return; // a background click only clears the highlight
    if (!detail(viewRef.current)) setOrigin(viewRef.current);
    setLastDetail({ kind: "node", id });
    window.location.hash = `#/node/${id}`;
  }, []);
  /** A link of the map (from the canvas or a panel row) opens as evidence. */
  const openEdge = useCallback((link: { source: string; target: string; kind?: string } | null) => {
    if (!link) return;
    const kind = link.kind ?? "";
    const g = graphRef.current;
    const hit = g?.edges.find(
      (e) =>
        e.subject === link.source &&
        e.object === link.target &&
        (e.predicate === kind || LINK_ALIAS[e.predicate] === kind),
    );
    if (!hit) return;
    if (!detail(viewRef.current)) setOrigin(viewRef.current);
    setLastDetail({
      kind: "edge",
      source: hit.subject,
      target: hit.object,
      predicate: hit.predicate,
    });
    window.location.hash = `#/edge/${hit.subject}/${hit.object}/${hit.predicate}`;
  }, []);
  const back = () => {
    if (detail(view) && origin) {
      const o = origin;
      setOrigin(null);
      nav(o);
    } else nav({ kind: "home" });
    // The returned-to page renders after the hash change; focus its heading once it exists.
    window.setTimeout(() => {
      const h = panelRef.current?.querySelector("h1") as HTMLElement | null;
      h?.setAttribute("tabindex", "-1");
      h?.focus();
    }, 250);
  };

  const onResolve = (r: Resolution, raw: string) => {
    setLastQuery(raw);
    switch (r.kind) {
      case "line": {
        const a = r.alias;
        openLine(r.line);
        if (a?.kind === "variant" && a.pmid)
          setVia({ line: r.line, via: { variant: a.term.replace(/^\S+\s+/, ""), pmid: a.pmid } });
        return;
      }
      case "mixed":
        return nav({ kind: "mixed", gene: r.gene, variant: r.variant, pmid: r.pmid });
      case "direction":
        return nav({ kind: "direction", gene: r.gene });
      case "picker":
        return nav({ kind: "picker", alias: r.alias });
      case "mechanism":
        return nav({ kind: "mechanism", mechanism: r.mechanism, direction: r.direction });
      case "unknown_variant":
        return nav({ kind: "unknown_variant", gene: r.gene, variant: r.variant });
      default:
        return nav({ kind: "gap", query: raw });
    }
  };

  /** After "Which direction?": a shipped line, the gated gene card, or "not mapped yet". */
  const pickDirection = (gene: string, d: "gain" | "loss" | "unknown") => {
    if (!graph) return;
    if (d === "unknown")
      return gatedCardFor(graph, gene)
        ? nav({ kind: "gated", gene })
        : nav({ kind: "not_mapped", gene, direction: "unknown" });
    const line = graph.lines.find((l) => l.gene === gene && l.direction === d);
    return line ? openLine(line.key) : nav({ kind: "not_mapped", gene, direction: d });
  };

  /** A gene chosen in a picker: the direction step for channel genes, else its line. */
  const pickGene = (gene: string) => {
    if (!graph) return;
    if (isDirectionStepGene(graph, gene)) return nav({ kind: "direction", gene });
    const line = graph.lines.find((l) => l.gene === gene);
    return line ? openLine(line.key) : nav({ kind: "gap", query: "" });
  };

  // --- What the graph shows for the view -------------------------------------------------
  const focus = useMemo((): { visible: Set<string> | null; focusId: string | null } => {
    if (!graph || !model) return { visible: null, focusId: null };
    const linesOfGene = (gene: string) =>
      graph.lines.filter((l) => l.gene === gene).map((l) => l.key);
    const orgsOfGene = (gene: string, out: Set<string>) => {
      const keys = linesOfGene(gene);
      for (const o of graph.organisations)
        if (o.lines.some((k) => keys.includes(k))) out.add(`org:${o.key}`);
      return out;
    };
    const hubsAndOrgs = (gene: string) =>
      orgsOfGene(gene, new Set(linesOfGene(gene).map((k) => `line:${k}`)));
    // Direction not known: organisations and the gated card's resources only; no direction
    // hubs, no trial or model (safety set).
    const gatedSet = (gene: string) => {
      const out = orgsOfGene(gene, new Set<string>());
      for (const t of gatedCardFor(graph, gene)?.transfers ?? [])
        if (!DIRECTION_GATED_TYPES.has(t.asset_type)) out.add(`asset:${t.asset_id}`);
      for (const s of graph.studies)
        if (s.kind !== "trial" && s.genes_named?.includes(gene)) out.add(`study:${s.nct}`);
      return out;
    };
    const v = detail(view) && origin ? origin : view;
    let visible: Set<string> | null;
    switch (v.kind) {
      case "line":
        visible = subgraphForLine(model, v.key);
        break;
      case "gated":
      case "mixed":
        visible = gatedSet(v.gene);
        break;
      case "direction":
      case "not_mapped":
      case "unknown_variant":
        visible = hubsAndOrgs(v.gene); // both forms of the gene stand out; none is chosen yet
        break;
      case "picker":
        visible = subgraphForLines(model, (v.alias.genes ?? []).flatMap(linesOfGene));
        break;
      case "cluster": {
        const c = graph.mechanism_view.find((x) => x.key === v.key);
        visible = subgraphForLines(model, c?.lines ?? []);
        break;
      }
      case "mechanism":
        visible = subgraphForLines(
          model,
          clustersForMechanism(graph, v.mechanism, v.direction).flatMap((c) => c.lines),
        );
        break;
      case "node":
        visible = neighbourhood(model, v.id);
        break;
      case "edge":
        visible = new Set([...neighbourhood(model, v.source), ...neighbourhood(model, v.target)]);
        break;
      default:
        visible = null;
    }
    if (view.kind === "node") {
      // A node reached by following links stays drawn with its own neighbourhood.
      if (visible && !visible.has(view.id))
        visible = new Set([...visible, ...neighbourhood(model, view.id)]);
      return { visible, focusId: view.id };
    }
    if (view.kind === "edge") {
      if (visible) visible = new Set([...visible, view.source, view.target]);
      return { visible, focusId: view.source };
    }
    return { visible, focusId: v.kind === "line" ? `line:${v.key}` : null };
  }, [graph, model, view, origin]);

  if (error)
    return (
      <div className="app-page">
        <Header onHome={() => nav({ kind: "home" })} />
        <main id="main" tabIndex={-1}>
          <LoadError />
        </main>
      </div>
    );
  if (!graph || !index || !model)
    return (
      <div className="app-page">
        <Header />
        <main id="main" tabIndex={-1}>
          <Skeleton />
        </main>
      </div>
    );

  const c = counts(graph);
  const wide = view.kind === "mechanism" || view.kind === "cluster";
  const panelKey = detail(view)
    ? hashFor(view)
    : hashFor(view) + (view.kind === "gap" ? view.query : "");
  const lastCondition =
    rememberedCondition ?? (view.kind === "line" || view.kind === "gated" ? view : null);
  const lastDetail = rememberedDetail ?? (detail(view) ? view : null);

  const panelBody = (() => {
    switch (view.kind) {
      case "home":
        return null;
      case "direction":
        return (
          <DirectionStep
            graph={graph}
            gene={view.gene}
            onPick={(d) => pickDirection(view.gene, d)}
          />
        );
      case "not_mapped":
        return (
          <FormNotMapped
            graph={graph}
            gene={view.gene}
            direction={view.direction}
            onBack={() => nav({ kind: "home" })}
          />
        );
      case "picker":
        return (
          <GenePicker
            alias={view.alias}
            onGene={pickGene}
            onNotListed={() => nav({ kind: "gap", query: "" })}
          />
        );
      case "gap":
        return <GapState graph={graph} query={view.query} onOpenLine={openLine} />;
      case "unknown_variant":
        return (
          <UnknownVariant
            graph={graph}
            gene={view.gene}
            variant={view.variant}
            onContinueGated={() => pickDirection(view.gene, "unknown")}
            onContinueLine={openLine}
          />
        );
      case "mixed":
        return (
          <MixedVariant
            graph={graph}
            gene={view.gene}
            variant={view.variant}
            pmid={view.pmid}
            onContinueGated={() => pickDirection(view.gene, "unknown")}
          />
        );
      case "mechanism":
        return (
          <MechanismView
            graph={graph}
            clusters={clustersForMechanism(graph, view.mechanism, view.direction)}
            title={`Who works on this mechanism: ${view.mechanism.replace(/_/g, " ")}${
              view.direction === "gain"
                ? ", works too strongly"
                : view.direction === "loss"
                  ? ", works too weakly"
                  : ""
            }`}
            onOpenLine={openLine}
          />
        );
      case "cluster":
        return (
          <MechanismView
            graph={graph}
            clusters={graph.mechanism_view.filter((c) => c.key === view.key)}
            title={
              graph.mechanism_view.find((c) => c.key === view.key)?.label ??
              "Who works on this mechanism"
            }
            onOpenLine={openLine}
          />
        );
      case "line":
        return (
          <Result
            key={view.key}
            graph={graph}
            line={graph.lines.find((l) => l.key === view.key)!}
            via={via?.line === view.key ? via.via : undefined}
            onOpenCluster={(key) => nav({ kind: "cluster", key })}
            onSeeLinks={() => openNode(`line:${view.key}`)}
            tab={view.tab ?? "condition"}
            onTab={(tab) => nav({ kind: "line", key: view.key, tab })}
            phoneMap={
              phone ? (
                <ClusterGroups
                  graph={graph}
                  me={graph.lines.find((l) => l.key === view.key)}
                  onOpenLine={openLine}
                />
              ) : null
            }
          />
        );
      case "gated":
        return gatedCardFor(graph, view.gene) ? (
          <Result
            key={`gated-${view.gene}`}
            graph={graph}
            gene={view.gene}
            tab={view.tab ?? "condition"}
            onTab={(tab) => nav({ kind: "gated", gene: view.gene, tab })}
            phoneMap={
              phone ? (
                <ClusterGroups graph={graph} meGene={view.gene} onOpenLine={openLine} />
              ) : null
            }
          />
        ) : (
          <FormNotMapped
            graph={graph}
            gene={view.gene}
            direction="unknown"
            onBack={() => nav({ kind: "home" })}
          />
        );
      case "pick":
        return <ConditionPicker graph={graph} onPick={openLine} />;
      case "evidence":
        return <EvidenceIndex graph={graph} model={model} onOpenEdge={openEdge} />;
      case "node":
        return (
          <NodePanel
            graph={graph}
            model={model}
            id={view.id}
            onOpenNode={openNode}
            onOpenLine={openLine}
            onOpenEdge={openEdge}
          />
        );
      case "edge":
        return (
          <EdgePanel
            graph={graph}
            model={model}
            source={view.source}
            target={view.target}
            kind={view.predicate}
            onOpenNode={openNode}
          />
        );
      default:
        return null;
    }
  })();

  const hasPanel = view.kind !== "home" && view.kind !== "about";
  const panelWidth = wide ? PANEL_WIDE : PANEL;
  const backLabel =
    origin && (origin.kind === "line" || origin.kind === "gated")
      ? "Back to the condition"
      : "Back";
  const railItems: {
    key: string;
    label: string;
    icon: ReactNode;
    active: boolean;
    go: () => void;
    href?: string;
  }[] = [
    {
      key: "map",
      label: "Map",
      icon: <MapIcon size={20} aria-hidden="true" />,
      active: !detail(view) && !["line", "gated", "about", "pick", "evidence"].includes(view.kind),
      go: () => nav({ kind: "home" }),
    },
    {
      key: "condition",
      label: "My condition",
      icon: <HeartPulse size={20} aria-hidden="true" />,
      active: view.kind === "line" || view.kind === "gated" || view.kind === "pick",
      go: () => nav(lastCondition ?? { kind: "pick" }),
    },
    {
      key: "evidence",
      label: "Evidence",
      icon: <FileSearch size={20} aria-hidden="true" />,
      active: detail(view) || view.kind === "evidence",
      go: () => nav(lastDetail ?? { kind: "evidence" }),
    },
    {
      key: "researchers",
      label: "Researcher view",
      icon: <FlaskConical size={20} aria-hidden="true" />,
      active: false,
      go: () => window.location.assign("/researchers/"),
      href: "/researchers/",
    },
  ];
  const aboutItem = {
    key: "about",
    label: "About",
    icon: <Info size={20} aria-hidden="true" />,
    active: view.kind === "about",
    go: () => nav({ kind: "about" }),
  };
  const railButton = (it: (typeof railItems)[number]) => {
    const cls = `group relative flex h-12 w-12 items-center justify-center rounded-xl border-0 ${
      it.active ? "bg-accent text-paper" : "bg-transparent text-ink-2 hover:bg-paper-2"
    } cursor-pointer`;
    const tip = (
      <span
        className={`pointer-events-none absolute z-40 whitespace-nowrap rounded-md bg-ink px-2 py-1 text-xs text-paper opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 ${
          phone ? "bottom-full mb-1" : "left-full ml-2"
        }`}
      >
        {it.label}
      </span>
    );
    return it.href ? (
      <a key={it.key} className={cls} href={it.href} rel="nofollow" aria-label={it.label}>
        {it.icon}
        {tip}
      </a>
    ) : (
      <button
        key={it.key}
        type="button"
        className={cls}
        aria-label={it.label}
        aria-current={it.active ? "page" : undefined}
        onClick={it.go}
      >
        {it.icon}
        {tip}
      </button>
    );
  };
  const rail = (
    <nav
      aria-label="Pages"
      className={
        phone
          ? "flex shrink-0 justify-around border-t border-hair bg-paper px-2 py-1"
          : "flex w-14 shrink-0 flex-col items-center gap-1 border-r border-hair bg-paper py-2"
      }
    >
      {railItems.map(railButton)}
      {!phone && <div className="flex-1" />}
      {railButton(aboutItem)}
    </nav>
  );
  const searchBar = (
    <div className="pointer-events-auto w-full max-w-[560px]">
      <Search index={index} onResolve={onResolve} initial={lastQuery} examples={EXAMPLES} />
    </div>
  );

  return (
    <div className="flex h-full flex-col">
      <Header onHome={() => nav({ kind: "home" })} />
      <div className={`flex min-h-0 flex-1 ${phone ? "flex-col" : ""}`}>
        {!phone && rail}
        <main id="main" tabIndex={-1} className="relative min-h-0 flex-1 overflow-hidden">
          {view.kind === "about" ? (
            <div className="h-full overflow-y-auto px-4 py-4">
              <div className="mx-auto max-w-[900px]">
                <About graph={graph} />
              </div>
            </div>
          ) : phone ? (
            // Phones: the slim search bar pinned on top, the map below it as a display-only
            // picture driven by searches and the bottom bar, then the panel as a plain page.
            <div ref={panelRef} className="h-full overflow-y-auto">
              <div className="sticky top-0 z-30 border-b border-hair bg-paper px-3 py-2">
                {searchBar}
              </div>
              <div
                className="relative h-[40vh] min-h-[240px] overflow-hidden border-b border-hair"
                aria-hidden="true"
              >
                <Suspense fallback={null}>
                  <PolarisCanvas
                    nodes={model.nodes}
                    links={model.links}
                    focusId={focus.focusId}
                    visibleIds={focus.visible}
                    interactive={false}
                    edgeLabels={false}
                    className="h-full w-full"
                  />
                </Suspense>
              </div>
              {hasPanel ? (
                <div className="m-3 rounded-lg border border-hair bg-paper p-4">
                  {detail(view) && (
                    <button type="button" className="btn quiet mb-2 -ml-2 !px-2" onClick={back}>
                      <ArrowLeft size={16} aria-hidden="true" /> {backLabel}
                    </button>
                  )}
                  {panelBody}
                </div>
              ) : (
                <section className="p-3" aria-label="The map as a list">
                  <h2>The groups, as a list</h2>
                  <ClusterGroups graph={graph} onOpenLine={openLine} />
                </section>
              )}
            </div>
          ) : (
            <>
              <div className="absolute inset-0 isolate overflow-hidden" aria-hidden="true">
                <Suspense fallback={null}>
                  <PolarisCanvas
                    nodes={model.nodes}
                    links={model.links}
                    focusId={focus.focusId}
                    visibleIds={focus.visible}
                    onSelect={openNode}
                    onSelectEdge={openEdge}
                    padding={{ top: 96, left: hasPanel ? panelWidth + 32 : 0 }}
                    className="h-full w-full"
                  />
                </Suspense>
              </div>
              <div
                className="pointer-events-none absolute top-3 right-0 z-30 flex justify-center px-3"
                style={{ left: hasPanel ? panelWidth + 24 : 0 }}
              >
                {searchBar}
              </div>
              <div className="absolute right-4 bottom-4 z-10">
                {legendOpen ? (
                  <div
                    className="w-[220px] rounded-md border border-hair bg-paper p-[10px] text-[11px] leading-tight shadow-[var(--shadow)] [&>div]:!max-w-none [&>div]:!border-0 [&>div]:!bg-transparent [&>div]:!p-0"
                    onMouseLeave={() => setLegendOpen(false)}
                  >
                    <button
                      ref={legendClose}
                      type="button"
                      className="mb-1 flex min-h-11 w-full cursor-pointer items-center justify-between border-0 bg-transparent p-0 text-[14px] text-ink"
                      aria-expanded={true}
                      onClick={() => setLegendOpen(false)}
                    >
                      <span>Legend</span>
                      <span aria-hidden="true">×</span>
                    </button>
                    <Legend />
                    <p className="mt-2 mb-1 font-semibold text-ink-2">How to read</p>
                    <ul className="m-0 grid list-none gap-1 p-0">
                      {[
                        ["\u25cf", "Circles are communities, grouped by how their gene behaves."],
                        [
                          "\u2022",
                          "Dots around a circle are its organisation, studies, assets and papers.",
                        ],
                        ["\u2015", "Lines are rule decisions with a source."],
                        [
                          "#",
                          `${c.lines} conditions, ${c.genes} genes, ${c.studies} studies, ${c.papers} papers, ${c.edges} links.`,
                        ],
                      ].map(([glyph, text]) => (
                        <li key={text} className="flex items-start gap-[7px]">
                          <span
                            className="w-[14px] shrink-0 text-center text-ink-3"
                            aria-hidden="true"
                          >
                            {glyph}
                          </span>
                          <span>{text}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <button
                    ref={legendButton}
                    type="button"
                    className="btn-flat shadow-[var(--shadow)]"
                    aria-expanded={false}
                    onClick={() => setLegendOpen(true)}
                  >
                    Legend
                  </button>
                )}
              </div>
              {hasPanel && (
                <motion.div
                  key={panelKey}
                  ref={panelRef}
                  initial={{ opacity: 0, x: -24 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.2, ease: "easeOut" }}
                  className="absolute top-3 bottom-3 left-3 z-20 overflow-y-auto rounded-lg border border-hair bg-paper shadow-[var(--shadow)]"
                  style={{ width: panelWidth }}
                >
                  <div className="p-4">
                    {detail(view) && (
                      <button type="button" className="btn quiet mb-2 -ml-2 !px-2" onClick={back}>
                        <ArrowLeft size={16} aria-hidden="true" /> {backLabel}
                      </button>
                    )}
                    {panelBody}
                  </div>
                </motion.div>
              )}
            </>
          )}
        </main>
        {phone && rail}
      </div>
    </div>
  );
}

// The Polaris graph canvas: raw three.js, one shader-drawn point cloud for the nodes, one
// line-segment buffer for the thin links and one screen-space ribbon buffer for the transfer
// edges between hubs, HTML overlays for labels and the tooltip, OrbitControls with a slow
// constant rotation and a bezier camera fly-to. No per-node meshes. The layout is computed
// once per dataset and never moves: a search (`visibleIds`) ghosts what is outside the set,
// dims what is unrelated and flies to the focused node.
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { createPointMaterial } from "./pointShader";
import { boundingSphere, buildNeighbours, hashString, layoutNodes, seededRandom } from "./layout";

export type GraphNodeKind = "line" | "organisation" | "study" | "asset" | "paper" | "conflict";

export interface CanvasNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  group: "gain" | "loss" | "non_channel" | "other";
  /** The line a satellite belongs to. */
  lineKey?: string;
  direction?: string;
}

export interface CanvasLink {
  source: string;
  target: string;
  /** 'blocked' | 'viable' | 'already_open' | 'co_listed' | 'claim' | 'owns' | 'disputes' | ... */
  kind: string;
}

export interface PolarisCanvasHandle {
  focusNode(id: string): void;
  clearFocus(): void;
  fitAll(): void;
}

export interface PolarisCanvasProps {
  nodes: CanvasNode[];
  links: CanvasLink[];
  /** The node the camera should fly to and highlight. */
  focusId: string | null;
  /** Search mode: nodes outside this set fade to a faint ghost; null = all. Positions never change. */
  visibleIds: Set<string> | null;
  onSelect?(id: string | null): void;
  onHover?(id: string | null): void;
  /** An edge was clicked (nearest edge when no node is under the pointer); null = cleared. */
  onSelectEdge?(link: CanvasLink | null): void;
  /** Stage area covered by the shell's panels, in CSS pixels: fits centre in the free part. */
  padding?: { left?: number; right?: number; top?: number; bottom?: number };
  /** Words on the focused hub's transfer edges (default true). */
  edgeLabels?: boolean;
  /**
   * Pointer input (default true). When false the canvas is display-only: no picking, no
   * hover ring or tooltip, no orbit input (the slow rotation stays), `pointer-events: none`
   * so page scroll, taps and pinches pass through, a 1.5 DPR cap and only the hub labels.
   * `focusId` and `visibleIds` still fly the camera and ghost the rest.
   */
  interactive?: boolean;
  className?: string;
}

/* ------------------------------------------------------------------ palette (light only) */

export const KIND_COLORS: Record<GraphNodeKind, string> = {
  line: "#6f4bd8",
  organisation: "#415f80",
  study: "#237a3f",
  asset: "#a27620",
  paper: "#6f737c",
  conflict: "#a8231c",
};

export const GROUP_COLORS: Record<CanvasNode["group"], string> = {
  gain: "#d9641b",
  loss: "#b8437a", // deep rose: distinct from gain orange under deuteranopia (dE 62)
  non_channel: "#6f4bd8",
  other: "#6b6b6b",
};

export const GROUP_LABELS: Record<CanvasNode["group"], string> = {
  gain: "gain of function",
  loss: "loss of function",
  non_channel: "non-channel gene",
  other: "other",
};

export const KIND_LABELS: Record<GraphNodeKind, string> = {
  line: "community (disease form)",
  organisation: "patient organisation",
  study: "study record",
  asset: "research asset",
  paper: "paper",
  conflict: "sources disagree",
};

export const LINK_COLORS: Record<string, string> = {
  blocked: "#b3261e",
  needs_expert_check: "#8a5a00",
  viable: "#0b6e4f",
  already_open: "#5b6f8a",
  not_shared: "#a6a6a6",
  co_listed: "#666666",
  co_listed_in: "#666666",
  claim: "#808080",
  claim_review: "#808080",
  claim_clinical_inference: "#808080",
  cited_source: "#808080",
  holds_asset: "#a27620",
  owns: "#a27620",
  organisation: "#415f80",
  conflict: "#b3261e",
  disputes: "#b3261e",
};

/** The word an edge carries on screen. */
export const LINK_WORDS: Record<string, string> = {
  blocked: "blocked",
  needs_expert_check: "expert check",
  viable: "borrow",
  already_open: "open to you",
  not_shared: "not shared",
  co_listed: "same study",
  co_listed_in: "same study",
  claim: "paper",
  claim_review: "review",
  claim_clinical_inference: "clinical inference",
  cited_source: "source",
  holds_asset: "holds",
  owns: "holds",
  organisation: "organisation",
  conflict: "disagreement",
  disputes: "disagreement",
};

/** Resting alpha per link kind; unknown kinds get a quiet grey line. */
const LINK_ALPHA: Record<string, number> = {
  blocked: 0.9,
  needs_expert_check: 0.85,
  viable: 0.8,
  already_open: 0.8,
  not_shared: 0.36,
  co_listed: 0.65,
  co_listed_in: 0.65,
  claim: 0.48,
  claim_review: 0.48,
  claim_clinical_inference: 0.48,
  cited_source: 0.48,
  holds_asset: 0.6,
  owns: 0.6,
  organisation: 0.65,
  conflict: 0.7,
  disputes: 0.7,
};
const DASHED_KINDS = new Set(["co_listed", "co_listed_in"]);
/** Transfer decisions between two communities are drawn as wider ribbons and get words. */
const RIBBON_KINDS = new Set(["blocked", "needs_expert_check", "viable", "already_open"]);
/** When two lines are joined by several edges, the strongest decision is the one drawn. */
const LINK_PRIORITY: Record<string, number> = {
  blocked: 6,
  needs_expert_check: 5,
  viable: 4,
  already_open: 3,
  conflict: 2,
  disputes: 2,
  co_listed: 1,
  co_listed_in: 1,
  not_shared: -1,
};

/** World diameter per kind; the shader turns it into pixels with perspective and clamps. */
const KIND_SIZE: Record<GraphNodeKind, number> = {
  line: 64,
  organisation: 20,
  study: 19,
  asset: 18,
  paper: 13,
  conflict: 17,
};

/** Emphasis levels: the interacted node, its neighbours, and everything else. */
const NEAR = 0.55;
const FADE = 0.08;
const EDGE_NEAR = 0.6;
const EDGE_FADE = 0.04;
/** Eased transitions settle in about 250 ms. */
const EASE_RATE = 12;
/** Alpha of a node outside `visibleIds`: still there, still readable as shape. */
const GHOST = 0.1;
const FLY_MS = 1250;
const RING_MS = 400;
const RIBBON_PX = 3;
/** Hover/click reach of an edge, in CSS pixels. */
const EDGE_REACH = 8;
const DASH_PIECES = 5;
const STAGE_BG = "#f4f6f8";
/** White halo that keeps overlay text legible over discs and lines. */
const HALO =
  "0 0 2px #f4f6f8, 0 0 2px #f4f6f8, 0 0 3px #f4f6f8, 1px 1px 0 #f4f6f8, -1px -1px 0 #f4f6f8, 1px -1px 0 #f4f6f8, -1px 1px 0 #f4f6f8";

/* ------------------------------------------------------------------ helpers */

/** Raw sRGB components: the ShaderMaterials write them straight to the sRGB framebuffer. */
function rgb(hex: string): [number, number, number] {
  return [
    parseInt(hex.slice(1, 3), 16) / 255,
    parseInt(hex.slice(3, 5), 16) / 255,
    parseInt(hex.slice(5, 7), 16) / 255,
  ];
}

const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

function nodeColor(n: CanvasNode): string {
  return n.kind === "line" ? GROUP_COLORS[n.group] : KIND_COLORS[n.kind];
}

/** Distance from point p to segment ab, in the same units. */
function segmentDistance(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): number {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 < 1e-6 ? 0 : THREE.MathUtils.clamp(((px - ax) * dx + (py - ay) * dy) / len2, 0, 1);
  const qx = ax + dx * t - px;
  const qy = ay + dy * t - py;
  return Math.sqrt(qx * qx + qy * qy);
}

interface SceneNode {
  id: string;
  index: number;
  data: CanvasNode;
  /** Layout position (never changes). */
  base: THREE.Vector3;
  /** Drawn position (base + drift). */
  pos: THREE.Vector3;
  alphaTo: number;
  alpha: number;
  /** Inside `visibleIds` (or no search active). */
  visible: boolean;
  phase: number;
  drift: THREE.Vector3;
  /** Arc sweep 0..1 of the hover/focus ring. */
  ring: number;
  /** Size boost 0..1 of the interacted node (eased). */
  boost: number;
  boostTo: number;
  /** Heartbeat strength 0..1 (eased): off for everything while something is emphasised. */
  pulse: number;
  pulseTo: number;
}

interface SceneLink {
  a: SceneNode;
  b: SceneNode;
  kind: string;
  color: [number, number, number];
  /** Segments in the thin-line buffer (0 for ribbons). */
  pieces: number;
  seg: number;
  /** Index in the ribbon buffer, or -1. */
  ribbon: number;
  /** Current drawn alpha (for picking). */
  alpha: number;
  /** Original orientation and kind, handed back on click. */
  link: CanvasLink;
  /** The word overlay for a ribbon, created on demand. */
  labelEl: HTMLDivElement | null;
}

interface Pose {
  position: THREE.Vector3;
  target: THREE.Vector3;
}

interface InternalApi {
  focusNode(id: string, notify: boolean): void;
  clearFocus(notify: boolean): void;
  fitAll(): void;
  setVisible(ids: Set<string> | null): void;
  setEdgeLabels(on: boolean): void;
}

const LINE_VERTEX = /* glsl */ `
  attribute vec4 aRGBA;
  varying vec4 vRGBA;
  void main() {
    vRGBA = aRGBA;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;
const LINE_FRAGMENT = /* glsl */ `
  precision highp float;
  varying vec4 vRGBA;
  void main() { if (vRGBA.a < 0.003) discard; gl_FragColor = vRGBA; }`;

/* Ribbons: each transfer edge is a quad whose two long sides are offset in screen space, so
   the stroke keeps a constant pixel width (WebGL lines are always one pixel wide). */
const RIBBON_VERTEX = /* glsl */ `
  attribute vec3 aOther;
  attribute float aSide, aWide;
  attribute vec4 aRGBA;
  uniform vec2 uResolution;
  uniform float uWidth;
  varying vec4 vRGBA;
  varying float vSide;
  void main() {
    vRGBA = aRGBA;
    vSide = aSide;
    vec4 c0 = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    vec4 c1 = projectionMatrix * modelViewMatrix * vec4(aOther, 1.0);
    vec2 s0 = c0.xy / max(c0.w, 1e-4) * uResolution * 0.5;
    vec2 s1 = c1.xy / max(c1.w, 1e-4) * uResolution * 0.5;
    vec2 dir = s1 - s0;
    float len = length(dir);
    dir = len > 1e-4 ? dir / len : vec2(1.0, 0.0);
    vec2 nrm = vec2(-dir.y, dir.x) * aSide * uWidth * aWide * 0.5;
    c0.xy += nrm / (uResolution * 0.5) * c0.w;
    gl_Position = c0;
  }`;
const RIBBON_FRAGMENT = /* glsl */ `
  precision highp float;
  varying vec4 vRGBA;
  varying float vSide;
  void main() {
    float a = vRGBA.a * (1.0 - smoothstep(0.55, 1.0, abs(vSide)));
    if (a < 0.003) discard;
    gl_FragColor = vec4(vRGBA.rgb, a);
  }`;

/* ------------------------------------------------------------------ component */

export const PolarisCanvas = forwardRef<PolarisCanvasHandle, PolarisCanvasProps>(
  function PolarisCanvas(
    {
      nodes,
      links,
      focusId,
      visibleIds,
      onSelect,
      onHover,
      onSelectEdge,
      padding,
      edgeLabels = true,
      interactive = true,
      className,
    },
    ref,
  ) {
    const containerRef = useRef<HTMLDivElement>(null);
    const tooltipRef = useRef<HTMLDivElement>(null);
    const tooltipTitleRef = useRef<HTMLDivElement>(null);
    const tooltipKindRef = useRef<HTMLDivElement>(null);
    const hubLabelRefs = useRef<Map<string, HTMLDivElement>>(new Map());
    const callbacks = useRef({ onSelect, onHover, onSelectEdge });
    callbacks.current = { onSelect, onHover, onSelectEdge };
    const pad = useRef({ left: 0, right: 0, top: 0, bottom: 0 });
    pad.current = {
      left: padding?.left ?? 0,
      right: padding?.right ?? 0,
      top: padding?.top ?? 0,
      bottom: padding?.bottom ?? 0,
    };
    const apiRef = useRef<InternalApi | null>(null);
    // The props to apply as soon as the scene exists (effects below run after the build).
    const wanted = useRef({ visibleIds, focusId, edgeLabels });
    wanted.current = { visibleIds, focusId, edgeLabels };

    useImperativeHandle(ref, () => ({
      focusNode: (id) => apiRef.current?.focusNode(id, false),
      clearFocus: () => apiRef.current?.clearFocus(false),
      fitAll: () => apiRef.current?.fitAll(),
    }));

    useEffect(() => {
      const container = containerRef.current;
      const tooltip = tooltipRef.current;
      if (!container || !tooltip) return;
      const tooltipEl: HTMLDivElement = tooltip;
      // Overlays are positioned against the container; a static one gets `relative`, an
      // absolutely placed one (the usual case) is left as it is.
      if (getComputedStyle(container).position === "static") container.style.position = "relative";

      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const motion = reducedMotion ? 0 : 1;
      // Phones and display-only canvases draw at most 1.5 device pixels per CSS pixel.
      const dprCap = !interactive || window.innerWidth < 640 ? 1.5 : 2;
      const dpr = () => Math.min(window.devicePixelRatio, dprCap);

      /* ---------------- scene data (layout once per dataset) ---------------- */
      const layout = layoutNodes(nodes, links);
      const rand = seededRandom(hashString("polaris-drift"));
      const sceneNodes: SceneNode[] = nodes.map((data, index) => {
        const base = layout.get(data.id)?.clone() ?? new THREE.Vector3();
        return {
          id: data.id,
          index,
          data,
          base,
          pos: base.clone(),
          alphaTo: 1,
          alpha: 1,
          visible: true,
          phase: rand() * Math.PI * 2,
          drift: new THREE.Vector3(0.5 + rand() * 0.5, 0.5 + rand() * 0.5, 0.5 + rand() * 0.5),
          ring: 0,
          boost: 0,
          boostTo: 0,
          pulse: 1,
          pulseTo: 1,
        };
      });
      const byId = new Map(sceneNodes.map((n) => [n.id, n]));
      const neighbours = buildNeighbours(nodes, links);
      const N = sceneNodes.length;

      // One drawn link per node pair; the highest-priority kind wins.
      const linkByKey = new Map<string, { a: SceneNode; b: SceneNode; kind: string }>();
      for (const l of links) {
        const a = byId.get(l.source);
        const b = byId.get(l.target);
        if (!a || !b || a === b) continue;
        const key = a.id < b.id ? `${a.id}|${b.id}` : `${b.id}|${a.id}`;
        const prev = linkByKey.get(key);
        if (!prev || (LINK_PRIORITY[l.kind] ?? 0) > (LINK_PRIORITY[prev.kind] ?? 0)) {
          linkByKey.set(key, { a, b, kind: l.kind });
        }
      }
      let segCount = 0;
      let ribbonCount = 0;
      const sceneLinks: SceneLink[] = [];
      for (const { a, b, kind } of linkByKey.values()) {
        const isRibbon = RIBBON_KINDS.has(kind) && a.data.kind === "line" && b.data.kind === "line";
        const pieces = isRibbon ? 0 : DASHED_KINDS.has(kind) ? DASH_PIECES : 1;
        sceneLinks.push({
          a,
          b,
          kind,
          color: rgb(LINK_COLORS[kind] ?? "#bdbdbd"),
          pieces,
          seg: segCount,
          ribbon: isRibbon ? ribbonCount++ : -1,
          alpha: 0,
          labelEl: null,
          link: { source: a.id, target: b.id, kind },
        });
        segCount += pieces;
      }

      /* ---------------- three ---------------- */
      const renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: "high-performance",
      });
      renderer.setPixelRatio(dpr());
      renderer.setClearColor(0x000000, 0);
      renderer.domElement.setAttribute("aria-hidden", "true");
      renderer.domElement.style.display = "block";
      renderer.domElement.style.touchAction = "none";
      container.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(42, 1, 1, 20000);
      camera.position.set(0, 120, 1800);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.rotateSpeed = 0.6;
      controls.minDistance = 80;
      controls.maxDistance = 8000;
      controls.autoRotateSpeed = 0.22;
      controls.autoRotate = motion === 1;
      if (!interactive) {
        // Display-only: no user orbit, zoom or pan; fly-to and the slow rotation still run.
        controls.enableRotate = false;
        controls.enableZoom = false;
        controls.enablePan = false;
        // OrbitControls claims every touch on connect; hand page gestures back.
        renderer.domElement.style.touchAction = "auto";
      }

      // Points
      const pPos = new Float32Array(N * 3);
      const pCol = new Float32Array(N * 3);
      const pSize = new Float32Array(N);
      const pAlpha = new Float32Array(N).fill(1);
      const pRing = new Float32Array(N);
      const pBoost = new Float32Array(N);
      const pPulse = new Float32Array(N).fill(1);
      const pHub = new Float32Array(N);
      const pPhase = new Float32Array(N);
      sceneNodes.forEach((n, i) => {
        const [r, g, b] = rgb(nodeColor(n.data));
        pCol[i * 3] = r;
        pCol[i * 3 + 1] = g;
        pCol[i * 3 + 2] = b;
        pSize[i] = KIND_SIZE[n.data.kind];
        pHub[i] = n.data.kind === "line" ? 1 : 0;
        pPhase[i] = n.phase;
      });
      const dyn = (arr: Float32Array, size: number) =>
        new THREE.BufferAttribute(arr, size).setUsage(THREE.DynamicDrawUsage);
      const pGeo = new THREE.BufferGeometry();
      pGeo.setAttribute("position", dyn(pPos, 3));
      pGeo.setAttribute("aColor", new THREE.BufferAttribute(pCol, 3));
      pGeo.setAttribute("aSize", new THREE.BufferAttribute(pSize, 1));
      pGeo.setAttribute("aAlpha", dyn(pAlpha, 1));
      pGeo.setAttribute("aRing", dyn(pRing, 1));
      pGeo.setAttribute("aBoost", dyn(pBoost, 1));
      pGeo.setAttribute("aPulse", dyn(pPulse, 1));
      pGeo.setAttribute("aHub", new THREE.BufferAttribute(pHub, 1));
      pGeo.setAttribute("aPhase", new THREE.BufferAttribute(pPhase, 1));
      // Frustum culling would use a stale bounding sphere while nodes drift.
      pGeo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e6);
      const pMat = createPointMaterial(motion);
      const points = new THREE.Points(pGeo, pMat);
      points.renderOrder = 3;
      scene.add(points);

      // Thin links
      const lPos = new Float32Array(Math.max(1, segCount) * 6);
      const lCol = new Float32Array(Math.max(1, segCount) * 8);
      const lGeo = new THREE.BufferGeometry();
      lGeo.setAttribute("position", dyn(lPos, 3));
      lGeo.setAttribute("aRGBA", dyn(lCol, 4));
      lGeo.setDrawRange(0, segCount * 2);
      lGeo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e6);
      const lMat = new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        depthTest: false,
        vertexShader: LINE_VERTEX,
        fragmentShader: LINE_FRAGMENT,
      });
      const lines = new THREE.LineSegments(lGeo, lMat);
      lines.renderOrder = 1;
      scene.add(lines);

      // Ribbons: 4 vertices and 6 indices per transfer edge.
      const R = Math.max(1, ribbonCount);
      const rPos = new Float32Array(R * 12);
      const rOther = new Float32Array(R * 12);
      const rSide = new Float32Array(R * 4);
      const rWide = new Float32Array(R * 4).fill(1);
      const rCol = new Float32Array(R * 16);
      const rIdx = new Uint16Array(R * 6);
      for (let i = 0; i < R; i++) {
        rSide.set([-1, 1, -1, 1], i * 4);
        const v = i * 4;
        rIdx.set([v, v + 1, v + 2, v + 1, v + 3, v + 2], i * 6);
      }
      const rGeo = new THREE.BufferGeometry();
      rGeo.setAttribute("position", dyn(rPos, 3));
      rGeo.setAttribute("aOther", dyn(rOther, 3));
      rGeo.setAttribute("aSide", new THREE.BufferAttribute(rSide, 1));
      rGeo.setAttribute("aWide", dyn(rWide, 1));
      rGeo.setAttribute("aRGBA", dyn(rCol, 4));
      rGeo.setIndex(new THREE.BufferAttribute(rIdx, 1));
      rGeo.setDrawRange(0, ribbonCount * 6);
      rGeo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e6);
      const rMat = new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        depthTest: false,
        side: THREE.DoubleSide,
        uniforms: {
          uResolution: { value: new THREE.Vector2(1, 1) },
          uWidth: { value: RIBBON_PX },
        },
        vertexShader: RIBBON_VERTEX,
        fragmentShader: RIBBON_FRAGMENT,
      });
      const ribbons = new THREE.Mesh(rGeo, rMat);
      ribbons.renderOrder = 2;
      ribbons.frustumCulled = false;
      scene.add(ribbons);

      /* ---------------- satellite label overlays (the lit non-hub nodes) ---------------- */
      const satLabels: HTMLDivElement[] = [];
      for (let i = 0; i < 3; i++) {
        const el = document.createElement("div");
        el.setAttribute("aria-hidden", "true");
        Object.assign(el.style, {
          position: "absolute",
          left: "0",
          top: "0",
          zIndex: "2",
          pointerEvents: "none",
          opacity: "0",
          whiteSpace: "nowrap",
          fontSize: "11px",
          fontWeight: "600",
          color: "#111111",
          textShadow: HALO,
          maxWidth: "220px",
          overflow: "hidden",
          textOverflow: "ellipsis",
        } satisfies Partial<CSSStyleDeclaration>);
        container.appendChild(el);
        satLabels.push(el);
      }

      /* ---------------- edge word overlays ---------------- */
      const edgeLabelLayer = document.createElement("div");
      edgeLabelLayer.setAttribute("aria-hidden", "true");
      Object.assign(edgeLabelLayer.style, {
        position: "absolute",
        left: "0",
        top: "0",
        zIndex: "1",
        pointerEvents: "none",
      } satisfies Partial<CSSStyleDeclaration>);
      container.appendChild(edgeLabelLayer);
      function edgeLabelFor(l: SceneLink): HTMLDivElement {
        if (l.labelEl) return l.labelEl;
        const el = document.createElement("div");
        el.textContent = LINK_WORDS[l.kind] ?? l.kind;
        Object.assign(el.style, {
          position: "absolute",
          left: "0",
          top: "0",
          opacity: "0",
          whiteSpace: "nowrap",
          fontSize: "10px",
          fontWeight: "600",
          letterSpacing: "0.02em",
          lineHeight: "14px",
          padding: "0 4px",
          color: LINK_COLORS[l.kind] ?? "#555",
          background: STAGE_BG,
          border: `1px solid ${LINK_COLORS[l.kind] ?? "#555"}`,
          transition: "opacity 160ms",
        } satisfies Partial<CSSStyleDeclaration>);
        edgeLabelLayer.appendChild(el);
        l.labelEl = el;
        return el;
      }

      /* ---------------- state ---------------- */
      let hovered: SceneNode | null = null;
      let hoveredLink: SceneLink | null = null;
      let selectedLink: SceneLink | null = null;
      let focused: SceneNode | null = null;
      let searching = false;
      let showEdgeLabels = interactive && wanted.current.edgeLabels;
      let dirty = true;
      const pointer = { x: -1e4, y: -1e4, inside: false, downX: 0, downY: 0 };
      const tmpA = new THREE.Vector3();
      const tmpB = new THREE.Vector3();
      const tmpC = new THREE.Vector3();
      let widthCss = 1;
      let heightCss = 1;

      const fly = {
        active: false,
        t: 0,
        duration: FLY_MS / 1000,
        from: new THREE.Vector3(),
        mid: new THREE.Vector3(),
        to: new THREE.Vector3(),
        fromTarget: new THREE.Vector3(),
        toTarget: new THREE.Vector3(),
      };

      const visibleNodes = () => sceneNodes.filter((n) => n.visible);

      /* ---------------- camera ---------------- */
      function flyTo(pose: Pose, ms: number) {
        fly.active = true;
        fly.t = 0;
        fly.duration = reducedMotion ? 0.001 : ms / 1000;
        fly.from.copy(camera.position);
        fly.fromTarget.copy(controls.target);
        fly.to.copy(pose.position);
        fly.toTarget.copy(pose.target);
        const travel = fly.from.distanceTo(fly.to);
        const dir = tmpA.copy(fly.to).sub(fly.from).normalize();
        const side = tmpB.crossVectors(dir, camera.up);
        if (side.lengthSq() < 1e-6) side.set(1, 0, 0);
        else side.normalize();
        // A quadratic bezier: the midpoint is lifted and pushed sideways so the camera
        // swings in rather than tracking a straight line.
        fly.mid
          .lerpVectors(fly.from, fly.to, 0.5)
          .addScaledVector(camera.up, Math.min(travel * 0.14, 130))
          .addScaledVector(side, Math.min(travel * 0.1, 90));
        controls.enabled = false;
        dirty = true;
      }

      /** Camera distance that fits a sphere of `radius` for the current aspect. */
      function fitDistance(radius: number): number {
        const vFov = THREE.MathUtils.degToRad(camera.fov);
        const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
        const fov = Math.min(vFov, hFov);
        return THREE.MathUtils.clamp(
          radius / Math.sin(fov / 2),
          controls.minDistance,
          controls.maxDistance,
        );
      }

      /** Shift a pose so its target sits in the free part of the stage, not behind a panel. */
      function offsetForPanels(pose: Pose): Pose {
        const p = pad.current;
        const offsetX = (p.left - p.right) / 2;
        const offsetY = (p.top - p.bottom) / 2;
        if (offsetX === 0 && offsetY === 0) return pose;
        const distance = pose.position.distanceTo(pose.target);
        const worldPerPx =
          (2 * distance * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)) / heightCss;
        probe.position.copy(pose.position);
        probe.up.copy(camera.up);
        probe.lookAt(pose.target);
        probe.updateMatrixWorld();
        const right = tmpB.setFromMatrixColumn(probe.matrixWorld, 0).normalize();
        const up = tmpC.setFromMatrixColumn(probe.matrixWorld, 1).normalize();
        const shift = right
          .multiplyScalar(-offsetX * worldPerPx)
          .addScaledVector(up, offsetY * worldPerPx);
        pose.position.add(shift);
        pose.target.add(shift);
        return pose;
      }

      /**
       * Pose that frames the given positions from the camera's current direction, using the
       * free stage: the sphere fit is refined by projecting the points and scaling the
       * distance so the widest extent reaches ~88% of the free area.
       */
      const probe = new THREE.PerspectiveCamera();
      function fitPose(positions: THREE.Vector3[]): Pose {
        const { centre, radius } = boundingSphere(positions);
        const dir = tmpA.copy(camera.position).sub(controls.target);
        if (dir.lengthSq() < 1e-6) dir.set(0, 0.1, 1);
        dir.normalize();
        const p = pad.current;
        const freeW = Math.max(80, widthCss - p.left - p.right);
        const freeH = Math.max(80, heightCss - p.top - p.bottom);
        let distance = fitDistance(radius + 80);
        probe.fov = camera.fov;
        probe.aspect = camera.aspect;
        probe.near = camera.near;
        probe.far = camera.far;
        probe.up.copy(camera.up);
        for (let pass = 0; pass < 3; pass++) {
          probe.position.copy(centre).addScaledVector(dir, distance);
          probe.lookAt(centre);
          probe.updateProjectionMatrix();
          probe.updateMatrixWorld();
          let extent = 0;
          for (const q of positions) {
            tmpB.copy(q).project(probe);
            extent = Math.max(
              extent,
              (Math.abs(tmpB.x) * widthCss) / freeW,
              (Math.abs(tmpB.y) * heightCss) / freeH,
            );
          }
          if (extent < 1e-3) break;
          distance = THREE.MathUtils.clamp(
            (distance * extent) / 0.88,
            controls.minDistance,
            controls.maxDistance,
          );
        }
        return offsetForPanels({
          position: centre.clone().addScaledVector(dir, distance),
          target: centre.clone(),
        });
      }

      /** Pose that looks at a node from a comfortable distance for its kind: a hub is framed
       *  with its shell and room around it so the neighbouring hubs stay in view. */
      function focusPose(node: SceneNode): Pose {
        const at = node.base;
        const dir = tmpA.copy(camera.position).sub(at);
        if (dir.lengthSq() < 1e-6) dir.set(0, 0.1, 1);
        dir.normalize();
        const distance =
          node.data.kind === "line"
            ? fitDistance(400)
            : THREE.MathUtils.clamp(fitDistance(80), controls.minDistance, 480);
        return offsetForPanels({
          position: at.clone().addScaledVector(dir, distance).addScaledVector(camera.up, 20),
          target: at.clone(),
        });
      }

      function fitAll(ms = FLY_MS) {
        const positions = visibleNodes().map((n) => n.base);
        if (positions.length === 0) return;
        flyTo(fitPose(positions), ms);
      }

      /* ---------------- emphasis ---------------- */
      // One model for hover and selection: the interacted node (or an edge's two endpoints)
      // at full brightness and a little larger, its neighbours visible but quieter, and
      // everything else faded hard so the rest reads as background. Nothing pulses while
      // something is emphasised; at rest the heartbeat returns.
      const lit = new Set<SceneNode>();
      const near = new Set<SceneNode>();
      let activeLink: SceneLink | null = null;
      let emphasised = false;
      function applyEmphasis() {
        lit.clear();
        near.clear();
        activeLink = null;
        if (hovered) {
          lit.add(hovered);
          for (const id of neighbours.get(hovered.id) ?? []) near.add(byId.get(id)!);
        } else if (hoveredLink || selectedLink) {
          activeLink = selectedLink ?? hoveredLink;
          lit.add(activeLink!.a);
          lit.add(activeLink!.b);
        } else if (focused) {
          lit.add(focused);
          for (const id of neighbours.get(focused.id) ?? []) near.add(byId.get(id)!);
        }
        emphasised = lit.size > 0;
        for (const n of sceneNodes) {
          if (!emphasised) {
            n.alphaTo = n.visible ? 1 : GHOST;
            n.boostTo = 0;
            n.pulseTo = 1;
          } else if (lit.has(n)) {
            n.alphaTo = 1;
            n.boostTo = 1;
            n.pulseTo = 0;
          } else if (near.has(n)) {
            n.alphaTo = NEAR;
            n.boostTo = 0;
            n.pulseTo = 0;
          } else {
            n.alphaTo = FADE;
            n.boostTo = 0;
            n.pulseTo = 0;
          }
        }
        dirty = true;
      }

      /* ---------------- search (ghost + dim + fly, no position change) ---------------- */
      let currentVisible: Set<string> | null | undefined;
      function setVisible(ids: Set<string> | null) {
        if (ids === currentVisible) return;
        const first = currentVisible === undefined;
        currentVisible = ids;
        searching = ids !== null;
        for (const n of sceneNodes) n.visible = !ids || ids.has(n.id);
        if (hovered && !hovered.visible) hovered = null;
        // The focus prop decides the camera: a visible wanted node is flown to, otherwise the
        // visible set is fitted. The internal focus may be stale here because the parent
        // updates both props in the same render.
        const want = wanted.current.focusId ? byId.get(wanted.current.focusId) : undefined;
        focused = want && want.visible ? want : null;
        if (first) for (const n of sceneNodes) n.alpha = n.visible ? 1 : GHOST;
        applyEmphasis();
        if (focused) flyTo(focusPose(focused), FLY_MS);
        else fitAll(first ? 1400 : FLY_MS);
      }

      /** The clicked edge stays highlighted until the next selection or an empty click. */
      function selectEdge(link: SceneLink | null) {
        if (link === selectedLink) return;
        selectedLink = link;
        applyEmphasis();
        callbacks.current.onSelectEdge?.(link ? link.link : null);
      }

      /* ---------------- focus ---------------- */
      // Clearing the focus never moves the camera or the layout: the highlight goes, the
      // rotation carries on from where it is.
      function setFocus(node: SceneNode | null, notify: boolean) {
        const changed = node !== focused;
        focused = node;
        applyEmphasis();
        if (node && (changed || !fly.active)) flyTo(focusPose(node), FLY_MS);
        if (notify && changed) callbacks.current.onSelect?.(node ? node.id : null);
      }

      apiRef.current = {
        focusNode: (id, notify) => {
          const n = byId.get(id);
          if (n && n.visible) setFocus(n, notify);
        },
        clearFocus: (notify) => setFocus(null, notify),
        fitAll: () => fitAll(),
        setVisible,
        setEdgeLabels: (on) => {
          showEdgeLabels = interactive && on;
          dirty = true;
        },
      };

      /* ---------------- pointer ---------------- */
      const canvas = renderer.domElement;
      const onPointerMove = (e: PointerEvent) => {
        const r = canvas.getBoundingClientRect();
        pointer.x = e.clientX - r.left;
        pointer.y = e.clientY - r.top;
        pointer.inside = true;
        dirty = true;
      };
      const onPointerLeave = () => {
        pointer.inside = false;
        dirty = true;
      };
      const onPointerDown = (e: PointerEvent) => {
        pointer.downX = e.clientX;
        pointer.downY = e.clientY;
      };
      const onPointerUp = (e: PointerEvent) => {
        const dx = e.clientX - pointer.downX;
        const dy = e.clientY - pointer.downY;
        if (dx * dx + dy * dy > 36) return; // a drag, not a click
        // Pick again at the click point: the pointer may have moved since the last frame.
        hovered = pickNode();
        hoveredLink = hovered ? null : pickLink();
        if (!hovered && hoveredLink) {
          selectEdge(hoveredLink);
          return;
        }
        if (selectedLink) selectEdge(null);
        setFocus(hovered, true);
      };
      if (interactive) {
        canvas.addEventListener("pointermove", onPointerMove);
        canvas.addEventListener("pointerleave", onPointerLeave);
        canvas.addEventListener("pointerdown", onPointerDown);
        canvas.addEventListener("pointerup", onPointerUp);
      }
      const onControlsChange = () => {
        dirty = true;
      };
      controls.addEventListener("change", onControlsChange);

      const projected = new Float32Array(N * 3); // sx, sy, depth per node, this frame

      function pixelSize(n: SceneNode): number {
        const depth = tmpC.copy(n.pos).applyMatrix4(camera.matrixWorldInverse).z;
        const px =
          (KIND_SIZE[n.data.kind] * (pMat.uniforms.uPx.value as number)) / Math.max(-depth, 1);
        return THREE.MathUtils.clamp(px, 4, 72) / dpr();
      }

      /** Nearest visible node under the pointer, within a radius that grows with the disc. */
      function pickNode(): SceneNode | null {
        if (!pointer.inside) return null;
        let best: SceneNode | null = null;
        let bestScore = Infinity;
        for (const n of sceneNodes) {
          if (!n.visible || n.alpha < 0.3) continue;
          const z = projected[n.index * 3 + 2];
          if (z > 1) continue;
          const dx = projected[n.index * 3] - pointer.x;
          const dy = projected[n.index * 3 + 1] - pointer.y;
          const d = Math.sqrt(dx * dx + dy * dy);
          const px = pixelSize(n);
          const radius = Math.max(16, px * 0.6 + 8);
          if (d > radius) continue;
          const score = d - px * 0.15 + z * 2; // closer discs and nearer depth win
          if (score < bestScore) {
            bestScore = score;
            best = n;
          }
        }
        return best;
      }

      /** Nearest visibly drawn edge within EDGE_REACH CSS pixels of the pointer. */
      function pickLink(): SceneLink | null {
        if (!pointer.inside) return null;
        let best: SceneLink | null = null;
        let bestD = Infinity;
        for (const l of sceneLinks) {
          if (l.alpha < 0.06) continue;
          const ia = l.a.index * 3;
          const ib = l.b.index * 3;
          if (projected[ia + 2] > 1 || projected[ib + 2] > 1) continue;
          const d = segmentDistance(
            pointer.x,
            pointer.y,
            projected[ia],
            projected[ia + 1],
            projected[ib],
            projected[ib + 1],
          );
          if (d <= EDGE_REACH && d < bestD) {
            bestD = d;
            best = l;
          }
        }
        return best;
      }

      function showTooltip(title: string, sub: string, color: string) {
        if (!tooltipTitleRef.current || !tooltipKindRef.current) return;
        tooltipTitleRef.current.textContent = title;
        tooltipKindRef.current.textContent = sub;
        tooltipKindRef.current.style.color = color;
        const left = Math.min(pointer.x + 16, widthCss - 260);
        const top = Math.min(pointer.y + 16, heightCss - 56);
        tooltipEl.style.transform = `translate(${left}px, ${top}px)`;
        tooltipEl.style.opacity = "1";
      }

      function updateHover() {
        if (!interactive) return;
        const nextNode = pickNode();
        if (nextNode !== hovered) {
          hovered = nextNode;
          callbacks.current.onHover?.(nextNode?.id ?? null);
          applyEmphasis();
        }
        const nextLink = hovered ? null : pickLink();
        if (nextLink !== hoveredLink) {
          hoveredLink = nextLink;
          applyEmphasis();
        }
        if (hovered) {
          showTooltip(
            hovered.data.label,
            hovered.data.kind === "line"
              ? `${KIND_LABELS.line} · ${GROUP_LABELS[hovered.data.group]}`
              : KIND_LABELS[hovered.data.kind],
            nodeColor(hovered.data),
          );
          canvas.style.cursor = "pointer";
        } else if (hoveredLink) {
          showTooltip(
            LINK_WORDS[hoveredLink.kind] ?? hoveredLink.kind,
            `${hoveredLink.a.data.label} · ${hoveredLink.b.data.label}`,
            LINK_COLORS[hoveredLink.kind] ?? "#555",
          );
          canvas.style.cursor = "pointer";
        } else {
          tooltipEl.style.opacity = "0";
          canvas.style.cursor = "grab";
        }
      }

      /* ---------------- labels ---------------- */
      type Rect = { l: number; t: number; r: number; b: number };
      const placed: Rect[] = [];
      const shownLabels = new Set<string>();
      // Label boxes are measured once per text, never per frame: reading offsetWidth after
      // writing transforms would force a reflow for every label on every frame.
      const labelSizes = new Map<HTMLDivElement, { text: string; w: number; h: number }>();
      function labelSize(el: HTMLDivElement): { w: number; h: number } {
        const text = el.textContent ?? "";
        const cached = labelSizes.get(el);
        if (cached && cached.text === text) return cached;
        const next = { text, w: el.offsetWidth || 120, h: el.offsetHeight || 16 };
        labelSizes.set(el, next);
        return next;
      }
      function overlaps(a: Rect): boolean {
        for (const p of placed) {
          if (a.l < p.r && a.r > p.l && a.t < p.b && a.b > p.t) return true;
        }
        return false;
      }
      function insideStage(rect: Rect): boolean {
        const p = pad.current;
        return !(
          rect.r < p.left ||
          rect.l > widthCss - p.right ||
          rect.b < p.top ||
          rect.t > heightCss - p.bottom
        );
      }
      /** Places a label box at (x, y) unless it leaves the stage or covers another label. */
      function placeBox(el: HTMLDivElement, x: number, y: number, opacity: number, force: boolean) {
        const { w, h } = labelSize(el);
        const rect = { l: x, t: y, r: x + w, b: y + h };
        if (!insideStage(rect) || (!force && overlaps(rect))) {
          el.style.opacity = "0";
          return false;
        }
        placed.push(rect);
        el.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
        el.style.opacity = String(opacity);
        return true;
      }
      /** Centres a node's label under its disc. Hub labels stay on while ghosted or faded. */
      function placeLabel(el: HTMLDivElement, n: SceneNode, force: boolean): boolean {
        const z = projected[n.index * 3 + 2];
        const isHub = n.data.kind === "line";
        if (z > 1 || (!isHub && !lit.has(n))) {
          el.style.opacity = "0";
          return false;
        }
        const px = pixelSize(n);
        const { w } = labelSize(el);
        const x = projected[n.index * 3] - w / 2;
        const y = projected[n.index * 3 + 1] + px * 0.5 + 6;
        let opacity: number;
        if (!isHub) opacity = 1;
        else if (!emphasised) opacity = Math.max(0.45, Math.min(1, n.alpha));
        else if (lit.has(n)) opacity = 1;
        else if (near.has(n)) opacity = 0.8;
        else opacity = 0.3;
        return placeBox(el, x, y, opacity, force);
      }

      function updateLabels() {
        placed.length = 0;
        // Lit satellites get a label each (the interacted node, or an edge's endpoints);
        // a display-only canvas shows the hub labels alone.
        const litSats = interactive ? [...lit].filter((n) => n.data.kind !== "line") : [];
        satLabels.forEach((el, i) => {
          const n = litSats[i];
          if (!n) {
            el.style.opacity = "0";
            return;
          }
          el.textContent = n.data.label;
          placeLabel(el, n, true);
        });
        // Labels already on screen keep their place, then nearer hubs get first pick of the
        // space; without that hysteresis two close hubs would swap labels as they drift.
        const hubs = sceneNodes
          .filter((n) => n.data.kind === "line" && hubLabelRefs.current.has(n.id))
          .sort((a, b) => {
            // On a small display-only canvas the focused hub's label claims its space first.
            const la = !interactive && lit.has(a) ? 0 : 1;
            const lb = !interactive && lit.has(b) ? 0 : 1;
            if (la !== lb) return la - lb;
            const sa = shownLabels.has(a.id) ? 0 : 1;
            const sb = shownLabels.has(b.id) ? 0 : 1;
            return sa - sb || projected[a.index * 3 + 2] - projected[b.index * 3 + 2];
          });
        for (const n of hubs) {
          const shown = placeLabel(hubLabelRefs.current.get(n.id)!, n, lit.has(n));
          if (shown) shownLabels.add(n.id);
          else shownLabels.delete(n.id);
        }
        // Words on the focused hub's transfer edges (and on a hovered edge), at the midpoint.
        for (const l of sceneLinks) {
          const wanted =
            l === hoveredLink ||
            l === selectedLink ||
            (showEdgeLabels &&
              l.ribbon >= 0 &&
              focused !== null &&
              (l.a === focused || l.b === focused));
          if (!wanted) {
            if (l.labelEl) l.labelEl.style.opacity = "0";
            continue;
          }
          const el = edgeLabelFor(l);
          const ia = l.a.index * 3;
          const ib = l.b.index * 3;
          if (projected[ia + 2] > 1 || projected[ib + 2] > 1 || l.alpha < 0.2) {
            el.style.opacity = "0";
            continue;
          }
          const { w, h } = labelSize(el);
          const mx = (projected[ia] + projected[ib]) / 2 - w / 2;
          const my = (projected[ia + 1] + projected[ib + 1]) / 2 - h / 2;
          placeBox(el, mx, my, 1, l === hoveredLink || l === selectedLink);
        }
      }

      /* ---------------- frame ---------------- */
      const clock = new THREE.Clock();
      let raf = 0;

      function writeNodes(time: number, dt: number) {
        const ease = reducedMotion ? 1 : Math.min(1, dt * EASE_RATE);
        const ringStep = dt / (RING_MS / 1000);
        for (const n of sceneNodes) {
          if (Math.abs(n.alpha - n.alphaTo) > 0.002) {
            n.alpha += (n.alphaTo - n.alpha) * ease;
            dirty = true;
          } else n.alpha = n.alphaTo;
          if (Math.abs(n.boost - n.boostTo) > 0.002) {
            n.boost += (n.boostTo - n.boost) * ease;
            dirty = true;
          } else n.boost = n.boostTo;
          if (Math.abs(n.pulse - n.pulseTo) > 0.002) {
            n.pulse += (n.pulseTo - n.pulse) * ease;
            dirty = true;
          } else n.pulse = n.pulseTo;
          // Slow sinusoidal drift: alive, never enough to tangle.
          const amp = n.data.kind === "line" ? 3 : 7;
          n.pos.set(
            n.base.x + Math.sin(time * n.drift.x + n.phase) * amp * motion,
            n.base.y + Math.sin(time * n.drift.y * 0.9 + n.phase * 1.7) * amp * motion,
            n.base.z + Math.sin(time * n.drift.z * 1.1 + n.phase * 2.3) * amp * motion,
          );
          const i = n.index;
          pPos[i * 3] = n.pos.x;
          pPos[i * 3 + 1] = n.pos.y;
          pPos[i * 3 + 2] = n.pos.z;
          pAlpha[i] = n.alpha;
          pBoost[i] = n.boost;
          pPulse[i] = n.pulse;
          // The ring sweeps in over RING_MS on hover, stays full while focused, unwinds
          // when the pointer leaves.
          const ringTarget = n === hovered || n === focused ? 1 : 0;
          if (n.ring !== ringTarget) {
            n.ring = reducedMotion
              ? ringTarget
              : ringTarget > n.ring
                ? Math.min(1, n.ring + ringStep)
                : Math.max(0, n.ring - ringStep);
            dirty = true;
          }
          pRing[i] = n.ring;
        }
        pGeo.attributes.position.needsUpdate = true;
        pGeo.attributes.aAlpha.needsUpdate = true;
        pGeo.attributes.aRing.needsUpdate = true;
        pGeo.attributes.aBoost.needsUpdate = true;
        pGeo.attributes.aPulse.needsUpdate = true;
      }

      // Links ease on their own: a 'to' alpha from the emphasis model, approached each frame.
      const linkAlphaTo = (l: SceneLink): number => {
        if (!emphasised) {
          const rest = (LINK_ALPHA[l.kind] ?? 0.3) * Math.min(l.a.alpha, l.b.alpha);
          return searching && !l.a.visible && !l.b.visible ? Math.min(rest, EDGE_FADE) : rest;
        }
        if (l === activeLink) return 1;
        if (activeLink === null && (lit.has(l.a) || lit.has(l.b))) return EDGE_NEAR;
        return EDGE_FADE;
      };
      function writeLinks(dt: number) {
        const ease = reducedMotion ? 1 : Math.min(1, dt * EASE_RATE);
        for (const l of sceneLinks) {
          const a = l.a.pos;
          const b = l.b.pos;
          const to = linkAlphaTo(l);
          const alpha = Math.abs(l.alpha - to) > 0.002 ? l.alpha + (to - l.alpha) * ease : to;
          if (alpha !== to) dirty = true;
          l.alpha = alpha;
          const [r, g, bl] = l.color;
          if (l.ribbon >= 0) {
            const v = l.ribbon * 12;
            for (let k = 0; k < 2; k++) {
              rPos[v + k * 3] = a.x;
              rPos[v + k * 3 + 1] = a.y;
              rPos[v + k * 3 + 2] = a.z;
              rOther[v + k * 3] = b.x;
              rOther[v + k * 3 + 1] = b.y;
              rOther[v + k * 3 + 2] = b.z;
              rPos[v + 6 + k * 3] = b.x;
              rPos[v + 6 + k * 3 + 1] = b.y;
              rPos[v + 6 + k * 3 + 2] = b.z;
              rOther[v + 6 + k * 3] = a.x;
              rOther[v + 6 + k * 3 + 1] = a.y;
              rOther[v + 6 + k * 3 + 2] = a.z;
            }
            const wide = l === selectedLink ? 1.8 : l === hoveredLink ? 1.3 : 1;
            for (let k = 0; k < 4; k++) rWide[l.ribbon * 4 + k] = wide;
            const c = l.ribbon * 16;
            for (let k = 0; k < 4; k++) {
              rCol[c + k * 4] = r;
              rCol[c + k * 4 + 1] = g;
              rCol[c + k * 4 + 2] = bl;
              rCol[c + k * 4 + 3] = alpha;
            }
            continue;
          }
          for (let p = 0; p < l.pieces; p++) {
            // Dashed links draw the first 55% of each fifth; solid links draw it whole.
            const t0 = l.pieces === 1 ? 0 : (p + 0.1) / l.pieces;
            const t1 = l.pieces === 1 ? 1 : (p + 0.65) / l.pieces;
            const s = (l.seg + p) * 6;
            lPos[s] = a.x + (b.x - a.x) * t0;
            lPos[s + 1] = a.y + (b.y - a.y) * t0;
            lPos[s + 2] = a.z + (b.z - a.z) * t0;
            lPos[s + 3] = a.x + (b.x - a.x) * t1;
            lPos[s + 4] = a.y + (b.y - a.y) * t1;
            lPos[s + 5] = a.z + (b.z - a.z) * t1;
            const c = (l.seg + p) * 8;
            lCol[c] = r;
            lCol[c + 1] = g;
            lCol[c + 2] = bl;
            lCol[c + 3] = alpha;
            lCol[c + 4] = r;
            lCol[c + 5] = g;
            lCol[c + 6] = bl;
            lCol[c + 7] = alpha;
          }
        }
        lGeo.attributes.position.needsUpdate = true;
        lGeo.attributes.aRGBA.needsUpdate = true;
        rGeo.attributes.position.needsUpdate = true;
        rGeo.attributes.aOther.needsUpdate = true;
        rGeo.attributes.aRGBA.needsUpdate = true;
        rGeo.attributes.aWide.needsUpdate = true;
      }

      function project() {
        for (const n of sceneNodes) {
          tmpA.copy(n.pos).project(camera);
          projected[n.index * 3] = (tmpA.x * 0.5 + 0.5) * widthCss;
          projected[n.index * 3 + 1] = (-tmpA.y * 0.5 + 0.5) * heightCss;
          projected[n.index * 3 + 2] = tmpA.z;
        }
      }

      // Rendering pauses while the canvas is scrolled out of view or the tab is hidden.
      let onScreen = true;
      let running = false;
      function start() {
        if (running || !onScreen || document.hidden) return;
        running = true;
        clock.getDelta(); // the pause does not count as elapsed frame time
        dirty = true;
        raf = requestAnimationFrame(frame);
      }
      function stop() {
        running = false;
        cancelAnimationFrame(raf);
      }

      function frame() {
        if (!running) return;
        raf = requestAnimationFrame(frame);
        const dt = Math.min(clock.getDelta(), 0.05);
        const time = clock.elapsedTime;

        if (fly.active) {
          fly.t = Math.min(fly.t + dt / fly.duration, 1);
          const e = easeInOut(fly.t);
          tmpA.lerpVectors(fly.from, fly.mid, e);
          tmpB.lerpVectors(fly.mid, fly.to, e);
          camera.position.lerpVectors(tmpA, tmpB, e);
          controls.target.lerpVectors(fly.fromTarget, fly.toTarget, e);
          dirty = true;
          if (fly.t >= 1) {
            fly.active = false;
            controls.enabled = true;
          }
        }
        // The slow rotation runs all the time, except while the camera is flying.
        controls.autoRotate = motion === 1 && !fly.active;
        controls.update();

        // With motion on the picture is always alive, so every frame renders; with reduced
        // motion the loop only renders when something changed.
        const animating = motion === 1 || fly.active;
        if (!animating && !dirty) return;
        dirty = false;

        camera.updateMatrixWorld();
        writeNodes(time, dt);
        project();
        updateHover();
        writeLinks(dt);
        updateLabels();
        pMat.uniforms.uTime.value = time;
        renderer.render(scene, camera);
      }

      /* ---------------- size ---------------- */
      const resize = () => {
        const w = Math.max(1, container.clientWidth);
        const h = Math.max(1, container.clientHeight);
        widthCss = w;
        heightCss = h;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h, false);
        canvas.style.width = `${w}px`;
        canvas.style.height = `${h}px`;
        const ratio = dpr();
        pMat.uniforms.uPx.value =
          (h * ratio) / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2));
        (rMat.uniforms.uResolution.value as THREE.Vector2).set(w * ratio, h * ratio);
        rMat.uniforms.uWidth.value = RIBBON_PX * ratio;
        dirty = true;
      };
      resize();
      let lastW = widthCss;
      let lastH = heightCss;
      const ro = new ResizeObserver(() => {
        resize();
        // Re-frame only when the stage really changed shape (a few pixels do not count).
        if (Math.abs(widthCss - lastW) < 8 && Math.abs(heightCss - lastH) < 8) return;
        lastW = widthCss;
        lastH = heightCss;
        if (focused) flyTo(focusPose(focused), 400);
        else fitAll(400);
      });
      ro.observe(container);

      // First frame: the camera starts a little further out and settles in.
      setVisible(wanted.current.visibleIds);
      {
        const { centre } = boundingSphere(visibleNodes().map((n) => n.base));
        camera.position.copy(fly.to).sub(centre).multiplyScalar(1.3).add(centre);
        controls.target.copy(centre);
        fly.from.copy(camera.position);
        fly.fromTarget.copy(controls.target);
        fly.mid.lerpVectors(fly.from, fly.to, 0.5);
      }
      running = true;
      frame();
      const io = new IntersectionObserver((entries) => {
        onScreen = entries.some((e) => e.isIntersecting);
        if (onScreen) start();
        else stop();
      });
      io.observe(container);
      const onVisibility = () => (document.hidden ? stop() : start());
      document.addEventListener("visibilitychange", onVisibility);

      return () => {
        stop();
        io.disconnect();
        document.removeEventListener("visibilitychange", onVisibility);
        ro.disconnect();
        canvas.removeEventListener("pointermove", onPointerMove);
        canvas.removeEventListener("pointerleave", onPointerLeave);
        canvas.removeEventListener("pointerdown", onPointerDown);
        canvas.removeEventListener("pointerup", onPointerUp);
        controls.removeEventListener("change", onControlsChange);
        controls.dispose();
        pGeo.dispose();
        pMat.dispose();
        lGeo.dispose();
        lMat.dispose();
        rGeo.dispose();
        rMat.dispose();
        renderer.dispose();
        if (canvas.parentNode === container) container.removeChild(canvas);
        if (edgeLabelLayer.parentNode === container) container.removeChild(edgeLabelLayer);
        apiRef.current = null;
      };
    }, [nodes, links, interactive]);

    useEffect(() => {
      apiRef.current?.setVisible(visibleIds);
    }, [visibleIds, nodes, links, interactive]);

    useEffect(() => {
      if (focusId) apiRef.current?.focusNode(focusId, false);
      else apiRef.current?.clearFocus(false);
    }, [focusId, nodes, links, interactive]);

    useEffect(() => {
      apiRef.current?.setEdgeLabels(edgeLabels);
    }, [edgeLabels, nodes, links, interactive]);

    const hubs = nodes.filter((n) => n.kind === "line");

    return (
      <div
        ref={containerRef}
        className={className}
        style={{
          overflow: "hidden",
          isolation: "isolate",
          pointerEvents: interactive ? undefined : "none",
          backgroundColor: STAGE_BG,
          // Plain stage: a barely-there vertical gradient, nothing patterned.
          backgroundImage: "linear-gradient(180deg, #f7f8fa 0%, #f3f5f8 100%)",
        }}
      >
        <div
          ref={tooltipRef}
          aria-hidden="true"
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            zIndex: 3,
            maxWidth: 244,
            padding: "6px 9px",
            background: "#ffffff",
            border: "1px solid #111111",
            boxShadow: "2px 2px 0 #111111",
            pointerEvents: "none",
            opacity: 0,
            transition: "opacity 120ms",
            fontSize: 12,
            lineHeight: 1.3,
            color: "#111111",
          }}
        >
          <div ref={tooltipTitleRef} style={{ fontWeight: 600 }} />
          <div
            ref={tooltipKindRef}
            style={{
              fontSize: 11,
              marginTop: 1,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          />
        </div>
        {hubs.map((h) => (
          <div
            key={h.id}
            aria-hidden="true"
            ref={(el) => {
              if (el) hubLabelRefs.current.set(h.id, el);
              else hubLabelRefs.current.delete(h.id);
            }}
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              zIndex: 1,
              pointerEvents: "none",
              opacity: 0,
              whiteSpace: "nowrap",
              fontSize: 12,
              fontWeight: 700,
              letterSpacing: "0.02em",
              color: "#111111",
              textShadow: HALO,
              maxWidth: 240,
              overflow: "hidden",
              textOverflow: "ellipsis",
              transition: "opacity 160ms",
            }}
          >
            <span
              style={{
                display: "inline-block",
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: GROUP_COLORS[h.group],
                marginRight: 5,
                verticalAlign: "1px",
              }}
            />
            {h.label}
          </div>
        ))}
      </div>
    );
  },
);

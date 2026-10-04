// Deterministic 3D layout for the Polaris canvas: the disease lines are hubs spread over a
// wide, slightly flattened sphere, grouped by direction with gaps between groups; every
// satellite sits in a spherical shell around one hub, banded by kind and turned towards the
// other hubs it links to; a satellite with no owner and exactly two hubs sits between them.
// Computed once per dataset; pure, no three state.
import { Vector3 } from "three";
import type { CanvasLink, CanvasNode, GraphNodeKind } from "./PolarisCanvas";

type Group = CanvasNode["group"];
type SatelliteKind = Exclude<GraphNodeKind, "line">;

const GROUP_ORDER: Group[] = ["gain", "loss", "non_channel", "other"];
/** Gap between adjacent groups, in units of one hub slot. */
const GROUP_GAP = 1.0;
/** Minimum distance between two neighbouring hubs: their shells must not touch. */
const HUB_SPACING = 420;
/** The hub sphere is wider than tall, like a landscape viewport. */
const Y_SQUASH = 0.68;
/** ... and a little wider than deep. */
const X_STRETCH = 1.18;
/** Shell radius per satellite kind (world units from the hub). */
const BAND: Record<SatelliteKind, number> = {
  organisation: 80,
  conflict: 96,
  asset: 116,
  study: 140,
  paper: 166,
};

export function hashString(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** mulberry32: a small seeded PRNG so the layout never changes between loads. */
export function seededRandom(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const unit = (seedText: string) => seededRandom(hashString(seedText));

/** Point `i` of `n` on the unit sphere (Fibonacci lattice), spun by `spin` radians. */
export function spherePoint(i: number, n: number, spin = 0): Vector3 {
  if (n <= 1) return new Vector3(0, 0, 1);
  const y = 1 - (2 * (i + 0.5)) / n;
  const r = Math.sqrt(Math.max(0, 1 - y * y));
  const theta = Math.PI * (3 - Math.sqrt(5)) * i + spin;
  return new Vector3(Math.cos(theta) * r, y, Math.sin(theta) * r);
}

export function buildNeighbours(
  nodes: CanvasNode[],
  links: CanvasLink[],
): Map<string, Set<string>> {
  const map = new Map<string, Set<string>>(nodes.map((n) => [n.id, new Set<string>()]));
  for (const l of links) {
    const a = map.get(l.source);
    const b = map.get(l.target);
    if (!a || !b || l.source === l.target) continue;
    a.add(l.target);
    b.add(l.source);
  }
  return map;
}

/** Which hubs a satellite belongs to: its `lineKey` first, then every line it links to. */
export function hubsOf(
  node: CanvasNode,
  neighbours: Map<string, Set<string>>,
  hubIds: Set<string>,
): string[] {
  const out: string[] = [];
  if (node.lineKey) {
    const direct = hubIds.has(node.lineKey) ? node.lineKey : `line:${node.lineKey}`;
    if (hubIds.has(direct)) out.push(direct);
  }
  for (const other of [...(neighbours.get(node.id) ?? [])].sort()) {
    if (hubIds.has(other) && !out.includes(other)) out.push(other);
  }
  return out;
}

/**
 * Hubs over a sphere, in group order with empty slots between groups so each group occupies
 * its own region. The Fibonacci lattice keeps consecutive slots adjacent, so a group stays
 * together and the whole set spreads over all three axes.
 */
function placeHubs(hubs: CanvasNode[], out: Map<string, Vector3>) {
  const byGroup = new Map<Group, CanvasNode[]>(GROUP_ORDER.map((g) => [g, []]));
  for (const h of hubs) byGroup.get(h.group)!.push(h);
  for (const list of byGroup.values()) list.sort((a, b) => a.id.localeCompare(b.id));
  const groupsPresent = GROUP_ORDER.filter((g) => byGroup.get(g)!.length > 0);
  const onSphere = groupsPresent.reduce((n, g) => n + byGroup.get(g)!.length, 0);
  if (onSphere === 0) return;

  const gap = GROUP_GAP;
  const slots = Math.max(
    1,
    Math.round(onSphere + (groupsPresent.length > 1 ? (groupsPresent.length - 1) * gap : 0)),
  );
  // Nearest-neighbour angle of a lattice with `slots` points, then the radius at which that
  // chord is at least HUB_SPACING.
  const angle = Math.min(Math.PI, Math.sqrt((4 * Math.PI) / slots));
  const radius = Math.max(300, HUB_SPACING / (2 * Math.sin(angle / 2)));
  const spin = 0.6;

  let slot = 0;
  groupsPresent.forEach((g, gi) => {
    if (gi > 0) slot += gap;
    for (const h of byGroup.get(g)!) {
      const p = spherePoint(Math.round(slot), slots, spin).multiplyScalar(radius);
      p.y *= Y_SQUASH;
      p.x *= X_STRETCH;
      out.set(h.id, p);
      slot += 1;
    }
  });
}

interface Satellite {
  node: CanvasNode;
  partners: string[];
}

/**
 * One band of satellites around a hub: lattice points on the shell, assigned so that a
 * satellite shared with other hubs takes the free point nearest to those hubs.
 */
function placeBand(
  hubId: string,
  centre: Vector3,
  kind: SatelliteKind,
  items: Satellite[],
  out: Map<string, Vector3>,
) {
  const radius = BAND[kind];
  const n = items.length;
  const spin = (hashString(hubId + kind) % 628) / 100;
  // Spare points so the last assignments still have a choice.
  const count = n + Math.ceil(n * 0.15);
  const free = Array.from({ length: count }, (_, i) => spherePoint(i, count, spin));
  const used = new Set<number>();

  const preferredDir = (s: Satellite): Vector3 | null => {
    if (s.partners.length === 0) return null;
    const dir = new Vector3();
    for (const p of s.partners) {
      const q = out.get(p);
      if (q) dir.add(q.clone().sub(centre).normalize());
    }
    return dir.lengthSq() < 1e-6 ? null : dir.normalize();
  };

  const take = (s: Satellite, dir: Vector3 | null) => {
    let best = -1;
    let bestScore = -Infinity;
    const start = Math.floor(unit(`${hubId}:${s.node.id}`)() * count);
    for (let k = 0; k < count; k++) {
      const i = (start + k) % count;
      if (used.has(i)) continue;
      // Shared satellites face their partners; the rest take the first free point from a
      // seeded start, which spreads them evenly.
      const score = dir ? free[i].dot(dir) : -k;
      if (score > bestScore) {
        bestScore = score;
        best = i;
      }
    }
    used.add(best);
    const rad = radius * (0.9 + unit(`${s.node.id}:r`)() * 0.2);
    out.set(s.node.id, free[best].clone().multiplyScalar(rad).add(centre));
  };
  for (const s of items) if (s.partners.length > 0) take(s, preferredDir(s));
  for (const s of items) if (s.partners.length === 0) take(s, null);
}

export function layoutNodes(nodes: CanvasNode[], links: CanvasLink[]): Map<string, Vector3> {
  const out = new Map<string, Vector3>();
  const hubs = nodes.filter((n) => n.kind === "line");
  const hubIds = new Set(hubs.map((h) => h.id));
  const neighbours = buildNeighbours(nodes, links);

  placeHubs(hubs, out);

  // --- assign every satellite to one hub (or to a pair) ------------------------------------
  const bands = new Map<string, Map<SatelliteKind, Satellite[]>>();
  const pairs = new Map<string, { hubs: [string, string]; nodes: CanvasNode[] }>();
  const orphans: CanvasNode[] = [];
  for (const n of nodes) {
    if (n.kind === "line") continue;
    const owners = hubsOf(n, neighbours, hubIds);
    if (owners.length === 0) {
      orphans.push(n);
      continue;
    }
    const hasLineKey =
      n.lineKey !== undefined && (owners[0] === n.lineKey || owners[0] === `line:${n.lineKey}`);
    if (!hasLineKey && owners.length === 2) {
      const key = `${owners[0]}|${owners[1]}`;
      const entry = pairs.get(key) ?? { hubs: [owners[0], owners[1]], nodes: [] };
      entry.nodes.push(n);
      pairs.set(key, entry);
      continue;
    }
    const owner = owners[0];
    let byKind = bands.get(owner);
    if (!byKind) bands.set(owner, (byKind = new Map()));
    const list = byKind.get(n.kind as SatelliteKind) ?? [];
    list.push({ node: n, partners: owners.filter((o) => o !== owner) });
    byKind.set(n.kind as SatelliteKind, list);
  }

  for (const [hubId, byKind] of bands) {
    const centre = out.get(hubId)!;
    for (const [kind, items] of byKind) {
      items.sort((a, b) => a.node.id.localeCompare(b.node.id));
      placeBand(hubId, centre, kind, items, out);
    }
  }

  // A satellite owned by nobody but linked to exactly two hubs sits between them, fanned
  // out so several between the same pair do not stack.
  for (const [key, { hubs: pair, nodes: list }] of pairs) {
    list.sort((a, b) => a.id.localeCompare(b.id));
    const a = out.get(pair[0])!;
    const b = out.get(pair[1])!;
    const mid = a.clone().add(b).multiplyScalar(0.5);
    const axis = b.clone().sub(a).normalize();
    const across = new Vector3(0, 1, 0).cross(axis);
    if (across.lengthSq() < 1e-6) across.set(1, 0, 0);
    across.normalize();
    const r = unit(key);
    list.forEach((n, i) => {
      const t = list.length === 1 ? 0 : i / (list.length - 1) - 0.5;
      out.set(
        n.id,
        mid
          .clone()
          .addScaledVector(across, t * Math.min(140, 30 * list.length))
          .add(new Vector3((r() - 0.5) * 24, (r() - 0.5) * 24, (r() - 0.5) * 24)),
      );
    });
  }

  // Nodes with no hub at all sit loosely in the middle.
  orphans.sort((a, b) => a.id.localeCompare(b.id));
  orphans.forEach((n, i) => {
    const r = unit(n.id);
    out.set(n.id, spherePoint(i, orphans.length, 1.1).multiplyScalar(90 + r() * 30));
  });

  return out;
}

/** Centre and radius of the smallest sphere (approximated) around the given positions. */
export function boundingSphere(positions: Iterable<Vector3>): { centre: Vector3; radius: number } {
  const centre = new Vector3();
  let n = 0;
  for (const p of positions) {
    centre.add(p);
    n++;
  }
  if (n === 0) return { centre, radius: 1 };
  centre.divideScalar(n);
  let r = 0;
  for (const p of positions) r = Math.max(r, p.distanceTo(centre));
  return { centre, radius: Math.max(r, 1) };
}

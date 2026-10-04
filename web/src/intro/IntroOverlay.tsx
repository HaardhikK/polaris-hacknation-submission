// The landing intro (about 6.7 s, home route on a fresh load only): a muted night sky with a
// soft Milky Way band drifting very slowly; the buffalo constellation fading in star by star
// (the map's own dot with a steady halo and faint four-way spikes) while its wireframe draws
// on; the eye star swelling for a moment, then blooming into a soft light that fills the screen
// with the page background while it travels to the title;
// the title "Polaris" fading in from the light while a small star contracts into the dot of
// its i; then the card lifts away while the title flies into the header wordmark. The
// dashboard is mounted underneath the whole time. Skip, Escape or a click ends it. Under
// reduced motion only the title card shows, briefly, then lifts.
import { useEffect, useRef } from "react";
import * as THREE from "three";
import "@fontsource/cormorant-garamond/latin-400.css";
import "@fontsource/cormorant-garamond/latin-400-italic.css";
import { createPointMaterial } from "../graph/pointShader";
import { seededRandom } from "../graph/layout";
import { Wordmark } from "../shared/Layout";
import { ASPECT, EDGES, EYE, POINTS } from "./buffalo";

/* Intro-only constants: the night and the constellation's cyan. The title card uses tokens. */
const SPACE = "#05070b";
const TAGLINE = "A little direction, when you need it most.";
const CYAN: [number, number, number] = [0x3e / 255, 0xc9 / 255, 0xf0 / 255];
const STAR: [number, number, number] = [0xec / 255, 0xfa / 255, 0xff / 255];
/** The site favicon's four-pointed star (48 x 48 box, centre 24, arm 18). */
const STAR_PATH = "M24 6 L27.5 20.5 L42 24 L27.5 27.5 L24 42 L20.5 27.5 L6 24 L20.5 20.5 Z";

/* Timeline, ms. */
const SKY_IN: [number, number] = [0, 500];
const LIGHT: [number, number] = [300, 1950];
const FADE_IN_MS = 250;
const EDGE_MS = 300;
// The buffalo is complete at 2250 (last star plus its edges); it holds for 1.2 s while the
// chosen star swells, then blooms and travels to the dot of the i.
const SWELL: [number, number] = [2250, 3450];
const BLOOM: [number, number] = [3450, 4350];
const TRAVEL: [number, number] = [3450, 4800];
const CARD_IN: [number, number] = [4000, 4350];
const TITLE_IN: [number, number] = [4200, 4750];
const CONTRACT: [number, number] = [4200, 4850];
const DOT_SWAP: [number, number] = [4750, 4900];
// The title is complete at 4900; it holds for 1 s before the lift.
const LIFT: [number, number] = [5900, 6700];
const END = 6700;
/* Reduced motion: the card alone, then the lift. */
const RM_LIFT: [number, number] = [1200, 2000];
const SKIP_FADE_MS = 220;
const DRIFT = 0.006; // rad/s, the sky's slow rotation

const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const span = (t: number, [a, b]: [number, number]) => clamp01((t - a) / (b - a));
const easeOut = (x: number) => 1 - Math.pow(1 - x, 3);
const easeInOut = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

export type IntroMode = "full" | "reduced" | "none";

/** Play only on a fresh load of the home route; reduced motion gets the short card. */
export function introMode(): IntroMode {
  const h = window.location.hash;
  if (h && h !== "#" && h !== "#/") return "none";
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "reduced" : "full";
}

/* The Milky Way: a soft diagonal band with dust lanes and faint nebula colour, all muted. */
const SKY_VERTEX = /* glsl */ `
  void main() { gl_Position = vec4(position.xy, 0.0, 1.0); }`;
const SKY_FRAGMENT = /* glsl */ `
  precision highp float;
  uniform vec2 uRes;
  uniform float uFade, uAngle;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x),
               mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
  }
  float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    for (int k = 0; k < 5; k++) { v += a * noise(p); p = p * 2.03 + 17.0; a *= 0.5; }
    return v;
  }
  void main() {
    vec2 p = (gl_FragCoord.xy - 0.5 * uRes) / uRes.y;
    float ca = cos(uAngle), sa = sin(uAngle);
    p = mat2(ca, sa, -sa, ca) * p;
    vec2 dir = normalize(vec2(1.0, 0.55));
    float d = dot(p, vec2(-dir.y, dir.x));
    float along = dot(p, dir);
    float band = exp(-d * d / 0.03);
    float core = exp(-d * d / 0.006);
    float cloud = fbm(vec2(along * 3.0, d * 6.0) + 3.0);
    float lane = smoothstep(0.35, 0.75, fbm(vec2(along * 5.0, d * 14.0) + 9.0));
    float glow = band * (0.45 + 0.75 * cloud) * (1.0 - 0.55 * lane * core);
    vec3 base = vec3(0.020, 0.027, 0.043);
    vec3 dust = vec3(0.060, 0.068, 0.095) * glow + vec3(0.035, 0.034, 0.040) * core * cloud;
    float neb = smoothstep(0.55, 0.85, fbm(p * 2.2 + 31.0)) * band;
    vec3 tint = mix(vec3(0.050, 0.020, 0.055), vec3(0.015, 0.045, 0.060), fbm(p * 1.3 + 5.0));
    float vig = 1.0 - 0.35 * dot(p, p);
    vec3 col = (base + dust + tint * neb) * vig;
    gl_FragColor = vec4(mix(base, col, uFade), 1.0);
  }`;

/* Small sharp background stars (and, with spikes, the buffalo stars' halos), additive. */
const SOFT_VERTEX = /* glsl */ `
  attribute vec3 aColor;
  attribute float aSize, aAlpha, aPhase, aTwinkle, aSpike;
  uniform float uPx, uTime;
  varying vec3 vColor;
  varying float vAlpha, vSpike;
  void main() {
    vColor = aColor;
    vSpike = aSpike;
    float speed = 0.5 + fract(aPhase * 7.31) * 0.6;
    float tw = 0.5 + 0.5 * sin(uTime * speed + aPhase * 6.2831853);
    vAlpha = aAlpha * (1.0 - aTwinkle * tw * tw);
    gl_PointSize = aSize * uPx;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;
const SOFT_FRAGMENT = /* glsl */ `
  precision highp float;
  uniform float uSharp;
  varying vec3 vColor;
  varying float vAlpha, vSpike;
  void main() {
    vec2 p = 2.0 * gl_PointCoord - 1.0;
    float r2 = dot(p, p);
    float a = exp(-r2 * uSharp) + 0.18 * exp(-r2 * 3.0);
    // Four diffraction spikes, the favicon's star in light.
    vec2 q = abs(p);
    float spikes = exp(-q.y * 70.0) * exp(-q.x * 2.6) + exp(-q.x * 70.0) * exp(-q.y * 2.6);
    a = max(a, vSpike * spikes);
    a *= 1.0 - smoothstep(0.75, 1.0, max(q.x, q.y));
    if (a * vAlpha < 0.002) discard;
    gl_FragColor = vec4(vColor, a * vAlpha);
  }`;
const EDGE_VERTEX = /* glsl */ `
  attribute vec4 aRGBA;
  varying vec4 vRGBA;
  void main() {
    vRGBA = aRGBA;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;
const EDGE_FRAGMENT = /* glsl */ `
  precision highp float;
  varying vec4 vRGBA;
  void main() { if (vRGBA.a < 0.003) discard; gl_FragColor = vRGBA; }`;

function softMaterial(sharp: number): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    depthTest: false,
    blending: THREE.AdditiveBlending,
    uniforms: { uPx: { value: 1 }, uTime: { value: 0 }, uSharp: { value: sharp } },
    vertexShader: SOFT_VERTEX,
    fragmentShader: SOFT_FRAGMENT,
  });
}

/** One soft point cloud: positions and the per-point attributes the soft shader reads. */
function softCloud(n: number) {
  const a = {
    pos: new Float32Array(n * 3),
    col: new Float32Array(n * 3),
    size: new Float32Array(n),
    alpha: new Float32Array(n),
    phase: new Float32Array(n),
    twinkle: new Float32Array(n),
    spike: new Float32Array(n),
  };
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(a.pos, 3));
  geo.setAttribute("aColor", new THREE.BufferAttribute(a.col, 3));
  geo.setAttribute("aSize", new THREE.BufferAttribute(a.size, 1));
  geo.setAttribute("aAlpha", new THREE.BufferAttribute(a.alpha, 1));
  geo.setAttribute("aPhase", new THREE.BufferAttribute(a.phase, 1));
  geo.setAttribute("aTwinkle", new THREE.BufferAttribute(a.twinkle, 1));
  geo.setAttribute("aSpike", new THREE.BufferAttribute(a.spike, 1));
  geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e6);
  return { ...a, geo };
}

export function IntroOverlay({ mode, onDone }: { mode: "full" | "reduced"; onDone: () => void }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLDivElement>(null);
  const bloomRef = useRef<HTMLDivElement>(null);
  const rayHRef = useRef<HTMLDivElement>(null);
  const rayVRef = useRef<HTMLDivElement>(null);
  const starRef = useRef<SVGSVGElement>(null);
  const wordRef = useRef<HTMLSpanElement>(null);
  const taglineRef = useRef<HTMLParagraphElement>(null);
  const skipRef = useRef<HTMLButtonElement>(null);
  const doneRef = useRef(onDone);
  useEffect(() => {
    doneRef.current = onDone;
  }, [onDone]);

  useEffect(() => {
    const root = rootRef.current!;
    const host = hostRef.current!;
    const card = cardRef.current!;
    const title = titleRef.current!;
    const titleDot = title.querySelector<HTMLElement>("[data-wordmark-dot]")!;
    const bloomEl = bloomRef.current!;
    const rayH = rayHRef.current!;
    const rayV = rayVRef.current!;
    const star = starRef.current!;
    const starPath = star.firstElementChild as SVGPathElement;
    const word = wordRef.current!;
    const tagline = taglineRef.current!;
    const skipBtn = skipRef.current!;
    skipRef.current?.focus({ preventScroll: true });
    const full = mode === "full";
    const end = full ? END : RM_LIFT[1];
    const lift = full ? LIFT : RM_LIFT;

    let t = 0;
    let last = performance.now();
    let raf = 0;
    let finished = false;
    let skipping = -1; // ms of the skip fade so far, -1 when not skipping
    let disposeGl = () => {};
    let renderGl = () => {};
    let resizeGl = () => {};
    let eyeScreen = (): [number, number] => [window.innerWidth / 2, window.innerHeight / 2];

    if (full) {
      /* ---------------- three ---------------- */
      const phone = window.matchMedia("(max-width: 639px)").matches;
      const dpr = () => Math.min(window.devicePixelRatio || 1, phone ? 1.5 : 2);
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
      renderer.setPixelRatio(dpr());
      renderer.setClearColor(new THREE.Color(SPACE), 1);
      const canvas = renderer.domElement;
      canvas.setAttribute("aria-hidden", "true");
      canvas.style.display = "block";
      host.appendChild(canvas);
      const scene = new THREE.Scene();
      const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10);
      camera.position.z = 1;

      // The band.
      const skyMat = new THREE.ShaderMaterial({
        depthWrite: false,
        depthTest: false,
        uniforms: {
          uRes: { value: new THREE.Vector2(1, 1) },
          uFade: { value: 0 },
          uAngle: { value: 0 },
        },
        vertexShader: SKY_VERTEX,
        fragmentShader: SKY_FRAGMENT,
      });
      const skyGeo = new THREE.PlaneGeometry(2, 2);
      const skyMesh = new THREE.Mesh(skyGeo, skyMat);
      skyMesh.frustumCulled = false;
      skyMesh.renderOrder = 0;
      scene.add(skyMesh);

      // Background stars, most of them along the band; positions in units of screen height.
      const rand = seededRandom(0x6a1a);
      const gauss = () => {
        const u = Math.max(rand(), 1e-6);
        return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand());
      };
      const B = 420;
      const sky = softCloud(B);
      const skyXY = new Float32Array(B * 2);
      const skyBase = new Float32Array(B);
      const dir = [1 / Math.hypot(1, 0.55), 0.55 / Math.hypot(1, 0.55)];
      for (let i = 0; i < B; i++) {
        let x: number;
        let y: number;
        if (rand() < 0.68) {
          const along = (rand() - 0.5) * 2.6;
          const off = gauss() * 0.11;
          x = along * dir[0] - off * dir[1];
          y = along * dir[1] + off * dir[0];
        } else {
          x = (rand() - 0.5) * 2.4;
          y = rand() - 0.5;
        }
        skyXY[i * 2] = x;
        skyXY[i * 2 + 1] = y;
        const b = Math.pow(rand(), 3); // many faint, few bright
        sky.size[i] = 2.2 + b * 3.2;
        skyBase[i] = 0.16 + b * 0.5;
        sky.phase[i] = rand();
        sky.twinkle[i] = rand() < 0.3 ? 0.12 + rand() * 0.1 : 0; // a gentle shimmer on a few
        const warm = rand();
        sky.col.set(
          warm < 0.2 ? [1, 0.9, 0.78] : warm < 0.55 ? [0.78, 0.86, 1] : [0.92, 0.94, 1],
          i * 3,
        );
      }
      const skyMatPts = softMaterial(14);
      const skyPts = new THREE.Points(sky.geo, skyMatPts);
      skyPts.renderOrder = 1;
      scene.add(skyPts);

      // The constellation: lighting order (seeded shuffle) and per-star times.
      const N = POINTS.length;
      const order = Array.from({ length: N }, (_, i) => i);
      const shuffle = seededRandom(0xb0ff);
      for (let i = N - 1; i > 0; i--) {
        const j = Math.floor(shuffle() * (i + 1));
        [order[i], order[j]] = [order[j], order[i]];
      }
      const litAt = new Float32Array(N);
      order.forEach((s, k) => {
        litAt[s] = LIGHT[0] + (k * (LIGHT[1] - LIGHT[0])) / (N - 1);
      });

      // Edges: two quads each (soft glow + thin core), grown from the newer star.
      const E = EDGES.length;
      const ePos = new Float32Array(E * 8 * 3);
      const eCol = new Float32Array(E * 8 * 4);
      const eIdx: number[] = [];
      for (let q = 0; q < E * 2; q++) {
        const o = q * 4;
        eIdx.push(o, o + 1, o + 2, o + 2, o + 1, o + 3);
      }
      const eGeo = new THREE.BufferGeometry();
      eGeo.setAttribute(
        "position",
        new THREE.BufferAttribute(ePos, 3).setUsage(THREE.DynamicDrawUsage),
      );
      eGeo.setAttribute(
        "aRGBA",
        new THREE.BufferAttribute(eCol, 4).setUsage(THREE.DynamicDrawUsage),
      );
      eGeo.setIndex(eIdx);
      eGeo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e6);
      const eMat = new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
        vertexShader: EDGE_VERTEX,
        fragmentShader: EDGE_FRAGMENT,
      });
      const edgeMesh = new THREE.Mesh(eGeo, eMat);
      edgeMesh.renderOrder = 2;
      scene.add(edgeMesh);

      // Halos and flares behind each star.
      const halo = softCloud(N);
      for (let i = 0; i < N; i++) {
        halo.col.set(CYAN, i * 3);
        halo.phase[i] = shuffle();
        halo.twinkle[i] = 0; // steady: no flicker
      }
      const haloMat = softMaterial(5);
      const haloPts = new THREE.Points(halo.geo, haloMat);
      haloPts.renderOrder = 3;
      scene.add(haloPts);

      // The stars themselves: the map's point sprite, twinkling with its heartbeat.
      const sPos = new Float32Array(N * 3);
      const sCol = new Float32Array(N * 3);
      const sSize = new Float32Array(N);
      const sAlpha = new Float32Array(N);
      const sBoost = new Float32Array(N);
      const sPulse = new Float32Array(N); // no heartbeat
      const sPhase = new Float32Array(N);
      for (let i = 0; i < N; i++) {
        sCol.set(STAR, i * 3);
        sPhase[i] = shuffle() * 6.28;
        sSize[i] = i === EYE ? 6.5 : 4 + shuffle() * 2;
      }
      const sGeo = new THREE.BufferGeometry();
      sGeo.setAttribute("position", new THREE.BufferAttribute(sPos, 3));
      sGeo.setAttribute("aColor", new THREE.BufferAttribute(sCol, 3));
      sGeo.setAttribute("aSize", new THREE.BufferAttribute(sSize, 1));
      sGeo.setAttribute("aAlpha", new THREE.BufferAttribute(sAlpha, 1));
      sGeo.setAttribute("aRing", new THREE.BufferAttribute(new Float32Array(N), 1));
      sGeo.setAttribute("aHub", new THREE.BufferAttribute(new Float32Array(N), 1));
      sGeo.setAttribute("aPhase", new THREE.BufferAttribute(sPhase, 1));
      sGeo.setAttribute("aBoost", new THREE.BufferAttribute(sBoost, 1));
      sGeo.setAttribute("aPulse", new THREE.BufferAttribute(sPulse, 1));
      sGeo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e6);
      const sMat = createPointMaterial(0);
      const stars = new THREE.Points(sGeo, sMat);
      stars.renderOrder = 4;
      scene.add(stars);

      /* ---------------- layout ---------------- */
      let w = 1;
      let h = 1;
      const starXY = new Float32Array(N * 2); // world px, origin at screen centre, y up
      resizeGl = () => {
        w = Math.max(1, window.innerWidth);
        h = Math.max(1, window.innerHeight);
        const ratio = dpr();
        renderer.setPixelRatio(ratio);
        renderer.setSize(w, h, false);
        canvas.style.width = `${w}px`;
        canvas.style.height = `${h}px`;
        camera.left = -w / 2;
        camera.right = w / 2;
        camera.top = h / 2;
        camera.bottom = -h / 2;
        camera.updateProjectionMatrix();
        (skyMat.uniforms.uRes.value as THREE.Vector2).set(w * ratio, h * ratio);
        for (const m of [sMat, skyMatPts, haloMat]) m.uniforms.uPx.value = ratio;
        const bw = Math.min(w * (w < 640 ? 0.9 : 0.72), h * 0.62 * ASPECT, 980);
        const bh = bw / ASPECT;
        for (let i = 0; i < N; i++) {
          const x = (POINTS[i][0] - 0.5) * bw;
          const y = (0.5 - POINTS[i][1]) * bh + h * 0.02;
          starXY[i * 2] = x;
          starXY[i * 2 + 1] = y;
          sPos.set([x, y, 0], i * 3);
          halo.pos.set([x, y, 0], i * 3);
        }
        sGeo.attributes.position.needsUpdate = true;
        halo.geo.attributes.position.needsUpdate = true;
        for (let i = 0; i < B; i++) {
          sky.pos[i * 3] = skyXY[i * 2] * h;
          sky.pos[i * 3 + 1] = skyXY[i * 2 + 1] * h;
        }
        sky.geo.attributes.position.needsUpdate = true;
      };
      eyeScreen = () => [w / 2 + starXY[EYE * 2], h / 2 - starXY[EYE * 2 + 1]];

      const quad = (
        q: number,
        ax: number,
        ay: number,
        bx: number,
        by: number,
        half: number,
        rgba: number[],
      ) => {
        const dx = bx - ax;
        const dy = by - ay;
        const len = Math.hypot(dx, dy) || 1;
        const nx = (-dy / len) * half;
        const ny = (dx / len) * half;
        ePos.set(
          [ax + nx, ay + ny, 0, ax - nx, ay - ny, 0, bx + nx, by + ny, 0, bx - nx, by - ny, 0],
          q * 12,
        );
        for (let v = 0; v < 4; v++) eCol.set(rgba, q * 16 + v * 4);
      };

      renderGl = () => {
        const time = t / 1000;
        for (const m of [sMat, skyMatPts, haloMat]) m.uniforms.uTime.value = time;
        const skyIn = easeOut(span(t, SKY_IN));
        const bloom = easeInOut(span(t, BLOOM));
        const swell = easeInOut(span(t, SWELL));
        const rest = 1 - bloom;
        skyMat.uniforms.uFade.value = skyIn;
        for (let i = 0; i < B; i++) sky.alpha[i] = skyBase[i] * skyIn * (1 - 0.6 * bloom);
        skyPts.rotation.z = time * DRIFT;
        skyMat.uniforms.uAngle.value = -time * DRIFT;
        sky.geo.attributes.aAlpha.needsUpdate = true;

        // Each star fades and brightens in, then holds a steady glow. In the bloom the eye's
        // rays lengthen and its halo swells while the rest of the scene fades.
        for (let i = 0; i < N; i++) {
          const on = easeInOut(clamp01((t - litAt[i]) / FADE_IN_MS));
          const k = i === EYE ? 1 : rest;
          sAlpha[i] = on * k;
          const eye = i === EYE;
          sBoost[i] = eye ? 1.2 * swell + 1.3 * bloom : 0;
          halo.size[i] = on * (24 + (eye ? 40 * swell + 160 * bloom : 0));
          halo.alpha[i] = on * (0.38 + (eye ? 0.32 * swell + 0.3 * bloom : 0)) * k;
          halo.spike[i] = on * (0.32 + (eye ? 0.33 * swell + 0.35 * bloom : 0));
        }
        sGeo.attributes.aAlpha.needsUpdate = true;
        sGeo.attributes.aBoost.needsUpdate = true;
        for (const k of ["aSize", "aAlpha", "aSpike"]) halo.geo.attributes[k].needsUpdate = true;

        for (let k = 0; k < E; k++) {
          const [a, b] = EDGES[k];
          const from = litAt[a] > litAt[b] ? a : b;
          const to = from === a ? b : a;
          const p = easeOut(clamp01((t - litAt[from]) / EDGE_MS));
          const ax = starXY[from * 2];
          const ay = starXY[from * 2 + 1];
          const bx = ax + (starXY[to * 2] - ax) * p;
          const by = ay + (starXY[to * 2 + 1] - ay) * p;
          const al = p > 0 ? rest : 0;
          quad(k * 2, ax, ay, bx, by, 2.2, [CYAN[0], CYAN[1], CYAN[2], 0.09 * al]);
          quad(k * 2 + 1, ax, ay, bx, by, 0.55, [CYAN[0], CYAN[1], CYAN[2], 0.72 * al]);
        }
        eGeo.attributes.position.needsUpdate = true;
        eGeo.attributes.aRGBA.needsUpdate = true;

        if (t < CARD_IN[1]) renderer.render(scene, camera);
      };

      disposeGl = () => {
        for (const g of [skyGeo, sky.geo, eGeo, halo.geo, sGeo]) g.dispose();
        for (const m of [skyMat, skyMatPts, eMat, haloMat, sMat]) m.dispose();
        renderer.dispose();
        canvas.remove();
      };
    }

    /* ---------------- DOM layers: the bloom, the card, the title, the small star ---------------- */
    // The header wordmark's glyphs: the title flies there and hands over to it.
    const headerMark = () =>
      document.querySelector<HTMLElement>("header [data-wordmark-dot]")?.parentElement
        ?.parentElement ?? null;
    let titleRect: DOMRect | null = null;
    const resize = () => {
      resizeGl();
      titleRect = null;
    };
    const render = () => {
      const W = window.innerWidth;
      const H = window.innerHeight;
      if (full) {
        renderGl();
        // The light travels on a smooth eased path from the buffalo's star to the dot of the i.
        const dr = titleDot.getBoundingClientRect();
        const dx = dr.left + dr.width / 2;
        const dy = dr.top + dr.height / 2;
        const [sx, sy] = eyeScreen();
        const tp = easeInOut(span(t, TRAVEL));
        const ex = sx + (dx - sx) * tp;
        const ey = sy + (dy - sy) * tp;
        const cover = Math.hypot(Math.max(ex, W - ex), Math.max(ey, H - ey));

        // The bloom: a smooth radial light with four rays, swelling from the eye star.
        const b = span(t, BLOOM);
        const be = easeInOut(b);
        const r = 20 + cover * 2.3 * be;
        bloomEl.style.opacity = String(b > 0 ? clamp01(b * 4) : 0);
        bloomEl.style.width = `${r * 2}px`;
        bloomEl.style.height = `${r * 2}px`;
        bloomEl.style.transform = `translate(${ex - r}px, ${ey - r}px)`;
        const len = 60 + Math.max(W, H) * 2.4 * be;
        const thick = 2 + 10 * be;
        const rayOp =
          b > 0 ? clamp01(b * 3) * (1 - span(t, [CARD_IN[1] - 150, CARD_IN[1] + 200])) : 0;
        for (const [el, horiz] of [
          [rayH, true],
          [rayV, false],
        ] as const) {
          el.style.opacity = String(rayOp);
          el.style.width = `${horiz ? len : thick}px`;
          el.style.height = `${horiz ? thick : len}px`;
          el.style.transform = horiz
            ? `translate(${ex - len / 2}px, ${ey - thick / 2}px)`
            : `translate(${ex - thick / 2}px, ${ey - len / 2}px)`;
        }
        const cardIn = easeInOut(span(t, CARD_IN));
        card.style.opacity = String(cardIn);
        if (cardIn >= 1) {
          host.style.display = "none"; // the night is gone; the dashboard shows when the card lifts
          bloomEl.style.display = "none";
          root.style.background = "transparent";
        }

        // The small star: it appears in the light, on the same path, and contracts into the dot.
        const dotSize = Math.max(dr.width, dr.height, 2);
        const c = easeInOut(span(t, CONTRACT));
        const swap = span(t, DOT_SWAP);
        const arm = 36 + (dotSize * 1.9 - 36) * c;
        const cx = ex;
        const cy = ey;
        star.style.opacity =
          t >= CONTRACT[0] ? String(clamp01(span(t, CONTRACT) * 4) * (1 - swap)) : "0";
        star.style.width = `${(arm * 48) / 18}px`;
        star.style.height = `${(arm * 48) / 18}px`;
        star.style.transform = `translate(${cx - (arm * 24) / 18}px, ${cy - (arm * 24) / 18}px)`;
        starPath.style.fill = `color-mix(in srgb, var(--ink) ${Math.round(40 + 60 * c)}%, var(--paper))`;
        title.style.opacity = String(easeInOut(span(t, TITLE_IN)));
        titleDot.style.opacity = String(swap);
      } else {
        card.style.opacity = "1";
        title.style.opacity = "1";
        titleDot.style.opacity = "1";
        root.style.background = "transparent";
      }

      // The lift: the card goes up; the title flies into the header wordmark (FLIP).
      const lp = easeInOut(span(t, lift));
      card.style.transform = `translateY(${-100 * lp}%)`;
      tagline.style.transform = `translateY(${-H * lp}px)`;
      skipBtn.style.opacity = String(1 - lp);
      if (lp <= 0 || !titleRect) {
        word.style.transform = "";
        titleRect = word.getBoundingClientRect();
      }
      const hm = headerMark();
      if (lp > 0 && hm && titleRect) {
        const hr = hm.getBoundingClientRect();
        const sc = hr.width / titleRect.width;
        const tx = hr.left - titleRect.left;
        const ty = hr.top + hr.height / 2 - (titleRect.top + (titleRect.height * sc) / 2);
        const k = 1 + (sc - 1) * lp;
        word.style.transform = `translate(${tx * lp}px, ${ty * lp}px) scale(${k})`;
        const hand = span(lp, [0.72, 1]);
        word.style.opacity = String(1 - hand);
        hm.style.opacity = String(hand);
      } else if (hm && t > 0) hm.style.opacity = "0";
    };

    const restoreHeader = () => {
      const hm = headerMark();
      if (hm) hm.style.opacity = "";
    };
    const finish = () => {
      if (finished) return;
      finished = true;
      restoreHeader();
      const input = document.querySelector<HTMLInputElement>('#main [role="search"] input');
      input?.focus({ preventScroll: true });
      doneRef.current();
    };

    const frame = (now: number) => {
      raf = 0;
      const dt = Math.min(now - last, 50); // a hidden tab pauses the intro instead of skipping it
      last = now;
      if (skipping >= 0) {
        skipping += dt;
        root.style.opacity = String(1 - clamp01(skipping / SKIP_FADE_MS));
        if (skipping >= SKIP_FADE_MS) return finish();
      } else {
        const ended = t >= end;
        t = Math.min(t + dt, end);
        render();
        if (ended) return finish();
      }
      raf = requestAnimationFrame(frame);
    };

    const skip = () => {
      if (skipping >= 0 || finished) return;
      skipping = 0;
      restoreHeader();
      root.style.pointerEvents = "none";
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") skip();
    };
    root.addEventListener("click", skip);
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", resize);
    resize();
    render();
    raf = requestAnimationFrame(frame);

    return () => {
      if (raf) cancelAnimationFrame(raf);
      root.removeEventListener("click", skip);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", resize);
      disposeGl();
      restoreHeader();
    };
  }, [mode]);

  return (
    <div
      ref={rootRef}
      className="fixed inset-0 cursor-pointer overflow-hidden"
      style={{ zIndex: 1000, background: mode === "full" ? SPACE : "transparent" }}
    >
      <div ref={hostRef} className="absolute inset-0" aria-hidden="true" />
      <div
        ref={bloomRef}
        className="pointer-events-none absolute top-0 left-0 rounded-full"
        style={{
          opacity: 0,
          background:
            "radial-gradient(circle closest-side, var(--paper-2) 0%, var(--paper-2) 34%, color-mix(in srgb, var(--paper-2) 55%, transparent) 62%, transparent 100%)",
        }}
        aria-hidden="true"
      />
      <div
        ref={cardRef}
        className="absolute inset-0"
        style={{ background: "var(--paper-2)", opacity: 0 }}
        aria-hidden="true"
      />
      <div
        ref={rayHRef}
        className="pointer-events-none absolute top-0 left-0 rounded-full"
        style={{
          opacity: 0,
          background:
            "radial-gradient(closest-side, var(--paper), color-mix(in srgb, var(--paper) 35%, transparent) 55%, transparent)",
        }}
        aria-hidden="true"
      />
      <div
        ref={rayVRef}
        className="pointer-events-none absolute top-0 left-0 rounded-full"
        style={{
          opacity: 0,
          background:
            "radial-gradient(closest-side, var(--paper), color-mix(in srgb, var(--paper) 35%, transparent) 55%, transparent)",
        }}
        aria-hidden="true"
      />
      <div
        ref={titleRef}
        className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center px-4 text-center"
        style={{ opacity: 0, fontFamily: '"Cormorant Garamond", Georgia, serif' }}
        aria-hidden="true"
      >
        <span
          ref={wordRef}
          style={{
            display: "inline-block",
            transformOrigin: "0 0",
            color: "var(--ink)",
            fontSize: "clamp(64px, 14vw, 112px)",
            fontWeight: 400,
            lineHeight: 1,
            letterSpacing: "0.03em",
          }}
        >
          <Wordmark className="" dotStyle={{ background: "var(--ink)", opacity: 0 }} />
        </span>
        <p
          ref={taglineRef}
          style={{
            margin: "0.9em 0 0",
            fontStyle: "italic",
            color: "var(--ink-3)",
            fontSize: "clamp(17px, 2.4vw, 22px)",
          }}
        >
          {TAGLINE}
        </p>
      </div>
      <svg
        ref={starRef}
        className="pointer-events-none absolute top-0 left-0"
        viewBox="0 0 48 48"
        style={{ opacity: 0, overflow: "visible" }}
        aria-hidden="true"
      >
        <path d={STAR_PATH} />
      </svg>
      <button ref={skipRef} type="button" className="btn-flat night absolute right-4 bottom-4">
        Skip
      </button>
    </div>
  );
}

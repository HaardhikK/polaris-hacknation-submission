// The map's dot: one shader-drawn point sprite (a clean disc with a soft edge, an optional hub
// rim, a progress ring and a heartbeat pulse). Shared by the graph canvas and the intro so both
// draw the same star. Attributes: position, aColor, aSize, aAlpha, aRing, aHub, aPhase, aBoost,
// aPulse. Uniforms: uPx (size scale), uTime (seconds), uMotion (0 under reduced motion).
import * as THREE from "three";

export const POINT_VERTEX = /* glsl */ `
  attribute vec3 aColor;
  attribute float aSize, aAlpha, aRing, aHub, aPhase, aBoost, aPulse;
  uniform float uPx, uTime, uMotion;
  varying vec3 vColor;
  varying float vAlpha, vRing, vHub, vBeat;
  void main() {
    vColor = aColor;
    vAlpha = aAlpha;
    vRing = aRing;
    vHub = aHub;
    // Heartbeat: satellites pulse in size and brightness, hubs only breathe.
    float beat = sin(uTime * 2.2 + aPhase);
    beat = beat * beat * beat;
    vBeat = beat * uMotion * aPulse;
    float grow = 1.0 + (aHub > 0.5 ? 0.03 : 0.16) * vBeat + 0.22 * aBoost;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float px = clamp(aSize * grow * uPx / max(-mv.z, 1.0), 4.0, 72.0);
    // Room for the ring: a thin stroke slightly larger than the disc.
    gl_PointSize = px * 1.5;
    gl_Position = projectionMatrix * mv;
  }`;

export const POINT_FRAGMENT = /* glsl */ `
  precision highp float;
  varying vec3 vColor;
  varying float vAlpha, vRing, vHub, vBeat;
  void main() {
    vec2 p = 2.0 * gl_PointCoord - 1.0;
    float r = length(p);
    float discR = 1.0 / 1.5;
    float aa = max(fwidth(r), 0.01) * 1.5;
    // The disc: a clean circle with a soft edge.
    float disc = 1.0 - smoothstep(discR - aa, discR + aa * 0.4, r);
    // Hubs get a thin darker rim just inside the edge.
    float rim = vHub * smoothstep(discR - 0.1 - aa, discR - 0.1, r) * disc;
    // The ring: an arc that sweeps clockwise from the top as vRing goes 0 -> 1.
    float frac = fract(atan(p.x, -p.y) / 6.2831853 + 1.0);
    float band = abs(r - 0.88) - 0.05;
    float ring = (1.0 - smoothstep(0.0, aa, band)) * step(frac, vRing) * step(0.001, vRing);
    float alpha = max(disc, ring);
    if (alpha < 0.004) discard;
    vec3 col = mix(vColor, vec3(1.0), 0.18 * max(vBeat, 0.0));
    col = mix(col, vColor * 0.62, rim);
    col = mix(col, vColor * 0.55, ring * (1.0 - disc));
    gl_FragColor = vec4(col, alpha * vAlpha);
  }`;

/** The map's point material: transparent, no depth, the three uniforms above. */
export function createPointMaterial(motion: number): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    depthTest: false,
    uniforms: { uPx: { value: 1 }, uTime: { value: 0 }, uMotion: { value: motion } },
    vertexShader: POINT_VERTEX,
    fragmentShader: POINT_FRAGMENT,
  });
}

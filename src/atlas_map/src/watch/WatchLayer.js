import * as THREE from "three";
import { toX, toZ } from "../scene/geo.js";
import { beamFrag } from "../scene/EvidenceLayer.js";
import { riseAt, sinkAt, spikeHeight } from "../scene/evidenceMath.js";
import { PROBLEM, WATCH_LABEL } from "./watch.js";

// The Watcher view in the scene: glowing beams rising from the seafloor at each site with a sensor not recording well,
// as an Ask Atlas answer's evidence rises. A site gets one beam for each problem among its sensors, side by side, so a
// site with one sensor under Navy diversion and another not recording shows a purple beam and a red one; the taller the
// worse (red, purple, yellow). Each beam's tag counts its sensors; a beam opens its site. Beams rise one after another
// when the view turns on and sink together when it turns off.

// Purple for the diversion: blue is the Water properties family's colour.
export const COLORS = { no_data: "#d03b3b", diverted: "#a56ee8", gaps: "#e0b13a" };
const HEIGHT = { no_data: 1, diverted: 0.82, gaps: 0.66 };
const SPACING = 11;   // px between a site's beams
const ORDER = 29;     // drawn just under the evidence's beams

// The beams: one per site and problem, worst first at a site; k and of place it among the site's beams.
export function watchBeams(sites, states) {
  const beams = [];
  for (const site of sites) {
    const byState = {};
    for (const id of site.sensorIds) {
      const st = states[id]?.state;
      if (PROBLEM.includes(st)) (byState[st] ||= []).push(id);
    }
    const here = PROBLEM.filter(p => byState[p]);
    here.forEach((state, k) => beams.push({ key: `${site.id}:${state}`, site, state, ids: byState[state], k, of: here.length }));
  }
  return beams;
}

// The evidence beam's vertex shader with a sideways offset in pixels, so a site's beams stand side by side.
const beamVert = `
  attribute vec2 corner;
  uniform vec3 uBase; uniform float uHeight, uWidth, uOff; uniform vec2 uRes;
  varying vec2 vC;
  void main() {
    vec4 b = projectionMatrix * viewMatrix * vec4(uBase, 1.0);
    vec4 t = projectionMatrix * viewMatrix * vec4(uBase + vec3(0.0, uHeight, 0.0), 1.0);
    vec2 d = (t.xy / t.w - b.xy / b.w) * uRes;
    float len = length(d);
    vec2 dir = len > 1e-3 ? d / len : vec2(0.0, 1.0);
    vec2 side = vec2(-dir.y, dir.x);
    vec4 p = mix(b, t, corner.y);
    p.xy += side * (corner.x * uWidth + uOff * 2.0) / uRes * p.w;
    gl_Position = p; vC = corner;
  }`;
const additive = { transparent: true, depthTest: false, depthWrite: false, blending: THREE.AdditiveBlending };

export class WatchLayer {
  // handlers: onSite(site)
  constructor(container, scene, handlers = {}) {
    this.c = container; this.sc = scene; this.h = handlers;
    this.sets = []; this.key = "";
    this._geo = new THREE.BufferGeometry();
    this._geo.setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(12), 3));
    this._geo.setAttribute("corner", new THREE.Float32BufferAttribute([-1, 0, 1, 0, -1, 1, 1, 1], 2));
    this._geo.setIndex([0, 1, 2, 2, 1, 3]);
  }

  // The beams to show (null or [] clears). The same beams again change nothing; others sink, then the new rise.
  show(beams, names = {}) {
    const key = (beams || []).map(b => `${b.key}:${b.ids.length}`).join("|");
    if (key === this.key) return;
    this.key = key;
    const now = performance.now();
    let wait = 0;
    for (const s of this.sets) if (!s.sinkT0) { s.sinkT0 = now; if (s.beams.length) wait = this.sc.reducedMotion ? 0 : 300; }
    if (beams?.length) this.sets.push({ t0: now + wait, beams: beams.map((b, i) => this._beam(b, i, names)) });
  }

  _beam(b, i, names) {
    const color = COLORS[b.state];
    const mat = new THREE.ShaderMaterial({ vertexShader: beamVert, fragmentShader: beamFrag, ...additive, side: THREE.DoubleSide,
      uniforms: { uBase: { value: new THREE.Vector3() }, uHeight: { value: 0 }, uWidth: { value: 22 }, uOff: { value: 0 },
                  uRes: { value: new THREE.Vector2(innerWidth, innerHeight) }, uColor: { value: new THREE.Color(color) },
                  uGlow: { value: 1 }, uAlpha: { value: 1 } } });
    const mesh = new THREE.Mesh(this._geo, mat);
    mesh.frustumCulled = false; mesh.renderOrder = ORDER; this.sc.scene.add(mesh);
    const tag = document.createElement("div");
    tag.className = "ev-tag watch-tag";
    tag.style.setProperty("--c", color);
    const list = b.ids.map(id => names[id] || id);
    const count = document.createElement("span");
    count.textContent = String(b.ids.length);
    tag.appendChild(count);
    tag.title = `${b.site.label} · ${WATCH_LABEL[b.state]}: ${list.slice(0, 8).join("; ")}${list.length > 8 ? ` +${list.length - 8}` : ""}`;
    tag.setAttribute("role", "button");
    tag.setAttribute("aria-label", tag.title);
    tag.addEventListener("click", ev => { ev.stopPropagation(); this.h.onSite?.(b.site); });
    this.c.appendChild(tag);
    return { ...b, i, mesh, mat, tag };
  }

  update(now = performance.now()) {
    const sc = this.sc, reduced = sc.reducedMotion, e = sc.e, dist = sc.frame?.dist ?? 50;
    for (const set of [...this.sets]) {
      const sinking = set.sinkT0 != null, sink = sinking ? sinkAt(now - set.sinkT0, reduced) : 1;
      if (sinking && sink <= 0) { this._dispose(set); continue; }
      for (const b of set.beams) {
        const rise = (sinking ? sink : riseAt(now - set.t0, b.i, reduced)) || 0;
        const x = toX(b.site.lon), z = toZ(b.site.lat), y = Math.min(0, sc.elevAt(b.site.lon, b.site.lat)) * e;
        const h = spikeHeight(dist) * HEIGHT[b.state] * rise, off = (b.k - (b.of - 1) / 2) * SPACING;
        const u = b.mat.uniforms;
        u.uBase.value.set(x, y, z); u.uHeight.value = h; u.uOff.value = off; u.uRes.value.set(innerWidth, innerHeight);
        u.uAlpha.value = sinking ? sink : Math.min(1, rise * 3);
        const [, , bz] = sc.project(x, y, z), [tx, ty] = sc.project(x, y + h, z);
        const front = bz < 1;
        b.mesh.visible = front && rise > 0.001;
        const shown = front && rise > 0.3;
        b.tag.style.transform = `translate(${(tx + off).toFixed(1)}px, ${ty.toFixed(1)}px)`;
        b.tag.style.opacity = shown ? 1 : 0;
        b.tag.style.pointerEvents = shown ? "auto" : "none";
      }
    }
  }

  // For the browser tests: each beam's site, state, count and height.
  snapshot() {
    const cur = this.sets.find(s => !s.sinkT0);
    return (cur?.beams || []).map(b => ({ site: b.site.id, state: b.state, n: b.ids.length, height: b.mat.uniforms.uHeight.value }));
  }

  _dispose(set) {
    for (const b of set.beams) { this.sc.scene.remove(b.mesh); b.mat.dispose(); b.tag.remove(); }
    this.sets = this.sets.filter(s => s !== set);
  }

  dispose() { for (const s of [...this.sets]) this._dispose(s); this._geo.dispose(); }
}

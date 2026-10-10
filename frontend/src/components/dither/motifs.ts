// Procedural 1-bit pictures of the mill, one per part of it (Dither Ledger "BayerEmblem" idea):
// each motif fills a w×h density field (0..1) plus an ember-accent mask, and the Bayer pass in
// DitherPlate turns density into dots. Pure arithmetic, no data: same motif + seed, same picture.
// A motif with a moving part (smoke, shuttle, gears...) leaves it out when `live` is set, and
// LIVE draws just that part each frame on a second canvas, so the still picture is painted once.

import { mulberry32 } from "@/lib/bayer";

// cov marks cells that hide whatever is drawn underneath (paper fill), for overlays
export type Field = { val: Float32Array; acc: Uint8Array; w: number; h: number; cov?: Uint8Array };
type Rnd = () => number;
export type MotifName = "loom" | "cones" | "rolls" | "loupe" | "orders" | "bars" | "mill" | "gear" | "spool" | "truck" | "everest";

const clamp = (x: number, a = 0, b = 1) => Math.min(b, Math.max(a, x));

function field(w: number, h: number): Field {
  return { val: new Float32Array(w * h), acc: new Uint8Array(w * h), w, h };
}

function put(f: Field, x: number, y: number, v: number, accent = false) {
  const xi = Math.round(x);
  const yi = Math.round(y);
  if (xi < 0 || yi < 0 || xi >= f.w || yi >= f.h) return;
  const i = yi * f.w + xi;
  f.val[i] = v;
  f.acc[i] = accent ? 1 : 0;
}

function line(f: Field, x0: number, y0: number, x1: number, y1: number, v: number, accent = false, thick = 1) {
  const n = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0)));
  for (let s = 0; s <= n; s++) {
    const x = x0 + ((x1 - x0) * s) / n;
    const y = y0 + ((y1 - y0) * s) / n;
    for (let t = 0; t < thick; t++) put(f, x, y + t, v, accent);
  }
}

/** filled box; shade gets the box's own 0..1 coords */
function box(f: Field, x0: number, y0: number, x1: number, y1: number, shade: (u: number, v: number, x: number, y: number) => number, accent?: (u: number, v: number) => boolean) {
  const xa = Math.max(0, Math.round(x0));
  const xb = Math.min(f.w, Math.round(x1));
  const ya = Math.max(0, Math.round(y0));
  const yb = Math.min(f.h, Math.round(y1));
  for (let y = ya; y < yb; y++) {
    for (let x = xa; x < xb; x++) {
      const u = (x - x0) / Math.max(1, x1 - x0);
      const v = (y - y0) / Math.max(1, y1 - y0);
      f.val[y * f.w + x] = clamp(shade(u, v, x, y));
      f.acc[y * f.w + x] = accent?.(u, v) ? 1 : 0;
    }
  }
}

/** filled disc; shade gets (dx, dy) in -1..1 and the distance 0..1 */
function disc(f: Field, cx: number, cy: number, r: number, shade: (dx: number, dy: number, d: number) => number, accent?: (dx: number, dy: number, d: number) => boolean) {
  for (let y = Math.floor(cy - r); y <= Math.ceil(cy + r); y++) {
    for (let x = Math.floor(cx - r); x <= Math.ceil(cx + r); x++) {
      const dx = (x - cx) / r;
      const dy = (y - cy) / r;
      const d = Math.hypot(dx, dy);
      if (d > 1) continue;
      put(f, x, y, clamp(shade(dx, dy, d)), accent?.(dx, dy, d));
    }
  }
}

/** engineering paper: a dot every `step` cells, on the Bayer zero threshold so each prints */
function paper(f: Field, step = 8) {
  for (let y = 0; y < f.h; y += step) for (let x = 0; x < f.w; x += step) if (!f.val[y * f.w + x]) f.val[y * f.w + x] = 0.5;
}

/** the composition box: the largest 16:10 area that fits, centred */
function frame(w: number, h: number) {
  const U = Math.min(h, w / 1.6);
  const ox = (w - 1.6 * U) / 2;
  const oy = (h - U) / 2;
  return { U, X: (a: number) => ox + a * 1.6 * U, Y: (b: number) => oy + b * U };
}

const cyl = (u: number) => 0.18 + 0.72 * Math.sin(Math.PI * clamp(u)); // a round thing lit from the front

// shuttle: a pointed boat riding in the shed
function shuttle(f: Field, sx: number) {
  const { U, Y } = frame(f.w, f.h);
  const sw = U * 0.16;
  for (let y = Y(0.465); y < Y(0.505); y++) {
    const t = (y - Y(0.465)) / (Y(0.505) - Y(0.465));
    const half = sw * (0.55 + 0.45 * Math.sin(Math.PI * t));
    line(f, sx - half, y, sx + half, y, 1, true);
  }
}

// ── a loom: warp beam, warp threads through the heddles, the shed with the shuttle in it,
//    woven cloth below the fell and the cloth beam rolling it up
const loom = (w: number, h: number, rnd: Rnd, live = false): Field => {
  const f = field(w, h);
  paper(f);
  const { U, X, Y } = frame(w, h);
  const post = Math.max(2, U * 0.035);
  box(f, X(0.06), Y(0.04), X(0.06) + post, Y(0.97), () => 0.85);
  box(f, X(0.94) - post, Y(0.04), X(0.94), Y(0.97), () => 0.85);
  box(f, X(0.06), Y(0.06), X(0.94), Y(0.16), (_, v) => cyl(v));
  const step = Math.max(3, Math.round(U * 0.028));
  const shuttleX = 0.25 + rnd() * 0.45;
  let k = 0;
  for (let x = X(0.11); x < X(0.89); x += step, k++) {
    const odd = k % 2 === 1;
    line(f, x, Y(0.16), x, Y(0.4), 0.62);
    // the shed: odd threads lift, even threads drop, opening a diamond for the shuttle
    line(f, x, Y(0.4), x, odd ? Y(0.45) : Y(0.51), 0.62);
    line(f, x, odd ? Y(0.45) : Y(0.51), x, Y(0.58), 0.62);
  }
  box(f, X(0.08), Y(0.33), X(0.92), Y(0.35), () => 0.95); // heddle bar
  if (!live) shuttle(f, X(shuttleX));
  // woven cloth: a 2/2 twill below the fell, the newest pick drawn in ember
  box(f, X(0.11), Y(0.58), X(0.89), Y(0.82), (_, __, x, y) => ((x + y) % 4 < 2 ? 0.78 : 0.3));
  line(f, X(0.11), Y(0.58), X(0.89), Y(0.58), 1, true, 2);
  box(f, X(0.08), Y(0.83), X(0.92), Y(0.95), (_, v) => cyl(v));
  return f;
};

// the yarn climbs off the cone tip and drifts right; `sway` ripples it along its length
function thread(f: Field, x0: number, y0: number, sway: number) {
  const { U, X } = frame(f.w, f.h);
  for (let s = 0; s <= 160; s++) {
    const t = s / 160;
    put(f, x0 + t * (X(0.98) - x0), y0 - Math.sin(t * Math.PI) * U * 0.14 + t * U * 0.05 + Math.sin(t * 9 - sway) * U * 0.02 * t, 1, true);
  }
}

// ── yarn cones on the store shelf, wound in bands; one cone feeds a thread out to the right
const cones = (w: number, h: number, rnd: Rnd, live = false): Field => {
  const f = field(w, h);
  paper(f);
  const { U, X, Y } = frame(w, h);
  const n = 5;
  const lead = Math.floor(rnd() * n);
  for (let i = 0; i < n; i++) {
    const cx = X(0.12 + (i * 0.76) / (n - 1));
    const tall = U * (0.52 + 0.18 * rnd());
    const base = Y(0.86);
    const top = base - tall;
    const bw = U * 0.15;
    const tw = U * 0.055;
    const accentCone = i === lead;
    for (let y = Math.round(top); y < base; y++) {
      const t = (y - top) / tall;
      const half = tw + (bw - tw) * t;
      for (let x = Math.round(cx - half); x <= cx + half; x++) {
        const u = (x - (cx - half)) / (2 * half);
        const band = 0.82 + 0.18 * Math.sin(y * 0.9 + u * 3);
        put(f, x, y, cyl(u) * band, accentCone && Math.sin(y * 0.9) > 0.55);
      }
    }
    box(f, cx - tw * 0.55, top - U * 0.06, cx + tw * 0.55, top, () => 0.95); // the paper tube
    if (accentCone && !live) thread(f, cx, top - U * 0.06, 0);
  }
  box(f, X(0.02), Y(0.86), X(0.98), Y(0.9), () => 0.9);
  return f;
};

// ── finished rolls stacked end-on, the layers of cloth as rings; one carries its ember label
const rolls = (w: number, h: number, rnd: Rnd, live = false): Field => {
  const f = field(w, h);
  paper(f);
  const { U, X, Y } = frame(w, h);
  const r = U * 0.15;
  const rows = [4, 3, 2];
  const tagged = Math.floor(rnd() * 9);
  let k = 0;
  rows.forEach((count, row) => {
    for (let i = 0; i < count; i++, k++) {
      const cx = X(0.5) + (i - (count - 1) / 2) * r * 2.05;
      const cy = Y(0.88) - r - row * r * 1.78;
      const tag = k === tagged;
      disc(f, cx, cy, r, (dx, dy, d) => {
        if (d < 0.2) return 1; // the cardboard core
        const ring = 0.5 + 0.5 * Math.sin(d * 26);
        const light = 0.55 - 0.3 * (dx * -0.6 + dy * -0.6);
        return d > 0.92 ? 0.95 : 0.2 + ring * 0.25 + light * 0.35;
      }, (_, __, d) => tag && d > 0.2 && d < 0.32);
      if (tag) box(f, cx + r * 0.3, cy - r * 1.05, cx + r * 1.1, cy - r * 0.7, () => 1, () => true);
    }
  });
  box(f, X(0.02), Y(0.88), X(0.98), Y(0.91), () => 0.9);
  return f;
};

// ── the QC loupe over the cloth: the weave is magnified inside the lens, and one broken pick shows
const loupe = (w: number, h: number, rnd: Rnd, live = false): Field => {
  const f = field(w, h);
  const { U, X, Y } = frame(w, h);
  box(f, 0, 0, w, h, (u, _, x, y) => (((x >> 1) + (y >> 1)) % 4 < 2 ? 0.2 : 0.06) * (0.4 + u * 0.6));
  const cx = X(0.56);
  const cy = Y(0.44);
  const R = U * 0.34;
  const defectY = Math.round(cy + (rnd() - 0.5) * R * 0.6);
  disc(f, cx, cy, R, (dx, dy, d) => {
    if (d > 0.9) return 1; // the rim
    const x = Math.round(cx + dx * R);
    const y = Math.round(cy + dy * R);
    const mx = Math.floor(x / 3);
    const my = Math.floor(y / 3);
    const broken = Math.abs(y - defectY) < 3 && Math.abs(x - cx) < R * 0.45;
    if (broken) return 0.95;
    return (mx + my) % 4 < 2 ? 0.62 : 0.14;
  }, (dx, dy, d) => d <= 0.9 && Math.abs(Math.round(cy + dy * R) - defectY) < 3 && Math.abs(dx * R) < R * 0.45);
  // the handle, out to the lower right
  const a = Math.PI / 4;
  for (let t = 0; t < U * 0.42; t++) {
    const x = cx + Math.cos(a) * (R + t);
    const y = cy + Math.sin(a) * (R + t);
    disc(f, x, y, Math.max(2, U * 0.045), () => 0.9);
  }
  return f;
};

// ── the order book: sheets fanned out, ruled lines of text, a confirmed stamp in ember
const orders = (w: number, h: number, rnd: Rnd, live = false): Field => {
  const f = field(w, h);
  paper(f);
  const { U, X, Y } = frame(w, h);
  for (let s = 2; s >= 0; s--) {
    const x0 = X(0.18 + s * 0.08);
    const y0 = Y(0.08 + s * 0.05);
    const x1 = x0 + U * 0.95;
    const y1 = y0 + U * 0.78;
    box(f, x0, y0, x1, y1, () => (s === 0 ? 0.03 : 0.12));
    line(f, x0, y0, x1, y0, 0.95);
    line(f, x0, y1, x1, y1, 0.95);
    line(f, x0, y0, x0, y1, 0.95);
    line(f, x1, y0, x1, y1, 0.95);
    if (s !== 0) continue;
    line(f, x0 + U * 0.08, y0, x0 + U * 0.08, y1, 0.5);
    for (let r = 0; r < 9; r++) {
      const y = y0 + U * 0.1 + r * U * 0.072;
      const len = 0.35 + rnd() * 0.5;
      if (live && r === 8) continue; // the line still being written
      line(f, x0 + U * 0.12, y, x0 + U * 0.12 + len * U * 0.7, y, r === 0 ? 1 : 0.6, false, r === 0 ? 2 : 1);
    }
    const sx = x1 - U * 0.2;
    const sy = y1 - U * 0.2;
    disc(f, sx, sy, U * 0.13, (_, __, d) => (d > 0.82 || (d < 0.6 && d > 0.5) ? 1 : 0), (_, __, d) => d > 0.82 || (d < 0.6 && d > 0.5));
    line(f, sx - U * 0.06, sy, sx - U * 0.015, sy + U * 0.045, 1, true, 2);
    line(f, sx - U * 0.015, sy + U * 0.045, sx + U * 0.07, sy - U * 0.05, 1, true, 2);
  }
  return f;
};

// ── the books: month bars, shaded heavy at the top, with the trend drawn through them in ember
const bars = (w: number, h: number, rnd: Rnd, live = false): Field => {
  const f = field(w, h);
  paper(f);
  const { U, X, Y } = frame(w, h);
  const n = 9;
  const tops: [number, number][] = [];
  let level = 0.3;
  for (let i = 0; i < n; i++) {
    level = clamp(level + 0.04 + (rnd() - 0.35) * 0.1, 0.15, 0.85);
    const x0 = X(0.06 + i * 0.1);
    const x1 = x0 + U * 0.11;
    const top = Y(0.9) - level * U * 0.8;
    box(f, x0, top, x1, Y(0.9), (u, v) => (0.9 - v * 0.55) * (0.75 + 0.25 * Math.sin(Math.PI * u)));
    tops.push([(x0 + x1) / 2, top - U * 0.06]);
  }
  for (let i = 1; i < tops.length; i++) line(f, tops[i - 1][0], tops[i - 1][1], tops[i][0], tops[i][1], 1, true, 2);
  for (const [x, y] of tops) disc(f, x, y, Math.max(2, U * 0.022), () => 1, () => true);
  box(f, X(0.02), Y(0.9), X(0.98), Y(0.93), () => 0.95);
  return f;
};

// ── the mill: a north-light sawtooth roof over the shed, rows of windows, the chimney smoking
const mill = (w: number, h: number, rnd: Rnd, live = false): Field => {
  const f = field(w, h);
  paper(f);
  const { U, X, Y } = frame(w, h);
  const teeth = 6;
  const roofBase = Y(0.48);
  const toothH = U * 0.16;
  for (let t = 0; t < teeth; t++) {
    const x0 = X(0.04 + (t * 0.72) / teeth);
    const x1 = X(0.04 + ((t + 1) * 0.72) / teeth);
    for (let x = Math.round(x0); x < x1; x++) {
      const u = (x - x0) / (x1 - x0);
      const top = roofBase - toothH * u;
      for (let y = Math.round(top); y < roofBase; y++) put(f, x, y, u > 0.9 ? 1 : 0.32 + 0.3 * u, u > 0.9);
    }
  }
  box(f, X(0.04), roofBase, X(0.76), Y(0.9), () => 0.48);
  for (let r = 0; r < 3; r++) {
    for (let c = 0; c < 9; c++) {
      const x0 = X(0.07 + c * 0.077);
      const y0 = roofBase + U * (0.07 + r * 0.11);
      const lit = rnd() < 0.18;
      box(f, x0, y0, x0 + U * 0.06, y0 + U * 0.06, () => (lit ? 1 : 0.05), () => lit);
    }
  }
  box(f, X(0.8), Y(0.2), X(0.8) + U * 0.09, Y(0.9), (u) => cyl(u));
  box(f, X(0.8), Y(0.28), X(0.8) + U * 0.09, Y(0.31), () => 1, () => true);
  if (!live) {
    for (let p = 0; p < 7; p++) {
      const px = X(0.82) + p * U * 0.1;
      const py = Y(0.15) - p * U * 0.025;
      disc(f, px, py, U * (0.05 + p * 0.012), (_, __, d) => (0.5 - p * 0.06) * (1 - d * 0.6));
    }
  }
  box(f, X(0.02), Y(0.9), X(0.98), Y(0.93), () => 0.95);
  return f;
};

// ── setup: two meshing gears
const gear = (w: number, h: number, rnd: Rnd, live = false): Field => {
  const f = field(w, h);
  paper(f);
  const [p1, p2] = [rnd() * 3, rnd() * 3];
  if (!live) cogs(f, p1, p2);
  return f;
};

// two meshing gears; phases turn them (the small one runs 12:8 faster, the other way)
function cogs(f: Field, p1: number, p2: number) {
  const { U, X, Y } = frame(f.w, f.h);
  const cog = (cx: number, cy: number, R: number, n: number, phase: number, accentHub: boolean) => {
    const outer = R * 1.18;
    for (let y = Math.floor(cy - outer); y <= cy + outer; y++) {
      for (let x = Math.floor(cx - outer); x <= cx + outer; x++) {
        const d = Math.hypot(x - cx, y - cy);
        const a = Math.atan2(y - cy, x - cx);
        const tooth = Math.cos(n * a + phase) > 0.2 ? R * 0.18 : 0;
        if (d > R + tooth) continue;
        if (d < R * 0.22) {
          if (d > R * 0.12) put(f, x, y, 1, accentHub);
          continue;
        }
        const light = 0.5 + 0.35 * Math.cos(a + 2.4);
        put(f, x, y, d > R * 0.62 && d < R * 0.72 ? 0.1 : light);
      }
    }
  };
  cog(X(0.36), Y(0.5), U * 0.36, 12, p1, true);
  cog(X(0.36) + U * 0.36 * 1.18 + U * 0.22 * 1.05, Y(0.42), U * 0.22, 8, p2, false);
}

function looseEnd(f: Field, lift: number, sway: number) {
  const { U, X, Y } = frame(f.w, f.h);
  const x0 = X(0.5) + U * 0.2;
  for (let s = 0; s <= 160; s++) {
    const t = s / 160;
    put(f, x0 + t * U * 0.55, Y(0.55 + lift) + Math.sin(t * 9 - sway) * U * 0.05 * (1 - t * 0.6) + t * U * 0.25, 1, true);
  }
}

// ── a single spool with a loose thread curling off it: the empty-state picture
const spool = (w: number, h: number, rnd: Rnd, live = false): Field => {
  const f = field(w, h);
  paper(f, 10);
  const { U, X, Y } = frame(w, h);
  const cx = X(0.5);
  const top = Y(0.18);
  const bot = Y(0.82);
  const half = U * 0.2;
  box(f, cx - half * 1.35, top - U * 0.05, cx + half * 1.35, top, () => 0.95);
  box(f, cx - half * 1.35, bot, cx + half * 1.35, bot + U * 0.05, () => 0.95);
  box(f, cx - half, top, cx + half, bot, (u, _, __, y) => cyl(u) * (0.8 + 0.2 * Math.sin(y * 1.1)));
  const lift = rnd() * 0.1;
  if (!live) looseEnd(f, lift, 0);
  return f;
};

// the road, dashed, with speed lines behind; `shift` slides the dashes back
function road(f: Field, shift: number, jitter: number[]) {
  const { U, X, Y } = frame(f.w, f.h);
  const gap = U * 0.06;
  for (let x = X(0.02) - (shift % gap); x < X(0.98); x += gap) line(f, Math.max(X(0.02), x), Y(0.96), Math.max(X(0.02), x + U * 0.03), Y(0.96), 0.9);
  for (let k = 0; k < 4; k++) {
    const y = Y(0.4 + k * 0.08 + jitter[k] * 0.02);
    line(f, X(-0.05), y, X(0.04 - k * 0.01), y, 0.7);
  }
}

// ── dispatch: a lorry with its slatted bed loaded with rolls, tail light in ember, on the road
const truck = (w: number, h: number, rnd: Rnd, live = false): Field => {
  const f = field(w, h);
  paper(f);
  const { U, X, Y } = frame(w, h);
  const bedTop = Y(0.28);
  const deck = Y(0.74);
  // the load: rolls end-on, stacked in the bed
  const r = U * 0.075;
  for (let row = 0; row < 3; row++) {
    for (let i = 0; i < 6; i++) {
      const cx = X(0.1) + r + i * r * 2.08 + (row % 2) * r;
      const cy = deck - r - row * r * 1.8;
      if (cx + r > X(0.64)) continue;
      disc(f, cx, cy, r, (_, __, d) => (d < 0.22 ? 1 : d > 0.9 ? 0.95 : 0.25 + 0.3 * (0.5 + 0.5 * Math.sin(d * 22))));
    }
  }
  // slatted sides over the load
  for (let k = 0; k <= 7; k++) line(f, X(0.08 + k * 0.08), bedTop, X(0.08 + k * 0.08), deck, 0.95);
  line(f, X(0.08), bedTop, X(0.64), bedTop, 1, false, 2);
  // cab with its window
  box(f, X(0.66), Y(0.36), X(0.9), deck, (u) => 0.35 + 0.4 * u);
  box(f, X(0.7), Y(0.4), X(0.86), Y(0.54), () => 0.04);
  box(f, X(0.89), Y(0.6), X(0.92), Y(0.66), () => 1, () => true); // headlight
  box(f, X(0.06), Y(0.62), X(0.08), Y(0.7), () => 1, () => true); // tail light
  box(f, X(0.06), deck, X(0.92), deck + U * 0.04, () => 0.95); // chassis
  for (const a of [0.2, 0.5, 0.8]) {
    disc(f, X(a), deck + U * 0.08, U * 0.085, (_, __, d) => (d < 0.35 ? 0.2 : 0.95));
  }
  if (!live) road(f, 0, [rnd(), rnd(), rnd(), rnd()]);
  return f;
};

// Everest's skyline as a fraction of the height, left to right: Nuptse, the summit, Lhotse
const PEAKS: [number, number][] = [
  [0, 0.74], [0.07, 0.6], [0.14, 0.66], [0.24, 0.44], [0.3, 0.5], [0.36, 0.38], [0.47, 0.12],
  [0.53, 0.26], [0.6, 0.22], [0.66, 0.36], [0.74, 0.3], [0.82, 0.46], [0.9, 0.42], [1, 0.56],
];
function ridge(u: number) {
  let k = 0;
  while (k < PEAKS.length - 2 && PEAKS[k + 1][0] < u) k++;
  const [u0, v0] = PEAKS[k];
  const [u1, v1] = PEAKS[k + 1];
  return v0 + ((v1 - v0) * (u - u0)) / (u1 - u0) + Math.sin(u * 91 + 1.3) * 0.008 + Math.sin(u * 37) * 0.012;
}

// ── Mount Everest across the whole width: Nuptse, the summit pyramid with its wind plume, Lhotse.
//    Lit faces stay snow-white, shadow faces carry the dots; the mountain covers what is under it.
const everest = (w: number, h: number, rnd: Rnd, live = false): Field => {
  const f = field(w, h);
  f.cov = new Uint8Array(w * h);
  for (let x = 0; x < w; x++) {
    const u = x / w;
    const top = ridge(u) * h;
    const slope = ridge(u + 0.004) - ridge(u - 0.004);
    const lit = slope > 0; // the face turned to the morning sun on the left
    for (let y = Math.max(0, Math.round(top)); y < h; y++) {
      const i = y * w + x;
      const depth = (y - top) / h;
      const strata = 0.05 * Math.sin(y * 0.6 + Math.sin(u * 13) * 4);
      const snow = depth < 0.05 + 0.04 * Math.sin(u * 23) ? 0.4 : 1;
      f.val[i] = Math.max(0, (lit ? 0.04 : 0.26) * snow + strata * (lit ? 0.4 : 1) + depth * 0.22);
      f.cov[i] = 1;
    }
    put(f, x, top, 1); // the skyline itself, in ink
  }
  // the summit plume: wind-blown snow streaming east
  if (!live) {
    const sx = 0.47 * w;
    const sy = ridge(0.47) * h;
    for (let p = 0; p < 14; p++) {
      const px = sx + p * w * 0.018;
      const py = sy - h * 0.02 - Math.sin(p * 0.5) * h * 0.02;
      disc(f, px, py, h * (0.012 + p * 0.0035), (_, __, d) => (0.42 - p * 0.026) * (1 - d * 0.7) + rnd() * 0.02);
    }
  }
  // a low ember sun above Nuptse
  disc(f, w * 0.2, h * 0.2, Math.min(w, h) * 0.05, () => 0.9, () => true);
  return f;
};

export const MOTIFS: Record<MotifName, (w: number, h: number, rnd: Rnd, live?: boolean) => Field> = { loom, cones, rolls, loupe, orders, bars, mill, gear, spool, truck, everest };

// 0..1 position in a repeating cycle of `period` seconds, offset by `k` of a cycle
const cycle = (t: number, period: number, k = 0) => (((t / period + k) % 1) + 1) % 1;
const ease = (x: number) => 0.5 - 0.5 * Math.cos(Math.PI * x);

// ── the moving parts, drawn into an empty field each frame. Slow on purpose: background, not show.
export const LIVE: Partial<Record<MotifName, (f: Field, t: number, seed: number) => void>> = {
  // smoke leaves the chimney, swells, drifts east on the wind and thins out
  mill: (f, t) => {
    const { U, X, Y } = frame(f.w, f.h);
    const cx = X(0.8) + U * 0.045;
    const top = Y(0.2);
    const n = 9;
    for (let i = 0; i < n; i++) {
      const p = cycle(t, 11, i / n);
      const fadeIn = Math.min(1, p / 0.12);
      const x = cx + p * U * 0.95 + Math.sin(t * 0.35 + i * 1.7) * U * 0.015;
      const y = top - U * 0.03 - Math.sqrt(p) * U * 0.2;
      const r = U * (0.03 + p * 0.1);
      disc(f, x, y, r, (_, __, d) => fadeIn * (0.55 * (1 - p)) * (1 - d * 0.65));
    }
  },
  // the shuttle flies across the shed and back, easing at each selvedge
  loom: (f, t) => {
    const { X } = frame(f.w, f.h);
    const p = cycle(t, 6);
    const there = p < 0.5 ? ease(p * 2) : 1 - ease((p - 0.5) * 2);
    shuttle(f, X(0.22 + there * 0.56));
  },
  // the running yarn ripples as it feeds off the cone
  cones: (f, t, seed) => {
    const { U, X, Y } = frame(f.w, f.h);
    const rnd = mulberry32(seed);
    const n = 5;
    const lead = Math.floor(rnd() * n);
    let tall = 0;
    for (let i = 0; i <= lead; i++) tall = U * (0.52 + 0.18 * rnd());
    thread(f, X(0.12 + (lead * 0.76) / (n - 1)), Y(0.86) - tall - U * 0.06, t * 1.6);
  },
  // an ember scan line sweeps the lens: the inspection in progress
  loupe: (f, t) => {
    const { U, X, Y } = frame(f.w, f.h);
    const cx = X(0.56);
    const cy = Y(0.44);
    const R = U * 0.34 * 0.86;
    const p = cycle(t, 7);
    const y = cy - R + ease(p < 0.5 ? p * 2 : 2 - p * 2) * 2 * R;
    const half = Math.sqrt(Math.max(0, R * R - (y - cy) * (y - cy)));
    line(f, cx - half, y, cx + half, y, 1, true);
  },
  // the newest line of the order is written out, held, and written again
  orders: (f, t, seed) => {
    const { U, X, Y } = frame(f.w, f.h);
    const rnd = mulberry32(seed);
    let len = 0;
    for (let r = 0; r < 9; r++) len = 0.35 + rnd() * 0.5;
    const x0 = X(0.18) + U * 0.12;
    const y = Y(0.08) + U * 0.1 + 8 * U * 0.072;
    const p = cycle(t, 7);
    const shown = Math.min(1, p / 0.55);
    const x1 = x0 + shown * len * U * 0.7;
    line(f, x0, y, x1, y, 0.6);
    if (p < 0.8 && Math.floor(t * 2) % 2 === 0) line(f, x1 + 1, y - 2, x1 + 1, y + 2, 1, true);
  },
  // the latest point on the trend breathes, a ring opening out from it
  bars: (f, t, seed) => {
    const { U, X, Y } = frame(f.w, f.h);
    const rnd = mulberry32(seed);
    let level = 0.3;
    for (let i = 0; i < 9; i++) level = clamp(level + 0.04 + (rnd() - 0.35) * 0.1, 0.15, 0.85);
    const x = X(0.06 + 8 * 0.1) + U * 0.055;
    const y = Y(0.9) - level * U * 0.8 - U * 0.06;
    const p = cycle(t, 3.2);
    const r = U * (0.03 + p * 0.07);
    disc(f, x, y, r, (_, __, d) => (d > 0.82 ? 1 - p : 0), (_, __, d) => d > 0.82);
  },
  // the gears turn, slowly, meshing
  gear: (f, t, seed) => {
    const rnd = mulberry32(seed);
    const [p1, p2] = [rnd() * 3, rnd() * 3];
    const w = t * 0.12;
    cogs(f, p1 - 12 * w, p2 + 12 * w);
  },
  spool: (f, t, seed) => looseEnd(f, mulberry32(seed)() * 0.1, t * 1.2),
  // the road slides back under the lorry
  truck: (f, t, seed) => {
    const { U } = frame(f.w, f.h);
    const rnd = mulberry32(seed);
    road(f, t * U * 0.09, [rnd(), rnd(), rnd(), rnd()]);
  },
  // the summit plume streams east off the top of the world
  everest: (f, t) => {
    const sx = 0.47 * f.w;
    const sy = ridge(0.47) * f.h;
    const n = 14;
    for (let i = 0; i < n; i++) {
      const p = cycle(t, 16, i / n);
      const fadeIn = Math.min(1, p / 0.1);
      const px = sx + p * f.w * 0.26;
      const py = sy - f.h * 0.02 - Math.sin(p * 7) * f.h * 0.02;
      disc(f, px, py, f.h * (0.012 + p * 0.05), (_, __, d) => fadeIn * (0.42 * (1 - p)) * (1 - d * 0.7));
    }
  },
};

// every part of the mill wears its own picture and a ledger index
export const SECTION: Record<string, { motif: MotifName; index: string }> = {
  Mill: { motif: "mill", index: "01" },
  "Yarn store": { motif: "cones", index: "02" },
  Sales: { motif: "orders", index: "03" },
  Production: { motif: "loom", index: "04" },
  Quality: { motif: "loupe", index: "05" },
  Dispatch: { motif: "truck", index: "06" },
  Accounts: { motif: "bars", index: "07" },
  Setup: { motif: "gear", index: "08" },
};

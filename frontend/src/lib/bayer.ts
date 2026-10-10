// The 8×8 Bayer ordered-dither matrix shared by the WebGL field, canvas widgets (GitHub heatmap,
// emblems, dither bands) and PixelSwap's `bayer` order. Same recursion as the poster shader:
// Bayer2(a) = fract(a.x*.5 + a.y*a.y*.75), Bayer4/8 nest it.

function bayer2(x: number, y: number) {
  const v = x * 0.5 + y * y * 0.75;
  return v - Math.floor(v);
}
function bayer4(x: number, y: number) {
  return bayer2(Math.floor(x / 2), Math.floor(y / 2)) * 0.25 + bayer2(x % 2, y % 2);
}
function bayer8(x: number, y: number) {
  return bayer4(Math.floor(x / 2), Math.floor(y / 2)) * 0.25 + bayer2(x % 2, y % 2);
}

/** 64 thresholds in [0,1), row-major, BAYER8[y * 8 + x]. */
export const BAYER8: Float32Array = (() => {
  const m = new Float32Array(64);
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) m[y * 8 + x] = bayer8(x, y);
  return m;
})();

/** Threshold for any integer pixel coordinate (tiles every 8px). */
export function bayerAt(x: number, y: number) {
  return BAYER8[(((y % 8) + 8) % 8) * 8 + (((x % 8) + 8) % 8)];
}

/** Cell indices of a cols×rows grid sorted by Bayer threshold — "flip order" for dissolves. */
export function bayerOrder(cols: number, rows: number): number[] {
  const idx: number[] = [];
  for (let i = 0; i < cols * rows; i++) idx.push(i);
  return idx.sort((a, b) => bayerAt(a % cols, Math.floor(a / cols)) - bayerAt(b % cols, Math.floor(b / cols)));
}

/** Deterministic PRNG (mulberry32) for seeded emblems. */
export function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Stable 32-bit hash of a string (FNV-1a) — use for emblem seeds. */
export function hashString(s: string) {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

let probe: CanvasRenderingContext2D | null = null;

/**
 * Any CSS colour as one packed RGBA pixel, for writing a Uint32Array view over ImageData — a whole
 * dithered canvas in one pass instead of a fillRect per dot. Little-endian, like every browser host.
 */
export function rgba32(color: string): number {
  probe ??= document.createElement("canvas").getContext("2d");
  if (!probe) return 0xffffffff;
  probe.fillStyle = "#000";
  probe.fillStyle = color; // the browser normalises it: "#rrggbb", or "rgba(…)" when translucent
  const s = String(probe.fillStyle);
  const [r, g, b] = s.startsWith("#")
    ? [1, 3, 5].map((k) => parseInt(s.slice(k, k + 2), 16))
    : (s.match(/[\d.]+/g) ?? ["0", "0", "0"]).map(Number);
  return ((255 << 24) | (b << 16) | (g << 8) | r) >>> 0;
}

/** Read a CSS custom property from :root (client only). */
export function cssVar(name: string, fallback = "#F2EEE4") {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

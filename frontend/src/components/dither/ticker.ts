// one shared clock for every live print: ~12 frames a second (a dither moves in steps anyway),
// a single rAF for the whole page, stopped when nothing subscribes. Browsers pause rAF in
// hidden tabs, so a backgrounded mill costs nothing.

type Sub = (t: number) => void;

const FRAME_MS = 1000 / 12;
const subs = new Set<Sub>();
let raf = 0;
let last = 0;

function loop(now: number) {
  raf = requestAnimationFrame(loop);
  if (now - last < FRAME_MS) return;
  last = now - ((now - last) % FRAME_MS);
  const t = now / 1000;
  for (const s of subs) s(t);
}

export function subscribe(s: Sub): () => void {
  subs.add(s);
  if (!raf) raf = requestAnimationFrame(loop);
  return () => {
    subs.delete(s);
    if (!subs.size && raf) {
      cancelAnimationFrame(raf);
      raf = 0;
    }
  };
}

// reduced motion: prints stay still and draw their moving parts in place
export function motionAllowed() {
  return typeof window !== "undefined" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

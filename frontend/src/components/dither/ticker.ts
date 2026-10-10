import { useEffect, useState } from "react";

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

const KEY = "motion";
const REDUCE = "(prefers-reduced-motion: reduce)";

// the OS reduced-motion setting, unless this browser picked "on" or "off" in the app
// (Windows turns it on with Settings > Accessibility > Animation effects)
export function motionAllowed() {
  if (typeof window === "undefined") return false;
  try {
    const v = localStorage.getItem(KEY);
    if (v === "on") return true;
    if (v === "off") return false;
  } catch {}
  return !window.matchMedia(REDUCE).matches;
}

export function setMotion(on: boolean) {
  try {
    localStorage.setItem(KEY, on ? "on" : "off");
  } catch {}
  window.dispatchEvent(new Event("motionchange"));
}

// live value of motionAllowed(): follows the in-app switch and the OS setting
export function useMotion() {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const read = () => setOn(motionAllowed());
    read();
    const mq = window.matchMedia(REDUCE);
    window.addEventListener("motionchange", read);
    mq.addEventListener("change", read);
    return () => {
      window.removeEventListener("motionchange", read);
      mq.removeEventListener("change", read);
    };
  }, []);
  return on;
}

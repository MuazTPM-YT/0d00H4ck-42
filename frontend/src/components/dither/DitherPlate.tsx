"use client";

import { memo, useEffect, useRef } from "react";

import { type Field, LIVE, MOTIFS, type MotifName } from "@/components/dither/motifs";
import { subscribe, useMotion } from "@/components/dither/ticker";
import { BAYER8, cssVar, hashString, mulberry32, rgba32 } from "@/lib/bayer";
import { cn } from "@/lib/utils";

const cache = new Map<string, Field>();

const idle = (fn: () => void): number =>
  typeof window.requestIdleCallback === "function" ? window.requestIdleCallback(fn, { timeout: 300 }) : window.setTimeout(fn, 16);
const cancelIdle = (id: number) => (typeof window.cancelIdleCallback === "function" ? window.cancelIdleCallback(id) : window.clearTimeout(id));

/**
 * A 1-bit picture of part of the mill (motifs.ts), dithered with the 8×8 Bayer matrix in ink with
 * ember highlights. The still picture is painted once, in idle time, when it comes near the screen.
 * Its one moving part (smoke, shuttle, gears…) is drawn on a second canvas by the shared 12 fps
 * clock, only while the plate is on screen, `live` is on and the viewer allows motion.
 */
function DitherPlateInner({
  motif,
  seed = 0,
  scale = 2,
  live = true,
  className,
  label,
}: {
  motif: MotifName;
  seed?: number | string;
  scale?: number;
  /** let the moving part move (e.g. only while a machine is running) */
  live?: boolean;
  className?: string;
  label?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const still = useRef<HTMLCanvasElement>(null);
  const moving = useRef<HTMLCanvasElement>(null);
  const motion = useMotion();

  useEffect(() => {
    const wrap = box.current;
    const canvas = still.current;
    if (!wrap || !canvas) return;
    const n = typeof seed === "string" ? hashString(seed) : seed;
    const liveFn = live && motion ? LIVE[motif] : undefined;
    let painted = "";
    let job = 0;
    let near = false;
    let seen = false;
    let w = 0;
    let h = 0;
    let ink = 0;
    let ac = 0;

    // the still picture; with a live part, the moving bits are left out of it
    const render = () => {
      w = Math.max(8, Math.floor(wrap.clientWidth / scale));
      h = Math.max(8, Math.floor(wrap.clientHeight / scale));
      ink = rgba32(cssVar("--foreground", "#15140f"));
      ac = rgba32(cssVar("--ember", "#ae4024"));
      const paperPx = rgba32(cssVar("--background", "#f2eee4"));
      const key = `${motif}:${n}:${w}x${h}:${liveFn ? "live" : "still"}`;
      if (painted === `${key}:${ink}:${ac}`) return;
      painted = `${key}:${ink}:${ac}`;
      let fld = cache.get(key);
      if (!fld) {
        fld = MOTIFS[motif](w, h, mulberry32(n), !!liveFn);
        cache.set(key, fld);
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      const img = ctx.createImageData(w, h);
      const px = new Uint32Array(img.data.buffer);
      const { val, acc, cov } = fld;
      for (let y = 0; y < h; y++) {
        const row = (y & 7) << 3;
        for (let x = 0; x < w; x++) {
          const i = y * w + x;
          if (val[i] > 0.03 && val[i] > BAYER8[row | (x & 7)]) px[i] = acc[i] ? ac : ink;
          else if (cov?.[i]) px[i] = paperPx;
        }
      }
      ctx.putImageData(img, 0, 0);
    };
    const queue = () => {
      if (near && !job)
        job = idle(() => {
          job = 0;
          render();
        });
    };

    // the moving part: one reused field and image, cleared and redrawn each tick
    let unsub: (() => void) | null = null;
    let buf: Field | null = null;
    let frame: ImageData | null = null;
    const tick = (t: number) => {
      const cv = moving.current;
      if (!cv || !liveFn || !w || !h) return;
      const ctx = cv.getContext("2d");
      if (!ctx) return;
      if (!buf || buf.w !== w || buf.h !== h) {
        buf = { val: new Float32Array(w * h), acc: new Uint8Array(w * h), w, h };
        frame = ctx.createImageData(w, h);
        cv.width = w;
        cv.height = h;
      }
      buf.val.fill(0);
      buf.acc.fill(0);
      liveFn(buf, t, n);
      const px = new Uint32Array(frame!.data.buffer);
      px.fill(0);
      const { val, acc } = buf;
      for (let y = 0; y < h; y++) {
        const row = (y & 7) << 3;
        for (let x = 0; x < w; x++) {
          const i = y * w + x;
          if (val[i] > 0.03 && val[i] > BAYER8[row | (x & 7)]) px[i] = acc[i] ? ac : ink;
        }
      }
      ctx.putImageData(frame!, 0, 0);
    };
    const animate = () => {
      if (liveFn && seen && !unsub) unsub = subscribe(tick);
      else if ((!seen || !liveFn) && unsub) {
        unsub();
        unsub = null;
      }
    };

    const io = new IntersectionObserver(
      ([e]) => {
        near = e.isIntersecting;
        queue();
      },
      { rootMargin: "300px" },
    );
    io.observe(wrap);
    // animate only what is actually on screen
    const onScreen = new IntersectionObserver(([e]) => {
      seen = e.isIntersecting;
      animate();
    });
    onScreen.observe(wrap);
    const ro = new ResizeObserver(queue);
    ro.observe(wrap);
    const mo = new MutationObserver(queue);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      io.disconnect();
      onScreen.disconnect();
      ro.disconnect();
      mo.disconnect();
      unsub?.();
      if (job) cancelIdle(job);
    };
  }, [motif, seed, scale, live, motion]);

  return (
    <div
      ref={box}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cn("relative block h-full w-full", className)}
    >
      <canvas ref={still} className="absolute inset-0 block h-full w-full [image-rendering:pixelated]" />
      <canvas ref={moving} className="absolute inset-0 block h-full w-full [image-rendering:pixelated]" />
    </div>
  );
}

export const DitherPlate = memo(DitherPlateInner);

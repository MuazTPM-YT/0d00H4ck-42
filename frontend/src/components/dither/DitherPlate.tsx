"use client";

import { memo, useEffect, useRef } from "react";

import { type Field, MOTIFS, type MotifName } from "@/components/dither/motifs";
import { BAYER8, cssVar, hashString, mulberry32, rgba32 } from "@/lib/bayer";
import { cn } from "@/lib/utils";

const cache = new Map<string, Field>();

const idle = (fn: () => void): number =>
  typeof window.requestIdleCallback === "function" ? window.requestIdleCallback(fn, { timeout: 300 }) : window.setTimeout(fn, 16);
const cancelIdle = (id: number) => (typeof window.cancelIdleCallback === "function" ? window.cancelIdleCallback(id) : window.clearTimeout(id));

/**
 * A 1-bit picture of part of the mill (motifs.ts), dithered with the 8×8 Bayer matrix in ink with
 * ember highlights. Painted once, in idle time, when it comes near the screen; repainted only on
 * resize or a theme change. It never depends on live data, so the 3-second floor feed costs nothing.
 */
function DitherPlateInner({
  motif,
  seed = 0,
  scale = 2,
  className,
  label,
}: {
  motif: MotifName;
  seed?: number | string;
  scale?: number;
  className?: string;
  label?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const n = typeof seed === "string" ? hashString(seed) : seed;
    let painted = "";
    let job = 0;
    let near = false;

    const render = () => {
      const w = Math.max(8, Math.floor(canvas.clientWidth / scale));
      const h = Math.max(8, Math.floor(canvas.clientHeight / scale));
      const ink = rgba32(cssVar("--foreground", "#15140f"));
      const ac = rgba32(cssVar("--ember", "#ae4024"));
      const paperPx = rgba32(cssVar("--background", "#f2eee4"));
      const key = `${motif}:${n}:${w}x${h}`;
      if (painted === `${key}:${ink}:${ac}`) return;
      painted = `${key}:${ink}:${ac}`;
      let fld = cache.get(key);
      if (!fld) {
        fld = MOTIFS[motif](w, h, mulberry32(n));
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
    const io = new IntersectionObserver(
      ([e]) => {
        near = e.isIntersecting;
        queue();
      },
      { rootMargin: "300px" },
    );
    io.observe(canvas);
    const ro = new ResizeObserver(queue);
    ro.observe(canvas);
    const mo = new MutationObserver(queue);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      io.disconnect();
      ro.disconnect();
      mo.disconnect();
      if (job) cancelIdle(job);
    };
  }, [motif, seed, scale]);

  return (
    <canvas
      ref={ref}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cn("block h-full w-full [image-rendering:pixelated]", className)}
    />
  );
}

export const DitherPlate = memo(DitherPlateInner);

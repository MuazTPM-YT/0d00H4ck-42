"use client";

import { useEffect, useRef } from "react";

import { bayerAt, cssVar, rgba32 } from "@/lib/bayer";
import { cn } from "@/lib/utils";

/** A 1-bit Bayer ramp strip between sections: a divider, not a bar. Painted once per size/theme. */
export function DitherBand({ height = 28, direction = "ltr", className }: { height?: number; direction?: "ltr" | "rtl" | "center"; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    let raf = 0;
    const draw = () => {
      raf = 0;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const w = Math.max(1, Math.floor(canvas.clientWidth / 2));
      const h = Math.max(1, Math.floor(canvas.clientHeight / 2));
      canvas.width = w;
      canvas.height = h;
      const fc = rgba32(cssVar("--foreground", "#15140f"));
      const ac = rgba32(cssVar("--ember", "#ae4024"));
      const img = ctx.createImageData(w, h);
      const px = new Uint32Array(img.data.buffer);
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          const u = x / w;
          const t = direction === "rtl" ? 1 - u : direction === "center" ? 1 - Math.abs(u - 0.5) * 2 : u;
          const edge = Math.min(1, Math.min(u, 1 - u) * 6);
          const vy = 1 - Math.abs(y / h - 0.5) * 1.35;
          const v = Math.min(0.58, Math.max(0, (t * 0.75 - 0.1) * vy * edge));
          if (v > 0.02 && v > bayerAt(x, y)) px[y * w + x] = t > 0.97 && bayerAt(x + 3, y + 5) < 0.08 ? ac : fc;
        }
      }
      ctx.putImageData(img, 0, 0);
    };
    const queue = () => {
      if (!raf) raf = requestAnimationFrame(draw);
    };
    const ro = new ResizeObserver(queue);
    ro.observe(canvas);
    const mo = new MutationObserver(queue);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      mo.disconnect();
    };
  }, [direction]);

  return (
    <div aria-hidden className={cn("relative w-full border-y border-border", className)} style={{ height }}>
      <canvas ref={ref} className="block h-full w-full [image-rendering:pixelated]" />
    </div>
  );
}

"use client";

import { useEffect, useRef } from "react";

import { BAYER8, cssVar, rgba32 } from "@/lib/bayer";
import { cn } from "@/lib/utils";

/**
 * A photo printed as 1-bit Bayer dots in the page ink (local file, so it works offline).
 * Darks become dots, lights stay paper. Painted once per size and theme.
 */
export function DitherImage({ src, scale = 2, contrast = 1.35, className, label }: { src: string; scale?: number; contrast?: number; className?: string; label?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const img = new Image();
    let ready = false;
    let raf = 0;
    const paint = () => {
      raf = 0;
      if (!ready) return;
      const w = Math.max(8, Math.floor(canvas.clientWidth / scale));
      const h = Math.max(8, Math.floor(canvas.clientHeight / scale));
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      if (!ctx) return;
      // cover-fit the photo into the canvas
      const k = Math.max(w / img.naturalWidth, h / img.naturalHeight);
      const dw = img.naturalWidth * k;
      const dh = img.naturalHeight * k;
      ctx.drawImage(img, (w - dw) / 2, (h - dh) / 2, dw, dh);
      const data = ctx.getImageData(0, 0, w, h);
      const src8 = data.data;
      const out = ctx.createImageData(w, h);
      const px = new Uint32Array(out.data.buffer);
      const ink = rgba32(cssVar("--foreground", "#15140f"));
      const ember = rgba32(cssVar("--ember", "#ae4024"));
      const lums = new Float32Array(w * h);
      for (let i = 0; i < w * h; i++) lums[i] = (0.299 * src8[i * 4] + 0.587 * src8[i * 4 + 1] + 0.114 * src8[i * 4 + 2]) / 255;
      // auto-levels: stretch the photo's own 5th..95th percentile, so a pale cloth still prints
      const sorted = Float32Array.from(lums).sort();
      const lo = sorted[Math.floor(sorted.length * 0.05)];
      const hi = sorted[Math.floor(sorted.length * 0.95)];
      const span = Math.max(0.05, hi - lo);
      for (let y = 0; y < h; y++) {
        const row = (y & 7) << 3;
        for (let x = 0; x < w; x++) {
          const i = y * w + x;
          const lum = (lums[i] - lo) / span;
          const dark = Math.min(0.92, Math.max(0, (0.5 - lum) * contrast + 0.45));
          // the warmest threads of the cloth print in ember
          const warm = src8[i * 4] - src8[i * 4 + 2] > 70 && dark > 0.35;
          if (dark > BAYER8[row | (x & 7)]) px[i] = warm ? ember : ink;
        }
      }
      ctx.putImageData(out, 0, 0);
    };
    const queue = () => {
      if (!raf) raf = requestAnimationFrame(paint);
    };
    img.onload = () => {
      ready = true;
      queue();
    };
    img.src = src;
    const ro = new ResizeObserver(queue);
    ro.observe(canvas);
    const mo = new MutationObserver(queue);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      mo.disconnect();
    };
  }, [src, scale, contrast]);

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

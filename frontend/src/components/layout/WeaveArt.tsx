import { memo, useId } from "react";

// a patch of woven cloth drawn in SVG: warp threads run down, weft threads run across,
// interlaced over-under in a twill. Same seed, same cloth; the tint is the section's colour.
function WeaveArtInner({ seed = 0, tint = "var(--info)", className }: { seed?: number; tint?: string; className?: string }) {
  const id = useId().replace(/:/g, "");
  const s = 26; // thread pitch
  const cols = 22;
  const rows = 9;
  const twill = (seed % 3) + 2; // 2/2, 3/3 or 4/4 twill per section
  const over = (i: number, j: number) => (i + j * (seed % 2 ? 1 : -1) + seed + 100 * twill) % (twill * 2) < twill;

  const weft = (j: number) => <rect key={`w${j}`} x={0} y={j * s + 5} width={cols * s} height={s - 10} rx={(s - 10) / 2} fill={`url(#weft-${id})`} />;
  const warps = Array.from({ length: cols }, (_, i) => (
    <rect key={`v${i}`} x={i * s + 4} y={0} width={s - 8} height={rows * s} rx={(s - 8) / 2} fill={`url(#warp-${id})`} />
  ));
  const floats = [];
  for (let j = 0; j < rows; j++) {
    for (let i = 0; i < cols; i++) {
      if (over(i, j)) floats.push(<rect key={`f${i}-${j}`} x={i * s - 1} y={j * s + 5} width={s + 2} height={s - 10} rx={(s - 10) / 2} fill={`url(#weft-${id})`} />);
    }
  }

  return (
    <svg viewBox={`0 0 ${cols * s} ${rows * s}`} preserveAspectRatio="xMaxYMid slice" className={className} aria-hidden>
      <defs>
        {/* each thread is rounded: bright on its crown, darker at the edges */}
        <linearGradient id={`warp-${id}`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor={tint} stopOpacity="0.35" />
          <stop offset="50%" stopColor={tint} stopOpacity="0.85" />
          <stop offset="100%" stopColor={tint} stopOpacity="0.35" />
        </linearGradient>
        <linearGradient id={`weft-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--foreground)" stopOpacity="0.10" />
          <stop offset="50%" stopColor="var(--foreground)" stopOpacity="0.30" />
          <stop offset="100%" stopColor="var(--foreground)" stopOpacity="0.10" />
        </linearGradient>
        <linearGradient id={`fade-${id}`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#fff" stopOpacity="0" />
          <stop offset="45%" stopColor="#fff" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#fff" stopOpacity="1" />
        </linearGradient>
        <mask id={`mask-${id}`}>
          <rect width="100%" height="100%" fill={`url(#fade-${id})`} />
        </mask>
      </defs>
      <g mask={`url(#mask-${id})`}>
        {Array.from({ length: rows }, (_, j) => weft(j))}
        {warps}
        {floats}
      </g>
    </svg>
  );
}

export const WeaveArt = memo(WeaveArtInner);

// one colour per part of the mill, so every section has its own cloth
export const SECTION_TINT: Record<string, string> = {
  Mill: "#5e5ce6",
  "Yarn store": "#ff9f0a",
  Sales: "#30b0c7",
  Production: "#0a84ff",
  Quality: "#bf5af2",
  Dispatch: "#34c759",
  Accounts: "#d4a017",
  Setup: "#8e8e93",
};

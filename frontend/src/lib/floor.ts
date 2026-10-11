// empty loom or jigger job sends nothing to QC; null when finishing is safe
export function emptyJobWarning(stage: string, code: string, produced: string): string | null {
  if (stage === "spinning" || Number(produced) > 0) return null;
  const what = stage === "weaving" ? "No roll cut yet" : "No roll dyed yet";
  return `${what} on ${code}. Nothing will reach QC. Finish anyway?`;
}

// skip on an empty loom job: the planned metres as rolls, none over the 1000 m a roll may hold
export function rollLengths(planned: string): string[] {
  const MAX = 1_000_000;
  let left = Math.round(Number(planned) * 1000);
  const out: string[] = [];
  while (left > 0) {
    const cut = Math.min(left, MAX);
    out.push((cut / 1000).toFixed(3));
    left -= cut;
  }
  return out;
}

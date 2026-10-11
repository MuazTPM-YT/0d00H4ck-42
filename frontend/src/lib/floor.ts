// empty loom or jigger job sends nothing to QC; null when finishing is safe
export function emptyJobWarning(stage: string, code: string, produced: string): string | null {
  if (stage === "spinning" || Number(produced) > 0) return null;
  const what = stage === "weaving" ? "No roll cut yet" : "No roll dyed yet";
  return `${what} on ${code}. Nothing will reach QC. Finish anyway?`;
}

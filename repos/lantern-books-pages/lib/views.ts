// Page views per book since the server started. Kept in memory: it is a demo counter, not analytics.
const counts = new Map<string, number>();

/** Count one more view of a book and return the new total. */
export function recordView(slug: string): number {
  const next = (counts.get(slug) ?? 0) + 1;
  counts.set(slug, next);
  return next;
}

export function viewsLabel(count: number): string {
  return `Viewed ${count} ${count === 1 ? "time" : "times"}`;
}

/**
 * Moves a combobox highlight through `count` options, where -1 means
 * "nothing highlighted" (the typed text). Wraps at both ends.
 */
export function cycleIndex(current: number, step: 1 | -1, count: number): number {
  if (count <= 0) return -1;
  const next = current + step;
  if (next >= count) return -1;
  if (next < -1) return count - 1;
  return next;
}

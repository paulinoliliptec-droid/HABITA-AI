/** One dictation at a time on the whole page, across every box (Codex voice-r2). */
let holder: object | null = null;

/** Takes the microphone for `owner`; false while another box holds it. */
export function claim(owner: object): boolean {
  if (holder && holder !== owner) return false;
  holder = owner;
  return true;
}

export function release(owner: object): void {
  if (holder === owner) holder = null;
}

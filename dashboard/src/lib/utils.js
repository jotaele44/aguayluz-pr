import { clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs) {
  return twMerge(clsx(inputs))
}


export const isIframe = window.self !== window.top;

// Look a key up in a plain object literal without inheriting from Object.prototype.
//
// `MAP[key] ?? fallback` looks like it degrades safely, and does for ordinary
// misses — but not for `__proto__`, `constructor`, `toString`, `valueOf` or
// `hasOwnProperty`. Those resolve through the prototype chain to a truthy object
// or function, so `??` never fires and the caller gets something that is not a
// value from the map at all.
//
// Where the key is server-supplied that is a wrong answer; where it comes from
// the URL it was a crash. `/sector/__proto__` resolved SECTOR_META to
// Object.prototype, which is truthy, so SectorDetailPage's `if (!meta)` guard
// passed it through and the next line — `meta.types.some(...)` — threw a
// TypeError and blanked the page.
export function lookup(map, key, fallback) {
  return Object.hasOwn(map, key) ? map[key] : fallback
}

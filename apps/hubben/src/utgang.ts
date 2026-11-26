import { useEffect, useRef } from "react";

// Pi:ns skärmar (S4, SKARM-03, SKARM-10): each of the Pi's two outputs shows its view in a browser
// in kiosk mode, opened at /skarm?utgang=1 and /skarm?utgang=2. Keyboard and mouse there are
// locked, and the hub's PIN unlocks them (Första start: the same PIN). Unlocked, one may open the
// hub's own pages on the output; two minutes without a key or a click lock it again, and the
// output shows its view.

/** The Pi's two HDMI outputs (SKARM-14). */
export const OUTPUTS = [1, 2] as const;
/** How long an unlocked output stays open without a key or a click. */
export const RELOCK_MS = 2 * 60_000;

const STORE = "trainmeet-utgang";

/** The output an address is for: /skarm?utgang=1 or 2, else none (a screen on a Mac or a PC). */
export function outputOf(search: string): number | null {
  const asked = Number(new URLSearchParams(search).get("utgang"));
  return (OUTPUTS as readonly number[]).includes(asked) ? asked : null;
}

export const outputAddress = (output: number) => `/skarm?utgang=${output}`;

/** The output the hub's pages are open on, after Till hubben on an unlocked output. The browser
 * tab keeps it, and only that tab: the other output is a window of its own. */
export function openedOnOutput(): number | null {
  try {
    return outputOf(`?utgang=${sessionStorage.getItem(STORE) ?? ""}`);
  } catch {
    return null;
  }
}

export function openOnOutput(output: number | null): void {
  try {
    if (output === null) sessionStorage.removeItem(STORE);
    else sessionStorage.setItem(STORE, String(output));
  } catch {
    // Without storage the hub's pages do not lock again by themselves; Lås skärmen still does.
  }
}

const ACTIVITY = ["keydown", "pointerdown", "wheel", "touchstart"] as const;

/** Calls `lock` after `ms` without a key, a click or a touch, while `active`. */
export function useRelock(active: boolean, lock: () => void, ms: number = RELOCK_MS): void {
  const latest = useRef(lock);
  latest.current = lock;
  useEffect(() => {
    if (!active) return;
    let timer = window.setTimeout(() => latest.current(), ms);
    const again = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => latest.current(), ms);
    };
    for (const kind of ACTIVITY) window.addEventListener(kind, again, { capture: true, passive: true });
    return () => {
      window.clearTimeout(timer);
      for (const kind of ACTIVITY) window.removeEventListener(kind, again, { capture: true });
    };
  }, [active, ms]);
}

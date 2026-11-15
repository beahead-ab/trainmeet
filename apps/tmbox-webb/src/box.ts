// What the box shows and what a key does, as the physical box (BOXWEB-03, BOXWEB-05). Drift
// draws the picture; the box only keeps the typed train number until #. No React here, so it
// can be tested on its own.
import type { Frame, Key } from "./api";

export const KEYS: Key[] = ["1", "2", "3", "A", "4", "5", "6", "B", "7", "8", "9", "C", "*", "0", "#", "D"];

/** The fields the old Server sends beside the contract's, kept as they come. */
export function extras(frame: Frame | null): { waiting: boolean; status: string; queue: string; queued: boolean } {
  const requests = frame?.requests as { label?: unknown; count?: unknown } | undefined;
  return {
    waiting: frame?.waiting === true,
    status: typeof frame?.status === "string" ? frame.status : "",
    queue: typeof requests?.label === "string" ? requests.label : "",
    queued: typeof requests?.count === "number" && requests.count > 0,
  };
}

/** The display's lines, with the typed digits written into the entry's place. */
export function shownLines(frame: Frame | null, entry: string | null): string[] {
  if (!frame) return ["", ""];
  if (entry === null || !frame.entry?.lines) return frame.lines;
  const rows = frame.entry.lines.map((line) => [...line]);
  const row = frame.entry.row ?? 0;
  const column = frame.entry.column ?? 5;
  const digits = entry.padEnd(frame.entry.max_length ?? 5, "_");
  [...digits].forEach((digit, index) => {
    const cells = rows[row];
    if (cells) cells[column + index] = digit;
  });
  return rows.map((cells) => cells.join(""));
}

/** What each key does now, for the hints and the keys' names. */
export function labels(frame: Frame | null, entry: string | null): Record<string, string> {
  if (!frame || extras(frame).waiting) return {};
  if (entry !== null) return frame.entry?.labels ?? {};
  return Object.fromEntries(Object.entries(frame.keys ?? {}).map(([key, info]) => [key, info.label]));
}

/** A key for Drift, with the typed train number when # sends it. */
export type SendKey = { key: Key; train_number?: string; entry_context?: string };
export type Pressed = { entry: string | null; send?: SendKey };

/**
 * One key: digits go into the train number, B erases, * cancels, A sends and # sends the
 * number. Otherwise the key goes to Drift if it does something now; a key that changes the
 * traffic waits a moment after a new picture (input_guard_ms).
 */
export function press(frame: Frame | null, entry: string | null, key: Key, sinceShown: number): Pressed {
  if (!frame || extras(frame).waiting) return { entry };
  if (/^[0-9]$/.test(key)) {
    const typed = entry ?? "";
    return { entry: typed.length < (frame.entry?.max_length ?? 5) ? typed + key : typed };
  }
  if (entry !== null) {
    if (key === "B") return { entry: entry.slice(0, -1) };
    if (key === "*") return { entry: null };
    if (key === "A") return { entry: null, send: { key: "A" } };
    if (key === "#") return entry ? { entry: null, send: { key: "#", train_number: entry, entry_context: frame.entry.context } } : { entry: null };
    return { entry };
  }
  const info = frame.keys?.[key];
  if (!info) return { entry };
  if (info.acts && sinceShown < (frame.input_guard_ms ?? 500)) return { entry };
  return { entry, send: { key } };
}

/** The keyboard as the keypad: digits, A–D, * and #; Enter is #, Backspace B and Esc *. */
export function keyFor(pressed: string): Key | null {
  const map: Record<string, Key> = { Enter: "#", Backspace: "B", Escape: "*" };
  const key = map[pressed] ?? pressed.toUpperCase();
  return (KEYS as string[]).includes(key) ? (key as Key) : null;
}

/** The display as the box draws it: 16 cells, or as many as a 20×4 box announced. */
export function columnsOf(lines: string[]): number {
  return Math.max(16, ...lines.map((line) => [...line.normalize("NFC")].length));
}

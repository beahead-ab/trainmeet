// Stream Deck on the screen (#86 del a, SD59): what the keys look like and how a press becomes a
// hold. TKL's server computes every key's face with the locked colours (SD3); the screen only
// draws it, as the prototype draws its canvas (src/streamdeck.js, rita): the background, the
// band at the top for a route's colour, the frame, the line at the bottom for the chosen page,
// the red dot for a hindered route, the text in the middle with a line over and a line under.
// A key held for the deck's hold time is a hold, else a press (SD29).
import type { CSSProperties } from "react";
import type { DeckFace, DeckView } from "./api";

/** The fjärrtågklarerare's role on a deck (#36 del d, SD37), as contracts/tkl.py has it. */
export const REMOTE_ROLE = "fjarrtagklarerare";

/** One deck per screen, known by its serial number like a real one (SD35). On a part's screen
 * /del/<id> the deck is the part's own, in its role (#87 del d); in the fjärrbild it is the
 * fjärrtågklarerare's (#36 del d). */
export const serialFor = (screen: number, role: string | null = null) =>
  role === REMOTE_ROLE ? `fjarr-${screen}` : role ? `del-${role.replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 48)}-${screen}` : `skarm-${screen}`;
export const KEY = 64;
export const STORED = "tkl.streamdeck";

export type Stored = { open: boolean; model: string };

const storedKey = (screen: number, role: string | null) => (role ? `${STORED}.del.${role}.${screen}` : `${STORED}.${screen}`);

export function readDeck(screen: number, storage: Pick<Storage, "getItem"> | null, role: string | null = null): Stored {
  try {
    const found = JSON.parse(storage?.getItem(storedKey(screen, role)) ?? "null") as Partial<Stored> | null;
    return { open: !!found?.open, model: typeof found?.model === "string" ? found.model : "15" };
  } catch {
    return { open: false, model: "15" };
  }
}

export function saveDeck(screen: number, stored: Stored, storage: Pick<Storage, "setItem"> | null, role: string | null = null): void {
  try {
    storage?.setItem(storedKey(screen, role), JSON.stringify(stored));
  } catch {
    // Without storage the choice holds for this page only.
  }
}

/** The sound a key makes on the deck on the screen: Tuta and Ring on the shunter's deck (#87). */
export function soundOf(face: DeckFace | undefined): "horn" | "ring" | null {
  if (!face || face.type !== "action") return null;
  if (face.text === "Tuta") return "horn";
  if (face.text === "Ring") return "ring";
  return null;
}

/** The text's size in a key's height, as the prototype's canvas chooses it: by its length,
 * and smaller until it fits nine tenths of the key's width (a monospace letter is 0.62 em). */
export function textSize(text: string): number {
  const n = [...text].length;
  const byLength = n > 6 ? 0.2 : n > 4 ? 0.25 : n > 2 ? 0.3 : 0.38;
  return Math.max(0.1, Math.min(byLength, 0.9 / (Math.max(1, n) * 0.62)));
}

/** The colour a key has now: a blinking key changes every half second (the prototype's blink). */
export function background(face: DeckFace, now: number): string {
  const on = Math.floor(now / 500) % 2 === 0;
  return face.blink && !on ? face.blink : (face.bg ?? "#0d0f11");
}

export function keyStyle(face: DeckFace, now: number, size = KEY): CSSProperties {
  const frame = face.frame ? Math.max(3, size / 18) : 0;
  return {
    width: size,
    height: size,
    background: background(face, now),
    color: face.fg ?? "#0d0f11",
    boxShadow: face.frame ? `inset 0 0 0 ${frame}px ${face.frame}` : undefined,
    outline: face.frame && face.dashed ? `${Math.max(2, frame - 1)}px dashed ${face.frame}` : undefined,
    outlineOffset: face.frame && face.dashed ? -Math.max(2, frame - 1) : undefined,
  };
}

/** A face for every key when the interlocking does not answer: never an old state (SD21). */
export function noContact(size: number): DeckFace[] {
  return Array.from({ length: size }, () => ({ type: "contact", text: "Ingen", under: "kontakt", bg: "#16191c", fg: "#8b95a1", dim: true, label: "Ingen kontakt" }) as DeckFace);
}

/** The keys' faces as the screen draws them: Ingen kontakt when TKL does not answer. */
export function facesOf(view: DeckView | null, contact: boolean): DeckFace[] {
  if (!view) return [];
  const size = view.settings.grid.columns * view.settings.grid.rows;
  if (!contact || !view.contact) return noContact(size);
  return view.keys ?? [];
}

/** Press or hold (SD29): a key held for the hold time is a hold, once, while it is still down;
 * a shorter one is a press when it comes up. The same rule as the server's for a real deck. */
export class Holds {
  private down = new Map<number, number>();
  private held = new Set<number>();
  constructor(public ms = 600) {}

  pressed(key: number, at: number): void {
    this.down.set(key, at);
    this.held.delete(key);
  }

  /** The keys just held long enough. */
  tick(at: number): number[] {
    const found: number[] = [];
    for (const [key, began] of this.down) {
      if (at - began >= this.ms && !this.held.has(key)) {
        this.held.add(key);
        found.push(key);
      }
    }
    return found;
  }

  released(key: number, at: number): "press" | "hold" | null {
    const began = this.down.get(key);
    this.down.delete(key);
    if (began === undefined) return null;
    if (this.held.has(key)) {
      this.held.delete(key);
      return null;
    }
    return at - began >= this.ms ? "hold" : "press";
  }

  cancel(key: number): void {
    this.down.delete(key);
    this.held.delete(key);
  }
}

/** The colours of Spårplan on a key (SD72): 85 with thin tracks in the skin's colours, or Relä
 * with a lamp per track piece. */
export const PLAN_COLOURS: Record<string, string> = {
  free: "#8a939c",
  train: "#22c55e",
  shunting: "#eab308",
  occupied: "#ef4444",
  local: "#38bdf8",
  out_of_service: "#6b7280",
  programming: "#a78bfa",
};
export const RELAY_TRACK = "#4b5563";
export const RELAY_DARK = "#1f2937";

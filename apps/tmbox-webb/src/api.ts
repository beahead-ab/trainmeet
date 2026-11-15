// TMBox web's API in the hub (contracts/terminal.py), with the types generated from the
// contracts. One box per tab: the session key lives in sessionStorage and goes as
// Authorization: Bearer for the picture, the keys and the event stream, never in an address.
import type { components } from "../../../contracts/types";

type Schemas = components["schemas"];
export type Frame = Schemas["trainmeet.terminal16.frame"];
export type Ack = Schemas["trainmeet.terminal16.ack"];
export type KeyPress = Schemas["trainmeet.terminal16.key-press"];
export type WebLogin = Schemas["trainmeet.terminal-web-1.login"];
export type WebSession = Schemas["trainmeet.terminal-web-1.session"];
export type Key = Frame["entry"]["commit"];

/** The box as the tab keeps it: the hub's session and the name the box was given. */
export type BoxSession = WebSession & { name: string };

export const STORE = "trainmeet-tmbox";

export function readSession(): BoxSession | null {
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORE) ?? "null") as BoxSession | null;
    return saved?.session_key ? saved : null;
  } catch {
    return null;
  }
}

export function writeSession(value: BoxSession | null): void {
  try {
    if (value) sessionStorage.setItem(STORE, JSON.stringify(value));
    else sessionStorage.removeItem(STORE);
  } catch {
    // A tab without storage keeps the box until it is closed.
  }
}

const bearer = (session: BoxSession) => ({ Authorization: `Bearer ${session.session_key}` });
const detail = (answer: unknown, otherwise: string) => {
  const said = (answer as { detail?: unknown } | null)?.detail;
  return typeof said === "string" ? said : otherwise;
};

export async function logIn(login: WebLogin): Promise<{ session: WebSession } | { problem: string; session?: undefined }> {
  try {
    const response = await fetch("/api/terminal/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(login),
    });
    const answer: unknown = await response.json().catch(() => null);
    if (!response.ok) return { problem: detail(answer, "Kontrollera namnet och koden.") };
    return { session: answer as WebSession };
  } catch {
    return { problem: "Hubben svarar inte. Försök igen." };
  }
}

/** The picture now; "gone" when the box is no longer known. */
export async function fetchFrame(session: BoxSession): Promise<Frame | "gone" | null> {
  const response = await fetch("/api/terminal/frame", { headers: bearer(session), cache: "no-store" }).catch(() => null);
  if (!response) return null;
  if (response.status === 401) return "gone";
  return response.ok ? ((await response.json()) as Frame) : null;
}

export type Sent = { ack: Ack } | { problem: string } | "gone" | "offline";

export async function sendKeys(session: BoxSession, press: KeyPress): Promise<Sent> {
  try {
    const response = await fetch("/api/terminal/keys", {
      method: "POST",
      headers: { ...bearer(session), "Content-Type": "application/json" },
      body: JSON.stringify(press),
    });
    if (response.status === 401) return "gone";
    const answer: unknown = await response.json().catch(() => null);
    if (!response.ok) return { problem: detail(answer, "Det gick inte.") };
    return { ack: answer as Ack };
  } catch {
    return "offline";
  }
}

/** Server-sent events read from a fetch, since EventSource cannot send Authorization. */
export function parseEvents(buffer: string): { events: { event: string; data: string }[]; rest: string } {
  const events: { event: string; data: string }[] = [];
  let rest = buffer;
  let end: number;
  while ((end = rest.indexOf("\n\n")) >= 0) {
    const chunk = rest.slice(0, end);
    rest = rest.slice(end + 2);
    let event = "message";
    let data = "";
    for (const line of chunk.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    events.push({ event, data });
  }
  return { events, rest };
}

/** Follows the box's events until stopped: a new picture, or that the box is gone. */
export async function follow(session: BoxSession, signal: AbortSignal, onFrame: (frame: Frame) => void): Promise<"gone" | "ended"> {
  const response = await fetch("/api/terminal/events", { headers: bearer(session), cache: "no-store", signal });
  if (response.status === 401) return "gone";
  if (!response.ok || !response.body) throw new Error("stream");
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return "ended";
    const parsed = parseEvents(buffer + value);
    buffer = parsed.rest;
    for (const { event, data } of parsed.events) {
      if (event === "frame" && data) onFrame(JSON.parse(data) as Frame);
      if (event === "gone") return "gone";
    }
  }
}

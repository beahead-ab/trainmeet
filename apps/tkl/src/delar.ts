// Delställverk (#87, TKL97–TKL103): what the box at the top of Ställverket and a part's own screen
// show, without React. The interlocking decides everything (STV-43); this only puts its state in
// order for the two screens.
import type { Interlocking, PartPlace, PartRequest, PartRouteOut, PartShown, PartSide, Ready } from "./api";
import type { Area } from "./Panelen";

export type Asking = { part: PartShown; request: PartRequest };
export type Box = { asking: Asking[]; ringing: PartShown[]; fika: PartShown[]; ready: Ready[] };

/** What the station sees at the top of Ställverket: the parts' waiting requests, the parts that
 * ring or have fika, and the list Klara att skicka in the station's order (TKL108). */
export function boxOf(state: Interlocking): Box {
  const parts = state.parts ?? [];
  return {
    asking: parts.flatMap((part) => (part.requests ?? []).filter((r) => r.state === "waiting").map((request) => ({ part, request }))),
    ringing: parts.filter((p) => !!p.rings),
    fika: parts.filter((p) => !!p.fika),
    ready: state.ready ?? [],
  };
}

/** What calls for the station's attention: a request, a ring or a train ready to send. A new one
 * rings in Ställverket (TKL98). */
export function attention(state: Interlocking): Set<string> {
  const box = boxOf(state);
  return new Set([...box.asking.map((a) => `begaran:${a.request.id}`), ...box.ringing.map((p) => `ring:${p.id}:${p.rings ?? ""}`), ...box.ready.map((r) => `klar:${r.number}`)]);
}

/** Whether something new calls for attention since the last time: never the first time. */
export function rings(before: Set<string> | null, now: Set<string>): boolean {
  if (!before) return false;
  for (const key of now) if (!before.has(key)) return true;
  return false;
}

/** A part by its id in the interlocking's state. */
export function partOf(state: Interlocking, id: string): PartShown | null {
  return (state.parts ?? []).find((p) => p.id === id) ?? null;
}

/** The streets or routes out at an end (TKL122): those of the end and those of neither. */
export function atEnd<T extends { side?: PartSide | null }>(items: T[], side: PartSide): T[] {
  return items.filter((item) => !item.side || item.side === side);
}

/** The part's approved requests: what Lämna gives back. */
export function approvedOf(part: PartShown): PartRequest[] {
  return (part.requests ?? []).filter((r) => r.state === "approved");
}

/** The part's area on the panel: its pieces, its signals, and its own and border switches. */
export function areaOf(part: PartShown): Area {
  return {
    pieces: new Set(part.pieces ?? []),
    signals: new Set(part.signals ?? []),
    switches: new Set([...(part.switches ?? []), ...(part.border ?? []).map((b) => b.switch)]),
  };
}

/** Where a train moved in Klara att skicka lands: from its place, by `step`, inside the list. */
export function stepTo(ready: Ready[], number: string, step: number): number | null {
  const at = ready.findIndex((r) => r.number === number);
  if (at < 0) return null;
  const to = at + step;
  return to < 0 || to >= ready.length ? null : to;
}

/** A train in Klara att skicka as the list says it: the part, its track and its planned time. */
export function readyLine(r: Ready, track: (name: string) => string): string {
  return [r.part_name, r.track ? track(r.track) : null].filter(Boolean).join(", ") + (r.departure ? ` · ${r.departure}` : "");
}

/** What a press on a route out does (RANG-03, RANG-09): a free one is requested; a waiting one is
 * taken back; an approved one is given back after Lämna, else the screen says how. */
export type OutPress = { kind: "request"; id: string } | { kind: "return"; request: number } | { kind: "say"; text: string };

export function outPress(out: PartRouteOut, giving: boolean): OutPress {
  if (out.request && out.state === "approved") {
    return giving ? { kind: "return", request: out.request } : { kind: "say", text: `${out.name} ligger. Tryck Lämna för att lämna tillbaka den.` };
  }
  if (out.request) return { kind: "return", request: out.request };
  return { kind: "request", id: out.id };
}

/** What Lämna does: the one approved request is given back at once; with several, the next
 * press on one chooses it (SD61). */
export type GivePress = { kind: "return"; request: number } | { kind: "choose" } | { kind: "none" };

export function givePress(part: PartShown): GivePress {
  const approved = approvedOf(part);
  if (!approved.length) return { kind: "none" };
  if (approved.length === 1) return { kind: "return", request: (approved[0] as PartRequest).id };
  return { kind: "choose" };
}

/** A part's driftplats in Hubben as a small line says it (#87 del b, TKL101, TRAFIK-35): what
 * the dispatcher answered for it. None for a part that is no driftplats of its own, or while
 * TKL is not connected. */
export function placeLine(part: { id: string; name: string; own_place?: boolean | null }, places: PartPlace[] | null | undefined, connected: boolean): string | null {
  if (!part.own_place || !connected) return null;
  const found = (places ?? []).find((p) => p.part === part.id);
  if (!found) return `${part.name} i Hubben: inte begärd. Anslut igen för att begära delens driftplats.`;
  const said: Record<string, string> = {
    waiting: "väntar på trafikledningen",
    approved: "godkänd",
    refused: "nekad",
    revoked: "återkallad",
  };
  return `${part.name} i Hubben (${found.place}): ${said[found.status] ?? found.status}.`;
}

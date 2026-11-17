// Ställverket at level 0 (TKL12, TKL21): Tåg · Klarering · Händelser, worked out from the hub's
// snapshot alone. TKL owns no clearance and no timetable (KLAR-09): it shows what the snapshot
// says and offers what `allowed_actions` allows, nothing else. These are pure functions, so the
// screen and its tests read the same thing.
import type { Action, CallHere, Clearance, Neighbour, Outside, SectionHere, Snapshot, TrainOnSection } from "./api";

export const SIDE: Record<string, string> = { left: "Väster", right: "Öster" };
export const TRACKS: Record<string, string> = { single: "enkelspår", double: "dubbelspår" };

/** A place's name from the snapshot, or its id. */
export function nameOf(snapshot: Snapshot, place: string | null | undefined): string {
  if (!place) return "";
  const found = [snapshot.place, ...snapshot.all_places, ...snapshot.neighbours].find((n) => n.place === place);
  return found?.name ?? place;
}

export function allows(call: CallHere | undefined, action: Action): boolean {
  return !!call && call.allowed_actions.includes(action);
}

export type Coming = { train: TrainOnSection; call: CallHere | undefined; from: string; exit: string | null };
export type AtStation = { call: CallHere; to: string; waitingFor: string | null };
export type Left = { train: TrainOnSection; to: string; exit: string | null };
export type Next = { call: CallHere; time: string; kind: "Ank" | "Avg"; other: string };

export type Trains = { coming: Coming[]; atStation: AtStation[]; left: Left[]; next: Next[] };

function exitTowards(snapshot: Snapshot, section: string): string | null {
  return snapshot.sections.find((s) => s.section === section)?.exit ?? null;
}

/** Tåg (H22, H32): on its way here, at the station, has left, and next by the timetable. */
export function trains(snapshot: Snapshot): Trains {
  const all: CallHere[] = snapshot.calls;
  const calls = new Map(all.map((call) => [call.call, call]));
  const coming = snapshot.on_the_way.map((train) => ({
    train,
    call: calls.get(train.call),
    from: nameOf(snapshot, train.other_place),
    exit: exitTowards(snapshot, train.section),
  }));
  const left = snapshot.have_left.map((train) => ({
    train,
    to: nameOf(snapshot, train.other_place),
    exit: exitTowards(snapshot, train.section),
  }));
  const busy = new Set(snapshot.on_the_way.map((t) => t.call));
  const atStation: AtStation[] = [];
  const next: Next[] = [];
  for (const call of all) {
    if (busy.has(call.call) || call.departure_state === "departed") continue;
    const arrived = call.arrival_state === "arrived";
    const startsHere = !call.from_place;
    const underway = call.departure_state === "requested" || call.departure_state === "cleared";
    const setAside = arrived && !call.to_place && !allows(call, "train.set_aside");
    if (setAside) continue;
    if (arrived || (startsHere && (underway || call.positioned))) {
      const clearance = mine(snapshot, call);
      atStation.push({
        call,
        to: nameOf(snapshot, call.to_place),
        waitingFor: clearance && clearance.status === "waiting" ? nameOf(snapshot, clearance.to_place) : null,
      });
    } else if (call.arrival_state === "none") {
      const arriving = !startsHere && !!call.arrival;
      next.push({
        call,
        time: (arriving ? call.arrival : call.departure) ?? "",
        kind: arriving ? "Ank" : "Avg",
        other: nameOf(snapshot, arriving ? call.from_place : call.to_place),
      });
    }
  }
  return { coming, atStation, left, next: next.slice(0, 8) };
}

/** This place's own clearance for a call that leaves from here. */
function mine(snapshot: Snapshot, call: CallHere): Clearance | undefined {
  return snapshot.clearances.find(
    (c) => c.call === call.call && c.from_place === snapshot.place.place && c.status !== "cancelled" && c.status !== "rejected",
  );
}

export type Block = {
  section: SectionHere;
  neighbour: Neighbour | undefined;
  heading: string;
  /** Requests from here, waiting for the neighbour's answer: Återta. */
  asked: Clearance[];
  /** Clearances given to here: the train may leave. */
  cleared: Clearance[];
  /** Trains the neighbour has clearance for, here: on their way soon. */
  clearedIn: Clearance[];
  /** Requests to here, waiting for this station: Ge klart or Neka. */
  incoming: Clearance[];
  /** The train that could ask for the line now: Begär. */
  canAsk: CallHere | undefined;
  /** Linjen ledig from the neighbour, not yet acknowledged. */
  lineFree: string[];
  free: boolean;
};

/** Klarering: one block per section, named after the neighbour and the station's exit. */
export function blocks(snapshot: Snapshot, outside: Outside | null): Block[] {
  const here = snapshot.place.place;
  return snapshot.sections.map((section) => {
    const neighbour = snapshot.neighbours.find((n) => n.place === section.other_place);
    const exit = section.exit ? outside?.exits.find((e) => e.id === section.exit) : undefined;
    const open = snapshot.clearances.filter((c) => c.section === section.section && c.status !== "cancelled" && c.status !== "rejected");
    const asked = open.filter((c) => c.from_place === here && c.status === "waiting");
    const cleared = open.filter((c) => c.from_place === here && c.status === "approved" && !c.departed);
    const incoming = open.filter((c) => c.to_place === here && c.status === "waiting");
    const clearedIn = open.filter((c) => c.to_place === here && c.status === "approved" && !c.departed);
    const all: CallHere[] = snapshot.calls;
    const canAsk = all.find(
      (call) =>
        call.to_place === section.other_place &&
        call.departure_state === "planned" &&
        (call.arrival_state === "arrived" || !call.from_place) &&
        allows(call, "clearance.request"),
    );
    const name = neighbour?.name ?? section.other_code;
    const exitName = section.exit ? ` ${section.exit}` : "";
    return {
      section,
      neighbour,
      heading: `${name}${exitName} · ${TRACKS[section.tracks] ?? section.tracks}${exit?.side ? ` · ${SIDE[exit.side]?.toLowerCase()}` : ""}${section.clearance_mode === "direct" ? " · direkt" : ""}`,
      asked,
      cleared,
      clearedIn,
      incoming,
      canAsk,
      lineFree: snapshot.line_messages.filter((m) => m.section === section.section && !m.acknowledged).map((m) => m.message_id),
      free: !section.occupied && !open.length,
    };
  });
}

/** The hub's clock, run on locally between snapshots when it runs (×speed). */
export function clockAt(snapshot: Snapshot, heardMs: number, nowMs: number): string {
  const { clock } = snapshot;
  const seconds = clock.running ? clock.seconds + ((nowMs - heardMs) / 1000) * clock.speed : clock.seconds;
  const minutes = Math.floor(seconds / 60);
  const hh = Math.floor(minutes / 60) % 24;
  const mm = minutes % 60;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

/** A command's expected revision: the call's or the clearance's own number (v2 §5). */
export function revisionOf(action: Action, call: CallHere | undefined, clearance: Clearance | undefined) {
  if (clearance && (action === "clearance.response" || action === "clearance.cancel")) {
    return { scope: "case" as const, key: clearance.clearance_id, value: clearance.revision };
  }
  if (call) return { scope: "call" as const, key: call.call, value: call.revision };
  return null;
}

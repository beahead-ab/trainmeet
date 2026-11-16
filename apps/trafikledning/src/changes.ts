// Driftändringar (DRIFT-41, TRAFIK-02, H43): the ten kinds, what Nu says about each, and the
// form's fields turned into a change. Without React, so that it can be tested on its own.
import type { components } from "../../../contracts/types";
import type { Now, Weekday } from "./api";
import { callsOf, changeText, placeName, placesOf, sectionName, trainsOf, WEEKDAYS, type DriftChange, type Package } from "@trainmeet/hubben";

export { callsOf, changeText, placeName, placesOf, sectionName, trainsOf, type DriftChange, type Package };

type Schemas = components["schemas"];
export type ChangeNow = Schemas["trainmeet.drift-1.now.ChangeNow"];
export type ChangeKind = DriftChange["kind"];

/** The ten tiles of Ny driftändring, as the prototype names them. */
export const KINDS: [ChangeKind, string, string][] = [
  ["cancel", "Ställ in tåg", "tåget körs inte"],
  ["extra", "Extratåg", "nytt eller kopia av ett tåg"],
  ["times", "Ändrade tider", "per driftplats eller hela tåget"],
  ["place", "Ändrade driftplatser eller sträckor", "stängd sträcka, obemannad, klareringsläge"],
  ["track", "Ändrat planerat spår", "annat spår på en driftplats"],
  ["tracks", "Enkel eller dubbel sträcka", "hur sträckan körs"],
  ["days", "Ändrade trafikdagar", "vilka dagar tåget går"],
  ["number", "Byte av tågnummer", "samma tåg, nytt nummer"],
  ["no_stop", "Ej uppehåll", "genomfart utan stopp"],
  ["note", "Anmärkning", "text som följer tåget"],
];

const PROPOSALS: Record<string, string> = {
  waiting: "förslaget väntar i Planering",
  taken: "tagen med i nästa version",
  rejected: "avslagen i Planering",
  withdrawn: "förslaget återtaget",
};

/** Where a change stands, and Planering's answer to it (4.4). */
export function statusText(change: ChangeNow): string {
  const proposal = change.proposal ? ` · ${PROPOSALS[change.proposal] ?? change.proposal}` : "";
  if (change.status === "dropped") return "Släppt" + proposal;
  if (change.status === "waiting") return (change.waiting_for?.length ? `Väntar på tåg ${change.waiting_for.join(", ")}` : "Väntar") + proposal;
  return (change.forced ? "Gäller, tvingad igenom" : "Gäller") + proposal;
}

// --- The form ------------------------------------------------------------------------------------

export type Draft = {
  kind: ChangeKind;
  train: string;
  call: string;
  number: string;
  departure: string;
  copy: boolean;
  copyOf: string;
  from: string;
  to: string;
  minutes: string;
  section: string;
  sectionChange: "closed" | "open" | "requested" | "direct";
  onSection: boolean;
  place: string;
  placeKind: "manned" | "unmanned";
  track: string;
  tracks: "single" | "double";
  days: Weekday[];
  stops: boolean;
  text: string;
};

export const emptyDraft = (kind: ChangeKind, now: Now | null): Draft => ({
  kind,
  train: "",
  call: "",
  number: "",
  departure: now?.clock.time ?? "",
  copy: true,
  copyOf: "",
  from: "",
  to: "",
  minutes: "",
  section: "",
  sectionChange: "closed",
  onSection: true,
  place: "",
  placeKind: "unmanned",
  track: "",
  tracks: "double",
  days: now ? [now.traffic_day] : [],
  stops: false,
  text: "",
});

const TIME = /^([01]\d|2[0-3]):[0-5]\d$/;

/** The change the form describes, or what is missing, said to the dispatcher. */
export function buildChange(draft: Draft): DriftChange | string {
  const train = draft.train;
  const needTrain = "Välj ett tåg.";
  switch (draft.kind) {
    case "cancel":
      return train ? { kind: "cancel", train } : needTrain;
    case "extra": {
      if (!draft.number.trim()) return "Skriv tågnumret.";
      if (!TIME.test(draft.departure)) return "Skriv avgångstiden som TT:MM.";
      const days = draft.days.length ? draft.days : null;
      if (draft.copy) return draft.copyOf ? { kind: "extra", number: draft.number.trim(), departure: draft.departure, copy_of: draft.copyOf, from_place: null, to_place: null, days } : "Välj tåget att kopiera.";
      if (!draft.from || !draft.to) return "Välj från och till.";
      if (draft.from === draft.to) return "Från och till är samma driftplats.";
      return { kind: "extra", number: draft.number.trim(), departure: draft.departure, copy_of: null, from_place: draft.from, to_place: draft.to, days };
    }
    case "times": {
      const minutes = Number(draft.minutes);
      if (!train) return needTrain;
      if (!Number.isInteger(minutes) || minutes === 0 || Math.abs(minutes) > 720) return "Skriv hur många minuter, till exempel 10 eller −5.";
      return { kind: "times", train, minutes, from_call: draft.call || null, calls: [] };
    }
    case "place":
      if (draft.onSection) {
        if (!draft.section) return "Välj en sträcka.";
        const closed = draft.sectionChange === "closed" ? true : draft.sectionChange === "open" ? false : null;
        const mode = draft.sectionChange === "requested" || draft.sectionChange === "direct" ? draft.sectionChange : null;
        return { kind: "place", section: draft.section, closed, clearance_mode: mode, place: null, place_kind: null };
      }
      return draft.place ? { kind: "place", section: null, closed: null, clearance_mode: null, place: draft.place, place_kind: draft.placeKind } : "Välj en driftplats.";
    case "track":
      if (!draft.call) return "Välj tåget och driftplatsen.";
      return draft.track ? { kind: "track", call: draft.call, track: draft.track } : "Välj spåret.";
    case "tracks":
      return draft.section ? { kind: "tracks", section: draft.section, tracks: draft.tracks } : "Välj en sträcka.";
    case "days":
      if (!train) return needTrain;
      return draft.days.length ? { kind: "days", train, days: draft.days } : "Välj minst en dag.";
    case "number":
      if (!train) return needTrain;
      return draft.number.trim() ? { kind: "number", train, number: draft.number.trim() } : "Skriv det nya numret.";
    case "no_stop":
      return draft.call ? { kind: "no_stop", call: draft.call, stops: draft.stops } : "Välj tåget och driftplatsen.";
    case "note":
      return train ? { kind: "note", train, call: draft.call || null, text: draft.text.trim() || null } : needTrain;
  }
}

/** The trains a draft points at that are out or have an open clearance: the change waits. */
export function busyTrains(draft: Draft, pkg: Package | null, now: Now | null): string[] {
  if (!now || !pkg) return [];
  let number: string | undefined;
  if (["cancel", "times", "days", "number"].includes(draft.kind)) number = (pkg.trains ?? []).find((t) => t.id === draft.train)?.number;
  if (["track", "no_stop"].includes(draft.kind)) number = (pkg.trains ?? []).find((t) => t.calls.some((c) => c.id === draft.call))?.number;
  const section = draft.kind === "tracks" || (draft.kind === "place" && draft.onSection) ? draft.section : "";
  return [
    ...new Set(
      now.clearances
        .filter((c) => (number && c.train_number === number) || (section && c.section === section))
        .map((c) => c.train_number),
    ),
  ];
}

export { WEEKDAYS };

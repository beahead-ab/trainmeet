// Driftändringar (DRIFT-41) as people read them: one line per change, in Nu, Logg and
// Planering's Versioner (4.4). Shared, so that Drift and Planering say the same thing.
import type { components } from "../../../contracts/types";
import type { Weekday } from "./api";
import { dayName } from "./traff";

type Schemas = components["schemas"];
export type DriftChange = Schemas["trainmeet.drift-1.make-change"]["change"];
export type Package = Schemas["trainmeet.meet-1"];

const halt = (pkg: Package, place: string) => pkg.places.find((p) => p.id === place)?.kind === "halt";
export const trainsOf = (pkg: Package) => [...(pkg.trains ?? [])].sort((a, b) => a.number.localeCompare(b.number, "sv", { numeric: true }));
/** A train's calls where it can be cleared: not at halts along a section. */
export const callsOf = (pkg: Package, train: string) => ((pkg.trains ?? []).find((t) => t.id === train)?.calls ?? []).filter((call) => !halt(pkg, call.place));
export const placesOf = (pkg: Package) => pkg.places.filter((place) => place.kind !== "halt");
export const placeName = (pkg: Package | null, id: string | null | undefined) => pkg?.places.find((place) => place.id === id)?.name ?? id ?? "";
const code = (pkg: Package | null, id: string) => pkg?.places.find((place) => place.id === id)?.code ?? id;
export const sectionName = (pkg: Package | null, id: string | null | undefined) => {
  const section = (pkg?.sections ?? []).find((s) => s.id === id);
  return section ? `${code(pkg, section.place_a)}–${code(pkg, section.place_b)}` : (id ?? "");
};
const callPlace = (pkg: Package | null, call: string | null | undefined) => {
  for (const train of pkg?.trains ?? []) {
    const found = train.calls.find((c) => c.id === call);
    if (found) return placeName(pkg, found.place);
  }
  return call ?? "";
};
const trainNumber = (pkg: Package | null, id: string, fallback?: string | null) => fallback ?? (pkg?.trains ?? []).find((t) => t.id === id)?.number ?? id;
const days = (list: Weekday[]) => list.map((day) => dayName(day)).join(", ");

/** What a change does, in a line, as Nu lists it and Logg says it. */
export function changeText(change: DriftChange, pkg: Package | null, number?: string | null): string {
  switch (change.kind) {
    case "cancel":
      return `Inställt tåg ${trainNumber(pkg, change.train, number)}`;
    case "extra": {
      // A service run after the paper, approved: its own calls, marked so (LOK-13).
      const calls = change.calls ?? [];
      if (change.paper && calls.length) return `Extratåg ${change.number} efter pappret ${placeName(pkg, calls[0]!.place)}–${placeName(pkg, calls.at(-1)!.place)} kl. ${change.departure}`;
      return change.copy_of
        ? `Extratåg ${change.number}, kopia av ${trainNumber(pkg, change.copy_of)} kl. ${change.departure}`
        : `Extratåg ${change.number} ${placeName(pkg, change.from_place)}–${placeName(pkg, change.to_place)} kl. ${change.departure}`;
    }
    case "times": {
      const minutes = change.minutes ? `${change.minutes > 0 ? "+" : "−"}${Math.abs(change.minutes)} min` : "nya tider";
      return `Tåg ${trainNumber(pkg, change.train, number)}: ${minutes}${change.from_call ? ` från ${callPlace(pkg, change.from_call)}` : ""}`;
    }
    case "place":
      if (change.section) {
        const what = change.closed === true ? "stängd" : change.closed === false ? "öppen igen" : `klareras ${change.clearance_mode === "direct" ? "direkt" : "med begäran"}`;
        return `Sträckan ${sectionName(pkg, change.section)} ${what}`;
      }
      return `${placeName(pkg, change.place)} ${change.place_kind === "unmanned" ? "obemannad, sköts av automatiken" : "bemannad"}`;
    case "track":
      return `Tåg ${number ?? ""} i ${callPlace(pkg, change.call)}: spår ${change.track}`.replace("Tåg  i", "Spår i");
    case "tracks":
      return `Sträckan ${sectionName(pkg, change.section)} ${change.tracks === "double" ? "dubbelspårig" : "enkelspårig"}`;
    case "days":
      return `Tåg ${trainNumber(pkg, change.train, number)} går ${days(change.days)}`;
    case "number":
      return `Tåg ${number ?? ""} får nummer ${change.number}`.replace("Tåg  får", "Nytt tågnummer");
    case "no_stop":
      return `Tåg ${number ?? ""} ${change.stops ? "stannar i" : "passerar utan uppehåll"} ${callPlace(pkg, change.call)}`.replace("Tåg  ", "");
    case "note":
      return change.text ? `Anmärkning på tåg ${trainNumber(pkg, change.train, number)}: ${change.text}` : `Anmärkningen på tåg ${trainNumber(pkg, change.train, number)} borttagen`;
  }
}

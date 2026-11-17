import type { Now } from "./api";
import { between, minutesOf, type Leg, type Traffic } from "./bana";

// The next things that happen on the whole line, and the numbers above the line: the same on the
// screens' Översikt (SKARM-18) and on the participant page (DELT-01), in the page's language.

export type Happening = { minute: number; number: string; text: string; note: string | null; leg: Leg };

export type Words = {
  arrives: (place: string, track: string | null) => string;
  departs: (from: string, to: string) => string;
  waiting: string;
  cleared: string;
  now: string;
  inMinutes: (minutes: number) => string;
  numbers: [string, string, string, string];
};

export const SWEDISH: Words = {
  arrives: (place, track) => `ankommer ${place}${track ? ` spår ${track}` : ""}`,
  departs: (from, to) => `avgår ${from} mot ${to}`,
  waiting: "väntar på svar",
  cleared: "klart",
  now: "nu",
  inMinutes: (minutes) => `om ${minutes} min`,
  numbers: ["tåg på linjen", "tåg inne på driftplatserna", "väntar på svar", "klart, inte avgått"],
};

export const ENGLISH: Words = {
  arrives: (place, track) => `arrives ${place}${track ? ` track ${track}` : ""}`,
  departs: (from, to) => `leaves ${from} for ${to}`,
  waiting: "waiting for an answer",
  cleared: "cleared",
  now: "now",
  inMinutes: (minutes) => `in ${minutes} min`,
  numbers: ["trains on the line", "trains at the places", "waiting for an answer", "cleared, not yet left"],
};

/** The next things that happen, from now on: departures, the trains that wait for an answer,
 * and arrivals of those on the line. */
export function nextHappenings(seen: Now, names: Map<string, string>, count = 4, words: Words = SWEDISH): Happening[] {
  const clock = minutesOf(seen.clock.time) ?? 0;
  const name = (id: string) => names.get(id) ?? id;
  const found: Happening[] = [];
  for (const leg of seen.legs) {
    if (leg.state === "on_the_way" && leg.arrival) found.push({ minute: minutesOf(leg.arrival) ?? 0, number: leg.train_number, text: words.arrives(name(leg.to_place), leg.track ?? null), note: null, leg });
    else if ((leg.state === "planned" || leg.state === "requested" || leg.state === "cleared") && leg.departure) {
      found.push({ minute: minutesOf(leg.departure) ?? 0, number: leg.train_number, text: words.departs(name(leg.from_place), name(leg.to_place)), note: leg.state === "requested" ? words.waiting : leg.state === "cleared" ? words.cleared : null, leg });
    }
  }
  return found
    .map((item) => ({ item, away: between(clock, item.minute) }))
    .filter(({ item, away }) => away >= 0 || item.leg.state !== "planned")
    .filter(({ away }) => away >= -10 && away <= 180)
    .sort((a, b) => a.away - b.away)
    .slice(0, count)
    .map(({ item, away }) => ({ ...item, note: item.note ?? (away <= 0 ? words.now : words.inMinutes(away)) }));
}

/** The four numbers along the top. */
export function numbers(traffic: Traffic, words: Words = SWEDISH): [number, string][] {
  const inside = [...traffic.tracks.values()].flatMap((tracks) => [...tracks.values()].flat()).filter((entry) => entry.state !== "coming").length + [...traffic.yards.values()].reduce((sum, count) => sum + count, 0);
  return [
    [traffic.online.length, words.numbers[0]],
    [inside, words.numbers[1]],
    [traffic.requested.length, words.numbers[2]],
    [traffic.cleared.length, words.numbers[3]],
  ];
}

// The körplan as moments on a time axis (LOK-03): the arrivals, departures and passes of the
// service in order, the NU-line between them on Drift's clock (LOK-12), the next stop, and the
// marks that last a while on the meet clock (LOK-24, LOK-41). Ported from the old Lokföraren's
// korplan.js: drawing only, no decisions about the traffic (LOK-11).
import type { KorplanRow, Start, TrainPosition } from "./api";
import { CHANGED_MINUTES, REMINDERS } from "./api";
import { DAY, timeSeconds } from "./clock";

export type MomentKind = "arrival" | "departure" | "pass";
/** unknown: a time that stood on the paper but could not be read (LOK-29). It is shown as
 * unknown, never guessed; on the axis it stands just before the next time that was read, so it
 * counts as passed only once that one has. */
export type Moment = { t: number; kind: MomentKind; row: KorplanRow; index: number; unknown?: boolean };

/** The service's moments in time order, on a running axis: a time more than six hours before
 * the one before has gone past midnight. The service begins with a departure and ends with an
 * arrival; a call the train passes is one moment. unreadable: the rows of a körplan after the
 * paper whose times could not be read, kept with an unknown time in their place. */
export function momentsOf(rows: KorplanRow[], unreadable: (index: number) => boolean = () => false): Moment[] {
  const moments: Moment[] = [];
  let last: number | null = null;
  const onAxis = (value: string | null | undefined): number | null => {
    let t = timeSeconds(value);
    if (t === null) return null;
    while (last !== null && t < last - 6 * 3600) t += DAY;
    last = t;
    return t;
  };
  const add = (kind: MomentKind, row: KorplanRow, index: number, value: string | null | undefined, keep: boolean) => {
    const t = onAxis(value);
    if (t !== null) moments.push({ t, kind, row, index });
    else if (keep && unreadable(index)) moments.push({ t: Number.NaN, kind, row, index, unknown: true });
  };
  rows.forEach((row, index) => {
    const first = index === 0;
    if (!row.stops) {
      add("pass", row, index, row.departure ?? row.arrival, true);
      return;
    }
    if (!first && (row.arrival || !row.last || !row.departure)) add("arrival", row, index, row.arrival, true);
    if (!row.last) add("departure", row, index, row.departure, true);
    if (row.last && !row.arrival && row.departure) add("arrival", row, index, row.departure, false);
  });
  // An unknown time stands just before the next time that was read (or after the last one).
  let next: number | null = null;
  for (let i = moments.length - 1; i >= 0; i -= 1) {
    const moment = moments[i]!;
    if (!moment.unknown) next = moment.t;
    else if (next !== null) moment.t = next;
  }
  let before = 0;
  for (const moment of moments) {
    if (!moment.unknown) before = moment.t;
    else if (Number.isNaN(moment.t)) moment.t = before;
  }
  return moments;
}

/** The meet clock's seconds laid on the service's axis: the turn of the day nearest the service
 * (the clock may pass 24 h, and a service may pass midnight). */
export function onAxis(clockSeconds: number, from: number, to: number = from): number {
  const middle = (from + to) / 2;
  const base = ((clockSeconds % DAY) + DAY) % DAY;
  let best = clockSeconds;
  for (const candidate of [base - DAY, base, base + DAY, base + 2 * DAY, clockSeconds]) {
    if (Math.abs(candidate - middle) < Math.abs(best - middle)) best = candidate;
  }
  return best;
}

export function axisNow(moments: Moment[], clockSeconds: number): number {
  if (!moments.length) return clockSeconds;
  return onAxis(clockSeconds, moments[0]!.t, moments[moments.length - 1]!.t);
}

/** Where the NU-line stands: before the moment at index (moments.length after the last), and
 * how far it has come from the moment before, 0 to 1. Only Drift's clock moves it. */
export function nuPosition(moments: Moment[], now: number): { index: number; fraction: number } {
  const index = moments.findIndex((moment) => moment.t > now);
  if (index === -1) return { index: moments.length, fraction: 0 };
  if (index === 0) return { index: 0, fraction: 0 };
  const before = moments[index - 1]!.t;
  const after = moments[index]!.t;
  return { index, fraction: after > before ? Math.min(1, Math.max(0, (now - before) / (after - before))) : 0 };
}

export type NextStop = { moment: Moment; passes: Moment[] };

/** The next arrival or departure after now, and the places passed on the way there. */
export function nextStop(moments: Moment[], now: number): NextStop | null {
  const { index } = nuPosition(moments, now);
  const passes: Moment[] = [];
  for (const moment of moments.slice(index)) {
    if (moment.kind === "pass") passes.push(moment);
    else return { moment, passes };
  }
  return null;
}

/** The call the driver may say Framme at: where the train stands by the plan, or the next
 * arrival once the train is out on the line. With Drift's reality, the stations' word on where
 * the train is goes first. Before the first departure there is none. */
export function frammeRow(moments: Moment[], now: number, position: TrainPosition | null = null): KorplanRow | null {
  if (position) {
    if (position.state !== "on_the_way") return null;
    return moments.find((m) => m.kind === "arrival" && m.row.train === position.train && m.row.place === position.to_place)?.row ?? null;
  }
  const { index } = nuPosition(moments, now);
  const next = moments[index];
  const before = moments[index - 1];
  if (next?.kind === "departure" && before?.kind === "arrival" && before.row.call === next.row.call) return before.row;
  if (!next && before?.kind === "arrival") return before.row;
  if (!onLineByPlan(moments, now)) return null;
  return moments.slice(index).find((moment) => moment.kind === "arrival")?.row ?? null;
}

/** May the driver say Framme here (LOK-39): only when the game has chosen it, and only at a
 * place nobody works. */
export function frammeAllowed(row: KorplanRow | null, arrival: boolean): boolean {
  return Boolean(row && arrival && row.unmanned);
}

/** By the plan, the train is out on the line now: between a departure and the next arrival of
 * the same train. */
export function onLineByPlan(moments: Moment[], now: number): boolean {
  const { index } = nuPosition(moments, now);
  const before = moments[index - 1];
  const next = moments[index];
  if (!before || !next || before.row.train !== next.row.train) return false;
  return before.kind !== "arrival" && next.kind !== "departure";
}

/** Ändrat stays for ten game minutes (LOK-41): from when the hub first said it, on the meet
 * clock. The hub's next answer has the last word. */
export class ChangedMarks {
  private seen = new Map<string, number>();

  note(rows: KorplanRow[], now: number): void {
    for (const row of rows) {
      if (row.changed && !this.seen.has(row.call)) this.seen.set(row.call, now);
      if (!row.changed) this.seen.delete(row.call);
    }
  }

  shows(row: KorplanRow, now: number): boolean {
    if (!row.changed) return false;
    const since = this.seen.get(row.call) ?? now;
    return now - since < CHANGED_MINUTES * 60;
  }
}

export type Countdown = { game: number; real: number | null; starts: number };

/** Game seconds to the start on Drift's clock, and the real seconds with the clock's speed. */
export function countdown(start: Start, clockSeconds: number, speed: number, running: boolean): Countdown {
  const now = onAxis(clockSeconds, start.seconds);
  const game = start.seconds - now;
  return { game, real: running && speed > 0 ? game / speed : null, starts: start.seconds };
}

/** The reminder due now, 20 or 10 game minutes before the start, once each (LOK-41). */
export function dueReminder(gameSecondsLeft: number, fired: readonly number[]): number | null {
  for (const minutes of REMINDERS) {
    if (fired.includes(minutes)) continue;
    if (gameSecondsLeft <= minutes * 60 && gameSecondsLeft > (minutes - 2) * 60) return minutes;
  }
  return null;
}

/** Whole minutes, rounded up, never below zero. */
export const wholeMinutes = (seconds: number) => Math.max(0, Math.ceil(seconds / 60));

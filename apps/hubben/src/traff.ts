// The meet as the header shows it, without React: the clock, the meet's name and the meets
// Byt träff offers. The same words as the old pages (hub/static/drift.js).
import type { Client, MeetSummary, Now, Weekday } from "./api";

export const WEEKDAYS: [Weekday, string][] = [
  ["mon", "Måndag"],
  ["tue", "Tisdag"],
  ["wed", "Onsdag"],
  ["thu", "Torsdag"],
  ["fri", "Fredag"],
  ["sat", "Lördag"],
  ["sun", "Söndag"],
];
const SHORT_DAYS: Record<Weekday, string> = { mon: "mån", tue: "tis", wed: "ons", thu: "tor", fri: "fre", sat: "lör", sun: "sön" };

const pad = (value: number) => String(value).padStart(2, "0");

/** The meet clock: it runs on between the hub's answers, at the meet's speed, over midnight. */
export function clockText(now: Now | null, elapsedMs: number): string {
  if (!now) return "--:--";
  const { clock } = now;
  const passed = clock.running ? (elapsedMs / 1000) * clock.speed : 0;
  const minutes = Math.floor((clock.seconds + passed) / 60) % 1440;
  return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`;
}

/** The small text after the clock in the header: the traffic day and the speed. */
export const clockNote = (now: Now) => `${SHORT_DAYS[now.traffic_day]} · ×${now.clock.speed}`;

export const dayName = (day: Weekday) => (WEEKDAYS.find(([key]) => key === day)?.[1] ?? day).toLowerCase();

/** The meet's name in the header: Provbanan as it is, a meet from Planering with its version. */
export const meetTitle = (now: Now) => (now.meet_id === "provbanan" ? now.name : `${now.name} · version ${now.version}`);

/** One meet the hub can run: a published version from Planering, or Provbanan (steg 4a). */
export type MeetChoice = { value: string; meet: string; version: number; name: string; note: string };

export const PROVBANAN: MeetChoice = { value: "provbanan:1", meet: "provbanan", version: 1, name: "Provbanan", note: "för prov" };

export function meetChoices(meets: MeetSummary[]): MeetChoice[] {
  const choices: MeetChoice[] = [];
  for (const summary of meets) {
    // A withdrawn version can no longer be started (PLAN-18).
    for (const version of (summary.versions ?? []).filter((v) => !v.withdrawn).reverse()) {
      choices.push({
        value: `${summary.meet.id}:${version.number}`,
        meet: summary.meet.id,
        version: version.number,
        name: summary.meet.name,
        note: `version ${version.number}`,
      });
    }
  }
  return [...choices, PROVBANAN];
}

/** The meet asked for in the address (Kör i Drift in Planering), if the hub has it. */
export function askedChoice(search: string, choices: MeetChoice[]): string | null {
  const wanted = new URLSearchParams(search);
  const meet = wanted.get("traff");
  if (!meet) return null;
  const value = `${meet}:${wanted.get("version") ?? ""}`;
  return choices.some((choice) => choice.value === value) ? value : null;
}

export const runningChoice = (now: Now | null) => (now ? `${now.meet_id}:${now.version}` : null);

export const waitingCount = (clients: Client[]) => clients.filter((client) => client.status === "waiting").length;

// Händelser (KLAR-05): what happens at the station, latest first. The hub sends no history to a
// station, so TKL writes its own journal from what changes between two snapshots, as the old TKL
// did (trainmeet-clearance, journal rows from a poll). The time is the meet's clock.
import type { Snapshot } from "./api";
import { nameOf } from "./niva0";

export type Happening = { id: string; time: string; text: string; sound?: Sound };
export type Sound = "request" | "coming" | "alarm";

const key = (...parts: (string | number)[]) => parts.join(":");

/** What happened between before and now. None the first time: the journal starts empty. */
export function happenings(before: Snapshot | null, now: Snapshot): Happening[] {
  if (!before) return [];
  const time = now.clock.time.slice(0, 5);
  const here = now.place.place;
  const found: Happening[] = [];
  const add = (id: string, text: string, sound?: Sound) => found.push({ id: key(id, now.place_revision), time, text, sound });

  if (before.clock.running !== now.clock.running) {
    add("clock", now.clock.running ? "Trafikledningen startade klockan" : "Trafikledningen stoppade klockan");
  }
  const old = new Map(before.clearances.map((c) => [c.clearance_id, c]));
  for (const c of now.clearances) {
    const was = old.get(c.clearance_id);
    const from = nameOf(now, c.from_place);
    const to = nameOf(now, c.to_place);
    if (!was) {
      if (c.to_place === here && c.status === "waiting") add(key("req", c.clearance_id), `${from} begär klart för ${c.train_number} hit`, "request");
      if (c.to_place === here && c.status === "approved") add(key("direct", c.clearance_id), `${from} fick klart för ${c.train_number} hit (direkt)`);
      if (c.from_place === here) add(key("ask", c.clearance_id), `Du begärde klart för ${c.train_number} mot ${to}`);
      continue;
    }
    if (was.status !== c.status) {
      if (c.from_place === here && c.status === "approved") add(key("ok", c.clearance_id), `${to} gav klart för ${c.train_number}`);
      if (c.from_place === here && c.status === "rejected") add(key("no", c.clearance_id), `${to} nekade ${c.train_number}`, "alarm");
      if (c.to_place === here && c.status === "approved") add(key("gave", c.clearance_id), `Du gav klart för ${c.train_number} från ${from}`);
      if (c.to_place === here && c.status === "rejected") add(key("refused", c.clearance_id), `Du nekade ${c.train_number} från ${from}`);
      if (c.status === "cancelled") add(key("cancel", c.clearance_id), `Klareringen för ${c.train_number} återtogs`);
      if (c.status === "invalidated") add(key("invalid", c.clearance_id), `Klareringen för ${c.train_number} gäller inte längre (spårbyte)`, "alarm");
    }
    if (c.reminders > was.reminders && c.status === "waiting") {
      const who = c.to_place === here ? `${from} väntar på svar för ${c.train_number}` : `${to} har inte svarat för ${c.train_number}`;
      add(key("remind", c.clearance_id, c.reminders), `Påminnelse: ${who}`, "alarm");
    }
  }
  const coming = new Set(before.on_the_way.map((t) => t.call));
  for (const t of now.on_the_way) {
    if (!coming.has(t.call)) {
      const track = t.planned_track ? ` mot spår ${t.planned_track}` : "";
      add(key("coming", t.call), `${t.train_number} avgick från ${nameOf(now, t.other_place)}${track}`, "coming");
    }
  }
  const left = new Set(before.have_left.map((t) => t.call));
  for (const t of now.have_left) {
    if (!left.has(t.call)) add(key("left", t.call), `${t.train_number} avgick mot ${nameOf(now, t.other_place)}`);
  }
  const calls = new Map(before.calls.map((c) => [c.call, c]));
  for (const c of now.calls) {
    const was = calls.get(c.call);
    if (!was) continue;
    if (was.arrival_state !== "arrived" && c.arrival_state === "arrived") {
      add(key("in", c.call), `${c.train_number} ankom${c.track ? ` spår ${c.track}` : ""} (knapp)`);
    } else if (was.track !== c.track && c.track) {
      add(key("track", c.call), `${c.train_number} till spår ${c.track}`);
    }
  }
  const lines = new Set(before.line_messages.map((m) => m.message_id));
  for (const m of now.line_messages) {
    if (!lines.has(m.message_id) && !m.acknowledged) add(key("line", m.message_id), `${nameOf(now, m.from_place)}: linjen ledig`, "request");
  }
  return found.reverse();
}

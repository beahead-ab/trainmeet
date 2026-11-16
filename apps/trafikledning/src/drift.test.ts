import { describe as group, expect, it } from "vitest";
import type { Client, DriftEvent, Now } from "./api";
import { waitingCount } from "@trainmeet/hubben";
import { actorName, clientDetails, clockAt, describe, hhmm, jumpNote, jumpText, minuteOf, modeText } from "./drift";

const now = {
  meet_id: "provbanan",
  name: "Provbanan",
  version: 1,
  traffic_day: "mon",
  game_day: 1,
  clock: { time: "23:58", seconds: 23 * 3600 + 58 * 60, running: true, speed: 4, game_day: 1 },
  places: [
    { place: "nby", code: "Nby", name: "Norrby" },
    { place: "sjv", code: "Sjv", name: "Sjövik" },
  ],
  legs: [{ leg: "t101-nby", train: "t101", train_number: "101", train_type: null, section: "s1", from_place: "nby", to_place: "sjv", departure: "06:00", arrival: "06:10", state: "planned", clearance_id: null, track: null }],
  clearances: [],
} as unknown as Now;

const client = (change: Partial<Client>) => ({ client_id: "c1", name: "Box 12", kind: "tmbox_web", status: "approved", places: [], side: "both", language: null, display: null, view: null, ...change }) as Client;

group("Klienter and Logg (TRAFIK-04, TRAFIK-07)", () => {
  it("says what a client is, where it works and how", () => {
    expect(clientDetails(client({ places: ["nby"], side: "left", display: { rows: 4, cols: 20 } as Client["display"], language: "en" }), now)).toBe("Webbox · Ansluten · Norrby · vänster · 20×4 · English");
    expect(clientDetails(client({ kind: "screen", status: "approved" }), now)).toBe("Skärm · Väntar på en vy");
    expect(clientDetails(client({ kind: "tkl", status: "waiting" }), now)).toBe("TKL · Väntar");
    expect(waitingCount([client({ status: "waiting" }), client({})])).toBe(1);
  });

  it("describes what happened and who did it", () => {
    const event = (kind: string, data: Record<string, unknown> = {}) => ({ kind, data }) as unknown as DriftEvent;
    expect(describe(event("clearance.answered", { approved: false }))).toBe("Begäran nekad");
    expect(describe(event("clock.speed", { speed: 4 }))).toBe("Ny hastighet 4×");
    expect(describe(event("train.arrived", { track: "2" }))).toBe("Ankomst spår 2");
    expect(describe(event("train.arrived", { track: "2", forward: true }))).toBe("Ankomst spår 2, flyttat fram");
    expect(describe(event("clearance.answered", { approved: true, forward: true }))).toBe("Klart givet, flyttat fram");
    expect(describe(event("clearance.reminded", { clearance_id: "c", count: 2 }))).toBe("Påminnelse 2, obesvarad begäran");
    expect(describe(event("clock.jump", { before: 21600, seconds: 30600, closed: ["c1", "c2"] }))).toBe("Tidshopp till 08:30, 2 klareringar stängda");
    expect(describe(event("clock.jump", { before: 21600, seconds: 30600, closed: ["c1"] }))).toBe("Tidshopp till 08:30, 1 klarering stängd");
    expect(describe(event("clock.jump", { before: 21600, seconds: 30600, closed: [] }))).toBe("Tidshopp till 08:30");
    expect(describe(event("clock.jump_undone", { jump: 7, seconds: 21660 }))).toBe("Tidshoppet ångrat, klockan åter 06:01");
    expect(describe(event("something.new"))).toBe("something.new");
    expect(actorName({ kind: "system", id: null }, [])).toBe("Hubben");
    expect(actorName({ kind: "dispatcher", id: null }, [])).toBe("Trafikledningen");
    expect(actorName({ kind: "client", id: "c1" } as never, [client({})])).toBe("Box 12");
    expect(actorName({ kind: "client", id: "c9" } as never, [])).toBe("c9");
  });

  it("says how Automatiken holds a place (F14, F15)", () => {
    const place = { place: "nby", name: "Norrby", code: "Nby", mode: "automatic", left_by: "dispatcher", takes_over_in: null, operator: null, present: [] } as never;
    expect(modeText(place, (id) => id)).toBe("Automatiken · lämnad av trafikledningen");
    const manned = { place: "nby", name: "Norrby", code: "Nby", mode: "no_contact", left_by: null, takes_over_in: 90, operator: "c1", present: [] } as never;
    expect(modeText(manned, () => "Box 12")).toBe("Kontakt saknas · automatiken tar över om 2 min · Box 12");
  });
});

group("Tidshopp (TRAFIK-01, H37, F6)", () => {
  it("reads and writes a minute of the game day", () => {
    expect([clockAt(0), clockAt(6 * 60 + 5), clockAt(1439)]).toEqual(["00:00", "06:05", "23:59"]);
    expect(hhmm(25 * 3600 + 120)).toBe("01:02");
    expect([minuteOf("06:05"), minuteOf("6:05"), minuteOf("24:00"), minuteOf("06:60"), minuteOf("")]).toEqual([365, 365, null, null, null]);
  });

  it("says what the jump does before, and what it did after", () => {
    expect(jumpNote(0)).toBe("Tågen ställs där tidtabellen har dem. Hoppet kan ångras.");
    expect(jumpNote(1)).toBe("Den öppna klareringen stängs, och tågen ställs där tidtabellen har dem. Hoppet kan ångras.");
    expect(jumpNote(3)).toBe("De 3 öppna klareringarna stängs, och tågen ställs där tidtabellen har dem. Hoppet kan ångras.");
    expect(jumpText({ from_time: "06:12", to_time: "08:00", closed: 2 })).toBe("Tidshopp från 06:12 till 08:00 · 2 klareringar stängdes");
    expect(jumpText({ from_time: "06:12", to_time: "08:00", closed: 0 })).toBe("Tidshopp från 06:12 till 08:00");
  });
});

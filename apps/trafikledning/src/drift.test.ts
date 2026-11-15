import { describe as group, expect, it } from "vitest";
import type { Client, DriftEvent, MeetSummary, Now } from "./api";
import { actorName, askedChoice, clientDetails, clockNote, clockText, describe, meetChoices, meetTitle, modeText, runningChoice, waitingCount } from "./drift";

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

group("the meet clock in the header (TRAFIK-12)", () => {
  it("runs on between the hub's answers at the meet's speed, over midnight", () => {
    expect(clockText(now, 0)).toBe("23:58");
    expect(clockText(now, 30_000)).toBe("00:00");
    expect(clockText({ ...now, clock: { ...now.clock, running: false } }, 60_000)).toBe("23:58");
    expect(clockText(null, 0)).toBe("--:--");
    expect(clockNote(now)).toBe("mån · ×4");
  });

  it("names Provbanan as it is and a meet from Planering with its version", () => {
    expect(meetTitle(now)).toBe("Provbanan");
    expect(meetTitle({ ...now, meet_id: "grimslov", name: "Grimslöv 2027", version: 6 })).toBe("Grimslöv 2027 · version 6");
  });
});

group("Byt träff (TRAFIK-29)", () => {
  const meets = [{ meet: { id: "grimslov", name: "Grimslöv 2027" }, versions: [{ number: 1 }, { number: 2 }] }] as unknown as MeetSummary[];

  it("lists every published version, newest first, and Provbanan last", () => {
    expect(meetChoices(meets).map((choice) => choice.value)).toEqual(["grimslov:2", "grimslov:1", "provbanan:1"]);
    expect(meetChoices([]).map((choice) => choice.name)).toEqual(["Provbanan"]);
    expect(runningChoice(now)).toBe("provbanan:1");
  });

  it("takes the meet Planering asks for, if the hub has it", () => {
    const choices = meetChoices(meets);
    expect(askedChoice("?traff=grimslov&version=1", choices)).toBe("grimslov:1");
    expect(askedChoice("?traff=grimslov&version=9", choices)).toBeNull();
    expect(askedChoice("", choices)).toBeNull();
  });
});

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

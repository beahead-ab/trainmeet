import { describe, expect, it } from "vitest";
import type { MeetSummary, Now } from "./api";
import { askedChoice, clockNote, clockText, meetChoices, meetTitle, runningChoice } from "./traff";

const now = {
  meet_id: "provbanan",
  name: "Provbanan",
  version: 1,
  traffic_day: "mon",
  game_day: 1,
  clock: { time: "23:58", seconds: 23 * 3600 + 58 * 60, running: true, speed: 4, game_day: 1 },
  places: [],
  legs: [],
  clearances: [],
} as unknown as Now;

describe("the meet clock in the header (TRAFIK-12)", () => {
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

describe("Byt träff (TRAFIK-29)", () => {
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


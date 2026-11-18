import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clockText, LOST_AFTER_MS, MeetClock } from "./clock";
import { ChangedMarks, countdown, dueReminder, frammeAllowed, frammeRow, momentsOf, nextStop, nuPosition, onAxis, onLineByPlan } from "./korplan";
import { CLOCK, row, rows } from "./testdata";

const at = (time: string) => {
  const [h, m, s] = time.split(":").map(Number);
  return (h ?? 0) * 3600 + (m ?? 0) * 60 + (s ?? 0);
};

describe("the NU-line on Drift's clock, never the phone's (LOK-12)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-18T09:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("counts on from Drift's clock with Drift's speed, and ignores the phone's time of day", () => {
    const clock = new MeetClock();
    clock.accept({ ...CLOCK, seconds: at("06:03:00") });
    vi.advanceTimersByTime(10_000);
    expect(clockText(clock.seconds())).toBe("06:03:40");
    // The phone's clock jumps a year and a day: the meet clock does not care.
    vi.setSystemTime(new Date("2027-11-19T23:59:00Z"));
    expect(clockText(clock.seconds())).toBe("06:03:40");
    const moments = momentsOf(rows());
    // 06:03:40 lies between Norrby's departure 06:00 and Åsen's arrival 06:08.
    expect(nuPosition(moments, clock.seconds()!)).toEqual({ index: 1, fraction: (220 / 480) });
    // 75 real seconds more, with the hub's answers every 25 as the phone polls: 06:08:40, past
    // Åsen's arrival.
    for (const seconds of [at("06:05:20"), at("06:07:00"), at("06:08:40")]) {
      vi.advanceTimersByTime(25_000);
      clock.accept({ ...CLOCK, seconds });
    }
    expect(clockText(clock.seconds())).toBe("06:08:40");
    expect(nuPosition(moments, clock.seconds()!).index).toBe(2);
    expect(moments[2]?.kind).toBe("departure");
  });

  it("stands still when the clock is stopped, and when the contact is lost", () => {
    const clock = new MeetClock();
    clock.accept({ ...CLOCK, seconds: at("06:03:00"), running: false });
    vi.advanceTimersByTime(20_000);
    expect(clock.mode()).toBe("stopped");
    expect(clockText(clock.seconds())).toBe("06:03:00");
    clock.accept({ ...CLOCK, seconds: at("06:03:00") });
    vi.advanceTimersByTime(LOST_AFTER_MS + 60_000);
    expect(clock.mode()).toBe("lost");
    expect(clockText(clock.seconds())).toBe("06:05:00"); // 30 s at ×4, then still.
  });

  it("takes a jump of the meet clock, but not a small step back from a slow answer", () => {
    const clock = new MeetClock();
    clock.accept({ ...CLOCK, seconds: at("06:03:00") });
    vi.advanceTimersByTime(1000);
    clock.accept({ ...CLOCK, seconds: at("06:03:02") });
    expect(clockText(clock.seconds())).toBe("06:03:04");
    clock.accept({ ...CLOCK, seconds: at("05:00:00") });
    expect(clockText(clock.seconds())).toBe("05:00:00");
  });
});

describe("the körplan's moments (LOK-03)", () => {
  it("has a departure first, an arrival last, and a moment for a pass", () => {
    const moments = momentsOf(rows());
    expect(moments.map((m) => `${m.row.place}:${m.kind}`)).toEqual(["nby:departure", "asn:arrival", "asn:departure", "lvh:pass", "mla:arrival", "mla:departure", "sjv:arrival"]);
  });

  it("goes past midnight on a running axis, and the clock is laid on the nearest day", () => {
    const moments = momentsOf([row("t9-asn", null, "23:50", { first_of_train: true }), row("t9-sjv", "00:20", null, { last: true })]);
    expect(moments.map((m) => m.t)).toEqual([at("23:50"), at("24:20")]);
    expect(onAxis(at("00:05"), moments[0]!.t, moments[1]!.t)).toBe(at("24:05"));
    expect(onAxis(at("24:05"), moments[0]!.t, moments[1]!.t)).toBe(at("24:05"));
  });

  it("says the next stop and what is passed on the way", () => {
    const moments = momentsOf(rows());
    const next = nextStop(moments, at("06:12"));
    expect(next?.moment.row.place).toBe("mla");
    expect(next?.passes.map((p) => p.row.place)).toEqual(["lvh"]);
    expect(nextStop(moments, at("06:40"))).toBeNull();
  });

  it("knows by the plan when the train is out on the line", () => {
    const moments = momentsOf(rows());
    expect(onLineByPlan(moments, at("06:04"))).toBe(true);
    expect(onLineByPlan(moments, at("06:09"))).toBe(false);
    expect(onLineByPlan(moments, at("06:16"))).toBe(true);
  });
});

describe("Framme only when allowed and only where nobody works (LOK-39)", () => {
  it("is the next arrival on the line, or where the train stands by the plan", () => {
    const moments = momentsOf(rows());
    expect(frammeRow(moments, at("05:55"))).toBeNull();
    expect(frammeRow(moments, at("06:04"))?.place).toBe("asn");
    expect(frammeRow(moments, at("06:09"))?.place).toBe("asn");
    expect(frammeRow(moments, at("06:12"))?.place).toBe("mla");
    expect(frammeRow(moments, at("06:40"))?.place).toBe("sjv");
  });

  it("goes by the stations' word on where the train is, when the game shows it", () => {
    const moments = momentsOf(rows());
    const late = { train: "t101", train_number: "101", state: "on_the_way" as const, from_place: "nby", to_place: "asn", section: "s", place: null, delay: 6, paper: false };
    expect(frammeRow(moments, at("06:12"), late)?.place).toBe("asn");
    expect(frammeRow(moments, at("06:04"), { ...late, state: "at", place: "nby", to_place: null })).toBeNull();
  });

  it("is off by default, and never at a manned place", () => {
    const unmanned = row("t101-asn", "06:08", "06:10", { unmanned: true });
    const manned = row("t101-mla", "06:19", "06:21", { unmanned: false });
    expect(frammeAllowed(unmanned, false)).toBe(false);
    expect(frammeAllowed(unmanned, true)).toBe(true);
    expect(frammeAllowed(manned, true)).toBe(false);
    expect(frammeAllowed(null, true)).toBe(false);
  });
});

describe("Ändrat stays for ten game minutes (LOK-41)", () => {
  it("from when the hub first said it, on the meet clock", () => {
    const marks = new ChangedMarks();
    const changed = row("t101-asn", "06:08", "06:12", { changed: true, track: "2" });
    marks.note([changed], at("06:03"));
    expect(marks.shows(changed, at("06:03"))).toBe(true);
    marks.note([changed], at("06:09"));
    expect(marks.shows(changed, at("06:12:59"))).toBe(true);
    expect(marks.shows(changed, at("06:13"))).toBe(false);
    // The hub has the last word: no longer changed is no mark, and a new change marks anew.
    const again = { ...changed, changed: false };
    marks.note([again], at("06:14"));
    expect(marks.shows(again, at("06:14"))).toBe(false);
    marks.note([changed], at("06:20"));
    expect(marks.shows(changed, at("06:25"))).toBe(true);
  });
});

describe("the reminders 20 and 10 minutes before the start (LOK-41)", () => {
  it("each once, in the two minutes after it is due", () => {
    expect(dueReminder(21 * 60, [])).toBeNull();
    expect(dueReminder(20 * 60, [])).toBe(20);
    expect(dueReminder(19 * 60, [20])).toBeNull();
    expect(dueReminder(15 * 60, [])).toBeNull();
    expect(dueReminder(9.5 * 60, [20])).toBe(10);
    expect(dueReminder(9 * 60, [20, 10])).toBeNull();
    expect(dueReminder(5 * 60, [])).toBeNull();
  });

  it("counts down on the meet clock, with the real time beside it", () => {
    const start = { time: "06:30", seconds: at("06:30"), in_game_seconds: 0, in_real_seconds: null };
    expect(countdown(start, at("06:06"), 4, true)).toEqual({ game: 24 * 60, real: 6 * 60, starts: at("06:30") });
    expect(countdown(start, at("06:06"), 4, false).real).toBeNull();
  });
});

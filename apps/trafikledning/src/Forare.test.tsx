import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { DriftEvent, DriverOverview, Now } from "./api";
import { pageOf } from "./App";
import { describe as describeEvent } from "./drift";
import { alarmText, ForarePage, TEXT } from "./Forare";
import { Forarna } from "./Nu";

const now = {
  meet_id: "provbanan",
  name: "Provbanan",
  version: 1,
  traffic_day: "mon",
  game_day: 1,
  clock: { time: "06:10", seconds: 22200, running: true, speed: 4, game_day: 1 },
  places: [
    { place: "nby", code: "Nby", name: "Norrby" },
    { place: "asn", code: "Åsn", name: "Åsen" },
    { place: "sjv", code: "Sjv", name: "Sjövik" },
  ],
  legs: [],
  clearances: [],
  driver_alarms: [{ service: { kind: "duty", id: "d1" }, number: "1", train: "t101", train_number: "101", section: "s-nby-asn", from_place: "nby", to_place: "asn", since: "06:08", seq: 12 }],
  driver_messages: [{ kind: "engine_trouble", train: "t102", train_number: "102", service_number: "2", model_time: "06:09", seq: 13 }],
} as unknown as Now;

const offer = (number: string, extra: Record<string, unknown> = {}) => ({
  service: { kind: "duty", id: `d${number}` },
  number,
  start: { time: "06:05", place: "sjv", place_name: "Sjövik" },
  end: { time: "07:29", place: "sjv", place_name: "Sjövik" },
  operator: "SJ",
  level: "easy",
  trains: ["102", "103"],
  taken: false,
  driver: null,
  driver_name: null,
  released_on_line: false,
  matches_level: false,
  exact: false,
  done: false,
  ...extra,
});

const overview = (maySet: boolean): DriverOverview =>
  ({
    drivers: [
      {
        driver: { id: "forare-a", name: "Anna Ek", initials: "AE", level: "medium", state: null, photo: null, linked: false, joined: "2026-11-18T09:00:00Z" },
        service: offer("1", { taken: true, driver: "forare-a", driver_name: "Anna Ek", level: "medium", trains: ["101", "104"] }),
        checkin: { place: "asn", place_name: "Åsen", track: "1", train: "t101", train_number: "101", model_time: "06:08", age_seconds: 120, fading: false },
        position: { train: "t101", train_number: "101", state: "on_the_way", from_place: "nby", to_place: "asn", section: "s-nby-asn", place: null, delay: 3 },
        message: { seq: 13, kind: "needs_help", driver: "forare-a", driver_name: "Anna Ek", service: { kind: "duty", id: "d1" }, service_number: "1", train: "t101", train_number: "101", model_time: "06:09", wall_time: "2026-11-18T09:01:00Z" },
      },
      {
        driver: { id: "forare-b", name: "Bo", initials: "BO", level: "easy", state: "waiting_start", photo: null, linked: true, joined: "2026-11-18T09:00:10Z" },
        service: null,
        checkin: null,
        position: null,
        message: null,
      },
    ],
    services: { kind: "duty", services: [offer("1", { taken: true, driver: "forare-a", driver_name: "Anna Ek" }), offer("2"), offer("3", { released_on_line: true })] },
    messages: [{ seq: 13, kind: "needs_help", driver: "forare-a", driver_name: "Anna Ek", service: { kind: "duty", id: "d1" }, service_number: "1", train: "t101", train_number: "101", model_time: "06:09", wall_time: "2026-11-18T09:01:00Z" }],
    alarms: now.driver_alarms,
    settings: { reality: true, clearances: false, arrival: false },
    may_hand_out: true,
    may_set: maySet,
    names_shown: true,
  }) as unknown as DriverOverview;

const joining = { code: "123456", url: "http://hubben.local/lokforaren/#kod=123456" };
const go = () => undefined;

describe("Förare in Drift (TRAFIK-33)", () => {
  it("is a page of Drift's own, at /drift/forare", () => {
    expect(pageOf("/drift/forare")).toBe("forare");
  });

  it("asks for the login first", () => {
    const html = renderToStaticMarkup(<ForarePage loggedIn={false} now={now} navigate={go} language="sv" />);
    expect(html).toContain("Logga in som trafikledare eller lokledare");
  });

  it("lists the drivers with their service, train, check-in and latest message", () => {
    const html = renderToStaticMarkup(<ForarePage loggedIn now={now} navigate={go} language="sv" initial={{ overview: overview(true), joining }} />);
    expect(html).toContain("<b>Anna Ek</b>");
    expect(html).toContain("Medel · Tjänst 1 · tåg 101, 104 · På väg Norrby → Åsen · 3 min sent · Incheckad Åsen kl. 06:08");
    expect(html).toContain("06:09 · Behöver hjälp");
    expect(html).toContain("Lätt · Inväntar start · Ingen tjänst");
    // Hand out the free ones, take back the one that is driven (LOK-30).
    expect(html).toContain(">Dela ut<");
    expect(html).toContain(">Ta tillbaka<");
    expect(html).toContain("Körs av Anna Ek");
    expect(html).toContain("Släppt på linjen");
    expect(html).toContain("06:05 Sjövik – 07:29 Sjövik · SJ · Lätt");
  });

  it("has the game's two settings and Framme, which only Trafikledningen changes", () => {
    const dispatcher = renderToStaticMarkup(<ForarePage loggedIn now={now} navigate={go} language="sv" initial={{ overview: overview(true), joining }} />);
    expect(dispatcher).toContain("Förarna ser verkligheten");
    expect(dispatcher).toContain("Förarna ser tågklareringens besked");
    expect(dispatcher).toContain("Framme räknas som ankomst, bara på obemannade driftplatser");
    expect(dispatcher).toMatch(/name="reality" checked=""/);
    expect(dispatcher).not.toMatch(/name="clearances" checked=""/);
    expect(dispatcher).not.toContain("disabled");
    expect(dispatcher).toContain("Släpp in en lokledare");
    expect(dispatcher).toContain(">Kvittera<");
    const lead = renderToStaticMarkup(<ForarePage loggedIn now={now} navigate={go} language="sv" initial={{ overview: overview(false), joining }} />);
    expect(lead).toContain("Du är lokledare");
    expect(lead).toMatch(/disabled="" name="reality" checked=""/);
    expect(lead).not.toContain("Släpp in en lokledare");
    expect(lead).not.toContain(">Kvittera<");
    expect(lead).toContain(">Dela ut<");
  });

  it("shows the QR code the drivers come in with (LOK-01)", () => {
    const html = renderToStaticMarkup(<ForarePage loggedIn now={now} navigate={go} language="sv" initial={{ overview: overview(true), joining }} />);
    expect(html).toContain('src="/api/drift/1/drivers/connect.svg"');
    expect(html).toContain("Kod 123 456");
    expect(html).toContain("/lokforaren/#kod=123456");
  });

  it("speaks English too", () => {
    const html = renderToStaticMarkup(<ForarePage loggedIn now={now} navigate={go} language="en" initial={{ overview: overview(true), joining }} />);
    expect(html).toContain("The drivers see reality");
    expect(html).toContain("Needs help");
    expect(html).toContain("Hand out");
    expect(alarmText(now.driver_alarms![0]!, now, TEXT.en)).toBe("Train 101 stands without a driver between Norrby and Åsen · service 1 · since 06:08");
  });
});

describe("Lokföraren in Nu and Logg (LOK-35, LOK-23)", () => {
  it("raises the alarm at once in Nu, without names", () => {
    const html = renderToStaticMarkup(<Forarna now={now} />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("Tåg 101 står utan förare mellan Norrby och Åsen · tjänst 1 · sedan 06:08");
    expect(html).toContain("06:09 · Loket krånglar");
    expect(html).toContain("Tåg 102 · tjänst 2");
    expect(renderToStaticMarkup(<Forarna now={{ ...now, driver_alarms: [], driver_messages: [] }} />)).toBe("");
  });

  it("says in Logg what a driver did", () => {
    const event = (kind: string, data: Record<string, unknown>) => ({ kind, data }) as unknown as DriftEvent;
    expect(describeEvent(event("driver.message", { kind: "stopped_on_line" }))).toBe("Föraren: Står på linjen");
    expect(describeEvent(event("service.released", { on_line: true }))).toBe("Tjänsten släppt på linjen: tåget står utan förare");
    expect(describeEvent(event("service.released", { done: true }))).toBe("Tjänsten klar: Framme vid slutet");
    expect(describeEvent(event("driver.arrived", { counted: true }))).toBe("Föraren: Framme, räknas som ankomst");
    expect(describeEvent(event("service.claimed", {}))).toBe("Tjänsten tagen");
  });
});

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Preview, PreviewCase } from "./api";
import { caseActions, caseStatus, legInfo, legLabel, ProvbananPage, runClock, shownCases } from "./Provbanan";

const places = { nby: "Norrby", asn: "Åsen" };
const leg = (change: Record<string, unknown> = {}) =>
  ({ train: "101", section: "nby-asn", departure: { id: "t101-nby", place: "nby", departure: "06:00" }, arrival: { id: "t101-asn", place: "asn", track: "2" }, blocked: null, complete: false, ...change }) as unknown as Preview["legs"][number];
const item = (change: Partial<PreviewCase> = {}) =>
  ({ id: "c1", train: "101", departure: "t101-nby", arrival: "t101-asn", from_place: "nby", to_place: "asn", status: "waiting", departed: false, arrived: false, revision: 1, ...change }) as PreviewCase;
const state = {
  revision: 3,
  context: { meet_id: "provbanan", version: 1, game_day: 1, epoch: 0 },
  traffic_day: "mon",
  places,
  stations: ["nby", "asn"],
  sections: { "nby-asn": "requested" },
  clock: { seconds: 23 * 3600 + 59 * 60, time: "23:59", speed: 4, running: true },
  legs: [leg()],
  cases: [item()],
} as unknown as Preview;

describe("Provbanan (steg 2)", () => {
  it("names a leg and says how it is cleared, where it arrives and why it cannot be asked for", () => {
    expect(legLabel(leg(), places)).toBe("06:00 · tåg 101 · Norrby → Åsen");
    expect(legLabel(leg({ departure: { id: "x", place: "nby", departure: null } }), places)).toBe("Utan avgångstid · tåg 101 · Norrby → Åsen");
    expect(legInfo(leg(), state)).toBe("Begärd klarering · planerat ankomstspår 2");
    expect(legInfo(leg({ blocked: "channel_occupied" }), { ...state, sections: { "nby-asn": "direct" } })).toBe("Direktklarering · planerat ankomstspår 2 · Sträckan är upptagen.");
  });

  it("lets each place do what it can with a case, and only that", () => {
    const labels = (change: Partial<PreviewCase>) => caseActions(item(change), places).map((action) => action.label);
    expect(labels({})).toEqual(["Åsen: Ge klart", "Åsen: Neka", "Norrby: Återkalla"]);
    expect(labels({ status: "approved" })).toEqual(["Norrby: Återkalla", "Norrby: Avgå"]);
    expect(labels({ status: "approved", departed: true })).toEqual(["Åsen: Ankom"]);
    expect(labels({ status: "approved", departed: true, arrived: true })).toEqual([]);
    expect(caseStatus(item({ status: "approved", departed: true }))).toBe("På väg");
    expect(caseStatus(item({ arrived: true }))).toBe("Ankommen");
  });

  it("shows the cases going on first, then the last five finished, newest first", () => {
    const done = [1, 2, 3, 4, 5, 6].map((n) => item({ id: `d${n}`, status: "rejected" }));
    expect(shownCases([...done.slice(0, 3), item({ id: "a" }), ...done.slice(3)]).map((c) => c.id)).toEqual(["a", "d6", "d5", "d4", "d3", "d2"]);
  });

  it("runs the clock on over midnight at the run's speed", () => {
    expect(runClock(state, 0)).toBe("23:59");
    expect(runClock(state, 15_000)).toBe("00:00");
  });

  it("asks to start a run first, and then shows the run with its code and its boxes", () => {
    expect(renderToStaticMarkup(<ProvbananPage initial={{ state: null, clients: null }} />)).toContain('id="start"');
    const clients = { code: "123456", clients: [{ client_id: "b1", name: "Box 12", kind: "tmbox_web", status: "waiting", places: [], side: "both" }] } as never;
    const html = renderToStaticMarkup(<ProvbananPage initial={{ state, clients }} />);
    expect(html).not.toContain('id="start"');
    expect(html).toContain('id="join-code" class="tm-mono">123456<');
    expect(html).toContain('href="/provbanan/box#kod=123456"');
    expect(html).toContain("Box 12");
    expect(html).toContain("Väntar på tilldelning");
    expect(html).toContain(">Åsen: Ge klart<");
    expect(html).toContain(">Stanna klockan<");
  });
});

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Package, ScreenPicture } from "./api";
import { clockText, Screen } from "./App";
import { clockSeconds, hands } from "./Klocka";
import { rowsOf } from "./Diagram";
import { nextHappenings, numbers } from "./Oversikt";
import { lines, trafficOf, type Package as HubPackage } from "@trainmeet/hubben";
import provbanan from "../../../contracts/examples/provbanan.meet.json";

const picture = (change: Partial<ScreenPicture> = {}): ScreenPicture => ({
  name: "TV vid entrén",
  view: "clock",
  meet: "Provbanan",
  traffic_day: "mon",
  clock: { time: "06:00", seconds: 6 * 3600, running: true, speed: 4, game_day: 1 },
  now: null,
  package: null,
  ...change,
});

describe("a meet screen (SKARM-14)", () => {
  it("joins with the meet's code, which a link can fill in", () => {
    const html = renderToStaticMarkup(<Screen picture={null} fetchedAt={0} now={0} message="" code="482915" />);
    expect(html).toContain('id="login-form"');
    expect(html).toContain('pattern="[0-9]{6}"');
    expect(html).toContain('value="482915"');
  });

  it("waits under Väntar until the dispatcher gives it a view", () => {
    const html = renderToStaticMarkup(<Screen picture={picture({ view: null })} fetchedAt={0} now={0} message="" code="" />);
    expect(html).toContain("Väntar på en vy");
    expect(html).toContain("TV vid entrén");
  });

  it("shows the meet clock, analog or digital, running on at its speed between the hub's answers (SKARM-23)", () => {
    const html = renderToStaticMarkup(<Screen picture={picture()} fetchedAt={0} now={0} message="" code="" />);
    expect(html).toContain('id="clock-view" class="klocka gar analog"');
    expect(html).toContain('<h1 id="meet">Provbanan</h1><p id="day">Måndag · dag 1 · ×4</p>');
    expect(html).toContain('class="urtavla"');
    expect(html).toContain("Klockan går i 4×");
    const digital = renderToStaticMarkup(<Screen picture={picture({ view: "clock_digital" })} fetchedAt={0} now={0} message="" code="" />);
    expect(digital).toContain('<p id="time" class="tid">06:00</p>');
    expect(digital).not.toContain("urtavla");
    expect(hands(3 * 3600 + 30 * 60)).toEqual({ hour: 105, minute: 180, second: 0 });
    expect(clockSeconds(picture(), 0, 2_500)).toBe(6 * 3600 + 10);
    expect(clockText(picture(), 0, 30_000)).toBe("06:02"); // 30 s at 4× is two minutes
    expect(clockText(picture({ clock: { ...picture().clock, running: false } }), 0, 30_000)).toBe("06:00");
    expect(clockText(picture({ clock: { ...picture().clock, seconds: 23 * 3600 + 59 * 60 } }), 0, 60_000)).toBe("00:03");
  });

  it("says when the clock stands still", () => {
    const html = renderToStaticMarkup(<Screen picture={picture({ clock: { ...picture().clock, running: false } })} fetchedAt={0} now={0} message="" code="" />);
    expect(html).toContain("klocka star");
    expect(html).toContain('<p id="state" class="lage stopp">Klockan står still</p>');
  });

  it("draws Banöversikten with the trains, the clock and the four lists (SKARM-21)", () => {
    const pkg = provbanan as unknown as Package;
    const legs = [{ leg: "t101-nby", train: "t101", train_number: "101", section: "s-nby-asn", from_place: "nby", to_place: "asn", departure: "06:00", arrival: "06:08", state: "on_the_way", clearance_id: null, track: "1" }];
    const seen = { meet_id: "provbanan", name: "Provbanan", version: 1, traffic_day: "mon", game_day: 1, clock: picture().clock, places: [], legs, clearances: [], changes: [] };
    const shown = picture({ view: "tracks", now: seen as unknown as ScreenPicture["now"], package: "k1" });
    const html = renderToStaticMarkup(<Screen picture={shown} pkg={pkg} fetchedAt={0} now={0} message="" code="" />);
    expect(html).toContain('id="tracks-view"');
    expect(html).toContain("Banöversikt · 1 tåg på linjen · 0 klart, inte avgått · 0 väntar på svar · 0 slutar här");
    expect(html).toContain('class="banoversikt"');
    expect(html).toContain(">Norrby</text>");
    expect(html).toContain("101 ▶");
    expect(html).toContain("Norrby → Åsen");
    expect(renderToStaticMarkup(<Screen picture={shown} pkg={null} fetchedAt={0} now={0} message="" code="" />)).toContain("Hämtar banan");
  });

  it("draws Tågdiagrammet: three hours of the main line, run, planned and now (SKARM-18)", () => {
    const pkg = provbanan as unknown as Package;
    const line = lines(pkg as unknown as HubPackage)[0];
    const rows = rowsOf(pkg as unknown as HubPackage, line!);
    expect([...rows.values()][0]).toBe(0);
    expect([...rows.values()].at(-1)).toBe(1);
    const legs = [{ leg: "t101-nby", train: "t101", train_number: "101", section: "s-nby-asn", from_place: "nby", to_place: "asn", departure: "06:00", arrival: "06:08", state: "on_the_way", clearance_id: null, track: "1" }];
    const seen = { meet_id: "provbanan", name: "Provbanan", version: 1, traffic_day: "mon", game_day: 1, clock: { ...picture().clock, time: "06:04" }, places: [], legs, clearances: [], changes: [] };
    const shown = picture({ view: "graph", clock: { ...picture().clock, seconds: 6 * 3600 + 4 * 60 }, now: seen as unknown as ScreenPicture["now"], package: "k1" });
    const html = renderToStaticMarkup(<Screen picture={shown} pkg={pkg} fetchedAt={0} now={0} message="" code="" />);
    expect(html).toContain('id="graph-view"');
    expect(html).toContain("tre timmar från 05:34");
    expect(html).toContain('class="tagnr kort">101<');
    expect(html).toContain("1 tåg på linjen");
  });

  it("shows Översikt: the clock, four numbers, the line, the next things and the trains on it (SKARM-18)", () => {
    const pkg = provbanan as unknown as Package;
    const legs = [
      { leg: "t101-nby", train: "t101", train_number: "101", section: "s-nby-asn", from_place: "nby", to_place: "asn", departure: "06:00", arrival: "06:08", state: "on_the_way", clearance_id: null, track: "1" },
      { leg: "t102-sjv", train: "t102", train_number: "102", section: "s-mla-sjv", from_place: "sjv", to_place: "mla", departure: "06:05", arrival: "06:13", state: "requested", clearance_id: null, track: "2" },
      { leg: "t103-nby", train: "t103", train_number: "103", section: "s-nby-asn", from_place: "nby", to_place: "asn", departure: "07:00", arrival: "07:08", state: "planned", clearance_id: null, track: "1" },
    ];
    const seen = { meet_id: "provbanan", name: "Provbanan", version: 1, traffic_day: "mon", game_day: 1, clock: { ...picture().clock, time: "06:04" }, places: [], legs, clearances: [], changes: [] } as unknown as NonNullable<ScreenPicture["now"]>;
    const names = new Map(pkg.places.map((place) => [place.id, place.name]));
    expect(nextHappenings(seen, names).map((item) => `${item.number} ${item.text} · ${item.note}`)).toEqual([
      "102 avgår Sjövik mot Mellanå · väntar på svar",
      "101 ankommer Åsen spår 1 · om 4 min",
      "103 avgår Norrby mot Åsen · om 56 min",
    ]);
    expect(numbers(trafficOf(pkg as unknown as HubPackage, seen as never)).map(([count]) => count)).toEqual([1, 1, 1, 0]);
    const html = renderToStaticMarkup(<Screen picture={picture({ view: "overview", now: seen, package: "k1" })} pkg={pkg} fetchedAt={0} now={0} message="" code="" />);
    expect(html).toContain('id="overview-view"');
    expect(html).toContain("Måndag · dag 1 av 1");
    expect(html).toContain("tåg inne på driftplatserna");
    expect(html).toContain('class="banoversikt"');
    expect(html).toContain("Nästa händelser");
    expect(html).toContain("Norrby → Åsen");
  });
});

import type { Package } from "@trainmeet/hubben";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TjanstKort } from "./Tag";
import { lokWith, offer } from "./testdata";
import { TEXT } from "./text";
import { Topologi, topologyOf, wayOf } from "./Topologi";

// Topologin i tjänsten (LOK-28, LF15, om-taget.jpg): the line with the service's way and stops.

const place = (id: string, name: string, kind = "manned") => ({ id, code: id, name, kind });
const call = (id: string, at: string, time: string, stops = true) => ({ id, place: at, arrival: time, departure: time, stops });

/** Norrby – Åsen – Sjövik on the main line, Lövhult branching at Åsen, a halt along the way,
 * and a depot at Sjövik. Duty d1 runs 101 from Norrby to Sjövik, through Åsen without a stop. */
const PKG = {
  format: "trainmeet.meet/1",
  meet: { id: "prov", name: "Provträffen" },
  places: [place("nby", "Norrby"), place("asn", "Åsen"), place("sjv", "Sjövik"), place("lvh", "Lövhult"), place("hpl", "Hållplatsen", "halt"), place("dep", "Depå", "shadow_yard")],
  sections: [
    { id: "s1", place_a: "nby", place_b: "asn" },
    { id: "s2", place_a: "asn", place_b: "sjv" },
    { id: "s3", place_a: "asn", place_b: "lvh" },
    { id: "s4", place_a: "sjv", place_b: "dep" },
  ],
  trains: [
    { id: "t101", number: "101", days: ["mon"], calls: [call("c1", "nby", "06:00"), call("c2", "hpl", "06:05"), call("c3", "asn", "06:10", false), call("c4", "sjv", "06:20"), call("c5", "dep", "06:30")] },
    { id: "t104", number: "104", days: ["mon"], calls: [call("c6", "lvh", "07:00"), call("c7", "asn", "07:10")] },
  ],
  duties: [{ id: "d1", name: "1", legs: [{ train: "t101", from_call: "c1", to_call: "c4" }] }],
} as unknown as Package;

describe("Topologi in the service (LOK-28)", () => {
  it("follows the duty's legs: the places it passes, and where it stops", () => {
    expect(wayOf(PKG, offer("1"))).toEqual([
      { place: "nby", stops: true },
      { place: "asn", stops: false },
      { place: "sjv", stops: true },
    ]);
    // A train on its own, and an extra train after the paper found by its number.
    expect(wayOf(PKG, offer("104", { service: { kind: "train", id: "t104" } })).map((stop) => stop.place)).toEqual(["lvh", "asn"]);
    expect(wayOf(PKG, offer("x", { service: { kind: "paper", id: "papper-1" }, trains: ["104"] })).map((stop) => stop.place)).toEqual(["lvh", "asn"]);
  });

  it("draws the whole line, the service's way and its stops, without the halts", () => {
    const drawn = topologyOf(PKG, offer("1"));
    expect(drawn?.places.map((p) => p.id).sort()).toEqual(["asn", "dep", "lvh", "nby", "sjv"]);
    expect(drawn?.links.filter((link) => link.onWay).map((link) => `${link.a}-${link.b}`)).toEqual(["nby-asn", "asn-sjv"]);
    const at = new Map(drawn?.places.map((p) => [p.id, p]));
    expect([at.get("nby")?.y, at.get("asn")?.y, at.get("sjv")?.y]).toEqual([40, 40, 40]);
    expect(at.get("lvh")?.y).toBeGreaterThan(40);
    expect(at.get("dep")?.yard).toBe(true);

    const html = renderToStaticMarkup(<Topologi pkg={PKG} offer={offer("1")} text={TEXT.sv} />);
    expect(html).toContain(">Topologi</h2>");
    expect(html).toContain('aria-label="Linjen, med tjänstens väg genom Norrby, Åsen, Sjövik"');
    expect(html).toContain('<g class="plats pa-vagen"><circle cx="40" cy="40" r="7" class="uppehall"></circle><text x="40" y="62" text-anchor="middle">Norrby</text></g>');
    expect(html).toContain("Din tjänst");
    expect(html).not.toContain("Hållplatsen");
  });

  it("stands in Hela tjänsten after the front, and not before the package has come", () => {
    const service = offer("1");
    const lok = lokWith({ selected: service });
    const shown = renderToStaticMarkup(<TjanstKort lok={lok} state={lok.state} now={null} initialPackage={PKG} />);
    expect(shown.indexOf("lok-framsida")).toBeLessThan(shown.indexOf('id="topologi"'));
    expect(renderToStaticMarkup(<TjanstKort lok={lok} state={lok.state} now={null} initialPackage={null} />)).not.toContain('id="topologi"');
  });
});

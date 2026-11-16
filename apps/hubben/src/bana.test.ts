import { describe, expect, it } from "vitest";
import type { Now } from "./api";
import type { Package } from "./andringar";
import provbanan from "../../../contracts/examples/provbanan.meet.json";
import { between, drawing, gridOf, summary, trafficOf, type Leg } from "./bana";

// Banöversikten (SKARM-21, H47) on Provbanan: Norrby – Åsen – (Lövhult) – Mellanå – Sjövik.

const pkg = provbanan as unknown as Package;

const leg = (train: string, from: string, to: string, state: Leg["state"], departure: string, arrival: string, track: string | null = "1"): Leg =>
  ({ leg: `${train}-${from}`, train, train_number: train.slice(1), section: ["nby", "asn"].includes(from) && ["nby", "asn"].includes(to) ? "s-nby-asn" : "s-mla-sjv", from_place: from, to_place: to, departure, arrival, state, clearance_id: state === "requested" ? "c1" : null, track }) as Leg;

const now = (legs: Leg[], time = "07:00") => ({ clock: { time }, legs, clearances: [{ clearance_id: "c1", requested_at: "06:57", reminders: 1 }] }) as unknown as Now;

describe("Banöversikten (SKARM-21, H47)", () => {
  it("lays the places that clear out along the line, with the halts left to the sections", () => {
    const drawn = drawing(pkg);
    const order = [...drawn.boxes.values()].sort((a, b) => a.x - b.x).map((box) => box.place.id);
    expect(order).toEqual(["nby", "asn", "mla", "sjv"]);
    expect(new Set([...drawn.boxes.values()].map((box) => box.y)).size).toBe(1);
    expect(drawn.links.map((link) => link.section?.id)).toEqual(["s-nby-asn", "s-asn-mla", "s-mla-sjv"]);
    expect(drawn.boxes.get("asn")?.tracks).toEqual(["1", "2", "3"]);
  });

  it("hangs a branch below where it leaves", () => {
    const grid = gridOf(["a", "b", "c", "d"], [
      { a: "a", b: "b", section: null },
      { a: "b", b: "c", section: null },
      { a: "b", b: "d", section: null },
    ]);
    expect(grid.get("a")?.[1]).toBe(0);
    expect(grid.get("b")?.[1]).toBe(0);
    expect(new Set([grid.get("c")?.[1], grid.get("d")?.[1]])).toEqual(new Set([0, 1]));
  });

  it("puts each train where the buttons say: start track, section, destination track", () => {
    const traffic = trafficOf(
      pkg,
      now([
        leg("t101", "nby", "asn", "on_the_way", "06:56", "07:04", "2"),
        leg("t102", "sjv", "mla", "requested", "07:01", "07:09"),
        leg("t103", "nby", "asn", "cleared", "07:00", "07:08"),
        leg("t104", "asn", "nby", "arrived", "06:50", "06:58", "2"),
        leg("t105", "nby", "asn", "planned", "07:10", "07:18"),
        leg("t106", "sjv", "mla", "planned", "08:05", "08:13"),
      ]),
    );
    expect(traffic.online.map((l) => l.train)).toEqual(["t101"]);
    expect(traffic.sections.get("s-nby-asn")?.map((s) => [s.train, s.state])).toEqual([
      ["t101", "occupied"],
      ["t103", "cleared"],
    ]);
    expect(traffic.sections.get("s-nby-asn")?.[0]?.progress).toBe(0.5);
    expect(traffic.tracks.get("asn")?.get("2")?.map((t) => [t.number, t.state])).toEqual([["101", "coming"]]);
    expect(traffic.tracks.get("sjv")?.get("2")?.map((t) => t.state)).toEqual(["requested"]);
    expect(traffic.ends.map((l) => l.train)).toEqual(["t104"]);
    expect(traffic.tracks.get("nby")?.get("2")?.map((t) => t.state)).toEqual(["ends"]);
    const atNorrby = [...(traffic.tracks.get("nby")?.values() ?? [])].flat().map((t) => `${t.number}:${t.state}`);
    expect(atNorrby).toEqual(expect.arrayContaining(["103:cleared", "105:here", "104:ends"]));
    expect(atNorrby).not.toContain("106:here");
    expect(summary(traffic)).toBe("1 tåg på linjen · 1 klart, inte avgått · 1 väntar på svar · 1 slutar här");
  });

  it("counts minutes the short way round midnight", () => {
    expect(between(23 * 60 + 58, 3)).toBe(5);
    expect(between(5, 23 * 60 + 58)).toBe(-7);
  });
});

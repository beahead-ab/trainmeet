import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Draft } from "./api";
import { BanaPage, Karta } from "./Bana";
import type { Package } from "./data";
import { GrafPage, sheet } from "./Graf";
import { DAY, lines, marksOf, onLine, runs, times, trafficDays } from "./graf";
import { layout, links } from "./karta";

const go = () => undefined;
// A line A–B–C with a branch C–D, and track B–E that no section clears.
const pkg = {
  meet: { traffic_week: { start_weekday: "fri", days: 3 } },
  clock: { start_time: "06:00" },
  places: [
    { id: "a", code: "A", name: "Alby", kind: "manned", remote_from: null, phone: null, tracks: [] },
    { id: "b", code: "B", name: "Byn", kind: "manned", remote_from: null, phone: null, tracks: [] },
    { id: "c", code: "C", name: "Cby", kind: "remote", remote_from: "b", phone: null, tracks: [] },
    { id: "d", code: "D", name: "Dal", kind: "halt", remote_from: null, phone: null, tracks: [] },
    { id: "e", code: "E", name: "Ek", kind: "shadow_yard", remote_from: null, phone: null, tracks: [] },
  ],
  sections: [
    { id: "s1", place_a: "a", place_b: "c", tracks: "double", clearance_mode: null, parts: [{ id: "p1", from_place: "a", to_place: "b" }, { id: "p2", from_place: "b", to_place: "c" }], source_ids: { planning_json: "11" } },
    { id: "s2", place_a: "c", place_b: "d", tracks: "single", clearance_mode: "direct", parts: [{ id: "p3", from_place: "c", to_place: "d" }] },
  ],
  display: { graph_pages: [{ id: "g1", name: "Huvudlinjen", number: "1", places: ["a", "b", "c", "d"] }, { id: "g2", name: "Grenen", places: ["b", "e"] }] },
  trains: [
    { id: "t1", number: "101", train_type: "P", days: ["fri"], calls: [{ id: "c1", place: "a", departure: "06:00" }, { id: "c2", place: "b", arrival: "06:10", departure: "06:12" }, { id: "c3", place: "c", arrival: "06:20" }] },
    { id: "t2", number: "202", train_type: "G", days: ["thu"], calls: [{ id: "c4", place: "a", departure: "23:50" }, { id: "c5", place: "b", arrival: "00:05", day_offset: 1 }] },
  ],
} as unknown as Package;

describe("Bana: the derived confirmed, on the organiser's picture (IMPORT-04, PLAN-02)", () => {
  const draft = {
    meet: { id: "m", name: "Mellby", clearance_mode: "requested" },
    package: pkg,
    facts: [
      { ref: "section:s2", certainty: "unsure", origins: [] },
      { ref: "part:s2.1", certainty: "unsure", origins: [] },
      { ref: "place:d.kind", certainty: "unsure", origins: [] },
      { ref: "section:s1", certainty: "sure", origins: [] },
    ],
    sources: [],
  } as unknown as Draft;

  it("asks the administrator to confirm, one thing or all at once", () => {
    const all = renderToStaticMarkup(<BanaPage admin meet="m" draft={draft} />);
    expect(all).toContain('id="confirm-all"');
    expect(all).toContain("Bekräfta dem på kartan en i taget, eller alla på en gång om banan stämmer.");
    expect(renderToStaticMarkup(<BanaPage admin={false} meet="m" draft={draft} />)).not.toContain('id="confirm-all"');
    const section = renderToStaticMarkup(<BanaPage admin meet="m" draft={draft} initialChoice={{ kind: "section", id: "s2" }} />);
    expect(section).toContain("Sträckan är härledd och osäker. Stämmer den med banan?");
    expect(section).toContain('id="confirm-choice"');
    const place = renderToStaticMarkup(<BanaPage admin meet="m" draft={draft} initialChoice={{ kind: "place", id: "d" }} />);
    expect(place).toContain("Platsen är härledd och osäker.");
    const sure = renderToStaticMarkup(<BanaPage admin meet="m" draft={draft} initialChoice={{ kind: "section", id: "s1" }} />);
    expect(sure).not.toContain('id="confirm-choice"');
  });

  it("stands where the picture has the places, with the picture's lines under", () => {
    const points = { A: { x: 40, y: 100 }, B: { x: 80, y: 100 }, C: { x: 120, y: 100 }, D: { x: 160, y: 100 }, E: { x: 80, y: 140 } };
    const ids: Record<string, string> = { a: "A", b: "B", c: "C", d: "D", e: "E" };
    const placed = { ...pkg, display: { ...pkg.display, reference_layout: Object.fromEntries(Object.entries(ids).map(([id, code]) => [id, points[code as keyof typeof points]])) } } as unknown as Package;
    const picture = { source: "u-pic", page: 1, points, photo: null, links: [{ a: "A", b: "B", double: true }, { a: "B", b: "C", double: true }, { a: "C", b: "D", double: false }, { a: "B", b: "E", double: false }] };
    const html = renderToStaticMarkup(<Karta pkg={placed} choice={null} unsure={new Set()} picture={picture} onSelect={go} />);
    expect(html).toContain('id="picture"');
    expect((html.match(/<line /g) ?? []).length).toBe(4);
    expect(html).toContain('class="dubbel"');
    expect(html).toContain("M90,70 L210,70");
    expect(renderToStaticMarkup(<Karta pkg={pkg} choice={null} unsure={new Set()} picture={picture} onSelect={go} />)).not.toContain('id="picture"');
    const photographed = renderToStaticMarkup(<Karta pkg={placed} choice={null} unsure={new Set()} picture={{ ...picture, photo: { x: 200, y: 160 } }} photo="/foto" onSelect={go} />);
    expect(photographed).toContain('<image href="/foto" x="90" y="70" width="600" height="480"');
  });
});

describe("Bana (S6, H47)", () => {
  it("lays the longest way level and hangs the rest off, with track without clearance dashed", () => {
    const plan = layout(pkg);
    const row = (id: string) => plan.at.get(id)?.[1];
    expect([row("a"), row("b"), row("c"), row("d")]).toEqual([0, 0, 0, 0]);
    expect(row("e")).not.toBe(0);
    const found = links(pkg);
    expect(found.find((link) => link.b === "e")?.section).toBeNull();
    expect(found.filter((link) => link.section?.id === "s1")).toHaveLength(2);
  });

  it("draws the map and shows the chosen section, with its tracks and clearance for the administrator", () => {
    const draft = { meet: { id: "m", name: "Mellby", clearance_mode: "requested" }, package: pkg, facts: [{ ref: "section:s2", certainty: "unsure", origins: [] }], sources: [] } as unknown as Draft;
    const looking = renderToStaticMarkup(<BanaPage admin={false} meet="m" draft={draft} />);
    expect(looking).toContain('class="lank double"');
    expect(looking).toContain('class="lank single osaker"');
    expect(looking).toContain('class="lank utan"');
    expect(looking).toContain(">11</text>");
    expect(looking).toContain('aria-label="Alby"');
    expect(looking).toContain("1 uppgift är osäkra.");
    expect(looking).toContain("Välj en sträcka eller en driftplats på kartan.");
    const chosen = renderToStaticMarkup(<BanaPage admin meet="m" draft={draft} initialChoice={{ kind: "section", id: "s1" }} />);
    expect(chosen).toContain("11 · Alby – Cby");
    expect(chosen).toContain('aria-pressed="true">Dubbel</button>');
    expect(chosen).toContain("Byn (bemannad)");
    expect(chosen).toContain('<option value="" selected="">Begärd (träffens grundläge)</option>');
    expect(renderToStaticMarkup(<BanaPage admin={false} meet="m" draft={draft} initialChoice={{ kind: "section", id: "s1" }} />)).toContain("Dubbelspår");
    expect(renderToStaticMarkup(<BanaPage admin={false} meet="m" draft={{ ...draft, package: null }} onTell={go} />)).toContain("Lägg till underlag under Data först.");
  });
});

describe("Graf (S6)", () => {
  it("counts a call's minutes from the train's first day, also over midnight", () => {
    expect(times({ arrival: "23:58", departure: "00:02" })).toEqual({ arrival: 1438, departure: 1442 });
    expect(times({ arrival: "00:05", day_offset: 1 })).toEqual({ arrival: DAY + 5, departure: null });
  });

  it("follows the plan's sheets and the game week", () => {
    expect(lines(pkg).map((line) => line.name)).toEqual(["1 · Huvudlinjen", "Grenen"]);
    expect(lines({ ...pkg, display: {} } as unknown as Package)[0]?.places).toEqual(["a", "b", "c", "d"]);
    expect(trafficDays(pkg)).toEqual(["fri", "sat", "sun"]);
  });

  it("draws a train on its day, and the one from the day before that runs past midnight", () => {
    const rows = new Map([["a", 0], ["b", 1], ["c", 2]]);
    const [t1, t2] = pkg.trains ?? [];
    expect(runs(t1!, rows, "fri")).toHaveLength(1);
    expect(runs(t1!, rows, "sat")).toHaveLength(0);
    const late = runs(t2!, rows, "fri");
    expect(late).toHaveLength(1);
    expect(late[0]?.[0]?.[0]).toBe(23 * 60 + 50 - DAY);
    const line = lines(pkg)[0]!;
    expect(sheet({ pkg, line, day: "fri", kinds: new Map([["P", "passengers"]]), marks: [], perMinute: 3 }).trains.map((train) => [train.label, train.kind])).toEqual([
      ["P 101", "resande"],
      ["G 202", "okand"],
    ]);
  });

  it("numbers the check's findings, on the line or not", () => {
    const marks = marksOf(pkg, [
      { severity: "observation", message: "Spår utan klarering", code: "no_section", refs: ["b", "e"] },
      { severity: "conflict", message: "Två tåg på spår 1", code: "track_conflict", refs: ["b", "c2"] },
    ]);
    expect(marks.map((mark) => mark.number)).toEqual([1, 2]);
    expect(marks[1]).toMatchObject({ place: "b", minute: 6 * 60 + 10, days: ["fri"] });
    const [main, branch] = lines(pkg);
    expect(onLine(marks[0]!, main!)).toBe(false);
    expect(onLine(marks[0]!, branch!)).toBe(true);
    const draft = { meet: { id: "m", name: "Mellby" }, package: pkg, rulebook: { train_types: [] } } as unknown as Draft;
    const html = renderToStaticMarkup(<GrafPage draft={draft} findings={[{ id: "f1", severity: "conflict", code: "track_conflict", message: "Två tåg på spår 1", refs: ["b", "c2"] }] as never} />);
    expect(html).toContain("2 tåg på fredag på 1 · Huvudlinjen · dra i sidled för resten av dygnet");
    expect(html).toContain('<span class="pill conflict">Konflikt</span><p>Två tåg på spår 1</p>');
    expect(html).toContain('aria-pressed="true">Fredag</button>');
    expect(html).toContain('class="ring conflict"');
  });
});

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Draft, ImportPreview } from "./api";
import { changesOf, DataPage, shownValue, type Edit } from "./Data";
import { days, describePreview, Facts, reportSummary } from "./data";
import { Underlag } from "./Underlag";

const go = () => undefined;
const draft = {
  meet: { id: "varnamo", name: "Värnamo Moduldagar", clearance_mode: "requested" },
  package: {
    places: [
      { id: "nby", code: "Nby", name: "Norrby", kind: "manned", remote_from: null, phone: "101", tracks: [{ name: "1", sort_order: 0 }] },
      { id: "sjv", code: "Sjv", name: "Sjövik", kind: "remote", remote_from: "nby", phone: null, tracks: [] },
    ],
    sections: [{ id: "s1", place_a: "nby", place_b: "sjv", tracks: "single", clearance_mode: null, parts: [{ id: "p1", from_place: "nby", to_place: "sjv" }] }],
    trains: [{ id: "t1", number: "101", train_type: "P", operator: null, days: ["mon", "tue", "wed", "thu", "fri"], calls: [{ id: "c1", place: "nby", departure: "06:00", stops: true }, { id: "c2", place: "sjv", arrival: "06:10", stops: true }] }],
    duties: [],
    turns: [],
    shunting: [],
  },
  facts: [
    { ref: "place:nby", certainty: "sure", origins: [{ source: "src1", at: "places[0]" }], note: null },
    { ref: "place:nby.phone", certainty: "confirmed", origins: [{ source: "planner", at: "Data" }], note: null },
    { ref: "section:s1", certainty: "likely", origins: [{ source: "regelboken", at: "R1" }], note: null },
  ],
  sources: [{ id: "src1", filename: "varnamo.json", size: 20480, level: 4, added: "2026-11-14T08:00:00Z" }],
  questions: [],
  rulebook: { train_types: [] },
  report: { places: { manned: 1, remote: 1 }, sections: 1, parts: 1, trains: 1, calls: 2, duties: 0, turns: 0, shunting: 0, notes: [], left_out: [] },
} as unknown as Draft;

const page = (admin: boolean, given: Draft = draft) => renderToStaticMarkup(<DataPage admin={admin} meet="varnamo" draft={given} findings={[]} versions={[]} onTell={go} />);

describe("Data (S6, PLAN-37)", () => {
  it("shows everyone the blocks with where each row comes from and how sure it is", () => {
    const html = page(false);
    expect(html).toContain('<button type="button" class="chip" aria-pressed="true"><b>2 </b>Driftplatser</button>');
    expect(html).toContain('<button type="button" class="chip" aria-pressed="false"><b>1 </b>Tåg</button>');
    expect(html).toContain("Norrby");
    expect(html).toContain('<span class="kalla" title="varnamo.json">JSON</span><span class="kalla andrad" title="Ändrat i Planering">PLAN</span>');
    expect(html).toContain('<span class="pill confirmed">bekräftad</span>');
    expect(html).toContain('<span class="kalla regel" title="Regelboken">REGEL</span>');
    expect(html).toContain("Begärd (träffens)");
    expect(html).toContain("Utkast");
    expect(html).not.toContain('id="add-source"');
    expect(html).not.toContain('id="save"');
    expect(html).not.toContain("<select class=\"cell\"");
  });

  it("gives the administrator the fields, undo, redo, Spara and Lägg till underlag", () => {
    const html = page(true);
    expect(html).toContain('id="add-source"');
    expect(html).toContain('id="undo" type="button" class="ikon" title="Ångra" aria-label="Ångra" disabled=""');
    expect(html).toContain('id="save" type="button" class="primar" disabled=""');
    expect(html).toContain('<select class="cell" aria-label="Spår">');
    expect(html).toContain('<select class="cell" aria-label="Klareringsläge">');
  });

  it("asks for a source first when the meet has none", () => {
    const empty = { ...draft, package: null } as unknown as Draft;
    expect(page(false, empty)).toContain("Inget underlag än");
    expect(page(false, empty)).not.toContain('id="add-first"');
    expect(page(true, empty)).toContain('id="add-first"');
  });

  it("keeps the latest unsaved change and sends them all with Spara", () => {
    const pending: Edit[] = [
      { kind: "place", id: "nby", before: "101", after: "102" },
      { kind: "place", id: "nby", before: "102", after: null },
      { kind: "tracks", id: "s1", before: "single", after: "double" },
      { kind: "section", id: "s1", before: null, after: "direct" },
    ];
    expect(shownValue(pending, "place", "nby", "101")).toBeNull();
    expect(shownValue(pending, "place", "sjv", null)).toBeNull();
    expect(shownValue(pending.slice(0, 1), "place", "nby", "101")).toBe("102");
    expect(changesOf(pending)).toEqual([{ place: "nby", phone: "102" }, { place: "nby", phone: null }, { section: "s1", tracks: "double" }, { section: "s1", clearance_mode: "direct" }]);
  });

  it("reads the facts, the days and the report as before", () => {
    const facts = new Facts(draft.facts ?? []);
    expect(facts.certainty("place:nby")).toBe("confirmed");
    expect([...facts.sources("place:nby")]).toEqual(["src1", "planner"]);
    expect(days(["mon", "tue", "wed", "thu", "fri"])).toBe("Mån–Fre");
    expect(days(["mon", "wed"])).toBe("Mån, Ons");
    expect(days(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])).toBe("Dagl");
    expect(reportSummary(draft.report as NonNullable<Draft["report"]>)).toContain("2 driftplatser (1 bemannade, 1 fjärrstyrda), 1 klareringssträcka, 1 tåg med 2 besök");
  });
});

describe("Lägg till underlag", () => {
  const preview = {
    source: { id: "src2", filename: "varnamo.json" },
    report: { level: 4, places: { manned: 12 }, sections: 11, trains: 228 },
    first: false,
    trains: { added: 2, removed: 0, changed: 3 },
    places: { added: 0, removed: 0, changed: 0 },
    sections: { added: 0, removed: 1, changed: 0 },
    times: 5,
    tracks: 0,
    questions: 1,
    kept: 2,
  } as unknown as ImportPreview;

  it("says the level and exactly what changes before anything is put in", () => {
    expect(describePreview(preview)).toBe("2 tåg nya · 3 tåg ändrade · 1 sträcka borta · 5 tider ändrade · 1 fråga. 2 ändringar från Planering står kvar.");
    expect(describePreview({ ...preview, first: true, trains: { added: 228 }, places: { added: 12 }, sections: { added: 11 } } as unknown as ImportPreview)).toBe("Allt är nytt: 228 tåg, 12 driftplatser, 11 sträckor.");
    const html = renderToStaticMarkup(<Underlag meet="varnamo" onClose={go} onApplied={go} initial={{ name: "varnamo.json", state: "read", preview }} />);
    expect(html).toContain("Tellurians plan · 228 tåg · 12 driftplatser · 11 sträckor");
    expect((html.match(/class="fylld"/g) ?? []).length).toBe(4);
    expect(html).toContain('id="apply" type="button" class="primar">Lägg in i utkastet');
    expect(renderToStaticMarkup(<Underlag meet="varnamo" onClose={go} onApplied={go} />)).toContain('id="apply" type="button" class="primar" disabled=""');
  });
});

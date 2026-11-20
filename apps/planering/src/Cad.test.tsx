import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { planning, type CadAssemblies, type Draft, type ImportPreview } from "./api";
import { BanaPage } from "./Bana";
import { describePreview, modelLength, prototypeLength, sourceKind, type Package } from "./data";
import { FranCad, Underlag, readLine } from "./Underlag";

// Anläggning från CAD (#89 del d3, CAD-11, K4): the planner's assemblies in TrainMeet CAD in Lägg
// till underlag, grey with the reason without CAD or a login with ID; one read like a file; and
// Bana with the sections' lengths from CAD, with their origin.

const go = () => undefined;

const listed: CadAssemblies = {
  available: true,
  reason: null,
  assemblies: [{ id: "00000000-0000-4000-8000-0000000000aa", name: "Provträffens anläggning", scale: "H0", modules: 6, revision: 3, problems: 0, owner: "Planeraren", changed_at: "2026-11-20T10:00:00Z" }],
};

const preview = {
  source: { id: "u-cad", kind: "cad_assembly", filename: "Provträffens anläggning, revision 3.json", size: 10, sha256: "c".repeat(64), level: 2, added: "2026-11-20T10:00:00Z" },
  report: { source: "u-cad", level: 4, notes: ["Anläggningen Provträffens anläggning, revision 3: 6 moduler, 3 platser. 3 driftplatser i planen finns i anläggningen, och 2 sträckor får sin längd ur den."], places: {}, sections: 0, trains: 0, calls: 0, duties: 0, turns: 0 },
  first: false,
  places: { added: 0, removed: 0, changed: 0 },
  sections: { added: 0, removed: 0, changed: 0 },
  trains: { added: 0, removed: 0, changed: 0 },
  lengths: 2,
  questions: 1,
} as unknown as ImportPreview;

afterEach(() => vi.unstubAllGlobals());

describe("Lägg till underlag: Anläggning från CAD (CAD-11)", () => {
  it("is grey with the reason without CAD or a login with ID", () => {
    const grey = renderToStaticMarkup(<FranCad meet="m" busy={false} onRead={go} initial={{ available: false, reason: "Logga in med TrainMeet ID för att hämta dina anläggningar från CAD.", assemblies: [] }} />);
    expect(grey).toContain('class="fran-cad gra"');
    expect(grey).toContain('id="cad-grey"');
    expect(grey).toContain("Logga in med TrainMeet ID för att hämta dina anläggningar från CAD.");
    expect(grey).not.toContain("Läs");
  });

  it("lists the planner's assemblies, each to read like a file", () => {
    const html = renderToStaticMarkup(<Underlag meet="m" onClose={go} onApplied={go} cad={listed} />);
    expect(html).toContain("Anläggning från CAD");
    expect(html).toContain('id="cad-list"');
    expect(html).toContain("Provträffens anläggning");
    expect(html).toContain("6 moduler · H0 · revision 3 · Planeraren");
    expect(html).toContain('aria-label="Läs Provträffens anläggning"');
    const empty = renderToStaticMarkup(<FranCad meet="m" busy={false} onRead={go} initial={{ available: true, reason: null, assemblies: [] }} />);
    expect(empty).toContain("Du har inga anläggningar i CAD än.");
  });

  it("shows what the assembly gives before it is laid in", () => {
    const html = renderToStaticMarkup(<Underlag meet="m" onClose={go} onApplied={go} initial={{ name: "Provträffens anläggning", state: "read", preview }} cad={listed} />);
    expect(readLine(preview)).toBe("Anläggning från CAD · 2 sträckor får längd");
    expect(html).toContain('<span class="kalla">CAD</span>');
    expect(html).toContain("2 sträckor får sin längd ur den.");
    expect(describePreview(preview)).toBe("2 sträckor får längd ur anläggningen · 1 fråga.");
    expect(html).toContain("Anläggningen läses med kod ur modulernas riktiga geometri. Inga tokens.");
    expect(html).toContain('id="apply" type="button" class="primar"');
    expect(html).not.toContain('id="apply" type="button" class="primar" disabled=""');
  });

  it("asks the hub for the list and for one assembly, with the planner's own login", async () => {
    const asked: { url: string; method: string }[] = [];
    vi.stubGlobal("fetch", (url: string, init: RequestInit) => {
      asked.push({ url, method: init.method ?? "GET" });
      return Promise.resolve(new Response(JSON.stringify(url.endsWith("/cad") ? listed : preview), { status: url.endsWith("/cad") ? 200 : 201 }));
    });
    expect((await planning.cadAssemblies("höst")).assemblies?.[0]?.name).toBe("Provträffens anläggning");
    expect((await planning.readCad("höst", "00000000-0000-4000-8000-0000000000aa")).lengths).toBe(2);
    expect(asked).toEqual([
      { url: "/api/planering/1/meets/h%C3%B6st/cad", method: "GET" },
      { url: "/api/planering/1/meets/h%C3%B6st/cad/00000000-0000-4000-8000-0000000000aa", method: "POST" },
    ]);
  });
});

describe("Bana: the lengths from CAD's assembly, with their origin (CAD-11, IMPORT-03)", () => {
  const pkg = {
    meet: { traffic_week: { start_weekday: "fri", days: 3 } },
    clock: { start_time: "06:00" },
    places: [
      { id: "a", code: "Aby", name: "Aby", kind: "manned", tracks: [] },
      { id: "b", code: "Bby", name: "Bby", kind: "manned", tracks: [] },
      { id: "c", code: "Cby", name: "Cby", kind: "manned", tracks: [] },
    ],
    sections: [
      { id: "s1", place_a: "a", place_b: "b", tracks: "double", parts: [{ id: "p1", from_place: "a", to_place: "b" }] },
      { id: "s2", place_a: "b", place_b: "c", tracks: "single", parts: [{ id: "p2", from_place: "b", to_place: "c" }] },
    ],
    display: { reference_layout: { a: { x: 0, y: 0 }, b: { x: 200, y: 0 }, c: { x: 400, y: 0 } } },
    trains: [],
  } as unknown as Package;
  const cad = { id: "u-cad", kind: "cad_assembly", filename: "Provträffens anläggning, revision 3.json", size: 10, sha256: "c".repeat(64), level: 2, added: "2026-11-20T10:00:00Z" };
  const origin = [{ source: "u-cad", at: "Anläggningen Provträffens anläggning, revision 3: M-002 Linje 1, M-003 Linje 2" }];
  const draft = {
    meet: { id: "m", name: "Provträffen", clearance_mode: "requested" },
    package: pkg,
    sources: [cad, { id: "u-bild", kind: "track_picture", filename: "Banan.pdf", size: 1, sha256: "b".repeat(64), level: 2, added: "2026-11-20T09:00:00Z" }],
    assembly: { source: "u-cad", assembly: "00000000-0000-4000-8000-0000000000aa", name: "Provträffens anläggning", revision: 3, scale: "H0", ratio: 87, places: [], links: [], through: [], modules: 6, problems: [] },
    lengths: [{ section: "s1", length: 2500, prototype: 217.5, tracks: 2, links: ["l1"] }],
    facts: [
      { ref: "section:s1", certainty: "sure", origins: [{ source: "u-json", at: "DispatchStretches Id 1" }] },
      { ref: "section:s1.length", certainty: "likely", origins: origin, note: "2 500 mm längs spåret i modellen, 218 m i H0." },
      { ref: "display:map", certainty: "likely", origins: [{ source: "u-cad", at: "platsernas lägen" }] },
    ],
  } as unknown as Draft;

  it("shows a section's length in the model and the prototype, its origin and certainty", () => {
    const html = renderToStaticMarkup(<BanaPage admin meet="m" draft={draft} initialChoice={{ kind: "section", id: "s1" }} />);
    expect(html).toContain('id="length"');
    expect(html).toContain("2,50 m i modellen · 218 m i H0");
    expect(html).toContain("Längs spåret ur anläggningen Provträffens anläggning, 2 spår bredvid varandra.");
    expect(html).toContain('<span class="pill likely">trolig</span>');
    expect(html).toContain('<span class="kalla">CAD</span><span>Anläggningen Provträffens anläggning');
    expect(html).toContain("M-002 Linje 1, M-003 Linje 2 (längd)");
    expect(html).toContain("2 500 mm längs spåret i modellen, 218 m i H0.");
    expect(html).toContain('id="confirm-length"');
    expect(renderToStaticMarkup(<BanaPage admin={false} meet="m" draft={draft} initialChoice={{ kind: "section", id: "s1" }} />)).not.toContain('id="confirm-length"');
  });

  it("says when a section is not in the assembly, and how to get lengths at all", () => {
    expect(renderToStaticMarkup(<BanaPage admin meet="m" draft={draft} initialChoice={{ kind: "section", id: "s2" }} />)).toContain("Sträckan finns inte i anläggningen från CAD.");
    const without = { ...draft, assembly: null, lengths: [], facts: [] } as unknown as Draft;
    expect(renderToStaticMarkup(<BanaPage admin meet="m" draft={without} initialChoice={{ kind: "section", id: "s1" }} />)).toContain("Lägg till anläggningen från CAD under Data för exakta längder.");
  });

  it("stands where the assembly has the places, before the track picture", () => {
    const html = renderToStaticMarkup(<BanaPage admin meet="m" draft={draft} />);
    expect(html).toContain('id="cad-legend"');
    expect(html).toContain("Kartan står där anläggningen Provträffens anläggning har driftplatserna");
    expect(html).not.toContain('id="picture-legend"');
    expect(html).toContain("Aby – Bby · 2,50 m");
  });

  it("writes lengths as Swedish does, and names the source CAD", () => {
    expect([modelLength(830), modelLength(2500), modelLength(12345)]).toEqual(["830 mm", "2,50 m", "12,35 m"]);
    expect([prototypeLength(217.5), prototypeLength(1234)]).toEqual(["218 m", "1,2 km"]);
    expect(sourceKind({ source: "u-cad", at: "" }, draft.sources)[0]).toBe("CAD");
  });
});

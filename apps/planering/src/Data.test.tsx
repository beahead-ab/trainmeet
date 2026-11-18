import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Draft, ImportPreview } from "./api";
import { changesOf, clockValue, DataPage, shownValue, type Edit } from "./Data";
import { days, describePreview, Facts, reportSummary, sourceKind } from "./data";
import { Skriv, Underlag } from "./Underlag";

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
    // Koppla station (PLAN-05): the place and the station among the sources, or none.
    expect(changesOf([{ kind: "station", id: "p4", before: null, after: "lekby-tkl" }, { kind: "station", id: "p4", before: "lekby-tkl", after: null }])).toEqual([
      { place: "p4", station: "lekby-tkl" },
      { place: "p4", station: null },
    ]);
  });

  it("sends the grid's changes to calls and trains, and reads times as the planner types them (PLAN-01)", () => {
    const pending: Edit[] = [
      { kind: "departure", id: "c1", before: "06:00", after: "06:05" },
      { kind: "track", id: "c1", before: null, after: "1" },
      { kind: "number", id: "t1", before: "101", after: "111" },
      { kind: "note", id: "t1", before: null, after: "Ånglok" },
      { kind: "days", id: "t1", before: "mon,tue", after: "sat,sun" },
    ];
    expect(changesOf(pending)).toEqual([
      { call: "c1", field: "departure", value: "06:05" },
      { call: "c1", field: "track", value: "1" },
      { train: "t1", field: "number", value: "111" },
      { train: "t1", field: "note", value: "Ånglok" },
      { train: "t1", days: ["sat", "sun"] },
    ]);
    expect(["615", "6.15", "6:15", "0615", "06:15", "x"].map(clockValue)).toEqual(["06:15", "06:15", "06:15", "06:15", "06:15", "x"]);
  });

  it("shows the trains with their note, and every call in order", () => {
    const html = renderToStaticMarkup(<DataPage admin meet="varnamo" draft={draft} findings={[]} versions={[]} initialBlocks={["trains", "calls"]} />);
    expect(html).toContain("<th>Anmärkning</th>");
    expect(html).toContain("<b>P 101</b>");
    expect(html).toContain("Mån–Fre");
    const asked = renderToStaticMarkup(<DataPage admin meet="varnamo" draft={draft} findings={[]} versions={[]} initialBlocks={["calls"]} initialSearch="999" />);
    expect(asked).toContain('value="999"');
    expect(asked).toContain("Inget som passar filtret.");
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

/** The radio button for a choice, whatever order React writes its attributes in. */
const radio = (html: string, value: string) => html.match(new RegExp(`<input[^>]*value="${value}"[^>]*>`))?.[0] ?? "";

describe("a scanned file, before anything goes to the AI (IMPORT-05)", () => {
  it("says the pages to write down and who pays, and asks first", () => {
    const pages = { filename: "Lekby.png", pages: 3, saved: 1, model: "en-modell", tokens: 3460, trainmeet_ai: null };
    const html = renderToStaticMarkup(<Skriv pages={pages} writing={false} onWrite={go} />);
    expect(html).toContain("3 sidor att skriva av · cirka 3\u00a0460 tokens · 1 redan avskriven, kostar inget");
    expect(html).toContain("2 sidor betalas av din AI-tjänst (en-modell).");
    expect(html).toContain('id="transcribe"');
    expect(html).toContain(">Skriv av 2 sidor som stationslista</button>");
    expect(html).toContain('id="transcribe-picture"');
    expect(html).toContain(">Skriv av som graf</button>");
    const none = renderToStaticMarkup(<Skriv pages={{ ...pages, model: null }} writing={false} onWrite={go} />);
    expect(none).toContain('href="/installningar#ai"');
    expect(none).toContain("och tryck sedan Skriv av.");
    const kept = renderToStaticMarkup(<Skriv pages={{ ...pages, saved: 3, model: null }} writing={false} onWrite={go} />);
    expect(kept).toContain("Läs avskriften");
    const panel = renderToStaticMarkup(<Underlag meet="m" onClose={go} onApplied={go} initial={{ name: "Lekby.png", state: "ai", pages }} />);
    expect(panel).toContain("Skannad · skrivs av med AI");
    expect(panel).toContain("Behöver AI");
  });

  it("offers TrainMeets AI with where the pages go and who pays, chosen by the planner (#79, TK12)", () => {
    const pages = { filename: "Lekby.png", pages: 3, saved: 1, model: null, tokens: 3460, trainmeet_ai: { payer: "Västby MJK", available: 1500, price: 24, where: "Claude i Amazon Bedrock i Stockholm", own_ai: null } };
    const html = renderToStaticMarkup(<Skriv pages={pages} writing={false} onWrite={go} />);
    expect(html).toContain("TrainMeets AI");
    expect(html).toContain("Sidorna läses av Claude i Amazon Bedrock i Stockholm. 24 tokens dras från Västby MJK, som har 1\u00a0500 kvar.");
    // Nothing is chosen for the planner: the buttons wait until TrainMeets AI is chosen.
    expect(html).not.toContain("checked");
    expect(html).toMatch(/id="transcribe"[^>]*disabled=""/);
    const own = renderToStaticMarkup(<Skriv pages={{ ...pages, model: "en-modell" }} writing={false} onWrite={go} />);
    expect(radio(own, "own")).toContain('checked=""');
    expect(own).not.toMatch(/id="transcribe"[^>]*disabled=""/);
    const poor = renderToStaticMarkup(<Skriv pages={{ ...pages, trainmeet_ai: { ...pages.trainmeet_ai, available: 10 } }} writing={false} onWrite={go} />);
    expect(poor).toContain("Saldot räcker inte. Köp fler tokens i TrainMeet ID, eller koppla in egen AI.");
    expect(radio(poor, "trainmeet")).toContain('disabled=""');
    // The club's own AI on its account in ID reads for nothing (TK4, TOKEN-03).
    const theirs = renderToStaticMarkup(<Skriv pages={{ ...pages, trainmeet_ai: { ...pages.trainmeet_ai, price: 0, available: 0, own_ai: "en-modell" } }} writing={false} onWrite={go} />);
    expect(theirs).toContain("Egen AI på kontot");
    expect(theirs).toContain("Sidorna läses av den egna AI:n som Västby MJK har kopplat in i TrainMeet ID (en-modell). Inga tokens dras.");
    expect(radio(theirs, "trainmeet")).not.toContain('disabled=""');
  });
});

describe("where a fact comes from", () => {
  it("tags the source by its kind", () => {
    const sources = [
      { id: "u1", kind: "planning_json", filename: "plan.json" },
      { id: "u2", kind: "station_lists", filename: "listor.zip" },
      { id: "u3", kind: "track_picture", filename: "Banan.pdf" },
    ] as unknown as Draft["sources"];
    expect(["u1", "u2", "u3", "planner"].map((source) => sourceKind({ source, at: "x" }, sources)[0])).toEqual(["JSON", "ST", "BILD", "PLAN"]);
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
  it("shows each station list's verdict against the planning file (IMPORT-27)", () => {
    const lists = {
      ...preview,
      source: { id: "src3", kind: "station_lists", filename: "lists.zip" },
      report: {
        level: 1,
        trains: 0,
        sections: 0,
        verdicts: [
          { document: "Lek Lekby.odt", place: "lek", rows: 52, agreeing: 52, differences: [] },
          { document: "R Rotebro.odt", place: "r", rows: 72, agreeing: 71, differences: ["Tåg 538 vid Rotebro: avgång 10:42 i listan, 10:40 i planen."] },
        ],
      },
      trains: { added: 0, removed: 0, changed: 0 },
      sections: { added: 0, removed: 0, changed: 0 },
      times: 0,
      questions: 0,
      kept: 0,
    } as unknown as ImportPreview;
    const html = renderToStaticMarkup(<Underlag meet="varnamo" onClose={go} onApplied={go} initial={{ name: "lists.zip", state: "read", preview: lists }} />);
    expect(html).toContain("Stationslistor · 2 listor · 124 tågbesök");
    expect(html).toContain("52 av 52 tågbesök stämmer");
    expect(html).toContain("Skiljer");
    expect(html).toContain("avgång 10:42 i listan, 10:40 i planen.");
  });

  it("says what the lists alone give, derived and osäkert (IMPORT-17)", () => {
    const derived = {
      ...preview,
      source: { id: "src4", kind: "station_lists", filename: "lists.zip" },
      report: { level: 1, places: { manned: 11, shadow_yard: 3, remote: 1, halt: 7 }, sections: 14, trains: 228, verdicts: [] },
      first: true,
      trains: { added: 228 },
      places: { added: 22 },
      sections: { added: 14 },
    } as unknown as ImportPreview;
    const html = renderToStaticMarkup(<Underlag meet="varnamo" onClose={go} onApplied={go} initial={{ name: "lists.zip", state: "read", preview: derived }} />);
    expect(html).toContain("Stationslistor · 228 tåg · 22 driftplatser · 14 sträckor, härledda");
    expect(html).toContain("Allt är nytt: 228 tåg, 22 driftplatser, 14 sträckor.");
    expect(html).toContain("osäkra tills du bekräftar dem i Bana");
    expect(html).not.toContain('id="verdicts"');
    const judged = { ...preview, report: { ...preview.report, verdicts: [{ document: "Lek Lekby.odt", place: "lek", rows: 52, agreeing: 52, differences: [] }] } } as unknown as ImportPreview;
    const both = renderToStaticMarkup(<Underlag meet="varnamo" onClose={go} onApplied={go} initial={{ name: "varnamo.json", state: "read", preview: judged }} />);
    expect(both).toContain('id="changes"');
    expect(both).toContain("Stationslistorna som redan är underlag får en dom var");
  });

  it("says what the track picture gives on top of the lists (level 2)", () => {
    const note = "Utkastet är härlett ur 14 stationslistor och banbilden. Banbilden visar 14 av 14 sträckor, 9 platser emellan och dubbelspår på 6 sträckor.";
    const drawn = {
      ...preview,
      source: { id: "src5", kind: "track_picture", filename: "Banan.pdf" },
      report: { level: 2, places: { manned: 11, shadow_yard: 3, remote: 1, halt: 16 }, sections: 14, trains: 228, verdicts: [], notes: [note] },
    } as unknown as ImportPreview;
    const html = renderToStaticMarkup(<Underlag meet="varnamo" onClose={go} onApplied={go} initial={{ name: "Banan.pdf", state: "read", preview: drawn }} />);
    expect(html).toContain("Banbild och stationslistor · 228 tåg · 31 driftplatser · 14 sträckor");
    expect(html).toContain(">BILD<");
    expect(html).toContain(note);
    expect((html.match(/class="fylld"/g) ?? []).length).toBe(2);
    const kept = { ...drawn, report: { level: 2, trains: 0, sections: 0, notes: ["Planeringsfilen har redan banan; banbilden sparas som underlag."] } } as unknown as ImportPreview;
    expect(renderToStaticMarkup(<Underlag meet="varnamo" onClose={go} onApplied={go} initial={{ name: "Banan.pdf", state: "read", preview: kept }} />)).toContain("Banbild · sparas som underlag");
  });
});

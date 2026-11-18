import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Draft } from "./api";
import { isOwn, routeOf } from "./App";
import { byLevel, dutyFront, ForarnaPage } from "./Forarna";
import type { Package } from "./data";

const call = (id: string, place: string, arrival: string | null, departure: string | null) => ({ id, place, arrival, departure, track: null, day_offset: 0, stops: true, exchange: true, note: null });

const pkg = {
  format: "trainmeet.meet/1",
  meet: { id: "grimslov", name: "Grimslöv" },
  clock: { start_time: "06:00" },
  places: [
    { id: "nby", code: "Nby", name: "Norrby", kind: "manned" },
    { id: "sjv", code: "Sjv", name: "Sjövik", kind: "manned" },
  ],
  trains: [
    { id: "t101", number: "101", days: ["mon"], calls: [call("t101-nby", "nby", null, "06:00"), call("t101-sjv", "sjv", "06:29", null)] },
    { id: "t104", number: "104", days: ["mon"], calls: [call("t104-sjv", "sjv", null, "07:05"), call("t104-nby", "nby", "07:34", null)] },
  ],
  duties: [
    { id: "d1", name: "39", level: "medium", legs: [{ train: "t101", from_call: "t101-nby", to_call: "t101-sjv" }, { train: "t104", from_call: "t104-sjv", to_call: "t104-nby" }] },
    { id: "d2", name: "40", level: "easy", legs: [{ train: "t104", from_call: "t104-sjv", to_call: "t104-nby" }] },
    { id: "d3", name: "41", level: null, legs: [{ train: "t101", from_call: "t101-nby", to_call: "t101-sjv" }] },
  ],
  about: { sv: { instructions: "Lägg tillbaka tjänsten när du är klar." } },
  attachments: [{ id: "instruktioner", kind: "instructions", filename: "Allmänt.pdf", media_type: "application/pdf", size: 20480, sha256: "0".repeat(64) }],
} as unknown as Package;

const draft = { meet: { id: "grimslov", name: "Grimslöv" }, revision: 3, package: pkg } as unknown as Draft;
const nothing = () => undefined;

describe("Förarna in Planering (PLAN-40)", () => {
  it("is a page of the meet, at /planering/<meet>/forarna", () => {
    expect(routeOf("/planering/grimslov/forarna")).toEqual({ page: "forarna", meet: "grimslov" });
    expect(isOwn("/planering/grimslov/forarna")).toBe(true);
  });

  it("shows the duties per driver level, as the papers' fronts say them (LOK-19, LOK-32)", () => {
    expect(byLevel(pkg).map(([level, duties]) => [level, duties.map((duty) => duty.name)])).toEqual([
      ["easy", ["40"]],
      ["medium", ["39"]],
      ["", ["41"]],
    ]);
    expect(dutyFront(pkg.duties![0]!, pkg)).toBe("06:00 Norrby – 07:34 Norrby · 101, 104");
    const html = renderToStaticMarkup(<ForarnaPage admin meet="grimslov" draft={draft} onDraft={nothing} onTell={nothing} onFail={nothing} />);
    expect(html).toContain("<b>Lätt</b>");
    expect(html).toContain("<b>Medel</b>");
    expect(html).toContain("<b>Utan svårighet</b>");
    expect(html).toContain("06:00 Norrby – 07:34 Norrby · 101, 104");
  });

  it("has the general instructions as text and as PDF (LOK-34)", () => {
    const html = renderToStaticMarkup(<ForarnaPage admin meet="grimslov" draft={draft} onDraft={nothing} onTell={nothing} onFail={nothing} />);
    expect(html).toContain("Lägg tillbaka tjänsten när du är klar.");
    expect(html).toContain('href="/api/planering/1/meets/grimslov/attachments/instruktioner"');
    expect(html).toContain("Visa Allmänt.pdf");
    expect(html).toContain("20 kB");
    expect(html).toContain("Byt PDF");
    expect(html).toContain("Ta bort PDF:en");
    expect(html).toContain("Spara texten");
  });

  it("lets only the organiser change them", () => {
    const html = renderToStaticMarkup(<ForarnaPage admin={false} meet="grimslov" draft={draft} onDraft={nothing} onTell={nothing} onFail={nothing} />);
    expect(html).toContain("Bara arrangören ändrar instruktionerna.");
    expect(html).toContain("readOnly");
    expect(html).not.toContain("Spara texten");
    expect(html).not.toContain("Ta bort PDF:en");
  });

  it("says when the meet has no duties, and speaks English", () => {
    const without = { ...draft, package: { ...pkg, duties: [], attachments: [] } } as unknown as Draft;
    const html = renderToStaticMarkup(<ForarnaPage admin meet="grimslov" draft={without} language="en" onDraft={nothing} onTell={nothing} onFail={nothing} />);
    expect(html).toContain("The meet has no duties.");
    expect(html).toContain("No PDF is added.");
    expect(html).toContain("Add PDF");
  });
});

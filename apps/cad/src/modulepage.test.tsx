import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ModulePage } from "./ModulePage";
import { CLUB, CURVE, HISTORY, STATION } from "./testdata";

function page(overrides: Partial<Parameters<typeof ModulePage>[0]> = {}): string {
  return renderToStaticMarkup(<ModulePage module={CURVE} history={HISTORY} tab="oversikt" clubs={[CLUB]} {...overrides} />);
}

describe("Modulens sida", () => {
  it("has the tabs Översikt, Ritning, Foto, Landskap and Historik", () => {
    const html = page();
    for (const tab of ["Översikt", "Ritning", "Foto", "Landskap", "Historik"]) expect(html).toContain(`>${tab}</a>`);
    expect(html).toContain('href="/moduler/1f7d3a1b-2c3d-4e4f-9051-6b7c8d9e0f1a" aria-current="page"');
  });

  it("shows an approved module with its version, gables, who sees it and where it is used", () => {
    const html = page();
    expect(html).toContain("✓ Godkänd 19 nov 2026");
    expect(html).toContain("Version 1");
    expect(html).toContain("Gavel A · Dubbelspår");
    expect(html).toContain("200 250");
    expect(html).toContain("Vem ser modulen");
    expect(html).toContain(`checked="" value="me"`);
    expect(html).toContain("Min klubb");
    expect(html).toContain("Alla i TrainMeet");
    expect(html).toContain("Används i");
    expect(html.match(/ingen än/g)?.length).toBe(2);
    expect(html).toContain("2 + 2");
    expect(html).not.toContain(">Godkänn</button>");
  });

  it("offers Godkänn on a draft to the one who may change it, and nothing to a viewer", () => {
    expect(page({ module: STATION })).toContain(">Godkänn</button>");
    expect(page({ module: STATION })).toContain("Ändra måtten");
    const viewer = page({ module: { ...STATION, may_edit: false, owner: { kind: "person", id: CLUB.id, name: "Kim Ek" } } });
    expect(viewer).not.toContain(">Godkänn</button>");
    expect(viewer).not.toContain("Ändra måtten");
    expect(viewer).toContain('<fieldset class="cad-kort cad-vem" disabled="">');
    expect(viewer).toContain("Ägare: Kim Ek.");
  });

  it("lists the history, newest first, with the versions to look at", () => {
    const html = page();
    expect(html.indexOf("Version 1 godkänd")).toBeLessThan(html.indexOf("Modulen skapad ur mått"));
    expect(html).toContain("Visa version 1");
  });

  it("shows an older version as such", () => {
    const html = page({ module: { ...STATION, version: 1, latest: 2 } });
    expect(html).toContain("Du ser version 1 av 2.");
    expect(html).not.toContain(">Godkänn</button>");
  });

  it("draws the module read-only under Ritning, and says Foto and Landskap come later", () => {
    const drawing = page({ tab: "ritning" });
    expect(drawing).toContain("Spårgrafen ur måtten · 2 spårbitar · 4 noder");
    expect(drawing).toContain('aria-label="Kurva 30° · K2 ovanifrån"');
    expect(page({ tab: "foto" })).toContain("Kommer med foto och kontroll.");
    expect(page({ tab: "landskap" })).toContain("Kommer med landskapet.");
    expect(page({ module: STATION, tab: "ritning" })).toContain("Spåren mellan gavlarna är okända tills modulen är fotad");
  });
});

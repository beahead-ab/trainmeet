import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { areaText, LandskapView, strokeOp, thin, type ViewProps } from "./Landskap";
import { STATION } from "./testdata";
import { APPROVED, MODULE_WITH_LANDSCAPE, NONE, PROPOSAL } from "./testlandskap";

function view(overrides: Partial<ViewProps> = {}): string {
  return renderToStaticMarkup(
    <LandskapView module={MODULE_WITH_LANDSCAPE} landscape={PROPOSAL} edits={0} undone={0} tool="paint" surface="grass" radius={20} photoUnder={false} {...overrides} />,
  );
}

describe("Landskapet", () => {
  it("shows the photo's surfaces as a proposal in orange until approved", () => {
    const html = view();
    expect(html).toContain('<span class="cad-tagg forslag">Förslag</span>');
    expect(html).toContain("Färgklustring av mätbilden");
    // The proposal's own surfaces get the orange edge; the owner's painted pond does not.
    expect(html.match(/class="cad-forslagskant"/g)?.length).toBe(1);
    expect(html).toContain('class="cad-yta forslag" data-yta="grass"');
    expect(html).toContain('class="cad-yta" data-yta="water"');
    expect(html).toContain("Ytorna med orange kant är ett förslag ur fotot tills du godkänner landskapet.");
    expect(html).toContain(">✓ Godkänn landskapet</button>");
    expect(html).toContain("tills TrainMeets egen modell för landskapet är tränad");
  });

  it("calls a landscape painted by hand an Utkast, not a proposal, until approved", () => {
    const painted = (PROPOSAL.areas ?? []).map((a) => ({ ...a, painted: true }));
    const html = view({ landscape: { ...PROPOSAL, method: "hand", made_by: "Målat för hand", areas: painted } });
    expect(html).toContain('<span class="cad-status utkast">Utkast</span>');
    expect(html).not.toContain("Förslag");
    expect(html).not.toContain("cad-forslagskant");
    expect(html).toContain("Målat för hand");
  });

  it("has the tools Måla, Sudda and Fyll, the surfaces and the brush", () => {
    const html = view({ tool: "erase", edits: 2 });
    for (const tool of ["Måla", "Sudda", "Fyll"]) expect(html).toContain(`>${tool}</button>`);
    expect(html).toContain('aria-pressed="true" title="Sudda bort en yta, till exempel en skugga som blivit en buske">Sudda');
    for (const name of ["Gräs", "Ballast", "Mark och väg", "Plattform", "Vatten", "Byggnad", "Buske och träd", "Stig"]) expect(html).toContain(name);
    // Okänd yta is offered only when the landscape has it.
    expect(html).not.toContain("Okänd yta");
    expect(html).toContain('<option value="40">40 mm</option>');
    expect(html).toContain("2 ändringar som inte är sparade");
    expect(html).toContain('class="cad-landskap-yta verktyg-erase"');
    expect(html).toContain("Spåren och ballasten under dem ritas från spårplanen, aldrig ur fotot.");
  });

  it("legends the surfaces with their areas, the track bed as ballast", () => {
    const html = view();
    expect(html).toContain("Ytor på modulen");
    expect(html).toContain("0,90 m²");
    expect(html).toContain("86 %");
    expect(html).toContain("0,030 m²");
    expect(html).toContain('class="cad-sparbadd"');
  });

  it("approved: no orange, no Godkänn, and a viewer gets no tools", () => {
    const html = view({ landscape: APPROVED });
    expect(html).toContain("✓ Godkänt");
    expect(html).not.toContain("cad-forslagskant");
    expect(html).not.toContain("Godkänn landskapet");
    const viewer = view({ module: { ...MODULE_WITH_LANDSCAPE, may_edit: false } });
    expect(viewer).not.toContain('role="toolbar"');
    expect(viewer).toContain("Bara ägaren och de med rollen redigera ändrar landskapet.");
    const older = view({ module: { ...MODULE_WITH_LANDSCAPE, version: 2 } });
    expect(older).toContain("Du ser version 2.");
  });

  it("offers the landscape from the measuring image, or an empty one without a photo", () => {
    expect(view({ landscape: NONE })).toContain(">Gör landskapet ur mätbilden</button>");
    const bare = view({ module: { ...STATION, photo: null }, landscape: { ...NONE, photo: null } });
    expect(bare).toContain("Modulen är inte fotad. Börja med ett tomt landskap och måla ytorna själv. Gratis.");
    expect(bare).toContain(">Börja med ett tomt landskap</button>");
    expect(view({ landscape: null })).toContain("Hämtar landskapet");
  });

  it("makes a stroke an operation, thinned, and a click a fill", () => {
    const points: [number, number][] = [[0, 0], [1, 0], [2, 0], [8, 0], [9.04, 0.04], [30, 0]];
    expect(thin(points, 5)).toEqual([[0, 0], [8, 0], [30, 0]]);
    expect(strokeOp("paint", "water", 15, points)).toEqual({ op: "paint", surface: "water", radius: 15, points: [[0, 0], [8, 0], [30, 0]] });
    expect(strokeOp("erase", "water", 15, points)).toMatchObject({ op: "erase", radius: 15 });
    expect(strokeOp("fill", "path", 15, [[12, 34]])).toEqual({ op: "fill", surface: "path", at: [12, 34] });
    expect(strokeOp("paint", "grass", 10, [])).toBeNull();
    expect(areaText(1_234_000)).toBe("1,23 m²");
  });
});

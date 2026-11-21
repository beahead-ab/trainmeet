import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AnyRailUpload, AnyRailView, grouped, MEASURES, shown, stored, type AnyRailViewProps } from "./AnyRail";
import { routeFor, tabOf } from "./routes";
import { ANYRAIL } from "./testanyrail";

const ALL = new Set((ANYRAIL.modules ?? []).map((m) => m.key));
const ASSUMED = (ANYRAIL.switches ?? []).find((s) => s.assumed);

function page(overrides: Partial<AnyRailViewProps> = {}): string {
  return renderToStaticMarkup(<AnyRailView found={ANYRAIL} chosen={ALL} names={{}} confirmed={new Set()} {...overrides} />);
}

describe("Import från AnyRail (#91)", () => {
  it("has its own addresses under Ny modul", () => {
    expect(routeFor("/moduler/ny/anyrail")).toEqual({ page: "anyrail" });
    expect(routeFor(`/moduler/ny/anyrail/${ANYRAIL.id}`)).toEqual({ page: "anyrail", id: ANYRAIL.id });
    expect(routeFor("/moduler/ny/anyrail/inte-ett-id").page).toBe("missing");
    expect(tabOf({ page: "anyrail" })).toBe("library");
  });

  it("uploads AnyRail's own file or its XML export, and says the file stays in CAD", () => {
    const html = renderToStaticMarkup(<AnyRailUpload />);
    expect(html).toContain('accept=".any,.xml,.zip');
    expect(html).toContain("Filen stannar i CAD");
    expect(renderToStaticMarkup(<AnyRailUpload busy />)).toContain("Läser filen …");
  });

  it("shows three measures and keeps the others under Fler mått, folded (AR5, AR6)", () => {
    const html = page();
    const [before, after] = html.split('<details class="cad-anyrail-fler">');
    for (const name of ["track_width", "join_distance", "lateral"]) expect(before).toContain(`name="${name}"`);
    for (const name of ["crossing_node", "crossing_angle", "backward_length", "tight_radius"]) {
      expect(before).not.toContain(`name="${name}"`);
      expect(after).toContain(`name="${name}"`);
    }
    expect(html).toContain('<details class="cad-anyrail-fler"><summary>Fler mått</summary>');
    expect(html).toContain('inputMode="decimal" name="track_width" value="1,65"');
    expect(html).toContain('inputMode="decimal" name="join_distance" value="4"');
    expect(html).toContain('inputMode="decimal" name="lateral" value="6"');
    expect(after).toContain('inputMode="decimal" name="tight_radius" value="400"');
    expect(html).toContain("Filen är läst med förvalen.");
    const measure = MEASURES[0];
    expect(measure && shown(measure, 16.5)).toBe("1,65");
    expect(measure && stored(measure, "1,8")).toBe(18);
    expect(measure && stored(measure, "inget")).toBeNull();
  });

  it("proposes the modules on the drawing, to approve each or all, with their standard size", () => {
    const html = page();
    expect(html).toContain('aria-label="Ritningen ur AnyRail med modulerna"');
    for (const number of ["1", "2a", "2b", "3", "Ä1", "Ä2"]) expect(html).toContain(`aria-label="Namn på modul ${number}"`);
    expect(html).toContain('value="Ändmodul Ä1"');
    expect(html).toContain("Standard 1500 × 350");
    expect(html).toContain("Godkänn alla");
    expect(html).toContain("6 av 6 moduler godkända.");
    expect(page({ chosen: new Set() })).toContain("0 av 6 moduler godkända.");
  });

  it("stands an assumed switch yellow until it is confirmed (AR3)", () => {
    expect(ASSUMED?.confirm).toBeTruthy();
    const open = page();
    expect(open).toContain(`<li class="antagen" data-vaxel="${ASSUMED?.number}">`);
    expect(open).toContain('class="cad-anyrail-vaxel antagen"');
    expect(open).toContain("1 antagna växlar står gula.");
    const done = page({ confirmed: new Set([ASSUMED?.confirm ?? ""]) });
    expect(done).not.toContain('class="cad-anyrail-vaxel antagen"');
    expect(done).toContain("· bekräftad");
    expect(done).toContain("Alla antagna växlar är bekräftade.");
  });

  it("lists the checks by kind, and the exports", () => {
    const groups = grouped(ANYRAIL.checks ?? []).map(([title, items]) => `${title} (${items.length})`);
    expect(groups).toContain("Antagna växlar (1)");
    expect(groups).toContain("Lösa delar (1)");
    expect(groups).toContain("Växlar över en modulskarv (1)");
    const html = page();
    expect(html).toContain("<summary>Borttagna öglor, broar och väggar (1)</summary>");
    expect(html).toContain(`href="/api/cad/1/anyrail/${ANYRAIL.id}/files/anlaggning.dxf" download="exempelstation-anlaggning.dxf"`);
    expect(html).toContain(`download="exempelstation-vaxlar.csv"`);
    expect(html).toContain(`download="exempelstation-gavelprofiler.csv"`);
    expect(html).toContain("DXF, modul 2a");
  });

  it("shows a track drawn twice among the drawing's fixes, yellow until confirmed in the module", () => {
    const doubled = {
      key: "drawing_fix:doubled:7",
      kind: "drawing_fix",
      at: [500, 300],
      title: "Två spår ritade ovanpå varandra lästes som ett",
      text: "Ett spår på 0,80 m låg inom 6 mm från ett annat.",
      refs: ["7"],
      choices: [{ id: "stammer", text: "Det stämmer" }],
      assumed: true,
    } as unknown as NonNullable<typeof ANYRAIL.checks>[number];
    const found = { ...ANYRAIL, checks: [...(ANYRAIL.checks ?? []), doubled], stats: { ...ANYRAIL.stats, doubled_removed: 1 } };
    const html = renderToStaticMarkup(<AnyRailView found={found} chosen={ALL} names={{}} confirmed={new Set()} />);
    expect(html).toContain("1 dubbelritade spår borttagna");
    expect(html).toContain('<b>Två spår ritade ovanpå varandra lästes som ett</b>');
    expect(html).toContain('<span class="cad-tagg gul">Ska bekräftas</span>');
    expect(page()).not.toContain("dubbelritade");
  });

  it("links the modules and the assembly once they are made", () => {
    const created = {
      modules: [{ ...((ANYRAIL.modules ?? [])[0] as object), id: "3d7f1c2a-0b1e-4c5d-8e6f-7a8b9c0d1e2f", number: "M-001", name: "Modul 1" }],
      assembly: "4e8a2d3b-1c2f-4d6e-9f70-8b9cad0e1f30",
      assembly_name: "Exempelstation",
      at: "2026-11-20T12:00:00Z",
    } as unknown as NonNullable<AnyRailViewProps["created"]>;
    const html = page({ created });
    expect(html).toContain('href="/anlaggningar/4e8a2d3b-1c2f-4d6e-9f70-8b9cad0e1f30">Exempelstation</a>');
    expect(html).toContain('href="/moduler/3d7f1c2a-0b1e-4c5d-8e6f-7a8b9c0d1e2f">M-001 Modul 1</a>');
    expect(html).not.toContain("Skapa modulerna</button>");
  });
});

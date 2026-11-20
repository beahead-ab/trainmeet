import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { dxfHref, ExportView, mmText } from "./Export";
import { routeFor } from "./routes";
import { EXPORT } from "./testlandskap";

function page(overrides: Partial<Parameters<typeof ExportView>[0]> = {}): string {
  return renderToStaticMarkup(<ExportView found={EXPORT} rails={false} landscape {...overrides} />);
}

describe("Exportera", () => {
  it("offers the FREMO sheet, the module database, MMM, DXF and the print", () => {
    const html = page();
    for (const choice of ["FREMO-ritning", "Moduldatabasen", "MMM", "DXF", "Utskrift"]) expect(html).toContain(`<h2>${choice}</h2>`);
    expect(html).toContain('href="/api/cad/1/modules/0e6c2f0a-1b2c-4d3e-8f40-5a6b7c8d9e0f/export/4/fremo.svg" download="M-001-exempelstation-v4-fremo.svg"');
    expect(html).toContain("trainmeet.cad.moduldatabas/1");
    expect(html).toContain(">JSON</a>");
    expect(html).toContain(">CSV</a>");
    expect(html).toContain("MMM:s blanketter kommer senare.");
    expect(html).toContain("DXF R12 i mm: spårmitt som riktiga LINE och ARC");
    expect(html).toContain("Exporten är gratis.");
    // The print shows only the sheets (landskap.css, @media print).
    expect(html).toContain('<div class="cad-utskrift" aria-hidden="true"><img class="cad-utskriftssida"');
  });

  it("marks a draft Utkast and lets the approved version be chosen", () => {
    const html = page();
    expect(html).toContain('<span class="cad-tagg forslag">Utkast</span>');
    expect(html).toContain("Version 4 är inte godkänd. Allt som exporteras märks Utkast.");
    expect(html).toContain('href="/moduler/0e6c2f0a-1b2c-4d3e-8f40-5a6b7c8d9e0f/exportera?version=2"');
    expect(html).toContain(">Godkänd version 2</a>");
    const approved = page({ found: { ...EXPORT, status: "approved", versions: [EXPORT.versions[0]!] } });
    expect(approved).not.toContain("märks Utkast");
    expect(approved).toContain("✓ Godkänd");
    expect(approved).not.toContain("Version att exportera");
  });

  it("shows MMM's measures with the deviation over 2 mm marked", () => {
    const html = page();
    expect(html).toContain('<tr class="avviker"><td>2</td><td class="tm-mono">200,5</td><td class="tm-mono">60,5</td><td class="tm-mono">197</td><td class="tm-mono">3,5</td></tr>');
    expect(mmText(-2.26)).toBe("−2,3");
    expect(mmText(null)).toBe("–");
  });

  it("asks for the DXF with the rails and the landscape as chosen", () => {
    expect(dxfHref(EXPORT, true, false)).toBe(`/api/cad/1/modules/${EXPORT.module}/export/4/modul.dxf?rails=true&landscape=false`);
    expect(dxfHref({ ...EXPORT, landscape: false }, false, true)).toContain("landscape=false");
    const without = page({ found: { ...EXPORT, landscape: false } });
    expect(without).toContain("Landskapet (modulen har inget landskap)");
  });

  it("has its own address under the module", () => {
    expect(routeFor("/moduler/0e6c2f0a-1b2c-4d3e-8f40-5a6b7c8d9e0f/exportera", "?version=2")).toEqual({
      page: "export",
      id: "0e6c2f0a-1b2c-4d3e-8f40-5a6b7c8d9e0f",
      version: 2,
    });
  });
});

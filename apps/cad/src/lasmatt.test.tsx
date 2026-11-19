import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { LasMatt } from "./LasMatt";
import { CURVE } from "./testdata";
import { PROPOSAL } from "./testdrawing";

const TRAPEZOID = {
  ...CURVE,
  name: "Trapets 480/280",
  shape: { kind: "trapezoid" as const, length: 685, width_a: 480, width_b: 280, offset: 131.5 },
  gables: [
    { end: "A" as const, label: "MMM enkelspår", norm: "mmm" as const, profile: "h0-mmm-enkelspar", tracks: [140] },
    { end: "B" as const, label: "MMM enkelspår", norm: "mmm" as const, profile: "h0-mmm-enkelspar", tracks: [140] },
  ],
};

function page(overrides: Partial<Parameters<typeof LasMatt>[0]> = {}): string {
  return renderToStaticMarkup(<LasMatt module={TRAPEZOID} proposal={PROPOSAL} {...overrides} />);
}

describe("Lås mått", () => {
  it("has the breadcrumb, the title, the module's size and norm, and the two choices", () => {
    const html = page();
    expect(html).toContain('<span aria-current="page">Lås mått</span>');
    expect(html).toContain(">Ritningen</a>");
    expect(html).toContain('<h1 id="rubrik">Lås ett mått, räkna om kurvan</h1>');
    expect(html).toContain(">685 × 480/280</span>");
    expect(html).toContain('<span class="cad-bricka">MMM</span>');
    expect(html).toContain(">Behåll linjen</a>");
    expect(html).toContain(">✓ Använd geometrin</button>");
    expect(html).not.toMatch(/disabled="">✓ Använd geometrin/);
  });

  it("draws the old line dashed, the new geometry, the tangent points and the parts", () => {
    const html = page();
    expect(html).toContain('class="cad-gammal"');
    expect(html).toContain("stroke-dasharray");
    expect(html.match(/class="cad-tangent"/g)?.length).toBe(4);
    expect(html.match(/class="cad-spar"/g)?.length).toBe(5);
    expect(html).toMatch(/>rakt 82<\/text>/);
    expect(html).toMatch(/>R 568<\/text>/);
    expect(html).toMatch(/>rakt 217 · 19°<\/text>/);
    expect(html).toContain("GAVEL A · 480");
    expect(html).toContain("GAVEL B · 280");
    expect(html).toContain("ny geometri");
    expect(html).toContain("tangentpunkt");
  });

  it("lists the locked measures with what the line said, and why", () => {
    const html = page();
    expect(html).toContain("Gavel A · spår 1</b><span class=\"cad-dampad\">linjen sa 138 mm</span>");
    expect(html).toContain("Gavel B · spår 1</b><span class=\"cad-dampad\">linjen sa 141 mm</span>");
    expect(html).toContain('name="las-A" value="140"');
    expect(html).toContain("MMM-normen säger 140 mm från Kant 1. Linjen låg 2 mm ifrån, så måttet låses och kurvan räknas om.");
  });

  it("has Kurvan: same or different radii, the table of parts and the deviation", () => {
    const html = page();
    expect(html).toContain('name="radier" checked="" value="same"');
    expect(html).toContain("Samma radie i båda bågarna");
    expect(html).toContain("Olika radier");
    for (const row of ["Rakt från gavel A", "Båge", "Rakt", "Rakt till gavel B"]) expect(html).toContain(`<td>${row}</td>`);
    expect(html).toContain('<td class="tm-mono">R 568 mm</td>');
    expect(html).toContain('<td class="tm-mono">217 mm · 19°</td>');
    expect(html).toContain("✓ Avviker median 0,3 mm");
    expect(html).toContain("högst 2,5 mm");
    expect(html).toContain("DXF-filen får riktiga linjer och bågar för spårmitten");
  });

  it("says why when there is no solution, and Använd geometrin waits", () => {
    const none = { ...PROPOSAL, solved: false, parts: [], new: [], tangents: [], deviation: null, why: "Spåret ska flytta 400 mm i sidled mellan gavlarna." };
    const html = page({ proposal: none });
    expect(html).toContain('<p class="cad-fel">Spåret ska flytta 400 mm i sidled mellan gavlarna.</p>');
    expect(html).toMatch(/disabled="">✓ Använd geometrin/);
  });
});

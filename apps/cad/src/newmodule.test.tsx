import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { NewModulePage } from "./NewModule";

describe("Ny modul", () => {
  it("has four ways in, and only Bara mått works now", () => {
    const html = renderToStaticMarkup(<NewModulePage tokens={86} />);
    for (const way of ["Fota med mobilen", "Ladda upp ett foto", "Från en skiss", "Bara mått"]) expect(html).toContain(way);
    expect(html.match(/Kommer med foto och kontroll/g)?.length).toBe(3);
    expect(html).toContain("12 tokens per bild");
    expect(html).toContain("Gratis");
    expect(html).toContain('href="/moduler/ny/rak"');
    expect(html).toContain('href="/moduler/ny/kurva"');
    expect(html).toContain('href="/moduler/ny/trapets"');
    expect(html).toContain("◎ 86 tokens kvar");
  });

  it("says when the files come: TrainMeet-modul and DXF in part d, AnyRail with #91", () => {
    const html = renderToStaticMarkup(<NewModulePage />);
    expect(html).toContain("TrainMeet-modul från Exportera");
    expect(html).toContain("DXF-ritning");
    expect(html).toMatch(/<button type="button" class="tm-knapp" disabled="">AnyRail<\/button>/);
    expect(html).toContain("kommer med exporten och anläggningarna (del d)");
    expect(html).toContain("AnyRail-importen (ärende 91)");
  });
});

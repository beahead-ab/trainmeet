import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { NewModulePage } from "./NewModule";

describe("Ny modul", () => {
  it("has four ways in: Fota med mobilen (#90), Ladda upp ett foto, Från en skiss and Bara mått", () => {
    const html = renderToStaticMarkup(<NewModulePage tokens={86} />);
    for (const way of ["Fota med mobilen", "Ladda upp ett foto", "Från en skiss", "Bara mått"]) expect(html).toContain(way);
    expect(html).toContain('<a class="tm-knapp primar" href="/moduler/ny/foto">Ladda upp foto</a>');
    expect(html).toContain("12 tokens per mätbild");
    expect(html).toContain("Utan AI gratis");
    expect(html).not.toContain("Kommer med CAD i mobilen");
    expect(html).toContain('<article class="cad-kort cad-vag-aktiv" id="fota-med-mobilen">');
    expect(html).toContain('<button type="button" class="tm-knapp primar">Visa QR-koden</button>');
    expect(html).not.toContain("Kommer i nästa steg av bildkedjan");
    expect(html).toContain('<a class="tm-knapp primar" href="/moduler/ny/skiss">Ladda upp skiss</a>');
    expect(html).toContain("12 tokens per skiss");
    expect(html).toContain("± 20 mm");
    expect(html).not.toContain("Kommer med foto och kontroll");
    expect(html).toContain("Gratis");
    expect(html).toContain('href="/moduler/ny/rak"');
    expect(html).toContain('href="/moduler/ny/kurva"');
    expect(html).toContain('href="/moduler/ny/trapets"');
    expect(html).toContain("◎ 86 tokens kvar");
  });

  it("says when the files come: TrainMeet-modul and DXF in part d; AnyRail is read here (#91)", () => {
    const html = renderToStaticMarkup(<NewModulePage />);
    expect(html).toContain("TrainMeet-modul från Exportera");
    expect(html).toContain("DXF-ritning");
    expect(html).toContain('<a class="tm-knapp" href="/moduler/ny/anyrail">AnyRail</a>');
    expect(html).not.toContain("ärende 91");
    expect(html).toContain("kommer med exporten och anläggningarna (del d)");
    expect(html).toContain("filen stannar i CAD");
  });
});

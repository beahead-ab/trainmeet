// Foto och kontroll, part c2 (#89): Kant 1 and gavel A tapped on the photo, mirrored and swapped
// before and after reading; a curve module from its chord and sagitta; and Från skiss.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PhotoPage, SketchPage, tapSide, UploadPage, type PhotoPageProps } from "./Foto";
import { routeFor, SKETCH_PATH } from "./routes";
import { CONSENT, CORNERS, DONE, PHOTOGRAPHED, STORAGE } from "./testphoto";
import type { PhotoJob } from "./api";

function photo(overrides: Partial<PhotoPageProps> = {}): string {
  return renderToStaticMarkup(<PhotoPage module={PHOTOGRAPHED} job={CORNERS} view="kontroll" consent={CONSENT} {...overrides} />);
}

/** The photo's sides as drawn: each one's class (Kant 1, gavel A or another side) and its title. */
function sides(html: string): { side: number; kind: string; title: string }[] {
  return [...html.matchAll(/<line class="(cad-[a-z0-9]+)" data-sida="(\d)"[^>]*><title>([^<]*)<\/title>/g)].map((m) => ({
    side: Number(m[2]),
    kind: m[1]!,
    title: m[3]!,
  }));
}

describe("Kant 1 and gavel A on the photo", () => {
  it("taps a gable to make it gavel A, and a long side to make it Kant 1, gavel A kept at its end when chosen", () => {
    // Kant 1 is side 0, gavel A side 3 (before Kant 1, as CAD draws it).
    expect(tapSide(1, 0, 3)).toEqual({ kant1: 0, gableA: 1 }); // the other gable: mirrored
    expect(tapSide(3, 0, 1)).toEqual({ kant1: 0, gableA: 3 });
    expect(tapSide(0, 0, 3)).toEqual({ kant1: 0, gableA: 3 }); // Kant 1 again: nothing changes
    // The other long side: gavel A before it, as CAD draws a module, unless the owner chose it.
    expect(tapSide(2, 0, 3)).toEqual({ kant1: 2, gableA: 1 });
    expect(tapSide(2, 0, 3, true)).toEqual({ kant1: 2, gableA: 3 });
    expect(tapSide(2, 0, 1, true)).toEqual({ kant1: 2, gableA: 1 });
    // Every result has gavel A beside Kant 1.
    for (let k = 0; k < 4; k++)
      for (const a of [(k + 1) % 4, (k + 3) % 4])
        for (let side = 0; side < 4; side++)
          for (const chosen of [false, true]) {
            const next = tapSide(side, k, a, chosen);
            expect([(next.kant1 + 1) % 4, (next.kant1 + 3) % 4]).toContain(next.gableA);
          }
  });

  it("marks Kant 1 and gavel A on the photo, each side says what a tap does, and mirroring is a button", () => {
    const html = photo();
    expect(sides(html)).toEqual([
      { side: 0, kind: "cad-fotokant1", title: "Kant 1" },
      { side: 1, kind: "cad-fotosida", title: "Gör den här gaveln till gavel A" },
      { side: 2, kind: "cad-fotosida", title: "Gör den här sidan till Kant 1" },
      { side: 3, kind: "cad-fotogavela", title: "Gavel A" },
    ]);
    for (const label of [">KANT 1<", ">GAVEL A<", ">GAVEL B<"]) expect(html).toContain(label);
    expect(html).toContain("tryck på den långsida som är Kant 1 och på gavel A");
    for (const button of ["Spegla: gavel A i andra änden", "Andra långsidan som Kant 1", "Vrid ett kvarts varv"]) {
      expect(html).toContain(`>${button}</button>`);
    }
    expect(html).toContain("Från gavel A längs Kant 1 ligger modulen till höger, sett ovanifrån.");
  });

  it("says when the module is mirrored, and shows Kant 1 and gavel A derived from the gables for the owner to confirm", () => {
    const mirrored = photo({ job: { ...CORNERS, corners: { ...CORNERS.corners!, gable_a: 1 } } });
    expect(sides(mirrored).find((s) => s.side === 1)?.kind).toBe("cad-fotogavela");
    expect(mirrored).toContain("Speglad: från gavel A längs Kant 1 ligger modulen till vänster, sett ovanifrån.");
    const why = "Spåren vid gavlarna stämmer med modulens gavlar åt det här hållet: Kant 1 och gavel A är härledda. Bekräfta dem.";
    const derived = photo({ job: { ...CORNERS, corners: { ...CORNERS.corners!, derived: true, why } } });
    expect(derived).toContain(`<p class="cad-ruta" role="status">${why}`);
  });

  it("after reading, mirrors or swaps at no cost, from the same measuring image", () => {
    const html = photo({ job: DONE });
    expect(html).toContain("<h2>Kant 1 och gavel A</h2>");
    expect(html).toContain('<span class="cad-tagg gron">Kostar inget</span>');
    expect(html).toContain("Ett annat val räknas om ur samma mätbild, utan ny avläsning.");
    expect(html).toContain(">Byt gavel A och B</button>");
    expect(html).toContain(">Kant 1 på andra långsidan</button>");
    const mirrored = photo({ job: { ...DONE, corners: { ...DONE.corners!, gable_a: 1 } } });
    expect(mirrored).toContain("Speglad: modulen ligger till vänster om Kant 1 från gavel A.");
  });
});

describe("a curve module from a photo", () => {
  it("asks for the chord and sagitta on track 1 and track 1 from Kant 1, and which edge Kant 1 is", () => {
    const html = renderToStaticMarkup(<UploadPage scale="H0" consent={CONSENT} storage={STORAGE} initialKind="curve" />);
    expect(html).toMatch(/<button type="button" role="radio" aria-checked="true">Kurva<\/button>/);
    for (const field of ['name="foto-korda"', 'name="foto-pilhojd"', 'name="foto-spar1"']) expect(html).toContain(field);
    expect(html).toContain("Mät spår 1 med ett snöre från spårmitten vid gavel A till spårmitten vid gavel B (kordan)");
    expect(html).toContain("Radien och vinkeln räknas fram exakt, utan avrundning.");
    expect(html).toContain('aria-label="Kant 1 på kurvan"');
    expect(html).toMatch(/aria-checked="true">Kant 1 ytterst<\/button>/);
    // The length comes from the chord and sagitta, never from the photo.
    expect(html).not.toContain('name="foto-langd"');
  });

  it("shows the question when the curve's edges are not the arcs its measures give", () => {
    const curve: PhotoJob = {
      ...DONE,
      questions: [
        {
          key: "kurva",
          kind: "curve",
          source: "code",
          title: "Kurvans kanter stämmer inte med fotot",
          text: "Kurvans kanter blir inte cirkelbågar när fotot rätas ut: de ligger upp till 3,9 mm från bågarna som kordan och pilhöjden ger.",
          choices: [
            { id: "horn", text: "Jag drar hörnen igen", hint: null, sketch: null },
            { id: "stammer", text: "Måtten stämmer", hint: null, sketch: null },
          ],
          at: [300, 200],
          topology: false,
          answer: null,
          ai: null,
          code: null,
          closeup: false,
          closeup_ai: null,
        },
      ],
    };
    const html = photo({ job: curve });
    expect(html).toContain("Kurvans kanter stämmer inte med fotot");
    expect(html).toContain("de ligger upp till 3,9 mm från bågarna som kordan och pilhöjden ger.");
  });
});

describe("Från skiss", () => {
  it("has its own address and page: the name, the form, the length and width that give the scale, the sketch and the price", () => {
    expect(routeFor(SKETCH_PATH)).toEqual({ page: "sketch" });
    const html = renderToStaticMarkup(<SketchPage scale="H0" consent={CONSENT} storage={STORAGE} />);
    expect(html).toContain("<h1 id=\"rubrik\">Ny modul ur en skiss</h1>");
    for (const field of ['name="skiss-namn"', 'name="skiss-langd"', 'name="skiss-bredd"', 'name="skiss"']) expect(html).toContain(field);
    expect(html).toContain("med modulernas ramar utritade. Du väljer sedan ramen som är den här modulen.");
    expect(html).toContain("± 20 mm, tills du mäter eller godkänner.");
    expect(html).toContain("<b>12 tokens</b> för mätbilden");
    expect(html).toContain("AI:n frågas bara om ett parti koden inte kan avgöra, till samma pris som ett foto: 12 tokens för skissen");
    expect(html).toMatch(/<button type="submit" class="tm-knapp primar" disabled="">Ladda upp skissen<\/button>/);
  });

  it("lets the owner pick the frame that is this module, and Kant 1 and gavel A on it", () => {
    const sketch: PhotoJob = {
      ...CORNERS,
      profile: "skiss",
      frames: [
        { corners: CORNERS.corners!.corners, kant1: 0 },
        {
          corners: [
            [1250, 430],
            [1900, 430],
            [1900, 800],
            [1250, 800],
          ],
          kant1: 0,
        },
      ],
      frame: null,
    };
    const html = photo({ job: sketch });
    expect(html).toContain("<h2>Skissen</h2>");
    expect(html).toContain("2 ramar hittade, välj modulens · tryck på den långsida som är Kant 1 och på gavel A");
    expect(html).toContain('role="radiogroup" aria-label="Modulens ram"');
    expect(html).toMatch(/role="radio" aria-checked="true" class="tm-knapp liten">Ram 1<\/button>/);
    expect(html).toMatch(/role="radio" aria-checked="false" class="tm-knapp liten">Ram 2<\/button>/);
  });

  it("marks what it read as a proposal from the sketch, ± 20 mm, until approved", () => {
    const read: PhotoJob = {
      ...DONE,
      profile: "skiss",
      facts: [
        { key: "vaxlar", label: "Växlar ur skissen", value: 3, text: null, plus_minus: null, source: "sketch", certainty: "probable" },
        ...(DONE.facts ?? []),
      ],
    };
    const html = photo({ job: read });
    expect(html).toContain('<span class="cad-tagg forslag">Förslag ur skissen, ± 20 mm</span>');
    expect(html).toContain('<i class="streckad orange"></i> Förslag ur skissen</span>');
    expect(html).not.toContain('<span class="cad-tagg forslag">AI-förslag</span>');
    // The result page names the sketch, not a photo.
    expect(html).toContain("<h2>Skissen</h2>");
    expect(html).toContain("Bara skissen");
    expect(html).toContain("Med spåren");
    expect(html).not.toContain("Med AI-spåren");
    if (DONE.summary?.deviation) expect(html).toContain("Avviker från skissen");
  });
});

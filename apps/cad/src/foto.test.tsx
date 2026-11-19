import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PhotoPage, Sketch, UploadPage, type PhotoPageProps } from "./Foto";
import { ModulePage } from "./ModulePage";
import { Ritningen } from "./Ritningen";
import { photoPath, routeFor, UPLOAD_PATH } from "./routes";
import { HISTORY, STATION } from "./testdata";
import { DRAWING } from "./testdrawing";
import { CONSENT, CORNERS, DONE, JOB_ID, LENGTH, PHOTOGRAPHED, STORAGE } from "./testphoto";

function photo(overrides: Partial<PhotoPageProps> = {}): string {
  return renderToStaticMarkup(<PhotoPage module={PHOTOGRAPHED} job={DONE} view="kontroll" consent={CONSENT} {...overrides} />);
}

describe("the photo's addresses", () => {
  it("has Ladda upp foto, Foto och kontroll, Längden ur fotot and Osäkert parti", () => {
    const id = STATION.id;
    expect(routeFor(UPLOAD_PATH)).toEqual({ page: "upload" });
    expect(routeFor(photoPath(id, JOB_ID))).toEqual({ page: "photo", id, job: JOB_ID, view: "kontroll" });
    expect(routeFor(photoPath(id, JOB_ID, "langd"))).toEqual({ page: "photo", id, job: JOB_ID, view: "langd" });
    const [path, search] = photoPath(id, JOB_ID, "osakert", "nod:x1").split("?");
    expect(routeFor(path!, `?${search}`)).toEqual({ page: "photo", id, job: JOB_ID, view: "osakert", question: "nod:x1" });
    expect(routeFor(`/moduler/${id}/foto/${JOB_ID}/annat`)).toEqual({ page: "missing" });
  });
});

describe("Ny modul ur ett foto", () => {
  it("asks for the name, the form, the width and the photos, with the price before start", () => {
    const html = renderToStaticMarkup(<UploadPage scale="H0" consent={CONSENT} storage={STORAGE} />);
    expect(html).toContain("Ny modul ur ett foto");
    for (const field of ['name="foto-namn"', 'name="foto-bredd"', 'name="foto-langd"', 'type="file"', "multiple", 'accept="image/jpeg,image/png"']) {
      expect(html).toContain(field);
    }
    expect(html).toContain("Foton, 1–4 av samma modul");
    expect(html).toContain("<b>12 tokens</b> för mätbilden, med följdfrågorna.");
    expect(html).toContain("Du har 86 tokens.");
    expect(html).toContain("Utan AI är det gratis.");
    expect(html).toContain("Fotots plats och kamerans uppgifter tas bort innan något sparas.");
    expect(html).toContain("Ditt utrymme för modulfoton: 3 av 100 MB.");
    expect(html).toContain("Spara originalet. Annars sparas det tills modulen godkänns, högst 30 dagar");
    expect(html).toMatch(/<button type="submit" class="tm-knapp primar" disabled="">Ladda upp<\/button>/);
  });

  it("says when AI cannot be used, and that the own AI is free", () => {
    const off = renderToStaticMarkup(<UploadPage scale="H0" consent={{ ...CONSENT, available: false, message: "AI-avläsningen kräver TrainMeet ID." }} />);
    expect(off).toContain("AI-avläsningen kräver TrainMeet ID. Utan AI är det gratis");
    const own = renderToStaticMarkup(<UploadPage scale="H0" consent={{ ...CONSENT, own_ai: "Claude via egen nyckel", price: 0 }} />);
    expect(own).toContain("<b>Gratis</b> med din egen AI (Claude via egen nyckel).");
  });
});

describe("Foto och kontroll", () => {
  it("shows the photo with the corners, Kant 1 and the gables, and the price and what is sent before it is read", () => {
    const html = photo({ job: CORNERS });
    expect(html).toContain("Foto och kontroll");
    expect(html).toContain('aria-label="Fotot med modulens hörn"');
    expect(html.match(/class="cad-fotohorn"/g)?.length).toBe(4);
    expect(html.match(/class="cad-fotokant1"/g)?.length).toBe(1);
    for (const label of [">KANT 1<", ">GAVEL A<", ">GAVEL B<"]) expect(html).toContain(label);
    expect(html).toContain("4 hörn hittade");
    expect(html).toContain("<b>12 tokens</b> för mätbilden");
    expect(html).toContain("Mätbilden skickas till TrainMeets AI: Claude från Anthropic via Amazon Bedrock i EU.");
    expect(html).toContain("Jag godkänner att mätbilden skickas till TrainMeets AI");
    // The first time, Läs av med AI waits for the yes; without AI it is free at once.
    expect(html).toMatch(/<button type="button" class="tm-knapp primar" disabled="">Läs av med AI · 12 tokens<\/button>/);
    expect(html).toMatch(/<button type="button" class="tm-knapp">Läs av utan AI · gratis<\/button>/);
    const again = photo({ job: CORNERS, consent: { ...CONSENT, given: true } });
    expect(again).not.toContain("Jag godkänner");
    expect(again).toMatch(/<button type="button" class="tm-knapp primar">Läs av med AI · 12 tokens<\/button>/);
  });

  it("follows the job while it runs", () => {
    const html = photo({ job: { ...CORNERS, state: "running", progress: 30, step: "Rätar ut fotot och läser spåren" } });
    expect(html).toContain("Läser av fotot");
    expect(html).toContain("Rätar ut fotot och läser spåren · 30 %");
    expect(html).toContain('<progress max="100" value="30"');
  });

  it("shows the AI's tracks over the photo, the measures against it, the quality and the track plan", () => {
    const html = photo();
    expect(html).toContain("2 saker att kolla");
    expect(html).toContain("Byt foto");
    expect(html).toContain("4 hörn hittade");
    expect(html).toContain("Bilden uträtad · 2,4 px per mm");
    expect(html).toContain("Skala från spårvidden · H0 16,5 mm på 23 ställen");
    expect(html).toContain("4 av 5 mått stämmer");
    expect(html).toContain("mätosäkerhet ±2 mm");
    expect(html).toContain("Med AI-spåren");
    expect(html.match(/class="cad-aispar"/g)?.length).toBeGreaterThanOrEqual(2);
    expect(html).toContain("Dina mått mot fotot");
    expect(html).toContain("Proportion längd/bredd");
    expect(html).toContain("1500 · ≈ 1494,2");
    expect(html).toContain("<b>Gavel B · spår 3</b>");
    expect(html).toContain("345 · ≈ 380,2");
    expect(html).toContain("35,2 mm ifrån, mer än fotots ± 0,9 mm.");
    expect(html).toContain(">Använd 380,2</button>");
    expect(html).toContain(">Behåll 345</button>");
    expect(html).toContain("Uträtad ritning");
    expect(html).toContain("1494 × 700 mm enligt fotot · du angav 1500 × 700");
    expect(html).toContain('<span class="cad-tagg forslag">AI-förslag</span>');
    expect(html).toContain("2 vid A · 3 vid B");
    expect(html).toContain("1 med stoppbock");
    expect(html).toContain("≈ 4,8 m");
    expect(html).toContain("median 0,08 mm, högst 0,94 mm");
    expect(html).toContain("1 parti att kontrollera innan spårplanen kan godkännas.");
    expect(html).toContain(`href="${photoPath(PHOTOGRAPHED.id, JOB_ID, "osakert", "nod:x1").replace("&", "&amp;")}"`);
    expect(html).toMatch(/<button type="button" class="tm-knapp primar" disabled="">Godkänn spårplanen<\/button>/);
    expect(html).toContain("Rätta i ritningen");
    const answered = photo({ job: { ...DONE, questions: DONE.questions?.map((q) => ({ ...q, answer: "tva-vaxlar" })) } });
    expect(answered).toMatch(/<button type="button" class="tm-knapp primar">Godkänn spårplanen<\/button>/);
  });
});

describe("Längden ur fotot", () => {
  it("gives the length with its ±, the sleeper check and a field to measure", () => {
    const html = photo({ job: LENGTH, view: "langd" });
    expect(html).toContain("Längden ur fotot");
    expect(html).toContain(">Förslag</span>");
    expect(html).toContain("Jag skriver in längden");
    expect(html).toContain("✓ Använd 1213 mm");
    expect(html).toContain("längd ≈ 1213 mm");
    expect(html).toContain("ej ifylld");
    expect(html).toContain("<b>1213</b> mm <span class=\"cad-dampad\">± 6 mm</span>");
    expect(html).toContain("Sliperdelning, raka spår");
    expect(html).toContain("Sliperdelning, sneda spåret (43°)");
    expect(html).toContain("7,09 mm");
    expect(html).toContain("✓ lika");
    expect(html).toContain("för brusig");
    expect(html).toContain("Sliperdelningen är densamma på raka och sneda spår, så skalan stämmer på längden också.");
    expect(html).toContain("Får du under 1207 eller över 1219 mm stämmer något inte.");
    expect(html).toContain("Fotot uträtat till 2,4 px per mm");
  });
});

describe("Osäkert parti", () => {
  it("shows the part enlarged, what the AI sees, the choices with sketches, the close-up and Spara", () => {
    const html = photo({ view: "osakert", question: "nod:x1" });
    expect(html).toContain("Ett parti att kontrollera");
    expect(html).toContain("⚠ 1 av 1");
    expect(html).toContain("Övriga 2 växlar och 5 gavelspår är klara");
    expect(html).toContain('aria-label="Partiet förstorat ur fotot"');
    expect(html).toContain('class="cad-osakert-ring"');
    expect(html).toContain("Vad AI:n ser");
    expect(html).toContain("Bedömningarna gick isär, så du får avgöra.");
    expect(html).toContain("<b>Två växlar</b>");
    expect(html).toContain("<b>En korsning</b>");
    expect(html).toContain("Spåren förbinds. Ett tåg kan byta spår här.");
    expect(html).toContain("Spåren korsar utan förbindelse. Inga växlar.");
    expect(html.match(/class="cad-skiss"/g)?.length).toBe(2);
    expect(html).toContain('class="cad-kort cad-valkort valt"');
    expect(html).toContain("Ta en närbild av partiet");
    expect(html).toContain("◎ 12 tokens");
    expect(html).toContain("Resten av spårplanen påverkas inte av valet.");
    expect(html).toContain("Fråga mig senare");
    expect(html).toContain("✓ Spara: två växlar");
    expect(html).toContain("250 mm från gavel B");
  });

  it("draws the sketches: switches as rings, a crossing as a diamond", () => {
    expect(renderToStaticMarkup(<Sketch kind="two_switches" />).match(/cad-skiss-vaxel/g)?.length).toBe(2);
    expect(renderToStaticMarkup(<Sketch kind="crossing" />)).toContain("cad-skiss-korsning");
  });
});

describe("Fotot under in Ritningen", () => {
  it("puts the measuring image under the drawing, with the AI-förslag badge and how far it lies from the photo", () => {
    const view = {
      ...DRAWING,
      drawing: { ...DRAWING.drawing, source: "photo" as const, photo: JOB_ID },
      photo: { job: JOB_ID, url: "/api/cad/1/photos/file/matbild.jpg", grid: { x0: -10, y0: -10, ppm: 1, width: 1521, height: 721 } },
      stats: { ...DRAWING.stats, deviation: { median: 0.08, max: 0.94, count: 2792 } },
    };
    const html = renderToStaticMarkup(<Ritningen module={PHOTOGRAPHED} view={view} changes={0} undone={0} />);
    expect(html).toContain('aria-pressed="true">Fotot under</button>');
    expect(html).toContain('class="cad-fotolager" href="/api/cad/1/photos/file/matbild.jpg" x="-10.5" y="-10.5" width="1521" height="721"');
    expect(html).toContain('class="cad-skiva genomskinlig"');
    expect(html).toContain(">AI-förslag</span>");
    expect(html).toContain("Avviker från fotot: median 0,08 mm, högst 0,94 mm");
    expect(html).toMatch(/name="lager-photo" checked=""/);
  });
});

describe("the Foto tab", () => {
  it("shows the measuring image, the original's days, Spara original, the training opt-in and Räkna om", () => {
    const html = renderToStaticMarkup(
      <ModulePage module={PHOTOGRAPHED} history={HISTORY} tab="foto" clubs={[]} consent={CONSENT} storage={STORAGE} now={new Date("2026-11-19T13:00:00+01:00")} />,
    );
    expect(html).toContain("Mätbilden");
    expect(html).toContain('href="/api/cad/1/photos/file/matbild.jpg"');
    expect(html).toContain("Originalet sparas till modulen godkänns, högst 30 dagar till (19 dec 2026).");
    expect(html).toContain("Spara original");
    expect(html).toContain("5 MB original väntar på godkännande och räknas inte.");
    expect(html).toContain("Ja, TrainMeet får använda mätbilden och spårplanen för att träna sin spårmodell.");
    expect(html).toContain("Bara mätbilden och geometrin, aldrig originalet. Inget tränas än.");
    expect(html).toContain("Läst med version 0.9.0.");
    expect(html).toMatch(/<button type="button" class="tm-knapp">Räkna om med nya versionen<\/button>/);
    expect(html).toContain("Spåren behåller sina nummer.");
    expect(html).toContain(`href="${photoPath(PHOTOGRAPHED.id, JOB_ID)}"`);
    expect(html).toContain("Ladda upp ett foto av modulen");
    const said = renderToStaticMarkup(
      <ModulePage module={{ ...PHOTOGRAPHED, training_at: "2026-11-19T13:00:00+01:00" }} history={HISTORY} tab="foto" clubs={[]} />,
    );
    expect(said).toContain("Du sa ja 19 nov 2026.");
    expect(said).toMatch(/name="traning" checked=""/);
    const same = renderToStaticMarkup(
      <ModulePage module={{ ...PHOTOGRAPHED, photo: { ...PHOTOGRAPHED.photo!, newer_chain: false } }} history={HISTORY} tab="foto" clubs={[]} />,
    );
    expect(same).toMatch(/disabled="">Räkna om med nya versionen<\/button>/);
  });

  it("says the length came from the photo on the overview", () => {
    const html = renderToStaticMarkup(<ModulePage module={PHOTOGRAPHED} history={HISTORY} tab="oversikt" clubs={[]} />);
    expect(html).toContain("ur fotot");
  });
});

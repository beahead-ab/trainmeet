import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { EmptyLibrary, LibraryPage } from "./Library";
import { EMPTY, LIST } from "./testdata";

const NOW = new Date("2026-11-19T20:00:00+01:00");

describe("Modulerna", () => {
  it("lists the modules with their drawing, form, gables, scale and status", () => {
    const html = renderToStaticMarkup(<LibraryPage list={LIST} now={NOW} />);
    expect(html).toContain("2 moduler · 2,1 m spår");
    for (const text of ["M-001", "Exempelstation", "Rak · 1500 × 700", "FREMO dubbelspår", "Egen gavel · 3 spår"]) expect(html).toContain(text);
    expect(html).toContain("Kurva · R 2000 · 30° · bredd 500");
    expect(html).toContain('<span class="cad-status utkast">Utkast</span>');
    expect(html).toContain('<span class="cad-status godkand">Godkänd</span>');
    expect(html).toContain('href="/moduler/0e6c2f0a-1b2c-4d3e-8f40-5a6b7c8d9e0f"');
    expect(html.match(/class="cad-ritning liten"/g)?.length).toBe(2);
    expect(html).toContain("+ Ny modul");
  });

  it("counts the gables in the library and filters with chips", () => {
    const html = renderToStaticMarkup(<LibraryPage list={LIST} now={NOW} />);
    expect(html).toContain("Gavlar i biblioteket");
    expect(html).toContain("<b>2</b> Dubbelspår");
    expect(html).toContain("4 gavlar på 2 moduler");
    for (const chip of ["Alla 2", "Raka 1", "Kurvor 1", "Utkast 1", "Godkända 1"]) expect(html).toContain(chip);
    expect(html).toContain("1 godkända · 1 utkast");
    expect(html).toContain('placeholder="Sök modul, ID eller gavel"');
  });

  it("shows the dashed unknown tracks of a module whose gables differ", () => {
    const html = renderToStaticMarkup(<LibraryPage list={{ ...LIST, modules: [LIST.modules[0]!] }} now={NOW} />);
    expect(html).toContain('class="cad-okant"');
  });

  it("shows how it works the first time, with the empty library", () => {
    const html = renderToStaticMarkup(<LibraryPage list={EMPTY} />);
    expect(html).toContain("Bygg ditt modulbibliotek");
    expect(html).toBe(renderToStaticMarkup(<EmptyLibrary />));
  });
});

describe("Tomt bibliotek", () => {
  it("has the four steps, the first module and the gable profiles", () => {
    const html = renderToStaticMarkup(<EmptyLibrary />);
    for (const step of ["Mät modulen", "Beskriv gavlarna", "Fota uppifrån", "AI ritar och kontrollerar"]) expect(html).toContain(step);
    expect(html).toContain('href="/moduler/ny"');
    expect(html).toContain("+ Lägg till första modulen");
    expect(html).toContain('href="/gavelprofiler"');
    expect(html).toContain("FÖRSLAG TILLS DU GODKÄNT");
  });
});

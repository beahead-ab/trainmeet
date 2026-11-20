import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ModuleForm } from "./ModuleForm";
import { CURVE, PROFILES, STATION } from "./testdata";

const NBSP = "\u00a0";

describe("Rak modul", () => {
  it("asks for name, scale, form, length and width, and gables measured from Kant 1", () => {
    const html = renderToStaticMarkup(<ModuleForm kind="straight" scale="H0" profiles={PROFILES} />);
    expect(html).toContain("Ny rak modul");
    for (const name of ["namn", "skala", "langd", "bredd"]) expect(html).toContain(`name="${name}"`);
    expect(html).toContain('role="radio" aria-checked="true">Rak</button>');
    expect(html).toContain("Gavel A");
    expect(html).toContain('<optgroup label="Normer"><option value="h0-fremo-dubbelspar">FREMO dubbelspår</option>');
    expect(html).toContain('<optgroup label="Allmänna">');
    expect(html).toContain('<optgroup label="Egna"><option value="egen-0a1b2c3d4e5f">Egen · 6 spår</option>');
    expect(html).toContain("Egen gavel (mät spår för spår)");
    expect(html).toContain("Kant 1 → spår 1");
    expect(html).toContain("Spår 1 ligger 250 mm från Kant 1");
    expect(html).toContain("Gavel B är likadan som gavel A");
    expect(html).toContain("KANT 1");
    expect(html).toContain("Inga ändringar");
  });

  it("shows a module whose gables differ, with its measures and two gables, to change it", () => {
    const html = renderToStaticMarkup(<ModuleForm kind="straight" scale="H0" profiles={PROFILES} module={STATION} />);
    expect(html).toContain("<h1 id=\"rubrik\">Exempelstation</h1>");
    expect(html).toContain('value="1500"');
    expect(html).toContain('value="700"');
    expect(html).toContain('<option value="h0-fremo-dubbelspar" selected="">FREMO dubbelspår</option>');
    expect(html).toContain("Spår 1 → spår 2");
    expect(html).toContain("Spår 3 ligger 345 mm från Kant 1");
    expect(html).toContain("2 spår in vid A, 3 spår ut vid B");
    expect(html).toContain('aria-label="Gavel A sedd utifrån"');
    expect(html).toContain('aria-label="Gavel B sedd utifrån"');
    // Nothing changed yet: nothing to save as a new version.
    expect(html).toMatch(/<button type="submit" class="tm-knapp primar" disabled="">Spara<\/button>/);
  });

  it("locks the positions a norm fixes, as MMM's 140 mm", () => {
    const mmm = { ...STATION, gables: [
      { end: "A" as const, label: "MMM enkelspår", norm: "mmm" as const, profile: "h0-mmm-enkelspar", tracks: [140] },
      { end: "B" as const, label: "MMM enkelspår", norm: "mmm" as const, profile: "h0-mmm-enkelspar", tracks: [140] },
    ] };
    const html = renderToStaticMarkup(<ModuleForm kind="straight" scale="H0" profiles={PROFILES} module={mmm} />);
    expect(html).toContain('readOnly="" aria-readonly="true" name="gavel-A-0" value="140"');
  });
});

describe("Kurvmodul", () => {
  it("asks for the string and the sagitta, the body and the gables", () => {
    const html = renderToStaticMarkup(<ModuleForm kind="curve" scale="H0" profiles={PROFILES} />);
    expect(html).toContain("Ny kurvmodul");
    expect(html).toContain('aria-checked="true">Snöre och pilhöjd</button>');
    expect(html).toContain("Radie och vinkel");
    expect(html).toContain("Snöret, A → B");
    expect(html).toContain("Pilhöjd");
    expect(html).toContain("Spänn ett snöre mellan spår 1:s mitt vid A och B");
    for (const text of ["Modulkroppen", "Ytterkanten", "Innerkanten", "Böjda", "Raka"]) expect(html).toContain(text);
  });

  it("gives radius and angle from the string and sagitta exactly as computed, with the table (CAD16)", () => {
    const html = renderToStaticMarkup(<ModuleForm kind="curve" scale="H0" profiles={PROFILES} module={CURVE} />);
    expect(html).toContain("Uträknat: R 2 003,2 mm · 29,94°");
    expect(html).toContain("utan avrundning");
    expect(html).not.toContain("Ångra avrundning");
    expect(html).not.toContain("Avrunda till");
    // 360 / 29,94° is no whole number of modules.
    expect(html).not.toContain("sådana moduler blir en hel cirkel");
    expect(html).toContain("högerkurva sedd från gavel A");
    for (const row of [
      `<th scope="row">Spår 1</th><td>2${NBSP}003 mm</td><td>1${NBSP}047 mm</td><td>1${NBSP}035 mm</td>`,
      `<th scope="row">Spår 2</th><td>1${NBSP}953 mm</td><td>1${NBSP}021 mm</td><td>1${NBSP}009 mm</td>`,
      `<th scope="row">Kant 1 · ytterkanten</th><td>2${NBSP}203 mm</td><td>1${NBSP}151 mm</td><td>1${NBSP}138 mm</td>`,
      `<th scope="row">Innerkanten</th><td>1${NBSP}703 mm</td><td>890 mm</td><td>880 mm</td>`,
    ]) {
      expect(html).toContain(row);
    }
    expect(html).toMatch(/<path class="cad-spar" d="M[^"]*A2003.2 2003.2 0 0 1/);
  });

  it("says when a curve makes a whole circle, from the radius and angle", () => {
    const shape = { ...CURVE.shape, radius: 2000, angle: 30, measured: null } as typeof CURVE.shape;
    const html = renderToStaticMarkup(<ModuleForm kind="curve" scale="H0" profiles={PROFILES} module={{ ...CURVE, shape }} />);
    expect(html).toContain("12 sådana moduler blir en hel cirkel");
  });
});

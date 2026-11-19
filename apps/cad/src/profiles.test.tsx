import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ProfilesPage } from "./Profiles";
import { CLUB, PROFILES } from "./testdata";

describe("Gavelprofiler", () => {
  it("shows the norms of the scale, general and own gables, and how many use them", () => {
    const html = renderToStaticMarkup(<ProfilesPage list={PROFILES} clubs={[CLUB]} />);
    expect(html).toContain("Normerna i skala H0: FREMO, MMM, USMS, Klubbens egen.");
    expect(html.match(/class="cad-bricka norm">Norm</g)?.length).toBe(2);
    expect(html.match(/class="cad-bricka general">Allmän</g)?.length).toBe(2);
    expect(html).toContain('class="cad-bricka own">Egen');
    expect(html).toContain("<span>1 gavel</span>");
    expect(html).toContain("<span>2 gavlar</span>");
    expect(html).toContain("53 134 184 236 580 631");
    expect(html).toContain(">140</p>");
    expect(html).toContain("läget per modul");
    expect(html).toContain('class="cad-prick oppen"');
    expect(html).toContain("+ Ny gavelprofil");
    expect(html).toContain("Normernas exakta mått läses in från FREMO, MMM och USMS innan lansering.");
  });

  it("says when the spec names no norm in the scale", () => {
    const html = renderToStaticMarkup(<ProfilesPage list={{ ...PROFILES, scale: "N", norms: [], profiles: [] }} clubs={[]} />);
    expect(html).toContain("Normerna i skala N: specen namnger ingen norm än.");
  });
});

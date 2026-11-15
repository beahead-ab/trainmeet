import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Check, Draft, MeetSummary, Version } from "./api";
import { isOwn, routeOf } from "./App";
import { dates, levelText } from "./text";
import { TraffarPage } from "./Traffar";
import { VersionerPage } from "./Versioner";

const go = () => undefined;
const summary = {
  meet: { id: "varnamo", name: "Värnamo Moduldagar", country: "se", first_date: "2026-11-13", last_date: "2026-11-15", clearance_mode: "requested" },
  level: 4,
  places: 12,
  trains: 1234,
  sources: 1,
  questions: 2,
  versions: [{ meet: "varnamo", number: 1, published: "2026-11-14T08:00:00Z", checksum: "a".repeat(64), conflicts: 0, observations: 1 }],
} as unknown as MeetSummary;

describe("Träffar (S6)", () => {
  it("lists the meets with their level, trains and latest version, and Provbanan last", () => {
    const html = renderToStaticMarkup(<TraffarPage admin={false} meets={[summary]} navigate={go} />);
    expect(html).toContain('href="/planering/varnamo">Värnamo Moduldagar</a>');
    expect(html).toContain("Nivå 4 · Facit");
    expect(html).toMatch(/<td class="tal">1\s234<\/td>/);
    expect(html).toContain("Version 1");
    expect(html).toContain('href="/provbanan">Provbanan</a>');
    expect(html).toContain('id="meet-count" class="antal">2<');
    expect(html).toContain("Logga in för att skapa en träff.");
    expect(html).not.toContain('id="new-meet"');
  });

  it("gives the administrator Ny träff", () => {
    const html = renderToStaticMarkup(<TraffarPage admin meets={[]} navigate={go} />);
    expect(html).toContain('id="new-meet"');
    expect(html).toContain(">Skapa träffen<");
    expect(html).toContain('<option value="dk">Danmark</option>');
  });

  it("says the dates and the level as before", () => {
    expect(dates(summary.meet)).toMatch(/13 nov\. 2026 – 15 nov\. 2026|13 nov 2026 – 15 nov 2026/);
    expect(dates({ ...summary.meet, first_date: null, last_date: null })).toBe("Inget datum");
    expect(levelText(null)).toBe("Inget underlag");
  });
});

describe("Versioner (S6)", () => {
  const draft = { meet: { id: "varnamo", name: "Värnamo Moduldagar" }, package: {} } as unknown as Draft;
  const check = { findings: [{ id: "f1", severity: "conflict", code: "x", message: "Två tåg på samma spår." }] } as Check;
  const versions = summary.versions as Version[];

  it("shows the check, the versions newest first and Kör i Drift", () => {
    const html = renderToStaticMarkup(<VersionerPage admin={false} meet="varnamo" draft={draft} check={check} versions={versions} />);
    expect(html).toContain('<span class="pill conflict">Konflikt</span><span>Två tåg på samma spår.</span>');
    expect(html).toContain("<b>Version 1</b>");
    expect(html).toContain('href="/drift?traff=varnamo&amp;version=1#ny-traff">Kör i Drift →</a>');
    expect(html).not.toContain('id="publish"');
  });

  it("lets the administrator publish the next version, once there is a plan", () => {
    const html = renderToStaticMarkup(<VersionerPage admin meet="varnamo" draft={draft} check={check} versions={versions} />);
    expect(html).toContain(">Publicera version 2<");
    const empty = renderToStaticMarkup(<VersionerPage admin meet="ny" draft={{ ...draft, package: null }} check={{ findings: [] }} versions={[]} />);
    expect(empty).toContain("Lägg till underlag under Data först.");
    expect(empty).toContain('disabled="">Publicera version 1<');
    expect(empty).toContain("Ingen version är publicerad än.");
  });
});

describe("the addresses", () => {
  it("draws Träffar, Data and Versioner, and leaves Bana and Graf to the hub for now", () => {
    expect(routeOf("/planering")).toEqual({ page: "traffar" });
    expect(routeOf("/planering/varnamo")).toEqual({ page: "data", meet: "varnamo" });
    expect(routeOf("/planering/varnamo/data")).toEqual({ page: "data", meet: "varnamo" });
    expect(routeOf("/planering/varnamo/versioner")).toEqual({ page: "versioner", meet: "varnamo" });
    expect(isOwn("/planering/")).toBe(true);
    expect(isOwn("/planering/varnamo")).toBe(true);
    expect(isOwn("/planering/varnamo/versioner")).toBe(true);
    expect(isOwn("/planering/varnamo/bana")).toBe(false);
    expect(isOwn("/drift")).toBe(false);
  });
});

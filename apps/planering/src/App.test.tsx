import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Check, Draft, MeetSummary, Proposal, Version } from "./api";
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

  it("says what stops publishing and asks the double-track question (PLAN-35)", () => {
    const asked = { ...check, blocking: ["Träffen saknar första eller sista dag. Ange dem under Träffar."], double_track: [{ section: "d8", conflicts: 2, fingerprint: "f".repeat(64), message: "Är det dubbelspår på Nättelund–Mohult? I så fall försvinner 2 konflikter." }] } as Check;
    const html = renderToStaticMarkup(<VersionerPage admin meet="varnamo" draft={draft} check={asked} versions={versions} />);
    expect(html).toContain('<span class="pill conflict">Stoppar</span><span>Träffen saknar första eller sista dag.');
    expect(html).toContain('disabled="">Publicera version 2<');
    expect(html).toContain("Rätta det som stoppar först.");
    expect(html).toContain("Är det dubbelspår på Nättelund–Mohult?");
    expect(html).toContain(">Ja, dubbelspår<");
    const looking = renderToStaticMarkup(<VersionerPage admin={false} meet="varnamo" draft={draft} check={asked} versions={versions} />);
    expect(looking).not.toContain(">Ja, dubbelspår<");
  });

  it("marks a withdrawn version and offers Dra tillbaka to the administrator (PLAN-18)", () => {
    const two = [...versions, { ...versions[0]!, number: 2, withdrawn: "2026-11-16T10:00:00Z" }] as Version[];
    const html = renderToStaticMarkup(<VersionerPage admin meet="varnamo" draft={draft} check={check} versions={two} />);
    expect(html).toContain('<tr class="tillbakadragen"><td><b>Version 2</b>');
    expect(html).toContain("Tillbakadragen ");
    expect(html).not.toContain("version=2#ny-traff");
    expect(html).toContain('aria-controls="withdraw-1">Dra tillbaka</button>');
    const looking = renderToStaticMarkup(<VersionerPage admin={false} meet="varnamo" draft={draft} check={check} versions={two} />);
    expect(looking).not.toContain("Dra tillbaka</button>");
  });

  it("lets the administrator publish the next version, once there is a plan", () => {
    const html = renderToStaticMarkup(<VersionerPage admin meet="varnamo" draft={draft} check={check} versions={versions} />);
    expect(html).toContain(">Publicera version 2<");
    const empty = renderToStaticMarkup(<VersionerPage admin meet="ny" draft={{ ...draft, package: null }} check={{ findings: [] }} versions={[]} />);
    expect(empty).toContain("Lägg till underlag under Data först.");
    expect(empty).toContain('disabled="">Publicera version 1<');
    expect(empty).toContain("Ingen version är publicerad än.");
  });

  it("lists the proposals from Drift with Ta med and Avslå, and what was answered before (PLAN-03)", () => {
    const planned = { ...draft, package: { places: [{ id: "nby", name: "Norrby", code: "Nby", kind: "manned" }], sections: [], trains: [{ id: "t101", number: "101", calls: [] }] } } as unknown as Draft;
    const proposal = (id: string, status: Proposal["status"], change: object, number: string | null = null) =>
      ({ id, meet: "varnamo", version: 1, change, train_number: number, made: "2026-11-16T09:00:00Z", status, answered: null }) as unknown as Proposal;
    const proposals = [
      proposal("c1", "waiting", { kind: "cancel", train: "t43" }, "43"),
      proposal("c2", "waiting", { kind: "extra", number: "9101", departure: "10:00", copy_of: "t101" }),
      proposal("c3", "taken", { kind: "cancel", train: "t101" }),
      proposal("c4", "rejected", { kind: "cancel", train: "t101" }),
    ];
    const html = renderToStaticMarkup(<VersionerPage admin meet="varnamo" draft={planned} check={check} versions={versions} proposals={proposals} />);
    expect(html).toContain('id="proposal-count" class="liten">· 2 väntar</span>');
    expect(html).toContain("<b>Inställt tåg 43</b>");
    expect(html).toContain("<b>Extratåg 9101, kopia av 101 kl. 10:00</b>");
    expect(html).toContain("körde version 1");
    expect(html).toContain(">Ta med i version 2<");
    expect(html).toContain(">Avslå<");
    expect(html).toContain("Tidigare: 1 tagna med · 1 avslagna");
    const looking = renderToStaticMarkup(<VersionerPage admin={false} meet="varnamo" draft={planned} check={check} versions={versions} proposals={proposals} />);
    expect(looking).not.toContain(">Avslå<");
    expect(looking).toContain("Logga in för att ta med eller avslå.");
    expect(renderToStaticMarkup(<VersionerPage admin meet="varnamo" draft={planned} check={check} versions={versions} proposals={[]} />)).toContain("Inga förslag väntar.");
  });
});

describe("the addresses", () => {
  it("draws all of Planering: Träffar, Data, Bana, Graf and Versioner", () => {
    expect(routeOf("/planering")).toEqual({ page: "traffar" });
    expect(routeOf("/planering/varnamo")).toEqual({ page: "data", meet: "varnamo" });
    expect(routeOf("/planering/varnamo/data")).toEqual({ page: "data", meet: "varnamo" });
    expect(routeOf("/planering/varnamo/bana")).toEqual({ page: "bana", meet: "varnamo" });
    expect(routeOf("/planering/varnamo/graf")).toEqual({ page: "graf", meet: "varnamo" });
    expect(routeOf("/planering/varnamo/versioner")).toEqual({ page: "versioner", meet: "varnamo" });
    expect(isOwn("/planering/")).toBe(true);
    expect(isOwn("/planering/varnamo/bana")).toBe(true);
    expect(isOwn("/drift")).toBe(false);
    expect(isOwn("/provbanan")).toBe(false);
  });
});

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

  it("shows the reasonableness check with Låt stå, Ta tillbaka and Visa i rutnätet (PLAN-36)", () => {
    const deviation = (id: string, let_stand: boolean) => ({ id, kind: "long_dwell", title: "Ovanligt långt uppehåll", message: "Tåg 5661 står 1 h i Steinsnes (ankomst 07:57, avgång 08:57). Andra tåg står 2 min (median av 33 tåg).", train: "t80", train_number: "5661", calls: ["c1"], days: ["mon", "tue", "wed", "thu", "fri"], minutes: 60, usual: 2, samples: 33, fingerprint: "f".repeat(64), let_stand });
    const checked = { ...check, deviations: [deviation("a", false), deviation("b", true)] } as Check;
    const html = renderToStaticMarkup(<VersionerPage admin meet="varnamo" draft={draft} check={checked} versions={versions} />);
    expect(html).toContain("Rimlighet <span class=\"liten\">· 1 att granska</span>");
    expect(html).toContain('<span class="pill observation">Ovanligt långt uppehåll</span>');
    expect(html).toContain("Tåg 5661 står 1 h i Steinsnes");
    expect(html).toContain(" · Mån–Fre");
    expect(html).toContain('href="/planering/varnamo/data?block=calls&amp;sok=5661">Visa i rutnätet</a>');
    expect(html).toContain(">Låt stå<");
    expect(html).toContain("<summary>1 lämnade som de är</summary>");
    expect(html).toContain(">Ta tillbaka<");
    const looking = renderToStaticMarkup(<VersionerPage admin={false} meet="varnamo" draft={draft} check={checked} versions={versions} />);
    expect(looking).not.toContain(">Låt stå<");
    expect(looking).toContain("Visa i rutnätet");
  });

  it("offers the exports of the draft, and the sources only to the administrator (PLAN-07)", () => {
    const html = renderToStaticMarkup(<VersionerPage admin meet="varnamo" draft={draft} check={check} versions={versions} />);
    expect(html).toContain('<option value="" selected="">Utkastet</option><option value="1">Version 1</option>');
    expect(html).toContain('href="/api/planering/1/meets/varnamo/export/stationstidtabeller" download="">Stationstidtabeller</a>');
    expect(html).toContain('href="/api/planering/1/meets/varnamo/export/tidtabell" download="">Hela tidtabellen</a>');
    expect(html).toContain(">Underlaget som ZIP<");
    const looking = renderToStaticMarkup(<VersionerPage admin={false} meet="varnamo" draft={draft} check={check} versions={versions} />);
    expect(looking).toContain(">Köruppdragen<");
    expect(looking).not.toContain("Underlaget som ZIP");
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

  it("lets the organizer publish only with the right to, and only the administrator withdraw (PLAN-24)", () => {
    const two = [...versions, { ...versions[0]!, number: 2 }] as Version[];
    const planning = renderToStaticMarkup(<VersionerPage admin mayPublish={false} mayWithdraw={false} meet="varnamo" draft={draft} check={check} versions={two} />);
    expect(planning).not.toContain("Publicera version 3");
    expect(planning).toContain("Klubbens administratör ger rätten att publicera i TrainMeet ID.");
    expect(planning).not.toContain("Dra tillbaka</button>");
    const publishing = renderToStaticMarkup(<VersionerPage admin mayPublish mayWithdraw={false} meet="varnamo" draft={draft} check={check} versions={two} />);
    expect(publishing).toContain(">Publicera version 3<");
    expect(publishing).not.toContain("ger rätten att publicera");
    expect(publishing).not.toContain("Dra tillbaka</button>");
    // Läsare (H16): the plan, with no buttons.
    const reading = renderToStaticMarkup(<VersionerPage admin={false} mayPublish={false} mayWithdraw={false} meet="varnamo" draft={draft} check={check} versions={two} />);
    expect(reading).toContain("Kör i Drift");
    expect(reading).not.toContain("<button");
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

describe("Ny träff ur TrainMeet ID (ID10, #78)", () => {
  const choice = { id: "cccccccc-6666-4777-8888-999900001111", name: "Höstträffen", club_name: "Västby MJK", starts_on: "2026-11-20", ends_on: "2026-11-22", hub_meet: null };

  it("lets someone logged in with ID make the hub's meet from a meet they plan in ID", () => {
    const html = renderToStaticMarkup(<TraffarPage admin={false} person idMeets={[choice, { ...choice, id: "x", name: "Vårträffen", hub_meet: "vartraffen" }]} meets={[]} navigate={go} />);
    expect(html).toContain("Ny träff ur TrainMeet ID");
    expect(html).toContain("<b>Höstträffen</b>");
    expect(html).toContain("Västby MJK · 2026-11-20 – 2026-11-22");
    expect(html).toContain(">Skapa träffen i hubben<");
    expect(html).toContain('href="/planering/vartraffen">Öppna<');
    expect(html).not.toContain('id="new-meet"');
  });

  it("says where the role is given when they plan nothing", () => {
    const html = renderToStaticMarkup(<TraffarPage admin={false} person idMeets={[]} meets={[]} navigate={go} />);
    expect(html).toContain("Du är inte arrangör för någon träff i TrainMeet ID.");
  });
});

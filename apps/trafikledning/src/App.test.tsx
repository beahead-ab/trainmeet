import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Client, HubInfo, Now, Version } from "./api";
import { isOwn, pageOf } from "./App";
import { meetChoices } from "./drift";
import { heaps, newSeed, SettingsPage } from "./Installningar";
import { KlienterPage } from "./Klienter";
import { LoggPage } from "./Logg";
import { NuPage } from "./Nu";
import { Sidhuvud, type HeaderProps } from "./Sidhuvud";
import { builtText, StartPage } from "./StartPage";

const now = {
  meet_id: "provbanan",
  name: "Provbanan",
  version: 1,
  traffic_day: "mon",
  game_day: 1,
  clock: { time: "06:00", seconds: 21600, running: false, speed: 4, game_day: 1 },
  places: [{ place: "nby", code: "Nby", name: "Norrby" }],
  legs: [],
  clearances: [],
} as unknown as Now;
const go = () => undefined;

const header = (change: Partial<HeaderProps> = {}) =>
  renderToStaticMarkup(
    <Sidhuvud page="nu" hubName="Hubben <i>Väst</i>" admin={false} now={now} elapsedMs={0} waiting={0} choices={meetChoices([])} asked={null} menu={null} joining={null} joinedAt={0} navigate={go} onMenu={go} onStart={go} onLogOut={go} {...change} />,
  );

describe("the header (S2, TRAFIK-12)", () => {
  it("shows everyone the meet and its clock, and only the administrator the buttons (S1)", () => {
    const looking = header();
    expect(looking).toContain('id="clock"');
    expect(looking).toContain("<b>06:00</b>");
    expect(looking).not.toContain('id="connect"');
    expect(looking).not.toContain('id="waiting"');
    expect(looking).not.toContain("Byt träff");
    expect(looking).toContain('href="/">Logga in</a>');
    expect(looking).toContain('id="gear" class="hknapp kugge" href="/installningar" aria-label="Inställningar"');
    const running = header({ admin: true, waiting: 2 });
    for (const part of ['id="connect"', 'id="waiting"', 'id="logout"', "Byt träff", 'id="waiting-count">2<']) expect(running).toContain(part);
    expect(running).toContain('class="hknapp har"');
  });

  it("marks the page in the tabs, and has Planering and Drift side by side", () => {
    for (const [page, path] of [
      ["nu", "/drift"],
      ["klienter", "/drift/klienter"],
      ["logg", "/drift/logg"],
    ] as const) {
      expect(header({ page })).toContain(`<a href="${path}" aria-current="page">`);
    }
    expect(header()).toContain('<span class="grupp">Planering</span><a href="/planering">Träffar</a>');
    const meet = header({ now: { ...now, meet_id: "grimslov", name: "Grimslöv 2027", version: 6 } });
    expect(meet).toContain('<a href="/planering/grimslov/versioner">Versioner</a>');
    expect(meet).toContain("Grimslöv 2027 · version 6");
  });

  it("never draws the hub's name as markup", () => {
    expect(header({ now: null })).toContain("Hubben &lt;i&gt;Väst&lt;/i&gt;");
  });

  it("opens Byt träff with the meets, the one Drift runs marked, and the one asked for chosen", () => {
    const choices = meetChoices([{ meet: { id: "grimslov", name: "Grimslöv 2027" }, versions: [{ number: 1 }] }] as never);
    const html = header({ admin: true, menu: "byt", choices, asked: "grimslov:1" });
    expect(html).toContain('role="dialog" aria-label="Byt träff"');
    expect(html).toContain('<button type="button" class="traff vald"><span class="vad"><b>Grimslöv 2027</b><span>version 1</span>');
    expect(html).toContain('aria-current="true" disabled=""><span class="vad"><b>Provbanan</b>');
    expect(html).toContain("Drift kör");
    expect(html).toContain("Börja om med samma träff");
  });

  it("shows Anslut with the code, the box's and the screen's addresses and the QR code", () => {
    const html = header({ admin: true, menu: "anslut", joining: { code: "123456", url: "https://hub.example/box#kod=123456" }, joinedAt: 7 });
    expect(html).toContain('id="connect-code" class="anslutkod">123456<');
    expect(html).toContain("https://hub.example/skarm#kod=123456");
    expect(html).toContain('src="/api/drift/1/connect.svg?7"');
  });
});

describe("Nu, Klienter and Logg (S6)", () => {
  it("shows everyone Nu, and the administrator the clock's buttons", () => {
    const looking = renderToStaticMarkup(<NuPage admin={false} now={now} clients={[]} choices={meetChoices([])} asked={null} automation={null} />);
    expect(looking).toContain("Trafikdag måndag · dag 1 · klockan står still");
    expect(looking).not.toContain('id="clock-toggle"');
    const running = renderToStaticMarkup(<NuPage admin now={now} clients={[]} choices={meetChoices([])} asked={null} automation={null} />);
    expect(running).toContain('id="clock-toggle"');
    expect(running).toContain(">Starta klockan<");
    expect(running).toContain('aria-pressed="true">4×</button>');
  });

  it("asks to start a meet when none runs, and to log in first when looking", () => {
    const html = renderToStaticMarkup(<NuPage admin now={null} clients={[]} choices={meetChoices([])} asked={null} automation={null} />);
    expect(html).toContain("Ingen träff är startad");
    expect(html).toContain('id="start-meet"');
    expect(renderToStaticMarkup(<NuPage admin={false} now={null} clients={[]} choices={[]} asked={null} automation={null} />)).toContain("Logga in för att starta en träff.");
  });

  it("asks for the login on Klienter and Logg", () => {
    for (const html of [renderToStaticMarkup(<KlienterPage admin={false} now={now} clients={[]} navigate={go} />), renderToStaticMarkup(<LoggPage admin={false} now={now} clients={[]} navigate={go} />)]) {
      expect(html).toContain("Logga in med hubbens PIN-kod");
      expect(html).not.toContain('id="clients"');
      expect(html).not.toContain('id="log"');
    }
  });

  it("puts the new clients under Väntar with the right buttons for each kind", () => {
    const clients = [
      { client_id: "b1", name: "Box 12", kind: "tmbox_web", status: "waiting", places: [], side: "both" },
      { client_id: "t1", name: "TKL Fy", kind: "tkl", status: "waiting", places: ["nby"], side: "both" },
      { client_id: "t2", name: "TKL Sjv", kind: "tkl", status: "approved", places: ["nby"], side: "both" },
      { client_id: "s1", name: "Skärm 1", kind: "screen", status: "approved", places: [], side: "both" },
    ] as unknown as Client[];
    const html = renderToStaticMarkup(<KlienterPage admin now={now} clients={clients} navigate={go} />);
    expect(html).toContain('aria-pressed="false">Väntar<span class="antal">2</span>');
    expect(html).toContain(">Tilldela<");
    expect(html).toContain(">Godkänn<");
    expect(html).toContain('class="fara">Återkalla<');
    expect(html).toContain(">Visa<");
    expect(html).toContain('<li class="vantar">');
    expect(renderToStaticMarkup(<KlienterPage admin now={now} clients={clients} navigate={go} group="screens" />)).not.toContain("Box 12");
  });

  it("lists what happened and what the clients were told no to", () => {
    const events = [{ seq: 3, model_time: "06:02", kind: "clearance.requested", place: "nby", train: null, actor: { kind: "dispatcher", id: null }, data: {} }] as never;
    const html = renderToStaticMarkup(<LoggPage admin now={now} clients={[]} navigate={go} rows={{ kind: "events", events }} />);
    expect(html).toContain("<td>06:02</td><td>Klarering begärd</td>");
    expect(html).toContain("<td>Norrby</td><td>Trafikledningen</td>");
    const refusals = [{ wall_time: "x", model_time: "06:03", client_id: "box-1", place: "nby", what: "knapp #", reason: null, message: "Läget ändrades." }] as never;
    const told = renderToStaticMarkup(<LoggPage admin now={now} clients={[]} navigate={go} rows={{ kind: "refusals", refusals }} />);
    expect(told).toContain("knapp #: Läget ändrades.");
    expect(renderToStaticMarkup(<LoggPage admin now={now} clients={[]} navigate={go} rows={{ kind: "events", events: [] }} />)).toContain("Inget har hänt här än.");
  });
});

describe("the start page (S1, H52)", () => {
  const info = (change: Partial<HubInfo>) => ({ name: "Testhubben", set_up: true, logged_in: false, ...change }) as HubInfo;
  const deployed = { product: "TrainMeet Hub", version: "0.1.0", hub_name: "Testhubben", commit: "29b7bb260a50b27c29f5147bcb43ccd469f41431", pr: 3, title: "Grundstommen", built: "2026-11-06T07:12:00+00:00", pr_url: "https://github.com/beahead-ab/trainmeet/pull/3", commit_url: "https://github.com/beahead-ab/trainmeet/commit/29b7bb260a50b27c29f5147bcb43ccd469f41431" } as Version;
  const page = (hub: HubInfo, version: Version | null = deployed) => renderToStaticMarkup(<StartPage info={hub} version={version} message="" navigate={go} />);

  it("asks a new hub for a name and a PIN, then for the login, then leads to the meet", () => {
    expect(page(info({ set_up: false }))).toContain('id="setup-form"');
    expect(page(info({}))).toContain('id="login-form"');
    expect(page(info({}))).toContain('href="/drift">Se träffen');
    const logged = page(info({ logged_in: true }));
    expect(logged).toContain('href="/drift">Kör träffen');
    expect(logged).toContain(">Logga ut<");
    expect(logged).toContain('href="/provbanan">Öppna Provbanan');
  });

  it("shows the version and the change that runs, or that it is a local build", () => {
    const html = page(info({}));
    expect(html).toContain("<dd>0.1.0</dd>");
    expect(html).toContain('href="https://github.com/beahead-ab/trainmeet/pull/3">#3 Grundstommen</a>');
    expect(html).toContain(">29b7bb2</a>");
    expect(html).toContain("2026-11-06 07:12 UTC");
    expect(page(info({}), { ...deployed, commit: null, pr: null, commit_url: null, pr_url: null })).toContain("Lokalt bygge");
    expect(builtText("inte en tid")).toBe("–");
  });

  it("never draws a title from the pull request as markup", () => {
    expect(page(info({}), { ...deployed, title: "<script>alert(1)</script>" })).toContain("&lt;script&gt;");
  });
});

describe("the addresses", () => {
  it("draws /, Provbanan and Drift's pages, and leaves Planering and the boxes to their own", () => {
    expect([pageOf("/"), pageOf("/provbanan"), pageOf("/drift"), pageOf("/drift/"), pageOf("/drift/klienter"), pageOf("/drift/logg")]).toEqual(["start", "provbanan", "nu", "nu", "klienter", "logg"]);
    expect(isOwn("/drift/logg")).toBe(true);
    expect(isOwn("/provbanan")).toBe(true);
    expect(pageOf("/installningar")).toBe("installningar");
    expect(isOwn("/installningar")).toBe(true);
    expect(isOwn("/planering")).toBe(false);
    expect(isOwn("/provbanan/box")).toBe(false);
  });
});

describe("Inställningar under the gear (TRAFIK-30, TRAFIK-31)", () => {
  const automation = {
    settings: { enabled: true, lost_contact_minutes: 0, disturbance: "off", where: "both", seed: "", stabling: true, stabling_minutes: 5, late_stop_minutes: 2, answer_seconds: 3 },
    places: [],
    trains: [],
  } as never;
  const settings = (admin: boolean, running: Now | null) =>
    renderToStaticMarkup(<SettingsPage admin={admin} now={running} hubName="Testhubben" version={null} automation={admin ? automation : null} automationSaved={0} />);

  it("shows the three heaps inside a meet, and only Den här hubben outside one", () => {
    expect(heaps(now).map((heap) => heap.label)).toEqual(["I paketet", "Under träffen", "Den här hubben"]);
    expect(heaps(null).map((heap) => heap.label)).toEqual(["Den här hubben"]);
    const outside = settings(true, null);
    expect(outside).toContain("Namn och version");
    expect(outside).not.toContain('id="automatik"');
    expect(outside).toContain("<dd>Testhubben</dd>");
  });

  it("lets the administrator change Automatiken and save it whole, and asks others to log in", () => {
    const html = settings(true, now);
    expect(html).toContain('id="traffen"');
    expect(html).toContain("<dd>Provbanan, för prov</dd>");
    expect(html).toContain('id="set-lost"');
    expect(html).toContain("Inget ändrat");
    expect(html).toContain('id="settings-save" type="button" class="primar" disabled=""');
    expect(settings(false, now)).toContain("Logga in med hubbens PIN-kod för att se och ändra automatiken.");
  });

  it("makes a new scenario key of two groups of four", () => {
    expect(newSeed()).toMatch(/^[A-Z2-9]{4}-[A-Z2-9]{4}$/);
    expect(newSeed(() => 0)).toBe("AAAA-AAAA");
  });

  it("leaves Automatiken's settings out of Nu and points to the gear", () => {
    const html = renderToStaticMarkup(<NuPage admin now={now} clients={[]} choices={meetChoices([])} asked={null} automation={automation} />);
    expect(html).toContain('href="/installningar#automatik"');
    expect(html).not.toContain('id="auto-save"');
  });
});

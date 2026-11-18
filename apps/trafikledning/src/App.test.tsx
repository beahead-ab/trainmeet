import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Client, HubInfo, Now, Version } from "./api";
import { isOwn, pageOf } from "./App";
import { meetChoices } from "@trainmeet/hubben";
import { heaps, Molnet, Natet, newSeed, SettingsPage, Uppdatering } from "./Installningar";
import { KlienterPage } from "./Klienter";
import { LoggPage } from "./Logg";
import { NuPage } from "./Nu";
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

describe("Nu, Klienter and Logg (S6)", () => {
  it("shows everyone Nu, and the administrator the clock's buttons", () => {
    const looking = renderToStaticMarkup(<NuPage admin={false} now={now} clients={[]} choices={meetChoices([])} asked={null} automation={null} />);
    expect(looking).toContain("Trafikdag måndag · dag 1 · klockan står still");
    expect(looking).not.toContain('id="clock-toggle"');
    const running = renderToStaticMarkup(<NuPage admin now={now} clients={[]} choices={meetChoices([])} asked={null} automation={null} />);
    const following = renderToStaticMarkup(<NuPage admin now={{ ...now, leader: { hub_name: "Pi:n hemma", heard: "2026-11-16T05:00:00Z", silent: 1 } } as Now} clients={[]} choices={meetChoices([])} asked={null} automation={null} />);
    expect(following).toContain("Följer Pi:n hemma live");
    expect(following).not.toContain('id="clock-controls"');
    expect(running).toContain('id="clock-toggle"');
    expect(running).toContain(">Starta klockan<");
    expect(running).toContain('aria-pressed="true">4×</button>');
    // Tidshopp (TRAFIK-01): the slider starts at the clock, and Ångra comes after a jump (F6).
    expect(looking).not.toContain('id="jump"');
    expect(running).toContain('id="jump-slider"');
    expect(running).toContain(">Hoppa till 06:00<");
    expect(running).not.toContain('id="undo-jump"');
    const jumped = { ...now, jump: { seq: 9, from_time: "06:00", to_time: "08:00", closed: 1, wall_time: "2026-11-16T09:00:00Z" } } as Now;
    const after = renderToStaticMarkup(<NuPage admin now={jumped} clients={[]} choices={meetChoices([])} asked={null} automation={null} />);
    expect(after).toContain("Tidshopp från 06:00 till 08:00 · 1 klarering stängdes");
    expect(after).toContain(">Ångra hoppet<");
    // Dygnsskiftet (F7): Starta ny dag, and Nu says when it is time.
    const day = { mode: "manual", time: "05:00", fixed: false, next_game_day: 2, next_traffic_day: "tue", suggested: "05:00", due: true, waiting: false };
    const due = renderToStaticMarkup(<NuPage admin now={{ ...now, day } as Now} clients={[]} choices={meetChoices([])} asked={null} automation={null} />);
    expect(due).toContain(">Starta dag 2 · tisdag<");
    expect(due).toContain("Klockan har passerat dygnsskiftet. Starta dag 2 när dagens tåg är inne.");
    expect(due).toContain('id="new-day-time"');
    expect(renderToStaticMarkup(<NuPage admin={false} now={{ ...now, day } as Now} clients={[]} choices={meetChoices([])} asked={null} automation={null} />)).not.toContain('id="new-day"');
  });

  it("lists the driftändringar with Släpp, and Tvinga igenom for one that waits (TRAFIK-02, H38)", () => {
    const changes = [
      { change_id: "c1", change: { kind: "cancel", train: "t43" }, status: "waiting", forced: false, train_number: "43", made: "06:10", waiting_for: ["43"] },
      { change_id: "c2", change: { kind: "number", train: "t44", number: "144" }, status: "dropped", forced: false, train_number: "44", made: "06:12", waiting_for: [] },
    ];
    const html = renderToStaticMarkup(<NuPage admin now={{ ...now, changes } as Now} clients={[]} choices={meetChoices([])} asked={null} automation={null} />);
    expect(html).toContain('id="change-count" class="antal">1</span>');
    expect(html).toContain(">Ny driftändring<");
    expect(html).toContain("<b>Inställt tåg 43</b>");
    expect(html).toContain("Väntar på tåg 43 · gjord 06:10");
    expect(html).toContain(">Tvinga igenom<");
    expect(html).toContain("<b>Tåg 44 får nummer 144</b>");
    expect(html).toContain("Släppt · gjord 06:12");
    const empty = renderToStaticMarkup(<NuPage admin now={now} clients={[]} choices={meetChoices([])} asked={null} automation={null} />);
    expect(empty).toContain("Inga driftändringar. Tidtabellen körs som versionen säger.");
    expect(renderToStaticMarkup(<NuPage admin={false} now={{ ...now, changes } as Now} clients={[]} choices={meetChoices([])} asked={null} automation={null} />)).not.toContain('id="changes"');
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
    // The export (TRAFIK-20): what is shown, as CSV or JSON.
    expect(html).toContain('id="export-csv" type="button">Exportera CSV</button>');
    expect(html).toContain('id="export-json" type="button">Exportera JSON</button>');
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
    const logged = page(info({ logged_in: true, admin: true }));
    expect(logged).toContain('href="/drift">Kör träffen');
    expect(logged).toContain('href="/planering">Planera en träff');
    expect(logged).toContain(">Logga ut<");
    expect(logged).toContain('href="/provbanan">Öppna Provbanan');
  });

  it("logs in with a one-time code from the dispatchers, and says what it gives (H56)", () => {
    const login = renderToStaticMarkup(<StartPage info={info({})} version={null} message="" navigate={go} onLogIn={() => undefined} onLogInWithCode={() => undefined} />);
    expect(login).toContain("eller med en engångskod från trafikledningen");
    expect(login).toContain('id="kodval" type="button" class="tm-knapp">Jag har en engångskod<');
    const dispatcher = page(info({ logged_in: true, admin: false, meet_role: "dispatcher" }));
    expect(dispatcher).toContain("Du är insläppt som trafikledare med en engångskod.");
    expect(dispatcher).toContain('href="/drift">Kör träffen');
    expect(dispatcher).not.toContain("Planera en träff");
  });

  it("logs in with TrainMeet ID when the hub has it, and says who one is (#78)", () => {
    expect(page(info({}))).not.toContain('id="id-login"');
    const offered = page(info({ id_login: true }));
    expect(offered).toContain('id="id-login" class="tm-knapp primar" href="/api/hub/id/login?next=%2F&amp;lang=sv">Logga in med TrainMeet ID<');
    const person = page(info({ logged_in: true, person: "Provare Ett", id_login: true }));
    expect(person).toContain("Du är inloggad med TrainMeet ID som Provare Ett.");
    expect(person).not.toContain("Planera en träff");
  });

  it("keeps the hub's own settings to the one with the PIN (H18, H56)", () => {
    const html = renderToStaticMarkup(<SettingsPage admin owner={false} now={null} hubName="Testhubben" version={null} automation={null} automationSaved={0} />);
    expect(html).toContain("Logga in med hubbens PIN-kod för att se AI-tjänsten.");
    expect(html).not.toContain('id="ai-connect"');
    expect(html).not.toContain("Byt PIN");
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

describe("Uppdatering under the gear (SYNK-19, SYNK-23)", () => {
  it("updates a Pi on the button, but never during a meet", () => {
    const idle = renderToStaticMarkup(<Uppdatering admin initial={{ available: true, build: "abc123def456", state: "done", message: "Hubben kör version abc123def456", at: null, meet_running: false } as never} />);
    expect(idle).toContain("abc123def456");
    expect(idle).toContain("Sök och installera");
    expect(idle).not.toContain('disabled=""');
    const during = renderToStaticMarkup(<Uppdatering admin initial={{ available: true, build: "abc123def456", state: null, meet_running: true } as never} />);
    expect(during).toContain("En träff pågår");
    expect(during).toContain('disabled=""');
  });
  it("shows Ny version finns when pi-senaste holds another change", () => {
    const base = { available: true, build: "abc123def456", state: null, meet_running: false };
    const newer = renderToStaticMarkup(<Uppdatering admin initial={{ ...base, latest: "fedcba987654", newer: true, checked: "2026-11-17T06:00:00Z" } as never} />);
    expect(newer).toContain("Ny version finns.");
    expect(newer).toContain("fedcba987654");
    expect(newer).toContain("Uppdatera nu");
    const same = renderToStaticMarkup(<Uppdatering admin initial={{ ...base, latest: "abc123def456", newer: false, checked: "2026-11-17T06:00:00Z" } as never} />);
    expect(same).not.toContain("Ny version finns");
    expect(same).toContain("Sök och installera");
    const offline = renderToStaticMarkup(<Uppdatering admin initial={{ ...base, latest: null, newer: false, checked: null } as never} />);
    expect(offline).toContain("Har den internet?");
  });
  it("says that the hub in the cloud is updated by its deploy", () => {
    const html = renderToStaticMarkup(<Uppdatering admin initial={{ available: false, reason: "Hubben i molnet uppdateras när en ändring läggs ut. Uppdateringen här gäller en Pi." } as never} />);
    expect(html).toContain("Hubben i molnet");
    expect(html).not.toContain("Sök och installera");
  });
});

describe("Pi:ns nät under the gear (SYNK-26, H45)", () => {
  const status = {
    supported: true,
    reason: null,
    profiles: [
      { uuid: "11111111-1111-4111-8111-111111111111", ssid: "Hemma", security: "wpa2", hidden: false, priority: 10, autoconnect: true, active: true, editable: true },
      { uuid: "22222222-2222-4222-8222-222222222222", ssid: "Träffens nät", security: "wpa3", hidden: false, priority: 0, autoconnect: true, active: false, editable: true },
    ],
    devices: [{ interface: "wlan0", state: 100, uuid: "11111111-1111-4111-8111-111111111111", addresses: ["192.168.1.20"] }],
    nearby: [{ ssid: "Klubblokalen", security: ["wpa2"], signal: 80, interface: "wlan0" }],
    radio_enabled: true,
    recovering: false,
    trial: null,
    can_manage: true,
  } as never;
  it("lists the Pi's nets, with Anslut nu only for one that is not on, and never a password", () => {
    const html = renderToStaticMarkup(<Natet admin initial={status} />);
    expect(html).toContain("Hemma");
    expect(html).toContain("anslutet nu");
    expect(html.match(/>Anslut nu<\/button>/g)?.length).toBe(1);
    expect(html).toContain("Spara nätet");
    expect(html).toContain("Klubblokalen");
    expect(html).not.toContain("private");
  });
  it("only reads over plain HTTP, and says where to change it", () => {
    const html = renderToStaticMarkup(<Natet admin initial={{ ...(status as object), can_manage: false } as never} />);
    expect(html).toContain("över HTTPS");
    expect(html).not.toContain("Spara nätet");
  });
  it("says so on a hub without the Pi's network service", () => {
    const html = renderToStaticMarkup(<Natet admin initial={{ supported: false, reason: "Pi:ns nät ställs in på en Raspberry Pi med TrainMeets nätverkstjänst." } as never} />);
    expect(html).toContain("Raspberry Pi");
  });
  it("asks to keep a net on trial within its seconds", () => {
    const trial = { ...(status as object), trial: { uuid: "22222222-2222-4222-8222-222222222222", interface: "wlan0", remaining: 74, token: "abc" } } as never;
    const html = renderToStaticMarkup(<Natet admin initial={trial} />);
    expect(html).toContain("Provar Träffens nät.");
    expect(html).toContain("74 sekunder");
    expect(html).toContain("Behåll anslutningen");
    expect(html).toContain("Återställ nu");
  });
});

describe("Namn och PIN under the gear (SYNK-07, H46)", () => {
  it("lets the administrator rename the hub and change the PIN, and tells how a forgotten one is set", () => {
    const html = renderToStaticMarkup(<SettingsPage admin now={null} hubName="Testhubben" version={null} automation={null} automationSaved={0} />);
    expect(html).toContain('id="hub-name"');
    expect(html).toContain('value="Testhubben"');
    expect(html).toContain("Spara namnet");
    expect(html).toContain('id="pin-now"');
    expect(html).toContain('autoComplete="current-password"');
    expect(html).toContain("Byt PIN");
    expect(html).toContain("trainmeet-ny-pin.txt");
  });
  it("shows only the name to the one who is not logged in", () => {
    const html = renderToStaticMarkup(<SettingsPage admin={false} now={null} hubName="Testhubben" version={null} automation={null} automationSaved={0} />);
    expect(html).toContain("Testhubben");
    expect(html).not.toContain('id="hub-name"');
    expect(html).not.toContain("Byt PIN");
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
    expect(outside).toContain('value="Testhubben"');
    expect(settings(false, null)).toContain("<dd>Testhubben</dd>");
  });

  it("links the Pi to the cloud with a code, and shows how the synk goes (SYNK-02)", () => {
    const cloud = { address: "https://test.hub.trainmeet.app", meet: "varnamo", meet_name: "Värnamo Moduldagar", cloud_name: "Testhubben", linked: "2026-11-16T04:00:00Z", heard: "2026-11-16T04:01:00Z", versions: 2, problem: "Molnhubben svarar inte.", home_here: false };
    const linked = renderToStaticMarkup(<Molnet admin initial={[cloud]} />);
    expect(linked).toContain("<b>Värnamo Moduldagar</b>");
    expect(linked).toContain("Testhubben · https://test.hub.trainmeet.app · 2 versioner");
    expect(linked).toContain("Molnhubben svarar inte.");
    expect(linked).toContain("Koppla bort");
    expect(linked).toContain('id="cloud-connect" type="button" class="primar" disabled=""');
    expect(renderToStaticMarkup(<Molnet admin={false} initial={[]} />)).toContain("Logga in med hubbens PIN-kod för att koppla Pi:n till molnet.");
    expect(linked).toContain("Ta hem träffen hit");
    expect(linked).toContain("Träffens hem är Testhubben: där planeras och publiceras den.");
    const home = renderToStaticMarkup(<Molnet admin initial={[{ ...cloud, home_here: true }]} />);
    expect(home).toContain("Lämna tillbaka");
    expect(home).not.toContain("Koppla bort");
  });

  it("connects own AI under Den här hubben, and never shows the key (H58, H70)", () => {
    expect(heaps(null)[0]?.items.map(([id]) => id)).toEqual(["hubben", "natet", "traffens-wifi", "uppdatering", "molnet", "ai"]);
    const none = renderToStaticMarkup(<SettingsPage admin now={null} hubName="Testhubben" version={null} automation={null} automationSaved={0} ai={null} />);
    expect(none).toContain("Ingen egen AI är inkopplad");
    expect(none).toContain('id="ai-connect" type="button" class="primar" disabled=""');
    expect(none).toContain("Koppla in och prova");
    expect(none).not.toContain('id="ai-off"');
    const ai = { format: "claude", address: "https://api.anthropic.com", model: "en-modell", key_set: true, checked: "2026-11-16T03:00:00Z" } as const;
    const set = renderToStaticMarkup(<SettingsPage admin now={null} hubName="Testhubben" version={null} automation={null} automationSaved={0} ai={ai} />);
    expect(set).toContain("Inkopplad · en-modell");
    expect(set).toContain('placeholder="Sparad"');
    expect(set).toContain('id="ai-key" type="password"');
    expect(set).toContain('id="ai-off"');
    expect(set).toContain('id="ai-connect" type="button" class="primar">Spara och prova');
    expect(renderToStaticMarkup(<SettingsPage admin={false} now={null} hubName="Testhubben" version={null} automation={null} automationSaved={0} />)).toContain("Logga in med hubbens PIN-kod för att se AI-tjänsten.");
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

  it("lets the administrator change the places' numbers, and asks others to log in (TRAFIK-06)", () => {
    expect(heaps(now)[1]?.items.map(([id]) => id)).toContain("telefon");
    const phones = [{ place: "nby", phone: "101" }];
    const html = renderToStaticMarkup(<SettingsPage admin now={now} hubName="Testhubben" version={null} automation={automation} automationSaved={0} phones={phones} />);
    expect(html).toContain('<label for="phone-nby" class="etikett">Norrby (Nby)</label>');
    expect(html).toContain('value="101"');
    expect(html).toContain('id="phone-save" type="button" class="primar" disabled=""');
    expect(settings(false, now)).toContain("Logga in med hubbens PIN-kod för att se och ändra telefonnumren.");
  });

  it("lets the administrator choose the day change by hand or automatic, and its time (F7)", () => {
    const day = { mode: "automatic", time: "04:30", fixed: true, next_game_day: 2, next_traffic_day: "tue", suggested: "04:30", due: false, waiting: false };
    expect(heaps(now)[1]?.items.map(([id]) => id)).toEqual(["automatik", "dygnsskifte", "telefon", "traffens-wifi"]);
    const html = settings(true, { ...now, day } as Now);
    expect(html).toContain('id="dygnsskifte"');
    expect(html).toContain('aria-pressed="true">Automatiskt</button>');
    expect(html).toContain('id="set-day-time" type="time" step="60" value="04:30"');
    expect(html).toContain('id="day-save" type="button" class="primar" disabled=""');
    expect(settings(false, { ...now, day } as Now)).toContain("Logga in med hubbens PIN-kod för att se och ändra dygnsskiftet.");
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

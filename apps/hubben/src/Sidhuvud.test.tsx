import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Now } from "./api";
import { Sidhuvud, type HeaderProps } from "./Sidhuvud";
import { meetChoices } from "./traff";

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
    <Sidhuvud current="/drift" hubName="Hubben <i>Väst</i>" admin={false} now={now} elapsedMs={0} waiting={0} choices={meetChoices([])} asked={null} menu={null} joining={null} joinedAt={0} navigate={go} onMenu={go} onStart={go} onLogOut={go} {...change} />,
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

  it("shows who is logged in with TrainMeet ID, and Logga ut, without the dispatcher's buttons (#78, S1)", () => {
    const person = header({ admin: false, owner: false, loggedIn: true, person: "Provare Ett" });
    expect(person).toContain('id="logout"');
    expect(person).toContain('title="Inloggad som Provare Ett"');
    expect(person).toContain("Provare Ett · </span>Logga ut");
    expect(person).not.toContain('id="connect"');
    expect(person).not.toContain('href="/">Logga in</a>');
  });

  it("gives someone let in with a one-time code the meet that runs, but not Byt träff (H56)", () => {
    const dispatcher = header({ admin: true, owner: false });
    for (const part of ['id="connect"', 'id="waiting"', 'id="logout"']) expect(dispatcher).toContain(part);
    expect(dispatcher).not.toContain("Byt träff");
    expect(dispatcher).toContain('id="meet-name"');
  });

  it("marks the page in the tabs, and has Planering and Drift side by side", () => {
    for (const path of ["/drift", "/drift/klienter", "/drift/logg"]) {
      expect(header({ current: path })).toContain(`<a href="${path}" aria-current="page">`);
    }
    expect(header({ current: "/installningar" })).toMatch(/id="gear"[^>]*aria-current="page"/);
    expect(header()).toContain('<span class="grupp">Planering</span><a href="/planering">Träffar</a>');
    const meet = header({ now: { ...now, meet_id: "grimslov", name: "Grimslöv 2027", version: 6 } });
    expect(meet).toContain('<a href="/planering/grimslov/versioner">Versioner</a>');
    expect(meet).toContain("Grimslöv 2027 · version 6");
    // In Planering the tabs are for the meet in view, and its page is marked.
    const viewed = header({ viewed: "mellby", current: "/planering/mellby/versioner" });
    expect(viewed).toContain('<a href="/planering/mellby/versioner" aria-current="page">Versioner</a>');
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

  it("leaves a withdrawn version out of Byt träff (PLAN-18)", () => {
    const choices = meetChoices([{ meet: { id: "grimslov", name: "Grimslöv 2027" }, versions: [{ number: 1 }, { number: 2, withdrawn: "2026-11-16T10:00:00Z" }] }] as never);
    expect(choices.map((choice) => choice.value)).toEqual(["grimslov:1", "provbanan:1"]);
  });

  it("shows Anslut with the code, the box's and the screen's addresses and the QR code", () => {
    const html = header({ admin: true, menu: "anslut", joining: { code: "123456", url: "https://hub.example/box#kod=123456" }, joinedAt: 7 });
    expect(html).toContain('id="connect-code" class="anslutkod">123456<');
    expect(html).toContain("https://hub.example/skarm#kod=123456");
    expect(html).toContain('src="/api/drift/1/connect.svg?7"');
  });
});


import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Now, Package, Participant } from "@trainmeet/hubben";
import provbanan from "../../../contracts/examples/provbanan.meet.json";
import { Connect, DeltagarePage, languageOf, Share, TEXT } from "./Deltagare";

const now = {
  meet_id: "provbanan",
  name: "Provbanan",
  version: 1,
  traffic_day: "sat",
  game_day: 2,
  clock: { time: "06:00", seconds: 21600, running: true, speed: 4, game_day: 2 },
  places: [],
  legs: [
    { leg: "l1", train: "t101", train_number: "101", from_place: "nby", to_place: "asn", section: "nby-asn", state: "planned", departure: "06:05", arrival: "06:12" },
  ],
  clearances: [],
  changes: [],
} as unknown as Now;
const pkg = provbanan as unknown as Package;
const outside: Participant = { full: false, logged_in: false, wifi: null, link: null };
const onSite: Participant = { full: true, logged_in: false, wifi: { name: "TrainMeet-Grimslöv", open: false, password: "lokforare27" }, link: null };
const page = (participant: Participant, language: "sv" | "en" = "sv") =>
  renderToStaticMarkup(<DeltagarePage now={now} elapsedMs={0} message="" language={language} initial={{ participant, pkg }} onLogIn={() => undefined} />);

describe("Deltagarna: what everyone sees without logging in (DELT-01, S1)", () => {
  it("shows the clock, the line and the next events, in that order, telephone first", () => {
    const html = page(onSite);
    expect(html).toContain('<h1 id="deltagare-traff">Provbanan</h1>');
    expect(html).toContain(">06:00<");
    expect(html).toContain("Går · ×4 · Lördag · dag 2");
    expect(html).toContain('class="banoversikt"');
    expect(html).toContain("tåg på linjen");
    expect(html).toContain("avgår Norrby mot Åsen");
    const order = ["deltagare-traff", "deltagare-bana", "deltagare-handelser", "anslut-box"].map((id) => html.indexOf(`id="${id}"`));
    expect(order.every((at) => at >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  it("over the internet, without logging in, shows only the traffic (S8)", () => {
    const html = page(outside);
    expect(html).toContain('id="bara-trafiken"');
    expect(html).toContain("Du ser trafiken. Namn, foton och träffens Wi-Fi visas på träffens nät eller när du är inloggad.");
    expect(html).not.toContain('id="dela-traffen"');
    expect(html).not.toContain('id="anslut-box"');
    expect(html).toContain('id="deltagare-logga-in"');
    expect(html).toContain("avgår Norrby mot Åsen");
  });

  it("on the meet's network, shares the meet and connects a box (DELT-02, DELT-03)", () => {
    const html = page(onSite);
    expect(html).toContain('id="dela-traffen"');
    expect(html).toContain('id="anslut-box"');
    expect(html).not.toContain('id="bara-trafiken"');
  });

  it("says when no meet runs", () => {
    const html = renderToStaticMarkup(<DeltagarePage now={null} elapsedMs={0} message="" language="sv" initial={{ participant: outside, pkg: null }} onLogIn={() => undefined} />);
    expect(html).toContain("Ingen träff körs just nu.");
  });
});

describe("Anslut din TMBox: three steps, in this order (DELT-03)", () => {
  it("gives the network and password as text, since a box cannot scan", () => {
    const html = renderToStaticMarkup(<Connect participant={onSite} t={TEXT.sv} />);
    expect(html).toContain("Koppla boxen till träffens Wi-Fi");
    expect(html).toContain("Nätverk TrainMeet-Grimslöv · lösenord lokforare27");
    expect(html).toContain("Boxen hittar hubben själv");
    expect(html).toContain("Trafikledaren tilldelar driftplats");
    expect(html).toContain('href="/box"');
    expect(html).not.toContain("<img");
    const open = renderToStaticMarkup(<Connect participant={{ ...onSite, wifi: { name: "Öppet", open: true, password: null } }} t={TEXT.sv} />);
    expect(open).toContain("Nätverk Öppet · öppet nät, inget lösenord");
    const none = renderToStaticMarkup(<Connect participant={{ ...onSite, wifi: null }} t={TEXT.sv} />);
    expect(none).toContain("Fråga trafikledningen om träffens Wi-Fi.");
  });
});

describe("Dela träffen: QR 1 · Wi-Fi and 2 · Träffen (DELT-02)", () => {
  it("draws the Wi-Fi code from the hub and the meet's link", () => {
    const html = renderToStaticMarkup(<Share participant={onSite} t={TEXT.sv} origin="http://trainmeet.local" />);
    expect(html).toContain('src="/api/deltagare/wifi.svg"');
    expect(html).toContain(`src="/api/deltagare/traffen.svg?address=${encodeURIComponent("http://trainmeet.local/")}"`);
    expect(html).toContain("Länken fungerar på träffens nät.");
    const cloud = renderToStaticMarkup(<Share participant={{ ...onSite, link: "https://test.hub.trainmeet.app" }} t={TEXT.sv} origin="http://trainmeet.local" />);
    expect(cloud).toContain(">https://test.hub.trainmeet.app<");
    expect(cloud).toContain("Länken fungerar på träffnätet och via internet.");
    const none = renderToStaticMarkup(<Share participant={{ ...onSite, wifi: null }} t={TEXT.sv} origin="http://trainmeet.local" />);
    expect(none).toContain("Träffens Wi-Fi har inte lagts in ännu.");
    expect(none).not.toContain("wifi.svg");
  });
});

describe("Swedish and English first (DELT-14)", () => {
  it("speaks Swedish to a Swedish browser and English to the rest", () => {
    expect(languageOf(["sv-SE", "en"])).toBe("sv");
    expect(languageOf(["en-GB", "sv"])).toBe("sv");
    expect(languageOf(["de-DE"])).toBe("en");
    const html = page(outside, "en");
    expect(html).toContain("Running · ×4 · Saturday · day 2");
    expect(html).toContain("You see the traffic.");
    expect(html).toContain("leaves Norrby for Åsen");
  });
});

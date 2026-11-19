import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Automation, Client, DriftEvent, Now } from "./api";
import { meetChoices } from "@trainmeet/hubben";
import { clientDetails, describe as says, modeText, shown, wantedRows } from "./drift";
import { KlienterPage } from "./Klienter";
import { NuPage, PlaceActions } from "./Nu";

// Fjärrstyrning in Trafikledningen (#36 del a, TRAFIK-34, FR4, FR5, FR9, FR37): the remote
// interlocking in Klienter with its area, the operating form and who controls each station in
// Nu with Ta över and Lämna tillbaka, and the handovers and routes in Logg.

const now = {
  meet_id: "provbanan",
  name: "Provbanan",
  version: 1,
  traffic_day: "mon",
  game_day: 1,
  clock: { time: "06:00", seconds: 21600, running: true, speed: 4, game_day: 1 },
  places: [
    { place: "nby", code: "Nby", name: "Norrby", part_of: null },
    { place: "asn", code: "Ån", name: "Åsen", part_of: null },
    { place: "mla", code: "Mlå", name: "Mellanå", part_of: null },
  ],
  legs: [],
  clearances: [],
} as unknown as Now;

const remote: Client = {
  client_id: "remote-1a2b",
  name: "Fjärr Västra",
  kind: "remote",
  status: "waiting",
  places: ["asn", "mla"],
  side: "both",
  language: null,
  display: null,
  view: null,
  station_id: null,
  questions: [],
  wanted: [
    { place: "asn", status: "waiting", part: null, part_of: null },
    { place: "mla", status: "waiting", part: null, part_of: null },
  ],
  controls: [],
};
const tkl: Client = { ...remote, client_id: "tkl-asn", name: "TKL Åsen", kind: "tkl", status: "approved", places: ["asn"], wanted: [], station_id: "asen" };

describe("Klienter: fjärrställverket och dess område (TRAFIK-34, FR4)", () => {
  it("shows the remote interlocking with its area, each driftplats to approve on its own", () => {
    expect(clientDetails(remote, now)).toBe("Fjärrställverk · Väntar · Fjärrområde Åsen, Mellanå");
    const html = renderToStaticMarkup(<KlienterPage admin now={now} clients={[remote]} navigate={() => undefined} />);
    expect(html).toContain("<b>Fjärr Västra</b>");
    expect(html).toContain('aria-label="Godkänn Åsen"');
    expect(html).toContain('aria-label="Neka Mellanå"');
    expect(html).toContain("Det ger bara rätt att ta emot dem");
    expect(wantedRows(remote, now)[0]?.approve).toEqual({ action: "approve", client_id: "remote-1a2b", places: ["asn"] });
    // It counts among the interlockings.
    const listed = renderToStaticMarkup(<KlienterPage admin now={now} clients={[remote]} group="stations" navigate={() => undefined} />);
    expect(listed).toContain("<b>Fjärr Västra</b>");
  });

  it("says what it remote-controls once a station is handed to it", () => {
    const approved: Client = { ...remote, status: "approved", wanted: [{ place: "asn", status: "approved", part: null, part_of: null }], controls: ["asn"] };
    expect(clientDetails(approved, now)).toBe("Fjärrställverk · Ansluten · Fjärrområde Åsen · Fjärrstyr Åsen");
    // A TKL that remote-controls its neighbour says so too (FR3).
    expect(clientDetails({ ...tkl, places: ["mla"], controls: ["asn"] }, now)).toBe("TKL · Ansluten · Mellanå · Fjärrstyr Åsen");
    expect(renderToStaticMarkup(<KlienterPage admin now={now} clients={[approved]} navigate={() => undefined} />)).toContain("Återkalla");
  });
});

const settings = { enabled: true, lost_contact_minutes: 0, disturbance: "off", where: "both", seed: "", stabling: true, stabling_minutes: 5, late_stop_minutes: 2, answer_seconds: 3 };
const place = (given: Record<string, unknown>) =>
  ({ name: "Åsen", code: "Ån", left_by: null, takes_over_in: null, operator: null, present: [], controller: null, offered_to: null, back_to: null, controllable: true, ...given }) as unknown as NonNullable<Automation["places"]>[number];
const clientName = (id: string) => ({ "remote-1a2b": "Fjärr Västra", "tkl-asn": "TKL Åsen" })[id] ?? id;

describe("Nu: driftformen, den som styr, Ta över och Lämna tillbaka (FR5, FR9)", () => {
  it("shows each station's operating form and who controls it", () => {
    expect(modeText(place({ place: "asn", mode: "remote", operator: "tkl-asn", controller: "remote-1a2b" }), clientName)).toBe("Fjärrstyrd · styrs av Fjärr Västra");
    expect(modeText(place({ place: "asn", mode: "offered", operator: "tkl-asn", offered_to: "remote-1a2b" }), clientName)).toBe("Erbjuden · TKL Åsen · till Fjärr Västra");
    expect(modeText(place({ place: "asn", mode: "no_contact", controller: "remote-1a2b" }), clientName)).toBe("Kontakt saknas · styrs av Fjärr Västra");
    expect(modeText(place({ place: "asn", mode: "manned", operator: "tkl-asn" }), clientName)).toBe("Bemannad · TKL Åsen");
  });

  it("takes a remote-controlled station over, and gives it back to the one who controlled it", () => {
    const taken: unknown[] = [];
    const over = renderToStaticMarkup(<PlaceActions place={place({ place: "asn", mode: "remote", controller: "remote-1a2b" })} clientName={clientName} onPlace={(change) => taken.push(change)} />);
    expect(over).toBe('<button type="button">Ta över</button>');
    const back = renderToStaticMarkup(<PlaceActions place={place({ place: "asn", mode: "automatic", left_by: "dispatcher", back_to: "remote-1a2b", present: ["tkl-asn"] })} clientName={clientName} />);
    expect(back).toContain(">Lämna tillbaka till Fjärr Västra<");
    expect(back).toContain(">Ge till TKL Åsen<");
    // A manned station is left to the automation as before.
    const manned = renderToStaticMarkup(<PlaceActions place={place({ place: "asn", mode: "manned", operator: "tkl-asn" })} clientName={clientName} />);
    expect(manned).toContain(">Lämna till automatiken<");
    expect(renderToStaticMarkup(<PlaceActions place={place({ place: "asn", mode: "automatic" })} clientName={clientName} />)).toContain("Ingen box eller TKL ansluten");
  });

  it("lists the stations in Automatiken with their form", () => {
    const automation = {
      settings,
      places: [place({ place: "asn", mode: "remote", operator: "tkl-asn", controller: "remote-1a2b" }), place({ place: "nby", name: "Norrby", code: "Nby", mode: "manned", controllable: false })],
      trains: [],
    } as unknown as Automation;
    const html = renderToStaticMarkup(<NuPage admin now={now} clients={[remote, tkl]} choices={meetChoices([])} asked={null} automation={automation} openAutomation />);
    expect(html).toContain("1 bemannade, 1 fjärrstyrda");
    expect(html).toContain('<span class="pill remote">Fjärrstyrd · styrs av Fjärr Västra</span>');
    expect(html).toContain(">Ta över<");
  });
});

describe("Logg: överlämningarna och fjärrtågvägarna (FR37)", () => {
  const event = (kind: string, data: Record<string, unknown> = {}) => ({ kind, data }) as unknown as DriftEvent;
  const clients = [remote, tkl];

  it("says who the station was handed to, and how it ended", () => {
    expect(says(event("place.offered", { to: "remote-1a2b", kind: "remote" }), null, clients)).toBe("Stationen erbjuden till Fjärr Västra");
    expect(says(event("place.offer_answered", { to: "remote-1a2b", accepted: true }), null, clients)).toBe("Fjärr Västra tog emot stationen: fjärrstyrd");
    expect(says(event("place.offer_answered", { to: "remote-1a2b", expired: true }), null, clients)).toBe("Erbjudandet till Fjärr Västra gick ut efter en minut");
    expect(says(event("place.offer_answered", { to: "remote-1a2b" }), null, clients)).toBe("Fjärr Västra avböjde stationen");
    expect(says(event("place.taken_back", { by: "operator", client_id: "tkl-asn", controller: "remote-1a2b" }), null, clients)).toBe("Tagen tillbaka från Fjärr Västra: bemannad");
    expect(says(event("place.left", { by: "dispatcher", controller: "remote-1a2b" }), null, clients)).toBe("Togs över från Fjärr Västra");
    expect(says(event("place.remote", { controller: "remote-1a2b", kind: "remote" }), null, clients)).toBe("Trafikledningen gav stationen till Fjärr Västra: fjärrstyrd");
    expect(says(event("place.taken_back", { by: "operator", client_id: "tkl-asn" }))).toBe("Tagen tillbaka från automatiken");
  });

  it("says what became of a route asked for from afar, and of the automats", () => {
    expect(says(event("route.requested", { request_id: "r1", route: "A-1" }))).toBe("Fjärrtågväg A-1 begärd");
    expect(says(event("route.answered", { request_id: "r1", locked: true }))).toBe("Fjärrtågvägen låst i stationens ställverk");
    expect(says(event("route.answered", { request_id: "r1", locked: false, reason: "station_not_answering", timed_out: true }))).toBe("Fjärrtågvägen nekad: stationen svarade inte");
    expect(says(event("route.released", { route: "A-1", by: "remote" }))).toBe("Fjärrtågväg A-1 upplöst");
    expect(says(event("automat.set", { code: "A3", on: true, by: "automat" }))).toBe("Stationsautomat A3 inkopplad av sig själv");
    expect(says(event("automat.set", { code: "A3", on: false }))).toBe("Stationsautomat A3 urkopplad");
    expect(says(event("local_release.answered", { code: "L01", given: true }))).toBe("Lokalt område L01 givet");
    // The station's whole state is Drift's own record; Logg shows what changed in it.
    expect(shown(event("route.state"))).toBe(false);
    expect(shown(event("route.requested"))).toBe(true);
  });

  it("says what became of a part's request and the list Klara att skicka, and who (#36 del d)", () => {
    const by = { kind: "client" as const, id: "remote-1a2b" };
    expect(says(event("part.requested", { part: "bangarden", request_id: "7", text: "Bangården begär 52 → 3." }))).toBe("Vidare från stationen: Bangården begär 52 → 3.");
    expect(says({ ...event("part.answered", { part: "bangarden", request_id: "7", approve: true }), actor: by }, null, clients)).toBe("Fjärr Västra godkände delens begäran");
    expect(says({ ...event("part.answered", { part: "bangarden", request_id: "7", approve: false, reason: "Tåg 102 kommer." }), actor: by }, null, clients)).toBe("Fjärr Västra nekade delens begäran: Tåg 102 kommer.");
    expect(says({ ...event("ready.moved", { train_number: "3795", to: 0 }), actor: by }, null, clients)).toBe("Fjärr Västra flyttade tåg 3795 till plats 1 i Klara att skicka");
    expect(says({ ...event("ready.sent", { train_number: "3795" }), actor: by }, null, clients)).toBe("Fjärr Västra: tåg 3795 skickat");
  });
});

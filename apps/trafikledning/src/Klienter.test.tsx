import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Client, Now } from "./api";
import { waits, wantedRows } from "./drift";
import { ExitQuestions, KlienterPage, remaining, SlappIn } from "./Klienter";

const tkl: Client = {
  client_id: "tkl-1a2b3c",
  name: "TKL Mellanå",
  kind: "tkl",
  status: "approved",
  places: ["mla"],
  side: "both",
  language: null,
  display: null,
  view: null,
  station_id: "mellana",
  questions: [
    {
      station_id: "mellana",
      place: "mla",
      section: "s-asn-mla",
      other_place: "asn",
      other_name: "Åsen",
      side: "left",
      alternatives: [
        { exit: "AU", side: "left", name: "Åsen uppspår" },
        { exit: "AN", side: "left", name: "Åsen nedspår" },
      ],
    },
  ],
};

describe("Hubben frågar om en utfart i Klienter (H26, TRAFIK-05)", () => {
  it("asks which exit leads to the neighbour, with the station's exits as answers", () => {
    const html = renderToStaticMarkup(<ExitQuestions client={tkl} onAnswer={() => undefined} />);
    expect(html).toContain("Vilken utfart går mot Åsen?");
    expect(html).toContain("Sträckan ligger åt vänster.");
    expect(html).toContain(">AU · Åsen uppspår<");
    expect(html).toContain(">AN · Åsen nedspår<");
    expect(html).toContain("Det första svaret gäller hela träffen.");
    expect(renderToStaticMarkup(<ExitQuestions client={{ ...tkl, questions: [] }} onAnswer={() => undefined} />)).toBe("");
  });

  it("shows the questions under the TKL in the list", () => {
    const html = renderToStaticMarkup(<KlienterPage admin now={null} clients={[tkl]} navigate={() => undefined} />);
    expect(html).toContain("Återkalla");
    expect(html).toContain("Vilken utfart går mot Åsen?");
  });
});

describe("Släpp in en person (H56, KONTO-19)", () => {
  it("lists who is in with a one-time code, never the code, and lets the dispatcher take it away", () => {
    const html = renderToStaticMarkup(
      <SlappIn
        initial={[
          { person: "3f2a9c1b7d4e", name: "Sjövik", role: "dispatcher", since: "2026-11-18T09:05:00Z", until: "2026-11-25T09:05:00Z" },
          { person: "9b8a7c6d5e4f", name: null, role: "dispatcher", since: "2026-11-18T10:00:00Z", until: "2026-11-25T10:00:00Z" },
        ]}
      />,
    );
    expect(html).toContain("Släpp in en person");
    expect(html).toContain("gäller en gång i 15 minuter");
    expect(html).toContain(">Ge en kod<");
    expect(html).toContain("<b>Sjövik</b>");
    expect(html).toContain("<b>Utan namn</b>");
    expect(html).toContain("Trafikledare · med engångskod sedan");
    expect(html.match(/>Ta bort</g)).toHaveLength(2);
  });

  it("counts the code's last minutes down", () => {
    const at = Date.parse("2026-11-18T09:00:00Z");
    expect(remaining("2026-11-18T09:15:00Z", at)).toBe("15:00");
    expect(remaining("2026-11-18T09:00:59Z", at)).toBe("0:59");
    expect(remaining("2026-11-18T08:59:00Z", at)).toBe("0:00");
  });

  it("shows the card only while a meet runs", () => {
    const html = renderToStaticMarkup(<KlienterPage admin now={null} clients={[]} navigate={() => undefined} letIn={[]} />);
    expect(html).not.toContain("Släpp in en person");
  });
});

// Godkännande per driftplats (TRAFIK-35): Lekby's TKL asks for Lekby and its yard, a part that is
// its own driftplats (PLAN-34). Each is a row of its own, the part marked with its station.
const lekbyNow = {
  meet_id: "varnamo",
  name: "Värnamo",
  version: 1,
  traffic_day: "mon",
  game_day: 1,
  clock: { time: "06:00", seconds: 21600, running: false, speed: 4, game_day: 1 },
  places: [
    { place: "p4", code: "Lek", name: "Lekby", part_of: null },
    { place: "lokstall", code: "Lls", name: "Lekby lokstall", part_of: "p4" },
    { place: "p5", code: "Gdö", name: "Gårdsjö", part_of: null },
  ],
  legs: [],
  clearances: [],
} as unknown as Now;
const lekby: Client = {
  client_id: "tkl-lekby",
  name: "TKL Lekby",
  kind: "tkl",
  status: "waiting",
  places: ["lokstall", "p4"],
  side: "both",
  language: null,
  display: null,
  view: null,
  station_id: "lekby-tkl",
  questions: [],
  wanted: [
    { place: "lokstall", status: "waiting", part: "lokstall", part_of: "p4" },
    { place: "p4", status: "waiting", part: null, part_of: null },
  ],
};

describe("Klienter: en driftplats per del (TRAFIK-35)", () => {
  it("shows the station and its part as rows of their own, the part after its station", () => {
    const html = renderToStaticMarkup(<KlienterPage admin now={lekbyNow} clients={[lekby]} navigate={() => undefined} />);
    expect(html).toContain('aria-label="Driftplatser för TKL Lekby"');
    expect(html.indexOf("<b>Lekby</b>")).toBeLessThan(html.indexOf("<b>Lekby lokstall</b>"));
    expect(html).toContain("del av Lekby · Väntar");
    expect(html).toContain('aria-label="Godkänn Lekby lokstall"');
    expect(html).toContain('aria-label="Neka Lekby lokstall"');
    expect(html).toContain('aria-label="Godkänn Lekby"');
    // The rows answer; the client's own Godkänn with a place to choose is not needed.
    expect(html).not.toContain('aria-label="Driftplats för TKL Lekby"');
  });

  it("approves or refuses the part on its own, never the station with it", () => {
    const [station, part] = wantedRows(lekby, lekbyNow);
    expect(station?.name).toBe("Lekby");
    expect(part?.part).toBe("del av Lekby");
    expect(part?.approve).toEqual({ action: "approve", client_id: "tkl-lekby", places: ["lokstall"] });
    expect(part?.refuse).toEqual({ action: "refuse", client_id: "tkl-lekby", places: ["lokstall"] });
    expect(station?.approve).toEqual({ action: "approve", client_id: "tkl-lekby", places: ["p4"] });
  });

  it("keeps the station when the part is refused, and lets the part be approved after all", () => {
    const refused: Client = {
      ...lekby,
      status: "approved",
      places: ["p4"],
      wanted: [
        { place: "p4", status: "approved", part: null, part_of: null },
        { place: "lokstall", status: "refused", part: "lokstall", part_of: "p4" },
      ],
    };
    const html = renderToStaticMarkup(<KlienterPage admin now={lekbyNow} clients={[refused]} navigate={() => undefined} />);
    expect(html).toContain("Återkalla");
    expect(html).toContain("del av Lekby · Nekad");
    expect(html).toContain('aria-label="Godkänn Lekby lokstall"');
    expect(html).not.toContain('aria-label="Neka Lekby lokstall"');
    expect(html).not.toContain('aria-label="Godkänn Lekby"');
    const [station, part] = wantedRows(refused, lekbyNow);
    expect([station?.said, station?.approve, part?.said]).toEqual(["Godkänd", null, "Nekad"]);
  });

  it("puts a TKL with a driftplats still waiting under Väntar", () => {
    const half: Client = { ...lekby, status: "approved", wanted: [{ place: "p4", status: "approved", part: null, part_of: null }, { place: "lokstall", status: "waiting", part: "lokstall", part_of: "p4" }] };
    expect(waits(half)).toBe(true);
    expect(waits({ ...half, wanted: [{ place: "p4", status: "approved", part: null, part_of: null }] })).toBe(false);
    const html = renderToStaticMarkup(<KlienterPage admin now={lekbyNow} clients={[half]} group="waiting" navigate={() => undefined} />);
    expect(html).toContain("<b>TKL Lekby</b>");
  });
});

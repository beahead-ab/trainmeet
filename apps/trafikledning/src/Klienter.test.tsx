import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Client } from "./api";
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

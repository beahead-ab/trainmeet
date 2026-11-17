import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Client } from "./api";
import { ExitQuestions, KlienterPage } from "./Klienter";

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

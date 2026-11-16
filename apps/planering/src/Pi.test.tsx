import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { KopplaPi } from "./Versioner";

describe("Koppla en Pi (SYNK-02)", () => {
  it("lists the Pis that follow the meet, and gives the administrator a code", () => {
    const follower = { hub_id: "hub-1a2b3c", hub_name: "Pi:n hemma", software: "0.1.0", linked: "2026-11-16T04:00:00Z", heard: null };
    const shown = renderToStaticMarkup(<KopplaPi admin meet="varnamo" initial={[follower]} />);
    expect(shown).toContain("Pi:n hemma · Hubben 0.1.0 · hörd aldrig");
    expect(shown).toContain(">Koppla en Pi</button>");
    expect(shown).toContain(">Koppla bort</button>");
    const looking = renderToStaticMarkup(<KopplaPi admin={false} meet="varnamo" initial={[]} />);
    expect(looking).toContain("Ingen Pi följer träffen än.");
    expect(looking).not.toContain("Koppla en Pi</button>");
  });
});

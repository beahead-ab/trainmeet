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

  it("says where the meet's home is when it is on the Pi, and offers to take it back (H35)", () => {
    const home = { meet: "varnamo", hub_id: "hub-1a2b3c", hub_name: "Låtsas-Pi", here: false, generation: 1, since: null };
    const away = renderToStaticMarkup(<KopplaPi admin meet="varnamo" initial={[]} initialHome={home} />);
    expect(away).toContain("Träffens hem är Låtsas-Pi");
    expect(away).toContain("Här kan du titta, inte ändra.");
    expect(away).toContain("Ta tillbaka hem hit …");
    expect(away).not.toContain("Koppla en Pi");
  });
});

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ValjTraff } from "./ValjTraff";
import { KopplaPi } from "./Versioner";

describe("Koppla en Pi (SYNK-02)", () => {
  it("lists the Pis that follow the meet, and gives the administrator a code", () => {
    const follower = { hub_id: "hub-1a2b3c", hub_name: "Pi:n hemma", software: "0.1.0", linked: "2026-11-16T04:00:00Z", heard: null };
    const shown = renderToStaticMarkup(<KopplaPi admin meet="varnamo" initial={[follower]} />);
    expect(shown).toContain("Pi:n hemma · Hubben 0.1.0 · hörd aldrig");
    expect(shown).toContain(">Ge en kod</button>");
    expect(shown).toContain("Logga in och välj träff");
    expect(shown).toContain(">Koppla bort</button>");
    const looking = renderToStaticMarkup(<KopplaPi admin={false} meet="varnamo" initial={[]} />);
    expect(looking).toContain("Ingen Pi följer träffen än.");
    expect(looking).not.toContain("Ge en kod</button>");
  });

  it("says where the meet's home is when it is on the Pi, and offers to take it back (H35)", () => {
    const home = { meet: "varnamo", hub_id: "hub-1a2b3c", hub_name: "Låtsas-Pi", here: false, generation: 1, since: null };
    const away = renderToStaticMarkup(<KopplaPi admin meet="varnamo" initial={[]} initialHome={home} />);
    expect(away).toContain("Träffens hem är Låtsas-Pi");
    expect(away).toContain("Här kan du titta, inte ändra.");
    expect(away).toContain("Ta tillbaka hem hit …");
    expect(away).not.toContain("Ge en kod");
  });

  it("lets the one logged in choose the meet for the Pi that asks, and shows which Pi it is (F16)", () => {
    const attempt = { hub_name: "Pi:n i hallen", software: "0.1.0", address: "http://pi.local", expires: "2026-11-23T21:00:00Z", meets: [{ meet: "varnamo", name: "Värnamo Moduldagar", first_date: "2026-10-30" }], chosen: null };
    const shown = renderToStaticMarkup(<ValjTraff initial={{ attempt }} />);
    expect(shown).toContain("<b>Pi:n i hallen</b>");
    expect(shown).toContain(" · Hubben 0.1.0 · http://pi.local");
    expect(shown).toContain("Välj bara om du själv har börjat på just den Pi:n nyss.");
    expect(shown).toContain("<b>Värnamo Moduldagar</b>");
    expect(shown).toContain(">Koppla hit</button>");
    const none = renderToStaticMarkup(<ValjTraff initial={{ attempt: { ...attempt, meets: [] } }} />);
    expect(none).toContain("Du planerar ingen träff här.");
    const login = renderToStaticMarkup(<ValjTraff initial={{ login: true }} />);
    expect(login).toContain('href="/api/hub/id/login?next=%2Fplanering%3Fkoppla%3Dpi&amp;lang=sv">Logga in med TrainMeet ID</a>');
    expect(renderToStaticMarkup(<ValjTraff withId={false} initial={{ login: true }} />)).toContain("Logga in med hubbens PIN-kod");
    expect(renderToStaticMarkup(<ValjTraff initial={{ gone: "Kopplingen har gått ut." }} />)).toContain("Kopplingen har gått ut.");
  });
});

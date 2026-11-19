import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Shell, switcherApps, type ShellProps } from "./App";
import { routeFor } from "./routes";
import { LIST, SESSION } from "./testdata";

const LIBRARIES = [
  { id: "mine", name: "Mitt modulbibliotek", kind: "mine" as const, club: null, may_add: true },
  { id: "club:5a1f0c3e-89a0-4d2b-9e1f-7a6b5c4d3e2f", name: "Provklubben", kind: "club" as const, club: "5a1f0c3e-89a0-4d2b-9e1f-7a6b5c4d3e2f", may_add: true },
  { id: "all", name: "Alla moduler jag ser", kind: "all" as const, club: null, may_add: false },
];

function render(overrides: Partial<ShellProps> = {}): string {
  return renderToStaticMarkup(
    <Shell
      route={routeFor("/moduler")}
      host="test.cad.trainmeet.app"
      session={SESSION}
      version={{ product: "TrainMeet CAD", version: "0.1.0", commit: "abcdef1234", pr: 301, title: "CAD", built: null }}
      libraries={LIBRARIES}
      library="mine"
      scale="H0"
      list={LIST}
      {...overrides}
    />,
  );
}

describe("the header", () => {
  it("has the sign, CAD in dots, the library with its chooser and the three tabs", () => {
    const html = render();
    expect(html).toContain('aria-label="TrainMeet CAD"');
    expect(html).toContain('class="tm-skylt"');
    expect(html).toContain("Mitt modulbibliotek</option>");
    expect(html).toContain("Provklubben</option>");
    expect(html).toContain("Alla moduler jag ser</option>");
    expect(html).toMatch(/<select class="cad-skala">.*H0.*N.*0/);
    for (const tab of ["Moduler", "Anläggningar", "Gavelprofiler"]) expect(html).toContain(`>${tab}</a>`);
    expect(html).toContain('href="/moduler" aria-current="page"');
  });

  it("then the token balance, the app switcher and the account", () => {
    const html = render();
    expect(html).toContain('<a class="cad-saldo" href="https://test.id.trainmeet.app/tokens">◎ 86 tokens</a>');
    expect(html).toContain('aria-label="Byt app"');
    expect(html).toContain('aria-label="PA, Kontomenyn, Provkonto A"');
    expect(html).toContain("Provinloggning i testmiljön");
    expect(html).toContain("Hjälp och fel");
    expect(html).toContain("Logga ut");
    expect(html).toContain("TrainMeet CAD · Version 0.1.0");
  });

  it("puts CAD in the app switcher, with the test environment's addresses", () => {
    const apps = switcherApps("test.cad.trainmeet.app", ["hub", "catalog", "id"]);
    expect(apps.map((a) => a.product)).toEqual(["HUB", "CAD", "CATALOG", "ID"]);
    expect(apps.find((a) => a.product === "CATALOG")?.href).toBe("https://test.catalog.trainmeet.app");
    expect(apps.find((a) => a.product === "CAD")?.href).toBeUndefined();
    expect(switcherApps("cad.trainmeet.app").every((a) => a.href === undefined)).toBe(true);
  });
});

describe("logging in", () => {
  it("lists the trial accounts", () => {
    const html = render({ session: { ...SESSION, account: null }, trialAccounts: [SESSION.account!] });
    expect(html).toContain("Logga in i TrainMeet CAD");
    expect(html).toContain("Välj ett provkonto");
    expect(html).toContain(">Provkonto A</button>");
  });

  it("goes to TrainMeet ID and back to the page, never to another site", () => {
    const id = { ...SESSION, account: null, login: "id" as const };
    const html = render({ route: routeFor("/logga-in"), session: id, search: "?next=%2Fgavelprofiler&inloggning=fel" });
    expect(html).toContain('href="/api/cad/1/id/login?next=%2Fgavelprofiler&amp;lang=sv"');
    expect(html).toContain('role="alert"');
    const elsewhere = render({ route: routeFor("/logga-in"), session: id, search: "?next=%2F%2Felak.example" });
    expect(elsewhere).toContain('href="/api/cad/1/id/login?next=%2Fmoduler&amp;lang=sv"');
  });
});

describe("Anläggningar", () => {
  it("is an empty page that says it comes in part d", () => {
    const html = render({ route: routeFor("/anlaggningar") });
    expect(html).toContain("Anläggningarna kommer i nästa steg");
    expect(html).toContain("Kommer i del d av CAD");
    expect(html).toContain('href="/anlaggningar" aria-current="page"');
  });
});

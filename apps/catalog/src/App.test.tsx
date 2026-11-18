import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Session } from "./api";
import { helpHref, Shell, switcherApps, type ShellProps } from "./App";
import { text } from "./i18n";

const account = { id: "8a3e1f0c-1111-5222-8333-944455556666", name: "Provkonto A", initials: "PA" };
const version = { product: "TrainMeet Catalog" as const, version: "0.1.0", commit: "abcdef1234", pr: 101, title: "Grunden", built: null };

function render(overrides: Partial<ShellProps> = {}): string {
  const session: Session = { account: null, login: "trial", simulated_tags: false, share_url: null, help_url: null, apps: null, tokens: null, tokens_url: null, logout_url: null };
  return renderToStaticMarkup(
    <Shell page="vehicles" language="sv" host="test.catalog.trainmeet.app" session={session} version={version} offline={false} fleet={false} {...overrides} />,
  );
}

describe("an empty Catalog", () => {
  it("shows its version and the change it came from", () => {
    const html = render();
    expect(html).toContain("TrainMeet Catalog · Version 0.1.0");
    expect(html).toContain('href="https://github.com/beahead-ab/trainmeet/pull/101"');
    expect(html).toContain("abcdef1");
  });

  it("has three tabs, the phone's bottom menu and the address in the header", () => {
    const html = render();
    for (const label of ["Fordon", "Träffar", "Förebilder", "Blippa"]) expect(html).toContain(`>${label}<`);
    expect(html).toContain('href="/fordon" aria-current="page"');
    expect(html).toContain("test.catalog.trainmeet.app");
    expect(html).toContain('aria-label="TrainMeet Catalog"');
  });

  it("asks a visitor to log in, and shows the empty fleet to the one logged in", () => {
    expect(render()).toContain("Logga in för att se din vagnpark.");
    const html = render({ session: { account, login: "trial", simulated_tags: false, share_url: null, help_url: null, apps: null, tokens: null, tokens_url: null, logout_url: null } });
    expect(html).toContain("Vagnparken · Provkonto A");
    expect(html).toContain("Vagnparken är tom.");
    expect(html).toContain('aria-label="PA, Kontomenyn, Provkonto A"');
    expect(html).toContain("Provinloggning i testmiljön");
    expect(html).toContain("Hjälp och fel");
    expect(html).toContain("Logga ut");
  });

  it("lists the trial accounts on the login page", () => {
    const html = render({ page: "login", trialAccounts: [account] });
    expect(html).toContain("Välj ett provkonto");
    expect(html).toContain("Provkonto A");
  });

  it("logs in with TrainMeet ID and comes back to the page one came from", () => {
    const id: Session = { account: null, login: "id", simulated_tags: false, share_url: null, help_url: null, apps: null, tokens: null, tokens_url: null, logout_url: null };
    const html = render({ page: "login", session: id, search: "?next=%2Ft%2F04A1B2C3D4E5F6" });
    expect(html).toContain("Logga in med TrainMeet ID");
    expect(html).toContain('href="/api/catalog/1/id/login?next=%2Ft%2F04A1B2C3D4E5F6&amp;lang=sv"');
    expect(html).not.toContain('role="alert"');
    // Never to another site, and in the chosen language.
    const elsewhere = render({ page: "login", session: id, language: "en", search: "?next=%2F%2Felak.example" });
    expect(elsewhere).toContain('href="/api/catalog/1/id/login?next=%2Ffordon&amp;lang=en"');
    expect(elsewhere).toContain("Log in with TrainMeet ID");
  });

  it("says so when the login with ID did not go through", () => {
    const id: Session = { account: null, login: "id", simulated_tags: false, share_url: null, help_url: null, apps: null, tokens: null, tokens_url: null, logout_url: null };
    const html = render({ page: "login", session: id, search: "?inloggning=fel" });
    expect(html).toContain('role="alert"');
    expect(html).toContain("Det gick inte att logga in");
  });

  it("speaks English too, and offers Swedish back", () => {
    const html = render({ language: "en", session: { account, login: "trial", simulated_tags: false, share_url: null, help_url: null, apps: null, tokens: null, tokens_url: null, logout_url: null } });
    expect(html).toContain("Your fleet is empty.");
    expect(html).toContain(">Vehicles<");
    expect(html).toContain('lang="sv"');
    expect(html).toContain(">Svenska<");
  });

  it("says so when Catalog does not answer", () => {
    expect(render({ offline: true, session: null })).toContain('role="alert"');
  });

  it("has a skip link to the main area", () => {
    const html = render();
    expect(html).toContain('href="#innehall"');
    expect(html).toContain('<main id="innehall"');
  });
});

describe("the app switcher", () => {
  const t = (key: Parameters<typeof text>[1]) => text("sv", key);

  it("has the seven apps as drawn, with the Hub's and ID's test environments from the test environment", () => {
    const apps = switcherApps(t, "test.catalog.trainmeet.app");
    expect(apps.map((app) => app.product)).toEqual(["HUB", "TKL", "CAD", "CATALOG", "TMBOX", "LOKFÖRAREN", "ID"]);
    expect(apps.filter((app) => app.href).map((app) => app.href)).toEqual(["https://test.hub.trainmeet.app", "https://test.id.trainmeet.app"]);
  });

  it("links to nothing that is not built yet", () => {
    expect(switcherApps(t, "catalog.trainmeet.app").filter((app) => app.href)).toHaveLength(0);
  });

  it("shows only the apps the person has something in, when ID says so (ID11)", () => {
    const shown = switcherApps(t, "test.catalog.trainmeet.app", ["hub", "catalog", "id"]).map((app) => app.product);
    expect(shown).toEqual(["HUB", "CATALOG", "ID"]);
    expect(switcherApps(t, "test.catalog.trainmeet.app", null)).toHaveLength(7); // ID does not answer
  });

  it("sends Hjälp och fel to ID with the app, the page and the version (KONTO-06)", () => {
    const href = helpHref("https://test.id.trainmeet.app/hjalp", "/fordon/1", version);
    expect(href).toBe("https://test.id.trainmeet.app/hjalp?app=catalog&sida=%2Ffordon%2F1&version=0.1.0+%C2%B7+abcdef1");
  });
});

describe("the balance in the account menu (TOKEN-01)", () => {
  it("shows the tokens left in ID, with the way to Tokens there", () => {
    const withTokens: Session = { account, login: "id", simulated_tags: false, share_url: null, help_url: null, apps: null, tokens: 1176, tokens_url: "https://id.example/tokens", logout_url: null };
    const html = render({ session: withTokens });
    expect(html).toMatch(/<a id="tokens" href="https:\/\/id.example\/tokens">Tokens: 1.176 kvar<\/a>/);
    expect(render({ language: "en", session: withTokens })).toContain("Tokens: 1,176 left");
    expect(render({ session: { ...withTokens, tokens: null, tokens_url: null } })).not.toContain('id="tokens"');
  });
});

describe("a club's fleet (CAT-51, C39)", () => {
  const club = "0f0e0d0c-3333-4444-8555-966677778888";
  const session: Session = { account, login: "id", simulated_tags: false, share_url: "https://id.example/vagnparker/a", help_url: null, apps: null, tokens: null, tokens_url: null, logout_url: null };
  const fleets = [
    { owner: account.id, title: "Vagnparken · Provkonto A", right: "owner" as const, share_url: "https://id.example/vagnparker/a" },
    { owner: club, title: "Vagnparken · Västby MJK", right: "owner" as const, share_url: `https://id.example/vagnparker/${club}` },
  ];

  it("says whose fleet one works in, also with the owner's right", () => {
    const html = render({ session, fleets, working: club });
    expect(html).toContain("Du arbetar i Vagnparken · Västby MJK.");
    expect(html).toContain("Till min egen vagnpark");
    expect(render({ session, fleets, working: null })).not.toContain("Du arbetar i");
  });
});

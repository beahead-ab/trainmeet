import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ClubPage, FleetPage, Invitation, Meet, MeetPage, Session, TokenBalance } from "./api";
import { days, helpAbout, helpHref, Shell, switcherApps, type ShellProps } from "./App";
import { TEXTS } from "./i18n";
import { routeFor } from "./routes";

const kim = { id: "8a3e1f0c-1111-4222-8333-944455556666", name: "Kim Ek", initials: "KE", email: "kim@example.com" };
const sara = { id: "1b2c3d4e-2222-4333-8444-955566667777", name: "Sara Holm", initials: "SH" };
const loggedIn: Session = { account: kim, logout_url: null };
const club = { id: "0f0e0d0c-3333-4444-8555-966677778888", name: "Västby MJK", role: "admin" as const };
const at = "2026-11-09T10:00:00Z";

function render(overrides: Partial<ShellProps> = {}): string {
  return renderToStaticMarkup(
    <Shell route={{ page: "account" }} language="sv" host="test.id.trainmeet.app" session={loggedIn} offline={false} {...overrides} />,
  );
}

const invitation: Invitation = {
  id: "aaaaaaaa-4444-4555-8666-977788889999",
  resource: { kind: "club", id: club.id },
  role: "member",
  title: "Västby MJK",
  sent_to: "sara@example.com",
  sent_by: { id: kim.id, name: "Kim Ek", initials: "KE" },
  state: "waiting",
  at,
};

describe("TrainMeet ID's web app", () => {
  it("asks the person to log in with the code, and comes back to the same page", () => {
    const html = render({ session: { account: null, logout_url: null }, route: { page: "club", id: club.id }, path: `/klubbar/${club.id}` });
    expect(html).toContain("Logga in");
    expect(html).toContain(`href="/api/id/1/login?next=%2Fklubbar%2F${club.id}&amp;lang=sv"`);
    expect(html).not.toContain("Klubbar</a>"); // no tabs before logging in
  });

  it("says so when the login did not go through", () => {
    const html = render({ session: { account: null, logout_url: null }, search: "?inloggning=fel" });
    expect(html).toContain('role="alert"');
  });

  it("shows the account with its verified address, the clubs and the waiting invitations", () => {
    const html = render({ data: { clubs: [club], invitations: [invitation] } });
    for (const tab of ["Konto", "Klubbar", "Träffar", "Tokens"]) expect(html).toContain(`>${tab}</a>`); // KONTO-38
    expect(html).toContain("kim@example.com · verifierad");
    expect(html).toContain(`href="/klubbar/${club.id}"`);
    expect(html).toContain("Administratör");
    expect(html).toContain("Klubb: Västby MJK");
    expect(html).toContain("från Kim Ek");
    expect(html).toContain("Ja, gå med");
    expect(html).toContain("Tokens betalar AI och lagring i hela TrainMeet.");
  });

  it("shows the person's balance and the club's, with the free quota and the bought tokens (#79)", () => {
    const tokens: TokenBalance[] = [
      { owner: { kind: "person", id: kim.id }, title: "Kim Ek", free_left: 64, free_monthly: 100, bought: 1500, reserved: 12, available: 1564, month: "2026-11", own_ai: null },
      { owner: { kind: "club", id: club.id }, title: "Västby MJK", free_left: 300, free_monthly: 300, bought: 0, reserved: 0, available: 300, month: "2026-11", own_ai: null },
    ];
    const html = render({ route: { page: "tokens" }, data: { tokens } });
    expect(html).toContain("Ditt saldo");
    expect(html).toContain("1\u00a0564 tokens");
    expect(html).toContain("64 av 100 gratis kvar den här månaden");
    expect(html).toContain("1\u00a0500 köpta, som inte förfaller");
    expect(html).toContain("12 reserverade just nu");
    expect(html).toContain("Klubben Västby MJK");
    expect(html).toContain(">300 tokens<");
    expect(html.match(/reserverade/g)?.length).toBe(1);
  });

  it("sells the packages in Stripe's test mode, for one's own balance and as the club's admin (TOKEN-02)", () => {
    const member = { id: "2f2e2d2c-3333-4444-8555-966677778888", name: "Grannklubben", role: "member" as const };
    const tokens: TokenBalance[] = [
      { owner: { kind: "person", id: kim.id }, title: "Kim Ek", free_left: 100, free_monthly: 100, bought: 0, reserved: 0, available: 100, month: "2026-11", own_ai: null },
      { owner: { kind: "club", id: club.id }, title: "Västby MJK", free_left: 300, free_monthly: 300, bought: 0, reserved: 0, available: 300, month: "2026-11", own_ai: null },
      { owner: { kind: "club", id: member.id }, title: "Grannklubben", free_left: 300, free_monthly: 300, bought: 0, reserved: 0, available: 300, month: "2026-11", own_ai: null },
    ];
    const shop = { mode: "test" as const, packages: [{ tokens: 500 as const, price_sek: 49 }, { tokens: 1500 as const, price_sek: 129 }, { tokens: 5000 as const, price_sek: 399 }] };
    const html = render({ route: { page: "tokens" }, data: { tokens, shop, clubs: [club, member] }, actions: { buy: async () => null }, search: "?kop=klart" });
    expect(html).toContain("Köp 500 för 49 kr");
    expect(html).toContain("Köp 1\u00a0500 för 129 kr");
    expect(html).toContain("Köp 5\u00a0000 för 399 kr");
    // Kim's own and Västby MJK, where Kim is admin; not the club where Kim is a member.
    expect(html.match(/Köp 500 för 49 kr/g)?.length).toBe(2);
    expect(html).toContain("Testläge: inga riktiga pengar dras.");
    expect(html).toContain("Tack! De köpta tokens kommer så snart betalningen är klar.");
    const closed = render({ route: { page: "tokens" }, data: { tokens, shop: { ...shop, mode: "off" }, clubs: [club] }, actions: { buy: async () => null } });
    expect(closed).not.toContain("Köp 500");
    expect(closed).toContain("Att köpa fler kommer snart.");
  });

  it("connects the account's own AI, the first choice, for one's own balance and the club's admin (TOKEN-03)", () => {
    const tokens: TokenBalance[] = [
      { owner: { kind: "person", id: kim.id }, title: "Kim Ek", free_left: 100, free_monthly: 100, bought: 0, reserved: 0, available: 100, month: "2026-11", own_ai: "en-modell" },
      { owner: { kind: "club", id: club.id }, title: "Västby MJK", free_left: 300, free_monthly: 300, bought: 0, reserved: 0, available: 300, month: "2026-11", own_ai: null },
    ];
    const html = render({ route: { page: "tokens" }, data: { tokens, clubs: [{ ...club, role: "member" }] }, actions: { connectOwnAi: async () => null, removeOwnAi: async () => null } });
    expect(html).toContain("Egen AI: en-modell");
    expect(html).toContain(">Koppla ur</button>");
    expect(html).toContain("Ändra egen AI");
    expect(html).toContain("Lämna tom för att behålla nyckeln");
    // A member does not change the club's own AI.
    expect(html).not.toContain("Koppla in egen AI");
    const admin = render({ route: { page: "tokens" }, data: { tokens, clubs: [club] }, actions: { connectOwnAi: async () => null, removeOwnAi: async () => null } });
    expect(admin).toContain("Koppla in egen AI");
    expect(admin).toContain("Claudes eget API");
  });

  it("shows the club's members, and only the admin may invite and remove", () => {
    const page: ClubPage = {
      club,
      members: [
        { person: { id: kim.id, name: "Kim Ek", initials: "KE" }, role: "admin", since: at },
        { person: sara, role: "member", since: at },
      ],
      invitations: [{ ...invitation, sent_to: "m***@example.com" }],
    };
    const admin = render({ route: { page: "club", id: club.id }, data: { club: page } });
    expect(admin).toContain("Medlemmar · 2");
    expect(admin).toContain('aria-label="Ta bort Sara Holm"');
    expect(admin).toContain("Gå ur klubben");
    expect(admin).toContain("m***@example.com");
    expect(admin).toContain("Skicka inbjudan");
    expect(admin).not.toContain("kim@example.com · verifierad");

    const member = render({
      route: { page: "club", id: club.id },
      session: { account: { ...kim, id: sara.id, name: "Sara Holm" }, logout_url: null },
      data: { club: { ...page, club: { ...club, role: "member" }, invitations: [] } },
    });
    expect(member).not.toContain("Skicka inbjudan");
    expect(member).not.toContain("Ta bort Kim Ek");
    expect(member).toContain("Gå ur klubben");
  });

  it("shares the fleet to look at or to edit, and stops sharing", () => {
    const fleet: FleetPage = {
      owner: { kind: "fleet", id: kim.id },
      title: "Vagnparken · Kim Ek",
      grants: [{ id: "bbbbbbbb-5555-4666-8777-988899990000", person: sara, role: "editor", resource: { kind: "fleet", id: kim.id }, at }],
      invitations: [],
    };
    const html = render({ route: { page: "fleet", id: kim.id }, data: { fleet } });
    expect(html).toContain("Dela vagnparken");
    expect(html).toContain("Vagnparken · Kim Ek");
    expect(html).toContain('aria-label="Sluta dela med Sara Holm"');
    const viewer = html.match(/<input[^>]*value="viewer"[^>]*>/)?.[0] ?? "";
    expect(viewer).toContain("checked"); // to look at is the default
    expect(html.match(/<input[^>]*value="editor"[^>]*>/)?.[0]).not.toContain("checked");
    expect(html).toContain(">Redigera<");
  });

  it("speaks English too", () => {
    const html = render({ language: "en", data: { clubs: [], invitations: [] } });
    expect(html).toContain("My account");
    expect(html).toContain("You are not in a club yet.");
    expect(html).toContain('lang="sv"');
  });

  it("has every text in both languages", () => {
    expect(Object.keys(TEXTS.en).sort()).toEqual(Object.keys(TEXTS.sv).sort());
  });

  it("finds the page from the address, also from a mail's link", () => {
    expect(routeFor("/")).toEqual({ page: "account" });
    expect(routeFor("/inbjudningar")).toEqual({ page: "invitations" });
    expect(routeFor(`/klubbar/${club.id}`)).toEqual({ page: "club", id: club.id });
    expect(routeFor(`/vagnparker/${kim.id}/`)).toEqual({ page: "fleet", id: kim.id });
    expect(routeFor("/klubbar/inte-ett-id")).toEqual({ page: "missing" });
    expect(routeFor(`/traffar/${club.id}`)).toEqual({ page: "meet", id: club.id });
  });
});

describe("the meets in ID (ID10)", () => {
  const autumn: Meet = { id: "cccccccc-6666-4777-8888-999900001111", club: club.id, club_name: "Västby MJK", name: "Höstträffen", starts_on: "2026-11-13", ends_on: "2026-11-15", roles: ["organizer"], club_admin: true };
  const jon = { id: "dddddddd-7777-4888-8999-000011112222", name: "Jon Eriksson", initials: "JE" };
  const grant = (id: string, person: typeof jon, role: string) => ({ id, person, role: role as "organizer", resource: { kind: "meet" as const, id: autumn.id }, at });
  const page = (change: Partial<MeetPage> = {}): MeetPage => ({
    meet: autumn,
    grants: [grant("eeeeeeee-0000-4000-8000-000000000001", { id: kim.id, name: "Kim Ek", initials: "KE" }, "organizer"), grant("eeeeeeee-0000-4000-8000-000000000002", jon, "loco_lead")],
    may_give: ["dispatcher", "loco_lead"],
    may_change: true,
    may_remove: false,
    members: [{ id: kim.id, name: "Kim Ek", initials: "KE" }, jon, sara],
    ...change,
  });

  it("writes a meet's days as one stretch", () => {
    expect(days(autumn, "sv")).toBe("13–15 november 2026");
    expect(days(autumn, "en")).toMatch(/^13\s?–\s?15 November 2026$/); // ICU spaces it in English
    expect(days({ starts_on: "2026-10-31", ends_on: "2026-11-01" }, "sv")).toBe("31 oktober–1 november 2026");
    expect(days({ starts_on: "2026-11-14", ends_on: "2026-11-14" }, "sv")).toBe("14 november 2026");
  });

  it("lists the club's meets with the person's roles, and the admin makes a new one", () => {
    const clubPage: ClubPage = { club, members: [{ person: { id: kim.id, name: "Kim Ek", initials: "KE" }, role: "admin", since: at }], invitations: [], meets: [autumn] };
    const admin = render({ route: { page: "club", id: club.id }, data: { club: clubPage } });
    expect(admin).toContain("Klubbens träffar");
    expect(admin).toContain(`href="/traffar/${autumn.id}"`);
    expect(admin).toContain("13–15 november 2026");
    expect(admin).toContain(">Arrangör<");
    expect(admin).toContain("Ny träff");
    expect(admin).toContain('type="date"');
    const member = render({ route: { page: "club", id: club.id }, data: { club: { ...clubPage, club: { ...club, role: "member" } } } });
    expect(member).not.toContain("Ny träff");

    const tab = render({ route: { page: "meets" }, data: { meets: [autumn] } });
    expect(tab).toContain("Västby MJK · 13–15 november 2026");
    expect(render({ route: { page: "meets" }, data: { meets: [] } })).toContain("Inga träffar än. Klubbens administratör lägger till dem under Klubbar.");
  });

  it("lets the organizer hand out Trafikledare and Lokledare to the club's members", () => {
    const html = render({ route: { page: "meet", id: autumn.id }, data: { meet: page() } });
    expect(html).toContain("Träff · Västby MJK");
    expect(html).toContain("Roller på Höstträffen");
    expect(html).toContain(">Lokledare<");
    expect(html).toContain("Dela ut en roll");
    expect(html).toContain(">Jon Eriksson · Västby MJK</option>");
    expect(html.match(/<input[^>]*value="dispatcher"[^>]*>/)?.[0]).toContain("checked");
    expect(html).not.toContain('value="remote_clearer"');
    expect(html).toContain('aria-label="Ändra rollerna för Jon Eriksson"');
    expect(html).toContain("Ändra träffen");
    expect(html).not.toContain("Ta bort träffen"); // only the club's admin
  });

  it("shows a member the roles, and nothing to hand out", () => {
    const html = render({
      route: { page: "meet", id: autumn.id },
      session: { account: { ...kim, id: sara.id, name: "Sara Holm" }, logout_url: null },
      data: { meet: page({ meet: { ...autumn, roles: [] }, may_give: [], may_change: false, members: [] }) },
    });
    expect(html).toContain("Roller på Höstträffen");
    expect(html).not.toContain("Dela ut en roll");
    expect(html).not.toContain("Ändra rollerna");
    expect(html).not.toContain("Ändra träffen");
    expect(html).toContain("Träffen i Hubben");
  });
});

describe("Hjälp och fel and the app switcher (KONTO-06, KONTO-38)", () => {
  const t = (key: keyof typeof TEXTS.sv) => TEXTS.sv[key];

  it("asks for the text, and says what goes with it and where the answer comes", () => {
    const html = render({ route: { page: "help" }, search: "?app=catalog&sida=%2Ffordon&version=0.1.0+%C2%B7+abcdef1" });
    expect(html).toContain("Hjälp och fel");
    expect(html).toContain("svaret kommer till kim@example.com");
    expect(html).toContain("Skickas med: TrainMeet Catalog · sidan /fordon · version 0.1.0 · abcdef1");
    expect(html).toContain("Jag behöver hjälp");
    expect(html).toContain("Något blev fel");
    expect(html).toContain('for="hjalp-text"');
  });

  it("reads the app from the link, and never an app that does not exist", () => {
    expect(helpAbout("?app=catalog&sida=%2Ffordon&version=1")).toEqual({ app: "catalog", page: "/fordon", version: "1" });
    expect(helpAbout("?app=okand&version=fel", "abc1234")).toEqual({ app: "id", page: "", version: "abc1234" });
    expect(helpHref("/klubbar")).toBe("/hjalp?app=id&sida=%2Fklubbar");
  });

  it("shows only the apps the person has something in", () => {
    const shown = switcherApps(t, "test.id.trainmeet.app", ["catalog", "driver", "id"]).map((app) => app.product);
    expect(shown).toEqual(["CATALOG", "LOKFÖRAREN", "ID"]);
    expect(switcherApps(t, "test.id.trainmeet.app", [])).toHaveLength(6);
  });
});

describe("removing the account (KONTO-31, ID7, ID13)", () => {
  const plan = { clubs_removed: [{ id: club.id, name: "Kims egen bana" }], clubs_blocking: [] };

  it("offers the file first, says what goes, and asks for the word", () => {
    const html = render({ route: { page: "remove" }, data: { removal: plan } });
    expect(html).toContain("Ta bort mitt konto");
    expect(html).toContain('href="/api/id/1/account/export" download=""');
    expect(html).toContain("Klubbarna där du är ensam tas också bort, med sina träffar och sin vagnpark: Kims egen bana.");
    expect(html).toContain("avgörs i frågan om GDPR");
    expect(html).toContain("Skriv TA BORT för att bekräfta");
    expect(html.match(/<button[^>]*type="submit"[^>]*>Ta bort mitt konto/)?.[0]).toContain("disabled");
  });

  it("stops while the person is a club's only administrator among others", () => {
    const html = render({ route: { page: "remove" }, data: { removal: { clubs_removed: [], clubs_blocking: [{ id: club.id, name: "Västby MJK" }] } } });
    expect(html).toContain("Ge administratörsrollen till någon annan först i: Västby MJK.");
    expect(html).toContain('role="alert"');
  });

  it("lets the admin give the role to a member, and says when the account is gone", () => {
    const page: ClubPage = {
      club,
      members: [
        { person: { id: kim.id, name: "Kim Ek", initials: "KE" }, role: "admin", since: at },
        { person: sara, role: "member", since: at },
      ],
      invitations: [],
    };
    const html = render({ route: { page: "club", id: club.id }, data: { club: page } });
    expect(html).toContain('aria-label="Gör Sara Holm till administratör"');
    expect(html).not.toContain("Gör Kim Ek");
    const gone = render({ session: { account: null, logout_url: null, apps: [] }, search: "?borttaget=1" });
    expect(gone).toContain("Ditt konto är borttaget");
  });
});

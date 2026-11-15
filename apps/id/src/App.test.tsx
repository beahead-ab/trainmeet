import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ClubPage, FleetPage, Invitation, Meet, MeetPage, Session } from "./api";
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
    expect(html).toContain("Saldot och köpen av tokens kommer med Tokens.");
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
  const autumn: Meet = { id: "cccccccc-6666-4777-8888-999900001111", club: club.id, club_name: "Västby MJK", name: "Höstträffen", starts_on: "2026-11-13", ends_on: "2026-11-15", roles: ["organizer"] };
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

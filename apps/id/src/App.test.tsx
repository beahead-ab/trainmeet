import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ClubPage, FleetPage, Invitation, Session } from "./api";
import { Shell, type ShellProps } from "./App";
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
  });
});

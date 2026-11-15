// ID's API with the types generated from the contracts (#67,
// contracts/id.openapi.json -> contracts/id.d.ts). Nothing here is typed by hand.
import type { components } from "../../../contracts/id";

type Schemas = components["schemas"];
export type Session = Schemas["trainmeet.id-1.session"];
export type Account = Schemas["trainmeet.id-1.account"];
export type Club = Schemas["trainmeet.id-1.club"];
export type ClubPage = Schemas["trainmeet.id-1.club-page"];
export type Member = Schemas["trainmeet.id-1.member"];
export type Invitation = Schemas["trainmeet.id-1.invitation"];
export type FleetPage = Schemas["trainmeet.id-1.fleet-page"];
export type Grant = Schemas["trainmeet.id-1.grant"];
export type Problem = Schemas["trainmeet.id-1.problem"];
export type ProblemCode = Problem["code"];
export type Role = Invitation["role"];
export type FleetRole = Schemas["trainmeet.id-1.fleet-invite"]["role"];
export type Meet = Schemas["trainmeet.id-1.meet"];
export type MeetPage = Schemas["trainmeet.id-1.meet-page"];
export type MeetRole = Schemas["trainmeet.id-1.meet-grant"]["role"];
export type NewMeet = Schemas["trainmeet.id-1.new-meet"];
export type HelpRequest = Schemas["trainmeet.id-1.help-request"];
export type AppKey = HelpRequest["app"];
export type Version = Schemas["trainmeet.id-1.version"];

/** ID said no, with a code the web app has a text for, or something else went wrong. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: ProblemCode | null,
    readonly problem: string | null,
  ) {
    super(`ID svarade ${status}${code ? ` (${code})` : ""}`);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.headers = { ...init.headers, "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const response = await fetch(path, init);
  if (!response.ok) {
    let code: ProblemCode | null = null;
    let message: string | null = null;
    try {
      const problem = (await response.json()) as Partial<Problem>;
      code = typeof problem.code === "string" ? problem.code : null;
      message = typeof problem.message === "string" ? problem.message : null;
    } catch {
      code = null;
    }
    throw new ApiError(response.status, code, message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const A = "/api/id/1";

/** The login: the browser goes to Keycloak itself, and comes back to `next`. */
export function loginHref(next: string, language: string): string {
  return `${A}/login?${new URLSearchParams({ next, lang: language })}`;
}

export const api = {
  session: () => call<Session>("GET", `${A}/session`),
  logOut: () => call<Session>("DELETE", `${A}/session`),
  clubs: () => call<Club[]>("GET", `${A}/clubs`),
  createClub: (name: string) => call<Club>("POST", `${A}/clubs`, { name }),
  club: (id: string) => call<ClubPage>("GET", `${A}/clubs/${id}`),
  inviteToClub: (id: string, email: string) => call<Invitation>("POST", `${A}/clubs/${id}/invitations`, { email }),
  removeMember: (club: string, person: string) => call<ClubPage | undefined>("DELETE", `${A}/clubs/${club}/members/${person}`),
  fleet: (owner: string) => call<FleetPage>("GET", `${A}/fleets/${owner}`),
  inviteToFleet: (owner: string, email: string, role: FleetRole) =>
    call<Invitation>("POST", `${A}/fleets/${owner}/invitations`, { email, role }),
  removeGrant: (grant: string) => call<{ id: string }>("DELETE", `${A}/grants/${grant}`),
  invitations: () => call<Invitation[]>("GET", `${A}/invitations`),
  answer: (invitation: string, accept: boolean) => call<Invitation>("POST", `${A}/invitations/${invitation}/answer`, { accept }),
  withdraw: (invitation: string) => call<{ id: string }>("DELETE", `${A}/invitations/${invitation}`),
  version: () => call<Version>("GET", "/api/version"),
  help: (request: HelpRequest) => call<{ sent: true }>("POST", `${A}/help`, request),
  meets: () => call<Meet[]>("GET", `${A}/meets`),
  meet: (id: string) => call<MeetPage>("GET", `${A}/meets/${id}`),
  createMeet: (club: string, meet: NewMeet) => call<Meet>("POST", `${A}/clubs/${club}/meets`, meet),
  changeMeet: (id: string, meet: NewMeet) => call<MeetPage>("PUT", `${A}/meets/${id}`, meet),
  removeMeet: (id: string) => call<{ id: string }>("DELETE", `${A}/meets/${id}`),
  giveAtMeet: (id: string, person: string, role: MeetRole) => call<MeetPage>("POST", `${A}/meets/${id}/grants`, { person, role }),
};

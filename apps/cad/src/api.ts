// CAD's API with the types generated from the contracts (#89, contracts/cad.openapi.json ->
// contracts/cad.d.ts). Nothing here is typed by hand.
import type { components } from "../../../contracts/cad";

type Schemas = components["schemas"];
export type CadVersion = Schemas["trainmeet.cad-1.version"];
export type Session = Schemas["trainmeet.cad-1.session"];
export type Account = Schemas["trainmeet.cad-1.account"];
export type ClubChoice = NonNullable<Session["clubs"]>[number];
export type AppKey = NonNullable<Session["apps"]>[number];
export type Problem = Schemas["trainmeet.cad-1.problem"];
export type Library = Schemas["trainmeet.cad-1.library"];
export type ModuleList = Schemas["trainmeet.cad-1.module-list"];
export type ModuleBrief = ModuleList["modules"][number];
export type Module = Schemas["trainmeet.cad-1.module"];
export type NewModule = Schemas["trainmeet.cad-1.new-module"];
export type ModuleChange = Schemas["trainmeet.cad-1.module-change"];
export type ModuleEvent = Schemas["trainmeet.cad-1.module-event"];
export type VisibilityChange = Schemas["trainmeet.cad-1.visibility-change"];
export type ProfileList = Schemas["trainmeet.cad-1.profile-list"];
export type GableProfile = Schemas["trainmeet.cad-1.gable-profile"];
export type NewProfile = Schemas["trainmeet.cad-1.new-profile"];
export type Shape = Module["shape"];
export type Straight = Extract<Shape, { kind?: "straight" }>;
export type Curve = Extract<Shape, { kind?: "curve" }>;
export type Trapezoid = Extract<Shape, { kind?: "trapezoid" }>;
export type GableLabel = Module["gables"][number];
export type TrackGraph = Module["graph"];
export type GraphPiece = NonNullable<TrackGraph["pieces"]>[number];
export type Segment = GraphPiece["segments"][number];
export type Scale = Module["scale"];
export type Norm = NonNullable<GableProfile["norm"]>;
export type Visibility = Module["visibility"];

export const API = "/api/cad/1";
export const SCALES: Scale[] = ["H0", "N", "0"];

/** An answer that is not OK: the problem CAD gave, with its status. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem: Problem | null,
  ) {
    super(problem?.message ?? `CAD svarade ${status}.`);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { ...init.headers, "Content-Type": "application/json" };
  }
  const response = await fetch(path, init);
  if (!response.ok) {
    let problem: Problem | null = null;
    try {
      const found = (await response.json()) as Partial<Problem>;
      if (found && typeof found.code === "string" && typeof found.message === "string") problem = found as Problem;
    } catch {
      problem = null;
    }
    throw new ApiError(response.status, problem);
  }
  return (await response.json()) as T;
}

export const api = {
  version: () => call<CadVersion>("GET", "/api/version"),
  session: () => call<Session>("GET", `${API}/session`),
  logOut: () => call<Session>("DELETE", `${API}/session`),
  trialAccounts: () => call<Account[]>("GET", `${API}/trial/accounts`),
  trialLogIn: (account: string) => call<Session>("POST", `${API}/trial/login`, { account }),
  libraries: () => call<Library[]>("GET", `${API}/libraries`),
  modules: (library: string, scale: Scale, q = "") =>
    call<ModuleList>("GET", `${API}/modules?${new URLSearchParams({ library, scale, ...(q ? { q } : {}) })}`),
  module: (id: string, version?: number) =>
    call<Module>("GET", version ? `${API}/modules/${id}/versions/${version}` : `${API}/modules/${id}`),
  history: (id: string) => call<ModuleEvent[]>("GET", `${API}/modules/${id}/history`),
  create: (body: NewModule) => call<Module>("POST", `${API}/modules`, body),
  save: (id: string, body: ModuleChange) => call<Module>("PUT", `${API}/modules/${id}`, body),
  approve: (id: string, version: number) => call<Module>("POST", `${API}/modules/${id}/approve`, { version }),
  visibility: (id: string, body: VisibilityChange) => call<Module>("PUT", `${API}/modules/${id}/visibility`, body),
  remove: (id: string) => call<{ id: string }>("DELETE", `${API}/modules/${id}`),
  profiles: (scale: Scale) => call<ProfileList>("GET", `${API}/profiles?scale=${encodeURIComponent(scale)}`),
  newProfile: (body: NewProfile) => call<GableProfile>("POST", `${API}/profiles`, body),
};

/** TrainMeet ID's login, back to the page one came from. */
export function idLoginHref(next: string): string {
  return `${API}/id/login?${new URLSearchParams({ next, lang: "sv" })}`;
}

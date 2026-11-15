// Planeringens API (PLAN-37), with the types generated from the contracts
// (contracts/planning.py). Everyone may look; what changes something needs the login.
import { call, type MeetSummary } from "@trainmeet/hubben";
import type { components } from "../../../contracts/types";

type Schemas = components["schemas"];
export type { MeetSummary };
export type Draft = Schemas["trainmeet.planning-1.draft"];
export type NewMeet = Schemas["trainmeet.planning-1.new-meet"];
export type Check = Schemas["trainmeet.planning-1.check"];
export type Finding = Schemas["trainmeet.planning-1.check.Finding"];
export type Version = Schemas["trainmeet.planning-1.version"];

const MEETS = "/api/planering/1/meets";
const meet = (id: string) => `${MEETS}/${encodeURIComponent(id)}`;

export const planning = {
  meets: () => call<MeetSummary[]>(MEETS),
  create: (fresh: NewMeet) => call<Draft>(MEETS, fresh),
  draft: (id: string) => call<Draft>(meet(id)),
  check: (id: string) => call<Check>(`${meet(id)}/check`),
  versions: (id: string) => call<Version[]>(`${meet(id)}/versions`),
  publish: (id: string) => call<Version>(`${meet(id)}/versions`, {}),
};

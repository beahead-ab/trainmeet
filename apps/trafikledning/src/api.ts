// Trafikledningen's own part of Driftens API (contracts/drift.py) and Provbanan's, with the
// types generated from the contracts. Nothing here is typed by hand. Den här hubben, Nu, the
// clients and the meets the header needs come from @trainmeet/hubben.
import { call, DRIFT, Problem, type Client, type DriftEvent } from "@trainmeet/hubben";
import type { components } from "../../../contracts/types";

type Schemas = components["schemas"];
export { call, DRIFT, Problem, type Client, type DriftEvent, type HubInfo, type Joining, type MeetSummary, type Now, type Version, type Weekday } from "@trainmeet/hubben";
export type Leg = Schemas["trainmeet.drift-1.now.LegNow"];
export type Clearance = Schemas["trainmeet.drift-1.now.Clearance"];
export type Actor = Schemas["trainmeet.drift-1.event.Actor"];
export type Refusal = Schemas["trainmeet.drift-1.refusal"];
export type Automation = Schemas["trainmeet.drift-1.automation"];
export type AutomationSettings = Schemas["trainmeet.drift-1.automation-settings"];
export type AutomationPlace = Schemas["trainmeet.drift-1.automation.AutomationPlaceStatus"];
export type ClockControl = Schemas["trainmeet.drift-1.clock"];
export type Assign = Schemas["trainmeet.drift-1.assign"];
export type Approve = Schemas["trainmeet.drift-1.approve"];
export type Revoke = Schemas["trainmeet.drift-1.revoke"];
export type ShowView = Schemas["trainmeet.screen-1.show"];
export type ChangePlace = Schemas["trainmeet.drift-1.automation-place"];
export type Preview = Schemas["trainmeet.drift-1.preview"];
export type PreviewLeg = Schemas["trainmeet.drift-1.preview.PreviewLeg"];
export type PreviewCase = Schemas["trainmeet.drift-1.preview.PreviewCase"];
export type PreviewClients = Schemas["trainmeet.drift-1.preview-clients"];
export type Command = Schemas["trainmeet.station-1.command"];

export const api = {
  clock: (control: ClockControl) => call<DriftEvent>(`${DRIFT}/clock`, control),
  assign: (change: Assign) => call<Client>(`${DRIFT}/clients/assign`, change),
  approve: (change: Approve) => call<Client>(`${DRIFT}/clients/approve`, change),
  revoke: (change: Revoke) => call<Client>(`${DRIFT}/clients/revoke`, change),
  view: (change: ShowView) => call<Client>(`${DRIFT}/clients/view`, change),
  automation: () => call<Automation>(`${DRIFT}/automation`),
  setAutomation: (settings: AutomationSettings) => call<Automation>(`${DRIFT}/automation`, settings),
  changePlace: (change: ChangePlace) => call<Automation>(`${DRIFT}/automation/place`, change),
  log: (place: string | null, train: string | null) => {
    const query = new URLSearchParams();
    if (place) query.set("place", place);
    if (train) query.set("train", train);
    return call<DriftEvent[]>(`${DRIFT}/log?${query}`);
  },
  refusals: () => call<Refusal[]>(`${DRIFT}/refusals`),
};

const PROV = "/api/provbanan";

/** Provbanan: this browser's own run, in a cookie of its own (H51). */
export const provbanan = {
  /** The run, or null when this browser has none. */
  state: async (): Promise<Preview | null> => {
    try {
      return await call<Preview>(PROV);
    } catch (error) {
      if (error instanceof Problem && error.status === 404) return null;
      throw error;
    }
  },
  start: () => call<Preview>(`${PROV}/start`, { version: 1 }),
  clock: (control: ClockControl) => call<Preview>(`${PROV}/clock`, control),
  command: (command: Command) => call<Preview>(`${PROV}/command`, command),
  clients: () => call<PreviewClients>(`${PROV}/clients`),
  assign: (change: Assign) => call<PreviewClients>(`${PROV}/clients/assign`, change),
  approve: (change: Approve) => call<PreviewClients>(`${PROV}/clients/approve`, change),
  revoke: (change: Revoke) => call<PreviewClients>(`${PROV}/clients/revoke`, change),
};


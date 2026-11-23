// Trafikledningen's own part of Driftens API (contracts/drift.py) and Provbanan's, with the
// types generated from the contracts. Nothing here is typed by hand. Den här hubben, Nu, the
// clients and the meets the header needs come from @trainmeet/hubben.
import { call, DRIFT, Problem, type Client, type DriftEvent, type Joining } from "@trainmeet/hubben";
import type { components } from "../../../contracts/types";

type Schemas = components["schemas"];
export { call, cloudLoginAddress, DRIFT, hub, idLoginAddress, Problem, type AiService, type AiServiceChange, type Client, type CloudLink, type DriftEvent, type HubInfo, type Joining, type LetIn, type OneTimeCode, type MeetSummary, type Now, type Version, type Weekday, type UpdateStatus, type MeetWifi, type ClockSource, type ClockSourceChange, type TellurianSettings, type TellurianLogEntry, type WifiProfile, type WifiStatus } from "@trainmeet/hubben";
export type Leg = Schemas["trainmeet.drift-1.now.LegNow"];
export type Clearance = Schemas["trainmeet.drift-1.now.Clearance"];
export type Actor = Schemas["trainmeet.drift-1.event.Actor"];
export type Refusal = Schemas["trainmeet.drift-1.refusal"];
export type Automation = Schemas["trainmeet.drift-1.automation"];
export type AutomationSettings = Schemas["trainmeet.drift-1.automation-settings"];
export type AutomationPlace = Schemas["trainmeet.drift-1.automation.AutomationPlaceStatus"];
export type ClockControl = Schemas["trainmeet.drift-1.clock"];
export type NewDay = Schemas["trainmeet.drift-1.new-day"];
export type DaySettings = Schemas["trainmeet.drift-1.day-settings"];
export type DayStatus = Schemas["trainmeet.drift-1.day"];
export type LastJump = Schemas["trainmeet.drift-1.now.LastJump"];
export type PlacePhone = Schemas["trainmeet.drift-1.phone"];
export type MakeChange = Schemas["trainmeet.drift-1.make-change"];
export type Package = Schemas["trainmeet.meet-1"];
export type PlanVersion = Schemas["trainmeet.planning-1.version"];
export type SwitchVersion = Schemas["trainmeet.drift-1.switch"];
export type SwitchPreview = Schemas["trainmeet.drift-1.switch-preview"];
export type Assign = Schemas["trainmeet.drift-1.assign"];
export type Approve = Schemas["trainmeet.drift-1.approve"];
export type Refuse = Schemas["trainmeet.drift-1.refuse"];
export type Revoke = Schemas["trainmeet.drift-1.revoke"];
export type CoupleExit = Schemas["trainmeet.drift-1.couple-exit"];
export type ShowView = Schemas["trainmeet.screen-1.show"];
export type ChangePlace = Schemas["trainmeet.drift-1.automation-place"];
export type Preview = Schemas["trainmeet.drift-1.preview"];
export type PreviewLeg = Schemas["trainmeet.drift-1.preview.PreviewLeg"];
export type PreviewCase = Schemas["trainmeet.drift-1.preview.PreviewCase"];
export type PreviewClients = Schemas["trainmeet.drift-1.preview-clients"];
export type Command = Schemas["trainmeet.station-1.command"];
// Förare in Drift (TRAFIK-33): the drivers' side for Trafikledningen and the lokledare.
export type DriverOverview = Schemas["trainmeet.driver-1.overview"];
export type DriverRow = Schemas["trainmeet.driver-1.overview.DriverRow"];
export type ServiceOffer = Schemas["trainmeet.driver-1.overview.ServiceOffer"];
export type DriverMessage = Schemas["trainmeet.driver-1.overview.DriverMessage"];
export type DriverAlarm = Schemas["trainmeet.driver-1.overview.DriverAlarm"];
export type DriverSettings = Schemas["trainmeet.drift-1.driver-settings"];
export type ServiceRef = Schemas["trainmeet.drift-1.service"];
export type NowDriverMessage = Schemas["trainmeet.drift-1.now.NowDriverMessage"];
// Efter pappret (LOK-13, LOK-29): a service missing from the plan, which Trafikledningen decides.
export type PaperService = Schemas["trainmeet.driver-1.paper"];
export type PaperRow = Schemas["trainmeet.driver-1.paper.PaperRow"];

export const api = {
  clock: (control: ClockControl) => call<DriftEvent>(`${DRIFT}/clock`, control),
  newDay: (request: NewDay) => call<DriftEvent>(`${DRIFT}/day`, request),
  daySettings: (settings: DaySettings) => call<DayStatus>(`${DRIFT}/day/settings`, settings),
  phones: () => call<PlacePhone[]>(`${DRIFT}/phones`),
  setPhone: (change: PlacePhone) => call<PlacePhone[]>(`${DRIFT}/phones`, change),
  makeChange: (request: MakeChange) => call<DriftEvent>(`${DRIFT}/changes`, request),
  dropChange: (id: string) => call<DriftEvent>(`${DRIFT}/changes/${encodeURIComponent(id)}/drop`, {}),
  forceChange: (id: string) => call<DriftEvent>(`${DRIFT}/changes/${encodeURIComponent(id)}/force`, {}),
  package: () => call<Package>(`${DRIFT}/package`),
  // Versionsbyte (TRAFIK-03) and Lås upp (DRIFT-47).
  versions: (meet: string) => call<PlanVersion[]>(`/api/planering/1/meets/${encodeURIComponent(meet)}/versions`),
  switchPreview: (version: number) => call<SwitchPreview>(`${DRIFT}/switch/${version}`),
  switchVersion: (request: SwitchVersion) => call<DriftEvent>(`${DRIFT}/switch`, request),
  forceSwitch: () => call<DriftEvent>(`${DRIFT}/switch/force`, {}),
  callOffSwitch: () => call<DriftEvent>(`${DRIFT}/switch/call-off`, {}),
  unlock: () => call<DriftEvent>(`${DRIFT}/unlock`, {}),
  // Ta över i molnet (TRAFIK-08, H8, H9): only by hand, with the meet's name written.
  takeOver: (confirm: string) => call<DriftEvent>(`${DRIFT}/takeover`, { confirm }),
  assign: (change: Assign) => call<Client>(`${DRIFT}/clients/assign`, change),
  approve: (change: Approve) => call<Client>(`${DRIFT}/clients/approve`, change),
  /** Neka a driftplats, each on its own (TRAFIK-35). */
  refuse: (change: Refuse) => call<Client>(`${DRIFT}/clients/refuse`, change),
  revoke: (change: Revoke) => call<Client>(`${DRIFT}/clients/revoke`, change),
  coupleExit: (change: CoupleExit) => call<Client>(`${DRIFT}/clients/exit`, change),
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
  // Förare (TRAFIK-33, LOK-30): the drivers, hand out and take back, and the game's settings.
  drivers: () => call<DriverOverview>(`${DRIFT}/drivers/overview`),
  handOut: (driver: string, service: ServiceRef) => call<DriverOverview>(`${DRIFT}/drivers/hand-out`, { driver, service }),
  takeBack: (driver: string) => call<DriverOverview>(`${DRIFT}/drivers/take-back`, { driver }),
  driverSettings: (settings: DriverSettings) => call<DriverOverview>(`${DRIFT}/drivers/settings`, settings),
  clearAlarm: (service: ServiceRef) => call<DriverOverview>(`${DRIFT}/drivers/alarms/clear`, service),
  /** Godkänn: the paper becomes an extra train the stations see, marked (LOK-13). */
  approvePaper: (paper: string, trainNumber: string) => call<DriverOverview>(`${DRIFT}/drivers/paper/${encodeURIComponent(paper)}/approve`, { train_number: trainNumber.trim() || null }),
  /** Avslå: the driver is told why. */
  rejectPaper: (paper: string, reason: string) => call<DriverOverview>(`${DRIFT}/drivers/paper/${encodeURIComponent(paper)}/reject`, { reason }),
  driverJoining: () => call<Joining>(`${DRIFT}/drivers/connect`),
  /** Släpp in en lokledare (LOK-30): a one-time code with that role. */
  locoLeadCode: (name: string) => call<OneTimeCodeAnswer>(`${DRIFT}/codes`, { name: name.trim() || null, role: "loco_lead" }),
};
export type OneTimeCodeAnswer = Schemas["trainmeet.hub-1.one-time-code"];

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
  refuse: (change: Refuse) => call<PreviewClients>(`${PROV}/clients/refuse`, change),
  revoke: (change: Revoke) => call<PreviewClients>(`${PROV}/clients/revoke`, change),
  coupleExit: (change: CoupleExit) => call<PreviewClients>(`${PROV}/clients/exit`, change),
};


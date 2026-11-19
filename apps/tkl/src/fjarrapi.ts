// Fjärrstyrning (#36 del c): TKL's own API for the remote interlocking and the fjärrbild, with the
// types generated from the contracts (contracts/tkl.py). The key from the approval stays in TKL's
// server (H31); Hubben decides which places TKL may read and act on.
import type { components } from "../../../contracts/tkl";
import { call, full, TKL, type Command, type Connection, type Reply, type State, type View } from "./api";

type Schemas = components["schemas"];
export type Remote = Schemas["trainmeet.tkl-1.state.TklRemote"];
export type RemoteSetUp = Schemas["trainmeet.tkl-1.remote-setup"];
export type RemoteAreas = Schemas["trainmeet.tkl-1.remote-areas"];
export type RemoteArea = Schemas["trainmeet.tkl-1.remote-areas.TklRemoteArea"];
export type RemotePlace = Schemas["trainmeet.tkl-1.remote-areas.TklRemotePlace"];
export type RemoteConnect = Schemas["trainmeet.tkl-1.remote-connect"];
export type Fjarr = Schemas["trainmeet.tkl-1.fjarr"];
export type Overview = Schemas["trainmeet.tkl-1.fjarr.Overview"];
export type OverviewPlace = Schemas["trainmeet.tkl-1.fjarr.OverviewPlace"];
export type OverviewDrawing = Schemas["trainmeet.tkl-1.fjarr.OverviewDrawing"];
export type OverviewTrack = Schemas["trainmeet.tkl-1.fjarr.OverviewTrack"];
export type OverviewSignal = Schemas["trainmeet.tkl-1.fjarr.OverviewSignal"];
export type RemoteRoute = Schemas["trainmeet.tkl-1.fjarr.RemoteRoute"];
export type RemoteRouteHere = Schemas["trainmeet.tkl-1.fjarr.RemoteRouteHere"];
export type RouteState = Schemas["trainmeet.tkl-1.fjarr.RouteState"];
export type OfferHere = Schemas["trainmeet.tkl-1.fjarr.OfferHere"];
export type PlaceMode = Schemas["trainmeet.tkl-1.fjarr.PlaceMode"];
export type Receiver = Schemas["trainmeet.tkl-1.fjarr.Receiver"];
export type SectionOverview = Schemas["trainmeet.tkl-1.fjarr.SectionOverview"];

export const fjarrApi = {
  setUp: (change: RemoteSetUp) => call<State>(`${TKL}/fjarr/setup`, "POST", change),
  areas: (address: string) => call<RemoteAreas>(`${TKL}/fjarr/areas?address=${encodeURIComponent(address)}`),
  connect: (given: RemoteConnect) => call<Connection>(`${TKL}/fjarr/connection`, "POST", given),
  picture: () => call<Fjarr>(`${TKL}/fjarr`),
  place: async (place: string): Promise<View> => {
    const view = await call<View>(`${TKL}/fjarr/places/${encodeURIComponent(place)}`);
    return { ...view, snapshot: view.snapshot ? full(view.snapshot) : null };
  },
  command: (command: Command) => call<Reply>(`${TKL}/fjarr/commands`, "POST", command),
};

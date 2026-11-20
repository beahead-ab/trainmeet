// Landskapet and Exportera through CAD's API (#89 del d1), with the types generated from the
// contracts (contracts/cad.d.ts). Nothing here is typed by hand.
import type { components } from "../../../contracts/cad";
import { API, call } from "./api";

type Schemas = components["schemas"];
export type Landscape = Schemas["trainmeet.cad-1.landscape"];
export type LandscapeEdit = Schemas["trainmeet.cad-1.landscape-edit"];
export type LandscapeOp = NonNullable<LandscapeEdit["operations"]>[number];
export type LandscapeArea = NonNullable<Landscape["areas"]>[number];
export type SurfaceInfo = NonNullable<Landscape["surfaces"]>[number];
export type SurfaceTotal = NonNullable<Landscape["totals"]>[number];
export type Surface = SurfaceInfo["surface"];
export type ModuleExport = Schemas["trainmeet.cad-1.module-export"];
export type ExportFile = ModuleExport["files"][number];
export type MmmGable = ModuleExport["mmm"][number];
export type ModuleRecord = ModuleExport["record"];

const modules = `${API}/modules`;

export const landscapeApi = {
  landscape: (id: string, version?: number) =>
    call<Landscape>("GET", `${modules}/${id}/landscape${version ? `?version=${version}` : ""}`),
  preview: (id: string, edit: LandscapeEdit) => call<Landscape>("POST", `${modules}/${id}/landscape`, edit),
  make: (id: string, base: number) => call<Landscape>("POST", `${modules}/${id}/landscape/make`, { base }),
  save: (id: string, edit: LandscapeEdit) => call<Landscape>("POST", `${modules}/${id}/landscape/save`, edit),
  approve: (id: string, edit: LandscapeEdit) => call<Landscape>("POST", `${modules}/${id}/landscape/approve`, edit),
  exportOf: (id: string, version?: number) =>
    call<ModuleExport>("GET", `${modules}/${id}/export${version ? `?version=${version}` : ""}`),
};

export type LandscapeApi = typeof landscapeApi;

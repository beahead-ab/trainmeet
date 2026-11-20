// Landskapet and Exportera as CAD's API answers them (#89 del d1), for the web app's tests: the
// photographed Exempelstation with a proposal from the colour clustering, a pond the owner painted,
// and its export as an approved version with a newer draft.
import type { Landscape, ModuleExport } from "./landskapapi";
import { PHOTOGRAPHED } from "./testphoto";

const SURFACES: NonNullable<Landscape["surfaces"]> = [
  { surface: "grass", name: "Gräs", colour: "#7fa860" },
  { surface: "ballast", name: "Ballast", colour: "#a8a39a" },
  { surface: "ground", name: "Mark och väg", colour: "#9c8466" },
  { surface: "platform", name: "Plattform", colour: "#d6d2c8" },
  { surface: "water", name: "Vatten", colour: "#5b8fc7" },
  { surface: "building", name: "Byggnad", colour: "#b0645a" },
  { surface: "trees", name: "Buske och träd", colour: "#3f6b3a" },
  { surface: "path", name: "Stig", colour: "#d2b98a" },
  { surface: "unknown", name: "Okänd yta", colour: "#c9b8d9" },
];

export const PROPOSAL: Landscape = {
  module: PHOTOGRAPHED.id,
  version: 3,
  latest: 3,
  saved_in: 3,
  status: "proposal",
  method: "colour",
  made_by: "Färgklustring 1",
  grid: { x0: 0, y0: 0, cell: 2, width: 750, height: 350 },
  areas: [
    { surface: "grass", outline: [[0, 0], [1500, 0], [1500, 700], [0, 700]], holes: [[[600, 450], [800, 450], [800, 600], [600, 600]]], area: 1_020_000, painted: false },
    { surface: "water", outline: [[600, 450], [800, 450], [800, 600], [600, 600]], holes: [], area: 30_000, painted: true },
  ],
  track_bed: [[[0, 307], [1500, 307], [1500, 403], [0, 403]]],
  totals: [
    { surface: "grass", area: 900_000, share: 0.857 },
    { surface: "ballast", area: 120_000, share: 0.114 },
    { surface: "water", area: 30_000, share: 0.029 },
  ],
  surfaces: SURFACES,
  photo: { job: PHOTOGRAPHED.photo!.job, url: PHOTOGRAPHED.photo!.display_url, grid: PHOTOGRAPHED.photo!.grid },
  may_edit: true,
  changed: false,
};

export const MODULE_WITH_LANDSCAPE = { ...PHOTOGRAPHED, version: 3, latest: 3 };

export const APPROVED: Landscape = { ...PROPOSAL, status: "approved" };

export const NONE: Landscape = {
  ...PROPOSAL,
  saved_in: null,
  status: "none",
  method: null,
  made_by: null,
  areas: [],
  totals: [],
};

const URL = `/api/cad/1/modules/${PHOTOGRAPHED.id}/export`;

export const EXPORT: ModuleExport = {
  module: PHOTOGRAPHED.id,
  number: "M-001",
  name: "Exempelstation",
  version: 4,
  status: "draft",
  versions: [
    { version: 2, status: "approved", label: "Godkänd version 2" },
    { version: 4, status: "draft", label: "Utkastet, version 4" },
  ],
  files: [
    ["fremo", "FREMO-ritning (SVG)", "fremo.svg", "image/svg+xml"],
    ["print", "Utskrift (SVG)", "utskrift.svg", "image/svg+xml"],
    ["database", "Moduldatabasen (JSON)", "moduldatabas.json", "application/json"],
    ["database", "Moduldatabasen (CSV)", "moduldatabas.csv", "text/csv; charset=utf-8"],
    ["mmm", "MMM-måtten (CSV)", "mmm.csv", "text/csv; charset=utf-8"],
    ["dxf", "DXF", "modul.dxf", "application/dxf"],
  ].map(([kind, name, file, media]) => ({
    kind: kind as ModuleExport["files"][number]["kind"],
    name: name as string,
    file: file === "modul.dxf" ? "M-001-exempelstation-v4.dxf" : `M-001-exempelstation-v4-${file}`,
    url: `${URL}/4/${file}`,
    media_type: media as string,
  })),
  record: {
    format: "trainmeet.cad.moduldatabas/1",
    id: PHOTOGRAPHED.id,
    number: "M-001",
    name: "Exempelstation",
    owner: "Provkonto A",
    scale: "H0",
    shape: "straight",
    length: 1500,
    radius: null,
    angle: null,
    offset: null,
    gables: [
      { end: "A", norm: "mmm", profile: "h0-mmm-dubbelspar", label: "MMM dubbelspår", width: 700, tracks: [140, 197] },
      { end: "B", norm: null, profile: null, label: "Egen gavel · 3 spår", width: 700, tracks: [245, 295, 345] },
    ],
    track_length: 4210,
    switches: 3,
    crossings: 0,
    landscape: true,
    version: 4,
    status: "draft",
    approved_at: null,
  },
  mmm: [
    {
      end: "A",
      norm: "mmm",
      label: "MMM dubbelspår",
      width: 700,
      tracks: [
        { track: 1, from_kant1: 140, spacing: null, mmm: 140, deviation: 0 },
        { track: 2, from_kant1: 200.5, spacing: 60.5, mmm: 197, deviation: 3.5 },
      ],
    },
    { end: "B", norm: null, label: "Egen gavel · 3 spår", width: 700, tracks: [{ track: 1, from_kant1: 245, spacing: null, mmm: null, deviation: null }] },
  ],
  landscape: true,
};

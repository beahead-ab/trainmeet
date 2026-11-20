// Modules, profiles and sessions as CAD's API gives them, for the web app's tests.
import type { Module, ModuleEvent, ModuleList, ProfileList, Session } from "./api";

export const ACCOUNT = { id: "6dc0f358-f4a0-53bc-8a19-9db29682090d", name: "Provkonto A", initials: "PA" };
export const CLUB = { id: "5a1f0c3e-89a0-4d2b-9e1f-7a6b5c4d3e2f", name: "Provklubben", admin: true };

export const SESSION: Session = {
  account: ACCOUNT,
  login: "trial",
  clubs: [CLUB],
  apps: ["hub", "cad", "catalog", "id"],
  tokens: 86,
  tokens_url: "https://test.id.trainmeet.app/tokens",
  help_url: "https://test.id.trainmeet.app/hjalp",
  logout_url: null,
};

const OWNER = { kind: "person" as const, id: ACCOUNT.id, name: ACCOUNT.name };
const NOW = "2026-11-19T13:04:00+01:00";

/** Exempelstation: FREMO dubbelspår at A, an own gable with three tracks at B, so the tracks
 * between wait for the photo. */
export const STATION: Module = {
  id: "0e6c2f0a-1b2c-4d3e-8f40-5a6b7c8d9e0f",
  number: "M-001",
  name: "Exempelstation",
  owner: OWNER,
  visibility: "me",
  scale: "H0",
  shape: { kind: "straight", length: 1500, width: 700 },
  gables: [
    { end: "A", label: "FREMO dubbelspår", norm: "fremo", profile: "h0-fremo-dubbelspar", tracks: [330, 380] },
    { end: "B", label: "Egen gavel · 3 spår", norm: null, profile: null, tracks: [245, 295, 345] },
  ],
  graph: {
    geometry: "mm",
    nodes: [
      { id: "n1", type: "module_joint", at: [0, 330], gable: "A", track: 1 },
      { id: "n2", type: "module_joint", at: [0, 380], gable: "A", track: 2 },
      { id: "n3", type: "module_joint", at: [1500, 245], gable: "B", track: 1 },
      { id: "n4", type: "module_joint", at: [1500, 295], gable: "B", track: 2 },
      { id: "n5", type: "module_joint", at: [1500, 345], gable: "B", track: 3 },
    ],
    pieces: [],
    switches: [],
    complete: false,
    issued: 5,
  },
  status: "draft",
  version: 1,
  photographed: false,
  track_length: 0,
  changed_at: NOW,
  club: null,
  club_name: null,
  approved_version: null,
  approved_at: null,
  approved_by: null,
  created_at: NOW,
  used_in: [],
  may_edit: true,
  latest: 1,
  photo: null,
  keep_original: false,
  training_at: null,
};

/** Kurva 30° · K2, the view Kurvmodul's example, approved. */
export const CURVE: Module = {
  ...STATION,
  id: "1f7d3a1b-2c3d-4e4f-9051-6b7c8d9e0f1a",
  number: "M-002",
  name: "Kurva 30° · K2",
  shape: {
    kind: "curve",
    // Exactly as computed from the string and sagitta (CAD16).
    radius: 2003.1636029411766,
    angle: 29.943333537924747,
    width: 500,
    edge: "outer",
    sides: "bent",
    measured: { chord: 1035, sagitta: 68 },
  },
  gables: [
    { end: "A", label: "Dubbelspår", norm: null, profile: "h0-dubbelspar", tracks: [200, 250] },
    { end: "B", label: "Dubbelspår", norm: null, profile: "h0-dubbelspar", tracks: [200, 250] },
  ],
  graph: {
    geometry: "mm",
    nodes: [
      { id: "n1", type: "module_joint", at: [0, 200], gable: "A", track: 1 },
      { id: "n2", type: "module_joint", at: [0, 250], gable: "A", track: 2 },
      { id: "n3", type: "module_joint", at: [1000, 267.95], gable: "B", track: 1 },
      { id: "n4", type: "module_joint", at: [975, 274.65], gable: "B", track: 2 },
    ],
    pieces: [
      {
        id: "s5",
        start: "n1",
        end: "n3",
        segments: [{ kind: "arc", start: [0, 200], end: [1000, 267.95], center: [0, 2200], radius: 2000, clockwise: true }],
        track: null,
        origin: { source: "measures", certainty: "probable" },
      },
      {
        id: "s6",
        start: "n2",
        end: "n4",
        segments: [{ kind: "arc", start: [0, 250], end: [975, 274.65], center: [0, 2200], radius: 1950, clockwise: true }],
        track: null,
        origin: { source: "measures", certainty: "probable" },
      },
    ],
    switches: [],
    complete: true,
    issued: 6,
  },
  status: "approved",
  track_length: 2068.4,
  approved_version: 1,
  approved_at: "2026-11-19T18:20:00+01:00",
  approved_by: "Provkonto A",
};

export const LIST: ModuleList = {
  library: { id: "mine", name: "Mitt modulbibliotek", kind: "mine", club: null, may_add: true },
  modules: [STATION, CURVE],
  gables: [
    { label: "Dubbelspår", profile: "h0-dubbelspar", count: 2 },
    { label: "FREMO dubbelspår", profile: "h0-fremo-dubbelspar", count: 1 },
    { label: "Egen gavel · 3 spår", profile: null, count: 1 },
  ],
};

export const EMPTY: ModuleList = { ...LIST, modules: [], gables: [] };

export const HISTORY: ModuleEvent[] = [
  { at: "2026-11-19T18:20:00+01:00", kind: "approved", version: 1, by: "Provkonto A", text: "Version 1 godkänd" },
  { at: "2026-11-19T15:57:00+01:00", kind: "created", version: 1, by: "Provkonto A", text: "Modulen skapad ur mått" },
];

export const PROFILES: ProfileList = {
  scale: "H0",
  norms: [
    { norm: "fremo", name: "FREMO" },
    { norm: "mmm", name: "MMM" },
    { norm: "usms", name: "USMS" },
    { norm: "club", name: "Klubbens egen" },
  ],
  profiles: [
    {
      id: "h0-fremo-dubbelspar",
      name: "FREMO dubbelspår",
      kind: "norm",
      scale: "H0",
      norm: "fremo",
      tracks: 2,
      first: null,
      spacings: [null],
      read: false,
      note: "Mått enligt FREMO:s standard, läses in före lanseringen. Lägena per modul.",
      owner: null,
      uses: 1,
    },
    {
      id: "h0-mmm-enkelspar",
      name: "MMM enkelspår",
      kind: "norm",
      scale: "H0",
      norm: "mmm",
      tracks: 1,
      first: 140,
      spacings: [],
      read: false,
      note: "Spåret 140 mm från Kant 1.",
      owner: null,
      uses: 0,
    },
    {
      id: "h0-enkelspar",
      name: "Enkelspår",
      kind: "general",
      scale: "H0",
      norm: null,
      tracks: 1,
      first: null,
      spacings: [],
      read: true,
      note: "Läge och spåravstånd anges per modul.",
      owner: null,
      uses: 0,
    },
    {
      id: "h0-dubbelspar",
      name: "Dubbelspår",
      kind: "general",
      scale: "H0",
      norm: null,
      tracks: 2,
      first: null,
      spacings: [null],
      read: true,
      note: "Läge och spåravstånd anges per modul.",
      owner: null,
      uses: 2,
    },
    {
      id: "egen-0a1b2c3d4e5f",
      name: "Egen · 6 spår",
      kind: "own",
      scale: "H0",
      norm: null,
      tracks: 6,
      first: 53,
      spacings: [81, 50, 52, 344, 51],
      read: true,
      note: null,
      owner: OWNER,
      uses: 1,
    },
  ],
};

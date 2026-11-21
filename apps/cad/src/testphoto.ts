// A module read from a synthetic photo as CAD's API answers it (#89 del c1), for the web app's
// tests: Exempelstation 1500 × 700 photographed, a pair the code and the AI read differently
// (Osäkert parti), a gable track 35 mm off, and the price before the photo is read.
import type { Module, PhotoConsent, PhotoJob, StorageUse } from "./api";
import { STATION } from "./testdata";

const JOB = "7b1e2d3c-4a5b-4c6d-8e7f-901a2b3c4d5e";
const TAKEN = "2026-11-19T12:58:00+01:00";
const GRID = { x0: -10, y0: -10, ppm: 1, width: 1521, height: 721, matrix: null };

export const CONSENT: PhotoConsent = {
  available: true,
  given: false,
  version: "2026-11-19",
  sent_to: "TrainMeets AI: Claude från Anthropic via Amazon Bedrock i EU",
  text: "Mätbilden skickas till TrainMeets AI: Claude från Anthropic via Amazon Bedrock i EU. AI:n svarar bara på vilka spår som hänger ihop.",
  own_ai: null,
  price: 12,
  balance: 86,
  payer: null,
  message: null,
  may_read: true,
};

export const STORAGE: StorageUse = { used: 3 * 1024 * 1024, limit: 100 * 1024 * 1024, waiting: 5 * 1024 * 1024 };

const IMAGE = { id: "00000000-0000-0000-0000-000000000063", url: "/api/cad/1/photos/file/forhand.jpg", width: 2000, height: 1500 };

/** The photo taken in: the corners found, waiting for the owner. */
export const CORNERS: PhotoJob = {
  id: JOB,
  module: STATION.id,
  profile: "modulfoto",
  frames: [],
  frame: null,
  state: "corners",
  progress: 0,
  step: "Bekräfta hörnen och Kant 1",
  created_at: TAKEN,
  photos: [{ ...IMAGE, id: "00000000-0000-0000-0000-000000000000", url: "/api/cad/1/photos/file/original.jpg", width: 4000, height: 3000 }],
  preview: IMAGE,
  corners: {
    corners: [
      [262, 430],
      [1146, 398],
      [1208, 784],
      [246, 820],
    ],
    kant1: 0,
    gable_a: 3,
    found: true,
    certain: true,
    derived: false,
    why: "Tryck på den långsida som är Kant 1 och på gavel A.",
    chosen: null,
  },
  quality: null,
  length: null,
  length_plus_minus: null,
  length_given: true,
  offset: null,
  measure: null,
  tracks_on_photo: [],
  facts: [],
  measures: [],
  questions: [],
  summary: null,
  sleepers: null,
  gauge: null,
  price: { tokens: 12, why: "first", text: "12 tokens för mätbilden, med följdfrågorna. Egen AI: gratis." },
  cost: 0,
  ai: null,
  version: null,
  chain: "1.0.0",
  key: "0".repeat(64),
  message: null,
};

/** The same photo read with AI: version 2 of the module, with a question and a measure off. */
export const DONE: PhotoJob = {
  ...CORNERS,
  state: "done",
  progress: 100,
  step: "Klart",
  quality: {
    px_per_mm: 2.4,
    tilt: 9.7,
    length_from_photo: true,
    gates: [
      { key: "resolution", level: "ok", value: 2.4, text: "2,4 px per mm" },
      { key: "tilt", level: "ok", value: 9.7, text: "Taget 9,7° från rakt ovanifrån" },
      { key: "sharpness", level: "ok", value: 0.21, text: "Skarpt" },
    ],
  },
  length: 1494.2,
  length_plus_minus: 1.6,
  length_given: true,
  offset: 0,
  measure: { job: JOB, url: "/api/cad/1/photos/file/matbild.jpg", grid: GRID },
  tracks_on_photo: [
    [
      [262, 610],
      [1180, 600],
    ],
    [
      [262, 630],
      [700, 625],
      [1180, 560],
    ],
  ],
  facts: [
    { key: "bredd", label: "Bredd", value: 700, text: null, plus_minus: null, source: "owner", certainty: "certain" },
    { key: "sparvidd", label: "Spårvidd", value: 16.49, text: "H0 16,5 mm, på 23 ställen", plus_minus: 0.05, source: "photo", certainty: "certain" },
  ],
  measures: [
    { key: "proportion", label: "Proportion längd/bredd", owner: 2.143, owner_source: "owner", photo: 2.135, plus_minus: 0.003, agrees: true, gable: null, track: null },
    { key: "langd", label: "Längd", owner: 1500, owner_source: "owner", photo: 1494.2, plus_minus: 1.6, agrees: true, gable: null, track: null },
    { key: "bredd", label: "Bredd", owner: 700, owner_source: "owner", photo: 705, plus_minus: 2, agrees: true, gable: null, track: null },
    { key: "gavel.a.1", label: "Gavel A · spår 1", owner: 330, owner_source: "owner", photo: 327.4, plus_minus: 0.8, agrees: true, gable: "A", track: 1 },
    { key: "gavel.b.3", label: "Gavel B · spår 3", owner: 345, owner_source: "owner", photo: 380.2, plus_minus: 0.9, agrees: false, gable: "B", track: 3 },
  ],
  questions: [
    {
      key: "nod:x1",
      kind: "node",
      source: "ai",
      title: "Två växlar eller en korsning?",
      text: "Två spår närmar sig varandra och byter plats mellan spår 2 och 3 från gavel B. Det kan vara två växlar eller en korsning. Bedömningarna gick isär, så du får avgöra.",
      choices: [
        { id: "tva-vaxlar", text: "Två växlar", hint: null, sketch: "two_switches" },
        { id: "korsning", text: "En korsning", hint: null, sketch: "crossing" },
      ],
      code: "korsning",
      ai: "tva-vaxlar",
      answer: null,
      at: [1250, 300],
      topology: true,
      closeup: true,
      closeup_ai: null,
      span: null,
    },
  ],
  summary: { tracks_a: 2, tracks_b: 3, switches: 2, crossings: 0, ends: 1, track_length: 4812.5, deviation: { median: 0.08, max: 0.94, count: 2792 } },
  sleepers: { straight: 7.09, slanting: 7.09, slanting_angle: 43, agree: true },
  gauge: { value: 16.49, nominal: 16.5, places: 23, agrees: true },
  price: { tokens: 0, why: "included", text: "Ingår: mätbilden är redan läst. Följdfrågor kostar inget." },
  cost: 12,
  ai: "provmodell",
  version: 2,
  key: "a".repeat(64),
};

/** A new module whose length came from the photo: Längden ur fotot. */
export const LENGTH: PhotoJob = {
  ...DONE,
  length: 1213.4,
  length_plus_minus: 6,
  length_given: false,
  measures: [DONE.measures?.[2]!],
  questions: [],
  sleepers: { straight: 7.09, slanting: 7.09, slanting_angle: 43, agree: true },
  gauge: { value: null, nominal: 16.5, places: 1, agrees: null },
};

/** Exempelstation after the photo: version 2, with its measuring image under the Foto tab. */
export const PHOTOGRAPHED: Module = {
  ...STATION,
  version: 2,
  latest: 2,
  photographed: true,
  drawing: { answers: [], lines: [], locks: [], ids: [], questions: [], plan_approved: false, source: "photo", photo: JOB, smoothing: "light" },
  photo: {
    job: JOB,
    measure_url: "/api/cad/1/photos/file/matbild2.jpg",
    display_url: "/api/cad/1/photos/file/matbild.jpg",
    grid: GRID,
    chain: "0.9.0",
    newer_chain: true,
    original_until: "2026-12-19T12:58:00+01:00",
    original_kept: false,
    taken_at: TAKEN,
  },
  keep_original: false,
  training_at: null,
};

export const JOB_ID = JOB;

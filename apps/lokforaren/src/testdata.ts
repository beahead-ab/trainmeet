// What the tests draw on: Provbanan's duty 1 as the hub sends it (train 101 Norrby–Sjövik and
// back as 104, Medel), and a fetch that answers like the hub. Made for the tests: no one's data.
import { vi } from "vitest";
import type { DriverMe, Korplan, KorplanRow, PaperPrice, PaperService, PaperStatus, Presence, ServiceList, ServiceOffer } from "./api";
import { memoryStorage, Memory } from "./memory";
import type { Notifier } from "./remind";
import { Lok, type LokState } from "./store";

export const CLOCK = { time: "06:03", seconds: 6 * 3600 + 3 * 60, running: true, speed: 4, game_day: 1 };
export const SETTINGS = { reality: false, clearances: false, arrival: false };

export function offer(number: string, extra: Partial<ServiceOffer> = {}): ServiceOffer {
  return {
    service: { kind: "duty", id: `d${number}` },
    number,
    start: { time: "06:00", place: "nby", place_name: "Norrby" },
    end: { time: "07:34", place: "nby", place_name: "Norrby" },
    operator: null,
    level: "medium",
    trains: ["101", "104"],
    taken: false,
    driver: null,
    driver_name: null,
    released_on_line: false,
    matches_level: false,
    exact: false,
    done: false,
    ...extra,
  } as ServiceOffer;
}

const PLACES: Record<string, string> = { nby: "Norrby", asn: "Åsen", lvh: "Lövhult", mla: "Mellanå", sjv: "Sjövik" };

export function row(call: string, arrival: string | null, departure: string | null, extra: Partial<KorplanRow> = {}): KorplanRow {
  const [train, place] = call.split("-") as [string, string];
  return {
    call,
    train,
    train_number: train.slice(1),
    place,
    place_code: place,
    place_name: PLACES[place] ?? place,
    arrival,
    departure,
    track: "1",
    stops: true,
    note: null,
    first_of_train: false,
    last: false,
    unmanned: true,
    changed: false,
    real: null,
    clearance: null,
    ...extra,
  } as KorplanRow;
}

/** Duty 1's calls of train 101, Norrby 06:00 to Sjövik 06:29 (the last of the service here). */
export function rows(): KorplanRow[] {
  return [
    row("t101-nby", null, "06:00", { first_of_train: true }),
    row("t101-asn", "06:08", "06:10"),
    row("t101-lvh", "06:14", "06:15", { track: null, stops: false }),
    row("t101-mla", "06:19", "06:21"),
    row("t101-sjv", "06:29", null, { last: true, note: "Ställ upp tåget på spår 1." }),
  ];
}

export function korplan(extra: Partial<Korplan> = {}): Korplan {
  return {
    service: { kind: "duty", id: "d1" },
    number: "1",
    rows: rows(),
    clock: CLOCK,
    settings: SETTINGS,
    position: null,
    checkin: null,
    revision: 4,
    ...extra,
  } as Korplan;
}

export function me(extra: Partial<DriverMe> = {}): DriverMe {
  return {
    driver: { id: "forare-a", name: "Kim Ek", initials: "KE", level: "medium", state: null, photo: null, linked: false, joined: "2026-11-18T09:00:00Z" },
    service: offer("1", { taken: true, driver: "forare-a", driver_name: "Kim Ek", matches_level: true }),
    claimed_by: "driver",
    start: { time: "06:00", seconds: 21600, in_game_seconds: -180, in_real_seconds: -45, reminders: [20, 10] },
    checkin: null,
    clock: CLOCK,
    settings: SETTINGS,
    revision: 4,
    ...extra,
  } as DriverMe;
}

export function services(list: ServiceOffer[] = [offer("1", { matches_level: true }), offer("5", { matches_level: true, start: { time: "08:05", place: "sjv", place_name: "Sjövik" } }), offer("2", { level: "easy", start: { time: "06:05", place: "sjv", place_name: "Sjövik" } }), offer("3", { level: "experienced", start: { time: "06:35", place: "nby", place_name: "Norrby" } })]): ServiceList {
  return { kind: "duty", services: list } as ServiceList;
}

export function presence(name: string | null, extra: Partial<Presence> = {}): Presence {
  return {
    driver: { id: `forare-${name ?? "x"}`, name, initials: name ? name.slice(0, 2).toUpperCase() : null, level: "easy", state: null, photo: null, linked: false, joined: "2026-11-18T09:00:00Z" },
    service_number: null,
    train_number: null,
    checkin: null,
    me: false,
    ...extra,
  } as Presence;
}

// --- Efter pappret: Tjänst 24 on the paper, not in Provbanan's plan (hub/tests/test_driver_paper.py)

export const PAPER_ID = "papper-0a1b2c3d4e";

/** The paper's timetable as the AI read it: Åsen's departure could not be read, and Bruket is no
 * place in the meet. */
export function paperService(extra: Partial<PaperService> = {}): PaperService {
  return {
    paper: PAPER_ID,
    service: { kind: "paper", id: PAPER_ID },
    status: "waiting",
    driver: "forare-a",
    driver_name: "Kim Ek",
    number: "24",
    train_number: "G 4521",
    operator: "Green Cargo",
    start: { time: "06:31", place: "nby", place_name: "Norrby", unreadable: false },
    end: { time: "07:20", place: "sjv", place_name: "Sjövik", unreadable: false },
    rows: [
      { place: "nby", place_name: "Norrby", arrival: null, departure: "06:41", track: "3", stops: true, note: "Koppla loket.", unreadable: false },
      { place: "asn", place_name: "Åsen", arrival: "06:49", departure: null, track: null, stops: true, note: null, unreadable: true },
      { place: null, place_name: "Bruket", arrival: "06:55", departure: "06:56", track: null, stops: true, note: null, unreadable: false },
      { place: "mla", place_name: "Mellanå", arrival: "06:59", departure: "07:01", track: null, stops: true, note: null, unreadable: false },
      { place: "sjv", place_name: "Sjövik", arrival: "07:10", departure: null, track: "2", stops: true, note: null, unreadable: false },
    ],
    pages: 2,
    photos: [`/api/drift/1/drivers/paper/${PAPER_ID}/pages/1`, `/api/drift/1/drivers/paper/${PAPER_ID}/pages/2`],
    paid_by: "meet",
    cost: 24,
    said: "Ingen tjänst startar 06:31 vid Norrby. Närmast: 3 kl. 06:35, 1 kl. 06:00.",
    candidates: [offer("3", { level: "experienced", start: { time: "06:35", place: "nby", place_name: "Norrby" } }), offer("1", { taken: true, driver: "forare-b", driver_name: "Bo" })],
    reason: null,
    train: null,
    model_time: "06:20",
    wall_time: "2026-11-18T09:00:00Z",
    ...extra,
  } as PaperService;
}

/** The körplan after the paper as the hub makes it: a row for each row of the paper, in its
 * order, Bruket as okand with its name as read, and no reality until it is approved. */
export function paperKorplan(status: PaperStatus = "waiting", extra: Partial<Korplan> = {}): Korplan {
  const paper = paperService();
  const last = (paper.rows ?? []).length - 1;
  return korplan({
    service: paper.service,
    number: "24",
    paper: status,
    rows: (paper.rows ?? []).map((read, index) =>
      row(`${PAPER_ID}-${index}`, read.arrival, read.departure, {
        train: PAPER_ID,
        train_number: "G 4521",
        place: read.place ?? "okand",
        place_code: read.place ?? read.place_name,
        place_name: read.place_name,
        track: read.track,
        note: read.note,
        unmanned: false,
        unreadable: read.unreadable,
        first_of_train: index === 0,
        last: index === last,
      }),
    ),
    ...extra,
  });
}

/** The driver running after the paper: the service as the list shows it, and the paper. */
export function paperMe(status: PaperStatus = "waiting", extra: Partial<PaperService> = {}): DriverMe {
  const paper = paperService({ status, ...extra });
  return me({
    service: offer("24", {
      service: paper.service,
      start: { time: "06:31", place: "nby", place_name: "Norrby" },
      end: { time: "07:20", place: "sjv", place_name: "Sjövik" },
      operator: "Green Cargo",
      level: null,
      trains: ["G 4521"],
      taken: true,
      driver: "forare-a",
      driver_name: "Kim Ek",
      paper: status,
    }),
    start: { time: "06:31", seconds: 6 * 3600 + 31 * 60, in_game_seconds: 0, in_real_seconds: null, reminders: [20, 10] },
    paper,
  });
}

export function price(extra: Partial<PaperPrice> = {}): PaperPrice {
  return { pages: 2, price: 24, per_page: 12, paid_by: "meet", payer: "Provbanans klubb", available: 480, ready: true, message: null, ...extra } as PaperPrice;
}

type Answer = { status?: number; body?: unknown; reason?: string };
export type Route = (url: URL, init: RequestInit) => Answer | undefined;

/** A fetch that answers like the hub: the routes are tried in order, method and path first. */
export function hub(answers: Record<string, Answer | ((url: URL, init: RequestInit) => Answer)>) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const fetch = vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input, "http://hubben.local");
    const method = init.method ?? "GET";
    const body = typeof init.body === "string" ? JSON.parse(init.body) : init.body;
    calls.push({ method, path: url.pathname + url.search, body });
    const found = answers[`${method} ${url.pathname}${url.search}`] ?? answers[`${method} ${url.pathname}`];
    const answer = typeof found === "function" ? found(url, init) : (found ?? { status: 404, body: { detail: "Finns inte." } });
    const status = answer.status ?? 200;
    const headers = new Headers(answer.reason ? { "X-Reason": answer.reason } : {});
    return new Response(status === 204 ? null : JSON.stringify(answer.body ?? {}), { status, headers });
  });
  vi.stubGlobal("fetch", fetch);
  return { fetch, calls };
}

export function notifier(allowed = false): Notifier & { shown: string[] } {
  const shown: string[] = [];
  return { shown, allowed: () => allowed, askable: () => false, ask: async () => allowed, show: (_title, body) => void shown.push(body) };
}

/** A Lok for the tests: its memory in memory, its clock on the fake timers, quiet. */
export function lokWith(state: Partial<LokState> = {}, options: { notifier?: Notifier } = {}): Lok {
  const lok = new Lok({ memory: new Memory(memoryStorage()), notifier: options.notifier ?? notifier(), sound: () => undefined });
  lok.state = { ...lok.state, language: "sv", phase: "app", meetName: "Provbanan", ...state };
  return lok;
}

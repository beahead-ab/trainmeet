// Lokföraren's state and what the driver does: come in, find and take a service, follow the
// körplan, check in, say Framme, tell the dispatcher, release the service, and leave. Drift owns
// all of it (LOK-07); the app reads it again after each of Drift's events (the long poll /wait)
// and between them counts the clock on with Drift's speed (LOK-12).
import {
  api,
  rowsOf,
  Problem,
  refKey,
  type ClaimedBy,
  type DriverMe,
  type DriverMessage,
  type HubInfo,
  type Instructions,
  type Korplan,
  type Level,
  type MessageKind,
  type Presence,
  type Profile,
  type ServiceList,
  type ServiceOffer,
} from "./api";
import { MeetClock } from "./clock";
import { ChangedMarks, countdown, dueReminder, wholeMinutes } from "./korplan";
import { Memory } from "./memory";
import { beep, browserNotifier, type Notifier } from "./remind";
import { guessLanguage, languageOf, TEXT, type Language, type Text } from "./text";

export type Route = "korplan" | "tag" | "forare" | "jag" | "instruktioner" | "tjanst";
export const ROUTES: Route[] = ["korplan", "tag", "forare", "jag", "instruktioner", "tjanst"];
export type Sheet = "messages" | "release" | "checkin" | null;
export type Theme = "morkt" | "ljust" | "auto";
export type Phase = "loading" | "join" | "nomeet" | "app";
export type Then = "pause" | "other" | "leave";
export type Place = { place: string; code: string; name: string };

export const BASE = "/lokforaren/";
const CLOCK_EVERY_MS = 10_000;
const KORPLAN_EVERY_MS = 30_000;
const DRIVERS_EVERY_MS = 15_000;
const WAIT_AGAIN_MS = 3_000;

export type LokState = {
  phase: Phase;
  route: Route;
  sheet: Sheet;
  language: Language;
  theme: Theme;
  remindersOn: boolean;
  /** The drivers' code from the QR address, when there was one. */
  code: string | null;
  needsCode: boolean;
  sessionLost: boolean;
  hub: HubInfo | null;
  meetName: string | null;
  places: Place[];
  me: DriverMe | null;
  korplan: Korplan | null;
  services: ServiceList | null;
  query: string;
  /** The number on the driver's paper, when it did not match the plan's (LOK-19). */
  paper: string | null;
  presence: Presence[] | null;
  instructions: Instructions | null;
  /** The service whose card is open (taget.jpg). */
  selected: ServiceOffer | null;
  /** What went wrong with the latest thing the driver did, in the driver's language. */
  problem: string | null;
  /** A word to the driver: a reminder, a message sent. */
  notice: string | null;
  sent: DriverMessage | null;
  busy: boolean;
  /** The paper's number beside the plan's, per service (LOK-19). */
  papers: Record<string, string>;
  /** Hand-outs the driver has seen. */
  seen: string[];
  /** Calls the driver has said Framme at. */
  framme: string[];
  /** The driver chose to see the körplan before the start. */
  showKorplan: boolean;
};

type Options = { monotonic?: () => number; memory?: Memory; notifier?: Notifier; sound?: () => void };

export class Lok {
  readonly clock: MeetClock;
  readonly marks = new ChangedMarks();
  private readonly memory: Memory;
  private readonly notifier: Notifier;
  private readonly sound: () => void;
  private listeners = new Set<() => void>();
  private timers: ReturnType<typeof setInterval>[] = [];
  private waiting: AbortController | null = null;
  private looping = false;
  private linkTried = false;
  private initial: Route | null = null;
  state: LokState;

  constructor(options: Options = {}) {
    this.clock = new MeetClock(options.monotonic);
    this.memory = options.memory ?? new Memory();
    this.notifier = options.notifier ?? browserNotifier;
    this.sound = options.sound ?? beep;
    const memory = this.memory;
    this.state = {
      phase: "loading",
      route: "tag",
      sheet: null,
      language: languageOf(memory.get<string | null>("sprak", null) ?? guessLanguage()),
      theme: memory.get<Theme>("tema", "morkt"),
      remindersOn: memory.get("paminnelser", true),
      code: memory.get<string | null>("kod", null),
      needsCode: false,
      sessionLost: false,
      hub: null,
      meetName: null,
      places: [],
      me: null,
      korplan: null,
      services: null,
      query: "",
      paper: null,
      presence: null,
      instructions: null,
      selected: null,
      problem: null,
      notice: null,
      sent: null,
      busy: false,
      papers: memory.get("papper", {}),
      seen: memory.get("sedda", []),
      framme: memory.get("framme", []),
      showKorplan: false,
    };
  }

  get text(): Text {
    return TEXT[this.state.language];
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => void this.listeners.delete(listener);
  };

  getState = () => this.state;

  private set(change: Partial<LokState>): void {
    this.state = { ...this.state, ...change };
    for (const listener of this.listeners) listener();
  }

  /** The hub's no, in the driver's language: the English for the reasons it has, else the
   * hub's own words. */
  private say(error: unknown): string {
    if (error instanceof Problem) {
      if (error.status === 0) return this.text.offline;
      const known = error.reason ? this.text.reasons[error.reason] : undefined;
      return known ?? (error.message || this.text.failed);
    }
    return this.text.failed;
  }

  // --- Coming in ------------------------------------------------------------------------------

  /** The QR address is /lokforaren/#kod=123456 (LOK-01). The code is kept, so that a phone whose
   * session is lost can come in again without scanning. */
  readCode(hash: string): void {
    const found = /(?:^#|&)kod=(\d{6})(?:&|$)/.exec(hash);
    if (!found) return;
    this.memory.set("kod", found[1]);
    this.set({ code: found[1]! });
  }

  /** initial: the page the address names, kept when the driver is in. */
  async start(initial: Route | null = null): Promise<void> {
    this.initial = initial === "tjanst" ? "tag" : initial;
    await Promise.all([this.loadHub(), this.loadMeet()]);
    await this.refresh();
  }

  private async loadHub(): Promise<void> {
    try {
      this.set({ hub: await api.hub() });
    } catch {
      this.set({ hub: null });
    }
  }

  private async loadMeet(): Promise<void> {
    try {
      const now = await api.now();
      this.clock.accept(now.clock);
      this.set({ meetName: now.name, places: now.places.map(({ place, code, name }) => ({ place, code, name })) });
    } catch {
      this.set({ meetName: null, places: [] });
    }
  }

  async join(name: string, level: Level, language: Language, code: string | null): Promise<boolean> {
    this.setLanguage(language);
    const given = (code ?? this.state.code ?? "").replace(/\D/g, "");
    this.set({ busy: true, problem: null });
    try {
      await api.join({ name: name.trim(), level, code: given.length === 6 ? given : null });
      if (given.length === 6) {
        this.memory.set("kod", given);
        this.set({ code: given });
      }
      this.set({ busy: false, needsCode: false, sessionLost: false, phase: "app" });
      await this.refresh();
      if (!this.state.me?.service) this.navigate("tag");
      return true;
    } catch (error) {
      const needsCode = error instanceof Problem && (error.status === 422 || error.status === 404);
      this.set({ busy: false, needsCode: needsCode || this.state.needsCode, problem: this.say(error) });
      return false;
    }
  }

  // --- Reading Drift again ------------------------------------------------------------------

  /** Me and my körplan, as Drift has them now. A lost key sends the driver back to Kom in. */
  async refresh(): Promise<void> {
    let me: DriverMe;
    try {
      me = await api.me();
    } catch (error) {
      if (error instanceof Problem && error.status === 401) {
        // The key no longer works: the meet changed or ended, or the phone left. Come in again.
        const wasIn = this.state.me !== null;
        this.waiting?.abort();
        await this.loadMeet();
        this.set({ phase: this.state.meetName ? "join" : "nomeet", me: null, korplan: null, sheet: null, sessionLost: wasIn });
        return;
      }
      if (error instanceof Problem && error.status === 404) {
        this.set({ phase: "nomeet", me: null, korplan: null });
        return;
      }
      if (this.state.phase === "loading") this.set({ phase: "nomeet" });
      return;
    }
    this.clock.accept(me.clock);
    const serviceOf = (found: DriverMe | null) => (found?.service ? refKey(found.service.service) : null);
    const sameService = serviceOf(me) === serviceOf(this.state.me);
    const first = this.state.phase !== "app";
    this.set({ me, phase: "app", showKorplan: sameService && this.state.showKorplan });
    if (first) {
      this.navigate(this.initial ?? (me.service ? "korplan" : "tag"), true);
      this.initial = null;
    }
    await this.loadKorplan();
    await this.link();
  }

  async loadKorplan(): Promise<void> {
    if (!this.state.me?.service) {
      this.set({ korplan: null });
      return;
    }
    try {
      const korplan = await api.korplan();
      this.clock.accept(korplan.clock);
      this.marks.note(rowsOf(korplan), this.clock.seconds() ?? korplan.clock.seconds);
      this.set({ korplan });
    } catch (error) {
      if (error instanceof Problem && error.status === 404) this.set({ korplan: null });
    }
  }

  /** Logged in to the hub with TrainMeet ID: the driver is linked to the person (LOK-16). */
  private async link(): Promise<void> {
    const me = this.state.me;
    if (this.linkTried || !me || me.driver.linked || !this.state.hub?.person) return;
    this.linkTried = true;
    try {
      this.set({ me: await api.profile({}) });
    } catch {
      /* the link waits for the next time */
    }
  }

  async loadServices(query = this.state.query): Promise<void> {
    this.set({ query });
    try {
      const services = await api.services(query);
      if (query === this.state.query) this.set({ services });
    } catch (error) {
      this.set({ problem: this.say(error) });
    }
  }

  async loadPresence(): Promise<void> {
    try {
      const [presence, services] = await Promise.all([api.list(), api.services()]);
      this.set({ presence, services: this.state.query ? this.state.services : services });
    } catch (error) {
      this.set({ problem: this.say(error) });
    }
  }

  async loadInstructions(): Promise<void> {
    try {
      this.set({ instructions: await api.instructions() });
    } catch {
      this.set({ instructions: { text: {}, pdf: null, filename: null } as Instructions });
    }
  }

  async readClock(): Promise<void> {
    try {
      this.clock.accept((await api.clock()).clock);
    } catch {
      /* the clock stands still when the contact is gone (LOK-12) */
    }
  }

  /** Everything the page shows, after one of Drift's events. */
  async again(): Promise<void> {
    await this.refresh();
    if (this.state.route === "tag") await this.loadServices();
    if (this.state.route === "forare") await this.loadPresence();
  }

  // --- The long poll and the timers ---------------------------------------------------------

  startLoops(): void {
    if (this.looping) return;
    this.looping = true;
    void this.waitLoop();
    this.timers.push(setInterval(() => void this.readClock(), CLOCK_EVERY_MS));
    this.timers.push(setInterval(() => void this.loadKorplan(), KORPLAN_EVERY_MS));
    this.timers.push(
      setInterval(() => {
        if (this.state.route === "forare" && this.state.phase === "app") void this.loadPresence();
      }, DRIVERS_EVERY_MS),
    );
  }

  stopLoops(): void {
    this.looping = false;
    this.waiting?.abort();
    for (const timer of this.timers) clearInterval(timer);
    this.timers = [];
  }

  private async waitLoop(): Promise<void> {
    while (this.looping) {
      if (this.state.phase !== "app") {
        await sleep(WAIT_AGAIN_MS);
        continue;
      }
      this.waiting = new AbortController();
      try {
        const answer = await api.wait(this.state.me?.revision ?? 0, this.waiting.signal);
        if (answer.changed && this.looping) await this.again();
      } catch (error) {
        if (!this.looping) return;
        if (!(error instanceof DOMException && error.name === "AbortError")) await sleep(WAIT_AGAIN_MS);
      }
    }
  }

  // --- Each second: the countdown and the reminders (LOK-41) ---------------------------------

  /** Called each second. Gives the reminder 20 and 10 game minutes before the start, once each
   * per service, with the real time beside it. */
  tick(): void {
    const me = this.state.me;
    const seconds = this.clock.seconds();
    if (!me?.service || !me.start || seconds === null || this.clock.mode() !== "running" || !this.state.remindersOn) return;
    const left = countdown(me.start, seconds, this.clock.speed(), true);
    const key = `paminnelser.${refKey(me.service.service)}.${this.clock.gameDay() ?? 0}`;
    const fired = this.memory.get<number[]>(key, []);
    const due = dueReminder(left.game, fired);
    if (due === null) return;
    this.memory.set(key, [...fired, due]);
    const text = this.text;
    const real = left.real !== null ? text.remindReal(wholeMinutes(left.real)) : "";
    const body = text.remind(due, me.service.number, me.start.time, real) + (due === 10 ? ` ${text.remindOpens}` : "");
    this.sound();
    if (this.notifier.allowed()) this.notifier.show(text.app, body);
    else this.set({ notice: body });
  }

  async askNotifications(): Promise<void> {
    await this.notifier.ask();
    this.set({});
  }

  notificationsAskable(): boolean {
    return this.notifier.askable();
  }

  notificationsAllowed(): boolean {
    return this.notifier.allowed();
  }

  // --- What the driver does -----------------------------------------------------------------

  private async act(work: () => Promise<void>): Promise<boolean> {
    this.set({ busy: true, problem: null });
    try {
      await work();
      this.set({ busy: false });
      return true;
    } catch (error) {
      if (error instanceof Problem && error.status === 401) {
        this.set({ busy: false });
        await this.refresh();
        return false;
      }
      this.set({ busy: false, problem: this.say(error) });
      return false;
    }
  }

  /** Ta tjänsten: the first one gets it; the other is told it is taken (LOK-40). The paper's
   * number goes with it when it was not the plan's (LOK-19). */
  async claim(offer: ServiceOffer, paper: string | null = null): Promise<boolean> {
    const done = await this.act(async () => {
      const me = await api.claim(offer.service);
      const key = refKey(offer.service);
      if (paper && paper.trim() && paper.trim() !== offer.number) {
        this.remember("papers", "papper", { ...this.state.papers, [key]: paper.trim() });
      }
      this.remember("seen", "sedda", [...this.state.seen.filter((k) => k !== key), key]);
      this.clock.accept(me.clock);
      this.set({ me, selected: null, sheet: null, showKorplan: false, paper: null, query: "" });
      await this.loadKorplan();
    });
    if (done) this.navigate("korplan");
    else await this.loadServices();
    return done;
  }

  /** A service from the dispatcher or the lokledare: seen, and to the körplan. */
  acknowledge(): void {
    const key = this.state.me?.service ? refKey(this.state.me.service.service) : null;
    if (key) this.remember("seen", "sedda", [...this.state.seen.filter((k) => k !== key), key]);
    this.navigate("korplan");
  }

  /** Who gave the service, while the driver has not seen it: the dispatcher or the lokledare. */
  givenBy(): ClaimedBy | null {
    const me = this.state.me;
    if (!me?.service || !me.claimed_by || me.claimed_by === "driver") return null;
    return this.state.seen.includes(refKey(me.service.service)) ? null : me.claimed_by;
  }

  /** Släpp tjänsten, anywhere (LOK-25). On the line, the dispatcher gets the alarm (LOK-35). */
  async release(then: Then | null = null): Promise<boolean> {
    const done = await this.act(async () => {
      const me = await api.release();
      this.set({ me, korplan: null, sheet: null, showKorplan: false });
      if (then === "pause") this.set({ me: await api.profile({ state: "pause" }) });
    });
    if (!done) return false;
    if (then === "leave") return this.leave();
    this.navigate(then === "pause" ? "forare" : "tag");
    if (then !== "pause") await this.loadServices();
    return true;
  }

  async checkIn(place: string, track: string | null): Promise<boolean> {
    return this.act(async () => {
      const me = await api.checkIn(place, track?.trim() || null);
      this.set({ me, sheet: null });
      await this.loadKorplan();
      if (this.state.route === "forare") await this.loadPresence();
    });
  }

  /** Framme (LOK-04, LOK-39): at the last call the service is done. */
  async framme(call: string): Promise<boolean> {
    return this.act(async () => {
      const me = await api.framme(call);
      this.remember("framme", "framme", [...this.state.framme, call].slice(-50));
      this.set({ me });
      await this.loadKorplan();
      if (!me.service) this.navigate("tag");
    });
  }

  /** Försenad, Står på linjen, Behöver hjälp or Loket krånglar (LOK-23). */
  async send(kind: MessageKind): Promise<boolean> {
    return this.act(async () => {
      const sent = await api.send(kind);
      this.set({ sent, sheet: null, notice: this.text.sent(this.text.kinds[kind], sent.model_time) });
    });
  }

  async profile(change: Profile): Promise<boolean> {
    return this.act(async () => {
      this.set({ me: await api.profile(change) });
    });
  }

  async photo(picture: Blob): Promise<boolean> {
    return this.act(async () => {
      this.set({ me: await api.photo(picture) });
    });
  }

  async removePhoto(): Promise<boolean> {
    return this.act(async () => {
      this.set({ me: await api.removePhoto() });
    });
  }

  /** Lämna träffen: the service goes, the driver is gone from the others' lists, and the phone
   * forgets the driver. The code stays, to come in again. */
  async leave(): Promise<boolean> {
    const done = await this.act(async () => {
      await api.leave();
    });
    if (!done) return false;
    this.waiting?.abort();
    for (const key of ["papper", "sedda", "framme"]) this.memory.forget(key);
    this.set({ phase: "join", me: null, korplan: null, sheet: null, papers: {}, seen: [], framme: [], presence: null, selected: null, sessionLost: false });
    return true;
  }

  // --- The phone's own choices --------------------------------------------------------------

  private remember<K extends "papers" | "seen" | "framme">(field: K, key: string, value: LokState[K]): void {
    this.memory.set(key, value);
    this.set({ [field]: value } as Partial<LokState>);
  }

  setLanguage(language: Language): void {
    this.memory.set("sprak", language);
    this.set({ language });
  }

  setTheme(theme: Theme): void {
    this.memory.set("tema", theme);
    this.set({ theme });
  }

  setReminders(on: boolean): void {
    this.memory.set("paminnelser", on);
    this.set({ remindersOn: on });
    if (on && this.notifier.askable()) void this.askNotifications();
  }

  open(sheet: Sheet): void {
    this.set({ sheet, problem: null });
  }

  select(offer: ServiceOffer | null): void {
    this.set({ selected: offer, problem: null });
    if (offer) this.navigate("tjanst");
  }

  dismiss(): void {
    this.set({ notice: null, problem: null });
  }

  /** The paper's number did not match: look by the start time, and keep the number (LOK-19). */
  paperHint(number: string | null): void {
    this.set({ paper: number && number.trim() ? number.trim() : null });
  }

  seeKorplan(): void {
    this.set({ showKorplan: true });
  }

  /** Paths are /lokforaren/<route>; the hub gives the app's page for each of them. */
  navigate(route: Route, replace = false): void {
    if (route === this.state.route && !replace) return;
    this.set({ route, sheet: null, problem: null });
    if (typeof history === "undefined" || typeof location === "undefined") return;
    const path = BASE + route;
    if (location.pathname === path) return;
    if (replace) history.replaceState(null, "", path + location.hash);
    else history.pushState(null, "", path);
    if (typeof window !== "undefined") window.scrollTo?.(0, 0);
  }

  /** The route the address names, when the driver goes back or forward. */
  follow(pathname: string): void {
    const route = routeOf(pathname);
    if (route) this.set({ route, sheet: null });
  }

  /** The paper's number the driver searched for, beside the plan's (LOK-19). */
  paperOf(offer: ServiceOffer | null | undefined): string | null {
    return offer ? (this.state.papers[refKey(offer.service)] ?? null) : null;
  }
}

export function routeOf(pathname: string): Route | null {
  const part = pathname.startsWith(BASE) ? pathname.slice(BASE.length).split("/")[0] : "";
  return (ROUTES as string[]).includes(part ?? "") ? (part as Route) : null;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

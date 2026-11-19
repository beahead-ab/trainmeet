// Stream Deck with WebHID (#86 del b, SD50): in Chrome and Edge the browser drives a real deck for
// TKL in the cloud (test.tkl.trainmeet.app) and the reference stations. A local TKL owns its decks
// over USB itself, so that they work without an open tab; a deck TKL owns is never opened twice.
//
// The bridge is small: it opens the deck on TKL's server with its serial number and model, as the
// deck on the screen is opened (SD35), waits for the deck's next change, and on a change fetches
// the pictures of the keys whose face changed, and the touch strip or the info line where the
// model has one. TKL's server draws every picture (tkl/deck/render.py), the same as over USB, so a
// deck looks the same everywhere (SD3). A key down and up is a press or a hold by the same rule as
// the server's (SD29); the dials, the strip and Neo's touch points go to dial and touch (SD82,
// SD83). Without an answer from TKL every key says Ingen kontakt (SD21). Unplugged, the bridge
// lets go of the deck and tells TKL.
//
// Studio › Deck (#86 del c, SD46) reaches the deck through its view: its brightness, and after the
// owner's minutes without a press the deck goes dark; the first press then only wakes it. Blinka
// lights every key, and a dark deck too.
import type { StreamDeck, StreamDeckButtonControlDefinition, StreamDeckControlDefinition, StreamDeckEncoderControlDefinition, StreamDeckLcdSegmentControlDefinition } from "@elgato-stream-deck/webhid";
import type { DeckFace, DeckGrid, DeckModelId, DeckOpen, Decks, DeckView, InterlockingWait } from "./api";
import { Holds } from "./deck";

/** What the bridge uses of a deck: @elgato-stream-deck/webhid's StreamDeck, or a fake one. */
export type HidDeck = Pick<StreamDeck, "modelInfo" | "getSerialNumber" | "fillKeyBuffer" | "fillKeyColor" | "fillLcd" | "clearPanel" | "close" | "on" | "removeAllListeners" | "setBrightness">;

/** A picture as RGBA pixels, ready for the deck. */
export type Pixels = { width: number; height: number; data: Uint8ClampedArray };

/** TKL's API as the bridge uses it, and how a picture is fetched and decoded. */
export type BridgeApi = {
  decks: () => Promise<Decks>;
  open: (serial: string, open: DeckOpen) => Promise<DeckView>;
  view: (serial: string) => Promise<DeckView>;
  press: (serial: string, key: number, hold: boolean) => Promise<DeckView>;
  dial: (serial: string, dial: number, turn: number, press: boolean) => Promise<DeckView>;
  touch: (serial: string, point: -1 | 1) => Promise<DeckView>;
  wait: (serial: string, after: number, seconds: number) => Promise<InterlockingWait>;
  close: (serial: string) => Promise<void>;
  picture: (path: string) => Promise<Pixels>;
};

export const TKL = "/api/tkl/1";
export const OWNED = "Decket sköts av TKL över USB.";
export const NOT_HERE = "Ett riktigt Stream Deck kopplas in i Chrome eller Edge. Den här webbläsaren kan inte prata med USB-enheter (WebHID); decket på skärmen fungerar ändå.";
const SWIPE = 40;
const BLINK = 500;
const TICK = 100;
const SERIAL = /[^A-Za-z0-9._-]/g;

/** Elgato's models as the WebHID library names them, as TKL's (SD52, SD54): the older editions
 * and the Scissor Keys get the 15's profile, and the Modules theirs. */
export const MODELS: Record<string, DeckModelId> = {
  original: "15",
  originalv2: "15",
  "original-mk2": "15",
  "original-mk2-scissor": "15",
  mini: "mini",
  xl: "xl",
  pedal: "pedal",
  plus: "plus",
  "plus-xl": "plus-xl",
  neo: "neo",
  studio: "studio",
  "6-module": "module-6",
  "15-module": "module-15",
  "15-module-scissor": "module-15",
  "32-module": "module-32",
};

const isKey = (c: StreamDeckControlDefinition): c is StreamDeckButtonControlDefinition & { feedbackType: "lcd"; pixelSize: { width: number; height: number } } =>
  c.type === "button" && c.feedbackType === "lcd";
const isLcd = (c: StreamDeckControlDefinition): c is StreamDeckLcdSegmentControlDefinition => c.type === "lcd-segment";
const isDial = (c: StreamDeckControlDefinition): c is StreamDeckEncoderControlDefinition => c.type === "encoder";

/** A deck's grid read from its controls, for a model TKL does not know (SD53). */
export function gridOf(controls: readonly StreamDeckControlDefinition[]): DeckGrid {
  const keys = controls.filter(isKey);
  const dials = controls.filter(isDial).length;
  const lcd = controls.find(isLcd);
  return {
    columns: keys.length ? Math.max(...keys.map((k) => k.column)) + 1 : 0,
    rows: keys.length ? Math.max(...keys.map((k) => k.row)) + 1 : 0,
    dials,
    strip: !!lcd && dials > 0,
    info: !!lcd && dials === 0,
    touch: controls.filter((c) => c.type === "button" && c.feedbackType === "rgb").length,
    pedals: controls.filter((c) => c.type === "button" && c.feedbackType === "none").length,
  };
}

/** The serial number as TKL keeps it: letters, digits, dot, dash and underscore (SD35). */
export function serialOf(given: string, model: string): string {
  const clean = given.replace(SERIAL, "").slice(0, 64);
  return /^[A-Za-z0-9]/.test(clean) ? clean : `hid-${model}`.replace(SERIAL, "").slice(0, 64);
}

const keyPath = (serial: string, index: number, width: number, height: number, phase: number) =>
  `${TKL}/deck/${encodeURIComponent(serial)}/key/${index}.png?size=${width}${height !== width ? `&height=${height}` : ""}${phase ? "&phase=1" : ""}`;

type Painted = { face: string; pictures: Pixels[] };

/** One real deck in the browser, opened on TKL's server and kept in step with it. */
export class Bridge {
  serial = "";
  model: DeckModelId | null = null;
  view: DeckView | null = null;
  contact = true;
  closed = false;
  private holds = new Holds();
  private painted = new Map<number, Painted>();
  private lcdDrawn = "";
  private nothing: Pixels | null = null;
  private phase = 0;
  private sending: Promise<void> = Promise.resolve();
  private timer: ReturnType<typeof setInterval> | null = null;
  brightness: number | null = null;
  asleep = false;
  private activeAt = 0;
  private swallowed = new Set<number>();

  constructor(
    readonly deck: HidDeck,
    readonly api: BridgeApi,
    readonly onChange: (bridge: Bridge) => void = () => {},
    readonly now: () => number = () => Date.now(),
  ) {}

  get name(): string {
    return this.deck.modelInfo.name;
  }

  /** Opens the deck on TKL's server; "owned" when TKL already drives it over USB (SD50). */
  async start(): Promise<"open" | "owned"> {
    const info = this.deck.modelInfo;
    this.model = MODELS[info.id] ?? null;
    this.serial = serialOf(await this.deck.getSerialNumber().catch(() => ""), info.id);
    const known = await this.api.decks().catch(() => null);
    if (known?.decks?.some((d) => d.serial === this.serial && d.connection === "usb")) {
      await this.deck.close().catch(() => {});
      this.closed = true;
      return "owned";
    }
    const open: DeckOpen = this.model ? { model: this.model, grid: null, workplace: null, connection: "webhid" } : { model: null, grid: gridOf(info.controls), workplace: null, connection: "webhid" };
    let view: DeckView;
    try {
      view = await this.api.open(this.serial, open);
    } catch (error) {
      await this.deck.close().catch(() => {});
      this.closed = true;
      if ((error as { status?: number }).status === 409) return "owned";
      throw error;
    }
    const first = info.controls.find(isKey);
    if (first) this.nothing = await this.api.picture(`${TKL}/deck/ingen-kontakt.png?size=${first.pixelSize.width}${first.pixelSize.height !== first.pixelSize.width ? `&height=${first.pixelSize.height}` : ""}`).catch(() => null);
    this.listen();
    this.activeAt = this.now();
    await this.deck.clearPanel().catch(() => {});
    for (const touch of info.controls.filter((c) => c.type === "button" && c.feedbackType === "rgb")) {
      await this.deck.fillKeyColor((touch as StreamDeckButtonControlDefinition).index, 51, 65, 85).catch(() => {});
    }
    await this.show(view);
    this.timer = setInterval(() => this.tick(), TICK);
    void this.follow();
    return "open";
  }

  private listen(): void {
    const keys = this.deck.modelInfo.controls.filter(isKey).length;
    this.deck.on("down", (control) => {
      if (this.woken()) {
        if (control.type === "button") this.swallowed.add(control.index);
        return;
      }
      if (control.type === "encoder") {
        this.send(() => this.api.dial(this.serial, control.index, 0, true));
      } else if (control.feedbackType === "rgb") {
        // Neo's touch points, after the keys: the pages back and forth (SD82).
        const point = control.index === keys ? -1 : 1;
        this.send(() => this.api.touch(this.serial, point));
      } else if (control.feedbackType === "lcd") {
        this.holds.pressed(control.index, this.now());
      }
    });
    this.deck.on("up", (control) => {
      if (control.type === "button" && this.swallowed.delete(control.index)) return;
      if (control.type !== "button" || control.feedbackType !== "lcd") return;
      const what = this.holds.released(control.index, this.now());
      if (what) this.send(() => this.api.press(this.serial, control.index, what === "hold"));
    });
    this.deck.on("rotate", (control, amount) => {
      if (this.woken()) return;
      const turn = Math.max(-20, Math.min(20, amount));
      this.send(() => this.api.dial(this.serial, control.index, turn, false));
    });
    this.deck.on("lcdShortPress", (control, position) => {
      if (this.woken()) return;
      // A tap on the strip presses the dial over it (SD83).
      const dials = this.deck.modelInfo.controls.filter(isDial).length;
      if (!dials) return;
      const dial = Math.max(0, Math.min(dials - 1, Math.floor((position.x * dials) / control.pixelSize.width)));
      this.send(() => this.api.dial(this.serial, dial, 0, true));
    });
    this.deck.on("lcdSwipe", (_control, from, to) => {
      const moved = to.x - from.x;
      if (Math.abs(moved) >= SWIPE) this.send(() => this.api.touch(this.serial, moved < 0 ? 1 : -1));
    });
    this.deck.on("error", () => void this.close());
  }

  /** Something done on the deck: a dark deck only wakes (SD46); true when it did. */
  private woken(): boolean {
    this.activeAt = this.now();
    if (!this.asleep) return false;
    this.asleep = false;
    void this.light(this.view?.settings.brightness ?? 70);
    return true;
  }

  private async light(percent: number): Promise<void> {
    this.brightness = percent;
    try {
      await this.deck.setBrightness?.(percent);
    } catch {
      // A deck that cannot be dimmed is still a deck.
    }
  }

  /** One thing at a time, in order: the next press builds on the answer to this one. */
  private send(work: () => Promise<DeckView>): void {
    this.sending = this.sending.then(async () => {
      if (this.closed) return;
      try {
        await this.show(await work());
      } catch {
        await this.lost();
      }
    });
  }

  /** When everything sent so far has been answered and shown. */
  settled(): Promise<void> {
    return this.sending;
  }

  /** The blink every half second, and a key held long enough is a hold (SD29). */
  tick(): void {
    if (this.closed) return;
    const at = this.now();
    const minutes = this.view?.settings.sleep ?? 0;
    if (minutes && !this.asleep && at - this.activeAt >= minutes * 60_000) {
      // Släckning (SD46): dark after the owner's minutes without a press.
      this.asleep = true;
      void this.light(0);
    }
    for (const key of this.holds.tick(at)) this.send(() => this.api.press(this.serial, key, true));
    const phase = Math.floor(at / BLINK) % 2;
    if (phase !== this.phase) {
      this.phase = phase;
      for (const [index, painted] of this.painted) {
        const picture = painted.pictures[phase] ?? painted.pictures[0];
        if (painted.pictures.length > 1 && picture) void this.fill(index, picture);
      }
    }
  }

  private async follow(): Promise<void> {
    while (!this.closed) {
      const after = this.view?.revision ?? 0;
      try {
        const waited = await this.api.wait(this.serial, after, 25);
        if (this.closed) return;
        if (waited.changed || this.view?.revision === after || !this.contact) {
          const fresh = await this.api.view(this.serial);
          this.sending = this.sending.then(() => this.show(fresh));
          await this.sending;
        }
      } catch {
        await this.lost();
        await new Promise((done) => setTimeout(done, 2000));
      }
    }
  }

  /** The deck as TKL's server says: the keys whose face changed, and the strip or the info
   * line when theirs did. A reason's three seconds are read again when they run out. */
  async show(view: DeckView): Promise<void> {
    if (this.closed) return;
    const back = !this.contact;
    this.view = view;
    this.contact = true;
    this.holds.ms = view.hold_ms ?? 600;
    if (this.asleep && (view.keys ?? []).some((f) => f.type === "here")) {
      this.asleep = false; // Blinka lights a dark deck
      this.activeAt = this.now();
    }
    const wanted = view.settings.brightness ?? 70;
    if (!this.asleep && this.brightness !== wanted) await this.light(wanted);
    if (back) this.painted.clear();
    const faces: DeckFace[] = view.keys ?? [];
    const work: Promise<void>[] = [];
    for (const control of this.deck.modelInfo.controls.filter(isKey)) {
      const face = faces[control.index] ?? ({ type: "empty" } as DeckFace);
      const sig = JSON.stringify(face);
      if (this.painted.get(control.index)?.face === sig) continue;
      work.push(this.paintKey(control.index, control.pixelSize, face, sig));
    }
    const lcd = this.deck.modelInfo.controls.find(isLcd);
    if (lcd) work.push(this.paintLcd(lcd, view));
    await Promise.all(work);
    this.onChange(this);
    if ((view.refresh_ms ?? 15000) < 15000) {
      const at = view.revision;
      setTimeout(() => {
        if (!this.closed && this.view?.revision === at) this.send(() => this.api.view(this.serial));
      }, view.refresh_ms ?? 15000);
    }
  }

  private async paintKey(index: number, size: { width: number; height: number }, face: DeckFace, sig: string): Promise<void> {
    const phases = face.blink ? [0, 1] : [0];
    const pictures = await Promise.all(phases.map((p) => this.api.picture(keyPath(this.serial, index, size.width, size.height, p))));
    this.painted.set(index, { face: sig, pictures });
    const picture = pictures[face.blink ? this.phase : 0] ?? pictures[0];
    if (picture) await this.fill(index, picture);
  }

  private async paintLcd(lcd: StreamDeckLcdSegmentControlDefinition, view: DeckView): Promise<void> {
    const { width, height } = lcd.pixelSize;
    const strip = this.deck.modelInfo.controls.some(isDial);
    const sig = JSON.stringify(strip ? [view.strip, view.said, view.contact] : [view.info, view.contact]);
    if (sig === this.lcdDrawn) return;
    this.lcdDrawn = sig;
    const path = `${TKL}/deck/${encodeURIComponent(this.serial)}/${strip ? "strip" : "info"}.png?width=${width}&height=${height}`;
    const picture = await this.api.picture(path);
    await this.deck.fillLcd(lcd.index, picture.data, { format: "rgba" }).catch(() => this.close());
  }

  private async fill(index: number, picture: Pixels): Promise<void> {
    await this.deck.fillKeyBuffer(index, picture.data, { format: "rgba" }).catch(() => this.close());
  }

  /** Ingen kontakt (SD21): never an old state, and a hold half done is forgotten. */
  private async lost(): Promise<void> {
    if (this.closed || !this.contact) return;
    this.contact = false;
    this.holds = new Holds(this.holds.ms);
    this.painted.clear();
    this.lcdDrawn = "";
    const nothing = this.nothing;
    if (nothing) {
      for (const control of this.deck.modelInfo.controls.filter(isKey)) await this.fill(control.index, nothing);
    }
    const lcd = this.deck.modelInfo.controls.find(isLcd);
    if (lcd) {
      const dark = new Uint8ClampedArray(lcd.pixelSize.width * lcd.pixelSize.height * 4);
      await this.deck.fillLcd(lcd.index, dark, { format: "rgba" }).catch(() => {});
    }
    this.onChange(this);
  }

  /** Unplugged, or the page closes: let go of the deck and tell TKL. */
  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    if (this.timer) clearInterval(this.timer);
    this.deck.removeAllListeners();
    await this.api.close(this.serial).catch(() => {});
    await this.deck.close().catch(() => {});
    this.onChange(this);
  }

  /** After the browser says a device went: a deck that no longer answers is let go. */
  async check(): Promise<void> {
    if (this.closed) return;
    try {
      await this.deck.getSerialNumber();
    } catch {
      await this.close();
    }
  }
}

/** A picture fetched from TKL and decoded to RGBA in the browser. The ETag lets the browser keep
 * a picture it has: the same picture again is a 304. */
export async function fetchPixels(path: string): Promise<Pixels> {
  const response = await fetch(path, { credentials: "same-origin", cache: "no-cache" });
  if (!response.ok) throw Object.assign(new Error(`Bilden kom inte: ${response.status}`), { status: response.status });
  const bitmap = await createImageBitmap(await response.blob());
  const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Ingen canvas.");
  context.drawImage(bitmap, 0, 0);
  return { width: bitmap.width, height: bitmap.height, data: context.getImageData(0, 0, bitmap.width, bitmap.height).data };
}

/** The bridges of this page, one per deck, kept while the page lives: a deck shows the clock
 * while TKL is locked, and goes on when it is opened again (SD30). */
export const bridges = new Map<string, Bridge>();

type HidNavigator = Navigator & { hid?: { addEventListener: (type: "disconnect", listener: () => void) => void } };

/** WebHID is in Chrome and Edge, over https. */
export function hasHid(given: Navigator | undefined = typeof navigator === "undefined" ? undefined : navigator): boolean {
  return !!given && "hid" in given && !!(given as HidNavigator).hid;
}

let watching = false;

/** Opens each deck the user chose, or the ones the browser already allows, unless it is open
 * here already; says how each went. */
export async function connect(decks: HidDeck[], api: BridgeApi, onChange: (bridge: Bridge) => void): Promise<string[]> {
  if (!watching && hasHid()) {
    watching = true;
    (navigator as HidNavigator).hid?.addEventListener("disconnect", () => {
      for (const bridge of bridges.values()) void bridge.check();
    });
  }
  const said: string[] = [];
  for (const deck of decks) {
    const bridge = new Bridge(deck, api, onChange);
    try {
      const how = await bridge.start();
      if (how === "owned") {
        said.push(`${bridge.name}: ${OWNED}`);
        continue;
      }
      const before = bridges.get(bridge.serial);
      if (before && before !== bridge) await before.close();
      bridges.set(bridge.serial, bridge);
      said.push(`${bridge.name} är inkopplat med WebHID.`);
    } catch (error) {
      said.push(`${bridge.name} gick inte att koppla in: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  return said;
}

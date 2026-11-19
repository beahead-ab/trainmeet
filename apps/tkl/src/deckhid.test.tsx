// Stream Deck with WebHID (#86 del b, SD50), with a fake deck in place of @elgato-stream-deck's:
// the bridge opens the deck on TKL's server with its serial number and model, fills the keys
// from TKL's pictures and only those whose face changed, sends a press, a hold, the dials, the
// strip and Neo's touch points, says Ingen kontakt without TKL (SD21), never opens a deck TKL
// owns over USB, and lets go when the deck is unplugged. Where the browser has no WebHID a short
// line says so. A made-up station; nothing here names a real one (RS13).
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { DeckFace, DeckModelId, DeckOpen, Decks, DeckView } from "./api";
import { HidRow, modelName } from "./Deck";
import { Bridge, gridOf, MODELS, NOT_HERE, serialOf, type BridgeApi, type HidDeck, type Pixels } from "./deckhid";

type Control = Record<string, unknown> & { type: string; index: number };

function keys(columns: number, rows: number, size: number): Control[] {
  return Array.from({ length: columns * rows }, (_, i) => ({
    id: `button-${i}`,
    type: "button",
    row: Math.floor(i / columns),
    column: i % columns,
    index: i,
    hidIndex: i,
    feedbackType: "lcd",
    pixelSize: { width: size, height: size },
    bounds: { x: 0, y: 0, width: size, height: size },
  }));
}

const MODEL_CONTROLS: Record<string, () => Control[]> = {
  xl: () => keys(8, 4, 96),
  plus: () => [
    ...keys(4, 2, 120),
    { id: 0, type: "lcd-segment", row: 2, column: 0, columnSpan: 4, rowSpan: 1, index: 0, pixelSize: { width: 800, height: 100 }, drawRegions: true },
    ...[0, 1, 2, 3].map((i) => ({ id: `encoder-${i}`, type: "encoder", row: 3, column: i, index: i, hidIndex: i, hasLed: false, ledRingSteps: 0 })),
  ],
  neo: () => [
    ...keys(4, 2, 96),
    { id: "page-l", type: "button", row: 2, column: 0, index: 8, hidIndex: 8, feedbackType: "rgb" },
    { id: 0, type: "lcd-segment", row: 2, column: 1, columnSpan: 2, rowSpan: 1, index: 0, pixelSize: { width: 248, height: 58 }, drawRegions: false },
    { id: "page-r", type: "button", row: 2, column: 3, index: 9, hidIndex: 9, feedbackType: "rgb" },
  ],
  "galleon-k100": () => keys(3, 4, 72),
};

class FakeDeck {
  listeners = new Map<string, ((...args: unknown[]) => void)[]>();
  filled: [number, number][] = [];
  lcd: number[] = [];
  colours: number[] = [];
  closed = false;
  broken = false;
  modelInfo: HidDeck["modelInfo"];
  constructor(
    id: string,
    readonly serial = "SD0001",
  ) {
    this.modelInfo = { id, name: `Fake ${id}`, controls: MODEL_CONTROLS[id]?.() ?? [] } as unknown as HidDeck["modelInfo"];
  }
  getSerialNumber = async () => {
    if (this.closed) throw new Error("closed");
    return this.serial;
  };
  fillKeyBuffer = async (index: number, data: Uint8Array | Uint8ClampedArray) => {
    if (this.broken) throw new Error("unplugged");
    this.filled.push([index, data[0] ?? 0]);
  };
  fillKeyColor = async (index: number) => {
    this.colours.push(index);
  };
  fillLcd = async (index: number, data: Uint8Array | Uint8ClampedArray) => {
    this.lcd.push(data[0] ?? index);
  };
  clearPanel = async () => {};
  close = async () => {
    this.closed = true;
  };
  on = (event: string, listener: (...args: unknown[]) => void) => {
    this.listeners.set(event, [...(this.listeners.get(event) ?? []), listener]);
    return this;
  };
  removeAllListeners = () => {
    this.listeners.clear();
    return this;
  };
  emit(event: string, ...args: unknown[]): void {
    for (const listener of this.listeners.get(event) ?? []) listener(...args);
  }
  control(index: number, type = "button"): Control {
    const found = (this.modelInfo.controls as unknown as Control[]).find((c) => c.index === index && c.type === type);
    if (!found) throw new Error(`no ${type} ${index}`);
    return found;
  }
}

const GRID = { columns: 8, rows: 4, dials: 0, strip: false, info: false, touch: 0, pedals: 0 };
const face = (text: string, more: Partial<DeckFace> = {}): DeckFace => ({ type: "place", text, bg: "#000000", fg: "#f3f4f6", label: text, ...more }) as DeckFace;

function viewOf(serial: string, model: DeckModelId | null, faces: DeckFace[], more: Partial<DeckView> = {}): DeckView {
  return {
    settings: { serial, model, grid: { columns: 8, rows: 4 } },
    revision: 1,
    style: "column",
    keys: faces,
    hold_ms: 600,
    refresh_ms: 15000,
    locked: false,
    contact: true,
    info: "06:10  Nu",
    strip: [],
    said: "",
    ...more,
  } as unknown as DeckView;
}

/** TKL's API, recorded; a picture's first byte says which picture it is. */
class FakeApi implements BridgeApi {
  calls: string[] = [];
  fetched: string[] = [];
  opened: [string, DeckOpen][] = [];
  owned: string[] = [];
  faces: DeckFace[] = Array.from({ length: 36 }, (_, i) => face(`K${i}`));
  down = false;
  decks = async (): Promise<Decks> => ({ usb: true, usb_problem: null, decks: this.owned.map((serial) => ({ serial, model: "xl", name: "XL", grid: GRID, workplace: "1", connection: "usb", tried: false })) });
  open = async (serial: string, open: DeckOpen) => {
    this.opened.push([serial, open]);
    return viewOf(serial, open.model ?? null, this.faces);
  };
  view = async (serial: string) => viewOf(serial, null, this.faces);
  answer = async (serial: string, said: string) => {
    this.calls.push(said);
    if (this.down) throw new Error("Ingen kontakt med TKL.");
    return viewOf(serial, null, this.faces);
  };
  press = (serial: string, key: number, hold: boolean) => this.answer(serial, `press ${key}${hold ? " hold" : ""}`);
  dial = (serial: string, dial: number, turn: number, press: boolean) => this.answer(serial, `dial ${dial} ${turn}${press ? " press" : ""}`);
  touch = (serial: string, point: -1 | 1) => this.answer(serial, `touch ${point}`);
  wait = () => new Promise<never>(() => {});
  close = async (serial: string) => {
    this.calls.push(`close ${serial}`);
  };
  picture = async (path: string): Promise<Pixels> => {
    this.fetched.push(path);
    const mark = path.includes("ingen-kontakt") ? 99 : path.includes("phase=1") ? 2 : 1;
    return { width: 1, height: 1, data: new Uint8ClampedArray([mark, 0, 0, 255]) };
  };
}

async function started(id: string, api = new FakeApi(), serial = "SD0001") {
  const deck = new FakeDeck(id, serial);
  const clock = { now: 1000 };
  const bridge = new Bridge(deck as unknown as HidDeck, api, () => {}, () => clock.now);
  const how = await bridge.start();
  return { deck, api, bridge, clock, how };
}

describe("Stream Deck with WebHID (#86 del b, SD50)", () => {
  it("opens the deck on TKL's server with its serial number and model, and fills every key", async () => {
    const { deck, api, bridge, how } = await started("xl");
    expect(how).toBe("open");
    expect(api.opened).toEqual([["SD0001", { model: "xl", grid: null, workplace: null, connection: "webhid" }]]);
    expect(deck.filled.map(([i]) => i).sort((a, b) => a - b)).toEqual(Array.from({ length: 32 }, (_, i) => i));
    expect(api.fetched).toContain("/api/tkl/1/deck/SD0001/key/0.png?size=96");
    expect(api.fetched.filter((p) => p.includes("/key/")).length).toBe(32);
    await bridge.close();
  });

  it("fills only the keys whose face changed, and both colours of a blinking key", async () => {
    const { deck, api, bridge } = await started("xl");
    deck.filled = [];
    api.fetched = [];
    const faces = [...api.faces];
    faces[5] = face("Start", { frame: "#60a5fa" });
    faces[6] = face("Ny", { blink: "#3d3208" });
    await bridge.show(viewOf("SD0001", "xl", faces, { revision: 2 }));
    expect(deck.filled.map(([i]) => i).sort()).toEqual([5, 6]);
    expect(api.fetched).toEqual(["/api/tkl/1/deck/SD0001/key/5.png?size=96", "/api/tkl/1/deck/SD0001/key/6.png?size=96", "/api/tkl/1/deck/SD0001/key/6.png?size=96&phase=1"]);
    await bridge.close();
  });

  it("sends a press and a hold by the deck's hold time (SD29)", async () => {
    const { deck, api, bridge, clock } = await started("xl");
    deck.emit("down", deck.control(3));
    clock.now += 100;
    deck.emit("up", deck.control(3));
    await bridge.settled();
    deck.emit("down", deck.control(4));
    clock.now += 700;
    bridge.tick();
    deck.emit("up", deck.control(4));
    await bridge.settled();
    expect(api.calls).toEqual(["press 3", "press 4 hold"]);
    await bridge.close();
  });

  it("turns and presses the dials, taps and swipes the strip, and draws it (SD33, SD83)", async () => {
    const { deck, api, bridge } = await started("plus");
    expect(api.opened[0]?.[1].model).toBe("plus");
    expect(api.fetched).toContain("/api/tkl/1/deck/SD0001/strip.png?width=800&height=100");
    expect(deck.lcd.length).toBe(1);
    deck.emit("rotate", deck.control(1, "encoder"), 2);
    deck.emit("down", deck.control(0, "encoder"));
    deck.emit("lcdShortPress", deck.control(0, "lcd-segment"), { x: 650, y: 50 });
    deck.emit("lcdSwipe", deck.control(0, "lcd-segment"), { x: 600, y: 50 }, { x: 300, y: 50 });
    await bridge.settled();
    expect(api.calls).toEqual(["dial 1 2", "dial 0 0 press", "dial 3 0 press", "touch 1"]);
    await bridge.close();
  });

  it("turns the page with Neo's touch points and draws its info line (SD34, SD82)", async () => {
    const { deck, api, bridge } = await started("neo");
    expect(deck.colours).toEqual([8, 9]);
    expect(api.fetched).toContain("/api/tkl/1/deck/SD0001/info.png?width=248&height=58");
    deck.emit("down", deck.control(8));
    deck.emit("down", deck.control(9));
    await bridge.settled();
    expect(api.calls).toEqual(["touch -1", "touch 1"]);
    await bridge.close();
  });

  it("says Ingen kontakt on every key when TKL does not answer, never an old state (SD21)", async () => {
    const { deck, api, bridge, clock } = await started("xl");
    deck.filled = [];
    api.down = true;
    deck.emit("down", deck.control(0));
    clock.now += 50;
    deck.emit("up", deck.control(0));
    await bridge.settled();
    expect(bridge.contact).toBe(false);
    expect(deck.filled.length).toBe(32);
    expect(deck.filled.every(([, mark]) => mark === 99)).toBe(true);
    api.down = false;
    deck.filled = [];
    await bridge.show(viewOf("SD0001", "xl", api.faces, { revision: 3 }));
    expect(bridge.contact).toBe(true);
    expect(deck.filled.length).toBe(32);
    await bridge.close();
  });

  it("never opens a deck TKL owns over USB", async () => {
    const api = new FakeApi();
    api.owned = ["SD0001"];
    const { deck, how } = await started("xl", api);
    expect(how).toBe("owned");
    expect(api.opened).toEqual([]);
    expect(deck.closed).toBe(true);
  });

  it("lets go of the deck and tells TKL when it is unplugged", async () => {
    const { deck, api, bridge } = await started("xl");
    deck.broken = true;
    await bridge.show(viewOf("SD0001", "xl", [face("Annat")], { revision: 4 }));
    expect(bridge.closed).toBe(true);
    expect(deck.closed).toBe(true);
    expect(api.calls).toContain("close SD0001");
    const again = await started("xl");
    again.deck.closed = true;
    await again.bridge.check();
    expect(again.bridge.closed).toBe(true);
  });

  it("reads a deck TKL does not know by its grid (SD53), and the models and serials", async () => {
    const { api, bridge } = await started("galleon-k100");
    expect(api.opened[0]?.[1]).toEqual({ model: null, grid: { columns: 3, rows: 4, dials: 0, strip: false, info: false, touch: 0, pedals: 0 }, workplace: null, connection: "webhid" });
    await bridge.close();
    expect(gridOf(MODEL_CONTROLS.neo!() as never)).toMatchObject({ columns: 4, rows: 2, info: true, touch: 2 });
    expect(gridOf(MODEL_CONTROLS.plus!() as never)).toMatchObject({ columns: 4, rows: 2, dials: 4, strip: true });
    expect(MODELS["original-mk2-scissor"]).toBe("15");
    expect(MODELS["15-module-scissor"]).toBe("module-15");
    expect(serialOf("A1 B2/c3", "xl")).toBe("A1B2c3");
    expect(serialOf("", "xl")).toBe("hid-xl");
  });

  it("shows Anslut Stream Deck where the browser has WebHID, and a short line elsewhere", () => {
    const decks: Decks = { usb: true, usb_problem: null, decks: [{ serial: "XL1", model: "xl", name: "XL", grid: GRID, workplace: "1", connection: "usb", tried: false }] };
    const without = renderToStaticMarkup(<HidRow hid={false} decks={null} connected={[]} said={[]} />);
    expect(without).toContain(NOT_HERE);
    expect(without).not.toContain("Anslut Stream Deck");
    const withHid = renderToStaticMarkup(<HidRow hid decks={decks} connected={[{ serial: "SD1", name: "Stream Deck +", contact: false }]} said={["Stream Deck + är inkopplat med WebHID."]} />);
    expect(withHid).toContain("Anslut Stream Deck");
    expect(withHid).toContain("XL: Decket sköts av TKL över USB.");
    expect(withHid).toContain("Stream Deck + med WebHID: Ingen kontakt");
    expect(withHid).toContain("Koppla från");
    expect(modelName({ name: "Mini", tried: false })).toBe("Mini · Inte provad");
    expect(modelName({ name: "Mini", tried: true })).toBe("Mini");
  });
});

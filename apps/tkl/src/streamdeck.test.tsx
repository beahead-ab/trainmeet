// Studio › Inställningar › Stream Deck (#86 del c) on a made-up station, as TKL's server sends it:
// Sidor with drag and drop from Knappar and between cells, the chosen key's properties (SD43), the
// miniature that makes a snabbväg from a start and a goal (SD42), Föreslå (SD45), Att kolla (SD40)
// and Återställ; the pedal (SD55); Deck with Inte provad, Blinka and the settings (SD46, SD58); and
// Prova alla knappar with its progress and results (SD47). Nothing here names a real station (RS13).
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { DeckButton, DeckFace, DeckKey, DeckPage, DeckProva, Decks, DeckStudio, Panel } from "./api";
import { DeckTab, ProvaTab, SidorView, type DeckTabProps, type ProvaTabProps, type SidorProps } from "./StreamDeckStudio";
import { checkText, deckChange, dropped, edited, freeCell, fullKey, keyId, pageMoved, pageReset, pedalChosen, pedalKey, pedalValue, refOf, routeKey, whereToCheck } from "./streamdeck";

const panel: Panel = {
  source: "engine",
  width: 30,
  height: 9,
  cell: [24, 24],
  angle: "45",
  rows: 2,
  shortened: false,
  fields: [],
  lines: [
    { piece: "a", track: null, cells: [[3, 2], [10, 2]], real: [], free: false },
    { piece: "b", track: "1", cells: [[10, 2], [27, 2]], real: [], free: false },
  ],
  nodes: [],
  switches: [],
  signals: [
    { name: "In", type: "hsi", node: "In", cell: [5, 2], toward: [1, 0], symbol: [5, 2], label: [5, 0.9], side: "over", planned: false, real: null, real_toward: null },
    { name: "12", type: "hsi", node: "12", cell: [25, 2], toward: [1, 0], symbol: [25, 2], label: [25, 0.9], side: "over", planned: false, real: null, real_toward: null },
  ],
  labels: [],
  track_names: [],
  tables: [],
  platforms: [],
  building: null,
  real_box: null,
};

const key = (given: Partial<DeckKey> & Pick<DeckKey, "type">): DeckKey => fullKey(given);
const place = (id: string) => key({ type: "place", place: id });
const quick = (start: string, end: string, kind: "train" | "shunting" = "train") => key({ type: "route", route: { start, end, kind } });
const face = (text: string, more: Partial<DeckFace> = {}): DeckFace => ({ type: "place", text, bg: "#000000", fg: "#f3f4f6", label: `Plats ${text}`, ...more }) as DeckFace;
const FIXED = [10, 11, 12, 13, 14];
const fixedKeys = [key({ type: "action", action: "ankommit" }), key({ type: "action", action: "los" }), key({ type: "alarm" }), key({ type: "page" }), key({ type: "mode" })];

const platser: DeckPage = {
  name: "Platser",
  mode: "platser",
  kind: "platser",
  keys: [place("V"), place("1"), place("2"), place("O"), null, null, null, null, null, null, ...fixedKeys],
  listed: true,
  cancel: 10,
  part: null,
};
const signaler: DeckPage = { ...platser, name: "Signaler", kind: "signaler", keys: [key({ type: "signal", point: "In" }), key({ type: "signal", point: "12" }), ...Array(8).fill(null), ...fixedKeys] };
const faces = (page: DeckPage): DeckFace[] => page.keys.map((k) => (k ? face(k.place ?? k.point ?? k.type) : ({ type: "empty" } as DeckFace)));

const buttons: DeckButton[] = [
  { group: "trafiken", key: key({ type: "train", slot: 1 }), text: "Tågknapp", where: "Nu", missing: false, pieces: [] },
  { group: "tagvagar", key: quick("In", "12"), text: "In → 12", where: "start och mål · Signaler", missing: false, pieces: ["a", "b"] },
  { group: "vaxlingsvagar", key: quick("D", "22", "shunting"), text: "D → 22", where: "nås inte", missing: true, pieces: [] },
  { group: "platser", key: place("V"), text: "V", where: "Platser", missing: false, pieces: [] },
  { group: "funktioner", key: key({ type: "action", action: "los" }), text: "Lös ut", where: "fast rad", missing: false, pieces: [] },
];

function studioOf(more: Partial<DeckStudio> = {}): DeckStudio {
  return {
    size: "15",
    sizes: [
      { size: "mini", name: "Mini", grid: { columns: 3, rows: 2 }, decks: 0, deviations: 0, to_check: 0 },
      { size: "15", name: "Stream Deck 15", grid: { columns: 5, rows: 3 }, decks: 1, deviations: 1, to_check: 1 },
      { size: "pedal", name: "Pedal", grid: { columns: 0, rows: 0, pedals: 3 }, decks: 0, deviations: 0, to_check: 0 },
    ],
    profile: { model: "15", grid: { columns: 5, rows: 3, dials: 0, strip: false, info: false, touch: 0, pedals: 0 }, style: "row", fixed: FIXED, modes: ["platser"], pages: [platser, signaler], pedals: [] },
    pages: [
      { ref: refOf(platser), faces: faces(platser), changed: true },
      { ref: refOf(signaler), faces: faces(signaler), changed: false },
    ],
    deviations: [{ change: "flytta", page: refOf(platser), key: place("V"), cell: 0, text: null, under: null, press: null, hold: null, number: null, dim: null, confirm: null, mode: null, order: [], pedal: null }],
    saved: false,
    to_check: [{ deviation: 0, text: "Snabbvägen D → 22 finns inte i stationsmodellen.", page: refOf(signaler), key: key({ type: "signal", point: "12" }) }],
    checks: { routes: 11, reached: 10, quick: 1, problems: [{ kind: "nas-inte", text: "Växlingsvägen D → 22 nås inte från decket.", page: null, cell: null, route: { start: "D", end: "22", kind: "shunting" } }] },
    buttons,
    message: null,
    ...more,
  } as unknown as DeckStudio;
}

function sidor(more: Partial<SidorProps> = {}): SidorProps {
  return {
    studio: studioOf(),
    mode: "platser",
    page: 0,
    chosen: null,
    listed: null,
    filter: "",
    panel,
    start: null,
    lit: null,
    busy: false,
    said: "",
    problems: [],
    newPage: "",
    onSize: vi.fn(),
    onMode: vi.fn(),
    onPage: vi.fn(),
    onChoose: vi.fn(),
    onChooseButton: vi.fn(),
    onFilter: vi.fn(),
    onDrop: vi.fn(),
    onEdit: vi.fn(),
    onRemove: vi.fn(),
    onSignal: vi.fn(),
    onSuggest: vi.fn(),
    onResetPage: vi.fn(),
    onResetSize: vi.fn(),
    onSave: vi.fn(),
    onUndo: vi.fn(),
    onNewPage: vi.fn(),
    onAddPage: vi.fn(),
    onRemovePage: vi.fn(),
    onMovePage: vi.fn(),
    onPedal: vi.fn(),
    onForgetChange: vi.fn(),
    onGo: vi.fn(),
    onProblem: vi.fn(),
    ...more,
  };
}

type Element = ReactElement<Record<string, unknown>>;

/** Every element the view draws, the function components called as React would. */
function elements(node: ReactNode): Element[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!isValidElement(node)) return [];
  const props = node.props as { children?: ReactNode };
  if (typeof node.type === "function") return elements((node.type as (p: unknown) => ReactNode)(node.props));
  return [node as Element, ...elements(props.children)];
}

const text = (e: Element): string => {
  const children = e.props.children as ReactNode;
  const flat = (n: ReactNode): string => (Array.isArray(n) ? n.map(flat).join("") : typeof n === "string" || typeof n === "number" ? String(n) : isValidElement(n) ? flat((n.props as { children?: ReactNode }).children) : "");
  return flat(children);
};
const buttonsNamed = (all: Element[], name: string) => all.filter((e) => e.type === "button" && text(e).includes(name));
const cell = (all: Element[], at: number) => all.find((e) => e.props["data-cell"] === at) as Element;
const dropEvent = (data: unknown) => ({ preventDefault: vi.fn(), dataTransfer: { getData: () => JSON.stringify(data), setData: vi.fn() } });

describe("Sidor: drag and drop (SD41)", () => {
  it("adds from Knappar, moves within the page, and leaves the fixed row alone", () => {
    const moved = dropped([], platser, FIXED, place("V"), 7);
    expect(moved).toHaveLength(1);
    expect(moved[0]).toMatchObject({ change: "flytta", page: { kind: "platser", name: "Platser" }, cell: 7 });
    expect(moved[0]?.key?.place).toBe("V");
    const added = dropped([], platser, FIXED, quick("In", "12"), 5);
    expect(added.map((d) => d.change)).toEqual(["lagg-till"]);
    expect(added[0]?.key?.route).toEqual({ start: "In", end: "12", kind: "train" });
    const replaced = dropped([], platser, FIXED, quick("In", "12"), 2);
    expect(replaced.map((d) => [d.change, d.key?.place ?? d.key?.type])).toEqual([
      ["ta-bort", "2"],
      ["lagg-till", "route"],
    ]);
    expect(dropped([], platser, FIXED, quick("In", "12"), 12)).toEqual([]);
    expect(dropped([], platser, FIXED, place("V"), 0)).toEqual([]);
  });

  it("gives the dropped row or cell to the page, not on the fixed row", () => {
    const props = sidor();
    const all = elements(SidorView(props));
    const target = cell(all, 6);
    (target.props.onDrop as (e: unknown) => void)(dropEvent({ from: "list", index: 1 }));
    expect(props.onDrop).toHaveBeenCalledWith(6, { from: "list", index: 1 });
    (cell(all, 12).props.onDrop as (e: unknown) => void)(dropEvent({ from: "cell", cell: 0 }));
    expect(props.onDrop).toHaveBeenCalledTimes(1);
    expect(cell(all, 0).props.draggable).toBe(true);
    expect(cell(all, 12).props.draggable).toBe(false);
    expect(cell(all, 4).props.draggable).toBe(false);
    const set = vi.fn();
    (cell(all, 1).props.onDragStart as (e: unknown) => void)({ dataTransfer: { setData: set } });
    expect(set).toHaveBeenCalledWith("text/plain", JSON.stringify({ from: "cell", cell: 1 }));
    const row = all.find((e) => e.props.className === "sds-rad" && text(e).includes("In → 12")) as Element;
    (row.props.onDragStart as (e: unknown) => void)({ dataTransfer: { setData: set } });
    expect(set).toHaveBeenLastCalledWith("text/plain", JSON.stringify({ from: "list", index: 1 }));
  });

  it("puts a chosen row on the cell clicked, and marks the empty ones Släpp här", () => {
    const props = sidor({ listed: 1 });
    const all = elements(SidorView(props));
    expect(cell(all, 5).props["aria-label"]).toBe("Släpp här");
    (cell(all, 5).props.onClick as () => void)();
    expect(props.onDrop).toHaveBeenCalledWith(5, { from: "list", index: 1 });
    const markup = renderToStaticMarkup(<SidorView {...props} />);
    expect(markup).toContain("nås inte");
    expect(markup).toContain("Tågvägar · 1");
  });
});

describe("Sidor: the chosen key's properties (SD43)", () => {
  it("changes the text, press, hold and what a snabbväg shows, and says the colours are locked", () => {
    const withQuick: DeckPage = { ...platser, keys: platser.keys.map((k, i) => (i === 4 ? quick("In", "12") : k)) };
    const studio = studioOf({ profile: { ...studioOf().profile, pages: [withQuick, signaler] } });
    const props = sidor({ studio, chosen: 4 });
    const all = elements(SidorView(props));
    const markup = renderToStaticMarkup(<SidorView {...props} />);
    expect(markup).toContain("Snabbväg");
    expect(markup).toContain("In → 12 · tågväg");
    expect(markup).toContain("Färgerna och symbolerna följer standarden");
    expect(markup).toContain("Som katalogen: Lägg vägen");
    const press = all.find((e) => e.type === "select" && e.props["aria-label"] === "Tryck") as Element;
    (press.props.onChange as (e: unknown) => void)({ target: { value: "kor" } });
    expect(props.onEdit).toHaveBeenLastCalledWith({ press: "kor" });
    const options = (press.props.children as ReactNode[]).flat() as Element[];
    expect(options.map((o) => o.props.value)).not.toContain("noll");
    const textField = all.find((e) => e.type === "input" && e.props["aria-label"] === "Text") as Element;
    (textField.props.onBlur as (e: unknown) => void)({ target: { value: "In 12" } });
    expect(props.onEdit).toHaveBeenLastCalledWith({ text: "In 12" });
    const shows = all.filter((e) => e.type === "input" && e.props.type === "checkbox");
    expect(shows).toHaveLength(3);
    (shows[0]?.props.onChange as (e: unknown) => void)({ target: { checked: false } });
    expect(props.onEdit).toHaveBeenLastCalledWith({ number: false });
    (buttonsNamed(all, "Ta bort från sidan")[0]?.props.onClick as () => void)();
    expect(props.onRemove).toHaveBeenCalled();
    expect(edited([], withQuick, quick("In", "12"), { press: "kor", text: "In 12" })).toMatchObject([{ change: "andra", press: "kor", text: "In 12", hold: null }]);
  });

  it("locks what press and hold do on a place, and the fixed row's keys", () => {
    const place0 = renderToStaticMarkup(<SidorView {...sidor({ chosen: 0 })} />);
    expect(place0).toContain("Låst: plats gör det katalogen säger");
    const fixed = sidor({ chosen: 14 });
    const all = elements(SidorView(fixed));
    expect(buttonsNamed(all, "Ta bort från sidan")[0]?.props.disabled).toBe(true);
    expect(renderToStaticMarkup(<SidorView {...fixed} />)).toContain("Den fasta raden är densamma på alla sidor");
  });
});

describe("Sidor: the miniature makes a snabbväg (SD42)", () => {
  it("has the signals as buttons, shows the chosen start, and finds the route between two", () => {
    const props = sidor({ start: "In" });
    const all = elements(SidorView(props));
    const twelve = all.find((e) => e.props["data-signal"] === "12" && e.props.role === "button") as Element;
    (twelve.props.onClick as () => void)();
    expect(props.onSignal).toHaveBeenCalledWith("12");
    const markup = renderToStaticMarkup(<SidorView {...props} />);
    expect(markup).toContain("Start In: klicka målet.");
    expect(markup).toContain('class="signal hsi valbar markerad"');
    expect(routeKey(buttons, "In", "12")?.route).toEqual({ start: "In", end: "12", kind: "train" });
    expect(routeKey(buttons, "D", "22")?.route?.kind).toBe("shunting");
    expect(routeKey(buttons, "12", "In")).toBeNull();
    expect(freeCell(platser, FIXED)).toBe(4);
    expect(freeCell({ ...platser, keys: platser.keys.map((k) => k ?? place("X")) }, FIXED)).toBeNull();
  });

  it("draws the chosen key's route in the miniature", () => {
    const lit = { kind: "train" as const, start: "In", end: "12", pieces: ["a", "b"], positions: {}, turntable: null };
    const markup = renderToStaticMarkup(<SidorView {...sidor({ lit })} />);
    expect(markup).toContain('class="vag-linje tagvag"');
    expect(markup.match(/data-piece="a"/g)).toHaveLength(2);
  });
});

describe("Sidor: Föreslå, Att kolla, the checks and Återställ (SD40, SD44, SD45)", () => {
  it("suggests a page by each rule", () => {
    const props = sidor();
    const all = elements(SidorView(props));
    for (const [name, rule] of [
      ["Geografiskt", "geografiskt"],
      ["Dagens vägar", "dagens"],
      ["Mest använda", "mest-anvanda"],
    ] as const) {
      (buttonsNamed(all, name)[0]?.props.onClick as () => void)();
      expect(props.onSuggest).toHaveBeenLastCalledWith(rule);
    }
  });

  it("lists Att kolla and the problems, each clickable, and the checks in words", () => {
    const props = sidor();
    const markup = renderToStaticMarkup(<SidorView {...props} />);
    expect(markup).toContain("Att kolla.");
    expect(markup).toContain("Snabbvägen D → 22 finns inte i stationsmodellen.");
    expect(markup).toContain("1 av 11 vägar nås inte från decket");
    expect(markup).toContain("Förval ur stationen · 1 egen ändring");
    const all = elements(SidorView(props));
    (buttonsNamed(all, "Visa")[0]?.props.onClick as () => void)();
    expect(props.onGo).toHaveBeenCalledWith(1, 1);
    (buttonsNamed(all, "Ta bort ändringen")[0]?.props.onClick as () => void)();
    expect(props.onForgetChange).toHaveBeenCalledWith(0);
    (buttonsNamed(all, "nås inte från decket")[0]?.props.onClick as () => void)();
    expect(props.onProblem).toHaveBeenCalledWith(expect.objectContaining({ kind: "nas-inte" }));
    expect(checkText({ routes: 11, reached: 11, quick: 2, problems: [] })).toEqual({ ok: true, text: "Alla 11 vägar nås · 2 som snabbväg" });
    expect(whereToCheck(studioOf().profile, studioOf().to_check![0]!)).toEqual({ page: 1, cell: 1 });
  });

  it("resets a page, the whole size, and saves", () => {
    const own = { kind: "egen" as const, name: "Mina" };
    const deviations = [
      ...dropped([], platser, FIXED, place("V"), 7),
      ...dropped([], signaler, FIXED, quick("In", "12"), 5),
      ...pageMoved([], studioOf().profile, signaler, -1),
      { ...dropped([], platser, FIXED, quick("In", "12"), 5)[0]!, page: own },
    ];
    expect(pageReset(deviations, refOf(platser)).map((d) => d.change)).toEqual(["lagg-till", "lagg-till"]);
    expect(pageReset(deviations, own)).toHaveLength(3);
    const props = sidor();
    const all = elements(SidorView(props));
    (buttonsNamed(all, "Återställ sidan")[0]?.props.onClick as () => void)();
    (buttonsNamed(all, "Återställ hela storleken")[0]?.props.onClick as () => void)();
    (buttonsNamed(all, "Spara")[0]?.props.onClick as () => void)();
    expect(props.onResetPage).toHaveBeenCalled();
    expect(props.onResetSize).toHaveBeenCalled();
    expect(props.onSave).toHaveBeenCalled();
    const saved = elements(SidorView(sidor({ studio: studioOf({ saved: true }) })));
    expect(buttonsNamed(saved, "Spara")[0]?.props.disabled).toBe(true);
    expect(buttonsNamed(saved, "Ångra")).toHaveLength(0);
  });

  it("moves a page among its mode's pages", () => {
    const moved = pageMoved([], studioOf().profile, signaler, -1);
    expect(moved[0]).toMatchObject({ change: "ordning", order: [refOf(signaler), refOf(platser)] });
    expect(pageMoved([], studioOf().profile, platser, -1)).toEqual([]);
  });

  it("is the same key wherever it is, by what it is", () => {
    expect(keyId(quick("In", "12"))).toBe(keyId({ ...quick("In", "12"), text: "In 12", press: "kor" }));
    expect(keyId(quick("In", "12"))).not.toBe(keyId(quick("In", "22")));
  });
});

describe("Sidor: the pedal (SD55)", () => {
  it("has three pedals that do nothing until chosen, and never Lös ut alla, Noll or Nödutlösning", () => {
    const pedal = studioOf({
      size: "pedal",
      profile: { model: "pedal", grid: { columns: 0, rows: 0, dials: 0, strip: false, info: false, touch: 0, pedals: 3 }, style: "none", fixed: [], modes: [], pages: [], pedals: [null, null, null] } as unknown as DeckStudio["profile"],
      pages: [],
    });
    const props = sidor({ studio: pedal, mode: null });
    const markup = renderToStaticMarkup(<SidorView {...props} />);
    expect(markup).toContain("Pedalen har ingen skärm och inget förval");
    const all = elements(SidorView(props));
    const values = all.filter((e) => e.type === "option").map((e) => e.props.value);
    expect(values).toContain("action:ankommit");
    for (const never of ["action:los-alla", "action:noll", "action:nodutlosning"]) expect(values).not.toContain(never);
    const selects = all.filter((e) => e.type === "select");
    expect(selects).toHaveLength(3);
    (selects[1]?.props.onChange as (e: unknown) => void)({ target: { value: "route:train:In:12" } });
    expect(props.onPedal).toHaveBeenCalledWith(1, "route:train:In:12");
    expect(pedalKey("route:train:In:12")?.route).toEqual({ kind: "train", start: "In", end: "12" });
    expect(pedalValue(pedalKey("action:ankommit"))).toBe("action:ankommit");
    expect(pedalKey("")).toBeNull();
    const chosen = pedalChosen(pedalChosen([], 1, pedalKey("action:los")), 1, null);
    expect(chosen).toHaveLength(1);
    expect(chosen[0]).toMatchObject({ change: "pedal", pedal: 1, key: null });
  });
});

describe("Deck (SD46, SD58, SD35, SD36)", () => {
  const decks: Decks = {
    usb: true,
    usb_problem: null,
    decks: [
      { serial: "XL0001", model: "xl", name: "XL", grid: { columns: 8, rows: 4, dials: 0, strip: false, info: false, touch: 0, pedals: 0 }, workplace: "1", connection: "usb", tried: false, settings: null, blinking: false },
      {
        serial: "skarm-1",
        model: "15",
        name: "Stream Deck 15",
        grid: { columns: 5, rows: 3, dials: 0, strip: false, info: false, touch: 0, pedals: 0 },
        workplace: "1",
        connection: null,
        tried: true,
        settings: { serial: "skarm-1", name: "Tågen", brightness: 40, hold: "lang", sleep: 10, lock_key: true, opens_on: "Alla", workplace: "1" },
        blinking: true,
      },
    ],
  } as unknown as Decks;
  const deckProps = (more: Partial<DeckTabProps> = {}): DeckTabProps => ({
    decks,
    chosen: "skarm-1",
    pages: ["Platser", "Alla"],
    hid: true,
    said: [],
    busy: false,
    onChoose: vi.fn(),
    onConnect: vi.fn(),
    onBlink: vi.fn(),
    onChange: vi.fn(),
    onForget: vi.fn(),
    ...more,
  });

  it("lists the decks with their connection and Inte provad, and Blinka finds one", () => {
    const props = deckProps();
    const markup = renderToStaticMarkup(<DeckTab {...props} />);
    expect(markup).toContain("Inkopplat över USB");
    expect(markup).toContain("Decket sköts av TKL över USB.");
    expect(markup).toContain("Inte inkopplat");
    expect((markup.match(/Inte provad</g) ?? []).length).toBe(1);
    expect(markup).toContain(">Tågen<");
    expect(markup).toContain("Blinkar …");
    expect(markup).toContain("Koppla in ett deck");
    const all = elements(DeckTab(props));
    const blink = buttonsNamed(all, "Blinka");
    expect(blink[0]?.props.disabled).toBe(false);
    expect(blink[1]?.props.disabled).toBe(true);
    (blink[0]?.props.onClick as () => void)();
    expect(props.onBlink).toHaveBeenCalledWith("XL0001");
    (buttonsNamed(all, "Koppla in ett deck")[0]?.props.onClick as () => void)();
    expect(props.onConnect).toHaveBeenCalled();
    expect(renderToStaticMarkup(<DeckTab {...deckProps({ hid: false, decks: { ...decks, usb: false } })} />)).toContain("WebHID");
  });

  it("sets brightness, hold, sleep, the lock key, the start page and the workplace, and forgets a deck", () => {
    const props = deckProps();
    const all = elements(DeckTab(props));
    const by = (label: string) => all.find((e) => e.props["aria-label"] === label) as Element;
    expect(by("Ljusstyrka").props.value).toBe(40);
    (by("Ljusstyrka").props.onChange as (e: unknown) => void)({ target: { value: "55" } });
    expect(props.onChange).toHaveBeenLastCalledWith("skarm-1", { brightness: 55 });
    (by("Hålltid").props.onChange as (e: unknown) => void)({ target: { value: "kort" } });
    expect(props.onChange).toHaveBeenLastCalledWith("skarm-1", { hold: "kort" });
    (by("Släckning").props.onChange as (e: unknown) => void)({ target: { value: "30" } });
    expect(props.onChange).toHaveBeenLastCalledWith("skarm-1", { sleep: 30 });
    (by("Startsida").props.onChange as (e: unknown) => void)({ target: { value: "" } });
    expect(props.onChange).toHaveBeenLastCalledWith("skarm-1", { opens_on: "" });
    (by("Arbetsplats").props.onBlur as (e: unknown) => void)({ target: { value: "2" } });
    expect(props.onChange).toHaveBeenLastCalledWith("skarm-1", { workplace: "2" });
    (buttonsNamed(all, "Glöm decket")[0]?.props.onClick as () => void)();
    expect(props.onForget).toHaveBeenCalledWith("skarm-1");
    expect(deckChange({ brightness: 55 })).toEqual({ name: null, brightness: 55, hold: null, sleep: null, lock_key: null, opens_in: null, opens_on: null, workplace: null });
  });
});

describe("Prova alla knappar (SD47)", () => {
  const prova = (more: Partial<DeckProva>): DeckProva =>
    ({ size: "15", running: false, done: 0, total: 0, did: 0, refused: 0, nothing: 0, keys: [], started: null, finished: null, message: null, ...more }) as DeckProva;
  const provaProps = (more: Partial<ProvaTabProps> = {}): ProvaTabProps => ({
    size: "15",
    sizes: [{ size: "15", name: "Stream Deck 15" }],
    prova: null,
    pages: 2,
    favourites: null,
    onSize: vi.fn(),
    onStart: vi.fn(),
    onStop: vi.fn(),
    onGo: vi.fn(),
    ...more,
  });

  it("starts, shows the progress while it runs, and can be stopped", () => {
    const idle = provaProps();
    (buttonsNamed(elements(ProvaTab(idle)), "Prova alla knappar").at(-1)?.props.onClick as () => void)();
    expect(idle.onStart).toHaveBeenCalled();
    const running = provaProps({ prova: prova({ running: true, done: 7, total: 20, message: "Provar knapp 7 av 20 …" }) });
    const markup = renderToStaticMarkup(<ProvaTab {...running} />);
    expect(markup).toContain('<progress max="20" value="7"');
    expect(markup).toContain("Provar knapp 7 av 20 …");
    (buttonsNamed(elements(ProvaTab(running)), "Stoppa")[0]?.props.onClick as () => void)();
    expect(running.onStop).toHaveBeenCalled();
  });

  it("reports per key: did, refused with the reason, or did nothing, and leads to the key", () => {
    const done = provaProps({
      prova: prova({
        total: 3,
        done: 3,
        did: 1,
        refused: 1,
        nothing: 1,
        message: "1 av 3 knappar fick nej av ställverket.",
        keys: [
          { page: 0, page_name: "Platser", cell: 5, label: "In→12", result: "nej", said: "Spårledningen 2 är belagd." },
          { page: 0, page_name: "Platser", cell: 11, label: "Lös ut", result: "inget", said: "Inga vägar att lösa ut." },
          { page: 1, page_name: "Signaler", cell: 0, label: "Signal In", result: "gick", said: "Valde start In: 2 mål." },
        ],
      }),
      favourites: { pinned: [], counted: [{ start: "In", end: "12", kind: "train", count: 4 }], shown: [] },
    });
    const markup = renderToStaticMarkup(<ProvaTab {...done} />);
    expect(markup).toContain("knappar på 2 sidor");
    expect(markup).toContain('data-result="nej"');
    expect(markup).toContain("Spårledningen 2 är belagd.");
    expect(markup).toContain("Inga vägar att lösa ut.");
    expect(markup).toContain("Prova igen");
    expect(markup).toContain("In→12");
    (buttonsNamed(elements(ProvaTab(done)), "In→12")[0]?.props.onClick as () => void)();
    expect(done.onGo).toHaveBeenCalledWith(0, 5);
  });
});

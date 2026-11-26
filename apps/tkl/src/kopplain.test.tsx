import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { handlers, KopplaInView, type Handlers } from "./KopplaIn";
import { addressText, changeOf, connectAsk, counts, editOf, learnLabel, where, type Calls, type KopplaIn, type KopplaObject, type Listen, type Port } from "./kopplain";

// Studio › Koppla in (#85) on the made-up Provby, as TKL's server sends it: switches 1 and 2 at
// their numbers, the entry signal In, track 1 and track 2, against the pretend LocoNet. Nothing
// here names a real station (RS13).

const object = (o: Partial<KopplaObject> & Pick<KopplaObject, "kind" | "name" | "state">): KopplaObject => ({
  address: null,
  default: false,
  reversed: false,
  feedback: null,
  straight: null,
  diverging: null,
  control: null,
  card: null,
  module: null,
  channel: null,
  note: null,
  drop_delay: null,
  ...o,
});

const objects: KopplaObject[] = [
  object({ kind: "switch", name: "1", state: "green", address: 1, feedback: "card", control: "tkl", card: 1, module: "M01", channel: 1 }),
  object({ kind: "switch", name: "2", state: "yellow", address: 2, default: true, control: "tkl", note: "Adressen är växelns nummer, som förval." }),
  object({ kind: "switch", name: "10", state: "without", control: "manual", note: "Manuell: läggs för hand." }),
  object({ kind: "signal", name: "In", state: "grey" }),
  object({ kind: "track_circuit", name: "Spår 1", state: "green", address: 3 }),
  object({ kind: "track_circuit", name: "Spår 2", state: "grey" }),
];

const quiet: KopplaIn = {
  loconet: { available: true, reason: null, connected: false, type: null, port: null, channel: null, label: null, error: null, since: null },
  level: 2,
  level_3: { on: false, possible: false, reason: "Rätta det som står nedan först.", problems: ["Växel 2 saknar återrapport: välj från kortet, två givare, ingen eller manuell."] },
  cards: [],
  discovered: null,
  objects,
  question: null,
  learning: null,
  message: null,
};

const connected: KopplaIn = {
  ...quiet,
  loconet: { ...quiet.loconet, connected: true, type: "pretend", port: "latsas", label: "LocoNet ej ansluten · låtsas-LocoNet", since: "2026-11-18T12:00:00Z" },
  cards: [
    {
      address: 1,
      name: "MGP servokort med ingångar",
      manufacturer: 126,
      developer: 1,
      product: 9,
      serial: 100,
      base: 1,
      module: "M01",
      channels: [
        { channel: 1, address: 1, objects: ["växel 1"] },
        { channel: 2, address: 2, objects: ["växel 2"] },
      ],
    },
  ],
  discovered: "2026-11-18T12:00:05Z",
  learning: { kind: "track_circuit", name: "Spår 2", text: "Ställ en vagn på Spår 2." },
};

const asking: KopplaIn = {
  ...connected,
  question: {
    id: 4,
    kind: "track_circuit",
    object: "Spår 2",
    address: 4,
    text: "Givaren 4 slog till. Är det Spår 2?",
    seen: null,
    answers: [
      { value: "yes", label: "Ja" },
      { value: "no", label: "Nej" },
    ],
    choices: ["Vx1", "Vx2"],
  },
};

const ports: Port[] = [
  { type: "locobuffer", port: "/dev/serial/by-id/usb-RR-CirKits_LocoBuffer-USB-if00", label: "usb-RR-CirKits_LocoBuffer-USB-if00" },
  { type: "pretend", port: "latsas", label: "Låtsas-LocoNet: LocoNet ej ansluten, som Prova använder" },
];

const nothing: Handlers = {
  onConnect: () => undefined,
  onDisconnect: () => undefined,
  onDiscover: () => undefined,
  onModule: () => undefined,
  onChange: () => undefined,
  onLearn: () => undefined,
  onAnswer: () => undefined,
  onLevel: () => undefined,
  onWagon: () => undefined,
  onListen: () => undefined,
  onError: () => undefined,
};

const render = (view: KopplaIn, listen: Listen | null = null) => renderToStaticMarkup(<KopplaInView view={view} ports={ports} listen={listen} {...nothing} />);

/** Calls that answer with the next view and remember what was asked. */
function pretend(next: KopplaIn) {
  const asked: string[] = [];
  const answer =
    (name: string) =>
    (...args: unknown[]) => {
      asked.push(`${name}(${args.map((a) => JSON.stringify(a)).join(", ")})`);
      return Promise.resolve(next);
    };
  const calls: Calls = {
    view: answer("view"),
    ports: () => Promise.resolve(ports),
    connect: answer("connect"),
    disconnect: answer("disconnect"),
    discover: answer("discover"),
    module: answer("module"),
    change: answer("change"),
    learn: answer("learn"),
    answer: answer("answer"),
    level: answer("level"),
    listen: () => Promise.resolve({ connected: true, messages: [] }),
    wagon: answer("wagon"),
  };
  const views: KopplaIn[] = [];
  const failed: string[] = [];
  const done = handlers(
    calls,
    (work) => void work().then((v) => views.push(v)),
    (m) => failed.push(m),
    () => undefined,
  );
  return { asked, views, failed, done };
}

describe("Koppla in", () => {
  it("connects through the port list: LocoBuffer USB, BTLocoBridge or the pretend LocoNet (STUDIO-11, STUDIO-22)", async () => {
    const html = render(quiet);
    expect(html).toContain("<h1>Koppla in</h1>");
    expect(html).toContain("LocoBuffer USB");
    expect(html).toContain("BTLocoBridge");
    expect(html).toContain("Låtsas-LocoNet (LocoNet ej ansluten)");
    expect(html).toContain("usb-RR-CirKits_LocoBuffer-USB-if00");
    expect(html).toContain(">Anslut</button>");
    expect(connectAsk("pretend", "", 1)).toEqual({ port: null, channel: 1 });
    expect(connectAsk("locobuffer", "/dev/ttyACM0", 1)).toEqual({ port: "/dev/ttyACM0", channel: 1 });
    expect(connectAsk("locobuffer", "COM3", 1)).toEqual({ error: "LocoBufferns port ligger under /dev." });
    expect(connectAsk("btlocobridge", "AA:BB", 1)).toEqual({ error: "Ange adressen som AA:BB:CC:DD:EE:FF, eller en port under /dev." });
    expect(connectAsk("btlocobridge", "AA:BB:CC:DD:EE:FF", 31)).toEqual({ error: "Kanalen är 1–30." });
    const { asked, views, done } = pretend(connected);
    done.onConnect("pretend", null, 1);
    await Promise.resolve();
    expect(asked).toEqual(['connect("pretend", null, 1)']);
    expect(views[0]?.loconet.connected).toBe(true);
    const shown = render(connected);
    expect(shown).toContain("LocoNet ej ansluten · låtsas-LocoNet");
    expect(shown).toContain(">Discover</button>");
    expect(shown).toContain(">Koppla från</button>");
  });

  it("shows that the cloud never has LocoNet (TKLMOLN-08)", () => {
    const cloud: KopplaIn = { ...quiet, loconet: { ...quiet.loconet, available: false, reason: "TKL i molnet har aldrig LocoNet." } };
    const html = render(cloud);
    expect(html).toContain("TKL i molnet har aldrig LocoNet.");
    expect(html).not.toContain(">Anslut</button>");
  });

  it("shows the MGP cards with module and channel, and every object's card (STUDIO-18)", async () => {
    const html = render(connected);
    expect(html).toContain("MGP servokort med ingångar");
    expect(html).toContain('value="M01"');
    expect(html).toContain('<span class="tm-mono">1:1</span> växel 1');
    expect(html).toContain("Kort 1 · M01 · kanal 1");
    expect(where(objects[0] as KopplaObject)).toBe("Kort 1 · M01 · kanal 1");
    const { asked, done } = pretend(connected);
    done.onDiscover();
    done.onModule(1, "M02");
    expect(asked).toEqual(["discover()", 'module(1, "M02")']);
  });

  it("shows every object in one of the four states (STUDIO-17), and Utan adress for a manual switch", () => {
    const html = render(connected);
    expect(html).toContain("Grön · bekräftad på banan: 2");
    expect(html).toContain("Gul · adress angiven: 1");
    expect(html).toContain("Grå · ej kopplad: 2");
    expect(html).toContain("Utan adress: 1");
    expect(html).toContain('<tr class="objekt utan"><td><strong>10</strong>');
    expect(html).toContain("Manuell: läggs för hand.");
    expect(counts(objects)).toEqual([
      ["green", 2],
      ["yellow", 1],
      ["grey", 2],
      ["without", 1],
    ]);
    expect(addressText(objects[1] as KopplaObject)).toBe("2 (förval)");
    expect(addressText(objects[3] as KopplaObject)).toBe("ingen");
    expect(learnLabel("switch")).toBe("Lägg om");
    expect(learnLabel("signal")).toBe("Skicka kör");
    expect(html).toContain(">Lägg om</button>");
    expect(html).toContain(">Skicka kör</button>");
    expect(html).toContain("Vagn på");
  });

  it("asks the learning question as it comes, and the answer confirms it (STUDIO-04)", async () => {
    const html = render(asking);
    expect(html).toContain("Givaren 4 slog till. Är det Spår 2?");
    expect(html).toContain('role="alertdialog"');
    expect(html).toContain(">Ja</button>");
    expect(html).toContain(">Nej</button>");
    expect(html).toContain('<option value="Vx1">Vx1</option>');
    const green: KopplaIn = {
      ...connected,
      question: null,
      learning: null,
      message: "Spår 2 är grön: givare 4.",
      objects: objects.map((o) => (o.name === "Spår 2" ? { ...o, state: "green", address: 4 } : o)),
    };
    const { asked, views, done } = pretend(green);
    done.onAnswer(4, "yes", null);
    done.onAnswer(4, "yes", "Vx1");
    await Promise.resolve();
    expect(asked).toEqual(['answer(4, "yes", null)', 'answer(4, "yes", "Vx1")']);
    const after = render(views[0] as KopplaIn);
    expect(after).toContain("Spår 2 är grön: givare 4.");
    expect(after).not.toContain("alertdialog");
    expect(after).toContain("Grön · bekräftad på banan: 3");
  });

  it("learns a track by a wagon on the pretend LocoNet, a switch by Lägg om and a signal by Skicka kör", () => {
    expect(render(connected)).toContain("Ställ en vagn på Spår 2. Koppla in lyssnar efter givaren som slår till.");
    expect(render(connected)).toContain("Ställ en vagn (låtsas)");
    const { asked, done } = pretend(connected);
    done.onLearn("switch", "2");
    done.onLearn("signal", "In");
    done.onLearn("track_circuit", "Spår 2");
    done.onWagon("Spår 2", true);
    expect(asked).toEqual(['learn("switch", "2")', 'learn("signal", "In")', 'learn("track_circuit", "Spår 2")', 'wagon("Spår 2", true)']);
  });

  it("changes an address, the polarity, the feedback or Utan adress, and turns level 3 on", () => {
    const yellow = objects[1] as KopplaObject;
    const edit = { ...editOf(yellow), address: "12", reversed: true, feedback: "sensors" as const, straight: "41", diverging: "42" };
    expect(changeOf(yellow, edit)).toEqual({
      change: { kind: "switch", name: "2", address: 12, without: false, reversed: true, feedback: "sensors", straight: 41, diverging: 42, drop_delay: null },
    });
    expect(changeOf(yellow, { ...edit, address: "x" })).toEqual({ error: "Adressen är ett heltal 1–4096." });
    const { asked, failed, done } = pretend(connected);
    done.onChange(yellow, { ...editOf(yellow), without: true });
    done.onChange(yellow, { ...edit, address: "0" });
    done.onLevel(3);
    expect(asked[0]).toBe('change({"kind":"switch","name":"2","address":2,"without":true,"reversed":false,"feedback":null,"straight":null,"diverging":null,"drop_delay":null})');
    expect(failed).toEqual(["Adressen är ett heltal 1–4096."]);
    expect(asked[1]).toBe("level(3)");
    const html = render(quiet);
    expect(html).toContain("Växel 2 saknar återrapport");
    expect(html).toMatch(/<button type="button" class="primar" disabled="">Slå på nivå 3<\/button>/);
  });

  it("gives a track circuit a släpptid in seconds, with a comma or a point (STUDIO-35, #274)", () => {
    const track = { ...(objects[4] as KopplaObject), drop_delay: 2.5 };
    expect(addressText(track)).toBe("3 · släpptid 2,5 s");
    expect(addressText(objects[4] as KopplaObject)).toBe("3");
    const edit = editOf(track);
    expect(edit.dropDelay).toBe("2,5");
    expect(changeOf(track, { ...edit, dropDelay: "10" })).toEqual({
      change: { kind: "track_circuit", name: "Spår 1", address: 3, without: false, reversed: false, feedback: null, straight: null, diverging: null, drop_delay: 10 },
    });
    expect(changeOf(track, { ...edit, dropDelay: "1.5" })).toMatchObject({ change: { drop_delay: 1.5 } });
    expect(changeOf(track, { ...edit, dropDelay: "" })).toMatchObject({ change: { drop_delay: 0 } });
    expect(changeOf(track, { ...edit, dropDelay: "61" })).toEqual({ error: "Släpptiden är 0–60 sekunder." });
    expect(changeOf(track, { ...edit, dropDelay: "x" })).toEqual({ error: "Släpptiden är 0–60 sekunder." });
    expect(changeOf(objects[1] as KopplaObject, editOf(objects[1] as KopplaObject))).toMatchObject({ change: { drop_delay: null } });
    const html = render({ ...quiet, objects: [track] });
    expect(html).toContain("3 · släpptid 2,5 s");
  });

  it("shows Lyssna behind Felsök: the last messages decoded in Swedish (STUDIO-24)", () => {
    const listen: Listen = {
      connected: true,
      messages: [
        { at: "2026-11-18T12:00:03Z", direction: "in", hex: "B2 01 50 1C", text: "Givare 4: slog till (aktiv).", objects: ["Spår 2: belagd"] },
        { at: "2026-11-18T12:00:01Z", direction: "out", hex: "B0 01 10 5E", text: "Order till adress 2: thrown (T), på.", objects: ["växel 2: avvikande (−)"] },
      ],
    };
    const closed = render(connected);
    expect(closed).toContain("<summary>Felsök › Lyssna</summary>");
    expect(closed).toContain("Öppna för att se de senaste LocoNet-meddelandena");
    const html = render(connected, listen);
    expect(html).toContain("B2 01 50 1C");
    expect(html).toContain("Givare 4: slog till (aktiv).");
    expect(html).toContain("Spår 2: belagd");
    expect(html).toContain("<td>ut</td>");
  });
});

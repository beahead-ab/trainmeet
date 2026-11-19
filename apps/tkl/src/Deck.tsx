// Stream Deck on the screen (#86 del a, SD59): TKL has the deck on the screen, so that it can be
// tried without hardware. It is the same deck as a real one: it is opened by its serial number
// and model, TKL's server computes every key's face from the interlocking and the hub (SD1, SD3),
// and a click is a press, holding it a hold (SD29). The dials turn with the wheel or the arrow
// keys and press with a click (SD83), Neo's touch points change the page (SD82). The deck waits
// for the next change like the interlocking's second screen, and says Ingen kontakt when TKL does
// not answer, never an old state (SD21).
//
// A real deck (#86 del b, SD50): a local TKL owns its decks over USB, and the panel says so. In
// Chrome and Edge, Anslut Stream Deck lets the browser drive a deck with WebHID (deckhid.ts), with
// the pictures TKL's server draws; elsewhere a short line says why there is no button.
//
// The shunter's deck (#87 del d): on a part's screen /del/<id> the panel opens the deck in the
// part's role, the mode Bangård only. Tuta and Ring sound on the screen, and Fika draws a cup.
//
// The fjärrtågklarerare's deck (#36 del d, SD37): in the fjärrbild the panel opens the deck in
// the role Fjärrtågklareraren, the mode Fjärr: a page per station TKL controls, a key per route in
// its remote catalogue, the offers and Läge. A route blinks after the first press and is sent with
// the second.
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type WheelEvent } from "react";
import { api, type DeckFace, type DeckModel, type Decks, type DeckTile, type DeckView, type Panel } from "./api";
import { facesOf, Holds, KEY, keyStyle, PLAN_COLOURS, readDeck, RELAY_DARK, RELAY_TRACK, REMOTE_ROLE, saveDeck, serialFor, soundOf, textSize, type Stored } from "./deck";
import { bridges, connect, fetchPixels, hasHid, NOT_HERE, OWNED, type Bridge, type BridgeApi, type HidDeck } from "./deckhid";
import { tone } from "./ljud";
import type { Drawing } from "./stallverk";
import "./deck.css";

const storage = (): Storage | null => (typeof localStorage === "undefined" ? null : localStorage);
const sleep = (ms: number) => new Promise((done) => setTimeout(done, ms));

type Plan = { panel: Panel; drawn: Drawing } | null;

/** A piece of the track plan on a key (SD70, SD71): the tracks in their state, the signals as
 * triangles, the station's own numbers and the train numbers (SD73). 85 or Relä (SD72). */
export function TileDrawing({ tile, plan }: { tile: DeckTile; plan: Plan }) {
  if (!plan) return null;
  const [cw, ch] = plan.panel.cell;
  const { x, y, w, h } = tile;
  const inside = (c: [number, number]) => c[0] >= x && c[0] < x + w && c[1] >= y && c[1] < y + h;
  const touches = (cells: [number, number][]) => cells.some((c, i) => inside(c) || (i > 0 && crosses(cells[i - 1] as [number, number], c, x, y, w, h)));
  const relay = tile.drawn === "rela";
  const lines = plan.drawn.lines.filter((l) => touches(l.cells as [number, number][]));
  const signals = plan.drawn.signals.filter((s) => inside(s.symbol as [number, number]));
  const numbers = plan.drawn.numbers.filter((n) => inside(n.at as [number, number]));
  const goals = new Set(tile.goals ?? []);
  return (
    <>
      <svg className="sd-plan" viewBox={`${x * cw} ${y * ch} ${w * cw} ${h * ch}`} preserveAspectRatio="none" aria-hidden="true">
        {lines.map((l) => {
          const points = l.cells.map(([cx, cy]) => `${cx * cw},${cy * ch}`).join(" ");
          const colour = relay ? RELAY_TRACK : (PLAN_COLOURS[l.state] ?? PLAN_COLOURS.free);
          return <polyline key={l.piece} points={points} fill="none" stroke={colour} strokeWidth={relay ? 2 : 4} vectorEffect="non-scaling-stroke" data-state={l.state} />;
        })}
        {relay
          ? lines.map((l) => {
              const [a, b] = [l.cells[0], l.cells[l.cells.length - 1]] as [[number, number], [number, number]];
              const mx = ((a[0] + b[0]) / 2) * cw;
              const my = ((a[1] + b[1]) / 2) * ch;
              const lit = l.state !== "free" ? (PLAN_COLOURS[l.state] ?? RELAY_DARK) : RELAY_DARK;
              return <ellipse key={`l-${l.piece}`} cx={mx} cy={my} rx={cw * 0.12} ry={ch * 0.12} fill={lit} stroke="#9ca3af" vectorEffect="non-scaling-stroke" strokeWidth={1} />;
            })
          : null}
        {signals.map((s) => {
          const [sx, sy] = s.symbol;
          const [tx, ty] = s.toward;
          const len = Math.hypot(tx, ty) || 1;
          const ux = (tx / len) * cw * 0.3;
          const uy = (ty / len) * ch * 0.3;
          const px = -uy * 0.6;
          const py = ux * 0.6;
          const cx = sx * cw;
          const cy = sy * ch;
          const fill = tile.start === s.name ? "#2563eb" : goals.has(s.name) ? "#22c55e" : s.aspect === "proceed" ? "#22c55e" : s.aspect === "shunt" ? "#e5e7eb" : "#000000";
          return <polygon key={s.name} points={`${cx + ux},${cy + uy} ${cx - ux + px},${cy - uy + py} ${cx - ux - px},${cy - uy - py}`} fill={fill} stroke="#ffffff" strokeWidth={1.5} vectorEffect="non-scaling-stroke" data-signal={s.name} />;
        })}
      </svg>
      {numbers.length ? <span className={`sd-chip ${numbers[0]?.colour === "red" ? "rod" : "gron"} sd-plan-chip`}>{numbers[0]?.number ?? ""}</span> : null}
      {tile.names?.length ? <span className="sd-plan-names">{tile.names.join(" ")}</span> : null}
    </>
  );
}

function crosses(a: [number, number], b: [number, number], x: number, y: number, w: number, h: number): boolean {
  // A segment that passes through the square without a point in it.
  const steps = 8;
  for (let i = 1; i < steps; i++) {
    const px = a[0] + ((b[0] - a[0]) * i) / steps;
    const py = a[1] + ((b[1] - a[1]) * i) / steps;
    if (px >= x && px < x + w && py >= y && py < y + h) return true;
  }
  return false;
}

/** One key, drawn as the prototype's canvas draws it (src/streamdeck.js, rita). */
export function DeckKey({ face, now, plan, size = KEY }: { face: DeckFace; now: number; plan: Plan; size?: number }) {
  const text = face.text ?? "";
  const top = face.top ?? "";
  const under = face.under ?? "";
  const small = face.small ?? "";
  const children: ReactNode[] = [];
  if (face.band) children.push(<span key="band" className="sd-band" style={{ background: face.band }} />);
  if (face.type === "fika") children.push(<Cup key="cup" />);
  if (face.tile) children.push(<TileDrawing key="tile" tile={face.tile} plan={plan} />);
  if (top) children.push(<span key="top" className="sd-top">{top}</span>);
  if (text) {
    children.push(
      <span key="text" className={`sd-text${top ? " med-top" : under || face.chip ? " med-under" : ""}`} style={{ fontSize: Math.round(size * textSize(text)) }}>
        {text}
      </span>,
    );
  }
  if (face.chip) children.push(<span key="chip" className={`sd-chip ${face.chip_colour === "red" ? "rod" : face.chip_colour === "green" ? "gron" : ""}`}>{face.chip}</span>);
  if (under) children.push(<span key="under" className={`sd-under${top ? " med-top" : ""}`}>{under}</span>);
  if (small) children.push(<span key="small" className="sd-small">{small}</span>);
  if (face.dot) children.push(<span key="dot" className="sd-dot" style={{ background: face.dot }} />);
  // Klart att skicka (SD62): the green mark on the train key.
  if (face.ready) children.push(<span key="ready" className="sd-klar" aria-hidden="true">{"✓"}</span>);
  if (face.star) children.push(<span key="star" className="sd-star">{"★"}</span>);
  if (face.line) children.push(<span key="line" className="sd-line" style={{ background: face.line }} />);
  if (face.bar) children.push(<span key="bar" className={`sd-bar${face.bar_dashed ? " streckad" : ""}`} style={{ color: face.bar, background: face.bar_dashed ? undefined : face.bar }} />);
  return (
    <span className={`sd-face${face.dim ? " dim" : ""}`} style={keyStyle(face, now, size)} data-type={face.type} data-blink={face.blink ? "ja" : undefined}>
      {children}
    </span>
  );
}

/** Fika on the shunter's deck: a cup drawn as a shape, never an emoji (SD6). */
function Cup() {
  return (
    <svg className="sd-kopp" viewBox="0 0 24 20" aria-hidden="true">
      <path d="M3 6h12l-1.2 9H4.2z" fill="currentColor" />
      <path d="M15 8.2a3 3 0 0 1 0 5.6" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M1.5 17.2h15" stroke="currentColor" strokeWidth="1.6" />
      <path d="M6 4.5l1-3M9 4.5l1-3" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

type GridProps = {
  view: DeckView;
  faces: DeckFace[];
  now: number;
  plan: Plan;
  onDown?: (key: number) => void;
  onUp?: (key: number) => void;
  onLeave?: (key: number) => void;
  onKey?: (key: number, hold: boolean) => void;
  onDial?: (dial: number, turn: number, press: boolean) => void;
  onTouch?: (point: -1 | 1) => void;
};

/** The deck: its keys in the model's grid, and the info line, the touch points, the strip and
 * the dials where the model has them (SD52, SD53). */
export function DeckGrid({ view, faces, now, plan, onDown, onUp, onLeave, onKey, onDial, onTouch }: GridProps) {
  const grid = view.settings.grid;
  const columns = grid.columns;
  const keyDown = (event: ReactKeyboardEvent, key: number) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onKey?.(key, event.shiftKey);
    }
  };
  return (
    <div className="sd-deck" data-columns={columns} data-rows={grid.rows} data-model={view.settings.model ?? ""}>
      {columns * grid.rows ? (
        <div className="sd-grid" style={{ gridTemplateColumns: `repeat(${columns}, ${KEY}px)` }} role="group" aria-label="Knapparna">
          {faces.map((face, i) => (
            <button
              key={i}
              type="button"
              className="sd-key"
              aria-label={face.label || [face.top, face.text, face.under].filter(Boolean).join(" ") || `Knapp ${i + 1}`}
              data-key={i}
              data-fixed={(view.fixed ?? []).includes(i) ? "ja" : undefined}
              onPointerDown={(e) => {
                e.preventDefault();
                onDown?.(i);
              }}
              onPointerUp={() => onUp?.(i)}
              onPointerLeave={() => onLeave?.(i)}
              onContextMenu={(e) => e.preventDefault()}
              onKeyDown={(e) => keyDown(e, i)}
            >
              <DeckKey face={face} now={now} plan={plan} />
            </button>
          ))}
        </div>
      ) : (
        <p className="sd-tom">Pedalen gör ingenting förrän ägaren har valt en funktion per pedal i Studio (SD55).</p>
      )}
      {grid.info ? (
        <div className="sd-info-rad">
          {grid.touch ? (
            <button type="button" className="sd-punkt" aria-label="Pekpunkt vänster" onClick={() => onTouch?.(-1)}>
              {"◀"}
            </button>
          ) : null}
          <span className="sd-info" aria-live="polite">
            {view.info}
          </span>
          {grid.touch ? (
            <button type="button" className="sd-punkt" aria-label="Pekpunkt höger" onClick={() => onTouch?.(1)}>
              {"▶"}
            </button>
          ) : null}
        </div>
      ) : null}
      {grid.strip ? (
        <div className="sd-remsa" style={{ gridTemplateColumns: `repeat(${Math.max(1, grid.dials)}, 1fr)` }} aria-label="Pekremsan">
          {(view.strip ?? []).map((part, i) => (
            <span key={i} className="sd-del">
              <span className="sd-etikett">{part.label}</span>
              <b>{part.value}</b>
              <span className="sd-etikett">{part.under}</span>
            </span>
          ))}
        </div>
      ) : null}
      {grid.dials ? <Dials count={grid.dials} labels={(view.strip ?? []).map((p) => p.label)} onDial={onDial} /> : null}
    </div>
  );
}

function Dials({ count, labels, onDial }: { count: number; labels: string[]; onDial?: (dial: number, turn: number, press: boolean) => void }) {
  const wheel = (event: WheelEvent, dial: number) => {
    event.preventDefault();
    onDial?.(dial, event.deltaY > 0 ? 1 : -1, false);
  };
  const keys = (event: ReactKeyboardEvent, dial: number) => {
    const turn = event.key === "ArrowRight" || event.key === "ArrowUp" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowDown" ? -1 : 0;
    if (turn) {
      event.preventDefault();
      onDial?.(dial, turn, false);
    }
  };
  return (
    <div className="sd-rattar" style={{ gridTemplateColumns: `repeat(${count}, 1fr)` }}>
      {Array.from({ length: count }, (_, i) => (
        <span key={i} className="sd-ratt-plats">
          <button type="button" className="sd-ratt" aria-label={`Ratt ${i + 1}${labels[i] ? ` ${labels[i]}` : ""}: vrid med hjulet eller pilarna, klicka för att trycka`} onWheel={(e) => wheel(e, i)} onKeyDown={(e) => keys(e, i)} onClick={() => onDial?.(i, 0, true)} />
          <span className="sd-etikett">{labels[i] ?? ""}</span>
        </span>
      ))}
    </div>
  );
}

/** TKL's API for a deck in the browser with WebHID. */
export const hidApi: BridgeApi = {
  decks: api.decks,
  open: api.deckOpenReal,
  view: api.deck,
  press: api.deckPress,
  dial: api.deckDial,
  touch: api.deckTouch,
  wait: api.deckWait,
  close: api.deckClose,
  picture: fetchPixels,
};

/** A model in the chooser: Inte provad until a real deck of it has been tried (SD58). */
export const modelName = (model: Pick<DeckModel, "name" | "tried">) => (model.tried ? model.name : `${model.name} · Inte provad`);

type HidProps = {
  hid: boolean;
  decks: Decks | null;
  connected: Pick<Bridge, "serial" | "name" | "contact">[];
  said: string[];
  onConnect?: () => void;
  onRelease?: (serial: string) => void;
};

/** A real deck (SD50): the decks TKL owns over USB, Anslut Stream Deck where the browser has
 * WebHID, the decks connected that way, and what happened. */
export function HidRow({ hid, decks, connected, said, onConnect, onRelease }: HidProps) {
  const owned = (decks?.decks ?? []).filter((d) => d.connection === "usb");
  return (
    <div className="sd-hid" aria-label="Riktigt Stream Deck">
      {owned.map((d) => (
        <p key={d.serial} className="liten">
          {d.name}: {OWNED}
        </p>
      ))}
      {decks?.usb && decks.usb_problem ? <p className="liten">{decks.usb_problem}</p> : null}
      {hid ? (
        <div className="sd-rad">
          <button type="button" onClick={onConnect}>
            Anslut Stream Deck
          </button>
          {connected.map((b) => (
            <span key={b.serial} className="liten">
              {b.name} med WebHID{b.contact ? "" : ": Ingen kontakt"}{" "}
              <button type="button" className="lank" onClick={() => onRelease?.(b.serial)}>
                Koppla från
              </button>
            </span>
          ))}
        </div>
      ) : (
        <p className="liten">{NOT_HERE}</p>
      )}
      {said.map((line, i) => (
        <p key={i} className="liten" role="status">
          {line}
        </p>
      ))}
    </div>
  );
}

let reopened = false;

/** The panel Stream Deck in Ställverket: the chosen model, the deck, and what it said. With a
 * part's role, on the part's screen: the shunter's deck, Bangård (#87 del d). */
export function DeckPanel({ screen, plan, initial, role = null }: { screen: number; plan: Plan; initial?: { view: DeckView; models: DeckModel[] }; role?: string | null }) {
  const serial = serialFor(screen, role);
  const [stored, setStored] = useState<Stored>(() => readDeck(screen, storage(), role));
  const [models, setModels] = useState<DeckModel[]>(initial?.models ?? []);
  const [view, setView] = useState<DeckView | null>(initial?.view ?? null);
  const [contact, setContact] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const revision = useRef<number | null>(initial?.view.revision ?? null);
  const holds = useRef(new Holds());
  const sending = useRef(Promise.resolve());
  const [decks, setDecks] = useState<Decks | null>(null);
  const [said, setSaid] = useState<string[]>([]);
  const [, redraw] = useState(0);
  const changed = () => redraw((n) => n + 1);

  useEffect(() => {
    // The decks TKL owns over USB, and a deck the browser already allows is opened again.
    if (initial) return;
    void api.decks().then(setDecks).catch(() => {});
    if (reopened || !hasHid()) return;
    reopened = true;
    void (async () => {
      const library = await import("@elgato-stream-deck/webhid");
      const found = await library.getStreamDecks().catch(() => []);
      if (found.length) setSaid(await connect(found as HidDeck[], hidApi, changed));
    })();
  }, [initial]);

  const connectHid = async () => {
    try {
      const library = await import("@elgato-stream-deck/webhid");
      const chosen = await library.requestStreamDecks();
      if (chosen.length) setSaid(await connect(chosen as HidDeck[], hidApi, changed));
      setDecks(await api.decks().catch(() => decks));
    } catch (error) {
      setSaid([`Stream Deck gick inte att koppla in: ${error instanceof Error ? error.message : String(error)}. Stäng Elgatos eget program om det håller decket.`]);
    }
  };
  const release = async (serial: string) => {
    await bridges.get(serial)?.close();
    bridges.delete(serial);
    changed();
  };

  const shown = (fresh: DeckView) => {
    revision.current = fresh.revision;
    holds.current.ms = fresh.hold_ms ?? 600;
    setView(fresh);
    setContact(true);
  };
  const send = (work: () => Promise<DeckView>) => {
    // One at a time, in order: the next press builds on the answer to this one.
    sending.current = sending.current.then(async () => {
      try {
        shown(await work());
      } catch {
        setContact(false);
      }
    });
  };

  useEffect(() => {
    if (initial) return;
    let alive = true;
    void (async () => {
      try {
        const [found, opened] = await Promise.all([api.deckModels(), api.deckOpen(serial, stored.model as DeckModel["id"], role)]);
        if (!alive) return;
        setModels(found);
        shown(opened);
      } catch {
        if (alive) setContact(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [serial, stored.model, initial, role]);

  useEffect(() => {
    if (initial) return;
    let alive = true;
    void (async () => {
      while (alive) {
        const after = revision.current;
        if (after === null) {
          await sleep(500);
          continue;
        }
        try {
          const waited = await api.deckWait(serial, after, 25);
          if (alive && (waited.changed || revision.current === after)) shown(await api.deck(serial));
        } catch {
          if (alive) setContact(false);
          await sleep(2000);
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [serial, initial]);

  useEffect(() => {
    // The clock and a reason's three seconds (SD18): read again when the server says.
    if (initial || !view) return;
    const timer = setTimeout(() => send(() => api.deck(serial)), Math.max(200, view.refresh_ms ?? 15000));
    return () => clearTimeout(timer);
  }, [view, serial, initial]);

  useEffect(() => {
    // The blink, and a key held long enough is a hold while it is still down (SD29).
    const timer = setInterval(() => {
      const at = Date.now();
      setNow(at);
      for (const key of holds.current.tick(at)) send(() => api.deckPress(serial, key, true));
    }, 100);
    return () => clearInterval(timer);
  }, [serial]);

  const choose = (model: string) => {
    const next = { ...stored, model };
    setStored(next);
    saveDeck(screen, next, storage(), role);
    revision.current = null;
  };
  const faces = facesOf(view, contact);
  const press = (key: number, hold: boolean) => {
    // Tuta and Ring sound here; the deck itself has no speaker (#87 del d).
    const sound = hold ? null : soundOf(faces[key]);
    if (sound) tone(sound);
    send(() => api.deckPress(serial, key, hold));
  };
  // A part's deck has no pedal (TKL122), and neither has the fjärrtågklarerare's.
  const offered = role ? models.filter((m) => m.id !== "pedal") : models;
  return (
    <section className="sd-panel" aria-label="Stream Deck">
      <div className="sd-rad">
        <b>Stream Deck</b>
        <label>
          Modell{" "}
          <select aria-label="Modell" value={stored.model} onChange={(e) => choose(e.target.value)}>
            {(offered.length ? offered : [{ id: stored.model, name: stored.model, tried: true }]).map((m) => (
              <option key={m.id} value={m.id}>
                {modelName(m)}
              </option>
            ))}
          </select>
        </label>
        <span className="liten">
          Klick är ett tryck, håll nere {((view?.hold_ms ?? 600) / 1000).toLocaleString("sv-SE")} s för håll in.{" "}
          {role === REMOTE_ROLE
            ? "En tågväg blinkar efter första trycket och läggs med det andra. Håll in en lagd väg för att ta bort den. Erbjudande tar emot med ett tryck. Läge visar stationerna."
            : role
              ? "Ände byter ände, ett spår lägger växelgatan och en väg ut begärs av tågklareraren. Håll in tågknappen för nästa tåg."
              : "Läge byter läge; håll in Läge för alla sidor."}
        </span>
      </div>
      {view ? (
        <DeckGrid
          view={view}
          faces={faces}
          now={now}
          plan={plan}
          onDown={(key) => holds.current.pressed(key, Date.now())}
          onUp={(key) => {
            const what = holds.current.released(key, Date.now());
            if (what) press(key, what === "hold");
          }}
          onLeave={(key) => holds.current.cancel(key)}
          onKey={(key, hold) => press(key, hold)}
          onDial={(dial, turn, press) => send(() => api.deckDial(serial, dial, turn, press))}
          onTouch={(point) => send(() => api.deckTouch(serial, point))}
        />
      ) : (
        <p className="tom">{contact ? "Öppnar decket …" : "Ingen kontakt med TKL."}</p>
      )}
      <p className={`sd-status${view?.accepted === false ? " nej" : ""}`} role="status" aria-live="polite">
        {!contact ? "Ingen kontakt med TKL." : view?.locked ? "TKL är låst: decket visar bara klockan." : (view?.message ?? "")}
      </p>
      {initial ? null : (
        <HidRow
          hid={hasHid()}
          decks={decks}
          connected={[...bridges.values()].filter((b) => !b.closed)}
          said={said}
          onConnect={() => void connectHid()}
          onRelease={(serial) => void release(serial)}
        />
      )}
    </section>
  );
}

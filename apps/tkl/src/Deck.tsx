// Stream Deck on the screen (#86 del a, SD59): TKL has the deck on the screen, so that it can be
// tried without hardware. It is the same deck as a real one: it is opened by its serial number
// and model, TKL's server computes every key's face from the interlocking and the hub (SD1, SD3),
// and a click is a press, holding it a hold (SD29). The dials turn with the wheel or the arrow
// keys and press with a click (SD83), Neo's touch points change the page (SD82). The deck waits
// for the next change like the interlocking's second screen, and says Ingen kontakt when TKL does
// not answer, never an old state (SD21).
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type WheelEvent } from "react";
import { api, type DeckFace, type DeckModel, type DeckTile, type DeckView, type Panel } from "./api";
import { facesOf, Holds, KEY, keyStyle, PLAN_COLOURS, readDeck, RELAY_DARK, RELAY_TRACK, saveDeck, serialFor, textSize, type Stored } from "./deck";
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
  if (face.star) children.push(<span key="star" className="sd-star">{"★"}</span>);
  if (face.line) children.push(<span key="line" className="sd-line" style={{ background: face.line }} />);
  if (face.bar) children.push(<span key="bar" className={`sd-bar${face.bar_dashed ? " streckad" : ""}`} style={{ color: face.bar, background: face.bar_dashed ? undefined : face.bar }} />);
  return (
    <span className={`sd-face${face.dim ? " dim" : ""}`} style={keyStyle(face, now, size)} data-type={face.type} data-blink={face.blink ? "ja" : undefined}>
      {children}
    </span>
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

/** The panel Stream Deck in Ställverket: the chosen model, the deck, and what it said. */
export function DeckPanel({ screen, plan, initial }: { screen: number; plan: Plan; initial?: { view: DeckView; models: DeckModel[] } }) {
  const serial = serialFor(screen);
  const [stored, setStored] = useState<Stored>(() => readDeck(screen, storage()));
  const [models, setModels] = useState<DeckModel[]>(initial?.models ?? []);
  const [view, setView] = useState<DeckView | null>(initial?.view ?? null);
  const [contact, setContact] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const revision = useRef<number | null>(initial?.view.revision ?? null);
  const holds = useRef(new Holds());
  const sending = useRef(Promise.resolve());

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
        const [found, opened] = await Promise.all([api.deckModels(), api.deckOpen(serial, stored.model as DeckModel["id"])]);
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
  }, [serial, stored.model, initial]);

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
    saveDeck(screen, next, storage());
    revision.current = null;
  };
  const faces = facesOf(view, contact);
  return (
    <section className="sd-panel" aria-label="Stream Deck">
      <div className="sd-rad">
        <b>Stream Deck</b>
        <label>
          Modell{" "}
          <select aria-label="Modell" value={stored.model} onChange={(e) => choose(e.target.value)}>
            {(models.length ? models : [{ id: stored.model, name: stored.model }]).map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </label>
        <span className="liten">Klick är ett tryck, håll nere {((view?.hold_ms ?? 600) / 1000).toLocaleString("sv-SE")} s för håll in. Läge byter läge; håll in Läge för alla sidor.</span>
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
            if (what) send(() => api.deckPress(serial, key, what === "hold"));
          }}
          onLeave={(key) => holds.current.cancel(key)}
          onKey={(key, hold) => send(() => api.deckPress(serial, key, hold))}
          onDial={(dial, turn, press) => send(() => api.deckDial(serial, dial, turn, press))}
          onTouch={(point) => send(() => api.deckTouch(serial, point))}
        />
      ) : (
        <p className="tom">{contact ? "Öppnar decket …" : "Ingen kontakt med TKL."}</p>
      )}
      <p className={`sd-status${view?.accepted === false ? " nej" : ""}`} role="status" aria-live="polite">
        {!contact ? "Ingen kontakt med TKL." : view?.locked ? "TKL är låst: decket visar bara klockan." : (view?.message ?? "")}
      </p>
    </section>
  );
}

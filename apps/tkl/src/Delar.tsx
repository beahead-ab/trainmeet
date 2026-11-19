// Delställverk (#87, TKL97–TKL103). Two views of the same interlocking:
//
// - PartBox, at the top of the station's Ställverket: a part's request with Godkänn and Neka
//   (RANG-03), the ring with a sound and a visible mark (TKL98), Fika, and the list Klara att
//   skicka, ordered by the planned departure and moved by drag or ▲ ▼, with Skickat (TKL108).
// - DelSida, the part's own screen at /del/<id>, on any screen on the station's network behind
//   the same PIN (TKL102): the station's panel with the part's area active and the rest greyed,
//   the switch streets and the routes out per end, Lämna, Klart, Grindar, Ring, Tuta, Fika and
//   Klocka (RANG-04), the train for Klart att skicka, and what was refused and why.
//
// Every press asks the interlocking, under the part's own path; its yes, or no with the reason,
// is what the screen shows (STV-43). The look follows the prototype's box (the reference
// interlocking with ?roll=rangerare in the specification).
import { useEffect, useMemo, useRef, useState } from "react";
import { api, Problem, type Interlocking, type InterlockingAnswer, type PartCalls, type PartRouteOut, type PartShown, type PartSide, type PartStreet, type PartTrains, type TrackPlan } from "./api";
import { areaOf, atEnd, boxOf, givePress, outPress, partOf, readyLine, stepTo } from "./delar";
import { tone } from "./ljud";
import { Panelen } from "./Panelen";
import { skinOf } from "./skal";
import { clickPoint, clickSwitch, drawing, filled, guidance, NOTHING, routeEnds, routeName, type Calls, type Done, type Valet } from "./stallverk";
import { text, type Say } from "./texter";
import "./delar.css";

type Work = () => Promise<InterlockingAnswer>;

type BoxProps = { state: Interlocking; say: Say; working: boolean; onWork: (work: Work) => void };

/** The box at the top of the station's Ställverket. Nothing in it acts by itself. */
export function PartBox(props: BoxProps) {
  const [dragged, setDragged] = useState<string | null>(null);
  return <PartBoxView {...props} dragged={dragged} onDrag={setDragged} />;
}

/** The box itself, without state of its own: the dragged train comes from PartBox. */
export function PartBoxView({ state, say, working, onWork, dragged, onDrag }: BoxProps & { dragged: string | null; onDrag: (number: string | null) => void }) {
  const box = boxOf(state);
  if (!box.asking.length && !box.ringing.length && !box.fika.length && !box.ready.length) return null;
  return (
    <section className="del-ruta" aria-label={say("partBox")}>
      {box.asking.map(({ part, request }) => (
        <div key={request.id} className="del-rad begaran" data-request={request.id}>
          <span>
            {say("partAsks", { part: part.name })} <b>{request.said}</b> · <span className="tm-mono">{routeName(request)}</span>
          </span>
          <button type="button" className="ja" disabled={working} onClick={() => onWork(() => api.partReply(request.id, true))}>
            {say("approve")}
          </button>
          <button type="button" disabled={working} onClick={() => onWork(() => api.partReply(request.id, false))}>
            {say("deny")}
          </button>
        </div>
      ))}
      {box.ringing.map((part) => (
        <div key={`ring-${part.id}`} className="del-rad ringer" role="alert" data-ringing={part.id}>
          <span className="del-klocka" aria-hidden="true">
            ☎
          </span>
          <span>{say("partRings", { part: part.name })}</span>
          <button type="button" disabled={working} onClick={() => onWork(() => api.partRingAnswer(part.id))}>
            {say("answerRing")}
          </button>
        </div>
      ))}
      {box.fika.map((part) => (
        <div key={`fika-${part.id}`} className="del-rad fika">
          <span aria-hidden="true">☕</span> {say("partFika", { part: part.name })}
        </div>
      ))}
      {box.ready.length ? (
        <>
          <div className="del-rad klarh">
            {say("readyTitle")} <span className="liten">· {say("readySub")}</span>
          </div>
          <ol className="del-klara" aria-label={say("readyTitle")}>
            {box.ready.map((r, k) => {
              const move = (step: number) => {
                const to = stepTo(box.ready, r.number, step);
                if (to !== null) onWork(() => api.readyMove(r.number, to));
              };
              return (
                <li
                  key={r.number}
                  className={`del-rad${dragged === r.number ? " dras" : ""}`}
                  data-ready={r.number}
                  draggable
                  onDragStart={(event) => {
                    onDrag(r.number);
                    event.dataTransfer?.setData("text/plain", r.number);
                  }}
                  onDragEnd={() => onDrag(null)}
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={(event) => {
                    event.preventDefault();
                    const number = event.dataTransfer?.getData("text/plain") || dragged;
                    onDrag(null);
                    if (number && number !== r.number) onWork(() => api.readyMove(number, k));
                  }}
                >
                  <span>
                    <b className="tm-mono">{r.number}</b> · {readyLine(r, (track) => say("readyTrack", { track }))}
                  </span>
                  <button type="button" title={say("readyUp", { number: r.number })} aria-label={say("readyUp", { number: r.number })} disabled={working || k === 0} onClick={() => move(-1)}>
                    ▲
                  </button>
                  <button type="button" title={say("readyDown", { number: r.number })} aria-label={say("readyDown", { number: r.number })} disabled={working || k === box.ready.length - 1} onClick={() => move(1)}>
                    ▼
                  </button>
                  <button type="button" aria-label={say("readySentLabel", { number: r.number })} disabled={working} onClick={() => onWork(() => api.readySent(r.number))}>
                    {say("readySent")}
                  </button>
                </li>
              );
            })}
          </ol>
        </>
      ) : null}
    </section>
  );
}

const sv: Say = (key, vars) => text("sv", key, vars);
const sleep = (ms: number) => new Promise((done) => setTimeout(done, ms));
const nowText = () => new Date().toLocaleTimeString("sv-SE");
const SIDES: [PartSide, string][] = [
  ["left", "Vänster"],
  ["right", "Höger"],
];

/** The part's own screen at /del/<id>: the model and the state fetched here, and followed with
 * the interlocking's wait, as every screen of Ställverket (STV-05). */
export function DelSida({ partId, initial }: { partId: string; initial?: { plan: TrackPlan; state: Interlocking; trains?: PartTrains } }) {
  const [plan, setPlan] = useState<TrackPlan | null | undefined>(initial?.plan);
  const [state, setState] = useState<Interlocking | null | undefined>(initial?.state);
  const revision = useRef<number | null>(null);
  revision.current = state?.revision ?? null;
  useEffect(() => {
    if (initial) return;
    let alive = true;
    void (async () => {
      try {
        const [found, now] = await Promise.all([api.stationModel(), api.interlocking()]);
        if (!alive) return;
        setPlan(found);
        setState(now);
      } catch {
        if (alive) setPlan(null);
      }
      while (alive) {
        const after = revision.current;
        if (after === null) {
          await sleep(2000);
          continue;
        }
        try {
          const waited = await api.interlockingWait(after, 25);
          if (alive && waited.changed && revision.current === after) {
            const fresh = await api.interlocking();
            if (alive) setState(fresh);
          }
        } catch {
          await sleep(3000);
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [initial]);
  const calls = useMemo(() => api.part(partId), [partId]);
  if (plan === undefined || state === undefined) return <p className="tom">Hämtar ställverket …</p>;
  const part = state ? partOf(state, partId) : null;
  if (!plan?.panel || !state || !part) {
    return <p className="tom">Stationen har inget delställverk som heter {partId}. Delarna ritas i Studio och står i stationsmodellen.</p>;
  }
  return <DelPanel plan={plan} state={state} part={part} calls={calls} onState={setState} trains={initial?.trains} />;
}

type PanelProps = { plan: TrackPlan; state: Interlocking; part: PartShown; calls: PartCalls; onState: (state: Interlocking) => void; trains?: PartTrains };

/** The part's screen with its state: the panel, the streets and routes out, the buttons. */
export function DelPanel({ plan, state: raw, part, calls, onState, trains: given }: PanelProps) {
  const panel = plan.panel as NonNullable<TrackPlan["panel"]>;
  const state = filled(raw);
  const [side, setSide] = useState<PartSide>("left");
  const [valet, setValet] = useState<Valet>(NOTHING);
  const [working, setWorking] = useState(false);
  const [giving, setGiving] = useState(false);
  const [trains, setTrains] = useState<PartTrains | null>(given ?? null);
  const [number, setNumber] = useState("");
  const skin = skinOf("85");
  const ends = useMemo(() => routeEnds(plan.route_list ?? []), [plan]);
  const drawn = drawing(panel, state, new Set(), ends);
  const area = useMemo(() => areaOf(part), [part]);
  const mine = state.routes.filter((r) => r.part === part.id && r.request === null);

  useEffect(() => {
    if (given) return;
    calls
      .trains()
      .then(setTrains)
      .catch(() => setTrains(null));
  }, [calls, given, part.requests?.length]);

  const asCalls: Calls = {
    targets: calls.targets,
    setRoute: (start, end) => calls.setRoute(start, end),
    release: calls.release,
    layLever: calls.layLever,
    emergencyRelease: refuse,
    step: refuse,
    arrive: refuse,
    depart: refuse,
    putTrain: refuse,
    removeTrain: refuse,
    panelFunction: refuse,
  };
  const run = async (work: () => Promise<Done>) => {
    if (working) return;
    setWorking(true);
    try {
      const done = await work();
      setValet(done.valet);
      if (done.state) onState(done.state);
    } finally {
      setWorking(false);
    }
  };
  const press = (work: Work, after?: () => void) =>
    void run(async () => {
      try {
        const answer = await work();
        after?.();
        return { valet: { ...valet, choice: null, said: { text: answer.message, ok: answer.accepted, at: new Date().toISOString() } }, state: answer.state };
      } catch (error) {
        const told = error instanceof Problem || error instanceof Error ? error.message : "Något gick fel.";
        return { valet: { ...valet, said: { text: told, ok: false, at: new Date().toISOString() } } };
      }
    });
  const say = (said: string, ok = true) => setValet({ ...valet, said: { text: said, ok, at: new Date().toISOString() } });
  const give = () => {
    const what = givePress(part);
    if (what.kind === "none") {
      say("Ingen godkänd väg att lämna tillbaka.", false);
      setGiving(false);
    } else if (what.kind === "return") {
      setGiving(false);
      press(() => calls.giveBack(what.request));
    } else {
      setGiving(!giving);
      say("Välj vägen som ska lämnas tillbaka.");
    }
  };
  const routeOut = (out: PartRouteOut) => {
    const what = outPress(out, giving);
    if (what.kind === "say") say(what.text);
    else if (what.kind === "return") {
      setGiving(false);
      press(() => calls.giveBack(what.request));
    } else press(() => calls.request(what.id));
  };
  const announce = (chosen: string, call: string | null) => {
    const trimmed = chosen.trim();
    if (!trimmed) return;
    press(
      () => calls.ready(trimmed, call),
      () => setNumber(""),
    );
  };
  const ready = new Set((state.ready ?? []).map((r) => r.number));

  return (
    <div className="stv del-sida" data-part={part.id}>
      <div className="niva del-huvud">
        <span className="niva-chip">Delställverk</span>
        <h1>{part.name}</h1>
        <span className="liten">i {plan.summary.name}s ställverk</span>
        <span className="tm-fyll" />
        <span className="klocka tm-mono">{nowText().slice(0, 5)}</span>
      </div>
      {valet.said ? (
        <p className={`stv-svar ${valet.said.ok ? "ja" : "nej"}`} role={valet.said.ok ? "status" : "alert"}>
          {valet.said.ok ? null : <b>Nej: </b>}
          {valet.said.text}
        </p>
      ) : null}
      <section className="stv-ruta" aria-label={`${part.name}s panel`}>
        <Panelen
          panel={panel}
          drawn={drawn}
          skin={skin}
          say={sv}
          title={part.name}
          choice={valet.choice}
          height="56vh"
          area={area}
          onPoint={(name) => void run(() => clickPoint(valet, name, asCalls, sv))}
          onSwitch={(sw) => void run(() => clickSwitch(valet, sw, asCalls))}
          onRoute={(route) => setValet({ ...valet, route, confirm: null })}
        />
        <p className="stv-hjalp liten">{valet.choice ? guidance(valet, sv) : `Klicka på en signal i ${part.name} för en växlingsväg, eller på en växel. Det gråa är stationens.`}</p>
        {mine.length ? (
          <div className="stv-vagar">
            <span className="liten">Mina vägar:</span>
            {mine.map((r) => (
              <button key={r.id} type="button" className="vag shunting" disabled={working} onClick={() => press(() => calls.release(r.id))}>
                Lös ut {routeName(r)}
              </button>
            ))}
          </div>
        ) : null}
      </section>
      <DelKnappar
        part={part}
        side={side}
        giving={giving}
        working={working}
        trains={trains}
        number={number}
        ready={ready}
        onSide={setSide}
        onStreet={(id) => press(() => calls.street(id))}
        onOut={routeOut}
        onGive={give}
        onDone={() => press(() => calls.done())}
        onGates={() => press(() => calls.gates())}
        onRing={() => {
          tone("ring");
          press(() => calls.ring());
        }}
        onHorn={() => {
          tone("horn");
          say("Tut!");
        }}
        onFika={() => press(() => calls.fika(true))}
        onClock={() => say(`Klockan är ${nowText()}.`)}
        onNumber={setNumber}
        onAnnounce={announce}
      />
      {part.fika ? (
        <div className="del-fika" role="dialog" aria-label="Fika">
          <span className="kopp" aria-hidden="true">
            ☕
          </span>
          <p>{part.name} har fika. Tågklareraren ser det.</p>
          <button type="button" className="primar" disabled={working} onClick={() => press(() => calls.fika(false))}>
            Tillbaka
          </button>
        </div>
      ) : null}
    </div>
  );
}

type KnapparProps = {
  part: PartShown;
  side: PartSide;
  giving: boolean;
  working: boolean;
  trains: PartTrains | null;
  number: string;
  ready: Set<string>;
  onSide: (side: PartSide) => void;
  onStreet: (id: string) => void;
  onOut: (out: PartRouteOut) => void;
  onGive: () => void;
  onDone: () => void;
  onGates: () => void;
  onRing: () => void;
  onHorn: () => void;
  onFika: () => void;
  onClock: () => void;
  onNumber: (number: string) => void;
  onAnnounce: (number: string, call: string | null) => void;
};

/** The part's buttons, without state of their own (RANG-01–RANG-04, TKL108, TKL122): the end,
 * the switch streets and the routes out at it, Lämna, Klart, Grindar, Ring, Tuta, Fika and
 * Klocka, the trains for Klart att skicka, and what was refused and why. */
export function DelKnappar(props: KnapparProps) {
  const { part, side, giving, working, trains, number, ready } = props;
  const streets = atEnd(part.streets ?? [], side);
  const routesOut = atEnd(part.routes_out ?? [], side);
  const refused = part.refused ?? [];
  const time = (at: string) => new Date(at).toLocaleTimeString("sv-SE");
  return (
    <div className="del-knappar">
      <div className="del-ande" role="group" aria-label="Ände">
        {SIDES.map(([id, name]) => (
          <button key={id} type="button" aria-pressed={side === id} onClick={() => props.onSide(id)}>
            {name}
          </button>
        ))}
      </div>
      <section className="del-grupp" aria-labelledby="del-gator">
        <h2 id="del-gator">Växelgator</h2>
        <div className="del-rutnat">
          {streets.map((s) => (
            <StreetButton key={s.id} street={s} working={working} onPress={() => props.onStreet(s.id)} />
          ))}
        </div>
      </section>
      <section className="del-grupp" aria-labelledby="del-ut">
        <h2 id="del-ut">Begär väg ut</h2>
        <div className="del-rutnat">
          {routesOut.map((out) => (
            <OutButton key={out.id} out={out} giving={giving} working={working} onPress={() => props.onOut(out)} />
          ))}
        </div>
      </section>
      <div className="del-fot" role="group" aria-label="Delens knappar">
        <button type="button" aria-pressed={giving} disabled={working} onClick={props.onGive}>
          Lämna
        </button>
        <button type="button" disabled={working} onClick={props.onDone}>
          Klart
        </button>
        <button type="button" disabled={working} onClick={props.onGates}>
          Grindar
        </button>
        <button type="button" className={part.rings ? "ringer" : undefined} disabled={working} onClick={props.onRing}>
          {part.rings ? "Ringer …" : "Ring"}
        </button>
        <button type="button" onClick={props.onHorn}>
          Tuta
        </button>
        <button type="button" disabled={working} onClick={props.onFika}>
          Fika
        </button>
        <button type="button" onClick={props.onClock}>
          Klocka
        </button>
      </div>
      <section className="del-grupp" aria-labelledby="del-klart">
        <h2 id="del-klart">Klart att skicka</h2>
        <div className="del-rutnat">
          {(trains?.trains ?? []).map((t) => (
            <button key={t.call ?? t.number} type="button" data-train={t.number} className={ready.has(t.number) ? "anmald" : undefined} disabled={working || ready.has(t.number)} onClick={() => props.onAnnounce(t.number, t.call ?? null)}>
              <b className="tm-mono">{t.number}</b>
              <span className="liten">
                {[t.track ? `spår ${t.track}` : null, t.departure].filter(Boolean).join(" · ") || "ur planen"}
                {ready.has(t.number) ? " · anmält" : ""}
              </span>
            </button>
          ))}
        </div>
        {trains?.message ? <p className="liten">{trains.message}</p> : null}
        <form
          className="del-nummer"
          onSubmit={(event) => {
            event.preventDefault();
            props.onAnnounce(number, null);
          }}
        >
          <input aria-label="Annat tågnummer" placeholder="Tågnummer" value={number} maxLength={8} size={8} onChange={(e) => props.onNumber(e.target.value)} />
          <button type="submit" disabled={working || !number.trim()}>
            Anmäl klart att skicka
          </button>
        </form>
      </section>
      <section className="del-grupp" aria-labelledby="del-nej">
        <h2 id="del-nej">Nekat</h2>
        {refused.length ? (
          <ul className="handelser del-nekat">
            {refused.map((r, i) => (
              <li key={`${r.at}${i}`} className="nej">
                <span className="tm-mono">{time(r.at)}</span> {r.text}
              </li>
            ))}
          </ul>
        ) : (
          <p className="tom">Inget har nekats.</p>
        )}
      </section>
    </div>
  );
}

const refuse = () => Promise.reject(new Problem("Delställverket gör inte det. Fråga tågklareraren.", 409));

function StreetButton({ street, working, onPress }: { street: PartStreet; working: boolean; onPress: () => void }) {
  const state = street.laid ? "ligger" : street.possible === false ? "hindrad" : "ledig";
  return (
    <button type="button" className={`del-knapp gata ${state}`} data-street={street.id} title={street.reason ?? `${street.name} mot ${street.track}`} disabled={working} onClick={onPress}>
      <b>{street.track}</b>
      <span className="liten">{street.laid ? "ligger" : street.possible === false ? (street.reason ?? "hindrad") : street.name}</span>
    </button>
  );
}

function OutButton({ out, giving, working, onPress }: { out: PartRouteOut; giving: boolean; working: boolean; onPress: () => void }) {
  const state = out.state === "approved" ? "godkand" : out.state === "waiting" ? "vantar" : out.possible === false ? "hindrad" : "ledig";
  const under = out.state === "approved" ? (giving ? "tryck: lämna tillbaka" : "godkänd") : out.state === "waiting" ? "väntar på svar" : out.possible === false ? (out.reason ?? "hindrad") : "begär";
  return (
    <button type="button" className={`del-knapp ut ${state}`} data-route-out={out.id} title={out.reason ?? `${out.start} → ${out.end}`} disabled={working} onClick={onPress}>
      <b>{out.name}</b>
      <span className="liten">{under}</span>
    </button>
  );
}

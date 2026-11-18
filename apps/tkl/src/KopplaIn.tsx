// Studio › Koppla in (#85, STUDIO-04, STUDIO-11, STUDIO-17, STUDIO-18, STUDIO-24): connect to
// LocoNet through a LocoBuffer USB, a BTLocoBridge or the pretend LocoNet, see the MGP cards with
// module and channel, and learn every object by touching the layout. Each switch, signal and
// track circuit is grey, yellow, green or Utan adress; the learning questions come as the layout
// answers ("Givaren 73 slog till. Är det Spår 3?"). Level 3 is turned on here. Felsök › Lyssna
// shows the last messages in Swedish. While connected the page asks the server every second, so
// that a question comes as soon as a sensor reports.
import { useCallback, useEffect, useState } from "react";
import "./kopplain.css";
import {
  addressText,
  attempt,
  changeOf,
  connectAsk,
  counts,
  editOf,
  FEEDBACK_LABEL,
  heardAt,
  KIND_TITLE,
  KINDS,
  kopplaIn,
  learnLabel,
  STATE_CLASS,
  STATE_LABEL,
  TYPE_LABEL,
  where,
  type Answer,
  type Calls,
  type Card,
  type Edit,
  type FeedbackType,
  type KopplaIn as View,
  type KopplaObject,
  type Listen,
  type LoconetType,
  type ObjectKind,
  type Port,
  type Question,
} from "./kopplain";

const POLL_MS = 1000;

export function KopplaIn({ calls = kopplaIn }: { calls?: Calls }) {
  const [view, setView] = useState<View | null>(null);
  const [ports, setPorts] = useState<Port[]>([]);
  const [listen, setListen] = useState<Listen | null>(null);
  const [error, setError] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const run = useCallback(
    async (work: () => Promise<View>) => {
      setBusy(true);
      setError("");
      setProblems([]);
      const done = await attempt(work);
      if ("done" in done) setView(done.done);
      else {
        setError(done.error);
        setProblems(done.problems);
      }
      setBusy(false);
    },
    [],
  );

  useEffect(() => {
    void run(calls.view);
    calls.ports().then(setPorts).catch(() => setPorts([]));
  }, [calls, run]);

  const connected = view?.loconet.connected ?? false;
  useEffect(() => {
    if (!connected) return;
    const every = setInterval(() => {
      calls.view().then(setView).catch(() => undefined);
      if (listen) calls.listen().then(setListen).catch(() => undefined);
    }, POLL_MS);
    return () => clearInterval(every);
  }, [calls, connected, listen]);

  if (!view) return <p className="tom">{error || "Läser Koppla in …"}</p>;
  return (
    <KopplaInView
      view={view}
      ports={ports}
      listen={listen}
      error={error}
      problems={problems}
      busy={busy}
      {...handlers(calls, (work) => void run(work), setError, setListen)}
    />
  );
}

/** What the page's buttons do: each a call to TKL's server, whose answer is the next view. */
export function handlers(calls: Calls, run: (work: () => Promise<View>) => void, fail: (message: string) => void, shown: (listen: Listen | null) => void): Handlers {
  return {
    onConnect: (type, port, channel) => run(() => calls.connect(type, port, channel)),
    onDisconnect: () => run(calls.disconnect),
    onDiscover: () => run(calls.discover),
    onModule: (card, module) => run(() => calls.module(card, module)),
    onChange: (object, edit) => {
      const made = changeOf(object, edit);
      if ("error" in made) fail(made.error);
      else run(() => calls.change(made.change));
    },
    onLearn: (kind, name) => run(() => calls.learn(kind, name)),
    onAnswer: (question, answer, other) => run(() => calls.answer(question, answer, other)),
    onLevel: (level) => run(() => calls.level(level)),
    onWagon: (name, occupied) => run(() => calls.wagon(name, occupied)),
    onListen: (open) => {
      if (!open) shown(null);
      else calls.listen().then(shown).catch(() => shown({ connected: false, messages: [] }));
    },
    onError: fail,
  };
}

export type Handlers = {
  onConnect: (type: LoconetType, port: string | null, channel: number) => void;
  onDisconnect: () => void;
  onDiscover: () => void;
  onModule: (card: number, module: string | null) => void;
  onChange: (object: KopplaObject, edit: Edit) => void;
  onLearn: (kind: ObjectKind, name: string) => void;
  onAnswer: (question: number, answer: Answer, other: string | null) => void;
  onLevel: (level: number) => void;
  onWagon: (name: string, occupied: boolean) => void;
  onListen: (open: boolean) => void;
  onError: (message: string) => void;
};

export function KopplaInView({
  view,
  ports,
  listen,
  error = "",
  problems = [],
  busy = false,
  ...on
}: { view: View; ports: Port[]; listen: Listen | null; error?: string; problems?: string[]; busy?: boolean } & Handlers) {
  const loconet = view.loconet;
  const pretend = loconet.connected && loconet.type === "pretend";
  return (
    <div className="koppla-in">
      <div className="sidrubrik">
        <h1>Koppla in</h1>
        <p className="liten">
          Anslut till banan över LocoNet och lär stationen genom att röra: ställ en vagn, lägg om en växel, skicka kör. Varje objekt är grått tills det har en adress, gult när adressen är angiven och grönt när det är bekräftat på banan. Utan adress väljs för manuella växlar och virtuella signaler.
        </p>
      </div>
      {error ? (
        <div className="fel" role="alert">
          <p>{error}</p>
          {problems.length ? (
            <ul>
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {view.message ? (
        <p className="notis" role="status">
          {view.message}
        </p>
      ) : null}
      <Connection loconet={loconet} ports={ports} busy={busy} on={on} />
      {view.question ? <Asking question={view.question} busy={busy} on={on} /> : null}
      {view.learning && !view.question ? (
        <p className="notis lar" role="status">
          {view.learning.text} Koppla in lyssnar efter givaren som slår till.
          {pretend ? (
            <>
              {" "}
              <button type="button" className="primar" disabled={busy} onClick={() => on.onWagon(view.learning?.name ?? "", true)}>
                Ställ en vagn (låtsas)
              </button>
            </>
          ) : null}
        </p>
      ) : null}
      <Level view={view} busy={busy} on={on} />
      {loconet.connected || view.cards?.length ? <Cards view={view} busy={busy} connected={loconet.connected} on={on} /> : null}
      <Objects view={view} busy={busy} connected={loconet.connected} pretend={pretend} on={on} />
      <Lyssna listen={listen} connected={loconet.connected} on={on} />
    </div>
  );
}

function Connection({ loconet, ports, busy, on }: { loconet: View["loconet"]; ports: Port[]; busy: boolean; on: Handlers }) {
  const [type, setType] = useState<LoconetType>(ports.find((p) => p.type !== "pretend")?.type ?? "pretend");
  const [port, setPort] = useState("");
  const [channel, setChannel] = useState(1);
  if (!loconet.available) {
    return (
      <section className="ruta" aria-label="LocoNet">
        <h2>LocoNet</h2>
        <p>{loconet.reason}</p>
      </section>
    );
  }
  if (loconet.connected) {
    return (
      <section className="ruta" aria-label="LocoNet">
        <h2>LocoNet</h2>
        <div className="rad">
          <span className={`tm-chip ${loconet.type === "pretend" ? "gul" : "gron"}`}>{loconet.label}</span>
          <span className="tm-fyll" />
          <button type="button" disabled={busy} onClick={on.onDiscover}>
            Discover
          </button>
          <button type="button" disabled={busy} onClick={on.onDisconnect}>
            Koppla från
          </button>
        </div>
      </section>
    );
  }
  const listed = ports.filter((p) => p.type === type && p.type !== "pretend");
  const connect = () => {
    const asked = connectAsk(type, port, channel);
    if ("error" in asked) on.onError(asked.error);
    else on.onConnect(type, asked.port, asked.channel);
  };
  return (
    <section className="ruta" aria-label="LocoNet">
      <h2>LocoNet</h2>
      <p className="liten">LocoNet finns bara i en lokal TKL, på stationens dator eller en Raspberry Pi. Para BTLocoBridgen i datorn först.</p>
      <div className="anslut">
        <fieldset className="typer">
          <legend>Anslutning</legend>
          {(["locobuffer", "btlocobridge", "pretend"] as LoconetType[]).map((t) => (
            <label key={t} className="kryss">
              <input type="radio" name="loconet-typ" checked={type === t} onChange={() => setType(t)} />
              {TYPE_LABEL[t]}
            </label>
          ))}
        </fieldset>
        {type === "pretend" ? (
          <p className="liten">Låtsas-LocoNet svarar som banan skulle, med stationens adresser. Det är läget Prova använder.</p>
        ) : (
          <div>
            <label>
              {type === "locobuffer" ? "Port" : "Adress eller parad port"}
              <input list="loconet-portar" value={port} placeholder={type === "locobuffer" ? "/dev/ttyACM0" : "AA:BB:CC:DD:EE:FF"} onChange={(e) => setPort(e.target.value)} />
              <datalist id="loconet-portar">
                {listed.map((p) => (
                  <option key={p.port} value={p.port}>
                    {p.label}
                  </option>
                ))}
              </datalist>
            </label>
            {type === "btlocobridge" ? (
              <label>
                Kanal
                <input type="number" min={1} max={30} value={channel} className="kort-falt" onChange={(e) => setChannel(Number(e.target.value))} />
              </label>
            ) : null}
            {listed.length ? (
              <p className="liten">
                Portar: {listed.map((p) => p.label).join(", ")}
              </p>
            ) : (
              <p className="liten">Ingen port hittades. Sätt i LocoBuffern eller para BTLocoBridgen och läs in sidan igen.</p>
            )}
          </div>
        )}
      </div>
      <div className="rad">
        <button type="button" className="primar" disabled={busy} onClick={connect}>
          Anslut
        </button>
        {loconet.error ? <span className="fel">{loconet.error}</span> : null}
      </div>
    </section>
  );
}

function Asking({ question, busy, on }: { question: Question; busy: boolean; on: Handlers }) {
  const [other, setOther] = useState("");
  const choices = question.choices ?? [];
  return (
    <section className="ruta fraga" aria-label="Fråga" role="alertdialog">
      <p className="overrad">Koppla in frågar</p>
      <h2>{question.text}</h2>
      {question.seen ? <p className="liten">{question.seen}</p> : null}
      <div className="rad">
        {question.answers.map((a) => (
          <button key={a.value} type="button" className={a.value === "yes" ? "primar" : undefined} disabled={busy} onClick={() => on.onAnswer(question.id, a.value, null)}>
            {a.label}
          </button>
        ))}
      </div>
      {choices.length ? (
        <div className="rad annan">
          <label className="kryss">
            {question.object ? "Nej, det är" : "Det är"}
            <select value={other} onChange={(e) => setOther(e.target.value)} aria-label="Spårledningen givaren hör till">
              <option value="">Välj …</option>
              {choices.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <button type="button" disabled={busy || !other} onClick={() => on.onAnswer(question.id, "yes", other)}>
            Bekräfta
          </button>
        </div>
      ) : null}
    </section>
  );
}

function Level({ view, busy, on }: { view: View; busy: boolean; on: Handlers }) {
  const level = view.level_3;
  return (
    <section className="ruta" aria-label="Nivå 3">
      <h2>
        Nivå 3 <span className={`chip ${level.on ? "gron" : ""}`}>{level.on ? "På" : "Av"}</span>
      </h2>
      <p className="liten">
        {level.on
          ? "Med LocoNet ansluten väntar ställverket på växlarnas återrapport, spårledningarna flyttar tågnumren och bara gröna objekt och Utan adress körs."
          : "Nivå 3 slås på när stationen har adresser och kontrollerna för nivå 3 går igenom: unika adresser och en återrapport per växel."}
      </p>
      {level.reason ? <p>{level.reason}</p> : null}
      {level.problems?.length ? (
        <ul className="fel">
          {level.problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      ) : null}
      {level.on ? (
        <button type="button" disabled={busy} onClick={() => on.onLevel(2)}>
          Slå av nivå 3
        </button>
      ) : (
        <button type="button" className="primar" disabled={busy || !level.possible} onClick={() => on.onLevel(3)}>
          Slå på nivå 3
        </button>
      )}
    </section>
  );
}

function Cards({ view, busy, connected, on }: { view: View; busy: boolean; connected: boolean; on: Handlers }) {
  const cards = view.cards ?? [];
  return (
    <section className="ruta" aria-label="MGP-korten">
      <h2>Korten</h2>
      {!cards.length ? (
        <p className="liten">{connected ? "Tryck Discover så svarar korten med sin identitet." : "Inga kort."}</p>
      ) : (
        <table className="tabell">
          <thead>
            <tr>
              <th>Kort</th>
              <th>Typ</th>
              <th>Serienummer</th>
              <th>Modul</th>
              <th>Kanaler</th>
            </tr>
          </thead>
          <tbody>
            {cards.map((c) => (
              <CardRow key={c.address} card={c} busy={busy} on={on} />
            ))}
          </tbody>
        </table>
      )}
      {view.discovered ? <p className="liten">Senaste Discover {new Date(view.discovered).toLocaleString("sv-SE")}.</p> : null}
    </section>
  );
}

function CardRow({ card, busy, on }: { card: Card; busy: boolean; on: Handlers }) {
  const [module, setModule] = useState(card.module ?? "");
  const channels = card.channels ?? [];
  return (
    <tr>
      <td className="tm-mono">{card.address}</td>
      <td>{card.name}</td>
      <td className="tm-mono">{card.serial}</td>
      <td>
        <span className="rad">
          <input className="kort-falt" value={module} placeholder="Modul" aria-label={`Modulen kort ${card.address} sitter i`} onChange={(e) => setModule(e.target.value)} />
          <button type="button" disabled={busy || module === (card.module ?? "")} onClick={() => on.onModule(card.address, module.trim() || null)}>
            Spara
          </button>
        </span>
      </td>
      <td className="kanaler">
        {channels.length
          ? channels.map((ch) => (
              <span key={ch.channel} className="kanal">
                <span className="tm-mono">
                  {ch.channel}:{ch.address}
                </span>{" "}
                {ch.objects?.length ? ch.objects.join(", ") : "–"}
              </span>
            ))
          : card.base
            ? `Basadress ${card.base}`
            : "Basadressen kunde inte läsas."}
      </td>
    </tr>
  );
}

function Objects({ view, busy, connected, pretend, on }: { view: View; busy: boolean; connected: boolean; pretend: boolean; on: Handlers }) {
  const objects = view.objects ?? [];
  if (!objects.length) {
    return (
      <section className="ruta">
        <h2>Objekten</h2>
        <p className="tom">Stationen har ingen stationsmodell. Rita den eller importera den i Spårplan först.</p>
      </section>
    );
  }
  return (
    <section className="ruta" aria-label="Objekten">
      <h2>Objekten</h2>
      <p className="lagen">
        {counts(objects).map(([state, n]) => (
          <span key={state} className={`lage ${STATE_CLASS[state]}`}>
            {STATE_LABEL[state]}: {n}
          </span>
        ))}
      </p>
      {KINDS.map((kind) => {
        const rows = objects.filter((o) => o.kind === kind);
        if (!rows.length) return null;
        return (
          <div key={kind} className="slag">
            <h3>{KIND_TITLE[kind]}</h3>
            <table className="tabell">
              <thead>
                <tr>
                  <th>Namn</th>
                  <th>Läge</th>
                  <th>Adress</th>
                  {kind === "switch" ? <th>Återrapport</th> : null}
                  <th>Kort</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((o) => (
                  <ObjectRow key={o.name} object={o} busy={busy} connected={connected} pretend={pretend} on={on} />
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </section>
  );
}

function ObjectRow({ object, busy, connected, pretend, on }: { object: KopplaObject; busy: boolean; connected: boolean; pretend: boolean; on: Handlers }) {
  const [editing, setEditing] = useState<Edit | null>(null);
  const kind = object.kind;
  const without = object.state === "without";
  return (
    <>
      <tr className={`objekt ${STATE_CLASS[object.state]}`}>
        <td>
          <strong>{object.name}</strong>
          {object.note ? <div className="liten">{object.note}</div> : null}
        </td>
        <td>
          <span className={`lage ${STATE_CLASS[object.state]}`}>{STATE_LABEL[object.state]}</span>
        </td>
        <td className="tm-mono">{addressText(object)}</td>
        {kind === "switch" ? (
          <td>
            {object.feedback ? FEEDBACK_LABEL[object.feedback] : without ? "–" : "ej vald"}
            {object.feedback === "sensors" ? <span className="liten tm-mono"> {object.straight ?? "?"}/{object.diverging ?? "?"}</span> : null}
          </td>
        ) : null}
        <td className="liten">{where(object)}</td>
        <td className="atgarder">
          {!without ? (
            <button type="button" disabled={busy || !connected || (kind !== "track_circuit" && object.address == null)} onClick={() => on.onLearn(kind, object.name)}>
              {learnLabel(kind)}
            </button>
          ) : null}
          {pretend && kind === "track_circuit" && !without ? (
            <button type="button" className="lank" disabled={busy} onClick={() => on.onWagon(object.name, true)}>
              Vagn på
            </button>
          ) : null}
          {pretend && kind === "track_circuit" && !without ? (
            <button type="button" className="lank" disabled={busy} onClick={() => on.onWagon(object.name, false)}>
              av
            </button>
          ) : null}
          <button type="button" className="lank" onClick={() => setEditing(editing ? null : editOf(object))}>
            {editing ? "Stäng" : "Ändra"}
          </button>
        </td>
      </tr>
      {editing ? (
        <tr className="redigera">
          <td colSpan={kind === "switch" ? 6 : 5}>
            <EditRow
              object={object}
              edit={editing}
              busy={busy}
              onEdit={setEditing}
              onSave={() => {
                on.onChange(object, editing);
                setEditing(null);
              }}
            />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function EditRow({ object, edit, busy, onEdit, onSave }: { object: KopplaObject; edit: Edit; busy: boolean; onEdit: (edit: Edit) => void; onSave: () => void }) {
  const switchRow = object.kind === "switch";
  return (
    <div className="rad redigering">
      <label>
        Adress
        <input className="kort-falt" inputMode="numeric" value={edit.address} disabled={edit.without} onChange={(e) => onEdit({ ...edit, address: e.target.value })} />
      </label>
      <label className="kryss">
        <input type="checkbox" checked={edit.reversed} disabled={edit.without} onChange={(e) => onEdit({ ...edit, reversed: e.target.checked })} />
        Omvänd polaritet
      </label>
      <label className="kryss">
        <input type="checkbox" checked={edit.without} onChange={(e) => onEdit({ ...edit, without: e.target.checked })} />
        Utan adress{switchRow ? " (manuell växel)" : object.kind === "signal" ? " (virtuell signal)" : " (ingen givare)"}
      </label>
      {switchRow && !edit.without ? (
        <label>
          Återrapport
          <select value={edit.feedback} onChange={(e) => onEdit({ ...edit, feedback: e.target.value as FeedbackType | "" })}>
            <option value="">Välj …</option>
            {(Object.keys(FEEDBACK_LABEL) as FeedbackType[]).map((f) => (
              <option key={f} value={f}>
                {FEEDBACK_LABEL[f]}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {switchRow && edit.feedback === "sensors" && !edit.without ? (
        <>
          <label>
            Givare rakt
            <input className="kort-falt" value={edit.straight} onChange={(e) => onEdit({ ...edit, straight: e.target.value })} />
          </label>
          <label>
            Givare avvikande
            <input className="kort-falt" value={edit.diverging} onChange={(e) => onEdit({ ...edit, diverging: e.target.value })} />
          </label>
        </>
      ) : null}
      <button type="button" className="primar" disabled={busy} onClick={onSave}>
        Spara
      </button>
    </div>
  );
}

function Lyssna({ listen, connected, on }: { listen: Listen | null; connected: boolean; on: Handlers }) {
  return (
    <details className="ruta felsok" open={listen !== null} onToggle={(e) => on.onListen((e.target as HTMLDetailsElement).open)}>
      <summary>Felsök › Lyssna</summary>
      {listen === null ? (
        <p className="liten">Öppna för att se de senaste LocoNet-meddelandena, avkodade.</p>
      ) : !listen.messages?.length ? (
        <p className="tom">{connected ? "Inga meddelanden än." : "LocoNet är inte anslutet."}</p>
      ) : (
        <table className="tabell lyssna">
          <thead>
            <tr>
              <th>Tid</th>
              <th />
              <th>Bytes</th>
              <th>Betyder</th>
            </tr>
          </thead>
          <tbody>
            {listen.messages.map((m, i) => (
              <tr key={`${m.at}-${i}`}>
                <td className="tm-mono">{heardAt(m)}</td>
                <td>{m.direction === "out" ? "ut" : "in"}</td>
                <td className="tm-mono">{m.hex}</td>
                <td>
                  {m.text}
                  {m.objects?.length ? <div className="liten">{m.objects.join(" · ")}</div> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
  );
}

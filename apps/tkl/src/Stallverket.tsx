// Ställverket på nivå 0 (TKLAPP 02): the strip that says what level 0 is, and the bottom row
// Tåg · Klarering · Händelser. Every button sends a station command through TKL's server; the
// hub's snapshot that comes back is what the screen shows (old TKL: never act locally).
import { useState } from "react";
import type { Action, CallHere, Clearance, Outside, Question, Snapshot, View } from "./api";
import type { Happening } from "./handelser";
import { SOUND_NAMES, type Sounds } from "./ljud";
import { allows, blocks, nameOf, SIDE, trains } from "./niva0";

export type Send = (action: Action, payload: Record<string, unknown>, call?: CallHere, clearance?: Clearance) => void;

type Props = {
  view: View;
  outside: Outside | null;
  journal: Happening[];
  sounds: Sounds;
  busy: boolean;
  onSend: Send;
  onExit: (section: string, exit: string) => void;
};

export function Stallverket({ view, outside, journal, sounds, busy, onSend, onExit }: Props) {
  const snapshot = view.snapshot;
  if (!snapshot) {
    return <p className="tom">{view.message ?? "Väntar på hubben …"}</p>;
  }
  const on = (Object.keys(SOUND_NAMES) as (keyof Sounds)[]).filter((s) => sounds[s]).map((s) => SOUND_NAMES[s].toLowerCase());
  return (
    <>
      <div className="niva">
        <span className="niva-chip">Nivå 0</span>
        <span>
          <b>Klarering utan spårplan.</b> Spårplanen läggs till i Studio. Nivå 1 spårplan · 2 signaler och spårledningar · 3 LocoNet.
        </span>
        <span className="tm-fyll" />
        <span className="liten">{on.length ? `Ljud på för ${on.join(", ")}` : "Ljudet är av på den här skärmen"}</span>
      </div>
      {view.stale ? (
        <p className="gammal" role="status">
          {view.message ?? "Ingen kontakt med hubben."} Det här är det senaste TKL fick{view.heard ? ` ${new Date(view.heard).toLocaleTimeString("sv-SE")}` : ""}.
        </p>
      ) : null}
      {snapshot.automatic ? (
        <p className="gammal" role="status">
          Automatiken sköter {snapshot.place.name} just nu. Trafikledningen kan ge platsen tillbaka i Nu.
        </p>
      ) : null}
      <Questions questions={snapshot.questions} onExit={onExit} />
      <div className="kolumner">
        <Tag snapshot={snapshot} outside={outside} busy={busy} onSend={onSend} />
        <Klarering snapshot={snapshot} outside={outside} busy={busy} onSend={onSend} />
        <Handelser journal={journal} />
      </div>
    </>
  );
}

function Questions({ questions, onExit }: { questions: Question[]; onExit: (section: string, exit: string) => void }) {
  if (!questions.length) return null;
  return (
    <section className="fragor" aria-label="Hubben frågar">
      {questions.map((q) => (
        <div key={q.section} className="fraga">
          <p>
            <b>Hubben frågar:</b> {`Vilken utfart går mot ${q.other_name}?`}
            {q.side ? <span className="liten">{` Sträckan ligger åt ${SIDE[q.side]?.toLowerCase()}.`}</span> : null}
          </p>
          <div className="knappar">
            {q.alternatives.map((a) => (
              <button key={a.exit} type="button" onClick={() => onExit(q.section, a.exit)}>
                {a.name ? `${a.exit} · ${a.name}` : a.exit}
              </button>
            ))}
          </div>
        </div>
      ))}
      <p className="liten">Trafikledningen ser samma fråga i Klienter. Det första svaret gäller hela träffen.</p>
    </section>
  );
}

function TrackChoice({ call, outside, busy, onSend }: { call: CallHere; outside: Outside | null; busy: boolean; onSend: Send }) {
  const [open, setOpen] = useState(false);
  const shown = call.track ?? call.planned_track;
  const label = shown ? `Spår ${shown}` : "Spår?";
  if (!allows(call, "train.track.change") || !outside) {
    return <span className="chip">{label}</span>;
  }
  if (!open) {
    return (
      <button type="button" className="chip knapp-chip" aria-label={`Byt spår för ${call.train_number}`} onClick={() => setOpen(true)}>
        {label} ▾
      </button>
    );
  }
  return (
    <span className="spar-val">
      {outside.tracks.map((track) => (
        <button
          key={track.id}
          type="button"
          disabled={busy}
          aria-pressed={track.id === shown}
          onClick={() => {
            setOpen(false);
            if (track.id !== shown) onSend("train.track.change", { call: call.call, track: track.id }, call);
          }}
        >
          {track.id}
        </button>
      ))}
    </span>
  );
}

function Tag({ snapshot, outside, busy, onSend }: { snapshot: Snapshot; outside: Outside | null; busy: boolean; onSend: Send }) {
  const { coming, atStation, left, next } = trains(snapshot);
  return (
    <section className="kolumn" aria-labelledby="kol-tag">
      <h2 id="kol-tag">
        Tåg <span className="liten">från Hubben</span>
      </h2>
      <h3>På väg hit</h3>
      {coming.length ? (
        coming.map(({ train, call, from, exit }) => (
          <div key={train.call} className="kort kommer">
            <div className="rad">
              <b className="tm-mono">{train.train_number}</b> från {from}
              {exit ? ` · ${exit}` : ""}
              <span className="tm-fyll" />
              {call ? <TrackChoice call={call} outside={outside} busy={busy} onSend={onSend} /> : null}
            </div>
            <p className="liten">
              Avgick {train.departed_at.slice(0, 5)}
              {call?.arrival ? ` · ankomst ${call.arrival.slice(0, 5)} enligt tidtabellen` : ""}
              {train.planned_track ? ` · planerat spår ${train.planned_track}` : ""}
            </p>
            <button
              type="button"
              className="primar"
              disabled={busy || !allows(call, "train.arrived")}
              onClick={() => onSend("train.arrived", { call: train.call, track: call?.track ?? null }, call)}
            >
              Ankommit
            </button>
            <span className="liten"> Tryck när tåget står inne.</span>
          </div>
        ))
      ) : (
        <p className="tom">Inga tåg på väg hit.</p>
      )}
      <h3>På stationen</h3>
      {atStation.length ? (
        atStation.map(({ call, to, waitingFor }) => (
          <div key={call.call} className="kort">
            <div className="rad">
              <b className="tm-mono">{call.train_number}</b>
              {to ? ` · mot ${to}` : " · slutstation"}
              <span className="tm-fyll" />
              <TrackChoice call={call} outside={outside} busy={busy} onSend={onSend} />
            </div>
            <p className="liten">
              {call.departure ? `Avgår ${call.departure.slice(0, 5)} enligt tidtabellen` : "Tåget slutar här"}
              {call.departure_state === "requested" ? " · klarering begärd" : ""}
              {call.departure_state === "cleared" ? " · klart" : ""}
            </p>
            {call.to_place ? (
              <>
                <button type="button" className="primar" disabled={busy || !allows(call, "train.departed")} onClick={() => onSend("train.departed", { call: call.call }, call)}>
                  Avgått
                </button>
                {waitingFor ? <span className="liten"> Väntar på klart från {waitingFor}.</span> : null}
                {allows(call, "line.available.publish") && call.arrival_state === "arrived" && call.from_place ? (
                  <LineFreeButton call={call} snapshot={snapshot} busy={busy} onSend={onSend} />
                ) : null}
              </>
            ) : allows(call, "train.set_aside") ? (
              <button type="button" disabled={busy} onClick={() => onSend("train.set_aside", { call: call.call }, call)}>
                Ställ undan
              </button>
            ) : null}
          </div>
        ))
      ) : (
        <p className="tom">Inga tåg på stationen.</p>
      )}
      <h3>Har lämnat</h3>
      {left.length ? (
        left.map(({ train, to, exit }) => (
          <div key={train.call} className="kort">
            <div className="rad">
              <b className="tm-mono">{train.train_number}</b> mot {to}
              {exit ? ` · ${exit}` : ""}
              <span className="tm-fyll" />
              <span className="chip">På linjen</span>
            </div>
            <p className="liten">Försvinner härifrån när {to} tagit emot det.</p>
          </div>
        ))
      ) : (
        <p className="tom">Inga tåg på linjen härifrån.</p>
      )}
      <h3>Härnäst enligt tidtabellen</h3>
      {next.length ? (
        <ul className="harnast">
          {next.map(({ call, time, kind, other }) => (
            <li key={call.call}>
              <span className="tm-mono">{time.slice(0, 5)}</span> {kind} <b className="tm-mono">{call.train_number}</b> {kind === "Ank" ? "från" : "mot"} {other}
              {call.planned_track ? <span className="liten"> · spår {call.planned_track}</span> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="tom">Inget mer i dag.</p>
      )}
      <p className="liten fot">Tågnummer, planerat spår, tidtabell och tåg på väg hit kommer från Hubben. Utan spårplan följer tågnumret knapparna.</p>
    </section>
  );
}

function LineFreeButton({ call, snapshot, busy, onSend }: { call: CallHere; snapshot: Snapshot; busy: boolean; onSend: Send }) {
  const section = snapshot.sections.find((s) => s.other_place === call.from_place);
  if (!section) return null;
  return (
    <button type="button" disabled={busy} onClick={() => onSend("line.available.publish", { call: call.call, section: section.section }, call)}>
      Linjen ledig
    </button>
  );
}

function Klarering({ snapshot, outside, busy, onSend }: { snapshot: Snapshot; outside: Outside | null; busy: boolean; onSend: Send }) {
  const [showAll, setShowAll] = useState(false);
  const here = snapshot.place.name;
  return (
    <section className="kolumn" aria-labelledby="kol-klarering">
      <h2 id="kol-klarering">
        Klarering <span className="liten">begäran och svar</span>
      </h2>
      {blocks(snapshot, outside).map((block) => (
        <div key={block.section.section} className="block">
          <h3>
            {block.heading}
            {block.neighbour?.phone ? <span className="liten tm-mono"> · tel {block.neighbour.phone}</span> : null}
          </h3>
          {block.incoming.map((c) => {
            const call = snapshot.calls.find((x) => x.train_number === c.train_number && x.from_place === c.from_place);
            return (
              <div key={c.clearance_id} className="kort begaran">
                {c.reminders ? <p className="paminn">▲ Påminnelse · obesvarad sedan {c.requested_at.slice(0, 5)}</p> : null}
                <p>
                  <b>Begäran</b> {nameOf(snapshot, c.from_place)} begär klart för <b className="tm-mono">{c.train_number}</b> hit
                </p>
                <p className="liten">
                  {block.section.exit ? `På ${block.section.exit}` : `Från ${nameOf(snapshot, c.from_place)}`}
                  {call?.planned_track ? `, planerat spår ${call.planned_track}.` : "."}
                </p>
                <button type="button" className="primar" disabled={busy} onClick={() => onSend("clearance.response", { clearance_id: c.clearance_id, approved: true }, undefined, c)}>
                  Ge klart
                </button>{" "}
                <button type="button" className="fara" disabled={busy} onClick={() => onSend("clearance.response", { clearance_id: c.clearance_id, approved: false }, undefined, c)}>
                  Neka
                </button>
                <span className="liten"> Trafikledningen ser den.</span>
              </div>
            );
          })}
          {block.asked.map((c) => (
            <div key={c.clearance_id} className="kort">
              <p>
                Du begärde klart för <b className="tm-mono">{c.train_number}</b> <span className="chip">Väntar på svar</span>
              </p>
              {c.reminders ? <p className="liten">{`${nameOf(snapshot, c.to_place)} har påmints ${c.reminders} gång${c.reminders === 1 ? "" : "er"}.`}</p> : null}
              <button type="button" disabled={busy} onClick={() => onSend("clearance.cancel", { clearance_id: c.clearance_id }, undefined, c)}>
                Återta
              </button>
            </div>
          ))}
          {block.cleared.map((c) => (
            <div key={c.clearance_id} className="kort klart">
              <p>
                Klart för <b className="tm-mono">{c.train_number}</b> mot {nameOf(snapshot, c.to_place)} <span className="chip gron">Klart</span>
              </p>
              <button type="button" disabled={busy} onClick={() => onSend("clearance.cancel", { clearance_id: c.clearance_id }, undefined, c)}>
                Återta
              </button>
            </div>
          ))}
          {block.clearedIn.map((c) => (
            <div key={c.clearance_id} className="kort">
              <p>
                {nameOf(snapshot, c.from_place)} har klart för <b className="tm-mono">{c.train_number}</b> hit <span className="chip gron">Klart</span>
              </p>
              {block.section.clearance_mode === "direct" ? <p className="liten">Direkt klarering: Hubben gav klart när linjen var fri.</p> : null}
            </div>
          ))}
          {block.lineFree.map((id) => (
            <div key={id} className="kort">
              <p>{nameOf(snapshot, block.section.other_place)}: linjen ledig</p>
              <button type="button" disabled={busy} onClick={() => onSend("line.available.acknowledge", { message_id: id })}>
                Kvittera
              </button>
            </div>
          ))}
          {block.free && !block.incoming.length && !block.clearedIn.length ? (
            <div className="rad fri">
              <span>Linjen fri</span>
              <span className="tm-fyll" />
              {block.canAsk ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    block.canAsk &&
                    onSend(
                      "clearance.request",
                      { call: block.canAsk.call, section: block.section.section, clearance_id: `tkl-${Date.now().toString(36)}-${block.canAsk.call}`.slice(0, 80) },
                      block.canAsk,
                    )
                  }
                >
                  Begär klart för {block.canAsk.train_number}
                </button>
              ) : null}
            </div>
          ) : block.section.occupied && !block.asked.length && !block.cleared.length && !block.incoming.length && !block.clearedIn.length ? (
            <p className="liten">Linjen har ett tåg på sig.</p>
          ) : null}
        </div>
      ))}
      <div className="block telefon">
        <h3>Telefon · från Hubben</h3>
        <ul>
          {(showAll ? snapshot.all_places : snapshot.neighbours).map((n) => (
            <li key={n.place}>
              {n.name} <span className="liten">{n.place === snapshot.place.place ? "här" : snapshot.neighbours.some((x) => x.place === n.place) ? "granne" : n.code}</span>
              <span className="tm-fyll" />
              <span className="tm-mono">{n.phone ?? "–"}</span>
            </li>
          ))}
        </ul>
        <p className="liten">
          Numren slås upp i Hubben, för {here}s grannar och alla stationer.{" "}
          <button type="button" className="lank" onClick={() => setShowAll(!showAll)}>
            {showAll ? "Bara grannarna" : "Alla stationer ›"}
          </button>
        </p>
      </div>
    </section>
  );
}

function Handelser({ journal }: { journal: Happening[] }) {
  return (
    <section className="kolumn" aria-labelledby="kol-handelser">
      <h2 id="kol-handelser">
        Händelser <span className="liten">senaste först</span>
      </h2>
      {journal.length ? (
        <ul className="handelser">
          {journal.map((h) => (
            <li key={h.id}>
              <span className="tm-mono">{h.time}</span> {h.text}
            </li>
          ))}
        </ul>
      ) : (
        <p className="tom">Inget har hänt sedan sidan öppnades.</p>
      )}
    </section>
  );
}

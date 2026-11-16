import { useState } from "react";
import type { Now, Weekday } from "./api";
import { busyTrains, buildChange, callsOf, changeText, emptyDraft, KINDS, placesOf, sectionName, statusText, trainsOf, type ChangeKind, type ChangeNow, type Draft, type DriftChange, type Package } from "./changes";
import { WEEKDAYS } from "./drift";
import { Chip, Chips } from "./ui";

// Driftändringar in Nu (TRAFIK-02, DRIFT-41, H38): the ten kinds. Each applies at once and
// becomes a proposal for the next version; against a train that is out it waits until the
// train is in, and Trafikledningen can force it through. Släpp takes it away.

export type ChangeProps = {
  now: Now;
  pkg: Package | null;
  onMake?: (change: DriftChange) => void;
  onDrop?: (id: string) => void;
  onForce?: (id: string) => void;
};

export function Andringar({ now, pkg, onMake, onDrop, onForce }: ChangeProps) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const changes = (now.changes ?? []) as ChangeNow[];
  const live = changes.filter((change) => change.status !== "dropped").length;
  return (
    <section id="changes" aria-labelledby="changes-title">
      <div className="rad mellan">
        <h2 id="changes-title">
          Driftändringar{" "}
          <span id="change-count" className="antal">
            {live}
          </span>
        </h2>
        <button id="new-change" type="button" aria-expanded={open} onClick={() => (setOpen(!open), setDraft(null))}>
          Ny driftändring
        </button>
      </div>
      {open && (
        <div id="change-panel" className="kort">
          <p className="liten">Välj slag. Ändringen gäller direkt och blir ett förslag till nästa version i Planering.</p>
          <div className="slag" role="group" aria-label="Slag av driftändring">
            {KINDS.map(([kind, title, note]) => (
              <button key={kind} type="button" aria-pressed={draft?.kind === kind} onClick={() => setDraft(emptyDraft(kind, now))}>
                <b>{title}</b>
                <span className="liten">{note}</span>
              </button>
            ))}
          </div>
          {draft && pkg && <Form now={now} pkg={pkg} draft={draft} setDraft={setDraft} onMake={(change) => (onMake?.(change), setOpen(false), setDraft(null))} />}
          {draft && !pkg && <p className="liten">Läser tidtabellen …</p>}
        </div>
      )}
      <ul id="change-list" className="lista">
        {changes.length ? (
          [...changes].reverse().map((change) => (
            <li key={change.change_id} className={change.status === "waiting" ? "vantar" : change.status === "dropped" ? "slappt" : undefined}>
              <div className="vem">
                <b>{changeText(change.change, pkg, change.train_number)}</b>
                <span className="liten">{`${statusText(change)} · gjord ${change.made}`}</span>
              </div>
              {change.status !== "dropped" && (
                <span className="rad">
                  {change.status === "waiting" && (
                    <button type="button" className="fara" onClick={() => onForce?.(change.change_id)} aria-describedby="force-note">
                      Tvinga igenom
                    </button>
                  )}
                  <button type="button" onClick={() => onDrop?.(change.change_id)}>
                    Släpp
                  </button>
                </span>
              )}
            </li>
          ))
        ) : (
          <li className="tom">Inga driftändringar. Tidtabellen körs som versionen säger.</li>
        )}
      </ul>
      {changes.some((change) => change.status === "waiting") && (
        <p id="force-note" className="liten">
          Tvingar du igenom en ändring gäller den direkt, fast tåget är ute. Det som inte längre körs stängs.
        </p>
      )}
    </section>
  );
}

function Form({ now, pkg, draft, setDraft, onMake }: { now: Now; pkg: Package; draft: Draft; setDraft: (draft: Draft) => void; onMake: (change: DriftChange) => void }) {
  const change = (part: Partial<Draft>) => setDraft({ ...draft, ...part });
  const built = buildChange(draft);
  const busy = busyTrains(draft, pkg, now);
  const title = KINDS.find(([kind]) => kind === draft.kind)?.[1] ?? "";
  const trains = trainsOf(pkg);
  const kind: ChangeKind = draft.kind;
  const trainField = (label = "Tåg") => (
    <label>
      {label}
      <select id="change-train" value={draft.train} onChange={(event) => change({ train: event.target.value, call: "" })}>
        <option value="">Välj tåg</option>
        {trains.map((train) => (
          <option key={train.id} value={train.id}>
            {train.number}
          </option>
        ))}
      </select>
    </label>
  );
  const callField = (label: string, whole?: string) => (
    <label>
      {label}
      <select id="change-call" value={draft.call} onChange={(event) => change({ call: event.target.value })} disabled={!draft.train}>
        <option value="">{whole ?? "Välj driftplats"}</option>
        {callsOf(pkg, draft.train).map((call) => (
          <option key={call.id} value={call.id}>
            {`${pkg.places.find((p) => p.id === call.place)?.name ?? call.place} ${call.departure ?? call.arrival ?? ""}`}
          </option>
        ))}
      </select>
    </label>
  );
  const sectionField = (
    <label>
      Sträcka
      <select id="change-section" value={draft.section} onChange={(event) => change({ section: event.target.value })}>
        <option value="">Välj sträcka</option>
        {(pkg.sections ?? []).map((section) => (
          <option key={section.id} value={section.id}>
            {sectionName(pkg, section.id)}
          </option>
        ))}
      </select>
    </label>
  );
  const dayField = (
    <Chips label="Trafikdagar">
      {WEEKDAYS.map(([day, name]) => (
        <Chip key={day} label={name.slice(0, 3)} pressed={draft.days.includes(day)} onClick={() => change({ days: draft.days.includes(day) ? draft.days.filter((d) => d !== day) : [...draft.days, day as Weekday] })} />
      ))}
    </Chips>
  );
  const callTracks = () => {
    const call = callsOf(pkg, draft.train).find((c) => c.id === draft.call);
    return pkg.places.find((p) => p.id === call?.place)?.tracks ?? [];
  };
  return (
    <form
      id="change-form"
      className="formular"
      aria-label={title}
      onSubmit={(event) => {
        event.preventDefault();
        if (typeof built !== "string") onMake(built);
      }}
    >
      <h3>{title}</h3>
      <div className="rad">
        {kind === "cancel" && trainField()}
        {kind === "extra" && (
          <>
            <Chips label="Extratåg">
              <Chip label="Kopia av ett tåg" pressed={draft.copy} onClick={() => change({ copy: true })} />
              <Chip label="Från–till" pressed={!draft.copy} onClick={() => change({ copy: false })} />
            </Chips>
            <label>
              Nytt nummer <input id="change-number" size={6} value={draft.number} onChange={(event) => change({ number: event.target.value })} />
            </label>
            {draft.copy ? (
              <label>
                Kopia av
                <select id="change-copy" value={draft.copyOf} onChange={(event) => change({ copyOf: event.target.value })}>
                  <option value="">Välj tåg</option>
                  {trains.map((train) => (
                    <option key={train.id} value={train.id}>
                      {train.number}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <>
                <PlaceSelect id="change-from" label="Från" pkg={pkg} value={draft.from} onChange={(from) => change({ from })} />
                <PlaceSelect id="change-to" label="Till" pkg={pkg} value={draft.to} onChange={(to) => change({ to })} />
              </>
            )}
            <label>
              Avgång <input id="change-departure" type="time" step={60} value={draft.departure} onChange={(event) => change({ departure: event.target.value })} />
            </label>
            {dayField}
          </>
        )}
        {kind === "times" && (
          <>
            {trainField()}
            {callField("Från", "Hela tåget")}
            <label>
              Minuter <input id="change-minutes" inputMode="numeric" size={5} value={draft.minutes} onChange={(event) => change({ minutes: event.target.value })} />
            </label>
          </>
        )}
        {kind === "place" && (
          <>
            <Chips label="Vad ändras">
              <Chip label="Sträcka" pressed={draft.onSection} onClick={() => change({ onSection: true })} />
              <Chip label="Driftplats" pressed={!draft.onSection} onClick={() => change({ onSection: false })} />
            </Chips>
            {draft.onSection ? (
              <>
                {sectionField}
                <Chips label="Sträckan">
                  {(
                    [
                      ["closed", "Stängd"],
                      ["open", "Öppen"],
                      ["requested", "Klareras med begäran"],
                      ["direct", "Klareras direkt"],
                    ] as const
                  ).map(([value, label]) => (
                    <Chip key={value} label={label} pressed={draft.sectionChange === value} onClick={() => change({ sectionChange: value })} />
                  ))}
                </Chips>
              </>
            ) : (
              <>
                <PlaceSelect id="change-place" label="Driftplats" pkg={pkg} value={draft.place} onChange={(place) => change({ place })} />
                <Chips label="Driftplatsen">
                  <Chip label="Obemannad, automatiken sköter den" pressed={draft.placeKind === "unmanned"} onClick={() => change({ placeKind: "unmanned" })} />
                  <Chip label="Bemannad" pressed={draft.placeKind === "manned"} onClick={() => change({ placeKind: "manned" })} />
                </Chips>
              </>
            )}
          </>
        )}
        {kind === "track" && (
          <>
            {trainField()}
            {callField("Driftplats")}
            <label>
              Spår
              <select id="change-track" value={draft.track} onChange={(event) => change({ track: event.target.value })} disabled={!draft.call}>
                <option value="">Välj spår</option>
                {callTracks().map((track) => (
                  <option key={track.name} value={track.name}>
                    {track.name}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
        {kind === "tracks" && (
          <>
            {sectionField}
            <Chips label="Sträckan körs">
              <Chip label="Enkelspår" pressed={draft.tracks === "single"} onClick={() => change({ tracks: "single" })} />
              <Chip label="Dubbelspår" pressed={draft.tracks === "double"} onClick={() => change({ tracks: "double" })} />
            </Chips>
          </>
        )}
        {kind === "days" && (
          <>
            {trainField()}
            {dayField}
          </>
        )}
        {kind === "number" && (
          <>
            {trainField()}
            <label>
              Nytt nummer <input id="change-number" size={6} value={draft.number} onChange={(event) => change({ number: event.target.value })} />
            </label>
          </>
        )}
        {kind === "no_stop" && (
          <>
            {trainField()}
            {callField("Driftplats")}
            <Chips label="Uppehåll">
              <Chip label="Ej uppehåll" pressed={!draft.stops} onClick={() => change({ stops: false })} />
              <Chip label="Uppehåll" pressed={draft.stops} onClick={() => change({ stops: true })} />
            </Chips>
          </>
        )}
        {kind === "note" && (
          <>
            {trainField()}
            {callField("Vid", "Hela tåget")}
            <label>
              Anmärkning <input id="change-text" size={30} maxLength={200} value={draft.text} onChange={(event) => change({ text: event.target.value })} />
            </label>
          </>
        )}
      </div>
      {busy.length > 0 && (
        <p id="change-busy" className="pamin">
          {`Tåg ${busy.join(", ")} är ute eller har en öppen klarering. Ändringen väntar tills tåget är framme; du kan tvinga igenom den i listan.`}
        </p>
      )}
      <div className="rad">
        <button id="make-change" type="submit" className="primar" disabled={typeof built === "string"}>
          Gör ändringen
        </button>
        {typeof built === "string" && <span className="liten">{built}</span>}
      </div>
    </form>
  );
}

function PlaceSelect({ id, label, pkg, value, onChange }: { id: string; label: string; pkg: Package; value: string; onChange: (value: string) => void }) {
  return (
    <label>
      {label}
      <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Välj driftplats</option>
        {placesOf(pkg).map((place) => (
          <option key={place.id} value={place.id}>
            {place.name}
          </option>
        ))}
      </select>
    </label>
  );
}

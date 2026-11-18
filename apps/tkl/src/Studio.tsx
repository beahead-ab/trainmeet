// Studio på nivå 0 (TKL21, KLAR-01): tracks and exits as a list, without a drawing. The list is
// the station's outside; it is saved on the computer, and Ny version av utsidan makes the version
// that goes with the next connection (TKL25). The telephone number is in the hub, not here (H24).
import { useState } from "react";
import type { Exit, Outside, Studio as StudioData, Track } from "./api";
import { SIDE } from "./niva0";

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$/;

/** What is wrong with the list, in words; empty when it can be saved. */
export function problems(outside: Outside): string[] {
  const found: string[] = [];
  const trackIds = outside.tracks.map((t) => t.id);
  const exitIds = outside.exits.map((e) => e.id);
  if (!outside.tracks.length) found.push("Stationen behöver minst ett spår.");
  if (!outside.exits.length) found.push("Stationen behöver minst en utfart.");
  for (const id of [...trackIds, ...exitIds]) {
    if (!ID_PATTERN.test(id)) found.push(`"${id}" går inte som id: bokstäver, siffror, punkt, kolon eller bindestreck.`);
  }
  if (new Set(trackIds).size !== trackIds.length) found.push("Två spår har samma id.");
  if (new Set(exitIds).size !== exitIds.length) found.push("Två utfarter har samma id.");
  if (outside.tracks.some((t) => !t.label.trim())) found.push("Varje spår behöver en etikett.");
  return found;
}

export function Studio({ studio, onSave, onVersion }: { studio: StudioData; onSave: (outside: Outside) => Promise<void>; onVersion: () => Promise<void> }) {
  const [draft, setDraft] = useState<Outside>(studio.draft);
  const [message, setMessage] = useState("");
  const wrong = problems(draft);
  const dirty = JSON.stringify(draft) !== JSON.stringify(studio.draft);
  const latest = studio.versions?.[0];
  const setTrack = (index: number, change: Partial<Track>) =>
    setDraft({ ...draft, tracks: draft.tracks.map((t, i) => (i === index ? { ...t, ...change } : t)) });
  const setExit = (index: number, change: Partial<Exit>) =>
    setDraft({ ...draft, exits: draft.exits.map((e, i) => (i === index ? { ...e, ...change } : e)) });
  const save = async () => {
    setMessage("");
    try {
      await onSave(draft);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte att spara.");
    }
  };
  return (
    <div className="studio">
      <div className="sidrubrik">
        <h1>{draft.name} på nivå 0 – bara klarering</h1>
        <p className="liten">
          Skriv spåren och utfarterna som en lista: det är stationens utsida, det träffen får veta. Spårets id är det korta namnet, till exempel 1a. Telefonnumret står i Hubben, inte här.
        </p>
      </div>
      <section className="ruta">
        <h2>Spår</h2>
        <table>
          <thead>
            <tr>
              <th>Spår</th>
              <th>Etikett</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {draft.tracks.map((track, index) => (
              <tr key={index}>
                <td>
                  <input aria-label={`Spår ${index + 1}, id`} className="tm-mono kort-falt" value={track.id} onChange={(e) => setTrack(index, { id: e.target.value.trim() })} />
                </td>
                <td>
                  <input aria-label={`Spår ${index + 1}, etikett`} value={track.label} onChange={(e) => setTrack(index, { label: e.target.value })} />
                </td>
                <td>
                  <button type="button" className="lank" onClick={() => setDraft({ ...draft, tracks: draft.tracks.filter((_, i) => i !== index) })}>
                    Ta bort
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          type="button"
          onClick={() => {
            const next = String(draft.tracks.length + 1);
            setDraft({ ...draft, tracks: [...draft.tracks, { id: next, label: `Spår ${next}` }] });
          }}
        >
          + Lägg till spår
        </button>
      </section>
      <section className="ruta">
        <h2>Utfarter</h2>
        <table>
          <thead>
            <tr>
              <th>Utfart</th>
              <th>Sida</th>
              <th>Mot</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {draft.exits.map((exit, index) => (
              <tr key={index}>
                <td>
                  <input aria-label={`Utfart ${index + 1}, id`} className="tm-mono kort-falt" value={exit.id} onChange={(e) => setExit(index, { id: e.target.value.trim() })} />
                </td>
                <td>
                  <select aria-label={`Utfart ${index + 1}, sida`} value={exit.side} onChange={(e) => setExit(index, { side: e.target.value as Exit["side"] })}>
                    {Object.entries(SIDE).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input aria-label={`Utfart ${index + 1}, mot`} placeholder="Till exempel Mot Västby" value={exit.name ?? ""} onChange={(e) => setExit(index, { name: e.target.value || null })} />
                </td>
                <td>
                  <button type="button" className="lank" onClick={() => setDraft({ ...draft, exits: draft.exits.filter((_, i) => i !== index) })}>
                    Ta bort
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          type="button"
          onClick={() => setDraft({ ...draft, exits: [...draft.exits, { id: String.fromCharCode(65 + draft.exits.length), side: "right", name: null, tracks: [], signals: [] }] })}
        >
          + Lägg till utfart
        </button>
        <p className="liten">Skriv grannens namn i Mot, så kan Hubben koppla utfarten till rätt sträcka själv. Är den osäker frågar den när TKL ansluter.</p>
      </section>
      {wrong.length ? (
        <ul className="fel" role="alert">
          {wrong.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
      {message ? (
        <p className="fel" role="alert">
          {message}
        </p>
      ) : null}
      <div className="fot rad">
        <span className="liten">
          {latest ? `Version ${latest.number} · ${new Date(latest.saved).toLocaleString("sv-SE")}` : "Ingen version än"}
          {studio.changed || dirty ? " · listan har ändrats sedan dess" : ""}
          {studio.station_model ? " · stationsmodellen följer med versionen" : ""}
        </span>
        <span className="tm-fyll" />
        <button type="button" disabled={!dirty || wrong.length > 0} onClick={() => void save()}>
          Spara på datorn
        </button>
        <button type="button" className="primar" disabled={dirty || !studio.changed || wrong.length > 0} onClick={() => void onVersion()}>
          Ny version av utsidan
        </button>
      </div>
    </div>
  );
}

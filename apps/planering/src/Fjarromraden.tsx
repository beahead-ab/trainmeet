import { useState } from "react";
import { planning, type Draft } from "./api";
import { areaChange, areaChoices, areaId, areaPlaces, type Package, type RemoteArea } from "./data";

// Fjärrområden i Data (PLAN-04, PLAN-33, FR49): the planner names an area and chooses its
// driftplatser, which must hang together along the line. Each is then planned as remote-controlled
// from the area. It is only the default: during the meet each station hands itself over, and the
// operating form decides (TKL87). Hubben says no to an area that does not hang together.

type Props = {
  meet: string;
  draft: Draft;
  pkg: Package;
  onDraft?: ((draft: Draft) => void) | undefined;
  onTell?: ((text: string, good?: boolean) => void) | undefined;
  onFail?: ((error: unknown) => void) | undefined;
};

export function Fjarromraden({ meet, draft, pkg, onDraft, onTell, onFail }: Props) {
  const areas = pkg.remote_areas ?? [];
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const placeName = (id: string) => pkg.places.find((place) => place.id === id)?.name ?? id;

  const open = (area: RemoteArea | null) => {
    setEditing(area?.id ?? "");
    setName(area?.name ?? "");
    setChosen(area?.places ?? []);
  };
  const save = async (id: string, given: string | null, places: string[], said: string) => {
    try {
      onDraft?.(await planning.change(meet, { revision: draft.revision ?? 0, changes: [areaChange(pkg, id, given, places)] }));
      onTell?.(said, true);
      setEditing(null);
    } catch (error) {
      onFail?.(error);
    }
  };
  const toggle = (place: string) => setChosen((list) => (list.includes(place) ? list.filter((item) => item !== place) : [...list, place]));

  return (
    <section className="kort data-kort" id="fjarromraden" aria-labelledby="fjarromraden-rubrik">
      <h2 id="fjarromraden-rubrik">Fjärrområden</h2>
      <p className="liten">Driftplatser i rad längs linjen som är tänkta att fjärrstyras tillsammans, av ett fjärrställverk. Det är ett förval: på träffen lämnar varje station över själv.</p>
      <ul id="remote-areas" className="lista">
        {areas.length ? (
          areas.map((area) => (
            <li key={area.id}>
              <div className="vem">
                <b>{area.name}</b>
                <span className="liten">{areaPlaces(area, placeName)}</span>
              </div>
              <div className="kontroller">
                <button type="button" onClick={() => open(area)}>
                  Ändra
                </button>
                <button type="button" className="fara" onClick={() => void save(area.id, null, [], `Fjärrområdet ${area.name} är borttaget.`)}>
                  Ta bort
                </button>
              </div>
            </li>
          ))
        ) : (
          <li className="tom">Inga fjärrområden i planen.</li>
        )}
      </ul>
      {editing === null ? (
        <button id="new-area" type="button" className="sekundar" onClick={() => open(null)}>
          + Nytt fjärrområde
        </button>
      ) : (
        <form
          id="area-form"
          className="formular"
          onSubmit={(event) => {
            event.preventDefault();
            const id = editing || areaId(name, areas.map((area) => area.id));
            void save(id, name, chosen, `Fjärrområdet ${name.trim()} är sparat.`);
          }}
        >
          <label>
            Namn <input id="area-name" maxLength={60} value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <fieldset>
            <legend>Driftplatserna, som hänger ihop längs linjen</legend>
            {areaChoices(pkg).map((place) => (
              <label key={place.id} className="val">
                <input type="checkbox" checked={chosen.includes(place.id)} onChange={() => toggle(place.id)} /> {`${place.name} (${place.code})`}
              </label>
            ))}
          </fieldset>
          <div className="rad">
            <button type="submit" className="primar" disabled={!name.trim() || !chosen.length}>
              Spara fjärrområdet
            </button>
            <button type="button" className="lank" onClick={() => setEditing(null)}>
              Avbryt
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

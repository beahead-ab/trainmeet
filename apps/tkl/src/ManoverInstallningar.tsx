// Manöver in Studio › Spårplan (STV-46, TKL86): the owner's free panel, set for the station. The
// symbols and colours come from one of the standard skins 59, 85 and 95, so that the same symbol
// means the same thing on every station; the owner renames what is shown for a track, a signal or
// a switch, and turns the track names, switch numbers, signal ids, train numbers and the row of
// buttons on or off. The ids stay, so every click still asks the interlocking by the id. The
// settings are station settings, the same on every screen, kept by TKL's server with the model
// and versioned with it; the server refuses a label for something the panel lacks.
import { useEffect, useState } from "react";
import { api, Problem, type Manover, type Panel } from "./api";
import { DEFAULT_MANOVER, ownerChoices, SKIN_NAMES, type ShownKey, type StandardId } from "./skal";

const SYMBOLS: [StandardId, string][] = [
  ["85", "85 · TDOK 2014:0693"],
  ["95", "95 · TDOK 2021:0552"],
  ["59", "59 · SJ:s modell 59"],
];
const SHOWN: [ShownKey, string][] = [
  ["track_names", "Spårnamn"],
  ["switch_numbers", "Växelnummer"],
  ["signal_ids", "Signalernas id"],
  ["train_numbers", "Tågnummer"],
  ["functions", "Raden Panelens knappar"],
];
type Kind = "tracks" | "signals" | "switches";

/** The settings as they are sent: every label trimmed, the empty ones and those that only
 * repeat the id left out. */
export function cleaned(settings: Manover): Manover {
  const { shown, labels } = ownerChoices(settings);
  const clean = (given: Record<string, string>) =>
    Object.fromEntries(
      Object.entries(given)
        .map(([id, label]) => [id, label.trim()] as const)
        .filter(([id, label]) => label && label !== id),
    );
  return { symbols: settings.symbols, shown, labels: { tracks: clean(labels.tracks), signals: clean(labels.signals), switches: clean(labels.switches) } };
}

export function ManoverInstallningar({ panel, initial }: { panel: Panel; initial?: Manover }) {
  const [saved, setSaved] = useState<Manover | null>(initial ?? null);
  const [draft, setDraft] = useState<Manover>(initial ?? DEFAULT_MANOVER);
  const [message, setMessage] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (initial) return;
    api
      .manover()
      .then((found) => {
        setSaved(found);
        setDraft(found);
      })
      .catch((error: unknown) => setMessage(error instanceof Error ? error.message : "TKL svarar inte."));
  }, [initial]);

  const { shown, labels } = ownerChoices(draft);
  const changed = saved === null || JSON.stringify(cleaned(draft)) !== JSON.stringify(cleaned(saved));
  const ids: Record<Kind, string[]> = {
    tracks: (panel.track_names ?? []).map((t) => t.name),
    signals: (panel.signals ?? []).map((s) => s.name),
    switches: (panel.switches ?? []).map((s) => s.number),
  };
  const setLabel = (kind: Kind, id: string, label: string) => setDraft({ ...draft, labels: { ...labels, [kind]: { ...labels[kind], [id]: label } } });
  const save = async (settings: Manover) => {
    setBusy(true);
    setMessage("");
    setProblems([]);
    try {
      const kept = await api.saveManover(cleaned(settings));
      setSaved(kept);
      setDraft(kept);
      setMessage("Sparat. Manöver visar det på alla skärmar när Ställverket öppnas på nytt.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte att spara.");
      setProblems(error instanceof Problem ? error.problems : []);
    } finally {
      setBusy(false);
    }
  };
  const list = (kind: Kind, title: string) => (
    <details className="manover-etiketter">
      <summary>
        {title} ({ids[kind].length}){Object.values(labels[kind]).some((l) => l.trim()) ? ` · ${Object.values(labels[kind]).filter((l) => l.trim()).length} med egen etikett` : ""}
      </summary>
      <div className="manover-lista">
        {ids[kind].map((id) => (
          <label key={id}>
            <span className="tm-mono">{id}</span>
            <input value={labels[kind][id] ?? ""} placeholder={id} maxLength={24} aria-label={`${title}: etikett för ${id}`} onChange={(e) => setLabel(kind, id, e.target.value)} />
          </label>
        ))}
      </div>
    </details>
  );
  return (
    <section className="ruta manover-ruta" aria-labelledby="manover-rubrik">
      <h2 id="manover-rubrik">Manöver · ägarens fria panel</h2>
      <p className="liten">
        Manöver visar {panel.source === "plan" ? "stationens egen panel, byggd ur dess spårplan," : "panelen som motorn lägger ut den, tills spårplanen ritas om i Studio,"} med symboler och färger ur ett av standardskalen, så att samma symbol betyder samma sak på alla stationer. Etiketterna byter bara det som
        visas; id:na är desamma. Inställningarna gäller stationen på alla skärmar, sparas med stationsmodellen och följer med nästa version av utsidan. Välj skalet {SKIN_NAMES.manover} i Ställverket.
      </p>
      <div className="manover-val">
        <fieldset>
          <legend>Symboler och färger ur</legend>
          {SYMBOLS.map(([id, name]) => (
            <label key={id}>
              <input type="radio" name="manover-symboler" value={id} checked={draft.symbols === id} onChange={() => setDraft({ ...draft, symbols: id })} /> {name}
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend>Visas</legend>
          {SHOWN.map(([key, name]) => (
            <label key={key}>
              <input type="checkbox" checked={shown[key]} onChange={(e) => setDraft({ ...draft, shown: { ...shown, [key]: e.target.checked } })} /> {name}
            </label>
          ))}
        </fieldset>
      </div>
      <h3>Egna etiketter</h3>
      {list("tracks", "Spår")}
      {list("signals", "Signaler")}
      {list("switches", "Växlar")}
      <div className="rad">
        <button type="button" className="primar" disabled={busy || !changed} onClick={() => void save(draft)}>
          Spara Manöver
        </button>
        <button type="button" className="lank" disabled={busy} onClick={() => setDraft(DEFAULT_MANOVER)}>
          Tillbaka till förvalen
        </button>
        {message ? (
          <span className={problems.length ? "liten fel-text" : "liten"} role="status">
            {message}
          </span>
        ) : null}
      </div>
      {problems.length ? (
        <ul className="problem">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

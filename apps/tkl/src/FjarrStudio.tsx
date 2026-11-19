// Studio › Inställningar › Fjärrstyrning (#36 del b, TKL46, FR10, FR16, FR24, FR29, FR40): the
// owner chooses which of the station's train routes may be requested from afar, by line end, in
// from it and out to it, with the quick choices alla, inga, alla utom ett spår and bara vissa
// spår. Shunting routes are never in the list. The station automats: A3, A2 and A1 for the whole
// station, AN and AU for one entry signal each, and the local release automats, with the default
// one the station switches on after 90 seconds without contact. Who may receive the station:
// neighbours, remote interlockings, or both. The choice is kept with the station's model and goes
// with the next version of the outside, which then has the catalogue and the overview; a station
// at level 0 has none (FR16).
import "./fjarrstation.css";
import { useEffect, useState } from "react";
import { api, Problem, type AutomatKind, type AutomatSpec, type Fjarr, type FjarrStudio as Studio, type ReceiverKind } from "./api";
import { codeFor, grouped, KIND_NAMES, quick, tracksOf, type Quick } from "./fjarrstation";

const RECEIVERS: [ReceiverKind, string][] = [
  ["neighbours", "Grannar längs linjen"],
  ["remote", "Fjärrställverk"],
];
const NEW_KINDS: AutomatKind[] = ["a3", "a2", "a1", "an", "au"];

export function FjarrStudio({ initial }: { initial?: Studio }) {
  const [studio, setStudio] = useState<Studio | null>(initial ?? null);
  const [draft, setDraft] = useState<Fjarr | null>(initial?.settings ?? null);
  const [message, setMessage] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [except, setExcept] = useState("");

  useEffect(() => {
    if (initial) return;
    api
      .fjarr()
      .then((found) => {
        setStudio(found);
        setDraft(found.settings);
      })
      .catch((error: unknown) => setMessage(error instanceof Error ? error.message : "TKL svarar inte."));
  }, [initial]);

  if (!studio || !draft) return <p className="tom">{message || "Läser fjärrstyrningen …"}</p>;
  const candidates = studio.candidates ?? [];
  if (studio.level < 1) {
    return (
      <section className="ruta fjarr-studio">
        <h2>Fjärrstyrning</h2>
        <p>{studio.note}</p>
      </section>
    );
  }
  const chosen = new Set(draft.routes ?? []);
  const automats = draft.automats ?? [];
  const receivers = draft.receivers ?? [];
  const tracks = tracksOf(candidates);
  const changed = !studio.kept || JSON.stringify(draft) !== JSON.stringify(studio.settings);
  const setRoutes = (routes: string[]) => setDraft({ ...draft, routes });
  const toggle = (id: string) => setRoutes(chosen.has(id) ? [...chosen].filter((r) => r !== id) : [...(draft.routes ?? []), id]);
  const pick = (rule: Quick) => setRoutes(quick(candidates, rule));
  const setAutomat = (i: number, change: Partial<AutomatSpec>) => setDraft({ ...draft, automats: automats.map((a, j) => (j === i ? { ...a, ...change } : change.default ? { ...a, default: false } : a)) });
  const save = async () => {
    setBusy(true);
    setMessage("");
    setProblems([]);
    try {
      const kept = await api.saveFjarr(draft);
      setStudio(kept);
      setDraft(kept.settings);
      setMessage("Sparat. Fjärrkatalogen följer med nästa version av utsidan, i Studio › Utsidan.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte att spara.");
      setProblems(error instanceof Problem ? error.problems : []);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="fjarr-studio">
      <section className="ruta">
        <h2>Fjärrkatalogen</h2>
        <p className="liten">
          De tågvägar den som fjärrstyr stationen får begära. Stationens ställverk prövar varje begäran som om den lagts här. Växlingsvägar ingår aldrig (FR10); behöver någon växla ger den som fjärrstyr ett lokalt område.
        </p>
        <div className="knappar" role="group" aria-label="Snabbval">
          <button type="button" onClick={() => pick({ kind: "all" })}>
            Alla
          </button>
          <button type="button" onClick={() => pick({ kind: "none" })}>
            Inga
          </button>
          <label>
            Alla utom spår{" "}
            <select aria-label="Alla utom spår" value={except} onChange={(e) => setExcept(e.target.value)}>
              <option value="">–</option>
              {tracks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <button type="button" disabled={!except} onClick={() => pick({ kind: "except", track: except })}>
            Välj
          </button>
        </div>
        <p className="liten" aria-live="polite">
          {chosen.size} av {candidates.length} tågvägar i katalogen.
        </p>
        {studio.note ? <p className="liten">{studio.note}</p> : null}
        {grouped(candidates).map((group) => (
          <div key={group.exit} className="fjarr-utfart">
            <h3>{group.name}</h3>
            {(
              [
                ["Tågväg in", group.into],
                ["Tågväg ut", group.out],
              ] as const
            ).map(([title, list]) =>
              list.length ? (
                <fieldset key={title}>
                  <legend>{title}</legend>
                  {list.map((c) => (
                    <label key={c.id} className="fjarr-vag">
                      <input type="checkbox" checked={chosen.has(c.id)} onChange={() => toggle(c.id)} /> <span className="tm-mono">{c.start}</span> → <span className="tm-mono">{c.end}</span>
                      {c.via?.length ? <span className="liten"> genom {c.via.join(", ")}</span> : null} <span className="liten">· {c.track_label}</span>
                    </label>
                  ))}
                </fieldset>
              ) : null,
            )}
          </div>
        ))}
      </section>
      <section className="ruta">
        <h2>Stationsautomaterna</h2>
        <p className="liten">
          Automaterna sitter i stationens eget ställverk. A3 är automatdrift, A2 en enstaka förbigång och A1 ett enstaka möte; AN och AU automatdrift på ned- och uppspåret, för infartssignalen. Den förvalda kopplar stationen in själv efter 90 sekunder utan kontakt med den som fjärrstyr.
        </p>
        <table>
          <thead>
            <tr>
              <th>Kod</th>
              <th>Slag</th>
              <th>Infartssignal</th>
              <th>Förvald</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {automats.map((a, i) => (
              <tr key={`${a.code}-${i}`}>
                <td>
                  <input aria-label={`Automat ${i + 1}, kod`} className="tm-mono kort-falt" value={a.code} maxLength={12} onChange={(e) => setAutomat(i, { code: e.target.value.trim() })} />
                </td>
                <td>{KIND_NAMES[a.kind]}</td>
                <td>
                  {a.kind === "an" || a.kind === "au" ? (
                    <select aria-label={`Automat ${i + 1}, infartssignal`} value={a.signals?.[0] ?? ""} onChange={(e) => setAutomat(i, { signals: e.target.value ? [e.target.value] : [] })}>
                      <option value="">–</option>
                      {(studio.entry_signals ?? []).map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  ) : a.kind === "local_release" ? (
                    <span className="liten">{a.function}</span>
                  ) : (
                    <span className="liten">alla</span>
                  )}
                </td>
                <td>{a.kind === "local_release" ? null : <input type="radio" name="forvald" aria-label={`${a.code} förvald`} checked={a.default ?? false} onChange={() => setAutomat(i, { default: true })} />}</td>
                <td>
                  <button type="button" className="lank" onClick={() => setDraft({ ...draft, automats: automats.filter((_, j) => j !== i) })}>
                    Ta bort
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="knappar">
          {NEW_KINDS.map((kind) => (
            <button
              key={kind}
              type="button"
              disabled={kind === "a3" && automats.some((a) => a.kind === "a3")}
              onClick={() => {
                const signals = kind === "an" || kind === "au" ? (studio.entry_signals ?? []).slice(0, 1) : [];
                setDraft({ ...draft, automats: [...automats, { code: codeFor(kind, signals, automats), kind, signals, default: false }] });
              }}
            >
              + {kind.toUpperCase()}
            </button>
          ))}
          <button type="button" className="lank" onClick={() => setDraft({ ...draft, automats: studio.suggested ?? [] })}>
            Föreslå
          </button>
        </div>
      </section>
      <section className="ruta">
        <h2>Vem som får ta emot stationen</h2>
        {RECEIVERS.map(([kind, label]) => (
          <label key={kind} className="rad">
            <input
              type="checkbox"
              checked={!receivers.length || receivers.includes(kind)}
              onChange={(e) => {
                const all = receivers.length ? receivers : RECEIVERS.map(([k]) => k);
                const next = e.target.checked ? [...all, kind] : all.filter((k) => k !== kind);
                setDraft({ ...draft, receivers: next.length === RECEIVERS.length ? [] : [...new Set(next)] });
              }}
            />{" "}
            {label}
          </label>
        ))}
        <p className="liten">Vilka grannarna är avgörs på träffen, när utfarterna kopplas till sträckorna.</p>
      </section>
      {studio.outside?.overview ? (
        <p className="liten">
          Översikten för fjärrbilden: {studio.outside.overview.tracks?.length ?? 0} spårbitar, {studio.outside.overview.links?.length ?? 0} växlar som streck, {studio.outside.overview.signals?.length ?? 0} huvudsignaler.
        </p>
      ) : null}
      {problems.length || studio.problems?.length ? (
        <ul className="fel" role="alert">
          {(problems.length ? problems : (studio.problems ?? [])).map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      ) : null}
      {message ? <p role="status">{message}</p> : null}
      <div className="fot rad">
        <span className="liten">{studio.kept ? "Sparat med stationsmodellen." : "Inget sparat än: det här är förslaget, utan fjärrkatalog."}</span>
        <span className="tm-fyll" />
        <button type="button" className="primar" disabled={busy || !changed} onClick={() => void save()}>
          Spara
        </button>
      </div>
    </div>
  );
}

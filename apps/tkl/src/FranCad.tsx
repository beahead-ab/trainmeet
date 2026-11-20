// Studio › Rita › Från CAD (#89 del d2, STUDIO-01, STUDIO-03, CAD-15, CAD-20): the person's
// assemblies and approved modules in TrainMeet CAD, the one the station comes from, and Gör
// förslaget: Rita's draft from the track graph, everything new or moved yellow until the owner
// confirms it, with the difference against what the station had. CAD never makes a station; the
// owner confirms here, and TKL then tells CAD which station uses it. The modules' measuring
// images for Foto come with the proposal (#89 del d4); how many the station keeps is said here.
import { useCallback, useEffect, useState } from "react";
import { api, Problem, type CadDiff, type CadImport, type CadSource, type FromCad } from "./api";

const KIND: Record<string, string> = { assembly: "Anläggning", module: "Modul" };

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export type FromCadProps = {
  fromCad: FromCad | null;
  busy: boolean;
  message: string;
  problems: string[];
  onPropose: (source: CadSource) => void;
  onClose: () => void;
};

/** The panel as it looks: grey with the reason, or the list with the link and the button. */
export function FromCadView({ fromCad, busy, message, problems, onPropose, onClose }: FromCadProps) {
  const link = fromCad?.link ?? null;
  const pending = fromCad?.pending ?? null;
  return (
    <section className="ruta ladda-upp fran-cad" aria-label="Från CAD">
      <div className="rad">
        <h2>Från CAD</h2>
        <span className="tm-fyll" />
        <button type="button" className="lank" onClick={onClose}>
          Tillbaka till Rita
        </button>
      </div>
      <p className="liten">
        Välj en anläggning eller en godkänd modul ur TrainMeet CAD. Studio gör förslaget ur spårgrafen; signaler, spårledningar och vägar lägger du till här. Allt är gult tills du bekräftar det. CAD skapar aldrig en station.
      </p>
      {!fromCad ? <p className="liten">Hämtar dina anläggningar …</p> : null}
      {fromCad && !fromCad.available ? <p className="liten ladda-gra">{fromCad.reason}</p> : null}
      {link ? (
        <p className="fran-cad-lank">
          Stationen kommer från <strong>{link.name}</strong>, version {link.revision}. {link.registered ? "CAD visar stationen under Används i." : "CAD vet inte om det än; Studio säger till nästa gång CAD svarar."}
        </p>
      ) : null}
      {link && ((link.images ?? []).length || (link.missing ?? []).length) ? (
        <p className="liten" title={(link.missing ?? []).join("\n") || undefined}>
          Mätbilder för Foto: {(link.images ?? []).length} av {(link.images ?? []).length + (link.missing ?? []).length} moduler, kvar med stationen. Slå på Mätbilden under i Foto i Ställverket.
        </p>
      ) : null}
      {pending ? (
        <p className="fran-cad-lank gul-rad">
          Utkastet i Rita kommer från <strong>{pending.name}</strong>, version {pending.revision}. Bekräfta och använd ritningen för att koppla stationen.
        </p>
      ) : null}
      {message ? (
        <div className="fel" role="alert">
          <p>{message}</p>
          {problems.length ? (
            <ul>
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {fromCad?.available ? (
        fromCad.sources?.length ? (
          <ul className="fran-cad-lista">
            {(fromCad.sources ?? []).map((source) => {
              const linked = source.id === link?.id || source.id === pending?.id;
              return (
                <li key={`${source.kind}-${source.id}`} data-kalla={source.id} className={source.ready ? "" : "ej-klar"}>
                  <div>
                    <strong>{source.name}</strong>{" "}
                    <span className="liten">
                      {KIND[source.kind] ?? source.kind} · {source.scale} · version {source.revision} · {count((source.modules ?? []).length, "modul", "moduler")}
                      {source.owner ? ` · ${source.owner}` : ""}
                    </span>
                    {(source.stations ?? []).length ? <div className="liten">Används i: {(source.stations ?? []).map((s) => s.name).join(", ")}</div> : null}
                    {!source.ready ? (
                      <ul className="liten fran-cad-problem">
                        {(source.problems ?? []).map((p) => (
                          <li key={p}>{p}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                  <button type="button" className={linked ? "" : "primar"} disabled={busy || !source.ready} onClick={() => onPropose(source)}>
                    {linked ? "Läs in igen" : "Gör förslaget i Rita"}
                  </button>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="liten">Du har inga anläggningar eller godkända moduler i TrainMeet CAD än. Sätt ihop dem under Anläggningar i CAD.</p>
        )
      ) : null}
    </section>
  );
}

/** Skillnaden: what an import from CAD changed, by CAD's ids, and what of the owner's stayed. */
export function DiffView({ diff, onClose }: { diff: CadDiff; onClose?: () => void }) {
  const added = diff.added ?? [];
  const removed = diff.removed ?? [];
  const moved = diff.moved ?? [];
  const kept = diff.kept ?? [];
  const lost = diff.lost ?? [];
  return (
    <section className="ruta fran-cad-skillnad" aria-label="Skillnaden mot CAD">
      <div className="rad">
        <h2>{diff.first ? "Förslaget ur TrainMeet CAD" : "Skillnaden mot förra gången"}</h2>
        <span className="tm-fyll" />
        {onClose ? (
          <button type="button" className="lank" onClick={onClose}>
            Stäng
          </button>
        ) : null}
      </div>
      {diff.first ? (
        <p className="liten">
          {count(added.length, "spårbit", "spårbitar")} ur CAD{diff.replaced ? ", i stället för stationens egen ritning när du använder den" : ""}.
        </p>
      ) : (
        <p>
          <span className="chip" data-skillnad="nytt">
            Nytt {added.length}
          </span>{" "}
          <span className="chip" data-skillnad="borta">
            Borta {removed.length}
          </span>{" "}
          <span className="chip" data-skillnad="flyttat">
            Flyttat {moved.length}
          </span>
        </p>
      )}
      {!diff.first ? (
        <>
          {[
            ["Nytt, gult", added],
            ["Borta", removed],
            ["Flyttat, gult igen", moved],
          ].map(([title, list]) =>
            (list as typeof added).length ? (
              <div key={title as string}>
                <h3>{title as string}</h3>
                <ul className="liten">
                  {(list as typeof added).map((p) => (
                    <li key={p.id}>{p.text}</li>
                  ))}
                </ul>
              </div>
            ) : null,
          )}
          {kept.length ? <p className="ok">Kvar av det du har lagt till: {kept.join(", ")}.</p> : null}
          {lost.length ? (
            <div className="fel">
              <p>Det här hängde på spår som är borta och följer inte med:</p>
              <ul>
                {lost.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {!diff.panel ? <p className="liten">Motorn lägger ut panelen på nytt; rita om den om du vill.</p> : null}
        </>
      ) : null}
    </section>
  );
}

/** The panel with TKL behind it: the list from CAD, and the proposal handed to Rita. */
export function FranCad({ onProposal, onClose }: { onProposal: (made: CadImport) => void; onClose: () => void }) {
  const [fromCad, setFromCad] = useState<FromCad | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [problems, setProblems] = useState<string[]>([]);

  const act = useCallback(async (work: () => Promise<void>) => {
    setBusy(true);
    setMessage("");
    setProblems([]);
    try {
      await work();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Det gick inte.");
      setProblems(error instanceof Problem ? error.problems : []);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void act(async () => setFromCad(await api.fromCad()));
  }, [act]);

  return (
    <FromCadView
      fromCad={fromCad}
      busy={busy}
      message={message}
      problems={problems}
      onPropose={(source) => void act(async () => onProposal(await api.fromCadProposal(source.kind, source.id)))}
      onClose={onClose}
    />
  );
}

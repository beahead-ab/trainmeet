import { useState } from "react";
import type { Now, PlanVersion, SwitchPreview, SwitchVersion } from "./api";
import { changeText, type ChangeNow, type Package } from "./changes";
import { Chip, Chips } from "./ui";

// Versionsbyte under träffen (TRAFIK-03, DRIFT-29, H4, H38, H66): Trafikledningen chooses when
// Drift goes over to a new version. The clock, where the trains stand and the open clearances
// go with it; each driftändring is kept unless let go, and one the planner took into the new
// version falls away. A train the version changes that is out makes the switch wait, unless
// it is forced through. And the lock (DRIFT-47): what was begun and never done.

const LOCKED: Record<string, string> = { version: "ett versionsbyte", jump: "ett tidshopp", undo: "Ångra", day: "ett dygnsskifte" };

/** Drift started locked: said, with Lås upp. */
export function Spärrad({ now, onUnlock }: { now: Now; onUnlock?: () => void }) {
  if (!now.locked) return null;
  return (
    <section id="locked" className="kort varning" role="alert" aria-labelledby="locked-title">
      <h2 id="locked-title">Drift är spärrad</h2>
      <p>{`${LOCKED[now.locked] ?? now.locked} påbörjades och blev aldrig klart. Läget är som det sparades; inget kan ändras förrän du låst upp.`.replace(/^./, (c) => c.toUpperCase())}</p>
      <p className="liten">Titta på tågen och klareringarna nedan. Stämmer läget, lås upp. Annars gör ett tidshopp efteråt.</p>
      <button id="unlock" type="button" className="primar" onClick={onUnlock}>
        Lås upp
      </button>
    </section>
  );
}

export type SwitchProps = {
  now: Now;
  pkg: Package | null;
  versions: PlanVersion[] | null;
  preview: SwitchPreview | null;
  onPreview?: (version: number | null) => void;
  onSwitch?: (request: SwitchVersion) => void;
  onForce?: () => void;
  onCallOff?: () => void;
};

/** The versions after the one that runs, newest last. */
export const newer = (versions: PlanVersion[] | null, running: number) => (versions ?? []).filter((v) => v.number > running);

export function Versionsbyte({ now, pkg, versions, preview, onPreview, onSwitch, onForce, onCallOff }: SwitchProps) {
  const [drop, setDrop] = useState<string[]>([]);
  const waiting = now.switch;
  const next = newer(versions, now.version ?? 1).at(-1);
  if (now.meet_id === "provbanan" && !waiting) return null;
  if (waiting) {
    return (
      <section id="switch" className="kort" aria-labelledby="switch-title">
        <h2 id="switch-title">{`Byte till version ${waiting.version} väntar`}</h2>
        <p className="pamin">{`Tåg ${(waiting.waits_for ?? []).join(", ")} är ute och får ändringar i version ${waiting.version}. Bytet görs när de är framme.`}</p>
        <div className="rad">
          <button id="switch-force" type="button" className="fara" onClick={onForce}>
            Tvinga igenom
          </button>
          <button id="switch-call-off" type="button" onClick={onCallOff}>
            Avbryt bytet
          </button>
        </div>
        <p className="liten">Tvingar du igenom ställs tågen enligt den nya versionen direkt, fast de är ute.</p>
      </section>
    );
  }
  if (!next) return null;
  const open = preview?.version === next.number;
  const changes = ((now.changes ?? []) as ChangeNow[]).filter((change) => change.status !== "dropped");
  const included = new Set((preview?.changes ?? []).filter((c) => c.included).map((c) => c.change_id));
  const waits = preview?.waits_for ?? [];
  const send = (force: boolean) => onSwitch?.({ version: next.number, drop, force });
  return (
    <section id="switch" className="kort" aria-labelledby="switch-title">
      <div className="rad mellan">
        <h2 id="switch-title">{`Version ${next.number} finns`}</h2>
        {!open && (
          <button id="switch-open" type="button" className="primar" onClick={() => (setDrop([]), onPreview?.(next.number))}>
            {`Byt till version ${next.number}`}
          </button>
        )}
      </div>
      <p className="liten">{`Träffen kör version ${now.version}. Klockan, tågens lägen och de öppna klareringarna följer med vid bytet.`}</p>
      {open && (
        <>
          <h3>Driftändringarna vid bytet</h3>
          <ul id="switch-changes" className="lista">
            {changes.length ? (
              changes.map((change) => (
                <li key={change.change_id}>
                  <div className="vem">
                    <b>{changeText(change.change, pkg, change.train_number)}</b>
                    <span className="liten">{included.has(change.change_id) ? `Med i version ${next.number} · faller bort` : drop.includes(change.change_id) ? "Släpps vid bytet" : "Ligger kvar ovanpå den nya versionen"}</span>
                  </div>
                  {!included.has(change.change_id) && (
                    <Chips label="Vid bytet">
                      <Chip label="Behåll" pressed={!drop.includes(change.change_id)} onClick={() => setDrop(drop.filter((id) => id !== change.change_id))} />
                      <Chip label="Släpp" pressed={drop.includes(change.change_id)} onClick={() => setDrop([...drop.filter((id) => id !== change.change_id), change.change_id])} />
                    </Chips>
                  )}
                </li>
              ))
            ) : (
              <li className="tom">Inga driftändringar.</li>
            )}
          </ul>
          {waits.length > 0 && <p id="switch-waits" className="pamin">{`Tåg ${waits.join(", ")} är ute och får ändringar i version ${next.number}. Bytet väntar tills de är framme, om du inte tvingar igenom det.`}</p>}
          <div className="rad">
            {waits.length ? (
              <>
                <button id="switch-go" type="button" className="primar" onClick={() => send(false)}>
                  {`Byt när tåg ${waits.join(", ")} är framme`}
                </button>
                <button id="switch-force-now" type="button" className="fara" onClick={() => send(true)}>
                  Tvinga igenom
                </button>
              </>
            ) : (
              <button id="switch-go" type="button" className="primar" onClick={() => send(false)}>
                {`Byt till version ${next.number}`}
              </button>
            )}
            <button type="button" onClick={() => onPreview?.(null)}>
              Inte nu
            </button>
          </div>
        </>
      )}
    </section>
  );
}

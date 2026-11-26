import { useEffect, useState } from "react";
import { planning, type ClockCheck, type ClockPackSeen, type ClockStamp, type Draft } from "./api";

// Egna urtavlor (F13, H75, SKARM-05): the organiser uploads a clock pack, confirms the right
// to use each face, and chooses it as the analog clock's style. The pack goes with the next
// version to the Pi, and the clock screen draws custom:<id> in light and in dark.

export type Language = "sv" | "en";

const TEXT = {
  sv: {
    title: "Klockan",
    under: "träffens egna urtavlor",
    empty: "Lägg till underlag i Data först.",
    note: "Ett klockpaket är bilder och en inställningsfil, ingen kod. Det följer med nästa version till Pi:n, och klockskärmen visar det utan internet.",
    readOnly: "Bara arrangören lägger in urtavlor.",
    style: "Klockskärmen visar",
    analog: "Analog, inbyggd",
    own: "egen urtavla",
    digital: "Digital väljs för en skärm i Klienter.",
    use: "Använd som klockans stil",
    using: "Visas på klockskärmen",
    back: "Tillbaka till analog",
    upload: "Lägg in klockpaket",
    none: "Inga egna urtavlor. Den analoga klockan är inbyggd.",
    remove: "Ta bort",
    approve: "Godkänn urtavlorna",
    rights: "Jag intygar att jag har rätt att använda tavlan.",
    rightsNote: "Varje klocka godkänns för sig. Intyget loggas med vem och när.",
    save: "Lägg in de godkända",
    cancel: "Avbryt",
    warnings: "Varningar",
    noWarnings: "Inga varningar.",
    replaces: "Ersätter den som redan finns.",
    stamp: "Godkänd att visas",
    byPin: "av den som har PIN",
    byId: "av en inloggad i TrainMeet ID",
    saved: "Urtavlan är inlagd i utkastet.",
    removed: "Urtavlan är borttagen.",
    chosen: "Klockskärmen visar den valda stilen.",
  },
  en: {
    title: "Clock",
    under: "the meet's own clock faces",
    empty: "Add a source in Data first.",
    note: "A clock pack is pictures and a settings file, no code. It goes with the next version to the Pi, and the clock screen shows it without internet.",
    readOnly: "Only the organiser adds clock faces.",
    style: "The clock screen shows",
    analog: "Analog, built in",
    own: "own clock face",
    digital: "Digital is chosen for a screen in Klienter.",
    use: "Use as the clock's style",
    using: "Shown on the clock screen",
    back: "Back to analog",
    upload: "Add a clock pack",
    none: "No own clock faces. The analog clock is built in.",
    remove: "Remove",
    approve: "Approve the faces",
    rights: "I confirm that I have the right to use the face.",
    rightsNote: "Each clock is approved on its own. The confirmation is logged, with who and when.",
    save: "Add the approved ones",
    cancel: "Cancel",
    warnings: "Warnings",
    noWarnings: "No warnings.",
    replaces: "Replaces the one already there.",
    stamp: "Approved to be shown",
    byPin: "by the PIN holder",
    byId: "by someone logged in with TrainMeet ID",
    saved: "The face is in the draft.",
    removed: "The face is removed.",
    chosen: "The clock screen shows the chosen style.",
  },
};

type Text = (typeof TEXT)["sv"];

export function chosenStyle(styles: string[] | undefined): string {
  return styles?.find((style) => style === "analog" || style.startsWith("custom:")) ?? "analog";
}

function when(stamp: ClockStamp): string {
  const at = stamp.at ? new Date(stamp.at) : null;
  if (!at || Number.isNaN(at.getTime())) return "";
  return at.toLocaleString("sv-SE", { dateStyle: "medium", timeStyle: "short" });
}

/** The approval, one clock at a time, before anything is saved. */
export function Godkann({
  preview,
  text,
  onSave,
  onCancel,
}: {
  preview: ClockCheck;
  text: Text;
  onSave: (approved: string[]) => void;
  onCancel: () => void;
}) {
  const packs = preview.packs ?? [];
  const [picked, setPicked] = useState<string[]>(packs.map((pack) => pack.id));
  const [rights, setRights] = useState(false);
  const toggle = (id: string) => setPicked((now) => (now.includes(id) ? now.filter((item) => item !== id) : [...now, id]));
  return (
    <section id="godkann-klocka" className="kort" aria-labelledby="godkann-rubrik">
      <h2 id="godkann-rubrik">{text.approve}</h2>
      <p className="liten">{text.rightsNote}</p>
      <ul className="klockor">
        {packs.map((pack) => (
          <FaceRow key={pack.id} pack={pack} text={text} picked={picked.includes(pack.id)} onToggle={() => toggle(pack.id)} />
        ))}
      </ul>
      <label className="valj intyg">
        <input id="ratt" type="checkbox" checked={rights} onChange={(event) => setRights(event.target.checked)} /> {text.rights}
      </label>
      <div className="rad">
        <button type="button" className="tm-knapp primar" disabled={!rights || picked.length === 0} onClick={() => onSave(picked)}>
          {text.save}
        </button>
        <button type="button" onClick={onCancel}>
          {text.cancel}
        </button>
      </div>
    </section>
  );
}

function FaceRow({ pack, text, picked, onToggle }: { pack: ClockPackSeen; text: Text; picked: boolean; onToggle: () => void }) {
  const warnings = pack.warnings ?? [];
  return (
    <li>
      <label className="valj">
        <input type="checkbox" checked={picked} onChange={onToggle} /> <b>{pack.name}</b> <span className="liten">{pack.id}</span>
      </label>
      {pack.layers?.dial && <img className="forhands" src={pack.layers.dial} alt="" />}
      {pack.replaces && <p className="liten">{text.replaces}</p>}
      {warnings.length > 0 ? (
        <ul className="punkter">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : (
        <p className="liten">{text.noWarnings}</p>
      )}
    </li>
  );
}

export function KlockanPage({
  admin,
  meet,
  draft,
  stamps = [],
  preview = null,
  language = "sv",
  onDraft,
  onTell,
  onFail,
}: {
  admin: boolean;
  meet: string;
  draft: Draft | null;
  stamps?: ClockStamp[];
  preview?: ClockCheck | null;
  language?: Language;
  onDraft: (draft: Draft) => void;
  onTell: (text: string, good?: boolean) => void;
  onFail: (error: unknown) => void;
}) {
  const text = TEXT[language];
  const [pending, setPending] = useState<ClockCheck | null>(preview);
  const [file, setFile] = useState<File | null>(null);
  const [known, setKnown] = useState(stamps);
  useEffect(() => {
    let live = true;
    void planning.clockFaces(meet).then(
      (found) => {
        if (live) setKnown(found.faces ?? []);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [meet, draft?.revision]);
  const pkg = draft?.package;
  const faces = (pkg?.attachments ?? []).filter((item) => item.kind === "clock_face");
  const style = chosenStyle(pkg?.clock?.styles);
  const stampOf = (id: string) => known.find((stamp) => stamp.id === id);
  /** The chosen face by its name, as the list below calls it. */
  const ownName = (chosen: string) => {
    const id = chosen.startsWith("custom:") ? chosen.slice("custom:".length) : null;
    const face = faces.find((item) => item.id === id);
    return id === null ? null : (stampOf(id)?.name ?? face?.filename ?? null);
  };

  const read = async (chosen: File | undefined) => {
    if (!chosen) return;
    try {
      setFile(chosen);
      setPending(await planning.checkClock(meet, chosen));
    } catch (error) {
      onFail(error);
    }
  };
  const save = async (approved: string[]) => {
    if (!file) return;
    try {
      onDraft(await planning.uploadClock(meet, file, approved));
      setPending(null);
      setFile(null);
      onTell(text.saved, true);
    } catch (error) {
      onFail(error);
    }
  };
  const remove = async (id: string) => {
    try {
      onDraft(await planning.removeClock(meet, id));
      onTell(text.removed, true);
    } catch (error) {
      onFail(error);
    }
  };
  const choose = async (next: string) => {
    try {
      onDraft(await planning.clockStyle(meet, next));
      onTell(text.chosen, true);
    } catch (error) {
      onFail(error);
    }
  };

  return (
    <>
      <header className="sidrubrik">
        <h1>{text.title}</h1>
        <p className="under">{text.under}</p>
      </header>
      {!pkg ? (
        <p className="tom">{text.empty}</p>
      ) : (
        <>
          <section id="klockans-stil" className="kort">
            <h2>{text.style}</h2>
            <p id="vald-stil">{style === "analog" ? text.analog : `${ownName(style) ?? style}, ${text.own}`}</p>
            <p className="liten">{text.digital}</p>
            {admin && style !== "analog" && (
              <button type="button" onClick={() => void choose("analog")}>
                {text.back}
              </button>
            )}
          </section>
          <section id="egna-klockor" className="kort">
            <h2>{text.title}</h2>
            <p className="liten">{admin ? text.note : text.readOnly}</p>
            {faces.length === 0 ? (
              <p className="tom">{text.none}</p>
            ) : (
              <ul className="klockor">
                {faces.map((face) => {
                  const stamp = stampOf(face.id);
                  const shown = style === `custom:${face.id}`;
                  return (
                    <li key={face.id} id={`klocka-${face.id}`}>
                      <b>{stamp?.name ?? face.filename}</b> <span className="liten">{`custom:${face.id}`}</span>
                      {shown && <p className="liten">{text.using}</p>}
                      {stamp && (
                        <p className="stampel">
                          {text.stamp} {stamp.by === "pin" ? text.byPin : text.byId} · {when(stamp)}
                        </p>
                      )}
                      {admin && (
                        <div className="rad">
                          {!shown && (
                            <button type="button" onClick={() => void choose(`custom:${face.id}`)}>
                              {text.use}
                            </button>
                          )}
                          <button type="button" className="fara" onClick={() => void remove(face.id)}>
                            {text.remove}
                          </button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
            {admin && (
              <label className="tm-knapp">
                {text.upload}
                <input id="klockfil" type="file" accept=".tmclock,.zip,application/zip" className="osynlig" onChange={(event) => void read(event.target.files?.[0])} />
              </label>
            )}
          </section>
          {pending && <Godkann preview={pending} text={text} onSave={(approved) => void save(approved)} onCancel={() => setPending(null)} />}
        </>
      )}
    </>
  );
}

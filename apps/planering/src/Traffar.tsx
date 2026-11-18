import { useState, type FormEvent } from "react";
import type { IdMeetChoice, MeetSummary, NewMeet } from "./api";
import { COUNTRIES, dates, levelText, number, when } from "./text";

// Träffar (S6): the meets planned here and run in Drift, Provbanan last; and Ny träff for the
// administrator. Everyone sees the list (S1).

export type TraffarProps = {
  /** The one with the hub's PIN: Ny träff with a name and dates. */
  admin: boolean;
  /** Logged in with TrainMeet ID: Ny träff from a meet in ID (ID10, #78). */
  person?: boolean;
  idMeets?: IdMeetChoice[] | null;
  meets: MeetSummary[] | null;
  navigate: (href: string) => void;
  onCreate?: (fresh: NewMeet) => void;
};

export function TraffarPage({ admin, person = false, idMeets = null, meets, onCreate }: TraffarProps) {
  return (
    <>
      <div className="sidrubrik">
        <h1>
          Träffar{" "}
          <span id="meet-count" className="antal">
            {meets ? meets.length + 1 : ""}
          </span>
        </h1>
        <span className="under">planeras här och körs i Drift</span>
      </div>
      <section className="kort lista-kort">
        <table className="tabell">
          <thead>
            <tr>
              <th>Träff</th>
              <th>Datum</th>
              <th>Nivå</th>
              <th className="tal">Tåg</th>
              <th>Senaste version</th>
              <th className="tal">Frågor</th>
            </tr>
          </thead>
          <tbody id="meets">
            {meets === null ? (
              <tr>
                <td colSpan={6} className="tom">
                  Hämtar träffarna …
                </td>
              </tr>
            ) : (
              <>
                {meets.map((summary) => {
                  const latest = summary.versions?.at(-1);
                  return (
                    <tr key={summary.meet.id}>
                      <td>
                        {summary.home ? <b>{summary.meet.name}</b> : <a href={`/planering/${encodeURIComponent(summary.meet.id)}`}>{summary.meet.name}</a>}
                        <div className="liten">{summary.home ? `Planeras i ${summary.home} · körs här med Byt träff` : (COUNTRIES[summary.meet.country] ?? summary.meet.country)}</div>
                      </td>
                      <td>{dates(summary.meet)}</td>
                      <td>
                        <span className={"niva" + (summary.level ? "" : " ingen")}>{levelText(summary.level)}</span>
                      </td>
                      <td className="tal">{summary.trains ? number(summary.trains) : "–"}</td>
                      <td>
                        {latest ? (
                          <span>
                            {`Version ${latest.number}`}
                            <span className="liten">{` · ${when(latest.published)}`}</span>
                          </span>
                        ) : (
                          <span className="svag">Ingen än</span>
                        )}
                      </td>
                      <td className="tal">{summary.questions ? String(summary.questions) : "–"}</td>
                    </tr>
                  );
                })}
                <tr>
                  <td>
                    <a href="/provbanan">Provbanan</a>
                    <div className="liten">Inbyggd provbana</div>
                  </td>
                  <td className="svag">Alltid</td>
                  <td className="svag">–</td>
                  <td className="tal">10</td>
                  <td>Version 1</td>
                  <td className="tal">–</td>
                </tr>
              </>
            )}
          </tbody>
        </table>
      </section>
      {admin ? <NewMeetCard onCreate={onCreate} /> : person ? <FromIdCard choices={idMeets} onCreate={onCreate} /> : <p className="liten">Logga in för att skapa en träff.</p>}
    </>
  );
}

/** Ny träff for someone logged in with TrainMeet ID (ID10, PLAN-19): the hub's meet is made
 * from a meet in ID where they are the club's admin or the organizer, and linked to it. The roles
 * there decide who plans it and who runs it. */
export function FromIdCard({ choices, onCreate }: { choices: IdMeetChoice[] | null; onCreate?: (fresh: NewMeet) => void }) {
  return (
    <section className="kort" id="ny" aria-labelledby="ny-rubrik">
      <h2 id="ny-rubrik">Ny träff ur TrainMeet ID</h2>
      <p className="liten">Träffarna i TrainMeet ID där du är arrangör eller klubbens administratör. Rollerna där bestämmer vem som planerar träffen och vem som kör den.</p>
      <ul id="id-meets" className="lista">
        {choices === null ? (
          <li className="tom">Hämtar träffarna i ID …</li>
        ) : choices.length === 0 ? (
          <li className="tom">Du är inte arrangör för någon träff i TrainMeet ID. Arrangören eller klubbens administratör delar ut rollen där.</li>
        ) : (
          choices.map((choice) => (
            <li key={choice.id}>
              <div className="vem">
                <b>{choice.name}</b>
                <span className="liten">{`${choice.club_name} · ${choice.starts_on} – ${choice.ends_on}`}</span>
              </div>
              <div className="kontroller">
                {choice.hub_meet ? (
                  <a href={`/planering/${encodeURIComponent(choice.hub_meet)}`}>Öppna</a>
                ) : (
                  <button type="button" className="primar" onClick={() => onCreate?.({ name: choice.name, country: "se", first_date: choice.starts_on, last_date: choice.ends_on, id_meet: choice.id })}>
                    Skapa träffen i hubben
                  </button>
                )}
              </div>
            </li>
          ))
        )}
      </ul>
    </section>
  );
}

function NewMeetCard({ onCreate }: { onCreate?: (fresh: NewMeet) => void }) {
  const [name, setName] = useState("");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [country, setCountry] = useState<NewMeet["country"]>("se");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onCreate?.({ name, country, first_date: first || null, last_date: last || null, id_meet: null });
  };
  return (
    <section className="kort" id="ny" aria-labelledby="ny-rubrik">
      <h2 id="ny-rubrik">Ny träff</h2>
      <form id="new-meet" className="formular" onSubmit={submit}>
        <label>
          Namn <input id="new-name" maxLength={120} required autoComplete="off" placeholder="Värnamo Moduldagar" value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <div className="rad">
          <label>
            Första dagen <input id="new-first" type="date" value={first} onChange={(event) => setFirst(event.target.value)} />
          </label>
          <label>
            Sista dagen <input id="new-last" type="date" value={last} onChange={(event) => setLast(event.target.value)} />
          </label>
          <label>
            Land{" "}
            <select id="new-country" value={country} onChange={(event) => setCountry(event.target.value as NewMeet["country"])}>
              {Object.entries(COUNTRIES).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button type="submit" className="primar">
          Skapa träffen
        </button>
      </form>
    </section>
  );
}

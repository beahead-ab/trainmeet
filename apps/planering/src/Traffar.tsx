import { useState, type FormEvent } from "react";
import type { MeetSummary, NewMeet } from "./api";
import { COUNTRIES, dates, levelText, number, when } from "./text";

// Träffar (S6): the meets planned here and run in Drift, Provbanan last; and Ny träff for the
// administrator. Everyone sees the list (S1).

export type TraffarProps = {
  admin: boolean;
  meets: MeetSummary[] | null;
  navigate: (href: string) => void;
  onCreate?: (fresh: NewMeet) => void;
};

export function TraffarPage({ admin, meets, onCreate }: TraffarProps) {
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
                        <a href={`/planering/${encodeURIComponent(summary.meet.id)}`}>{summary.meet.name}</a>
                        <div className="liten">{COUNTRIES[summary.meet.country] ?? summary.meet.country}</div>
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
      {admin ? <NewMeetCard onCreate={onCreate} /> : <p className="liten">Logga in för att skapa en träff.</p>}
    </>
  );
}

function NewMeetCard({ onCreate }: { onCreate?: (fresh: NewMeet) => void }) {
  const [name, setName] = useState("");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [country, setCountry] = useState<NewMeet["country"]>("se");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onCreate?.({ name, country, first_date: first || null, last_date: last || null });
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

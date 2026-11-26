import { idLoginAddress, Problem } from "@trainmeet/hubben";
import { useEffect, useState } from "react";
import { planning, type LinkAttempt } from "./api";

const day = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString("sv-SE", { day: "numeric", month: "short", year: "numeric" });

/** Where the person comes back to after logging in, with the Pi's attempt in a cookie. */
export const CHOOSE_PAGE = "/planering?koppla=pi";

type Seen = { attempt: LinkAttempt } | { login: true } | { gone: string } | null;

/** Välj träff åt Pi:n (F16, SYNK-02, KONTO-22): a Pi under Den här hubben → Molnet sent the
 * browser here. The person logged in chooses among the meets planned here that they may plan,
 * and the browser goes back to the Pi, which then fetches its key. The Pi's name and address
 * are shown, so that nobody chooses for a Pi they did not start themselves. */
export function ValjTraff({ withId = true, initial = null }: { withId?: boolean; initial?: Seen }) {
  const [seen, setSeen] = useState<Seen>(initial);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  useEffect(() => {
    if (initial) return;
    planning.linkAttempt().then(
      (attempt) => setSeen({ attempt }),
      (error: unknown) => {
        if (error instanceof Problem && error.status === 401) setSeen({ login: true });
        else setSeen({ gone: error instanceof Error ? error.message : "Det gick inte." });
      },
    );
  }, [initial]);
  const choose = async (meet: string) => {
    setBusy(true);
    setSaid("");
    try {
      const chosen = await planning.chooseForPi(meet);
      setSaid("Pi:n hämtar sin nyckel …");
      window.location.assign(chosen.back);
    } catch (error) {
      setSaid(error instanceof Error ? error.message : "Det gick inte.");
      setBusy(false);
    }
  };
  return (
    <section id="valj-traff" className="kort" aria-labelledby="valj-traff-rubrik">
      <h2 id="valj-traff-rubrik">Koppla Pi:n till en träff</h2>
      {seen === null && <p className="liten">Hämtar …</p>}
      {seen && "login" in seen && (
        <>
          <p className="liten">Logga in för att välja vilken träff Pi:n ska följa. Du väljer bland träffarna du får planera.</p>
          {withId ? (
            <a className="tm-knapp primar" id="valj-traff-logga-in" href={idLoginAddress(CHOOSE_PAGE)}>
              Logga in med TrainMeet ID
            </a>
          ) : (
            <p className="liten">Logga in med hubbens PIN-kod uppe till höger, och ladda om sidan.</p>
          )}
        </>
      )}
      {seen && "gone" in seen && (
        <p className="liten varning" id="valj-traff-borta">
          {seen.gone}
        </p>
      )}
      {seen && "attempt" in seen && (
        <>
          <p>
            <b>{seen.attempt.hub_name}</b>
            <span className="liten">{` · Hubben ${seen.attempt.software} · ${seen.attempt.address}`}</span>
          </p>
          <p className="liten">Pi:n vill följa en träff härifrån och hämta varje version när den publiceras. Välj bara om du själv har börjat på just den Pi:n nyss.</p>
          {seen.attempt.meets.length > 0 ? (
            <ul className="fynd" id="valj-traff-lista">
              {seen.attempt.meets.map((meet) => (
                <li key={meet.meet}>
                  <span>
                    <b>{meet.name}</b>
                    {meet.first_date && <span className="liten">{` · ${day(meet.first_date)}`}</span>}
                  </span>
                  <button type="button" className="primar" disabled={busy} onClick={() => void choose(meet.meet)}>
                    Koppla hit
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="liten" id="valj-traff-lista">
              Du planerar ingen träff här. Klubbens administratör ger rollen Arrangör i TrainMeet ID.
            </p>
          )}
          <span className="liten" role="status" id="valj-traff-sagt">
            {said}
          </span>
        </>
      )}
    </section>
  );
}

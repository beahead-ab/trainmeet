import { useEffect, useState, type FormEvent } from "react";
import { hub, type Client, type LetIn, type Now, type OneTimeCode } from "./api";
import { CLIENT_GROUPS, LANGUAGES, SIDES, VIEWS, clientDetails, type ClientGroup } from "./drift";
import { Chip, Chips, LoginFirst, Select } from "./ui";

// Klienter (S3, TRAFIK-04): boxes, TKL and screens, with the new ones under Väntar. Godkänn a
// TKL for a place, give a box its place, side and language, give a screen its view, and take
// a key back (H31). Only for the administrator.

export type ClientAction =
  | { action: "assign"; client_id: string; places: string[]; side: Client["side"]; language: string }
  | { action: "approve"; client_id: string; places: string[] }
  | { action: "revoke"; client_id: string }
  | { action: "view"; client_id: string; view: string }
  | { action: "exit"; client_id: string; section: string; exit: string };

type Question = NonNullable<Client["questions"]>[number];

const SIDE_WORD: Record<string, string> = { left: "vänster", right: "höger" };

/** Hubben frågar om en utfart (H26, TRAFIK-05): stationen i TKL eller trafikledningen här
 * svarar, och det första svaret gäller. */
export function ExitQuestions({ client, onAnswer }: { client: Client; onAnswer: (section: string, exit: string) => void }) {
  const questions = client.questions ?? [];
  if (!questions.length) return null;
  return (
    <div className="utfartsfragor">
      {questions.map((question: Question) => (
        <div key={question.section} className="utfartsfraga">
          <p>
            <b>Hubben frågar:</b> {`Vilken utfart går mot ${question.other_name}?`}
            {question.side ? <span className="liten">{` Sträckan ligger åt ${SIDE_WORD[question.side] ?? question.side}.`}</span> : null}
          </p>
          <div className="kontroller">
            {question.alternatives.map((choice) => (
              <button key={choice.exit} type="button" onClick={() => onAnswer(question.section, choice.exit)}>
                {choice.name ? `${choice.exit} · ${choice.name}` : choice.exit}
              </button>
            ))}
          </div>
        </div>
      ))}
      <p className="liten">Stationen kan också svara i TKL. Det första svaret gäller hela träffen.</p>
    </div>
  );
}

export type KlienterProps = {
  admin: boolean;
  now: Now | null;
  clients: Client[];
  group?: ClientGroup;
  navigate: (href: string) => void;
  onChange?: (change: ClientAction) => void;
  /** What the hub said no to, said on the page. */
  onMessage?: (text: string) => void;
  /** Given in tests; the page reads it from the hub itself. */
  letIn?: LetIn[];
};

export function KlienterPage({ admin, now, clients, group: initial = "all", navigate, onChange, onMessage, letIn }: KlienterProps) {
  const [group, setGroup] = useState<ClientGroup>(initial);
  if (!admin) {
    return (
      <>
        <LoginFirst navigate={navigate} />
      </>
    );
  }
  const test = CLIENT_GROUPS.find(([key]) => key === group)?.[2] ?? (() => true);
  const shown = clients.filter(test);
  return (
    <>
      <div className="sidrubrik">
        <h1>Klienter</h1>
        <p className="liten">Boxar, TKL och skärmar. Nya hamnar överst under Väntar. Anslut finns i sidhuvudet.</p>
      </div>
      <Chips label="Visa">
        {CLIENT_GROUPS.map(([key, label, test]) => (
          <Chip key={key} label={label} pressed={group === key} onClick={() => setGroup(key)} count={clients.filter(test).length} />
        ))}
      </Chips>
      <ul id="clients" className="lista">
        {shown.length ? (
          // A row keeps what was chosen in it while the list is read again: keyed by the client.
          shown.map((client) => <ClientRow key={client.client_id} client={client} now={now} onChange={onChange} />)
        ) : (
          <li className="tom">Inga klienter här. Anslut finns i sidhuvudet.</li>
        )}
      </ul>
      {now && <SlappIn initial={letIn} onMessage={onMessage} />}
    </>
  );
}

const ROLE_WORD: Record<string, string> = {
  dispatcher: "Trafikledare",
  organizer: "Arrangör",
  loco_lead: "Lokledare",
  remote_clearer: "Fjärrtågklarerare",
};

const clock = (iso: string) => new Date(iso).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" });

/** Kvar av koden: minutes and seconds, as 14:59. */
export function remaining(expires: string, at: number): string {
  const left = Math.max(0, Math.round((new Date(expires).getTime() - at) / 1000));
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
}

/** Släpp in en person (H56, KONTO-19, F18): a six-digit code for someone who has not logged in
 * on the Pi before. It works once, for 15 minutes, and gives Trafikledare in this meet: at most
 * one's own role. The list shows who is in and how, and Ta bort ends a role at once. The code is
 * shown here once and never again; the hub keeps only a hash. */
export function SlappIn({ initial, onMessage }: { initial?: LetIn[]; onMessage?: (text: string) => void }) {
  const [people, setPeople] = useState<LetIn[]>(initial ?? []);
  const [name, setName] = useState("");
  const [given, setGiven] = useState<OneTimeCode | null>(null);
  const [at, setAt] = useState(() => Date.now());
  const say = (error: unknown) => onMessage?.(error instanceof Error ? error.message : "Det gick inte.");

  useEffect(() => {
    if (initial) return;
    const read = () => void hub.letIn().then(setPeople, () => undefined);
    read();
    const timer = window.setInterval(read, 10000);
    return () => window.clearInterval(timer);
  }, [initial]);

  useEffect(() => {
    if (!given) return;
    const timer = window.setInterval(() => {
      setAt(Date.now());
      if (new Date(given.expires).getTime() <= Date.now()) setGiven(null);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [given]);

  const give = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setGiven(await hub.giveCode(name));
      setAt(Date.now());
      setName("");
    } catch (error) {
      say(error);
    }
  };

  const takeAway = async (person: string) => {
    try {
      await hub.takeAway(person);
      setPeople(await hub.letIn());
    } catch (error) {
      say(error);
    }
  };

  return (
    <section id="slapp-in" className="kort" aria-labelledby="slapp-in-rubrik">
      <h2 id="slapp-in-rubrik">Släpp in en person</h2>
      <p className="liten">För den som inte har loggat in på hubben förut. Koden har sex siffror, gäller en gång i 15 minuter och ger rollen Trafikledare i den här träffen, tills den slutar eller du tar bort den.</p>
      {given ? (
        <div className="engangskod" aria-live="polite">
          <p className="koden tm-mono" id="engangskod">
            {given.code.slice(0, 3)} {given.code.slice(3)}
          </p>
          <p className="liten">{`Trafikledare · gäller en gång, ${remaining(given.expires, at)} kvar. Koden visas bara nu.`}</p>
          <button type="button" className="tm-knapp" onClick={() => setGiven(null)}>
            Klar
          </button>
        </div>
      ) : (
        <form id="ge-kod" className="formular rad" onSubmit={(event) => void give(event)}>
          <label>
            Vem, om du vill <input id="kod-namn" maxLength={40} autoComplete="off" placeholder="Till exempel stationens namn" value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <button type="submit" className="tm-knapp primar">
            Ge en kod
          </button>
        </form>
      )}
      <h3>Insläppta</h3>
      <ul id="inslappta" className="lista">
        {people.length ? (
          people.map((person) => (
            <li key={person.person}>
              <div className="vem">
                <b>{person.name ?? "Utan namn"}</b>
                <span className="liten">{`${ROLE_WORD[person.role] ?? person.role} · med engångskod sedan ${clock(person.since)}`}</span>
              </div>
              <div className="kontroller">
                <button type="button" className="fara" onClick={() => void takeAway(person.person)}>
                  Ta bort
                </button>
              </div>
            </li>
          ))
        ) : (
          <li className="tom">Ingen är insläppt med en kod.</li>
        )}
      </ul>
    </section>
  );
}

function ClientRow({ client, now, onChange }: { client: Client; now: Now | null; onChange?: (change: ClientAction) => void }) {
  const places: [string, string][] = (now?.places ?? []).map((place) => [place.place, place.name]);
  const at = client.places ?? [];
  const [place, setPlace] = useState(at[0] ?? places[0]?.[0] ?? "");
  const [side, setSide] = useState<Client["side"]>(client.side);
  const [language, setLanguage] = useState<string>(client.language ?? "sv");
  const [view, setView] = useState(client.view ?? "clock");
  const id = client.client_id;
  let controls;
  if (client.kind === "screen") {
    controls = (
      <>
        <Select label={`Vy för ${client.name}`} options={Object.entries(VIEWS)} value={view} onChange={setView} />
        <button type="button" onClick={() => onChange?.({ action: "view", client_id: id, view })}>
          {client.view ? "Byt vy" : "Visa"}
        </button>
      </>
    );
  } else if (client.kind.startsWith("tmbox")) {
    controls = (
      <>
        <Select label={`Driftplats för ${client.name}`} options={places} value={place} onChange={setPlace} />
        <Select label={`Sida för ${client.name}`} options={Object.entries(SIDES)} value={side} onChange={(value) => setSide(value as Client["side"])} />
        <Select label={`Språk för ${client.name}`} options={Object.entries(LANGUAGES)} value={language} onChange={setLanguage} />
        <button type="button" onClick={() => onChange?.({ action: "assign", client_id: id, places: [place], side, language })}>
          {at.length ? "Ändra" : "Tilldela"}
        </button>
      </>
    );
  } else if (client.status === "approved") {
    controls = (
      <button type="button" className="fara" onClick={() => onChange?.({ action: "revoke", client_id: id })}>
        Återkalla
      </button>
    );
  } else {
    controls = (
      <>
        <Select label={`Driftplats för ${client.name}`} options={places} value={place} onChange={setPlace} />
        <button type="button" onClick={() => onChange?.({ action: "approve", client_id: id, places: [place] })}>
          Godkänn
        </button>
      </>
    );
  }
  return (
    <li className={client.status === "waiting" ? "vantar" : undefined}>
      <div className="vem">
        <b>{client.name}</b>
        <span className="liten">{clientDetails(client, now)}</span>
      </div>
      <div className="kontroller">{controls}</div>
      <ExitQuestions client={client} onAnswer={(section, exit) => onChange?.({ action: "exit", client_id: id, section, exit })} />
    </li>
  );
}

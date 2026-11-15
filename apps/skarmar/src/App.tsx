import { Skylt } from "@trainmeet/design";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { fetchPicture, join, savedKey, saveKey, type ScreenPicture } from "./api";

// A meet screen in the browser (SKARM-14): join with the code, wait under Väntar for a view,
// then show it. Steg 3 has the clock, drawn for 1920 × 1080 and scaled to the screen.

const DAYS: Record<ScreenPicture["traffic_day"], string> = {
  mon: "måndag",
  tue: "tisdag",
  wed: "onsdag",
  thu: "torsdag",
  fri: "fredag",
  sat: "lördag",
  sun: "söndag",
};

/** The meet clock now: the hub's time, run on at its speed since it was fetched. */
export function clockText(picture: ScreenPicture, fetchedAt: number, now: number): string {
  const { clock } = picture;
  const passed = clock.running ? ((now - fetchedAt) / 1000) * clock.speed : 0;
  const minutes = Math.floor((clock.seconds + passed) / 60) % 1440;
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

export type ScreenProps = {
  picture: ScreenPicture | null;
  fetchedAt: number;
  now: number;
  message: string;
  code: string;
  onJoin?: (name: string, code: string) => void;
};

/** Everything on the screen, from the state. No fetching here, so it can be rendered in tests. */
export function Screen({ picture, fetchedAt, now, message, code, onJoin }: ScreenProps) {
  if (picture && !picture.view) {
    return (
      <section id="waiting" className="vantar">
        <Skylt className="skylt" />
        <h1>Väntar på en vy</h1>
        <p>
          <b id="screen-name">{picture.name}</b> är ansluten. Välj vad den ska visa under Klienter.
        </p>
      </section>
    );
  }
  if (picture) {
    return (
      <section id="clock-view" className={`klocka ${picture.clock.running ? "gar" : "star"}`}>
        <h1 id="meet" className="traff">
          {picture.meet} · trafikdag {DAYS[picture.traffic_day]}
        </h1>
        <p id="time" className="tid">
          {clockText(picture, fetchedAt, now)}
        </p>
        <p id="state" className="lage">
          {picture.clock.running ? `Klockan går i ${picture.clock.speed}×` : "Klockan står still"}
        </p>
      </section>
    );
  }
  return <JoinForm message={message} code={code} onJoin={onJoin} />;
}

function JoinForm({ message, code, onJoin }: { message: string; code: string; onJoin?: ScreenProps["onJoin"] }) {
  const [name, setName] = useState("Skärm");
  const [typed, setTyped] = useState(code);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onJoin?.(name.trim(), typed.trim());
  };
  return (
    <section id="login" className="anslut">
      <Skylt className="skylt" />
      <h1>Anslut skärmen</h1>
      <p>Skriv träffens kod. Trafikledningen väljer sedan vad skärmen visar.</p>
      <form id="login-form" onSubmit={submit}>
        <label>
          Skärmens namn <input id="name" maxLength={40} required autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Kod <input id="code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} />
        </label>
        <button type="submit">Anslut</button>
      </form>
      <p id="message" role="alert">
        {message}
      </p>
    </section>
  );
}

/** The screen: asks the hub every 2 s, and moves the clock on every second in between. */
export function App() {
  const [key, setKey] = useState<string | null>(savedKey);
  const [picture, setPicture] = useState<ScreenPicture | null>(null);
  const [fetchedAt, setFetchedAt] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [message, setMessage] = useState("");
  const code = new URLSearchParams(window.location.hash.slice(1)).get("kod") ?? "";

  const refresh = useCallback(async () => {
    if (!key) return;
    const fetched = await fetchPicture(key);
    if (fetched === null) return; // The hub is out of reach; keep showing what we have.
    if ("gone" in fetched) {
      saveKey(null);
      setKey(null);
      setPicture(null);
      setMessage("Skärmen är inte ansluten längre. Anslut igen med koden.");
      return;
    }
    setPicture(fetched.picture);
    setFetchedAt(Date.now());
  }, [key]);

  useEffect(() => {
    void refresh();
    const asking = window.setInterval(() => void refresh(), 2000);
    const ticking = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      window.clearInterval(asking);
      window.clearInterval(ticking);
    };
  }, [refresh]);

  const onJoin = async (name: string, typed: string) => {
    const joined = await join({ name, code: typed });
    if ("problem" in joined) {
      setMessage(joined.problem);
      return;
    }
    saveKey(joined.key);
    setMessage("");
    setKey(joined.key);
  };

  return (
    <main>
      <Screen picture={picture} fetchedAt={fetchedAt} now={now} message={message} code={code} onJoin={onJoin} />
    </main>
  );
}

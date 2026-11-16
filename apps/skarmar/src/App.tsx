import { Skylt } from "@trainmeet/design";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { fetchPackage, fetchPicture, join, savedKey, saveKey, type Package, type ScreenPicture } from "./api";
import { BanaView } from "./Bana";
import { Klocka } from "./Klocka";

export { clockText } from "./Klocka";

// A meet screen in the browser (SKARM-14): join with the code, wait under Väntar for a view,
// then show it, drawn for 1920 × 1080 and scaled to the screen.

export type ScreenProps = {
  picture: ScreenPicture | null;
  /** The package the views that draw the line draw on. */
  pkg?: Package | null;
  fetchedAt: number;
  now: number;
  message: string;
  code: string;
  onJoin?: (name: string, code: string) => void;
};

/** Everything on the screen, from the state. No fetching here, so it can be rendered in tests. */
export function Screen({ picture, pkg = null, fetchedAt, now, message, code, onJoin }: ScreenProps) {
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
  if (picture?.view === "tracks") return <BanaView picture={picture} pkg={pkg} fetchedAt={fetchedAt} now={now} />;
  if (picture) return <Klocka picture={picture} fetchedAt={fetchedAt} now={now} />;
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
  const [pkg, setPkg] = useState<{ key: string; pkg: Package } | null>(null);
  const [fetchedAt, setFetchedAt] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [message, setMessage] = useState("");
  const pkgKey = useRef<string | null>(null);
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
    // The package is fetched once, and again when the version or a driftändring changes it.
    const wanted = fetched.picture.package;
    if (wanted && wanted !== pkgKey.current) {
      pkgKey.current = wanted;
      const read = await fetchPackage(key);
      if (read) setPkg({ key: wanted, pkg: read });
      else pkgKey.current = null;
    }
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
      <Screen picture={picture} pkg={pkg?.pkg ?? null} fetchedAt={fetchedAt} now={now} message={message} code={code} onJoin={onJoin} />
    </main>
  );
}

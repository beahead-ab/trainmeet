import { Header } from "@trainmeet/design";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { fetchFrame, follow, logIn, readSession, sendKeys, writeSession, type BoxSession, type Frame, type Key } from "./api";
import { columnsOf, extras, KEYS, keyFor, labels, press, shownLines, type SendKey } from "./box";

// TMBox web (BOXWEB-01–BOXWEB-14): one box per tab. Drift draws the picture (16×2 or 20×4);
// this page shows it, keeps the typed train number until #, and sends the keys.

const TONES: Record<string, number[]> = {
  incoming_request: [880, 0, 880],
  request_denied: [392, 0, 262],
  request_approved: [523, 659],
  incoming_train: [660, 0, 660],
};

/** On /provbanan/box the box joins a Provbanan run; on /box the hub's meet. */
export const onProvbanan = (path: string) => path.startsWith("/provbanan");

export type BoxPageProps = {
  provbanan: boolean;
  hubName: string;
  session: BoxSession | null;
  frame: Frame | null;
  entry: string | null;
  message: string;
  loginError: string;
  code: string;
  onLogIn?: (name: string, code: string, display: { rows: 2 | 4; cols: 16 | 20 }) => void;
  onPress?: (key: Key) => void;
  onLeave?: () => void;
};

/** Everything on the page, from the state. No fetching here, so it can be rendered in tests. */
export function BoxPage(props: BoxPageProps) {
  const { provbanan, hubName, session } = props;
  return (
    <>
      <Header product="HUB" productLabel="TrainMeet Hub" place={hubName} home="/" navLabel="Huvudmeny" tabs={[]} />
      <main className="tmbox">
        {provbanan ? <a href="/provbanan">← Provbanan</a> : <a href="/">← Hubben</a>}
        {session ? <Box {...props} session={session} /> : <LoginCard {...props} />}
      </main>
    </>
  );
}

function LoginCard({ provbanan, loginError, code, onLogIn }: BoxPageProps) {
  const [name, setName] = useState(() => `Box ${Math.floor(Math.random() * 90 + 10)}`);
  const [typed, setTyped] = useState(code);
  const [display, setDisplay] = useState("2x16");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const [rows, cols] = display.split("x").map(Number);
    onLogIn?.(name.trim(), typed.trim(), { rows: rows === 4 ? 4 : 2, cols: cols === 20 ? 20 : 16 });
  };
  return (
    <section id="login" className="kort">
      <h1>TMBox</h1>
      <p className="ingress">
        Anslut boxen till {provbanan ? "en provkörning med koden som står på Provbanan under Boxar" : "träffen med koden som trafikledningen visar under Anslut"}. Varje flik blir en egen box.
      </p>
      <form id="login-form" className="falt" onSubmit={submit}>
        <label>
          Boxens namn <input id="name" maxLength={40} required autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Kod <input id="code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} />
        </label>
        <label>
          Display{" "}
          <select id="display" value={display} onChange={(e) => setDisplay(e.target.value)}>
            <option value="2x16">16 × 2, som de flesta boxar</option>
            <option value="4x20">20 × 4</option>
          </select>
        </label>
        <button type="submit">Anslut</button>
      </form>
      <p id="login-error" className="fel" role="alert">
        {loginError}
      </p>
    </section>
  );
}

function Box({ session, frame, entry, message, onPress, onLeave }: BoxPageProps & { session: BoxSession }) {
  const shown = labels(frame, entry);
  const extra = extras(frame);
  const lines = shownLines(frame, entry);
  const columns = columnsOf(lines);
  return (
    <section id="box" className="kort">
      <div className="boxhuvud">
        <h1 id="box-name">{session.name + (frame && !extra.waiting ? ` · ${frame.station}` : "")}</h1>
        <button id="logout" type="button" className="lank" onClick={onLeave}>
          Koppla från
        </button>
      </div>
      <p id="status" className="boxstatus">
        {entry !== null ? "Skriv tågnumret och tryck #. B suddar, * avbryter." : extra.status}
      </p>
      <p id="queue" className={`boxko${extra.queued ? " vantar" : ""}`} role="status">
        {extra.queue}
      </p>
      <div className="tmbox-case">
        <div className="lcd-frame">
          <div id="lcd" className="lcd" role="img" aria-label={lines.join(". ")}>
            {lines.map((line, row) => (
              <div key={row} className="lcd-row" style={columns > 16 ? { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` } : undefined}>
                {[...line.normalize("NFC")].map((character, cell) => (
                  <span key={cell} className="lcd-cell" style={columns > 16 ? { fontSize: `clamp(10px, ${(128 / columns).toFixed(2)}cqi, 19px)` } : undefined}>
                    {character}
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>
        <div id="keypad" className="keypad">
          {/* Every key can always be pressed, as on the box. One that cannot do anything
              right now simply does nothing; nothing lights up or dims. */}
          {KEYS.map((key) => (
            <button key={key} type="button" className={"key" + (/[A-D]/.test(key) ? " function" : "")} data-key={key} aria-label={shown[key] ? `${key} · ${shown[key]}` : key} onClick={() => onPress?.(key)}>
              {key}
            </button>
          ))}
        </div>
      </div>
      <div id="hints" className="key-hints">
        {Object.entries(shown).map(([key, label]) => (
          <span key={key}>
            <b>{key}</b>
            {label}
          </span>
        ))}
      </div>
      <p id="message" className="fel" role="status">
        {message}
      </p>
      <p className="ingress tips">Tangentbordet fungerar också: siffror, A–D, * och #. Enter är #, Backsteg är B och Esc är *.</p>
    </section>
  );
}

/** The page: logs the tab in as a box, follows the picture and sends the keys. */
export function App() {
  const provbanan = onProvbanan(window.location.pathname);
  const [hubName, setHubName] = useState("Hubben");
  const [session, setSession] = useState<BoxSession | null>(readSession);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [entry, setEntry] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [loginError, setLoginError] = useState("");
  const shownAt = useRef(0);
  const updatedAt = useRef(0);
  const attention = useRef<Frame["attention"] | null>(null);
  const audio = useRef<AudioContext | null>(null);
  const messageTimer = useRef(0);
  const frameRef = useRef<Frame | null>(null);
  const entryRef = useRef<string | null>(null);
  const code = new URLSearchParams(window.location.hash.slice(1)).get("kod") ?? "";

  useEffect(() => {
    fetch("/api/version")
      .then((r) => r.json())
      .then((v: { hub_name?: unknown }) => {
        if (typeof v.hub_name === "string") setHubName(v.hub_name);
      })
      .catch(() => undefined);
  }, []);

  const say = useCallback((text: string) => {
    setMessage(text);
    window.clearTimeout(messageTimer.current);
    if (text) messageTimer.current = window.setTimeout(() => setMessage(""), 4000);
  }, []);

  const beep = useCallback((kind: string) => {
    try {
      audio.current ??= new AudioContext();
      let at = audio.current.currentTime;
      for (const tone of TONES[kind] ?? [660]) {
        if (tone) {
          const oscillator = audio.current.createOscillator();
          const gain = audio.current.createGain();
          oscillator.frequency.value = tone;
          gain.gain.value = 0.08;
          oscillator.connect(gain).connect(audio.current.destination);
          oscillator.start(at);
          oscillator.stop(at + 0.12);
        }
        at += 0.16;
      }
    } catch {
      // No sound in this browser; the picture still says it.
    }
  }, []);

  const show = useCallback(
    (next: Frame) => {
      const before = frameRef.current;
      if (next.view_token !== before?.view_token) shownAt.current = performance.now();
      const last = attention.current;
      const now = next.attention;
      if (last && now && now.epoch === last.epoch && now.seq > last.seq && now.kind) beep(now.kind);
      attention.current = now;
      frameRef.current = next;
      updatedAt.current = performance.now();
      setFrame(next);
    },
    [beep],
  );

  const leave = useCallback((text: string) => {
    writeSession(null);
    frameRef.current = null;
    entryRef.current = null;
    attention.current = null;
    setSession(null);
    setFrame(null);
    setEntry(null);
    setLoginError(text);
  }, []);

  // The picture comes over the event stream; one that stops coming is fetched instead.
  useEffect(() => {
    if (!session) return;
    const stop = new AbortController();
    let running = true;
    const gone = () => leave(provbanan ? "Provkörningen har gått ut. Anslut igen." : "Boxen är inte längre ansluten. Anslut igen.");
    void fetchFrame(session).then((got) => (got === "gone" ? leave("Boxen är inte längre ansluten. Anslut igen.") : got && show(got)));
    void (async () => {
      while (running) {
        try {
          if ((await follow(session, stop.signal, show)) === "gone") return gone();
        } catch {
          if (!running) return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
      }
    })();
    const fallback = window.setInterval(() => {
      if (performance.now() - updatedAt.current > 2500) {
        void fetchFrame(session).then((got) => (got === "gone" ? leave("Boxen är inte längre ansluten. Anslut igen.") : got && show(got)));
      }
    }, 1000);
    return () => {
      running = false;
      stop.abort();
      window.clearInterval(fallback);
    };
  }, [session, show, leave, provbanan]);

  const send = useCallback(
    async (key: SendKey) => {
      const current = frameRef.current;
      if (!session || !current) return;
      const sent = await sendKeys(session, {
        command_id: crypto.randomUUID(),
        view_token: current.view_token,
        key: key.key,
        train_number: key.train_number ?? null,
        entry_context: key.entry_context ?? null,
        boot: null,
      });
      if (sent === "gone") return leave("Boxen är inte längre ansluten. Anslut igen.");
      if (sent === "offline") return say("Kontakten med Hubben bröts. Försöker igen …");
      if ("problem" in sent) return say(sent.problem);
      if (sent.ack.status === "rejected" && sent.ack.message) say(sent.ack.message);
      show(sent.ack.frame);
    },
    [session, leave, say, show],
  );

  const onPress = useCallback(
    (key: Key) => {
      try {
        audio.current ??= new AudioContext();
      } catch {
        // no sound
      }
      const pressed = press(frameRef.current, entryRef.current, key, performance.now() - shownAt.current);
      entryRef.current = pressed.entry;
      setEntry(pressed.entry);
      if (pressed.send) void send(pressed.send);
    },
    [send],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!frameRef.current || event.target instanceof HTMLInputElement || event.metaKey || event.ctrlKey) return;
      const key = keyFor(event.key);
      if (key) {
        event.preventDefault();
        onPress(key);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onPress]);

  const onLogIn = async (name: string, typed: string, display: { rows: 2 | 4; cols: 16 | 20 }) => {
    try {
      audio.current ??= new AudioContext();
    } catch {
      // no sound
    }
    setLoginError("");
    const answer = await logIn({ name, code: typed, display });
    if (!answer.session) return setLoginError(answer.problem);
    const box = { ...answer.session, name };
    writeSession(box);
    setSession(box);
  };

  return (
    <BoxPage
      provbanan={provbanan}
      hubName={hubName}
      session={session}
      frame={frame}
      entry={entry}
      message={message}
      loginError={loginError}
      code={code}
      onLogIn={onLogIn}
      onPress={onPress}
      onLeave={() => leave("")}
    />
  );
}

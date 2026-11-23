import { hub, openOnOutput, Problem, useRelock } from "@trainmeet/hubben";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

// Skärmlåset (S4, SKARM-03): on the Pi's own outputs keyboard and mouse do nothing to the
// screen. A key or a click asks for the hub's PIN, the same PIN as at Första start. Unlocked,
// one may open the hub's pages on the output, join it to the meet again, or lock it; two
// minutes without a key or a click lock it again by themselves. A screen on a Mac or a PC has
// no lock: the computer is its owner's.

/** Every key and click that would reach the screen while it is locked. */
const STOPPED = ["keydown", "keyup", "keypress", "pointerdown", "pointerup", "mousedown", "mouseup", "click", "dblclick", "auxclick", "contextmenu", "wheel", "touchstart", "touchend"] as const;
/** The ones that ask for the PIN. */
const ASKING = new Set(["keydown", "pointerdown", "touchstart"]);
/** The PIN field goes away again after half a minute without a key. */
const ASKING_MS = 30_000;

export type LockState = "locked" | "asking" | "open";

export type LockProps = {
  output: number;
  /** The hub has its PIN. Before Första start there is nothing to unlock with, and no lock. */
  setUp: boolean;
  /** The output has joined the meet, so Anslut på nytt has something to undo. */
  joined: boolean;
  onReconnect: () => void;
  /** Leaves the screen for the hub's pages; left out, the browser goes there. */
  leave?: (href: string) => void;
  /** Where it starts; a test may start it asking or open. */
  initial?: LockState;
};

const goTo = (href: string) => window.location.assign(href);

export function Skarmlas({ output, setUp, joined, onReconnect, leave = goTo, initial = "locked" }: LockProps) {
  const [state, setState] = useState<LockState>(initial);
  const [pin, setPin] = useState("");
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const locked = setUp && state !== "open";

  useEffect(() => {
    if (!locked) return;
    const stop = (event: Event) => {
      if (event.target instanceof Node && box.current?.contains(event.target)) return;
      event.preventDefault();
      event.stopPropagation();
      if (ASKING.has(event.type)) setState("asking");
    };
    for (const kind of STOPPED) window.addEventListener(kind, stop, { capture: true, passive: false });
    return () => {
      for (const kind of STOPPED) window.removeEventListener(kind, stop, { capture: true });
    };
  }, [locked]);

  const close = () => {
    setState("locked");
    setPin("");
    setSaid("");
  };
  /** Locked again: the session the PIN gave this browser ends too. */
  const lock = () => {
    close();
    void hub.logOut().catch(() => undefined);
  };
  useRelock(state === "asking", close, ASKING_MS);
  useRelock(state === "open", lock);

  const unlock = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await hub.logIn(pin);
      setState("open");
      setSaid("");
    } catch (error) {
      setSaid(error instanceof Problem ? error.message : "Det gick inte.");
    } finally {
      setBusy(false);
      setPin("");
    }
  };
  const escape = (event: KeyboardEvent) => {
    if (event.key === "Escape") close();
  };
  const toHub = () => {
    openOnOutput(output);
    leave("/");
  };

  if (!setUp) {
    return (
      <p id="lock-none" className="las-rad">
        Hubben har ingen PIN-kod än, så skärmen är inte låst.{" "}
        <a
          href="/"
          onClick={(event) => {
            event.preventDefault();
            toHub();
          }}
        >
          Välj PIN-kod på hubben
        </a>
      </p>
    );
  }
  if (state === "open") {
    return (
      <div ref={box} id="lock-open" className="las-rad" role="region" aria-label="Skärmlåset">
        <p>
          Skärm {output} är upplåst. Den låses igen efter två minuter utan tangenttryck eller klick.
        </p>
        <button id="to-hub" type="button" onClick={toHub}>
          Till hubben
        </button>
        {joined && (
          <button id="reconnect" type="button" className="andra" onClick={onReconnect}>
            Anslut på nytt
          </button>
        )}
        <button id="lock" type="button" className="andra" onClick={lock}>
          Lås
        </button>
      </div>
    );
  }
  if (state === "asking") {
    return (
      <div className="las-bakgrund">
        <div ref={box} id="lock-dialog" className="las" role="dialog" aria-modal="true" aria-labelledby="lock-title">
          <h2 id="lock-title">Skärmen är låst</h2>
          <p>Skriv hubbens PIN-kod för att använda tangentbordet och musen.</p>
          <form id="unlock-form" onSubmit={(event) => void unlock(event)} onKeyDown={escape}>
            <label>
              PIN-kod{" "}
              <input id="unlock-pin" type="password" inputMode="numeric" autoComplete="off" autoFocus maxLength={12} value={pin} onChange={(event) => setPin(event.target.value)} />
            </label>
            <button type="submit" disabled={busy || !pin}>
              Lås upp
            </button>
          </form>
          <p id="unlock-message" role="alert">
            {said}
          </p>
        </div>
      </div>
    );
  }
  return null;
}

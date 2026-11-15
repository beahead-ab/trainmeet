import { useCallback, useEffect, useRef, useState } from "react";
import { api, Problem, type Automation, type AutomationSettings, type ChangePlace, type Client, type ClockControl, type HubInfo, type Joining, type MeetSummary, type Now, type Version, type Weekday } from "./api";
import { askedChoice, meetChoices, waitingCount, type MeetChoice } from "./drift";
import { KlienterPage, type ClientAction } from "./Klienter";
import { LoggPage } from "./Logg";
import { NuPage } from "./Nu";
import { ProvbananPage } from "./Provbanan";
import { isDrift, Sidhuvud, type Menu, type Page } from "./Sidhuvud";
import { StartPage } from "./StartPage";

// Trafikledningen (TRAFIK-21): the start page, and Nu, Klienter and Logg, under the same
// header. Nu is read every other second, the clients every third, Automatiken every third and
// the log every fifth, as the old pages did; the clock runs on between the answers.

export function pageOf(path: string): Page {
  const clean = path.replace(/\/+$/, "");
  if (clean === "/drift/klienter") return "klienter";
  if (clean === "/drift/logg") return "logg";
  if (clean === "/drift" || clean.startsWith("/drift/")) return "nu";
  if (clean === "/provbanan") return "provbanan";
  return "start";
}

/** The addresses this app draws itself; the rest (Planering, the boxes) are other pages. */
export const isOwn = (path: string) => path === "/" || path === "/provbanan" || path === "/drift" || path.startsWith("/drift/");

export function App() {
  const [path, setPath] = useState(() => window.location.pathname);
  const page = pageOf(path);
  const [info, setInfo] = useState<HubInfo | null>(null);
  const [version, setVersion] = useState<Version | null>(null);
  const [now, setNow] = useState<Now | null>(null);
  const nowAt = useRef(0);
  const [clients, setClients] = useState<Client[]>([]);
  const [meets, setMeets] = useState<MeetSummary[]>([]);
  const [automation, setAutomation] = useState<Automation | null>(null);
  const [automationSaved, setAutomationSaved] = useState(0);
  const [menu, setMenu] = useState<Menu>(null);
  const [joining, setJoining] = useState<Joining | null>(null);
  const [joinedAt, setJoinedAt] = useState(0);
  const [message, setMessage] = useState("");
  const [, setTick] = useState(0);
  const admin = info?.logged_in ?? false;
  const choices: MeetChoice[] = meetChoices(meets);
  const asked = askedChoice(window.location.search, choices);

  const readInfo = useCallback(async () => {
    try {
      setInfo(await api.hub());
    } catch {
      // The hub is out of reach; the next answer brings it back.
    }
  }, []);

  /** What went wrong, in the hub's words; a session that ran out logs the page out. */
  const fail = useCallback(
    (error: unknown) => {
      if (!(error instanceof Problem)) return;
      setMessage(error.message);
      if (error.status === 401) void readInfo();
    },
    [readInfo],
  );

  const readNow = useCallback(async () => {
    try {
      const next = await api.now();
      nowAt.current = performance.now();
      setNow(next);
    } catch {
      // The next round tries again.
    }
  }, []);

  const readClients = useCallback(async () => {
    try {
      setClients(await api.clients());
    } catch {
      setClients([]);
    }
  }, []);

  const readAutomation = useCallback(async () => {
    try {
      setAutomation(await api.automation());
    } catch {
      setAutomation(null);
    }
  }, []);

  useEffect(() => {
    void readInfo();
    void api.version().then(setVersion, () => undefined);
    void readNow();
    const clock = window.setInterval(() => setTick((tick) => tick + 1), 1000);
    const nu = window.setInterval(() => void readNow(), 2000);
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => {
      window.clearInterval(clock);
      window.clearInterval(nu);
      window.removeEventListener("popstate", onPop);
    };
  }, [readInfo, readNow]);

  useEffect(() => {
    if (!admin) {
      setClients([]);
      return;
    }
    void readClients();
    void api.meets().then(setMeets, () => undefined);
    const timer = window.setInterval(() => void readClients(), 3000);
    return () => window.clearInterval(timer);
  }, [admin, readClients]);

  const running = now !== null;
  useEffect(() => {
    if (!admin || page !== "nu" || !running) return setAutomation(null);
    void readAutomation();
    const timer = window.setInterval(() => void readAutomation(), 3000);
    return () => window.clearInterval(timer);
  }, [admin, page, running, readAutomation]);

  // Kör i Drift in Planering comes here with the meet asked for: Byt träff opens with it.
  useEffect(() => {
    if (admin && window.location.hash === "#ny-traff") setMenu("byt");
  }, [admin]);

  useEffect(() => {
    document.title = `TrainMeet Hub · ${info?.name ?? "Hubben"}`;
    document.body.classList.toggle("kontrollrummet", isDrift(page));
  }, [info, page]);

  const navigate = useCallback((href: string) => {
    const target = new URL(href, window.location.origin);
    if (!isOwn(target.pathname)) {
      window.location.assign(href);
      return;
    }
    window.history.pushState(null, "", href);
    setPath(target.pathname);
    setMenu(null);
    setMessage("");
    window.scrollTo(0, 0);
  }, []);

  const onMenu = async (next: Menu) => {
    setMenu(next);
    if (next === "byt") void api.meets().then(setMeets, () => undefined);
    if (next !== "anslut") return;
    try {
      setJoining(await api.connect());
      setJoinedAt(Date.now());
    } catch (error) {
      setMenu(null);
      fail(error);
    }
  };

  const act = async (action: () => Promise<unknown>) => {
    try {
      await action();
      setMessage("");
      return true;
    } catch (error) {
      fail(error);
      return false;
    }
  };

  const onStart = async (choice: MeetChoice, day: Weekday) => {
    if (await act(() => api.start({ meet: choice.meet, version: choice.version, traffic_day: day, game_day: 1 }))) {
      setMenu(null);
      setJoining(null);
      await readNow();
      await readClients();
    }
  };

  const onClock = async (control: ClockControl) => {
    if (await act(() => api.clock(control))) await readNow();
  };

  const onClient = async (change: ClientAction) => {
    const sent = await act(() => {
      switch (change.action) {
        case "assign":
          return api.assign({ client_id: change.client_id, places: change.places, side: change.side, language: change.language as never });
        case "approve":
          return api.approve({ client_id: change.client_id, places: change.places });
        case "revoke":
          return api.revoke({ client_id: change.client_id });
        case "view":
          return api.view({ client_id: change.client_id, view: change.view as never });
      }
    });
    if (sent) await readClients();
  };

  const onAutomation = async (settings: AutomationSettings) => {
    await act(async () => {
      setAutomation(await api.setAutomation(settings));
      setAutomationSaved((count) => count + 1);
    });
  };

  const onPlace = async (change: ChangePlace) => {
    await act(async () => setAutomation(await api.changePlace(change)));
  };

  const onLogOut = async () => {
    await act(() => api.logOut());
    await readInfo();
    navigate("/");
  };

  const onSetUp = async (name: string, pin: string) => {
    if (await act(() => api.setUp(name, pin))) await readInfo();
  };

  const onLogIn = async (pin: string) => {
    if (await act(() => api.logIn(pin))) await readInfo();
  };

  return (
    <>
      <Sidhuvud
        page={page}
        hubName={info?.name ?? "Hubben"}
        admin={admin}
        now={now}
        elapsedMs={now ? performance.now() - nowAt.current : 0}
        waiting={waitingCount(clients)}
        choices={choices}
        asked={asked}
        menu={admin ? menu : null}
        joining={joining}
        joinedAt={joinedAt}
        navigate={navigate}
        onMenu={(next) => void onMenu(next)}
        onStart={(choice, day) => void onStart(choice, day)}
        onLogOut={() => void onLogOut()}
      />
      <main id="innehall" className={page === "start" ? "startsida" : page === "provbanan" ? "provsida" : "drift"}>
        {page === "start" && (
          <StartPage
            info={info}
            version={version}
            message={message}
            navigate={navigate}
            onSetUp={(name, pin) => void onSetUp(name, pin)}
            onLogIn={(pin) => void onLogIn(pin)}
            onLogOut={() => void onLogOut()}
            onMessage={setMessage}
          />
        )}
        {page === "nu" && (
          <NuPage
            admin={admin}
            now={now}
            clients={clients}
            choices={choices}
            asked={asked}
            automation={automation}
            automationSaved={automationSaved}
            openAutomation={window.location.hash === "#automatiken"}
            onClock={(control) => void onClock(control)}
            onStart={(choice, day) => void onStart(choice, day)}
            onAutomation={(settings) => void onAutomation(settings)}
            onPlace={(change) => void onPlace(change)}
          />
        )}
        {page === "klienter" && <KlienterPage admin={admin} now={now} clients={clients} navigate={navigate} onChange={(change) => void onClient(change)} />}
        {page === "logg" && <LoggPage admin={admin} now={now} clients={clients} navigate={navigate} onMessage={setMessage} />}
        {page === "provbanan" && <ProvbananPage />}
        {isDrift(page) && (
          <p id="message" className="meddelande" role="alert">
            {message}
          </p>
        )}
      </main>
    </>
  );
}

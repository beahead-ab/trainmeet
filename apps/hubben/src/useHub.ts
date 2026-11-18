import { useCallback, useEffect, useRef, useState } from "react";
import { hub, Problem, type Client, type HubInfo, type Joining, type MeetSummary, type Now, type Version, type Weekday } from "./api";
import type { HeaderProps, Menu } from "./Sidhuvud";
import { askedChoice, meetChoices, waitingCount, type MeetChoice } from "./traff";

// What the header needs, kept fresh the same way on every page: Den här hubben once and after
// each login, Nu every other second, the clients every third (logged in), and the meets when
// Byt träff opens. The clock runs on between the answers, redrawn every second.

export type Hub = {
  info: HubInfo | null;
  /** May run the traffic: the one with the hub's PIN, or someone let in as Trafikledare (H56). */
  admin: boolean;
  /** The one with the hub's PIN (H18): the hub's own settings, Planering and Byt träff too. */
  owner: boolean;
  version: Version | null;
  now: Now | null;
  /** Milliseconds since Nu came, for a clock that runs on between the answers. */
  elapsedMs: number;
  clients: Client[];
  choices: MeetChoice[];
  asked: string | null;
  message: string;
  say: (text: string) => void;
  /** What went wrong, in the hub's words; a session that ran out logs the page out. */
  fail: (error: unknown) => void;
  readInfo: () => Promise<void>;
  readNow: () => Promise<void>;
  readClients: () => Promise<void>;
  /** Runs a call to the hub; true when it went through, else the problem is said. */
  act: (action: () => Promise<unknown>) => Promise<boolean>;
  logOut: () => Promise<void>;
  /** Starts a meet in Drift (Byt träff, or Starta träffen in Nu when none runs). */
  start: (choice: MeetChoice, day: Weekday) => Promise<void>;
  header: (page: { current: string; viewed?: string | null; navigate: (href: string) => void; bottom?: HeaderProps["bottom"] }) => HeaderProps;
};

export function useHub(): Hub {
  const [info, setInfo] = useState<HubInfo | null>(null);
  const [version, setVersion] = useState<Version | null>(null);
  const [now, setNow] = useState<Now | null>(null);
  const nowAt = useRef(0);
  const [clients, setClients] = useState<Client[]>([]);
  const [meets, setMeets] = useState<MeetSummary[]>([]);
  const [menu, setMenu] = useState<Menu>(null);
  const [joining, setJoining] = useState<Joining | null>(null);
  const [joinedAt, setJoinedAt] = useState(0);
  const [message, say] = useState("");
  const [, setTick] = useState(0);
  const owner = info?.admin ?? false;
  // Runs the meet that runs: the PIN, let in as Trafikledare (H56), or Administratör or
  // Trafikledare at the meet in TrainMeet ID (#78).
  const admin = owner || (info?.may_run ?? false) || info?.meet_role === "dispatcher";
  // Byt träff: the PIN, and someone logged in with ID, whom the hub lets start the meets where
  // ID gives them a role.
  const starts = owner || Boolean(info?.person);
  const choices = meetChoices(meets);
  const asked = askedChoice(window.location.search, choices);

  const readInfo = useCallback(async () => {
    try {
      setInfo(await hub.info());
    } catch {
      // The hub is out of reach; the next answer brings it back.
    }
  }, []);

  const fail = useCallback(
    (error: unknown) => {
      if (!(error instanceof Problem)) return;
      say(error.message);
      if (error.status === 401) void readInfo();
    },
    [readInfo],
  );

  const readNow = useCallback(async () => {
    try {
      const next = await hub.now();
      nowAt.current = performance.now();
      setNow(next);
    } catch {
      // The next round tries again.
    }
  }, []);

  const readClients = useCallback(async () => {
    try {
      setClients(await hub.clients());
    } catch {
      setClients([]);
    }
  }, []);

  useEffect(() => {
    void readInfo();
    void hub.version().then(setVersion, () => undefined);
    void readNow();
    const clock = window.setInterval(() => setTick((tick) => tick + 1), 1000);
    const nu = window.setInterval(() => void readNow(), 2000);
    return () => {
      window.clearInterval(clock);
      window.clearInterval(nu);
    };
  }, [readInfo, readNow]);

  useEffect(() => {
    if (!admin) {
      setClients([]);
      return;
    }
    void readClients();
    void hub.meets().then(setMeets, () => undefined);
    const timer = window.setInterval(() => void readClients(), 3000);
    return () => window.clearInterval(timer);
  }, [admin, readClients]);

  // Kör i Drift in Planering comes with the meet asked for: Byt träff opens with it.
  useEffect(() => {
    if (starts && window.location.hash === "#ny-traff") setMenu("byt");
  }, [starts]);

  useEffect(() => {
    document.title = `TrainMeet Hub · ${info?.name ?? "Hubben"}`;
  }, [info]);

  const act = useCallback(
    async (action: () => Promise<unknown>) => {
      try {
        await action();
        say("");
        return true;
      } catch (error) {
        fail(error);
        return false;
      }
    },
    [fail],
  );

  const onMenu = async (next: Menu) => {
    setMenu(next);
    if (next === "byt") void hub.meets().then(setMeets, () => undefined);
    if (next !== "anslut") return;
    try {
      setJoining(await hub.connect());
      setJoinedAt(Date.now());
    } catch (error) {
      setMenu(null);
      fail(error);
    }
  };

  const onStart = async (choice: MeetChoice, day: Weekday) => {
    if (await act(() => hub.start({ meet: choice.meet, version: choice.version, traffic_day: day, game_day: 1 }))) {
      setMenu(null);
      setJoining(null);
      await readNow();
      await readClients();
    }
  };

  const logOut = async () => {
    let away: string | null | undefined = null;
    await act(async () => {
      away = (await hub.logOut()).logout_url;
    });
    // A login with TrainMeet ID logs out of ID too, which sends the browser back (KONTO-01).
    if (away) {
      window.location.assign(away);
      return;
    }
    await readInfo();
  };

  return {
    info,
    admin,
    owner,
    version,
    now,
    elapsedMs: now ? performance.now() - nowAt.current : 0,
    clients,
    choices,
    asked,
    message,
    say,
    fail,
    readInfo,
    readNow,
    readClients,
    act,
    logOut,
    start: onStart,
    header: ({ current, viewed, navigate, bottom }) => ({
      current,
      viewed,
      bottom,
      hubName: info?.name ?? "Hubben",
      admin,
      owner: starts,
      loggedIn: info?.logged_in ?? false,
      person: info?.person ?? null,
      now,
      elapsedMs: now ? performance.now() - nowAt.current : 0,
      waiting: waitingCount(clients),
      choices,
      asked,
      menu: (menu === "byt" && starts) || (menu !== "byt" && admin) ? menu : null,
      joining,
      joinedAt,
      navigate: (href: string) => {
        setMenu(null);
        navigate(href);
      },
      onMenu: (next) => void onMenu(next),
      onStart: (choice, day) => void onStart(choice, day),
      onLogOut: () => {
        void logOut().then(() => navigate("/"));
      },
    }),
  };
}

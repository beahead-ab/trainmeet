import { DRIFT_TABS, hub, Sidhuvud, useHub } from "@trainmeet/hubben";
import { useCallback, useEffect, useState } from "react";
import { api, type Automation, type AutomationSettings, type ChangePlace, type ClockControl, type DaySettings, type NewDay, type PlacePhone } from "./api";
import { SettingsPage } from "./Installningar";
import { KlienterPage, type ClientAction } from "./Klienter";
import { LoggPage } from "./Logg";
import { NuPage } from "./Nu";
import { ProvbananPage } from "./Provbanan";
import { StartPage } from "./StartPage";

// Trafikledningen (TRAFIK-21): the start page, Provbanan, Inställningar, and Nu, Klienter and
// Logg, under the Hub's header (@trainmeet/hubben). Automatiken is read every third second and
// the log every fifth, as the old pages did; Nu and the clients come with the header.

export type Page = "start" | "nu" | "klienter" | "logg" | "provbanan" | "installningar";

export function pageOf(path: string): Page {
  const clean = path.replace(/\/+$/, "");
  if (clean === "/drift/klienter") return "klienter";
  if (clean === "/drift/logg") return "logg";
  if (clean === "/drift" || clean.startsWith("/drift/")) return "nu";
  if (clean === "/provbanan") return "provbanan";
  if (clean === "/installningar") return "installningar";
  return "start";
}

/** Nu, Klienter and Logg: Drift's own pages, in Kontrollrummet. */
export const isDrift = (page: Page) => page === "nu" || page === "klienter" || page === "logg";

/** The addresses this app draws itself; the rest (Planering, the boxes) are other pages. */
export const isOwn = (path: string) => ["/", "/provbanan", "/installningar", "/drift"].includes(path) || path.startsWith("/drift/");

const ADDRESS: Record<Page, string> = {
  start: "/",
  nu: "/drift",
  klienter: "/drift/klienter",
  logg: "/drift/logg",
  provbanan: "/provbanan",
  installningar: "/installningar",
};

const MAIN: Partial<Record<Page, string>> = { start: "startsida", provbanan: "provsida", installningar: "installningssida" };

export function App() {
  const [path, setPath] = useState(() => window.location.pathname);
  const page = pageOf(path);
  const hubState = useHub();
  const { admin, now, clients, info, act, say, readInfo, readNow, readClients } = hubState;
  const [automation, setAutomation] = useState<Automation | null>(null);
  const [automationSaved, setAutomationSaved] = useState(0);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    document.body.classList.toggle("kontrollrummet", isDrift(page));
  }, [page]);

  const readAutomation = useCallback(async () => {
    try {
      setAutomation(await api.automation());
    } catch {
      setAutomation(null);
    }
  }, []);

  const [phones, setPhones] = useState<PlacePhone[] | null>(null);
  const readPhones = useCallback(async () => {
    try {
      setPhones(await api.phones());
    } catch {
      setPhones(null);
    }
  }, []);

  const running = now !== null;
  useEffect(() => {
    if (!admin || (page !== "nu" && page !== "installningar") || !running) return setAutomation(null);
    void readAutomation();
    const timer = window.setInterval(() => void readAutomation(), 3000);
    return () => window.clearInterval(timer);
  }, [admin, page, running, readAutomation]);

  // The numbers are read under the gear only, and only by the administrator (B13).
  useEffect(() => {
    if (!admin || page !== "installningar" || !running) return setPhones(null);
    void readPhones();
  }, [admin, page, running, readPhones]);

  const navigate = useCallback(
    (href: string) => {
      const target = new URL(href, window.location.origin);
      if (!isOwn(target.pathname)) {
        window.location.assign(href);
        return;
      }
      window.history.pushState(null, "", href);
      setPath(target.pathname);
      say("");
      window.scrollTo(0, 0);
    },
    [say],
  );

  const onClock = async (control: ClockControl) => {
    if (await act(() => api.clock(control))) await readNow();
  };

  const onNewDay = async (request: NewDay) => {
    if (await act(() => api.newDay(request))) await readNow();
  };

  const onDay = async (settings: DaySettings) => {
    if (await act(() => api.daySettings(settings))) await readNow();
  };

  const onPhones = async (changes: PlacePhone[]) => {
    for (const change of changes) {
      if (!(await act(() => api.setPhone(change)))) break;
    }
    await readPhones();
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
    await hubState.logOut();
    navigate("/");
  };

  const bottom = isDrift(page) ? { label: "Drift", items: DRIFT_TABS.map(([label, href]) => ({ label, href, current: href === ADDRESS[page] })) } : undefined;

  return (
    <>
      <Sidhuvud {...hubState.header({ current: ADDRESS[page], navigate, bottom })} />
      <main id="innehall" className={MAIN[page] ?? "drift"}>
        {page === "start" && (
          <StartPage
            info={info}
            version={hubState.version}
            message={hubState.message}
            navigate={navigate}
            onSetUp={(name, pin) => void act(() => hub.setUp(name, pin)).then((done) => (done ? readInfo() : undefined))}
            onLogIn={(pin) => void act(() => hub.logIn(pin)).then((done) => (done ? readInfo() : undefined))}
            onLogOut={() => void onLogOut()}
            onMessage={say}
          />
        )}
        {page === "nu" && (
          <NuPage
            admin={admin}
            now={now}
            clients={clients}
            choices={hubState.choices}
            asked={hubState.asked}
            automation={automation}
            openAutomation={window.location.hash === "#automatiken"}
            onClock={(control) => void onClock(control)}
            onNewDay={(request) => void onNewDay(request)}
            onStart={(choice, day) => void hubState.start(choice, day)}
            onPlace={(change) => void onPlace(change)}
          />
        )}
        {page === "klienter" && <KlienterPage admin={admin} now={now} clients={clients} navigate={navigate} onChange={(change) => void onClient(change)} />}
        {page === "logg" && <LoggPage admin={admin} now={now} clients={clients} navigate={navigate} onMessage={say} />}
        {page === "provbanan" && <ProvbananPage />}
        {page === "installningar" && (
          <SettingsPage admin={admin} now={now} hubName={info?.name ?? "Hubben"} version={hubState.version} automation={automation} automationSaved={automationSaved} onAutomation={(settings) => void onAutomation(settings)} onDay={(settings) => void onDay(settings)} phones={phones} onPhones={(changes) => void onPhones(changes)} />
        )}
        {(isDrift(page) || page === "installningar") && (
          <p id="message" className="meddelande" role="alert">
            {hubState.message}
          </p>
        )}
      </main>
    </>
  );
}

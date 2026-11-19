import { DRIFT_TABS, hub, Sidhuvud, useHub } from "@trainmeet/hubben";
import { useCallback, useEffect, useState } from "react";
import { api, type AiService, type AiServiceChange, type Automation, type AutomationSettings, type ChangePlace, type ClockControl, type DaySettings, type NewDay, type Package, type PlacePhone, type PlanVersion, type SwitchPreview, type SwitchVersion } from "./api";
import type { DriftChange } from "./changes";
import { SettingsPage } from "./Installningar";
import { KlienterPage, type ClientAction } from "./Klienter";
import { LoggPage } from "./Logg";
import { NuPage } from "./Nu";
import { ProvbananPage } from "./Provbanan";
import { DeltagarePage } from "./Deltagare";
import { ForarePage } from "./Forare";
import { StartPage } from "./StartPage";

// Trafikledningen (TRAFIK-21): the start page, Provbanan, Inställningar, and Nu, Klienter,
// Logg and Förare (TRAFIK-14, TRAFIK-33), under the Hub's header (@trainmeet/hubben). Automatiken is read every third second and
// the log every fifth, as the old pages did; Nu and the clients come with the header.

export type Page = "start" | "deltagare" | "nu" | "klienter" | "logg" | "forare" | "provbanan" | "installningar";

export function pageOf(path: string): Page {
  const clean = path.replace(/\/+$/, "");
  if (clean === "/drift/klienter") return "klienter";
  if (clean === "/drift/logg") return "logg";
  if (clean === "/drift/forare") return "forare";
  if (clean === "/drift" || clean.startsWith("/drift/")) return "nu";
  if (clean === "/provbanan") return "provbanan";
  if (clean === "/installningar") return "installningar";
  if (clean === "/deltagare") return "deltagare";
  return "start";
}

/** Nu, Klienter, Logg and Förare: Drift's own pages, in Kontrollrummet. */
export const isDrift = (page: Page) => page === "nu" || page === "klienter" || page === "logg" || page === "forare";

/** The addresses this app draws itself; the rest (Planering, the boxes) are other pages. */
export const isOwn = (path: string) => ["/", "/deltagare", "/provbanan", "/installningar", "/drift"].includes(path) || path.startsWith("/drift/");

const ADDRESS: Record<Page, string> = {
  start: "/",
  deltagare: "/deltagare",
  nu: "/drift",
  klienter: "/drift/klienter",
  logg: "/drift/logg",
  forare: "/drift/forare",
  provbanan: "/provbanan",
  installningar: "/installningar",
};

const MAIN: Partial<Record<Page, string>> = { start: "startsida", deltagare: "deltagare", provbanan: "provsida", installningar: "installningssida" };

export function App() {
  const [path, setPath] = useState(() => window.location.pathname);
  const page = pageOf(path);
  const hubState = useHub();
  const { admin, owner, now, clients, info, act, say, readInfo, readNow, readClients } = hubState;
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

  // The package Drift goes by, for Ny driftändring and Logg's words: read again when a change
  // is made or let go (TRAFIK-02).
  const [pkg, setPkg] = useState<Package | null>(null);
  const changeCount = now?.changes?.length ?? 0;
  const changeState = (now?.changes ?? []).map((change) => change.status).join();
  useEffect(() => {
    if (!admin || (page !== "nu" && page !== "logg") || !running) return setPkg(null);
    void api.package().then(setPkg, () => setPkg(null));
  }, [admin, page, running, changeCount, changeState]);

  // Egen AI (H58) under Den här hubben: read under the gear, by the administrator only.
  const [ai, setAi] = useState<AiService | null | undefined>(undefined);
  const readAi = useCallback(async () => {
    try {
      setAi(await hub.ai());
    } catch {
      setAi(null);
    }
  }, []);
  useEffect(() => {
    if (!owner || page !== "installningar") return setAi(undefined);
    void readAi();
  }, [owner, page, readAi]);
  const onAi = async (change: AiServiceChange) => {
    const kept = await act(() => hub.connectAi(change));
    if (kept) say("AI-tjänsten är inkopplad. Modellen läste provbilden.");
    await readAi();
    return kept;
  };
  const onRename = async (name: string) => {
    const kept = await act(() => hub.rename(name));
    if (kept) say(`Hubben heter nu ${name}.`);
    await readInfo();
    return kept;
  };
  const onPin = async (pin: string, newPin: string) => {
    const changed = await act(() => hub.changePin(pin, newPin));
    if (changed) say("PIN-koden är bytt. Alla andra inloggningar har slutat gälla.");
    return changed;
  };
  const onAiOff = async () => {
    if (await act(() => hub.disconnectAi())) say("AI-tjänsten är bortkopplad, och nyckeln är borta ur hubben.");
    await readAi();
  };

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

  // Versionsbyte (TRAFIK-03): the running meet's versions from Planering, and the preview of a
  // switch before it is made.
  const [versions, setVersions] = useState<PlanVersion[] | null>(null);
  const [preview, setPreview] = useState<SwitchPreview | null>(null);
  const meetId = now?.meet_id;
  useEffect(() => {
    if (!admin || page !== "nu" || !meetId || meetId === "provbanan") return setVersions(null);
    const read = () => void api.versions(meetId).then(setVersions, () => setVersions(null));
    read();
    const timer = window.setInterval(read, 15000);
    return () => window.clearInterval(timer);
  }, [admin, page, meetId]);
  const onPreview = async (version: number | null) => {
    if (version === null) return setPreview(null);
    await act(async () => setPreview(await api.switchPreview(version)));
  };
  const onSwitch = async (request: SwitchVersion) => {
    if (await act(() => api.switchVersion(request))) {
      setPreview(null);
      await readNow();
    }
  };
  const onForceSwitch = async () => {
    if (await act(() => api.forceSwitch())) await readNow();
  };
  const onCallOff = async () => {
    if (await act(() => api.callOffSwitch())) await readNow();
  };
  const onUnlock = async () => {
    if (await act(() => api.unlock())) await readNow();
  };
  const onTakeOver = async (confirm: string) => {
    if (await act(() => api.takeOver(confirm))) await readNow();
  };

  const onChange = async (change: DriftChange) => {
    if (await act(() => api.makeChange({ change, force: false }))) await readNow();
  };
  const onDrop = async (id: string) => {
    if (await act(() => api.dropChange(id))) await readNow();
  };
  const onForce = async (id: string) => {
    if (await act(() => api.forceChange(id))) await readNow();
  };

  const onClient = async (change: ClientAction) => {
    const sent = await act(() => {
      switch (change.action) {
        case "assign":
          return api.assign({ client_id: change.client_id, places: change.places, side: change.side, language: change.language as never });
        case "approve":
          return api.approve({ client_id: change.client_id, places: change.places });
        case "refuse":
          return api.refuse({ client_id: change.client_id, places: change.places });
        case "revoke":
          return api.revoke({ client_id: change.client_id });
        case "view":
          return api.view({ client_id: change.client_id, view: change.view as never });
        case "exit":
          return api.coupleExit({ client_id: change.client_id, section: change.section, exit: change.exit });
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
        {/* Deltagarna (DELT-01, S1): what everyone sees without logging in, on / and on /deltagare. */}
        {(page === "deltagare" || (page === "start" && info?.set_up && !info.logged_in)) && (
          <DeltagarePage
            now={now}
            elapsedMs={hubState.elapsedMs}
            message={hubState.message}
            onLogIn={(pin) => void act(() => hub.logIn(pin)).then((done) => (done ? readInfo() : undefined))}
            onLogInWithCode={(code) => void act(() => hub.logInWithCode(code)).then((done) => (done ? readInfo() : undefined))}
            idLogin={info?.id_login ?? false}
            ticketName={info?.ticket_name ?? null}
            onLogInAgain={() => void act(() => hub.logInAgain()).then((done) => (done ? readInfo() : undefined))}
          />
        )}
        {page === "start" && !(info?.set_up && !info.logged_in) && (
          <StartPage
            info={info}
            version={hubState.version}
            message={hubState.message}
            navigate={navigate}
            onSetUp={(name, pin) => void act(() => hub.setUp(name, pin)).then((done) => (done ? readInfo() : undefined))}
            onLogIn={(pin) => void act(() => hub.logIn(pin)).then((done) => (done ? readInfo() : undefined))}
            onLogInWithCode={(code) => void act(() => hub.logInWithCode(code)).then((done) => (done ? readInfo() : undefined))}
            onLogInAgain={() => void act(() => hub.logInAgain()).then((done) => (done ? readInfo() : undefined))}
            onLogOut={() => void onLogOut()}
            onMessage={say}
          />
        )}
        {page === "nu" && (
          <NuPage
            admin={admin}
            owner={owner}
            now={now}
            clients={clients}
            choices={hubState.choices}
            asked={hubState.asked}
            automation={automation}
            openAutomation={window.location.hash === "#automatiken"}
            onClock={(control) => void onClock(control)}
            onNewDay={(request) => void onNewDay(request)}
            pkg={pkg}
            onChange={(change) => void onChange(change)}
            onDrop={(id) => void onDrop(id)}
            onForce={(id) => void onForce(id)}
            switching={{
              versions,
              preview,
              onPreview: (version) => void onPreview(version),
              onSwitch: (request) => void onSwitch(request),
              onForce: () => void onForceSwitch(),
              onCallOff: () => void onCallOff(),
            }}
            onUnlock={() => void onUnlock()}
            onTakeOver={(confirm) => void onTakeOver(confirm)}
            onStart={(choice, day) => void hubState.start(choice, day)}
            onPlace={(change) => void onPlace(change)}
          />
        )}
        {page === "klienter" && <KlienterPage admin={admin} now={now} clients={clients} navigate={navigate} onChange={(change) => void onClient(change)} onMessage={say} />}
        {page === "logg" && <LoggPage admin={admin} now={now} pkg={pkg} clients={clients} navigate={navigate} onMessage={say} />}
        {page === "forare" && <ForarePage loggedIn={info?.logged_in ?? false} now={now} navigate={navigate} onMessage={say} />}
        {page === "provbanan" && <ProvbananPage />}
        {page === "installningar" && (
          <SettingsPage admin={admin} owner={owner} now={now} hubName={info?.name ?? "Hubben"} version={hubState.version} automation={automation} automationSaved={automationSaved} onAutomation={(settings) => void onAutomation(settings)} onDay={(settings) => void onDay(settings)} phones={phones} onPhones={(changes) => void onPhones(changes)} ai={ai} onAi={onAi} onAiOff={() => void onAiOff()} onRename={onRename} onPin={onPin} />
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

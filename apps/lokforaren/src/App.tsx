import { BottomNav, Header, type NavItem } from "@trainmeet/design";
import { useEffect, useState, useSyncExternalStore } from "react";
import { clockText } from "./clock";
import { ForareTab } from "./Forare";
import { Instruktioner, JagTab } from "./Jag";
import { IngenTraff, Kom } from "./Kom";
import { KorplanTab, Sheets } from "./Korplan";
import { BASE, Lok, routeOf, type LokState, type Route } from "./store";
import { TagTab, TjanstKort } from "./Tag";
import { TEXT } from "./text";
import { ClockPill, Icon } from "./ui";

// Lokföraren (LOK-14, LOK-36, LOK-38): an app of its own that the hub delivers at /lokforaren/,
// with the header of every TrainMeet product, the TRAINMEET sign and LOKFÖRAREN in dots, and four
// tabs: Körplan, Tåg, Förare and Jag. The yellow is the clock; the blue is Drift's reality.

const TABS: Route[] = ["korplan", "tag", "forare", "jag"];

export function tabsOf(state: LokState): NavItem[] {
  const text = TEXT[state.language];
  const current: Route = state.route === "tjanst" ? "tag" : state.route === "instruktioner" ? "jag" : state.route;
  return TABS.map((route) => ({ href: BASE + route, label: text.tabs[route as keyof typeof text.tabs], current: current === route, icon: Icon[route as keyof typeof Icon] }));
}

/** The whole app for a state: what the tests draw, and what the phone shows each second. */
export function Screen({ lok, state, now }: { lok: Lok; state: LokState; now: number | null }) {
  const text = TEXT[state.language];
  const navigate = (href: string) => lok.navigate(href.slice(BASE.length) as Route);
  const mode = lok.clock.mode();
  const inApp = state.phase === "app";
  return (
    <div className={`lok${inApp ? " med-flikar" : ""}`}>
      <a className="tm-hoppa" href="#innehall">
        {text.skip}
      </a>
      <Header product="LOKFÖRAREN" productLabel="Lokföraren" place={state.meetName ?? ""} home={BASE} navLabel={text.tabsLabel} tabs={inApp ? tabsOf(state) : []} navigate={inApp ? navigate : undefined}>
        {inApp && (
          <span className="lok-klocka" aria-label={text.clockLabel}>
            <span className={`tm-mono${mode === "lost" ? " fryst" : ""}`}>{clockText(now)}</span>
            <ClockPill mode={mode} speed={lok.clock.speed()} text={text} />
          </span>
        )}
      </Header>
      {inApp && mode === "lost" && <p className="lok-kontakt" role="alert">{text.lostNote}</p>}
      {state.notice && (
        <div className="lok-notis" role="status">
          {Icon.bell}
          <span>{state.notice}</span>
          <button type="button" className="lok-lank" onClick={() => lok.dismiss()}>
            {text.close}
          </button>
        </div>
      )}
      {state.phase === "loading" && <main className="lok-sida" id="innehall" aria-busy="true" />}
      {state.phase === "nomeet" && <IngenTraff lok={lok} state={state} />}
      {state.phase === "join" && <Kom lok={lok} state={state} now={now} />}
      {inApp && state.route === "korplan" && <KorplanTab lok={lok} state={state} now={now} />}
      {inApp && state.route === "tag" && <TagTab lok={lok} state={state} now={now} />}
      {inApp && state.route === "tjanst" && <TjanstKort lok={lok} state={state} now={now} />}
      {inApp && state.route === "forare" && <ForareTab lok={lok} state={state} />}
      {inApp && state.route === "jag" && <JagTab lok={lok} state={state} />}
      {inApp && state.route === "instruktioner" && <Instruktioner lok={lok} state={state} instructions={state.instructions} />}
      {inApp && <Sheets lok={lok} state={state} now={now} />}
      {inApp && <BottomNav items={tabsOf(state)} label={text.tabsLabel} navigate={navigate} />}
    </div>
  );
}

/** The app in the phone: the store, the address, the theme, and a tick each second. */
export function App({ lok }: { lok: Lok }) {
  const state = useSyncExternalStore(lok.subscribe, lok.getState);
  const [, setTick] = useState(0);

  useEffect(() => {
    lok.readCode(location.hash);
    if (/kod=/.test(location.hash)) history.replaceState(null, "", location.pathname);
    void lok.start(routeOf(location.pathname)).then(() => lok.startLoops());
    const onPop = () => lok.follow(location.pathname);
    window.addEventListener("popstate", onPop);
    const timer = setInterval(() => {
      lok.tick();
      setTick((value) => value + 1);
    }, 1000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void lok.again();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("popstate", onPop);
      document.removeEventListener("visibilitychange", onVisible);
      clearInterval(timer);
      lok.stopLoops();
    };
  }, [lok]);

  useEffect(() => {
    if (state.phase !== "app") return;
    if (state.route === "tjanst" && !state.selected && !state.me?.service) lok.navigate("tag", true);
    if (state.route === "tag") void lok.loadServices();
    if (state.route === "forare") void lok.loadPresence();
    if (state.route === "instruktioner" && !state.instructions) void lok.loadInstructions();
  }, [lok, state.phase, state.route, state.instructions, state.selected, state.me?.service]);

  useEffect(() => {
    const root = document.documentElement;
    if (state.theme === "auto") delete root.dataset.tema;
    else root.dataset.tema = state.theme;
    root.lang = state.language;
  }, [state.theme, state.language]);

  return <Screen lok={lok} state={state} now={lok.clock.seconds()} />;
}

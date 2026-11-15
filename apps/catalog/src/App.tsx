import { AccountMenu, AppSwitcher, BottomNav, Header, linkClick, type App as SwitcherApp, type Navigate } from "@trainmeet/design";
import { useCallback, useEffect, useRef, useState, type ReactElement } from "react";
import { api, idLoginHref, workIn, type Account, type AppKey, type CatalogVersion, type FleetChoice, type Session } from "./api";
import { storeLanguage, text, type Language, type TextKey } from "./i18n";
import { MeetsIcon, TapIcon, VehiclesIcon } from "./icons";
import type { Ctx } from "./common";
import { LendPage } from "./LendPage";
import { PlacesPage } from "./PlacesPage";
import { TagPage } from "./TagPage";
import { TapPage } from "./TapPage";
import { nextAfterLogin, PATHS, routeFor, tabOf, type Page, type Route } from "./routes";
import { VehicleCardPage } from "./VehicleCard";
import { VehicleFormPage } from "./VehicleForm";
import { VehiclesPage } from "./VehiclesPage";

export type T = (key: TextKey, vars?: Record<string, string | number>) => string;

/** The other TrainMeet apps. Only the Hub has a test environment so far. */
const PRODUCTS: Record<AppKey, string> = { hub: "HUB", tkl: "TKL", cad: "CAD", catalog: "CATALOG", driver: "LOKFÖRAREN", id: "ID" };

/** With the person's apps from ID, only those they have something in (KONTO-38, ID11). */
export function switcherApps(t: T, host: string, apps?: AppKey[] | null): SwitcherApp[] {
  const all = everyApp(t, host);
  if (!apps?.length) return all;
  const shown = new Set(apps.map((app) => PRODUCTS[app]));
  return all.filter((app) => shown.has(app.product));
}

/** Hjälp och fel is TrainMeet ID's page, with this app, the page and the version (KONTO-06). */
export function helpHref(helpUrl: string, path: string, version: CatalogVersion | null | undefined): string {
  const built = version ? [version.version, version.commit?.slice(0, 7)].filter(Boolean).join(" · ") : "";
  return `${helpUrl}?${new URLSearchParams({ app: "catalog", sida: path, version: built })}`;
}

function everyApp(t: T, host: string): SwitcherApp[] {
  const test = host.startsWith("test.") || host.startsWith("localhost") || host.startsWith("127.");
  return [
    { product: "HUB", label: "TrainMeet Hub", what: t("appHub"), href: test ? "https://test.hub.trainmeet.app" : undefined },
    { product: "TKL", label: "TrainMeet TKL", what: t("appTkl") },
    { product: "CAD", label: "TrainMeet CAD", what: t("appCad") },
    { product: "CATALOG", label: "TrainMeet Catalog", what: t("appCatalog") },
    { product: "TMBOX", label: "TMBox", what: t("appTmbox") },
    { product: "LOKFÖRAREN", label: "Lokföraren", what: t("appDriver") },
    { product: "ID", label: "TrainMeet ID", what: t("appId"), href: test ? "https://test.id.trainmeet.app" : undefined },
  ];
}

const TITLES: Record<Page, TextKey> = {
  vehicles: "vehicles",
  newVehicle: "newTitle",
  vehicle: "cardEyebrow",
  editVehicle: "edit",
  lend: "lendTitle",
  places: "places",
  meets: "meets",
  prototypes: "prototypes",
  tap: "tapTitle",
  login: "logIn",
  help: "help",
  tag: "tagTitle",
  missing: "notFound",
};

export type ShellProps = {
  page: Page;
  id?: string;
  language: Language;
  host: string;
  session: Session | null;
  version: CatalogVersion | null;
  offline: boolean;
  navigate?: Navigate;
  replace?: Navigate;
  onLanguage?: () => void;
  onLogOut?: () => void;
  onLogIn?: (account: Account) => Promise<boolean>;
  trialAccounts?: Account[] | null;
  /** The address's query, for the login page: ?next= and ?inloggning=fel. */
  search?: string;
  /** The page's address, for Hjälp och fel (KONTO-06). */
  path?: string;
  /** False shows the empty fleet without fetching (tests of the shell). */
  fleet?: boolean;
  /** The fleets the person can work in: their own first, then the shared ones (CAT-50). */
  fleets?: FleetChoice[] | null;
  /** The fleet the person works in now: null for their own (#49). */
  working?: string | null;
  /** Work in another fleet, on the same page (a tag in it was tapped). */
  onWorkIn?: (owner: string | null) => void;
  /** Choose a fleet in the picker: its list opens. */
  onChooseFleet?: (owner: string | null) => void;
};

/** The fleet worked in now, if it is someone else's: shared with the person, or a club's. */
function otherFleet(props: ShellProps): FleetChoice | null {
  if (!props.working) return null;
  return props.fleets?.find((f) => f.owner === props.working) ?? null;
}

/** Everything on the screen, from the state. No fetching here, so it can be rendered in tests. */
export function Shell(props: ShellProps) {
  const { page, language, host, session, version, offline, navigate } = props;
  const t: T = (key, vars) => text(language, key, vars);
  const account = session?.account ?? null;
  const tab = (target: keyof typeof PATHS, label: TextKey, icon?: ReactElement) => ({
    href: PATHS[target],
    label: t(label),
    current: tabOf(page) === target,
    icon,
  });

  return (
    <>
      <a className="tm-hoppa" href="#innehall">
        {t("skip")}
      </a>
      <Header
        product="CATALOG"
        productLabel={t("product")}
        place={host}
        home={PATHS.vehicles}
        navLabel={t("mainNav")}
        tabs={[tab("vehicles", "vehicles"), tab("meets", "meets"), tab("prototypes", "prototypes")]}
        navigate={navigate}
      >
        <AppSwitcher
          apps={switcherApps(t, host, session?.apps)}
          current="CATALOG"
          title={t("switcher")}
          sameAccount={t("sameAccount")}
          buttonLabel={t("switcherButton")}
          comingLabel={t("coming")}
        />
        {account ? (
          <AccountMenu
            name={account.name}
            initials={account.initials}
            detail={session?.login === "trial" ? t("trialDetail") : t("idDetail")}
            buttonLabel={t("accountButton", { name: account.name })}
          >
            {(close) => (
              <>
                {session?.help_url ? (
                  <a href={helpHref(session.help_url, props.path ?? PATHS.vehicles, props.version)}>{t("help")}</a>
                ) : (
                  <a
                    href={PATHS.help}
                    onClick={(event) => {
                      linkClick(navigate, PATHS.help)(event);
                      close();
                    }}
                  >
                    {t("help")}
                  </a>
                )}
                <button
                  type="button"
                  className="neutral"
                  onClick={() => {
                    close();
                    props.onLogOut?.();
                  }}
                >
                  {t("logOut")}
                </button>
              </>
            )}
          </AccountMenu>
        ) : (
          <a className="tm-knapp" href={PATHS.login} onClick={linkClick(navigate, PATHS.login)}>
            {t("logIn")}
          </a>
        )}
      </Header>

      <main id="innehall" className="cat-sida" tabIndex={-1}>
        {offline ? (
          <p className="tm-kort" role="alert">
            {t("offline")}
          </p>
        ) : session === null ? (
          <p className="cat-laddar">{t("loading")}</p>
        ) : (
          <>
            {otherFleet(props) ? (
              <p className="tm-kort cat-annans" role="status">
                <span>{t("inFleet", { title: otherFleet(props)?.title ?? "" })}</span>
                <button type="button" className="tm-knapp" onClick={() => props.onWorkIn?.(null)}>
                  {t("toOwnFleet")}
                </button>
              </p>
            ) : null}
            <PageContent {...props} t={t} account={account} />
          </>
        )}
      </main>

      <footer className="cat-fot">
        <span>
          {t("product")} · {t("version", { version: version?.version ?? "…" })}
          {version?.pr ? (
            <>
              {" · "}
              <a href={`https://github.com/beahead-ab/trainmeet/pull/${version.pr}`}>{t("change", { pr: version.pr })}</a>
            </>
          ) : version && !version.commit ? (
            ` · ${t("localBuild")}`
          ) : null}
          {version?.commit ? <span className="tm-mono"> · {version.commit.slice(0, 7)}</span> : null}
        </span>
        <button type="button" className="cat-sprak" lang={language === "sv" ? "en" : "sv"} aria-label={t("otherLanguageLabel")} onClick={props.onLanguage}>
          {t("otherLanguage")}
        </button>
      </footer>

      <BottomNav
        label={t("phoneNav")}
        items={[tab("vehicles", "vehicles", <VehiclesIcon />), tab("tap", "tap", <TapIcon />), tab("meets", "meets", <MeetsIcon />)]}
        navigate={navigate}
      />
    </>
  );
}

/** One fleet at a time (CAT-50): the person's own, or one shared with them. */
function FleetPicker(props: ShellProps & { t: T }) {
  const { t, fleets } = props;
  if (!fleets || fleets.length < 2) return null;
  return (
    <div className="cat-vagnparksval">
      <label htmlFor="vagnpark">{t("chooseFleet")}</label>
      <select id="vagnpark" value={props.working ?? fleets[0]?.owner ?? ""} onChange={(event) => props.onChooseFleet?.(event.target.value === fleets[0]?.owner ? null : event.target.value)}>
        {fleets.map((choice) => (
          <option key={choice.owner} value={choice.owner}>
            {choice.title}
          </option>
        ))}
      </select>
    </div>
  );
}

function Empty({ title, detail }: { title: string; detail?: string }) {
  return (
    <section className="tm-kort cat-tomt">
      <p className="cat-tomt-rubrik">{title}</p>
      {detail ? <p>{detail}</p> : null}
    </section>
  );
}

function PageContent(props: ShellProps & { t: T; account: Account | null }) {
  const { page, t, account, navigate, id, language } = props;
  const loginLink = (
    <a className="tm-knapp primar" href={PATHS.login} onClick={linkClick(navigate, PATHS.login)}>
      {t("logIn")}
    </a>
  );
  const other = otherFleet(props);
  const ctx: Ctx = {
    t,
    language,
    navigate,
    replace: props.replace,
    // Until the fleets are known, someone else's fleet is only looked at.
    right: props.working ? (other?.right ?? "view") : "owner",
    fleetTitle: other?.title,
    shareUrl: props.working ? (other?.share_url ?? null) : (props.session?.share_url ?? null),
    workIn: props.onWorkIn,
    fleets: props.fleets,
  };
  const fleetPages: Page[] = ["newVehicle", "vehicle", "editVehicle", "lend", "places"];
  if (fleetPages.includes(page) && !account) {
    return (
      <section className="tm-kort cat-tomt">
        <p className="cat-tomt-rubrik">{t("loginForFleet")}</p>
        {loginLink}
      </section>
    );
  }
  if (page === "vehicles" && account && props.fleet !== false)
    return (
      <>
        <FleetPicker {...props} t={t} />
        <VehiclesPage key={props.working ?? "egen"} ctx={ctx} account={account} />
      </>
    );
  switch (page) {
    case "newVehicle":
      return <VehicleFormPage ctx={ctx} />;
    case "vehicle":
      return <VehicleCardPage key={id} ctx={ctx} id={id ?? ""} />;
    case "editVehicle":
      return <VehicleFormPage key={id} ctx={ctx} id={id} />;
    case "lend":
      return <LendPage ctx={ctx} id={id ?? ""} />;
    case "places":
      return <PlacesPage ctx={ctx} />;
    case "tag":
      return <TagPage key={id} ctx={ctx} uid={id ?? ""} account={account} />;
    case "vehicles":
      return (
        <>
          {account ? <p className="tm-overrubrik">{t("fleetOf", { name: account.name })}</p> : null}
          <h1>{t("vehicles")}</h1>
          {account ? (
            <Empty title={t("fleetEmpty")} detail={t("fleetEmptyDetail")} />
          ) : (
            <section className="tm-kort cat-tomt">
              <p className="cat-tomt-rubrik">{t("fleetLoggedOut")}</p>
              {loginLink}
            </section>
          )}
        </>
      );
    case "meets":
      return (
        <>
          <h1>{t("meets")}</h1>
          <Empty title={t("meetsEmpty")} detail={t("meetsEmptyDetail")} />
        </>
      );
    case "prototypes":
      return (
        <>
          <h1>{t("prototypes")}</h1>
          <Empty title={t("prototypesEmpty")} detail={t("prototypesEmptyDetail")} />
        </>
      );
    case "tap":
      return <TapPage ctx={ctx} account={account} simulated={props.session?.simulated_tags ?? false} />;
    case "help":
      return (
        <>
          <h1>{t("help")}</h1>
          {props.session?.help_url ? (
            <p>
              <a className="tm-knapp primar" href={helpHref(props.session.help_url, PATHS.help, props.version)}>
                {t("helpInId")}
              </a>
            </p>
          ) : (
            <Empty title={t("helpText")} />
          )}
        </>
      );
    case "login":
      return <LoginPage {...props} />;
    case "missing":
      return (
        <>
          <h1>{t("notFound")}</h1>
          <p>
            <a href={PATHS.vehicles} onClick={linkClick(navigate, PATHS.vehicles)}>
              {t("toVehicles")}
            </a>
          </p>
        </>
      );
  }
}

function LoginPage({ t, session, account, trialAccounts, onLogIn, search = "", language }: ShellProps & { t: T; account: Account | null }) {
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  if (session?.login !== "trial") {
    // TrainMeet ID (#66): the browser goes to ID and comes back logged in, or with ?inloggning=fel.
    const cameBackFailed = new URLSearchParams(search).get("inloggning") === "fel";
    return (
      <>
        <h1>{t("logIn")}</h1>
        <section className="tm-kort cat-inloggning">
          {cameBackFailed ? (
            <p className="cat-fel" role="alert">
              {t("loginFailed")}
            </p>
          ) : null}
          {account ? <p>{t("loggedInAs", { name: account.name })}</p> : null}
          <p>{t("loginIdIntro")}</p>
          <a className="tm-knapp primar" href={idLoginHref(nextAfterLogin(search), language)}>
            {t("loginWithId")}
          </a>
        </section>
      </>
    );
  }
  return (
    <>
      <h1>{t("logIn")}</h1>
      <section className="tm-kort">
        <p>{t("loginTrialIntro")}</p>
        {account ? <p>{t("loggedInAs", { name: account.name })}</p> : null}
        <ul className="cat-provkonton">
          {(trialAccounts ?? []).map((trial) => (
            <li key={trial.id}>
              <button
                type="button"
                className={trial.id === account?.id ? "tm-knapp primar" : "tm-knapp"}
                disabled={busy}
                aria-pressed={trial.id === account?.id}
                onClick={async () => {
                  setBusy(true);
                  setFailed(false);
                  const ok = (await onLogIn?.(trial)) ?? false;
                  setBusy(false);
                  setFailed(!ok);
                }}
              >
                <span className="tm-konto" aria-hidden="true">
                  {trial.initials}
                </span>
                {trial.name}
              </button>
            </li>
          ))}
        </ul>
        {failed ? (
          <p className="cat-fel" role="alert">
            {t("loginFailed")}
          </p>
        ) : null}
      </section>
    </>
  );
}

/** The web app: reads the version and the session, and follows the address. */
export function App({ initialLanguage }: { initialLanguage: Language }) {
  const [language, setLanguage] = useState<Language>(initialLanguage);
  const [route, setRoute] = useState<Route>(() => routeFor(window.location.pathname + window.location.search));
  const page = route.page;
  const [session, setSession] = useState<Session | null>(null);
  const [fleets, setFleets] = useState<FleetChoice[] | null>(null);
  const [working, setWorking] = useState<string | null>(null);
  const [version, setVersion] = useState<CatalogVersion | null>(null);
  const [trialAccounts, setTrialAccounts] = useState<Account[] | null>(null);
  const [offline, setOffline] = useState(false);
  const moved = useRef(false);

  const navigate = useCallback((href: string) => {
    window.history.pushState(null, "", href);
    moved.current = true;
    setRoute(routeFor(href));
  }, []);

  const replace = useCallback((href: string) => {
    window.history.replaceState(null, "", href);
    setRoute(routeFor(href));
  }, []);

  useEffect(() => {
    const onPop = () => setRoute(routeFor(window.location.pathname + window.location.search));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    Promise.all([api.version(), api.session()])
      .then(([v, s]) => {
        setVersion(v);
        setSession(s);
      })
      .catch(() => setOffline(true));
  }, []);

  useEffect(() => {
    if (page === "login" && session?.login === "trial" && trialAccounts === null) {
      api.trialAccounts().then(setTrialAccounts, () => setTrialAccounts([]));
    }
  }, [page, session, trialAccounts]);

  const workingNow = useRef<string | null>(null);
  const switchFleet = useCallback((owner: string | null) => {
    workIn(owner);
    workingNow.current = owner;
    setWorking(owner);
  }, []);

  const chooseFleet = useCallback(
    (owner: string | null) => {
      switchFleet(owner);
      navigate(PATHS.vehicles);
    },
    [navigate, switchFleet],
  );

  useEffect(() => {
    // The fleets shared with the person, from ID through Catalog (CAT-50). Without an answer
    // only the own: a fleet no longer shared is left at once (CAT-48).
    const keep = (found: FleetChoice[] | null) => {
      setFleets(found);
      const now = workingNow.current;
      if (now && !found?.some((f) => f.owner === now)) switchFleet(null);
    };
    if (session?.account) api.fleets().then(keep, () => keep(null));
    else setFleets(null);
  }, [session, switchFleet]);

  useEffect(() => {
    document.documentElement.lang = language;
    document.title = `${text(language, TITLES[page])} · TrainMeet Catalog`;
  }, [language, page]);

  useEffect(() => {
    // After moving to another page, the screen reader starts at its heading (WCAG 2.4.3).
    if (moved.current) document.querySelector<HTMLElement>("#innehall")?.focus();
  }, [route]);

  return (
    <Shell
      page={page}
      id={route.id}
      language={language}
      host={window.location.host}
      session={session}
      version={version}
      offline={offline}
      navigate={navigate}
      replace={replace}
      trialAccounts={trialAccounts}
      search={window.location.search}
      path={window.location.pathname}
      fleets={fleets}
      working={working}
      onWorkIn={switchFleet}
      onChooseFleet={chooseFleet}
      onLanguage={() => {
        const next: Language = language === "sv" ? "en" : "sv";
        setLanguage(next);
        storeLanguage(next);
      }}
      onLogOut={() => {
        api.logOut().then((after) => {
          // Logged in with ID: ID logs out too, and sends the browser back here (KONTO-01).
          if (after.logout_url) window.location.assign(after.logout_url);
          else setSession(after);
        }, () => setOffline(true));
      }}
      onLogIn={async (account) => {
        try {
          setSession(await api.trialLogIn({ account: account.id }));
          navigate(nextAfterLogin(window.location.search));
          return true;
        } catch {
          return false;
        }
      }}
    />
  );
}

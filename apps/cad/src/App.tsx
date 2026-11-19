// TrainMeet CAD's web app: the header and the pages from the state (Shell), and the state from
// CAD's API (App). Shell fetches nothing, so the tests can render it.
import { AccountMenu, AppSwitcher, Header, linkClick, type App as SwitcherApp, type Navigate } from "@trainmeet/design";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  idLoginHref,
  SCALES,
  type Account,
  type AppKey,
  type CadVersion,
  type Library,
  type Module,
  type ModuleChange,
  type ModuleEvent,
  type ModuleList,
  type NewModule,
  type NewProfile,
  type ProfileList,
  type Scale,
  type Session,
  type Visibility,
} from "./api";
import { LibraryPage } from "./Library";
import { ModuleForm, type Owner } from "./ModuleForm";
import { ModulePage } from "./ModulePage";
import { NewModulePage } from "./NewModule";
import { ProfilesPage } from "./Profiles";
import { modulePath, PATHS, routeFor, tabOf, type Route } from "./routes";

const PRODUCTS: Record<AppKey, string> = { hub: "HUB", tkl: "TKL", cad: "CAD", catalog: "CATALOG", driver: "LOKFÖRAREN", id: "ID" };

/** Every TrainMeet app, with the test environment's addresses where it runs there. */
export function switcherApps(host: string, apps?: AppKey[] | null): SwitcherApp[] {
  const test = host.startsWith("test.") || host.startsWith("localhost") || host.startsWith("127.");
  const at = (name: string) => (test ? `https://test.${name}.trainmeet.app` : undefined);
  const all: SwitcherApp[] = [
    { product: "HUB", label: "TrainMeet Hub", what: "Träffen: planering och drift", href: at("hub") },
    { product: "TKL", label: "TrainMeet TKL", what: "Ställverket och Studio", href: at("tkl") },
    { product: "CAD", label: "TrainMeet CAD", what: "Modulbiblioteket" },
    { product: "CATALOG", label: "TrainMeet Catalog", what: "Fordonen och resan till träffen", href: at("catalog") },
    { product: "LOKFÖRAREN", label: "Lokföraren", what: "Köruppdraget i telefonen" },
    { product: "ID", label: "TrainMeet ID", what: "Konto, klubbar och tokens", href: at("id") },
  ];
  if (!apps?.length) return all;
  const shown = new Set([...apps.map((app) => PRODUCTS[app]), "CAD"]);
  return all.filter((app) => shown.has(app.product));
}

export type ShellProps = {
  route: Route;
  host: string;
  session: Session | null;
  version: CadVersion | null;
  libraries?: Library[];
  library?: string;
  scale?: Scale;
  list?: ModuleList | null;
  module?: Module | null;
  history?: ModuleEvent[];
  profiles?: ProfileList | null;
  trialAccounts?: Account[] | null;
  /** The address's query: ?next= and ?inloggning=fel on the login page. */
  search?: string;
  error?: string | null;
  navigate?: Navigate;
  onLibrary?: (library: string) => void;
  onScale?: (scale: Scale) => void;
  onLogIn?: (account: Account) => void;
  onLogOut?: () => void;
  onSearch?: (q: string) => void;
  onCreate?: (body: NewModule) => Promise<void>;
  onSave?: (body: ModuleChange) => Promise<void>;
  onApprove?: () => void;
  onVisibility?: (visibility: Visibility, club: string | null) => void;
  onRemove?: () => void;
  onNewProfile?: (body: NewProfile) => Promise<void>;
  now?: Date;
};

function Place({ libraries, library, scale, onLibrary, onScale }: Pick<ShellProps, "libraries" | "library" | "scale" | "onLibrary" | "onScale">) {
  const current = libraries?.find((l) => l.id === library);
  return (
    <span className="cad-bibliotek">
      {libraries && libraries.length > 1 ? (
        <label>
          <span className="cad-dold">Bibliotek</span>
          <select value={library} onChange={(event) => onLibrary?.(event.currentTarget.value)}>
            {libraries.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <b>{current?.name ?? "Mitt modulbibliotek"}</b>
      )}
      <label>
        <span className="cad-dold">Skala</span>
        <select className="cad-skala" value={scale} onChange={(event) => onScale?.(event.currentTarget.value as Scale)}>
          {SCALES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
    </span>
  );
}

function LoginPage({ session, trialAccounts, search = "", onLogIn }: Pick<ShellProps, "session" | "trialAccounts" | "search" | "onLogIn">) {
  const query = new URLSearchParams(search);
  const next = query.get("next") ?? PATHS.library;
  const safe = next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/api/") ? next : PATHS.library;
  return (
    <section className="cad-sida cad-inloggning" aria-labelledby="rubrik">
      <div className="cad-kort">
        <h1 id="rubrik">Logga in i TrainMeet CAD</h1>
        <p className="cad-ingress">Modulbiblioteket hör till ditt konto i TrainMeet ID, samma konto som i de andra apparna.</p>
        {query.get("inloggning") === "fel" ? (
          <p className="cad-fel" role="alert">
            Inloggningen gick inte. Försök igen.
          </p>
        ) : null}
        {session?.login === "trial" ? (
          <>
            <h2>Välj ett provkonto</h2>
            <p className="cad-dampad">Provinloggning i testmiljön. Provkontona är gemensamma för alla som provar.</p>
            <div className="cad-knapprad">
              {(trialAccounts ?? []).map((account) => (
                <button key={account.id} type="button" className="tm-knapp" onClick={() => onLogIn?.(account)}>
                  {account.name}
                </button>
              ))}
            </div>
          </>
        ) : (
          <a className="tm-knapp primar" href={idLoginHref(safe)}>
            Logga in med TrainMeet ID
          </a>
        )}
      </div>
    </section>
  );
}

function AssembliesPage() {
  return (
    <section className="cad-sida" aria-labelledby="rubrik">
      <h1 id="rubrik">Anläggningar</h1>
      <div className="cad-kort cad-kommer">
        <h2>Anläggningarna kommer i nästa steg</h2>
        <p>
          Här sätter du ihop moduler till en anläggning: skarvarna kontrolleras, vinkeln sätts per modul och modulversionerna låses.
          Anläggningen går sedan vidare till TKL Studio, till träffplaneringen i Hubben eller som DXF. Kommer i del d av CAD.
        </p>
      </div>
    </section>
  );
}

function owners(session: Session | null): Owner[] {
  if (!session?.account) return [];
  return [{ id: "", name: `Jag, ${session.account.name}` }, ...(session.clubs ?? []).filter((c) => c.admin).map((c) => ({ id: c.id, name: c.name }))];
}

function Page(props: ShellProps) {
  const { route, session, navigate } = props;
  if (route.page === "login" || !session?.account) return <LoginPage {...props} />;
  if (route.page === "missing") {
    return (
      <section className="cad-sida">
        <h1>Sidan finns inte</h1>
        <a href={PATHS.library} onClick={linkClick(navigate, PATHS.library)}>
          Till modulerna
        </a>
      </section>
    );
  }
  if (route.page === "library") {
    return props.list ? <LibraryPage list={props.list} navigate={navigate} onSearch={props.onSearch} now={props.now} /> : <p className="cad-sida">Hämtar modulerna …</p>;
  }
  if (route.page === "new") return <NewModulePage tokens={session.tokens} navigate={navigate} />;
  if (route.page === "form") {
    if (route.id && props.module?.id !== route.id) return <p className="cad-sida">Hämtar modulen …</p>;
    if (!props.profiles) return <p className="cad-sida">Hämtar gavelprofilerna …</p>;
    const club = props.library?.startsWith("club:") ? props.library.slice(5) : "";
    const owner = (session.clubs ?? []).some((c) => c.id === club && c.admin) ? club : "";
    return (
      <ModuleForm
        key={`${route.kind}-${route.id ?? "ny"}`}
        kind={route.kind}
        scale={props.scale ?? "H0"}
        profiles={props.profiles}
        module={route.id ? props.module : null}
        owners={owners(session)}
        owner={owner}
        navigate={navigate}
        onCreate={props.onCreate}
        onSave={props.onSave}
        onScale={props.onScale}
        onCancel={() => navigate?.(route.id ? modulePath(route.id) : PATHS.new)}
      />
    );
  }
  if (route.page === "module") {
    if (props.module?.id !== route.id) return <p className="cad-sida">Hämtar modulen …</p>;
    return (
      <ModulePage
        module={props.module}
        history={props.history ?? []}
        tab={route.tab}
        clubs={session.clubs ?? []}
        navigate={navigate}
        onApprove={props.onApprove}
        onVisibility={props.onVisibility}
        onRemove={props.onRemove}
        error={props.error}
      />
    );
  }
  if (route.page === "profiles") {
    return props.profiles ? <ProfilesPage list={props.profiles} clubs={session.clubs ?? []} onCreate={props.onNewProfile} /> : <p className="cad-sida">Hämtar gavelprofilerna …</p>;
  }
  return <AssembliesPage />;
}

/** Everything on the screen, from the state. */
export function Shell(props: ShellProps) {
  const { route, host, session, version, navigate } = props;
  const account = session?.account ?? null;
  const current = tabOf(route);
  const tab = (href: string, label: string, key: typeof current) => ({ href, label, current: current === key });
  return (
    <>
      <a className="tm-hoppa" href="#innehall">
        Hoppa till innehållet
      </a>
      <Header
        product="CAD"
        productLabel="TrainMeet CAD"
        place={account ? <Place {...props} /> : "Modulbiblioteket"}
        home={PATHS.library}
        navLabel="CAD"
        tabs={[tab(PATHS.library, "Moduler", "library"), tab(PATHS.assemblies, "Anläggningar", "assemblies"), tab(PATHS.profiles, "Gavelprofiler", "profiles")]}
        navigate={navigate}
      >
        {account && session?.tokens != null ? (
          session.tokens_url ? (
            <a className="cad-saldo" href={session.tokens_url}>
              ◎ {session.tokens} tokens
            </a>
          ) : (
            <span className="cad-saldo">◎ {session.tokens} tokens</span>
          )
        ) : null}
        <AppSwitcher
          apps={switcherApps(host, session?.apps)}
          current="CAD"
          title="TrainMeets appar"
          sameAccount="Samma konto i alla"
          buttonLabel="Byt app"
          comingLabel="Kommer"
        />
        {account ? (
          <AccountMenu
            name={account.name}
            initials={account.initials}
            detail={session?.login === "trial" ? "Provinloggning i testmiljön" : "Inloggad med TrainMeet ID"}
            buttonLabel={`Kontomenyn, ${account.name}`}
          >
            {(close) => (
              <>
                {session?.tokens_url ? <a href={session.tokens_url}>Tokens</a> : null}
                {session?.help_url ? <a href={`${session.help_url}?${new URLSearchParams({ app: "cad", version: version?.version ?? "" })}`}>Hjälp och fel</a> : null}
                <button
                  type="button"
                  className="neutral"
                  onClick={() => {
                    close();
                    props.onLogOut?.();
                  }}
                >
                  Logga ut
                </button>
              </>
            )}
          </AccountMenu>
        ) : (
          <a className="tm-knapp" href={PATHS.login} onClick={linkClick(navigate, PATHS.login)}>
            Logga in
          </a>
        )}
      </Header>
      <main id="innehall">
        <Page {...props} />
      </main>
      <footer className="cad-fot">
        TrainMeet CAD · Version {version?.version ?? "–"}
        {version?.commit ? <span className="tm-mono"> · {version.commit.slice(0, 7)}</span> : null}
        {version?.pr ? (
          <>
            {" "}
            · <a href={`https://github.com/beahead-ab/trainmeet/pull/${version.pr}`}>#{version.pr}</a>
          </>
        ) : null}
      </footer>
    </>
  );
}

function stored(key: string, fallback: string): string {
  try {
    return window.localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function keep(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // A browser without storage starts from the default next time.
  }
}

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : "Något gick fel. Försök igen.";
}

/** The app: the state from CAD's API. */
export function App() {
  const [route, setRoute] = useState<Route>(() => routeFor(window.location.pathname, window.location.search));
  const [search, setSearch] = useState(window.location.search);
  const [session, setSession] = useState<Session | null>(null);
  const [version, setVersion] = useState<CadVersion | null>(null);
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [library, setLibrary] = useState(() => stored("cad.bibliotek", "mine"));
  const [scale, setScale] = useState<Scale>(() => stored("cad.skala", "H0") as Scale);
  const [list, setList] = useState<ModuleList | null>(null);
  const [module, setModule] = useState<Module | null>(null);
  const [history, setHistory] = useState<ModuleEvent[]>([]);
  const [profiles, setProfiles] = useState<ProfileList | null>(null);
  const [trialAccounts, setTrialAccounts] = useState<Account[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const query = useRef("");

  const navigate = useCallback((href: string) => {
    window.history.pushState(null, "", href);
    const url = new URL(href, window.location.origin);
    setRoute(routeFor(url.pathname, url.search));
    setSearch(url.search);
    setError(null);
    window.scrollTo(0, 0);
  }, []);

  useEffect(() => {
    const back = () => {
      setRoute(routeFor(window.location.pathname, window.location.search));
      setSearch(window.location.search);
    };
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, []);

  useEffect(() => {
    api.version().then(setVersion, () => setVersion(null));
    api.session().then(setSession, () => setSession(null));
  }, []);

  const account = session?.account?.id;
  useEffect(() => {
    if (session && !session.account && session.login === "trial") api.trialAccounts().then(setTrialAccounts, () => setTrialAccounts([]));
  }, [session]);

  useEffect(() => {
    if (!account) return;
    api.libraries().then(
      (found) => {
        setLibraries(found);
        if (!found.some((l) => l.id === library)) setLibrary("mine");
      },
      () => setLibraries([]),
    );
  }, [account, library]);

  const loadList = useCallback(() => {
    if (!account) return;
    api.modules(library, scale, query.current).then(setList, (failure: unknown) => {
      setError(message(failure));
      if (failure instanceof ApiError && failure.status === 404) setLibrary("mine");
    });
  }, [account, library, scale]);

  useEffect(() => {
    if (route.page === "library") loadList();
  }, [route, loadList]);

  useEffect(() => {
    if (!account) return;
    // The profiles page counts the gables now, so it never shows the counts from before.
    if (route.page === "profiles") setProfiles(null);
    if (route.page === "profiles" || route.page === "form") api.profiles(scale).then(setProfiles, (failure: unknown) => setError(message(failure)));
  }, [account, route, scale]);

  const moduleId = route.page === "module" || route.page === "form" ? (route.id ?? null) : null;
  const moduleVersion = route.page === "module" ? route.version : undefined;
  useEffect(() => {
    if (!account || !moduleId) return;
    api.module(moduleId, moduleVersion).then(
      (found) => {
        setModule(found);
        if (route.page === "form") {
          setScale(found.scale);
        }
      },
      (failure: unknown) => setError(message(failure)),
    );
    api.history(moduleId).then(setHistory, () => setHistory([]));
    // The route object changes on every navigation; the id and version are what matter.
  }, [account, moduleId, moduleVersion]);

  const props: ShellProps = {
    route,
    host: window.location.host,
    session,
    version,
    libraries,
    library,
    scale,
    list,
    module,
    history,
    profiles,
    trialAccounts,
    search,
    error,
    navigate,
    onLibrary: (chosen) => {
      setLibrary(chosen);
      keep("cad.bibliotek", chosen);
      if (route.page !== "library") navigate(PATHS.library);
    },
    onScale: (chosen) => {
      setScale(chosen);
      keep("cad.skala", chosen);
    },
    onLogIn: (chosen) => {
      api.trialLogIn(chosen.id).then(
        (started) => {
          setSession(started);
          const next = new URLSearchParams(search).get("next");
          navigate(next && next.startsWith("/") && !next.startsWith("//") ? next : PATHS.library);
        },
        (failure: unknown) => setError(message(failure)),
      );
    },
    onLogOut: () => {
      api.logOut().then((out) => {
        if (out.logout_url) window.location.assign(out.logout_url);
        else {
          setSession(out);
          navigate(PATHS.login);
        }
      }, () => undefined);
    },
    onSearch: (q) => {
      query.current = q;
      loadList();
    },
    onCreate: async (body) => {
      const made = await api.create(body);
      setModule(made);
      navigate(modulePath(made.id));
    },
    onSave: async (body) => {
      if (!module) return;
      const saved = await api.save(module.id, body);
      setModule(saved);
      api.history(saved.id).then(setHistory, () => undefined);
      navigate(modulePath(saved.id));
    },
    onApprove: () => {
      if (!module) return;
      api.approve(module.id, module.version).then(
        (approved) => {
          setModule(approved);
          api.history(approved.id).then(setHistory, () => undefined);
        },
        (failure: unknown) => setError(message(failure)),
      );
    },
    onVisibility: (visibility, club) => {
      if (!module) return;
      api.visibility(module.id, { visibility, club }).then(
        (changed) => {
          setModule(changed);
          api.history(changed.id).then(setHistory, () => undefined);
        },
        (failure: unknown) => setError(message(failure)),
      );
    },
    onRemove: () => {
      if (!module || !window.confirm(`Ta bort ${module.name}? Historiken sparas.`)) return;
      api.remove(module.id).then(() => navigate(PATHS.library), (failure: unknown) => setError(message(failure)));
    },
    onNewProfile: async (body) => {
      await api.newProfile(body);
      setProfiles(await api.profiles(scale));
    },
  };
  return <Shell {...props} />;
}

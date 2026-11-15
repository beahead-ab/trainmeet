import { AccountMenu, AppSwitcher, BottomNav, Header, linkClick, type App as SwitcherApp, type Navigate } from "@trainmeet/design";
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  api,
  ApiError,
  loginHref,
  type Club,
  type ClubPage,
  type FleetPage,
  type FleetRole,
  type Invitation,
  type Session,
} from "./api";
import { storeLanguage, text, type Language, type TextKey } from "./i18n";
import { AccountIcon, ClubsIcon, MeetsIcon, TokensIcon } from "./icons";
import { clubPath, PATHS, routeFor, tabOf, type Page, type Route } from "./routes";

export type T = (key: TextKey, vars?: Record<string, string | number>) => string;

/** The other TrainMeet apps. Catalog has a test environment beside ID's. */
export function switcherApps(t: T, host: string): SwitcherApp[] {
  const test = host.startsWith("test.") || host.startsWith("localhost") || host.startsWith("127.");
  return [
    { product: "HUB", label: "TrainMeet Hub", what: t("appHub"), href: test ? "https://test.hub.trainmeet.app" : undefined },
    { product: "TKL", label: "TrainMeet TKL", what: t("appTkl") },
    { product: "CAD", label: "TrainMeet CAD", what: t("appCad") },
    { product: "CATALOG", label: "TrainMeet Catalog", what: t("appCatalog"), href: test ? "https://test.catalog.trainmeet.app" : undefined },
    { product: "LOKFÖRAREN", label: "Lokföraren", what: t("appDriver") },
    { product: "ID", label: "TrainMeet ID", what: t("appId") },
  ];
}

const TITLES: Record<Page, TextKey> = {
  account: "account",
  clubs: "clubs",
  club: "club",
  meets: "meets",
  tokens: "tokens",
  invitations: "invitations",
  fleet: "fleetTitle",
  missing: "notFound",
};

/** What the pages show, as ID's API said it. */
export type Data = {
  clubs?: Club[];
  invitations?: Invitation[];
  club?: ClubPage;
  fleet?: FleetPage;
};

export type Actions = {
  createClub?: (name: string) => Promise<string | null>;
  invite?: (club: string, email: string) => Promise<string | null>;
  removeMember?: (club: string, person: string) => Promise<string | null>;
  withdraw?: (invitation: string) => Promise<string | null>;
  answer?: (invitation: string, accept: boolean) => Promise<string | null>;
  shareFleet?: (owner: string, email: string, role: FleetRole) => Promise<string | null>;
  stopSharing?: (grant: string) => Promise<string | null>;
};

export type ShellProps = {
  route: Route;
  language: Language;
  host: string;
  session: Session | null;
  offline: boolean;
  search?: string;
  /** The address's path, to come back to after logging in. */
  path?: string;
  data?: Data;
  actions?: Actions;
  navigate?: Navigate;
  onLanguage?: () => void;
  onLogOut?: () => void;
};

const date = (iso: string, language: Language) =>
  new Date(iso).toLocaleDateString(language === "sv" ? "sv-SE" : "en-GB", { day: "numeric", month: "long", year: "numeric" });

/** Everything on the screen, from the state. No fetching here, so it can be rendered in tests. */
export function Shell(props: ShellProps) {
  const { route, language, host, session, offline, navigate } = props;
  const t: T = (key, vars) => text(language, key, vars);
  const account = session?.account ?? null;
  const tab = (target: keyof typeof PATHS, label: TextKey, icon?: ReactNode) => ({
    href: PATHS[target],
    label: t(label),
    current: tabOf(route.page) === target,
    icon,
  });
  return (
    <>
      <a className="tm-hoppa" href="#innehall">
        {t("skip")}
      </a>
      <Header
        product="ID"
        productLabel={t("product")}
        place={host}
        home={PATHS.account}
        navLabel={t("mainNav")}
        tabs={account ? [tab("account", "account"), tab("clubs", "clubs"), tab("meets", "meets"), tab("tokens", "tokens")] : []}
        navigate={navigate}
      >
        <AppSwitcher apps={switcherApps(t, host)} current="ID" title={t("switcher")} sameAccount={t("sameAccount")} buttonLabel={t("switcherButton")} comingLabel={t("coming")} />
        {account ? (
          <AccountMenu name={account.name} initials={account.initials} detail={account.email} buttonLabel={t("accountButton", { name: account.name })}>
            {(close) => (
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
            )}
          </AccountMenu>
        ) : null}
      </Header>
      <main id="innehall" className="id-sida" tabIndex={-1}>
        {offline ? (
          <p className="tm-kort id-fel" role="alert">
            {t("offline")}
          </p>
        ) : session === null ? null : account ? (
          <Content {...props} t={t} />
        ) : (
          <LoginCard t={t} language={language} route={route} search={props.search ?? ""} path={props.path ?? "/"} />
        )}
      </main>
      {account ? (
        <BottomNav
          label={t("phoneNav")}
          items={[
            tab("account", "account", <AccountIcon />),
            tab("clubs", "clubs", <ClubsIcon />),
            tab("meets", "meets", <MeetsIcon />),
            tab("tokens", "tokens", <TokensIcon />),
          ]}
          navigate={navigate}
        />
      ) : null}
      <footer className="id-fot">
        <span>TrainMeet ID</span>
        <button type="button" className="tm-knapp" lang={language === "sv" ? "en" : "sv"} aria-label={t("otherLanguageLabel")} onClick={props.onLanguage}>
          {t("otherLanguage")}
        </button>
      </footer>
    </>
  );
}

function LoginCard({ t, language, route, search, path }: { t: T; language: Language; route: Route; search: string; path: string }) {
  const failed = new URLSearchParams(search).get("inloggning") === "fel";
  const here = route.page === "missing" ? PATHS.account : path;
  return (
    <section className="tm-kort id-inloggning">
      <h1>{t("logIn")}</h1>
      {failed ? (
        <p className="id-fel" role="alert">
          {t("loginFailed")}
        </p>
      ) : null}
      <p>{t("loginIntro")}</p>
      <a className="tm-knapp primar" href={loginHref(here, language)}>
        {t("logIn")}
      </a>
    </section>
  );
}

function Content(props: ShellProps & { t: T }) {
  const { route, t, data = {}, actions = {}, navigate, language } = props;
  switch (route.page) {
    case "account":
      return (
        <div className="id-raster">
          <div className="id-kolumn">
            <AccountCard {...props} />
            <InvitationsCard t={t} invitations={data.invitations} answer={actions.answer} />
            <ClubsCard t={t} clubs={data.clubs} navigate={navigate} />
          </div>
          <div className="id-kolumn">
            <TokensCard t={t} />
          </div>
        </div>
      );
    case "invitations":
      return (
        <div className="id-kolumn">
          <InvitationsCard t={t} invitations={data.invitations} answer={actions.answer} heading={1} />
        </div>
      );
    case "clubs":
      return (
        <div className="id-raster">
          <div className="id-kolumn">
            <h1>{t("clubs")}</h1>
            <ClubsCard t={t} clubs={data.clubs} navigate={navigate} />
            <NewClubCard t={t} create={actions.createClub} />
          </div>
          <div className="id-kolumn">
            <SeparateCard t={t} />
          </div>
        </div>
      );
    case "club":
      return data.club ? <ClubView t={t} page={data.club} me={props.session?.account?.id ?? ""} actions={actions} language={language} /> : null;
    case "fleet":
      return data.fleet ? <FleetView t={t} page={data.fleet} actions={actions} language={language} /> : null;
    case "meets":
      return (
        <section className="tm-kort">
          <h1>{t("meets")}</h1>
          <p>{t("meetsLater")}</p>
        </section>
      );
    case "tokens":
      return <TokensCard t={t} heading={1} />;
    case "missing":
      return (
        <section className="tm-kort">
          <h1>{t("notFound")}</h1>
          <a href={PATHS.account} onClick={linkClick(navigate, PATHS.account)}>
            {t("toAccount")}
          </a>
        </section>
      );
  }
}

function Heading({ level, children }: { level: 1 | 2; children: ReactNode }) {
  return level === 1 ? <h1>{children}</h1> : <h2>{children}</h2>;
}

function AccountCard({ session, t }: ShellProps & { t: T }) {
  const account = session?.account;
  if (!account) return null;
  return (
    <section className="tm-kort id-mitt-konto" aria-labelledby="mitt-konto">
      <h1 id="mitt-konto">{t("myAccount")}</h1>
      <div className="id-person">
        <span className="id-initialer" aria-hidden="true">
          {account.initials}
        </span>
        <div>
          <p className="id-namn">{account.name}</p>
          <p className="id-detalj">
            {account.email} · {t("verified")}
          </p>
        </div>
      </div>
    </section>
  );
}

function RoleChip({ t, role }: { t: T; role: string }) {
  const key = (["admin", "member", "viewer", "editor"].includes(role) ? role : "member") as TextKey;
  return <span className={`id-chip id-chip-${role}`}>{t(key)}</span>;
}

function ClubsCard({ t, clubs, navigate }: { t: T; clubs?: Club[]; navigate?: Navigate }) {
  return (
    <section className="tm-kort" aria-labelledby="mina-klubbar">
      <h2 id="mina-klubbar">{t("myClubs")}</h2>
      {clubs === undefined ? null : clubs.length === 0 ? (
        <p className="id-detalj">{t("noClubs")}</p>
      ) : (
        <ul className="id-lista">
          {clubs.map((club) => (
            <li key={club.id}>
              <a href={clubPath(club.id)} onClick={linkClick(navigate, clubPath(club.id))}>
                {club.name}
              </a>
              <RoleChip t={t} role={club.role} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** One request at a time, with what ID said if it said no. */
function useAction(): [boolean, string | null, (work: () => Promise<string | null>) => Promise<boolean>] {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const run = async (work: () => Promise<string | null>) => {
    setBusy(true);
    setProblem(null);
    const said = await work();
    setBusy(false);
    setProblem(said);
    return said === null;
  };
  return [busy, problem, run];
}

function Problem({ text: said }: { text: string | null }) {
  return said ? (
    <p className="id-fel" role="alert">
      {said}
    </p>
  ) : null;
}

function InvitationsCard({ t, invitations, answer, heading = 2 }: { t: T; invitations?: Invitation[]; answer?: Actions["answer"]; heading?: 1 | 2 }) {
  const [busy, problem, run] = useAction();
  if (invitations === undefined || (heading === 2 && invitations.length === 0)) return null;
  return (
    <section className="tm-kort id-inbjudningar" aria-label={t("invitations")}>
      <Heading level={heading}>{t("invitations")}</Heading>
      {invitations.length === 0 ? <p className="id-detalj">{t("noInvitations")}</p> : null}
      <ul className="id-lista">
        {invitations.map((invitation) => (
          <li key={invitation.id}>
            <div>
              <p className="id-namn">
                {invitation.resource.kind === "club" ? t("toClub") : t("toFleet")}: {invitation.title}
              </p>
              <p className="id-detalj">
                {t("invitedBy", { name: invitation.sent_by.name })} · {t("asRole", { role: t((["viewer", "editor"].includes(invitation.role) ? invitation.role : "member") as TextKey).toLowerCase() })}
              </p>
            </div>
            <div className="id-knappar">
              <button type="button" className="tm-knapp primar" disabled={busy} onClick={() => run(() => answer?.(invitation.id, true) ?? Promise.resolve(null))}>
                {t("yes")}
              </button>
              <button type="button" className="tm-knapp" disabled={busy} onClick={() => run(() => answer?.(invitation.id, false) ?? Promise.resolve(null))}>
                {t("no")}
              </button>
            </div>
          </li>
        ))}
      </ul>
      <Problem text={problem} />
    </section>
  );
}

function TokensCard({ t, heading = 2 }: { t: T; heading?: 1 | 2 }) {
  return (
    <section className="tm-kort">
      <Heading level={heading}>{t("tokensTitle")}</Heading>
      <p className="id-detalj">{t("tokensLater")}</p>
    </section>
  );
}

function SeparateCard({ t }: { t: T }) {
  return (
    <section className="tm-kort">
      <h2>{t("separateTitle")}</h2>
      <p>{t("separateText")}</p>
    </section>
  );
}

function NewClubCard({ t, create }: { t: T; create?: Actions["createClub"] }) {
  const [name, setName] = useState("");
  const [busy, problem, run] = useAction();
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (await run(() => create?.(name.trim()) ?? Promise.resolve(null))) setName("");
  };
  return (
    <section className="tm-kort" aria-labelledby="ny-klubb">
      <h2 id="ny-klubb">{t("newClub")}</h2>
      <form className="id-formular" onSubmit={submit}>
        <label htmlFor="klubbnamn">{t("clubName")}</label>
        <input id="klubbnamn" value={name} maxLength={80} required onChange={(e) => setName(e.target.value)} />
        <button type="submit" className="tm-knapp primar" disabled={busy || !name.trim()}>
          {t("create")}
        </button>
      </form>
      <Problem text={problem} />
    </section>
  );
}

function InviteForm({ t, submitLabel, onSend, children }: { t: T; submitLabel: TextKey; onSend: (email: string) => Promise<string | null>; children?: ReactNode }) {
  const [email, setEmail] = useState("");
  const [busy, problem, run] = useAction();
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (await run(() => onSend(email.trim()))) setEmail("");
  };
  return (
    <form className="id-formular" onSubmit={submit}>
      <label htmlFor="inbjudan-epost">{t("email")}</label>
      <input id="inbjudan-epost" type="email" autoComplete="off" value={email} required onChange={(e) => setEmail(e.target.value)} />
      {children}
      <button type="submit" className="tm-knapp primar" disabled={busy || !email.trim()}>
        {t(submitLabel)}
      </button>
      <Problem text={problem} />
    </form>
  );
}

function ClubView({ t, page, me, actions, language }: { t: T; page: ClubPage; me: string; actions: Actions; language: Language }) {
  const admin = page.club.role === "admin";
  const [busy, problem, run] = useAction();
  return (
    <div className="id-raster">
      <div className="id-kolumn">
        <div>
          <p className="id-overrubrik">{t("club")}</p>
          <h1>{page.club.name}</h1>
        </div>
        <section className="tm-kort" aria-labelledby="medlemmar">
          <h2 id="medlemmar">{t("members", { count: page.members.length })}</h2>
          <ul className="id-lista">
            {page.members.map((member) => (
              <li key={member.person.id}>
                <div>
                  <p className="id-namn">{member.person.name}</p>
                  <p className="id-detalj">{t("memberSince", { date: date(member.since, language) })}</p>
                </div>
                <div className="id-knappar">
                  <RoleChip t={t} role={member.role} />
                  {member.person.id === me ? (
                    <button type="button" className="tm-knapp" disabled={busy} onClick={() => run(() => actions.removeMember?.(page.club.id, me) ?? Promise.resolve(null))}>
                      {t("leave")}
                    </button>
                  ) : admin ? (
                    <button type="button" className="tm-knapp" disabled={busy} aria-label={t("removeNamed", { name: member.person.name })} onClick={() => run(() => actions.removeMember?.(page.club.id, member.person.id) ?? Promise.resolve(null))}>
                      {t("remove")}
                    </button>
                  ) : null}
                </div>
              </li>
            ))}
            {page.invitations?.map((invitation) => (
              <li key={invitation.id}>
                <div>
                  <p className="id-namn">{invitation.sent_to}</p>
                  <p className="id-detalj">{t("invitedAt", { date: date(invitation.at, language) })}</p>
                </div>
                <div className="id-knappar">
                  <span className="id-chip id-chip-invited">{t("invited")}</span>
                  <button type="button" className="tm-knapp" disabled={busy} aria-label={t("withdrawNamed", { address: invitation.sent_to })} onClick={() => run(() => actions.withdraw?.(invitation.id) ?? Promise.resolve(null))}>
                    {t("withdraw")}
                  </button>
                </div>
              </li>
            ))}
          </ul>
          <Problem text={problem} />
        </section>
        {admin ? (
          <section className="tm-kort" aria-labelledby="bjud-in">
            <h2 id="bjud-in">{t("invite")}</h2>
            <InviteForm t={t} submitLabel="send" onSend={(email) => actions.invite?.(page.club.id, email) ?? Promise.resolve(null)} />
          </section>
        ) : null}
      </div>
      <div className="id-kolumn">
        <SeparateCard t={t} />
      </div>
    </div>
  );
}

function FleetView({ t, page, actions, language }: { t: T; page: FleetPage; actions: Actions; language: Language }) {
  const [role, setRole] = useState<FleetRole>("viewer");
  const [busy, problem, run] = useAction();
  return (
    <div className="id-kolumn">
      <div>
        <p className="id-overrubrik">{page.title}</p>
        <h1>{t("fleetTitle")}</h1>
        <p>{t("fleetIntro")}</p>
      </div>
      <section className="tm-kort" aria-labelledby="delad-med">
        <h2 id="delad-med">{t("sharedWith")}</h2>
        {page.grants.length === 0 && page.invitations.length === 0 ? <p className="id-detalj">{t("notShared")}</p> : null}
        <ul className="id-lista">
          {page.grants.map((grant) => (
            <li key={grant.id}>
              <p className="id-namn">{grant.person.name}</p>
              <div className="id-knappar">
                <RoleChip t={t} role={grant.role} />
                <button type="button" className="tm-knapp" disabled={busy} aria-label={t("stopSharingNamed", { name: grant.person.name })} onClick={() => run(() => actions.stopSharing?.(grant.id) ?? Promise.resolve(null))}>
                  {t("stopSharing")}
                </button>
              </div>
            </li>
          ))}
          {page.invitations.map((invitation) => (
            <li key={invitation.id}>
              <div>
                <p className="id-namn">{t("sentTo", { address: invitation.sent_to })}</p>
                <p className="id-detalj">{t("invitedAt", { date: date(invitation.at, language) })}</p>
              </div>
              <div className="id-knappar">
                <RoleChip t={t} role={invitation.role} />
                <button type="button" className="tm-knapp" disabled={busy} aria-label={t("withdrawNamed", { address: invitation.sent_to })} onClick={() => run(() => actions.withdraw?.(invitation.id) ?? Promise.resolve(null))}>
                  {t("withdraw")}
                </button>
              </div>
            </li>
          ))}
        </ul>
        <Problem text={problem} />
      </section>
      <section className="tm-kort" aria-labelledby="dela">
        <h2 id="dela">{t("share")}</h2>
        <InviteForm t={t} submitLabel="send" onSend={(email) => actions.shareFleet?.(page.owner.id, email, role) ?? Promise.resolve(null)}>
          <fieldset className="id-val">
            <legend>{t("right")}</legend>
            {(["viewer", "editor"] as const).map((choice) => (
              <label key={choice}>
                <input type="radio" name="ratt" value={choice} checked={role === choice} onChange={() => setRole(choice)} /> {t(choice)}
              </label>
            ))}
          </fieldset>
        </InviteForm>
      </section>
    </div>
  );
}

/** The web app: reads the session, follows the address and fetches what the page shows. */
export function App({ initialLanguage }: { initialLanguage: Language }) {
  const [language, setLanguage] = useState<Language>(initialLanguage);
  const [route, setRoute] = useState<Route>(() => routeFor(window.location.pathname));
  const [session, setSession] = useState<Session | null>(null);
  const [offline, setOffline] = useState(false);
  const [data, setData] = useState<Data>({});
  const moved = useRef(false);
  const t: T = (key, vars) => text(language, key, vars);

  const navigate = useCallback((href: string) => {
    window.history.pushState(null, "", href);
    moved.current = true;
    setRoute(routeFor(href));
  }, []);

  useEffect(() => {
    const onPop = () => setRoute(routeFor(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    api.session().then(setSession, () => setOffline(true));
  }, []);

  const load = useCallback(async () => {
    if (!session?.account) return;
    try {
      switch (route.page) {
        case "account":
        case "invitations": {
          const [clubs, invitations] = await Promise.all([api.clubs(), api.invitations()]);
          setData({ clubs, invitations });
          break;
        }
        case "clubs":
          setData({ clubs: await api.clubs() });
          break;
        case "club":
          setData({ club: await api.club(route.id ?? "") });
          break;
        case "fleet":
          setData({ fleet: await api.fleet(route.id ?? "") });
          break;
        default:
          setData({});
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) setRoute({ page: "missing" });
      else if (error instanceof ApiError && error.status === 401) setSession({ account: null, logout_url: null });
      else setOffline(true);
    }
  }, [route, session]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    document.documentElement.lang = language;
    document.title = `${text(language, TITLES[route.page])} · TrainMeet ID`;
  }, [language, route]);

  useEffect(() => {
    if (moved.current) document.querySelector<HTMLElement>("#innehall")?.focus();
  }, [route]);

  /** Do something, then fetch the page again. Null when it went well, otherwise what ID said. */
  const act = (work: () => Promise<unknown>, after?: (result: unknown) => void) => async (): Promise<string | null> => {
    try {
      const result = await work();
      after?.(result);
      await load();
      return null;
    } catch (error) {
      if (error instanceof ApiError) return error.problem ?? t(`problem_${error.code ?? "conflict"}` as TextKey);
      return t("offline");
    }
  };

  const actions: Actions = {
    createClub: (name) => act(() => api.createClub(name), (club) => navigate(clubPath((club as Club).id)))(),
    invite: (club, email) => act(() => api.inviteToClub(club, email))(),
    removeMember: (club, person) =>
      act(
        () => api.removeMember(club, person),
        () => person === session?.account?.id && navigate(PATHS.clubs),
      )(),
    withdraw: (invitation) => act(() => api.withdraw(invitation))(),
    answer: (invitation, accept) => act(() => api.answer(invitation, accept))(),
    shareFleet: (owner, email, role) => act(() => api.inviteToFleet(owner, email, role))(),
    stopSharing: (grant) => act(() => api.removeGrant(grant))(),
  };

  return (
    <Shell
      route={route}
      language={language}
      host={window.location.host}
      session={session}
      offline={offline}
      search={window.location.search}
      path={window.location.pathname}
      data={data}
      actions={actions}
      navigate={navigate}
      onLanguage={() => {
        const next: Language = language === "sv" ? "en" : "sv";
        setLanguage(next);
        storeLanguage(next);
      }}
      onLogOut={() => {
        api.logOut().then((after) => {
          if (after.logout_url) window.location.assign(after.logout_url);
          else setSession(after);
        }, () => setOffline(true));
      }}
    />
  );
}

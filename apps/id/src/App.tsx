import { AccountMenu, AppSwitcher, BottomNav, Header, linkClick, type App as SwitcherApp, type Navigate } from "@trainmeet/design";
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  api,
  ApiError,
  EXPORT_HREF,
  loginHref,
  type Club,
  type ClubPage,
  type FleetPage,
  type FleetRole,
  type Invitation,
  type Meet,
  type MeetPage,
  type MeetRole,
  type NewMeet,
  type AppKey,
  type ClubRole,
  type HelpRequest,
  type RemovalPlan,
  type Session,
  type TokenBalance,
  type TokenPurchase,
  type TokenShop,
} from "./api";
import { storeLanguage, text, type Language, type TextKey } from "./i18n";
import { AccountIcon, ClubsIcon, MeetsIcon, TokensIcon } from "./icons";
import { clubPath, meetPath, PATHS, routeFor, tabOf, type Page, type Route } from "./routes";

export type T = (key: TextKey, vars?: Record<string, string | number>) => string;

const PRODUCTS: Record<AppKey, string> = { hub: "HUB", tkl: "TKL", cad: "CAD", catalog: "CATALOG", driver: "LOKFÖRAREN", id: "ID" };
const APP_NAMES: Record<AppKey, string> = { hub: "TrainMeet Hub", tkl: "TrainMeet TKL", cad: "TrainMeet CAD", catalog: "TrainMeet Catalog", driver: "Lokföraren", id: "TrainMeet ID" };

/** The other TrainMeet apps. Catalog has a test environment beside ID's. With the person's
 * apps from ID, only those they have something in (KONTO-38, ID11). */
export function switcherApps(t: T, host: string, apps?: AppKey[] | null): SwitcherApp[] {
  const test = host.startsWith("test.") || host.startsWith("localhost") || host.startsWith("127.");
  const all = [
    { product: "HUB", label: "TrainMeet Hub", what: t("appHub"), href: test ? "https://test.hub.trainmeet.app" : undefined },
    { product: "TKL", label: "TrainMeet TKL", what: t("appTkl") },
    { product: "CAD", label: "TrainMeet CAD", what: t("appCad") },
    { product: "CATALOG", label: "TrainMeet Catalog", what: t("appCatalog"), href: test ? "https://test.catalog.trainmeet.app" : undefined },
    { product: "LOKFÖRAREN", label: "Lokföraren", what: t("appDriver") },
    { product: "ID", label: "TrainMeet ID", what: t("appId") },
  ];
  if (!apps?.length) return all;
  const shown = new Set(apps.map((app) => PRODUCTS[app]));
  return all.filter((app) => shown.has(app.product));
}

/** Hjälp och fel from this page (KONTO-06): ID's own help page, with the app and the page. */
export function helpHref(path: string): string {
  return `${PATHS.help}?${new URLSearchParams({ app: "id", sida: path })}`;
}

const TITLES: Record<Page, TextKey> = {
  account: "account",
  clubs: "clubs",
  club: "club",
  meets: "meets",
  meet: "meet",
  tokens: "tokens",
  invitations: "invitations",
  fleet: "fleetTitle",
  help: "help",
  remove: "removeAccount",
  missing: "notFound",
};

/** What the pages show, as ID's API said it. */
export type Data = {
  clubs?: Club[];
  invitations?: Invitation[];
  club?: ClubPage;
  fleet?: FleetPage;
  meets?: Meet[];
  meet?: MeetPage;
  /** ID's own version, for Hjälp och fel from ID itself. */
  version?: string;
  removal?: RemovalPlan;
  /** The person's balance first, then their clubs' (#79, TOKEN-01). */
  tokens?: TokenBalance[];
  /** Whether buying is open, and the packages (TOKEN-02). */
  shop?: TokenShop;
};

export type Actions = {
  createClub?: (name: string) => Promise<string | null>;
  invite?: (club: string, email: string) => Promise<string | null>;
  removeMember?: (club: string, person: string) => Promise<string | null>;
  withdraw?: (invitation: string) => Promise<string | null>;
  answer?: (invitation: string, accept: boolean) => Promise<string | null>;
  shareFleet?: (owner: string, email: string, role: FleetRole) => Promise<string | null>;
  stopSharing?: (grant: string) => Promise<string | null>;
  createMeet?: (club: string, meet: NewMeet) => Promise<string | null>;
  changeMeet?: (meet: string, change: NewMeet) => Promise<string | null>;
  removeMeet?: (meet: string, club: string) => Promise<string | null>;
  giveRole?: (meet: string, person: string, role: MeetRole) => Promise<string | null>;
  takeRole?: (grant: string) => Promise<string | null>;
  sendHelp?: (request: HelpRequest) => Promise<string | null>;
  changeRole?: (club: string, person: string, role: ClubRole) => Promise<string | null>;
  removeAccount?: () => Promise<string | null>;
  /** Köp fler (TOKEN-02): to Stripe's page, and back to Tokens when paid. */
  buy?: (purchase: TokenPurchase) => Promise<string | null>;
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

/** A meet's days, as 13–15 november 2026. The dates are days, not moments. */
export function days(meet: Pick<NewMeet, "starts_on" | "ends_on">, language: Language): string {
  const day = (iso: string) => new Date(`${iso}T12:00:00`);
  const format = new Intl.DateTimeFormat(language === "sv" ? "sv-SE" : "en-GB", { day: "numeric", month: "long", year: "numeric" });
  return meet.starts_on === meet.ends_on ? format.format(day(meet.starts_on)) : format.formatRange(day(meet.starts_on), day(meet.ends_on));
}

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
        <AppSwitcher apps={switcherApps(t, host, session?.apps)} current="ID" title={t("switcher")} sameAccount={t("sameAccount")} buttonLabel={t("switcherButton")} comingLabel={t("coming")} />
        {account ? (
          <AccountMenu name={account.name} initials={account.initials} detail={account.email} buttonLabel={t("accountButton", { name: account.name })}>
            {(close) => (
              <>
                <a
                  href={helpHref(props.path ?? "/")}
                  onClick={(event) => {
                    linkClick(navigate, helpHref(props.path ?? "/"))(event);
                    close();
                  }}
                >
                  {t("help")}
                </a>
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
      {new URLSearchParams(search).get("borttaget") ? <p role="status">{t("removed")}</p> : null}
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
            <TokensCard t={t} tokens={data.tokens} language={language} />
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
      return data.club ? <ClubView t={t} page={data.club} me={props.session?.account?.id ?? ""} actions={actions} language={language} navigate={navigate} /> : null;
    case "fleet":
      return data.fleet ? <FleetView t={t} page={data.fleet} actions={actions} language={language} /> : null;
    case "meets":
      return (
        <div className="id-raster">
          <div className="id-kolumn">
            <h1>{t("meets")}</h1>
            <MeetsCard t={t} meets={data.meets} navigate={navigate} language={language} empty="noMeetsYet" withClub />
          </div>
          <div className="id-kolumn">
            <HubCard t={t} />
          </div>
        </div>
      );
    case "meet":
      return data.meet ? <MeetView t={t} page={data.meet} me={props.session?.account?.id ?? ""} actions={actions} language={language} navigate={navigate} /> : null;
    case "tokens":
      return (
        <TokensCard
          t={t}
          heading={1}
          tokens={data.tokens}
          language={language}
          shop={data.shop}
          admin={(data.clubs ?? []).filter((club) => club.role === "admin").map((club) => club.id)}
          buy={actions.buy}
          bought={new URLSearchParams(props.search ?? "").get("kop")}
        />
      );
    case "remove":
      return <RemoveView t={t} plan={data.removal} navigate={navigate} remove={actions.removeAccount} />;
    case "help":
      return <HelpView t={t} email={props.session?.account?.email ?? ""} search={props.search ?? ""} version={data.version} send={actions.sendHelp} />;
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
      <p>
        <a href={PATHS.remove}>{t("removeAccount")}</a>
      </p>
    </section>
  );
}

const ROLE_TEXTS = ["admin", "member", "viewer", "editor", "organizer", "publisher", "reader", "dispatcher", "loco_lead", "remote_clearer"];

function RoleChip({ t, role }: { t: T; role: string }) {
  const key = (ROLE_TEXTS.includes(role) ? role : "member") as TextKey;
  return <span className={`id-chip id-chip-${role}`}>{t(key)}</span>;
}

/** Meets, a club's or the person's clubs', with the person's own roles at each (ID10). */
function MeetsCard({ t, meets, navigate, language, empty, withClub = false, heading }: { t: T; meets?: Meet[]; navigate?: Navigate; language: Language; empty: TextKey; withClub?: boolean; heading?: ReactNode }) {
  return (
    <section className="tm-kort" aria-label={heading ? undefined : t("meets")} aria-labelledby={heading ? "traffar" : undefined}>
      {heading}
      {meets === undefined ? null : meets.length === 0 ? (
        <p className="id-detalj">{t(empty)}</p>
      ) : (
        <ul className="id-lista">
          {meets.map((meet) => (
            <li key={meet.id}>
              <div>
                <a className="id-namn" href={meetPath(meet.id)} onClick={linkClick(navigate, meetPath(meet.id))}>
                  {meet.name}
                </a>
                <p className="id-detalj">{withClub ? `${meet.club_name} · ${days(meet, language)}` : days(meet, language)}</p>
              </div>
              <div className="id-knappar">
                {meet.roles.map((role) => (
                  <RoleChip key={role} t={t} role={role} />
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** The app, the page and the version it is about come with the link from the app's menu. */
export function helpAbout(search: string, ownVersion?: string): { app: AppKey; page: string; version: string } {
  const query = new URLSearchParams(search);
  const asked = query.get("app") ?? "id";
  const app = (asked in APP_NAMES ? asked : "id") as AppKey;
  const version = app === "id" ? (ownVersion ?? "") : (query.get("version") ?? "");
  return { app, page: (query.get("sida") ?? "").slice(0, 300), version: version.slice(0, 80) };
}

function HelpView({ t, email, search, version, send }: { t: T; email: string; search: string; version?: string; send?: Actions["sendHelp"] }) {
  const about = helpAbout(search, version);
  const [kind, setKind] = useState<HelpRequest["kind"]>("help");
  const [text, setText] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, problem, run] = useAction();
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (await run(() => send?.({ kind, text: text.trim(), ...about }) ?? Promise.resolve(null))) setSent(true);
  };
  return (
    <div className="id-kolumn">
      <section className="tm-kort" aria-labelledby="hjalp">
        <h1 id="hjalp">{t("help")}</h1>
        {sent ? (
          <>
            <p role="status">{t("helpSent", { email })}</p>
            <button type="button" className="tm-knapp" onClick={() => window.history.back()}>
              {t("back")}
            </button>
          </>
        ) : (
          <form className="id-formular" onSubmit={submit}>
            <p>{t("helpIntro", { email })}</p>
            <fieldset className="id-val">
              <legend>{t("helpKind")}</legend>
              {(["help", "fault"] as const).map((choice) => (
                <label key={choice}>
                  <input type="radio" name="slag" value={choice} checked={kind === choice} onChange={() => setKind(choice)} /> {t(choice === "help" ? "helpAsk" : "helpFault")}
                </label>
              ))}
            </fieldset>
            <label htmlFor="hjalp-text">{t("helpText")}</label>
            <textarea id="hjalp-text" rows={6} maxLength={4000} required value={text} onChange={(e) => setText(e.target.value)} />
            <p className="id-detalj">
              {t("helpWith", { app: APP_NAMES[about.app], page: about.page || t("unknown"), version: about.version || t("unknown") })}
            </p>
            <button type="submit" className="tm-knapp primar" disabled={busy || !text.trim()}>
              {t("helpSend")}
            </button>
            <Problem text={problem} />
          </form>
        )}
      </section>
    </div>
  );
}

/** Ta bort mitt konto (KONTO-31, ID7, ID13): the file first, what goes, then the word. */
function RemoveView({ t, plan, navigate, remove }: { t: T; plan?: RemovalPlan; navigate?: Navigate; remove?: Actions["removeAccount"] }) {
  const [word, setWord] = useState("");
  const [busy, problem, run] = useAction();
  const names = (clubs: RemovalPlan["clubs_removed"]) => clubs.map((club) => club.name).join(", ");
  const blocked = (plan?.clubs_blocking.length ?? 0) > 0;
  const confirmed = word.trim().toUpperCase() === t("confirmWord");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (confirmed && !blocked) await run(() => remove?.() ?? Promise.resolve(null));
  };
  return (
    <div className="id-kolumn id-ta-bort-sida">
      <div>
        <p className="id-overrubrik">{t("myAccount")}</p>
        <h1>{t("removeAccount")}</h1>
        <p>{t("removeIntro")}</p>
      </div>
      <section className="tm-kort" aria-labelledby="hamta">
        <h2 id="hamta">
          <span className="id-steg">1</span> {t("fetchTitle")}
        </h2>
        <p>{t("fetchText")}</p>
        <p className="id-knappar">
          <a className="tm-knapp primar" href={EXPORT_HREF} download>
            {t("fetchButton")}
          </a>
          <span className="id-detalj">{t("fetchNote")}</span>
        </p>
      </section>
      <section className="tm-kort" aria-labelledby="tas-bort">
        <h2 id="tas-bort">
          <span className="id-steg">2</span> {t("goesTitle")}
        </h2>
        <div className="id-appruta">
          <div>
            <p className="id-namn">TrainMeet ID</p>
            <p className="id-detalj">{t("goesId")}</p>
          </div>
          <div>
            <p className="id-namn">TrainMeet Catalog</p>
            <p className="id-detalj">{t("goesCatalog")}</p>
          </div>
        </div>
        {plan && plan.clubs_removed.length > 0 ? <p>{t("goesClubs", { clubs: names(plan.clubs_removed) })}</p> : null}
        <p className="id-detalj">{t("clubStays")}</p>
        {blocked && plan ? (
          <p className="id-fel" role="alert">
            {t("blocking", { clubs: names(plan.clubs_blocking) })}
          </p>
        ) : null}
      </section>
      <section className="tm-kort id-oppet" aria-labelledby="sparas">
        <h2 id="sparas">
          <span className="id-chip id-chip-invited">{t("open")}</span> {t("keptTitle")}
        </h2>
        <p>{t("keptText")}</p>
      </section>
      <section className="tm-kort" aria-labelledby="bekrafta">
        <h2 id="bekrafta">
          <span className="id-steg fara">3</span> {t("confirmTitle")}
        </h2>
        <form className="id-formular" onSubmit={submit}>
          <label htmlFor="bekrafta-ord">{t("confirmLabel", { word: t("confirmWord") })}</label>
          <input id="bekrafta-ord" autoComplete="off" value={word} onChange={(e) => setWord(e.target.value)} />
          <div className="id-knappar">
            <button type="submit" className="tm-knapp fara-fylld" disabled={busy || !confirmed || blocked}>
              {t("removeAccount")}
            </button>
            <a className="tm-knapp" href={PATHS.account} onClick={linkClick(navigate, PATHS.account)}>
              {t("cancel")}
            </a>
          </div>
          <Problem text={problem} />
        </form>
      </section>
    </div>
  );
}

function HubCard({ t }: { t: T }) {
  return (
    <section className="tm-kort">
      <h2>{t("hubTitle")}</h2>
      <p>{t("hubText")}</p>
    </section>
  );
}

/** Name and days of a meet, to make it or to change it. */
function MeetForm({ t, id, initial, submitLabel, onSave }: { t: T; id: string; initial?: NewMeet; submitLabel: TextKey; onSave: (meet: NewMeet) => Promise<string | null> }) {
  const [name, setName] = useState(initial?.name ?? "");
  const [starts, setStarts] = useState(initial?.starts_on ?? "");
  const [ends, setEnds] = useState(initial?.ends_on ?? "");
  const [busy, problem, run] = useAction();
  const ready = name.trim() !== "" && starts !== "" && ends !== "";
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if ((await run(() => onSave({ name: name.trim(), starts_on: starts, ends_on: ends }))) && !initial) {
      setName("");
      setStarts("");
      setEnds("");
    }
  };
  return (
    <form className="id-formular" onSubmit={submit}>
      <label htmlFor={`${id}-namn`}>{t("meetName")}</label>
      <input id={`${id}-namn`} value={name} maxLength={80} required onChange={(e) => setName(e.target.value)} />
      <div className="id-datum">
        <div>
          <label htmlFor={`${id}-borjar`}>{t("startsOn")}</label>
          <input id={`${id}-borjar`} type="date" value={starts} required onChange={(e) => setStarts(e.target.value)} />
        </div>
        <div>
          <label htmlFor={`${id}-slutar`}>{t("endsOn")}</label>
          <input id={`${id}-slutar`} type="date" value={ends} min={starts || undefined} required onChange={(e) => setEnds(e.target.value)} />
        </div>
      </div>
      <button type="submit" className="tm-knapp primar" disabled={busy || !ready}>
        {t(submitLabel)}
      </button>
      <Problem text={problem} />
    </form>
  );
}

/** One person's roles at the meet. Ändra shows what the person asking may take back. */
function RolesRow({ t, name, grants, mayTake, me, busy, onTake }: { t: T; name: string; grants: MeetPage["grants"]; mayTake: (grant: MeetPage["grants"][number]) => boolean; me: boolean; busy: boolean; onTake: (grant: string) => void }) {
  const [open, setOpen] = useState(false);
  const takeable = grants.filter(mayTake);
  return (
    <li className="id-rollrad">
      <div className="id-rollrad-topp">
        <p className="id-namn">{name}</p>
        <div className="id-knappar">
          {grants.map((grant) => (
            <RoleChip key={grant.id} t={t} role={grant.role} />
          ))}
          {takeable.length > 0 ? (
            <button type="button" className="tm-knapp" aria-expanded={open} aria-label={t("changeRolesNamed", { name })} onClick={() => setOpen(!open)}>
              {open ? t("done") : t("change")}
            </button>
          ) : null}
        </div>
      </div>
      {open ? (
        <div className="id-knappar">
          {takeable.map((grant) => (
            <button
              key={grant.id}
              type="button"
              className="tm-knapp"
              disabled={busy}
              aria-label={me ? undefined : t("removeRoleNamed", { role: t(grant.role as TextKey).toLowerCase(), name })}
              onClick={() => onTake(grant.id)}
            >
              {t("removeRole", { role: t(grant.role as TextKey).toLowerCase() })}
            </button>
          ))}
        </div>
      ) : null}
    </li>
  );
}

function MeetView({ t, page, me, actions, language, navigate }: { t: T; page: MeetPage; me: string; actions: Actions; language: Language; navigate?: Navigate }) {
  const meet = page.meet;
  const members = page.members ?? [];
  const [person, setPerson] = useState(members[0]?.id ?? "");
  const [role, setRole] = useState<MeetRole | "">(page.may_give[0] ?? "");
  const [sure, setSure] = useState(false);
  const [busy, problem, run] = useAction();
  const people = new Map<string, { name: string; grants: MeetPage["grants"] }>();
  for (const grant of page.grants) {
    const entry = people.get(grant.person.id) ?? { name: grant.person.name, grants: [] };
    entry.grants.push(grant);
    people.set(grant.person.id, entry);
  }
  const give = async (event: FormEvent) => {
    event.preventDefault();
    if (person && role) await run(() => actions.giveRole?.(meet.id, person, role) ?? Promise.resolve(null));
  };
  return (
    <div className="id-raster">
      <div className="id-kolumn">
        <div>
          <p className="id-overrubrik">{t("meetIn", { club: meet.club_name })}</p>
          <h1>{meet.name}</h1>
          <p>{days(meet, language)}</p>
          <p>{t("meetIntro")}</p>
        </div>
        <section className="tm-kort" aria-labelledby="roller">
          <h2 id="roller">{t("rolesAt", { name: meet.name })}</h2>
          {people.size === 0 ? <p className="id-detalj">{t("noRoles")}</p> : null}
          <ul className="id-lista">
            {[...people.entries()].map(([id, entry]) => (
              <RolesRow
                key={id}
                t={t}
                name={entry.name}
                grants={entry.grants}
                me={id === me}
                busy={busy}
                mayTake={(grant) => grant.person.id === me || page.may_give.includes(grant.role as MeetRole)}
                onTake={(grant) => void run(() => actions.takeRole?.(grant) ?? Promise.resolve(null))}
              />
            ))}
          </ul>
          <Problem text={problem} />
        </section>
      </div>
      <div className="id-kolumn">
        {page.may_give.length > 0 ? (
          <section className="tm-kort" aria-labelledby="dela-ut">
            <h2 id="dela-ut">{t("give")}</h2>
            <form className="id-formular" onSubmit={give}>
              <label htmlFor="roll-person">{t("person")}</label>
              <select id="roll-person" value={person} onChange={(e) => setPerson(e.target.value)}>
                {members.map((member) => (
                  <option key={member.id} value={member.id}>
                    {member.name} · {meet.club_name}
                  </option>
                ))}
              </select>
              <fieldset className="id-val">
                <legend>{t("role")}</legend>
                {page.may_give.map((choice) => (
                  <label key={choice}>
                    <input type="radio" name="roll" value={choice} checked={role === choice} onChange={() => setRole(choice)} /> {t(choice as TextKey)}
                  </label>
                ))}
              </fieldset>
              <button type="submit" className="tm-knapp primar" disabled={busy || !person || !role}>
                {t("giveButton")}
              </button>
            </form>
          </section>
        ) : null}
        {page.may_change ? (
          <section className="tm-kort" aria-labelledby="andra-traffen">
            <h2 id="andra-traffen">{t("changeMeet")}</h2>
            <MeetForm key={`${meet.name}${meet.starts_on}${meet.ends_on}`} t={t} id="andra" initial={{ name: meet.name, starts_on: meet.starts_on, ends_on: meet.ends_on }} submitLabel="save" onSave={(change) => actions.changeMeet?.(meet.id, change) ?? Promise.resolve(null)} />
            {page.may_remove ? (
              <div className="id-knappar id-ta-bort">
                {sure ? (
                  <button type="button" className="tm-knapp fara" disabled={busy} onClick={() => void run(() => actions.removeMeet?.(meet.id, meet.club) ?? Promise.resolve(null))}>
                    {t("removeMeetSure")}
                  </button>
                ) : (
                  <button type="button" className="tm-knapp" onClick={() => setSure(true)}>
                    {t("removeMeet")}
                  </button>
                )}
              </div>
            ) : null}
          </section>
        ) : null}
        <HubCard t={t} />
        <a href={clubPath(meet.club)} onClick={linkClick(navigate, clubPath(meet.club))}>
          {meet.club_name}
        </a>
      </div>
    </div>
  );
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

/** The balances (TOKEN-01, TOKEN-12): what can be used now, this month's free quota, which is
 * not saved, and the bought tokens, which never run out. */
function TokensCard({
  t,
  heading = 2,
  tokens,
  language,
  shop,
  admin = [],
  buy,
  bought = null,
}: {
  t: T;
  heading?: 1 | 2;
  tokens?: TokenBalance[];
  language: Language;
  shop?: TokenShop;
  admin?: string[];
  buy?: Actions["buy"];
  bought?: string | null;
}) {
  const number = new Intl.NumberFormat(language === "sv" ? "sv-SE" : "en-GB");
  const [busy, problem, run] = useAction();
  const open = shop?.mode === "test";
  // A person buys for their own balance, and for a club's as its admin.
  const mayBuy = (balance: TokenBalance) => balance.owner.kind === "person" || admin.includes(balance.owner.id);
  return (
    <section className="tm-kort">
      <Heading level={heading}>{t("tokensTitle")}</Heading>
      <p className="id-detalj">{t("tokensIntro")}</p>
      {tokens === undefined ? null : (
        <ul className="id-lista id-saldon">
          {tokens.map((balance) => (
            <li key={`${balance.owner.kind}:${balance.owner.id}`}>
              <div>
                <strong>{balance.owner.kind === "person" ? t("tokensOwn") : t("tokensClub", { name: balance.title })}</strong>
                <div className="id-detalj">{t("tokensFree", { left: number.format(balance.free_left), monthly: number.format(balance.free_monthly) })}</div>
                <div className="id-detalj">{t("tokensBought", { n: number.format(balance.bought) })}</div>
                {balance.reserved > 0 ? <div className="id-detalj">{t("tokensReserved", { n: number.format(balance.reserved) })}</div> : null}
              </div>
              <span className="id-saldo">{t("tokensAvailable", { n: number.format(balance.available) })}</span>
              {open && buy && mayBuy(balance) ? (
                <div className="id-knappar id-paket">
                  {shop.packages.map((pack) => (
                    <button
                      key={pack.tokens}
                      type="button"
                      className="tm-knapp"
                      disabled={busy}
                      onClick={() => void run(() => buy({ owner: balance.owner, tokens: pack.tokens }))}
                    >
                      {t("tokensPackage", { n: number.format(pack.tokens), price: number.format(pack.price_sek) })}
                    </button>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {bought === "klart" ? <p role="status">{t("tokensBought_done")}</p> : null}
      {open ? <p className="id-detalj">{t("tokensTestMode")}</p> : <p className="id-detalj">{t("tokensBuyLater")}</p>}
      <Problem text={problem} />
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

function ClubView({ t, page, me, actions, language, navigate }: { t: T; page: ClubPage; me: string; actions: Actions; language: Language; navigate?: Navigate }) {
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
                    <>
                      <button
                        type="button"
                        className="tm-knapp"
                        disabled={busy}
                        aria-label={t(member.role === "admin" ? "makeMemberNamed" : "makeAdminNamed", { name: member.person.name })}
                        onClick={() => run(() => actions.changeRole?.(page.club.id, member.person.id, member.role === "admin" ? "member" : "admin") ?? Promise.resolve(null))}
                      >
                        {t(member.role === "admin" ? "makeMember" : "makeAdmin")}
                      </button>
                      <button type="button" className="tm-knapp" disabled={busy} aria-label={t("removeNamed", { name: member.person.name })} onClick={() => run(() => actions.removeMember?.(page.club.id, member.person.id) ?? Promise.resolve(null))}>
                        {t("remove")}
                      </button>
                    </>
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
        <MeetsCard t={t} meets={page.meets ?? []} navigate={navigate} language={language} empty="noMeets" heading={<h2 id="traffar">{t("clubMeets")}</h2>} />
        {admin ? (
          <section className="tm-kort" aria-labelledby="ny-traff">
            <h2 id="ny-traff">{t("newMeet")}</h2>
            <MeetForm t={t} id="ny-traff" submitLabel="add" onSave={(meet) => actions.createMeet?.(page.club.id, meet) ?? Promise.resolve(null)} />
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
          const [clubs, invitations, tokens] = await Promise.all([api.clubs(), api.invitations(), api.tokens()]);
          setData({ clubs, invitations, tokens });
          break;
        }
        case "tokens": {
          const [tokens, shop, clubs] = await Promise.all([api.tokens(), api.shop(), api.clubs()]);
          setData({ tokens, shop, clubs });
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
        case "meets":
          setData({ meets: await api.meets() });
          break;
        case "meet":
          setData({ meet: await api.meet(route.id ?? "") });
          break;
        case "remove":
          setData({ removal: await api.removalPlan() });
          break;
        case "help": {
          const version = await api.version().catch(() => null);
          setData({ version: version?.commit?.slice(0, 7) ?? undefined });
          break;
        }
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
    createMeet: (club, meet) => act(() => api.createMeet(club, meet), (made) => navigate(meetPath((made as Meet).id)))(),
    changeMeet: (meet, change) => act(() => api.changeMeet(meet, change))(),
    removeMeet: (meet, club) => act(() => api.removeMeet(meet), () => navigate(clubPath(club)))(),
    giveRole: (meet, person, role) => act(() => api.giveAtMeet(meet, person, role))(),
    takeRole: (grant) => act(() => api.removeGrant(grant))(),
    sendHelp: (request) => act(() => api.help(request))(),
    changeRole: (club, person, role) => act(() => api.changeRole(club, person, role))(),
    buy: async (purchase) => {
      try {
        const checkout = await api.buy(purchase);
        window.location.assign(checkout.url);
        return null;
      } catch (error) {
        if (error instanceof ApiError) return error.problem ?? t(`problem_${error.code ?? "conflict"}` as TextKey);
        return t("offline");
      }
    },
    removeAccount: async () => {
      try {
        await api.removeAccount();
        window.location.assign("/?borttaget=1");
        return null;
      } catch (error) {
        if (error instanceof ApiError) return error.problem ?? t(`problem_${error.code ?? "conflict"}` as TextKey);
        return t("offline");
      }
    },
  };

  return (
    <Shell
      route={route}
      language={language}
      host={window.location.host}
      session={session}
      offline={offline}
      search={window.location.search}
      path={window.location.pathname + window.location.search}
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

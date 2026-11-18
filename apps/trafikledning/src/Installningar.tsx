import { useEffect, useState } from "react";
import { hub, type AiService, type AiServiceChange, type Automation, type ClockSource, type AutomationSettings, type CloudLink, type DaySettings, type MeetWifi, type Now, type PlacePhone, type UpdateStatus, type Version, type WifiProfile, type WifiStatus } from "./api";
import { DISTURBANCES, LOST, WHERE, dayName } from "./drift";
import { Built } from "./StartPage";
import { Chip, Chips } from "./ui";

// Inställningar (TRAFIK-30, TRAFIK-31, H48, H50): reached with the gear in the header. Inside
// a meet it shows the three heaps: I paketet (follows the version), Under träffen (the meet's
// own settings) and Den här hubben (only the machine). Outside a meet only Den här hubben. Only
// what the hub can do today is here; the rest comes with its step.

export type SettingsProps = {
  /** May run the traffic: the meet's own settings (Under träffen). */
  admin: boolean;
  /** The one with the hub's PIN (H18): Den här hubben. Left out, the same as admin. */
  owner?: boolean;
  now: Now | null;
  hubName: string;
  version: Version | null;
  automation: Automation | null;
  /** Changes when Automatiken's settings were saved, so that the form starts over from them. */
  automationSaved: number;
  onAutomation?: (settings: AutomationSettings) => void;
  onDay?: (settings: DaySettings) => void;
  /** The places' game numbers, read only by the administrator (H30). */
  phones?: PlacePhone[] | null;
  onPhones?: (changes: PlacePhone[]) => void;
  /** Egen AI (H58), read only by the administrator; null when none is connected. */
  ai?: AiService | null;
  /** Resolves true when the hub checked the model and kept the setting. */
  onAi?: (change: AiServiceChange) => Promise<boolean>;
  onAiOff?: () => void;
  /** På den här hubben (SYNK-07): resolves true when the hub kept the new name. */
  onRename?: (name: string) => Promise<boolean>;
  /** Byt PIN: the current PIN first. Resolves true when it was changed. */
  onPin?: (pin: string, newPin: string) => Promise<boolean>;
};

type Heap = { label: string; note: string; items: [string, string][] };

export function heaps(now: Now | null): Heap[] {
  const machine: Heap = {
    label: "Den här hubben",
    note: "bara maskinen",
    items: [
      ["hubben", "Namn och version"],
      ["natet", "Pi:ns nät"],
      ...(now ? [] : ([["traffens-wifi", "Träffens Wi-Fi"]] as [string, string][])),
      ["uppdatering", "Uppdatering"],
      ["molnet", "Molnet"],
      ["ai", "AI"],
    ],
  };
  if (!now) return [machine];
  return [
    { label: "I paketet", note: "följer versionen", items: [["traffen", "Träffen och trafikdagarna"]] },
    {
      label: "Under träffen",
      note: "gäller medan den körs",
      items: [
        ["klockan", "Klockan"],
        ["automatik", "Automatik"],
        ["dygnsskifte", "Dygnsskifte"],
        ["telefon", "Telefonnummer"],
        ["traffens-wifi", "Träffens Wi-Fi"],
      ],
    },
    machine,
  ];
}

export function SettingsPage(props: SettingsProps) {
  const { now, hubName, version, owner = props.admin } = props;
  return (
    <>
      <div className="sidrubrik">
        <h1>Inställningar</h1>
        <p className="liten">{now ? `${now.name} · tre högar · nås med kugghjulet i sidhuvudet` : "Den här hubben · ingen träff körs"}</p>
      </div>
      <div className="installningar">
        <nav className="kort hogar" aria-label="Inställningar">
          {heaps(now).map((heap) => (
            <div key={heap.label} className="hog">
              <p className="hogrubrik">
                {heap.label}
                <span>{heap.note}</span>
              </p>
              <ul>
                {heap.items.map(([id, label]) => (
                  <li key={id}>
                    <a href={`#${id}`}>{label}</a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="kortlista">
          {now && <Meet now={now} />}
          {now && <Klockan admin={props.admin} now={now} />}
          {now && <Automatik {...props} now={now} />}
          {now && <Dygnsskifte {...props} now={now} />}
          {now && <Telefon {...props} now={now} />}
          <TraffensWifi admin={owner} />
          <section id="hubben" className="kort" aria-labelledby="hubben-rubrik">
            <h2 id="hubben-rubrik">Namn och version</h2>
            <p className="liten">Gäller den här hubben och alla träffar på den.</p>
            {owner ? (
              <NamnOchPin {...props} />
            ) : (
              <dl className="bygge">
                <dt>Namn</dt>
                <dd>{hubName}</dd>
              </dl>
            )}
            {version && <Built version={version} />}
            <p className="liten">Språket kommer hit senare i steg 5.</p>
          </section>
          <Natet admin={owner} />
          <Uppdatering admin={owner} />
          <Molnet admin={owner} />
          <EgenAi {...props} admin={owner} />
        </div>
      </div>
    </>
  );
}

const when = (at: string | null | undefined) => (at ? new Date(at).toLocaleString("sv-SE", { dateStyle: "short", timeStyle: "medium" }) : "aldrig");

const UPDATE_STATES: Record<string, string> = {
  checking: "Söker efter en nyare version",
  downloading: "Hämtar den nya versionen",
  installing: "Installerar",
  restarting: "Startar om hubben",
  done: "Klart",
  current: "Hubben har redan den senaste versionen",
  failed: "Uppdateringen gick inte",
};
const WORKING = new Set(["checking", "downloading", "installing", "restarting"]);

/** Den här hubben → Uppdatering (SYNK-19, SYNK-23): Ny version finns, on the button and never
 * during a meet. The Pi fetches the latest package, tries it and goes back if the hub does not
 * answer. */
export function Uppdatering({ admin, initial }: { admin: boolean; initial?: UpdateStatus }) {
  const [state, setState] = useState<UpdateStatus | null>(initial ?? null);
  const [said, setSaid] = useState("");
  const working = WORKING.has(state?.state ?? "");
  useEffect(() => {
    if (!admin || initial) return;
    const read = () => void hub.update().then(setState, () => undefined);
    read();
    const timer = window.setInterval(read, working ? 2000 : 30000);
    return () => window.clearInterval(timer);
  }, [admin, initial, working]);
  const start = async () => {
    setSaid("");
    try {
      setState(await hub.startUpdate());
      setSaid("Uppdateringen har startat. Hubben startar om när den är klar; sidan kan tappa kontakten en stund.");
    } catch (error) {
      setSaid(error instanceof Error ? error.message : "Det gick inte.");
    }
  };
  return (
    <section id="uppdatering" className="kort" aria-labelledby="uppdatering-rubrik">
      <h2 id="uppdatering-rubrik">Uppdatering</h2>
      <p className="liten">Pi:n hämtar den senaste versionen, provar den och går tillbaka till den förra om hubben inte svarar. Träffarna och inställningarna finns kvar.</p>
      {!admin ? (
        <p className="liten">Logga in med hubbens PIN-kod för att uppdatera hubben.</p>
      ) : !state ? (
        <p className="liten">Läser …</p>
      ) : !state.available ? (
        <p className="liten" id="uppdatering-saknas">{state.reason}</p>
      ) : (
        <>
          {state.newer && !working && (
            <p className="liten" role="status" id="uppdatering-ny">
              <strong>Ny version finns.</strong> {`Den senaste är ${state.latest}.`}
            </p>
          )}
          <dl className="bygge" id="uppdatering-lage">
            <dt>Körs nu</dt>
            <dd className="tm-mono">{state.build ?? "okänd"}</dd>
            <dt>Senaste</dt>
            <dd>
              {state.latest ? <span className="tm-mono">{state.latest}</span> : "Pi:n har inte kunnat se efter. Har den internet?"}
              {state.checked ? ` · sett ${when(state.checked)}` : ""}
            </dd>
            {state.state && (
              <>
                <dt>Senast</dt>
                <dd>{`${UPDATE_STATES[state.state] ?? state.state}${state.message ? `: ${state.message}` : ""}${state.at ? ` · ${when(state.at)}` : ""}`}</dd>
              </>
            )}
          </dl>
          <div className="installningsfot">
            <span className="liten" role="status" id="uppdatering-said">
              {said || (state.meet_running ? "En träff pågår. Uppdatera när klockan står still och träffen är slut." : "Aldrig under en träff.")}
            </span>
            <button id="update-start" type="button" className="primar" disabled={working || Boolean(state.meet_running)} onClick={() => void start()}>
              {working ? "Uppdaterar …" : state.newer ? "Uppdatera nu" : "Sök och installera"}
            </button>
          </div>
        </>
      )}
    </section>
  );
}

const SECURITY: [WifiProfile["security"], string][] = [
  ["wpa2", "WPA2"],
  ["wpa3", "WPA3"],
  ["open", "Öppet"],
];

/** Den här hubben → Pi:ns nät (SYNK-07, SYNK-26, H45): the Pi's own Wi-Fi, not the meet's.
 * Anslut nu is tried: keep it within 90 seconds, or NetworkManager goes back by itself. A
 * change is only made in the browser on the Pi or over HTTPS; a password never comes back. */
/** Träffens Wi-Fi (H45, DELT-02): what the participants and screens show, not the Pi's own
 * network. No name: it is not shared. The password is never sent back here. */
export function TraffensWifi({ admin, initial }: { admin: boolean; initial?: MeetWifi }) {
  const [state, setState] = useState<MeetWifi | null>(initial ?? null);
  const [name, setName] = useState(initial?.name ?? "");
  const [open, setOpen] = useState(initial?.open ?? false);
  const [password, setPassword] = useState("");
  const [said, setSaid] = useState("");
  const [drawn, setDrawn] = useState(0);
  useEffect(() => {
    if (!admin || initial) return;
    void hub.meetWifi().then((found) => {
      setState(found);
      setName(found.name);
      setOpen(found.open);
    }, () => undefined);
  }, [admin, initial]);
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaid("");
    try {
      const saved = await hub.saveMeetWifi({ name, open, password: password || null });
      setState(saved);
      setPassword("");
      setDrawn(Date.now());
      setSaid(saved.name ? "Sparat. Deltagarna ser det på träffens nät." : "Träffens Wi-Fi delas inte.");
    } catch (error) {
      setSaid(error instanceof Error ? error.message : "Det gick inte.");
    }
  };
  return (
    <section id="traffens-wifi" className="kort" aria-labelledby="traffens-wifi-rubrik">
      <h2 id="traffens-wifi-rubrik">Träffens Wi-Fi</h2>
      <p className="liten">Det deltagarna ser på träffens nät eller inloggade, i Dela träffen och i Anslut din TMBox. Pi:ns eget nät ställs under Den här hubben.</p>
      {!admin ? (
        <p className="liten">Logga in med hubbens PIN-kod för att ändra träffens Wi-Fi.</p>
      ) : (
        <form id="traffens-wifi-form" className="formular" onSubmit={(event) => void save(event)}>
          {state?.name && (
            <figure className="qr-forhand">
              <img src={`/api/deltagare/wifi.svg?v=${drawn}`} alt={`QR-koden för ${state.name}`} width={140} height={140} />
              <figcaption className="liten">1 · Wi-Fi</figcaption>
            </figure>
          )}
          <label>
            Nätverkets namn <input id="traffens-wifi-namn" maxLength={32} value={name} autoComplete="off" onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="kryss">
            <input id="traffens-wifi-oppet" type="checkbox" checked={open} onChange={(event) => setOpen(event.target.checked)} /> Öppet nät, utan lösenord
          </label>
          {!open && (
            <label>
              Lösenord, 8–63 tecken
              <input id="traffens-wifi-losen" type="password" minLength={8} maxLength={63} autoComplete="off" placeholder={state?.has_password ? "oförändrat" : ""} value={password} onChange={(event) => setPassword(event.target.value)} />
            </label>
          )}
          <div className="installningsfot">
            <span className="liten" role="status" id="traffens-wifi-said">
              {said || "Utan namn delas träffens Wi-Fi inte."}
            </span>
            <button type="submit" className="primar">
              Spara
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

const FASTCLOCK = "https://fastclock.azurewebsites.net";

/** Klockan (F12, IMPORT-35): Drift's own clock, or FastClock, which Drift then follows. The
 * hub reads FastClock before it is saved; the password is never shown again. */
export function Klockan({ admin, now, initial }: { admin: boolean; now: Now; initial?: ClockSource }) {
  const [state, setState] = useState<ClockSource | null>(initial ?? null);
  const [source, setSource] = useState<"drift" | "fastclock">(initial?.source ?? "drift");
  const [name, setName] = useState(initial?.clock_name ?? "");
  const [url, setUrl] = useState(initial?.url ?? FASTCLOCK);
  const [user, setUser] = useState(initial?.user ?? "");
  const [password, setPassword] = useState("");
  const [every, setEvery] = useState(initial?.poll_interval ?? 2);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  const take = (found: ClockSource) => {
    setState(found);
    setSource(found.source);
    setName(found.clock_name);
    setUrl(found.url);
    setUser(found.user);
    setEvery(found.poll_interval);
  };
  useEffect(() => {
    if (!admin || initial) return;
    void hub.clockSource().then(take, () => undefined);
  }, [admin, initial]);
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setSaid(source === "fastclock" ? "Läser FastClock …" : "");
    try {
      const saved = await hub.saveClockSource({ source, clock_name: name, url, user, password: password || null, poll_interval: every });
      take(saved);
      setPassword("");
      setSaid(saved.source === "fastclock" ? "Sparat. Klockan följer FastClock." : "Sparat. Drifts klocka står där FastClock var; starta den i Nu.");
    } catch (error) {
      setSaid(error instanceof Error ? error.message : "Det gick inte.");
    } finally {
      setBusy(false);
    }
  };
  const external = now.external_clock;
  return (
    <section id="klockan" className="kort" aria-labelledby="klockan-rubrik">
      <h2 id="klockan-rubrik">Klockan</h2>
      <p className="liten">Drifts egen klocka, eller FastClock som Drift följer. Skärmar, boxar och TKL läser tiden från Hubben som förut. Gäller den här träffen.</p>
      {external && (
        <p className={"liten" + (external.available ? "" : " varning")} id="klockan-lage" role="status">
          {external.available ? `Följer FastClock · ${external.name}.` : external.warning}
        </p>
      )}
      {!admin ? (
        <p className="liten">Logga in som trafikledare för att byta klocka.</p>
      ) : (
        <form id="klockan-form" className="formular" onSubmit={(event) => void save(event)}>
          <fieldset className="val">
            <legend>Klocka</legend>
            <label className="kryss">
              <input type="radio" name="klocka" value="drift" checked={source === "drift"} onChange={() => setSource("drift")} /> Drifts klocka
            </label>
            <label className="kryss">
              <input type="radio" name="klocka" value="fastclock" checked={source === "fastclock"} onChange={() => setSource("fastclock")} /> FastClock
            </label>
          </fieldset>
          {source === "fastclock" && (
            <>
              <label>
                Klockans namn i FastClock <input id="klockan-namn" maxLength={100} value={name} autoComplete="off" onChange={(event) => setName(event.target.value)} />
              </label>
              <label>
                FastClocks adress <input id="klockan-adress" className="tm-mono" maxLength={255} value={url} autoComplete="off" spellCheck={false} onChange={(event) => setUrl(event.target.value)} />
              </label>
              <label>
                Användare för start och stopp härifrån <input id="klockan-anvandare" maxLength={100} value={user} autoComplete="off" placeholder="tomt: bara följa" onChange={(event) => setUser(event.target.value)} />
              </label>
              {user && (
                <label>
                  Lösenord <input id="klockan-losen" type="password" maxLength={256} autoComplete="off" placeholder={state?.has_password ? "oförändrat" : ""} value={password} onChange={(event) => setPassword(event.target.value)} />
                </label>
              )}
              <label>
                Läs var{" "}
                <select id="klockan-intervall" value={every} onChange={(event) => setEvery(Number(event.target.value))}>
                  {[2, 5, 10, 30].map((seconds) => (
                    <option key={seconds} value={seconds}>{`${seconds} sekunder`}</option>
                  ))}
                </select>
              </label>
              <p className="liten">Tiden och hastigheten ändras i FastClock. Utan svar står klockan kvar på senaste tiden, med en varning i Nu.</p>
            </>
          )}
          <div className="installningsfot">
            <span className="liten" role="status" id="klockan-said">
              {said}
            </span>
            <button type="submit" className="primar" disabled={busy || (source === "fastclock" && !name.trim())}>
              Spara
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

export function Natet({ admin, initial }: { admin: boolean; initial?: WifiStatus }) {
  const [state, setState] = useState<WifiStatus | null>(initial ?? null);
  const [editing, setEditing] = useState<string | null>(null);
  const [ssid, setSsid] = useState("");
  const [security, setSecurity] = useState<"wpa2" | "wpa3" | "open">("wpa2");
  const [password, setPassword] = useState("");
  const [hidden, setHidden] = useState(false);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  const trial = state?.trial ?? null;
  useEffect(() => {
    if (!admin || initial) return;
    const read = () => void hub.wifi().then(setState, () => undefined);
    read();
    const timer = window.setInterval(read, trial ? 2000 : 10000);
    return () => window.clearInterval(timer);
  }, [admin, initial, trial]);
  const act = async (doing: () => Promise<WifiStatus>, done: string) => {
    setBusy(true);
    setSaid("");
    try {
      setState(await doing());
      setSaid(done);
      return true;
    } catch (error) {
      setSaid(error instanceof Error ? error.message : "Det gick inte.");
      return false;
    } finally {
      setBusy(false);
    }
  };
  const clear = () => {
    setEditing(null);
    setSsid("");
    setPassword("");
    setHidden(false);
    setSecurity("wpa2");
  };
  const edit = (profile: WifiProfile) => {
    setEditing(profile.uuid);
    setSsid(profile.ssid);
    setSecurity(profile.security === "unsupported" ? "wpa2" : profile.security);
    setHidden(profile.hidden);
    setPassword("");
  };
  const save = async () => {
    const change = { uuid: editing, ssid: ssid.trim(), security, password, hidden };
    if (await act(() => hub.saveWifi(change), `${ssid.trim()} är sparat. Det ändrar inte nätet Pi:n är på nu.`)) clear();
  };
  const profiles = state?.profiles ?? [];
  const editable = profiles.filter((profile) => profile.editable);
  const move = (uuid: string, step: number) => {
    const ids = editable.map((profile) => profile.uuid);
    const at = ids.indexOf(uuid);
    if (at + step < 0 || at + step >= ids.length) return;
    const [moved] = ids.splice(at, 1);
    if (moved) ids.splice(at + step, 0, moved);
    void act(() => hub.wifiAction("order", { uuids: ids }), "Ordningen är sparad. Den gäller nästa gång Pi:n startar.");
  };
  const device = state?.devices?.[0]?.interface ?? "wlan0";
  const manage = Boolean(state?.can_manage) && !trial && !state?.recovering;
  const tried = trial ? profiles.find((profile) => profile.uuid === trial.uuid) : undefined;
  const connect = (profile: WifiProfile) => {
    const warned = window.confirm(`Pi:n byter till ${profile.ssid}. Webbläsaren och boxarna kan tappa kontakten, och Pi:n kan få en ny adress. Anslut igen och tryck Behåll anslutningen inom 90 sekunder, annars går Pi:n tillbaka till nätet den har nu.`);
    if (warned) void act(() => hub.wifiAction("connect", { uuid: profile.uuid, interface: device }), `Provar ${profile.ssid}.`);
  };
  return (
    <section id="natet" className="kort" aria-labelledby="natet-rubrik">
      <h2 id="natet-rubrik">Pi:ns nät</h2>
      <p className="liten">De nät Pi:n själv ansluter till. Det är inte träffens Wi-Fi, som deltagarna ser. Näten och deras lösenord stannar på Pi:n.</p>
      {!admin ? (
        <p className="liten">Logga in med hubbens PIN-kod för att se Pi:ns nät.</p>
      ) : !state ? (
        <p className="liten">Läser Pi:ns nät …</p>
      ) : !state.supported ? (
        <p className="liten" id="natet-saknas">{state.reason ?? "Pi:ns nät ställs in på en Raspberry Pi."}</p>
      ) : (
        <>
          {trial && (
            <div className="provanslutning" role="status" id="natet-prov">
              <p>
                <b>{`Provar ${tried?.ssid ?? "ett nytt nät"}.`}</b> {`Behåll anslutningen inom ${trial.remaining} sekunder, annars går Pi:n tillbaka till nätet före.`}
              </p>
              {trial.token ? (
                <span className="rad">
                  <button type="button" disabled={busy} onClick={() => void act(() => hub.wifiAction("rollback", { token: trial.token ?? "" }), "Pi:n är tillbaka på nätet före.")}>
                    Återställ nu
                  </button>
                  <button type="button" className="primar" disabled={busy} onClick={() => void act(() => hub.wifiAction("confirm", { token: trial.token ?? "" }), "Pi:n behåller det nya nätet.")}>
                    Behåll anslutningen
                  </button>
                </span>
              ) : (
                <p className="liten">Provet startades av en annan inloggning.</p>
              )}
            </div>
          )}
          {state.recovering && !trial && <p className="liten varning">Pi:n går tillbaka till nätet före. Vänta en stund.</p>}
          {!state.can_manage && <p className="liten" id="natet-las">Ändra Pi:ns nät i webbläsaren på Pi:n, eller över HTTPS, så att ett lösenord aldrig går okrypterat över träffens nät.</p>}
          <ol className="moln natlista" id="natlista">
            {profiles.map((profile) => (
              <li key={profile.uuid}>
                <div>
                  <b>{profile.ssid}</b>
                  <div className="liten">
                    {[SECURITY.find(([value]) => value === profile.security)?.[1] ?? "Kan inte hanteras här", profile.hidden ? "dolt" : "", profile.active ? "anslutet nu" : "", !profile.autoconnect ? "ansluter inte av sig själv" : ""].filter(Boolean).join(" · ")}
                  </div>
                </div>
                {manage && profile.editable && (
                  <span className="rad">
                    <button type="button" aria-label={`Flytta upp ${profile.ssid}`} disabled={busy || editable[0]?.uuid === profile.uuid} onClick={() => move(profile.uuid, -1)}>
                      ↑
                    </button>
                    <button type="button" aria-label={`Flytta ned ${profile.ssid}`} disabled={busy || editable[editable.length - 1]?.uuid === profile.uuid} onClick={() => move(profile.uuid, 1)}>
                      ↓
                    </button>
                    {!profile.active && (
                      <>
                        <button type="button" disabled={busy} onClick={() => edit(profile)}>
                          Ändra
                        </button>
                        <button type="button" disabled={busy} onClick={() => window.confirm(`Ta bort ${profile.ssid} från Pi:n?`) && void act(() => hub.wifiAction("delete", { uuid: profile.uuid }), `${profile.ssid} är borttaget.`)}>
                          Ta bort
                        </button>
                        <button type="button" className="primar" disabled={busy} onClick={() => connect(profile)}>
                          Anslut nu
                        </button>
                      </>
                    )}
                  </span>
                )}
              </li>
            ))}
          </ol>
          {manage && (
            <>
              <div className="installning">
                <label htmlFor="wifi-ssid" className="etikett">
                  {editing ? "Ändra nätet" : "Lägg till ett nät"}
                </label>
                <input id="wifi-ssid" list="wifi-near" value={ssid} maxLength={32} onChange={(event) => setSsid(event.target.value)} autoComplete="off" spellCheck={false} placeholder="Nätets namn (SSID)" />
                <button type="button" disabled={busy} onClick={() => void act(() => hub.wifiAction("scan", { interface: device }), "Pi:n söker efter nät i närheten.")}>
                  Sök nät
                </button>
                <datalist id="wifi-near">
                  {(state.nearby ?? []).map((near) => (
                    <option key={`${near.interface}-${near.ssid}`} value={near.ssid} />
                  ))}
                </datalist>
              </div>
              <div className="installning">
                <span className="etikett">Säkerhet</span>
                <Chips label="Nätets säkerhet">
                  {SECURITY.map(([value, label]) => (
                    <Chip key={value} label={label} pressed={security === value} onClick={() => setSecurity(value as "wpa2" | "wpa3" | "open")} />
                  ))}
                </Chips>
              </div>
              {security !== "open" && (
                <div className="installning">
                  <label htmlFor="wifi-password" className="etikett">
                    Lösenord
                  </label>
                  <input id="wifi-password" type="password" value={password} maxLength={63} onChange={(event) => setPassword(event.target.value)} autoComplete="off" />
                  <span className="liten">{editing ? "tomt behåller det sparade, om namn och säkerhet är desamma" : "8–63 tecken; stannar på Pi:n och visas aldrig igen"}</span>
                </div>
              )}
              <div className="installning">
                <span className="etikett">Dolt nät</span>
                <label className="rad">
                  <input type="checkbox" checked={hidden} onChange={(event) => setHidden(event.target.checked)} /> Nätet syns inte i listan
                </label>
              </div>
              <div className="installningsfot">
                <span className="liten" role="status" id="natet-said">
                  {said || "Att spara byter inte nätet. Anslut nu provar det i 90 sekunder."}
                </span>
                <span className="rad">
                  {editing && (
                    <button type="button" disabled={busy} onClick={clear}>
                      Avbryt
                    </button>
                  )}
                  <button id="wifi-save" type="button" className="primar" disabled={busy || !ssid.trim()} onClick={() => void save()}>
                    Spara nätet
                  </button>
                </span>
              </div>
            </>
          )}
          {!manage && said && (
            <p className="liten" role="status">
              {said}
            </p>
          )}
        </>
      )}
    </section>
  );
}

/** Den här hubben → Molnet (SYNK-02, SYNK-10): a Pi follows meets planned in the cloud. The
 * administrator there gives a six-digit code under Versioner; the Pi gets a key of its own,
 * which is never shown, and fetches each version the moment it is published. */
export function Molnet({ admin, initial }: { admin: boolean; initial?: CloudLink[] }) {
  const [clouds, setClouds] = useState<CloudLink[] | null>(initial ?? null);
  const [address, setAddress] = useState("https://test.hub.trainmeet.app");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  useEffect(() => {
    if (!admin || initial) return;
    const read = () => void hub.cloud().then(setClouds, () => undefined);
    read();
    const timer = window.setInterval(read, 5000);
    return () => window.clearInterval(timer);
  }, [admin, initial]);
  const act = async (doing: () => Promise<CloudLink[]>, done: string) => {
    setBusy(true);
    setSaid("");
    try {
      setClouds(await doing());
      setSaid(done);
      return true;
    } catch (error) {
      setSaid(error instanceof Error ? error.message : "Det gick inte.");
      return false;
    } finally {
      setBusy(false);
    }
  };
  const link = async () => {
    if (await act(() => hub.connectCloud({ address: address.trim(), code: code.trim() }), "Pi:n följer träffen.")) setCode("");
  };
  return (
    <section id="molnet" className="kort" aria-labelledby="molnet-rubrik">
      <h2 id="molnet-rubrik">Molnet</h2>
      <p className="liten">En Pi följer en träff som planeras i molnhubben och hämtar varje version när den publiceras. Pi:n ringer alltid ut; ingen port öppnas på träffen.</p>
      {!admin ? (
        <p className="liten">Logga in med hubbens PIN-kod för att koppla Pi:n till molnet.</p>
      ) : (
        <>
          {clouds && clouds.length > 0 && (
            <ul className="moln" id="clouds">
              {clouds.map((cloud) => (
                <li key={cloud.meet}>
                  <div>
                    <b>{cloud.meet_name}</b>
                    <div className="liten">{`${cloud.cloud_name} · ${cloud.address} · ${cloud.versions === 1 ? "1 version" : `${cloud.versions} versioner`} · hörd ${when(cloud.heard)}`}</div>
                    <div className="liten">{cloud.home_here ? "Träffens hem är här: planera och publicera här, molnet följer." : `Träffens hem är ${cloud.cloud_name}: där planeras och publiceras den.`}</div>
                    {cloud.problem && <div className="liten varning">{cloud.problem}</div>}
                  </div>
                  <span className="rad">
                    {cloud.home_here ? (
                      <button type="button" className="primar" disabled={busy} onClick={() => void act(() => hub.handBack(cloud.meet), `${cloud.meet_name} är tillbaka i ${cloud.cloud_name}, med det som ändrades här.`)}>
                        Lämna tillbaka
                      </button>
                    ) : (
                      <>
                        <button type="button" disabled={busy} onClick={() => void act(() => hub.takeHome(cloud.meet), `Träffens hem är nu här. ${cloud.cloud_name} följer.`)}>
                          Ta hem träffen hit
                        </button>
                        <button type="button" disabled={busy} onClick={() => void act(() => hub.disconnectCloud(cloud.meet), `${cloud.meet_name} följs inte längre. Versionerna finns kvar.`)}>
                          Koppla bort
                        </button>
                      </>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <div className="installning">
            <label htmlFor="cloud-address" className="etikett">
              Molnhubben
            </label>
            <input id="cloud-address" className="tm-mono" value={address} onChange={(event) => setAddress(event.target.value)} autoComplete="off" spellCheck={false} />
          </div>
          <div className="installning">
            <label htmlFor="cloud-code" className="etikett">
              Kod
            </label>
            <input id="cloud-code" className="tm-mono" inputMode="numeric" maxLength={6} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))} autoComplete="off" placeholder="sex siffror" />
            <span className="liten">från Planering → Versioner → Koppla en Pi i molnhubben; gäller en gång i 15 minuter</span>
          </div>
          <div className="installningsfot">
            <span className="liten" role="status" id="cloud-said">
              {busy ? "Kopplar …" : said}
            </span>
            <button id="cloud-connect" type="button" className="primar" disabled={busy || code.length !== 6 || !address.trim()} onClick={() => void link()}>
              Koppla till molnet
            </button>
          </div>
        </>
      )}
    </section>
  );
}

const FORMATS: [AiServiceChange["format"], string, string][] = [
  ["claude", "Claudes API", "https://api.anthropic.com"],
  ["chat", "Det vanliga chatt-API:t", "https://"],
];

const PIN = /^[0-9]{6,12}$/;

/** På den här hubben (SYNK-07): the hub's name, and a new PIN with the current one first. A
 * forgotten PIN is set with physical access to the Pi (H46, SYNK-27). */
export function NamnOchPin({ hubName, onRename, onPin }: SettingsProps) {
  const [name, setName] = useState(hubName);
  const [pin, setPin] = useState("");
  const [newPin, setNewPin] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setName(hubName), [hubName]);
  const tidy = name.split(/\s+/).filter(Boolean).join(" ");
  const differ = newPin !== "" && again !== "" && newPin !== again;
  const pinReady = PIN.test(pin) && PIN.test(newPin) && newPin === again;
  const rename = async () => {
    setBusy(true);
    await onRename?.(tidy);
    setBusy(false);
  };
  const change = async () => {
    setBusy(true);
    const done = await (onPin?.(pin, newPin) ?? Promise.resolve(false));
    setBusy(false);
    if (done) [setPin, setNewPin, setAgain].forEach((clear) => clear(""));
  };
  return (
    <>
      <div className="installning">
        <label htmlFor="hub-name" className="etikett">
          Namn
        </label>
        <input id="hub-name" value={name} maxLength={40} onChange={(event) => setName(event.target.value)} autoComplete="off" />
        <button id="hub-rename" type="button" disabled={busy || !tidy || tidy === hubName} onClick={() => void rename()}>
          Spara namnet
        </button>
      </div>
      <fieldset className="pinbyte">
        <legend className="etikett">PIN-kod</legend>
        <div className="installning">
          <label htmlFor="pin-now" className="etikett">
            Nuvarande
          </label>
          <input id="pin-now" type="password" inputMode="numeric" autoComplete="current-password" value={pin} onChange={(event) => setPin(event.target.value)} />
        </div>
        <div className="installning">
          <label htmlFor="pin-new" className="etikett">
            Ny
          </label>
          <input id="pin-new" type="password" inputMode="numeric" autoComplete="new-password" value={newPin} onChange={(event) => setNewPin(event.target.value)} aria-describedby="pin-hint" />
        </div>
        <div className="installning">
          <label htmlFor="pin-again" className="etikett">
            Ny igen
          </label>
          <input id="pin-again" type="password" inputMode="numeric" autoComplete="new-password" value={again} onChange={(event) => setAgain(event.target.value)} aria-invalid={differ} aria-describedby="pin-hint" />
        </div>
        <div className="installningsfot">
          <span className="liten" id="pin-hint" role="status">
            {differ ? "De två nya PIN-koderna är olika." : "6–12 siffror. Alla andra inloggningar slutar gälla."}
          </span>
          <button id="pin-change" type="button" className="primar" disabled={busy || !pinReady} onClick={() => void change()}>
            Byt PIN
          </button>
        </div>
        <p className="liten">Glömd PIN-kod: kör python -m hub.pin på Pi:n, eller lägg en fil som heter trainmeet-ny-pin.txt, med den nya PIN-koden på första raden, på ett USB-minne och sätt i det i Pi:n.</p>
      </fieldset>
    </>
  );
}

/** Den här hubben → AI (H58, H59, H70): the service that transcribes scanned pages and pictures
 * in Planering. The hub checks that the model reads a picture before it keeps the setting; the
 * key is sent once and never shown again. */
export function EgenAi({ admin, ai, onAi, onAiOff }: SettingsProps) {
  const [format, setFormat] = useState<AiServiceChange["format"]>(ai?.format ?? "claude");
  const [address, setAddress] = useState(ai?.address ?? "https://api.anthropic.com");
  const [model, setModel] = useState(ai?.model ?? "");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const connect = async () => {
    setBusy(true);
    const kept = await (onAi?.({ format, address, model, key: key || null }) ?? Promise.resolve(false));
    setBusy(false);
    if (kept) setKey("");
  };
  return (
    <section id="ai" className="kort" aria-labelledby="ai-rubrik">
      <h2 id="ai-rubrik">AI</h2>
      <p className="liten">Egen AI skriver av skannade sidor och bilder när underlag läggs till i Planering. Den betalas av din AI-tjänst; TrainMeet drar inga tokens. Underlag med text läses alltid med kod, utan AI.</p>
      {!admin ? (
        <p className="liten" id="ai-state">{ai === undefined ? "Logga in med hubbens PIN-kod för att se AI-tjänsten." : ai ? `${ai.model} är inkopplad.` : "Ingen egen AI är inkopplad."}</p>
      ) : (
        <>
          <dl className="bygge" id="ai-state">
            <dt>Läge</dt>
            <dd>{ai ? `Inkopplad · ${ai.model}` : "Ingen egen AI är inkopplad"}</dd>
            {ai?.checked && (
              <>
                <dt>Provad</dt>
                <dd>{`Läste provbilden ${new Date(ai.checked).toLocaleString("sv-SE", { dateStyle: "short", timeStyle: "short" })}`}</dd>
              </>
            )}
          </dl>
          <div className="installning">
            <span className="etikett">Format</span>
            <Chips label="Tjänstens format">
              {FORMATS.map(([value, label, start]) => (
                <Chip key={value} label={label} pressed={format === value} onClick={() => (setFormat(value), FORMATS.some(([, , other]) => other === address) && setAddress(start))} />
              ))}
            </Chips>
          </div>
          <div className="installning">
            <label htmlFor="ai-address" className="etikett">
              Adress
            </label>
            <input id="ai-address" className="tm-mono" value={address} onChange={(event) => setAddress(event.target.value)} autoComplete="off" spellCheck={false} />
          </div>
          <div className="installning">
            <label htmlFor="ai-model" className="etikett">
              Modell
            </label>
            <input id="ai-model" className="tm-mono" value={model} onChange={(event) => setModel(event.target.value)} autoComplete="off" spellCheck={false} />
            <span className="liten">en modell som kan läsa bilder</span>
          </div>
          <div className="installning">
            <label htmlFor="ai-key" className="etikett">
              Nyckel
            </label>
            <input id="ai-key" type="password" className="tm-mono" value={key} onChange={(event) => setKey(event.target.value)} autoComplete="off" spellCheck={false} placeholder={ai?.key_set ? "Sparad" : "Klistra in nyckeln"} />
            <span className="liten">stannar i hubben, visas aldrig igen och skrivs aldrig i loggen; skriv en ny för att byta</span>
          </div>
          <div className="installningsfot">
            <span className="liten" role="status">
              {busy ? "Provar att modellen läser en bild …" : "Hubben provar att modellen läser en bild innan den sparas."}
            </span>
            <span className="rad">
              {ai && (
                <button id="ai-off" type="button" disabled={busy} onClick={() => onAiOff?.()}>
                  Koppla bort
                </button>
              )}
              <button id="ai-connect" type="button" className="primar" disabled={busy || !model.trim() || !address.trim() || (!key && !ai?.key_set)} onClick={() => void connect()}>
                {ai ? "Spara och prova" : "Koppla in och prova"}
              </button>
            </span>
          </div>
        </>
      )}
    </section>
  );
}

/** I paketet: what the version says, read here and changed in Planering. */
function Meet({ now }: { now: Now }) {
  const planned = now.meet_id !== "provbanan";
  return (
    <section id="traffen" className="kort" aria-labelledby="traffen-rubrik">
      <h2 id="traffen-rubrik">Träffen och trafikdagarna</h2>
      <p className="liten">Står i paketet och följer versionen.</p>
      <dl className="bygge">
        <dt>Träff</dt>
        <dd>{now.name}</dd>
        <dt>Version</dt>
        <dd>{planned ? now.version : "Provbanan, för prov"}</dd>
        <dt>Trafikdag</dt>
        <dd>{dayName(now.traffic_day)}</dd>
        <dt>Speldygn</dt>
        <dd>{`dag ${now.game_day}`}</dd>
      </dl>
      <p className="liten">
        {planned ? (
          <>
            Ändras i Planering: publicera en ny version under <a href={`/planering/${encodeURIComponent(now.meet_id)}/versioner`}>Versioner</a> och byt träff.
          </>
        ) : (
          "Provbanan är densamma på alla hubbar."
        )}
      </p>
    </section>
  );
}

const sameSettings = (a: AutomationSettings, b: AutomationSettings) => (Object.keys(a) as (keyof AutomationSettings)[]).every((key) => a[key] === b[key]);

/** A new scenario key: the same key gives the same disturbances (F15). */
export function newSeed(random: () => number = Math.random): string {
  const letters = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const part = () => Array.from({ length: 4 }, () => letters[Math.floor(random() * letters.length)]).join("");
  return `${part()}-${part()}`;
}

/** Under träffen: Automatiken (F14, F15, H42), changed as a whole and saved with Spara. */
function Automatik({ admin, now, automation, automationSaved, onAutomation }: SettingsProps & { now: Now }) {
  const saved = automation?.settings ?? null;
  const [draft, setDraft] = useState<AutomationSettings | null>(saved);
  const [filledAt, setFilledAt] = useState(automationSaved);
  // The form starts from what the hub has: when it first comes, and after each save.
  if (saved && (!draft || filledAt !== automationSaved)) {
    setDraft(saved);
    setFilledAt(automationSaved);
  }
  if (!admin) {
    return (
      <section id="automatik" className="kort" aria-labelledby="automatik-rubrik">
        <h2 id="automatik-rubrik">Automatik</h2>
        <p className="liten">Logga in med hubbens PIN-kod för att se och ändra automatiken.</p>
      </section>
    );
  }
  if (!saved || !draft) {
    return (
      <section id="automatik" className="kort" aria-labelledby="automatik-rubrik">
        <h2 id="automatik-rubrik">Automatik</h2>
        <p className="liten">Läser automatiken …</p>
      </section>
    );
  }
  const change = (part: Partial<AutomationSettings>) => setDraft({ ...draft, ...part });
  const changed = !sameSettings(draft, saved);
  return (
    <section id="automatik" className="kort" aria-labelledby="automatik-rubrik">
      <h2 id="automatik-rubrik">Automatik</h2>
      <p className="liten">{`Gäller ${now.name} medan den körs. En driftplats som ingen box eller TKL arbetar med sköts av automatiken.`}</p>
      <div className="installning">
        <span className="etikett">Automatiken</span>
        <Chips label="Automatiken">
          <Chip label="På" pressed={draft.enabled} onClick={() => change({ enabled: true })} />
          <Chip label="Av" pressed={!draft.enabled} onClick={() => change({ enabled: false })} />
        </Chips>
      </div>
      <div className="installning">
        <label htmlFor="set-lost" className="etikett">
          Tar över en driftplats
        </label>
        <select id="set-lost" value={draft.lost_contact_minutes} onChange={(event) => change({ lost_contact_minutes: Number(event.target.value) as AutomationSettings["lost_contact_minutes"] })}>
          {LOST.map(([minutes, label]) => (
            <option key={minutes} value={minutes}>
              {minutes ? `efter ${label}` : label}
            </option>
          ))}
        </select>
        <span className="liten">efter Kontakt saknas</span>
      </div>
      <div className="installning">
        <label htmlFor="set-answer" className="etikett">
          Klartecken efter
        </label>
        <span>
          <input id="set-answer" type="number" min={0} max={30} className="tal" value={draft.answer_seconds} onChange={(event) => change({ answer_seconds: Number(event.target.value) })} /> s
        </span>
      </div>
      <div className="installning">
        <label htmlFor="set-late" className="etikett">
          Försenat tåg står
        </label>
        <span>
          <input id="set-late" type="number" min={1} max={10} className="tal" value={draft.late_stop_minutes} onChange={(event) => change({ late_stop_minutes: Number(event.target.value) })} /> min
        </span>
      </div>
      <div className="installning">
        <span className="etikett">Undanställning</span>
        <span className="rad">
          <label>
            <input id="set-stabling" type="checkbox" checked={draft.stabling} onChange={(event) => change({ stabling: event.target.checked })} /> efter
          </label>
          <input id="set-stabling-minutes" type="number" min={1} max={60} className="tal" aria-label="Undanställning efter minuter" value={draft.stabling_minutes} onChange={(event) => change({ stabling_minutes: Number(event.target.value) })} /> min
        </span>
        <span className="liten">tåg som slutar ställs undan och släpper spåret</span>
      </div>
      <div className="installning">
        <span className="etikett">Störningar</span>
        <Chips label="Störningar">
          {Object.entries(DISTURBANCES).map(([key, label]) => (
            <Chip key={key} label={label} pressed={draft.disturbance === key} onClick={() => change({ disturbance: key as AutomationSettings["disturbance"] })} />
          ))}
        </Chips>
      </div>
      <div className="installning">
        <span className="etikett">Störningsplats</span>
        <Chips label="Störningsplats">
          {Object.entries(WHERE).map(([key, label]) => (
            <Chip key={key} label={label} pressed={draft.where === key} onClick={() => change({ where: key as AutomationSettings["where"] })} />
          ))}
        </Chips>
      </div>
      <div className="installning">
        <label htmlFor="set-seed" className="etikett">
          Scenarionyckel
        </label>
        <span className="rad">
          <input id="set-seed" maxLength={40} className="tm-mono" value={draft.seed} onChange={(event) => change({ seed: event.target.value })} />
          <button type="button" onClick={() => change({ seed: newSeed() })}>
            Ny nyckel
          </button>
        </span>
        <span className="liten">samma nyckel ger samma störningar</span>
      </div>
      <div className="installningsfot">
        <span id="settings-state" className="liten" role="status">
          {changed ? "Ändrat, inte sparat" : "Inget ändrat"}
        </span>
        <span className="rad">
          <button type="button" disabled={!changed} onClick={() => setDraft(saved)}>
            Avbryt
          </button>
          <button id="settings-save" type="button" className="primar" disabled={!changed} onClick={() => onAutomation?.({ ...draft, seed: draft.seed.trim() })}>
            Spara
          </button>
        </span>
      </div>
      <p className="liten">Ändrar aldrig versionen. Undanställningen räknas i spelminuter.</p>
    </section>
  );
}

/** Under träffen: Dygnsskiftet (F7), by hand by default or automatic, and its time: empty is an
 * hour before the new day's first train, never before midnight. Saved with Spara. */
function Dygnsskifte({ admin, now, onDay }: SettingsProps & { now: Now }) {
  const day = now.day;
  const saved = { mode: day?.mode ?? "manual", time: day?.fixed ? day.time : "" };
  const key = `${saved.mode}|${saved.time}`;
  const [draft, setDraft] = useState(saved);
  const [filledFrom, setFilledFrom] = useState(key);
  // The form starts from what the hub has, and again when that changes.
  if (filledFrom !== key) {
    setDraft(saved);
    setFilledFrom(key);
  }
  if (!admin || !day) {
    return (
      <section id="dygnsskifte" className="kort" aria-labelledby="dygnsskifte-rubrik">
        <h2 id="dygnsskifte-rubrik">Dygnsskifte</h2>
        <p className="liten">Logga in med hubbens PIN-kod för att se och ändra dygnsskiftet.</p>
      </section>
    );
  }
  const changed = draft.mode !== saved.mode || draft.time !== saved.time;
  return (
    <section id="dygnsskifte" className="kort" aria-labelledby="dygnsskifte-rubrik">
      <h2 id="dygnsskifte-rubrik">Dygnsskifte</h2>
      <p className="liten">När nästa speldygn börjar. Natten hör till dygnet före fram till skiftet.</p>
      <div className="installning">
        <span className="etikett">Ny dag</span>
        <Chips label="Ny dag">
          <Chip label="Manuellt" pressed={draft.mode === "manual"} onClick={() => setDraft({ ...draft, mode: "manual" })} />
          <Chip label="Automatiskt" pressed={draft.mode === "automatic"} onClick={() => setDraft({ ...draft, mode: "automatic" })} />
        </Chips>
        <span className="liten">{draft.mode === "manual" ? "Trafikledningen trycker Starta ny dag i Nu" : "startar av sig själv, och väntar högst 30 minuter på tåg som är ute"}</span>
      </div>
      <div className="installning">
        <label htmlFor="set-day-time" className="etikett">
          Tid
        </label>
        <input id="set-day-time" type="time" step={60} value={draft.time} onChange={(event) => setDraft({ ...draft, time: event.target.value })} />
        <span className="liten">tomt: en timme före första tåget, aldrig före midnatt</span>
      </div>
      <div className="installningsfot">
        <span id="day-settings-state" className="liten" role="status">
          {changed ? "Ändrat, inte sparat" : "Inget ändrat"}
        </span>
        <span className="rad">
          <button type="button" disabled={!changed} onClick={() => setDraft(saved)}>
            Avbryt
          </button>
          <button id="day-save" type="button" className="primar" disabled={!changed} onClick={() => onDay?.({ mode: draft.mode, time: draft.time || null })}>
            Spara
          </button>
        </span>
      </div>
    </section>
  );
}

/** Under träffen: the places' telephone numbers (TRAFIK-06, H30): the meet's game numbers, read
 * by TKL and the app in their phone list. Changed here during the meet; Planering keeps the
 * package's. Empty takes a number away. */
function Telefon({ admin, now, phones, onPhones }: SettingsProps & { now: Now }) {
  const saved = Object.fromEntries((phones ?? []).map((item) => [item.place, item.phone ?? ""]));
  const key = JSON.stringify(saved);
  const [draft, setDraft] = useState<Record<string, string>>(saved);
  const [filledFrom, setFilledFrom] = useState(key);
  if (filledFrom !== key) {
    setDraft(saved);
    setFilledFrom(key);
  }
  if (!admin || !phones) {
    return (
      <section id="telefon" className="kort" aria-labelledby="telefon-rubrik">
        <h2 id="telefon-rubrik">Telefonnummer</h2>
        <p className="liten">{admin ? "Läser numren …" : "Logga in med hubbens PIN-kod för att se och ändra telefonnumren."}</p>
      </section>
    );
  }
  const changes = phones.filter((item) => (draft[item.place] ?? "").trim() !== (item.phone ?? "")).map((item) => ({ place: item.place, phone: (draft[item.place] ?? "").trim() || null }));
  return (
    <section id="telefon" className="kort" aria-labelledby="telefon-rubrik">
      <h2 id="telefon-rubrik">Telefonnummer</h2>
      <p className="liten">Träffens leknummer per driftplats. TKL och appen visar dem i telefonlistan.</p>
      {now.places.map((place) => (
        <div className="installning" key={place.place}>
          <label htmlFor={`phone-${place.place}`} className="etikett">
            {`${place.name} (${place.code})`}
          </label>
          <input id={`phone-${place.place}`} inputMode="tel" maxLength={24} autoComplete="off" className="tal" value={draft[place.place] ?? ""} onChange={(event) => setDraft({ ...draft, [place.place]: event.target.value })} />
        </div>
      ))}
      <div className="installningsfot">
        <span id="phone-state" className="liten" role="status">
          {changes.length ? `${changes.length} ändrade, inte sparade` : "Inget ändrat"}
        </span>
        <span className="rad">
          <button type="button" disabled={!changes.length} onClick={() => setDraft(saved)}>
            Avbryt
          </button>
          <button id="phone-save" type="button" className="primar" disabled={!changes.length} onClick={() => onPhones?.(changes)}>
            Spara
          </button>
        </span>
      </div>
      <p className="liten">Ändringen gäller träffen som körs. Paketets nummer ändras i Planering.</p>
    </section>
  );
}


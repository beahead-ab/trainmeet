// Träffar: the owner's own meets, the pack list and the three steps (#55, CAT-174–CAT-183).
// A step is ticked by tapping the vehicle's tag, with Web NFC as on the Blippa page, or by a
// press on its row (CAT-176). Each step says how many are done (CAT-178), and at Hem what is
// missing stands first, with its last tick and what someone who found it said (CAT-179, CAT-180).
import { linkClick } from "@trainmeet/design";
import { useEffect, useId, useRef, useState } from "react";
import { api, STEPS, type NewTrip, type Trip, type TripRow, type TripStep, type TripSummary, type Vehicle } from "./api";
import { Crumbs, dateText, Dialog, ErrorLine, problemText, subtitle, timeText, title, type Ctx, type T } from "./common";
import { scan } from "./nfc";
import { meetPath, PATHS, uidFrom } from "./routes";
import { readerHere, type Reader } from "./TapPage";

export const stepName = (t: T, step: TripStep) => t(`step_${step}`);

export function tickOf(row: TripRow, step: TripStep) {
  return row.ticks.find((tick) => tick.step === step) ?? null;
}

/** When, and in which step, the vehicle was last ticked (CAT-179). */
export function lastLine(ctx: Ctx, row: TripRow): string {
  const { t, language } = ctx;
  const last = row.last;
  if (!last) return t("neverTicked");
  return t(last.by === "tap" ? "lastTapped" : "lastPressed", { step: stepName(t, last.step), time: timeText(language, last.at) });
}

/** What the row says in a step: its tick with the time, or where the vehicle is (CAT-177). */
export function rowLine(ctx: Ctx, row: TripRow, step: TripStep): string {
  const { t, language } = ctx;
  const vehicle = row.vehicle;
  const tick = tickOf(row, step);
  if (vehicle.state === "lent") return t("tripLent", { name: vehicle.lending?.to ?? "" });
  if (step === "pack") {
    if (tick) return t("tripPacked", { time: timeText(language, tick.at) });
    return vehicle.place_name ? t("tripLiesIn", { place: vehicle.place_name }) : t("tripAtHome");
  }
  if (step === "arrive") {
    if (tick) return t("tripOnLayout", { time: timeText(language, tick.at) });
    return tickOf(row, "pack") ? t("tripStillPacked") : t("tripNotPacked");
  }
  if (tick) return vehicle.place_name ? t("tripInBoxAt", { place: vehicle.place_name }) : t("tripInBox");
  return lastLine(ctx, row);
}

/** The meet in the list: the date, how many go, and how far the trip is, or whether all came home. */
export function meetLine(ctx: Ctx, meet: TripSummary): string {
  const { t, language } = ctx;
  const line = t("meetLine", { date: dateText(language, meet.date), n: meet.vehicles });
  if (!meet.vehicles) return line;
  const done = meet.done[meet.step] ?? 0;
  if (!meet.archived_at) return `${line} · ${t(`stepCount_${meet.step}`, { n: done, of: meet.vehicles })}`;
  const home = meet.done["home"] ?? 0;
  return `${line} · ${home >= meet.vehicles ? t("allCameHome") : t("cameHome", { n: home, of: meet.vehicles })}`;
}

/** The fleet's simulated tags, to tap without hardware in the test environment (CAT-96). */
export function simulatedTags(t: T, fleet: Vehicle[] | null): { uid: string; label: string }[] {
  return (fleet ?? []).flatMap((vehicle) =>
    (vehicle.tags ?? []).filter((tag) => tag.kind === "sim").map((tag) => ({ uid: tag.uid, label: t("simulatedTap", { tag: tag.name, name: title(t, vehicle) }) })),
  );
}

// --- The list of meets ---------------------------------------------------------------------

export function MeetsView({ ctx, meets, error, onNew }: { ctx: Ctx; meets: TripSummary[] | null; error: string | null; onNew?: (template: TripSummary | null) => void }) {
  const { t, navigate } = ctx;
  const active = meets?.filter((meet) => !meet.archived_at) ?? [];
  const earlier = meets?.filter((meet) => meet.archived_at) ?? [];
  const link = (meet: TripSummary) => (
    <a className="cat-fordon" href={meetPath(meet.id)} onClick={linkClick(navigate, meetPath(meet.id))}>
      <b>{meet.name}</b>
    </a>
  );
  return (
    <>
      <div className="cat-rubrikrad">
        <div>
          {ctx.fleetTitle ? <p className="tm-overrubrik">{ctx.fleetTitle}</p> : null}
          <h1>{t("meets")}</h1>
        </div>
        <div className="cat-knappar">
          <button type="button" className="tm-knapp primar cat-huvudknapp" onClick={() => onNew?.(null)}>
            {t("newMeet")}
          </button>
        </div>
      </div>
      <ErrorLine text={error} />
      <div className="cat-kortet">
        <div className="cat-huvudkolumn">
          {meets === null ? (
            <p className="cat-laddar">{t("loading")}</p>
          ) : active.length === 0 ? (
            <section className="tm-kort cat-tomt">
              <p className="cat-tomt-rubrik">{t("meetsEmpty")}</p>
              <p>{t("meetsEmptyDetail")}</p>
            </section>
          ) : (
            <section className="tm-kort cat-lista" aria-labelledby="aktiva-rubrik">
              <h2 id="aktiva-rubrik" className="cat-listrubrik">
                {t("meetsActive")}
              </h2>
              <ul className="cat-traffar">
                {active.map((meet) => (
                  <li key={meet.id}>
                    {link(meet)}
                    <span className="cat-under">{meetLine(ctx, meet)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
        <div className="cat-sidokolumn">
          <section className="tm-kort cat-avsnitt" aria-labelledby="sa-rubrik">
            <h2 id="sa-rubrik">{t("meetsHow")}</h2>
            <p>{t("meetsIntro")}</p>
            <p>{t("meetsHowMissing")}</p>
          </section>
          {earlier.length ? (
            <section className="tm-kort cat-lista" aria-labelledby="tidigare-rubrik">
              <h2 id="tidigare-rubrik" className="cat-listrubrik">
                {t("meetsEarlier")}
              </h2>
              <ul className="cat-traffar">
                {earlier.map((meet) => (
                  <li key={meet.id}>
                    {link(meet)}
                    <span className="cat-under">{meetLine(ctx, meet)}</span>
                    <button type="button" className="tm-knapp" onClick={() => onNew?.(meet)}>
                      {t("fromThis")}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      </div>
    </>
  );
}

/** A new meet: a name and a date (CAT-174), and perhaps an earlier meet's pack list (CAT-183). */
export function NewMeetDialog({
  ctx,
  open,
  meets,
  template,
  onClose,
  onCreate,
}: {
  ctx: Ctx;
  open: boolean;
  meets: TripSummary[];
  template: string | null;
  onClose: () => void;
  onCreate: (body: NewTrip) => Promise<void>;
}) {
  const { t, language } = ctx;
  const id = useId();
  const [name, setName] = useState("");
  const [day, setDay] = useState("");
  const [from, setFrom] = useState(template ?? "");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) setFrom(template ?? "");
  }, [open, template]);
  return (
    <Dialog open={open} title={t("newMeet")} onClose={onClose}>
      <form
        className="cat-formular"
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          await onCreate({ name: name.trim(), date: day, template: from || null });
          setBusy(false);
          setName("");
          setDay("");
        }}
      >
        <div className="cat-falt">
          <label htmlFor={`${id}-namn`}>{t("meetName")}</label>
          <input id={`${id}-namn`} required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="cat-falt">
          <label htmlFor={`${id}-datum`}>{t("meetDate")}</label>
          <input id={`${id}-datum`} type="date" required value={day} onChange={(e) => setDay(e.target.value)} />
        </div>
        {meets.length ? (
          <div className="cat-falt">
            <label htmlFor={`${id}-mall`}>{t("meetTemplate")}</label>
            <select id={`${id}-mall`} value={from} onChange={(e) => setFrom(e.target.value)}>
              <option value="">{t("meetNoTemplate")}</option>
              {meets.map((meet) => (
                <option key={meet.id} value={meet.id}>
                  {meet.name} · {dateText(language, meet.date)}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div className="cat-dialogknappar">
          <button type="button" className="tm-knapp" onClick={onClose}>
            {t("cancel")}
          </button>
          <button type="submit" className="tm-knapp primar" disabled={busy || !name.trim() || !day}>
            {t("createMeet")}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export function MeetsPage({ ctx }: { ctx: Ctx }) {
  const { t } = ctx;
  const [meets, setMeets] = useState<TripSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // undefined: no dialog; null: a new meet; an id: a new meet from that one's pack list.
  const [newFrom, setNewFrom] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    api.trips().then(setMeets, (failure) => {
      setMeets([]);
      setError(problemText(t, failure));
    });
  }, [t]);

  return (
    <>
      <MeetsView ctx={ctx} meets={meets} error={error} onNew={(meet) => setNewFrom(meet?.id ?? null)} />
      <NewMeetDialog
        ctx={ctx}
        open={newFrom !== undefined}
        meets={meets ?? []}
        template={newFrom ?? null}
        onClose={() => setNewFrom(undefined)}
        onCreate={async (body) => {
          try {
            const made = await api.newTrip(body);
            setNewFrom(undefined);
            ctx.navigate?.(meetPath(made.id));
          } catch (failure) {
            setNewFrom(undefined);
            setError(problemText(t, failure));
          }
        }}
      />
    </>
  );
}

// --- One meet: the pack list and the three steps ---------------------------------------------

function TripRowItem({ ctx, row, step, archived, missing, onPress }: { ctx: Ctx; row: TripRow; step: TripStep; archived: boolean; missing?: boolean; onPress?: (row: TripRow, ticked: boolean) => void }) {
  const { t, language } = ctx;
  const ticked = tickOf(row, step) !== null;
  const notice = missing ? row.vehicle.notices?.[0] : undefined;
  return (
    <li>
      <button type="button" className="cat-resrad" aria-pressed={ticked} disabled={archived} onClick={() => onPress?.(row, !ticked)}>
        {row.vehicle.picture ? (
          <img className="cat-listbild" src={row.vehicle.picture.thumb_url} alt="" width={72} height={48} loading="lazy" decoding="async" />
        ) : (
          <span className="cat-listbild" aria-hidden="true" />
        )}
        <span className="cat-restext">
          <b>{title(t, row.vehicle)}</b>
          <span className="cat-under">{rowLine(ctx, row, step)}</span>
          {notice ? <span className="cat-besked-rad">{t("someoneSaid", { time: timeText(language, notice.at), text: notice.text })}</span> : null}
        </span>
        <span className="cat-bock" aria-hidden="true" />
        <span className="cat-dold">{t(ticked ? "untickHint" : "tickHint", { step: stepName(t, step) })}</span>
      </button>
    </li>
  );
}

/** Blippa in the step: Web NFC on Android, as on the Blippa page, the tag's address, and in the
 * test environment the fleet's simulated tags (CAT-96, CAT-117). */
export function TripTapPanel({
  ctx,
  step,
  reader,
  scanning,
  simulated,
  onStart,
  onStop,
  onTap,
}: {
  ctx: Ctx;
  step: TripStep;
  reader: Reader;
  scanning: boolean;
  simulated: { uid: string; label: string }[];
  onStart?: () => void;
  onStop?: () => void;
  onTap?: (uid: string) => void;
}) {
  const { t } = ctx;
  const [text, setText] = useState("");
  const id = useId();
  return (
    <section className="tm-kort cat-avsnitt cat-blippa" aria-labelledby={`${id}-rubrik`}>
      <h2 id={`${id}-rubrik`}>{t("tapInTrip")}</h2>
      {reader === "nfc" ? (
        scanning ? (
          <>
            <p className="cat-tomt-rubrik" role="status">
              {t("tapHold")}
            </p>
            <button type="button" className="tm-knapp" onClick={onStop}>
              {t("tapStop")}
            </button>
          </>
        ) : (
          <button type="button" className="tm-knapp primar cat-huvudknapp" onClick={onStart}>
            {t(`tapButton_${step}`)}
          </button>
        )
      ) : (
        <p className="cat-under">{t("tapOtherWays")}</p>
      )}
      <form
        className="cat-rad"
        onSubmit={(event) => {
          event.preventDefault();
          if (!uidFrom(text)) return;
          onTap?.(uidFrom(text));
          setText("");
        }}
      >
        <label htmlFor={id}>{t("openTagLabel")}</label>
        <input id={id} className="tm-mono" value={text} spellCheck={false} autoComplete="off" onChange={(e) => setText(e.target.value)} />
        <button type="submit" className="tm-knapp" disabled={!uidFrom(text)}>
          {t("tapInTrip")}
        </button>
      </form>
      {simulated.length ? (
        <div className="cat-simulerade">
          <p className="cat-under">{t("simulatedTitle")}</p>
          <div className="cat-knappar">
            {simulated.map((tag) => (
              <button key={tag.uid} type="button" className="tm-knapp" onClick={() => onTap?.(tag.uid)}>
                {tag.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

export type TripViewProps = {
  ctx: Ctx;
  trip: Trip;
  step: TripStep;
  error: string | null;
  /** What the last tap did, for the screen reader too. */
  notice?: string | null;
  /** A tapped vehicle that is not on the pack list: Lägg till? (CAT-181) */
  asking?: { uid: string; title: string } | null;
  reader?: Reader;
  scanning?: boolean;
  simulated?: { uid: string; label: string }[];
  onStep?: (step: TripStep) => void;
  onPress?: (row: TripRow, ticked: boolean) => void;
  onTap?: (uid: string) => void;
  onAdd?: () => void;
  onDismiss?: () => void;
  onStart?: () => void;
  onStop?: () => void;
  onPackList?: () => void;
  onArchive?: () => void;
  onFromThis?: () => void;
};

/** The meet as it looks, from its state. Rendered in the tests without fetching. */
export function TripView(props: TripViewProps) {
  const { ctx, trip, step } = props;
  const { t, language } = ctx;
  const archived = Boolean(trip.archived_at);
  const done = trip.done[step] ?? 0;
  const count = t(`stepCount_${step}`, { n: done, of: trip.vehicles });
  // Vid hemfärden står det som saknas överst (CAT-179).
  const missing = step === "home" ? trip.rows.filter((row) => row.missing) : [];
  const listed = step === "home" ? trip.rows.filter((row) => !row.missing) : trip.rows;
  const item = (row: TripRow, isMissing = false) => (
    <TripRowItem key={row.vehicle.id} ctx={ctx} row={row} step={step} archived={archived} missing={isMissing} onPress={props.onPress} />
  );
  return (
    <>
      <Crumbs ctx={ctx} items={[{ href: PATHS.meets, label: t("meets") }, { label: trip.name }]} />
      <p className="tm-overrubrik">
        {trip.name} · {dateText(language, trip.date)}
      </p>
      <h1>{t(`stepTitle_${step}`)}</h1>
      <p className="cat-ingress">{trip.archived_at ? t("archivedNote", { date: dateText(language, trip.archived_at) }) : t(`stepIntro_${step}`)}</p>

      <div className="cat-steg" role="group" aria-label={t("steps")}>
        {STEPS.map((each, index) => (
          <button key={each} type="button" aria-pressed={each === step} onClick={() => props.onStep?.(each)}>
            <span>
              {index + 1} · {stepName(t, each)}
            </span>
            <span className="cat-under">{t(`stepCount_${each}`, { n: trip.done[each] ?? 0, of: trip.vehicles })}</span>
          </button>
        ))}
      </div>

      <p className="cat-framstegstext">
        <b>{count}</b>
      </p>
      <progress className="cat-framsteg" value={done} max={Math.max(trip.vehicles, 1)} aria-label={count} />

      <ErrorLine text={props.error} />
      <p className="cat-ok cat-blippsvar" role="status">
        {props.notice ?? ""}
      </p>
      {props.asking ? (
        <div className="cat-vantar" role="alert">
          <p>{t("notOnList", { name: props.asking.title })}</p>
          <div className="cat-knappar">
            <button type="button" className="tm-knapp primar" onClick={props.onAdd}>
              {t("add")}
            </button>
            <button type="button" className="tm-knapp" onClick={props.onDismiss}>
              {t("cancel")}
            </button>
          </div>
        </div>
      ) : null}

      {missing.length ? (
        <section className="tm-kort cat-saknas" aria-labelledby="saknas-rubrik">
          <h2 id="saknas-rubrik">{t("missingTitle", { n: missing.length })}</h2>
          <ul className="cat-resrader">{missing.map((row) => item(row, true))}</ul>
        </section>
      ) : null}

      <section className="tm-kort cat-lista" aria-label={t("packListTitle")}>
        {trip.rows.length === 0 ? <p className="cat-tom-lista">{t("packListEmpty")}</p> : null}
        {listed.length ? <ul className="cat-resrader">{listed.map((row) => item(row))}</ul> : null}
        {archived ? null : (
          <div className="cat-urval">
            <button type="button" className="tm-knapp" onClick={props.onPackList}>
              {trip.rows.length ? t("changePackList") : t("addFromFleet")}
            </button>
          </div>
        )}
      </section>

      {archived ? null : (
        <TripTapPanel
          ctx={ctx}
          step={step}
          reader={props.reader ?? "none"}
          scanning={props.scanning ?? false}
          simulated={props.simulated ?? []}
          onStart={props.onStart}
          onStop={props.onStop}
          onTap={props.onTap}
        />
      )}

      <div className="cat-knappar cat-avsnitt">
        <button type="button" className="tm-knapp" onClick={props.onFromThis}>
          {t("fromThis")}
        </button>
        {archived ? null : (
          <button type="button" className="tm-knapp" onClick={props.onArchive}>
            {t("archiveTrip")}
          </button>
        )}
      </div>
    </>
  );
}

/** Choose the vehicles that go to the meet (CAT-175). */
export function PackListDialog({
  ctx,
  open,
  fleet,
  chosen,
  onClose,
  onSave,
}: {
  ctx: Ctx;
  open: boolean;
  fleet: Vehicle[] | null;
  chosen: string[];
  onClose: () => void;
  onSave: (vehicles: string[]) => Promise<void>;
}) {
  const { t } = ctx;
  const [picked, setPicked] = useState<Set<string>>(() => new Set(chosen));
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open) return;
    setPicked(new Set(chosen));
    setQ("");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when the dialog opens
  }, [open]);
  const needle = q.trim().toLowerCase();
  const shown = (fleet ?? []).filter((vehicle) => !needle || `${title(t, vehicle)} ${subtitle(t, vehicle)}`.toLowerCase().includes(needle));
  return (
    <Dialog open={open} title={t("packListTitle")} onClose={onClose}>
      <input className="cat-sok" type="search" value={q} aria-label={t("packListSearch")} placeholder={t("packListSearch")} onChange={(e) => setQ(e.target.value)} />
      {fleet === null ? (
        <p className="cat-laddar">{t("loading")}</p>
      ) : (
        <ul className="cat-packval">
          {shown.map((vehicle) => (
            <li key={vehicle.id}>
              <label className="cat-vaxel">
                <input
                  type="checkbox"
                  checked={picked.has(vehicle.id)}
                  onChange={(event) =>
                    setPicked((before) => {
                      const next = new Set(before);
                      if (event.target.checked) next.add(vehicle.id);
                      else next.delete(vehicle.id);
                      return next;
                    })
                  }
                />
                <span>
                  {title(t, vehicle)} <span className="cat-under">{subtitle(t, vehicle)}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <p className="cat-under">{t("packListChosen", { n: picked.size })}</p>
      <div className="cat-dialogknappar">
        <button type="button" className="tm-knapp" onClick={onClose}>
          {t("cancel")}
        </button>
        <button
          type="button"
          className="tm-knapp primar"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            await onSave([...picked]);
            setBusy(false);
          }}
        >
          {t("packListSave")}
        </button>
      </div>
    </Dialog>
  );
}

export function TripPage({ ctx, id, simulated }: { ctx: Ctx; id: string; simulated: boolean }) {
  const { t } = ctx;
  const [trip, setTrip] = useState<Trip | null>(null);
  const [chosenStep, setChosenStep] = useState<TripStep | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [asking, setAsking] = useState<{ uid: string; title: string } | null>(null);
  const [scanning, setScanning] = useState(false);
  const [reader] = useState<Reader>(readerHere);
  const [fleet, setFleet] = useState<Vehicle[] | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [newFrom, setNewFrom] = useState(false);
  const stop = useRef<AbortController | null>(null);
  const step: TripStep = chosenStep ?? trip?.step ?? "pack";
  // The step shown when a tag is read, also while Web NFC keeps reading.
  const stepNow = useRef<TripStep>(step);
  stepNow.current = step;

  const loadFleet = () => api.vehicles().then((found) => setFleet(found.vehicles), () => setFleet([]));
  useEffect(() => {
    api.trip(id).then(setTrip, (failure) => setError(problemText(t, failure)));
  }, [id, t]);
  useEffect(() => {
    if (simulated) loadFleet();
  }, [simulated]);
  useEffect(() => () => stop.current?.abort(), []);

  if (!trip) return error ? <ErrorLine text={error} /> : <p className="cat-laddar">{t("loading")}</p>;

  const act = async (work: () => Promise<Trip>) => {
    setError(null);
    setNotice(null);
    try {
      setTrip(await work());
    } catch (failure) {
      setError(problemText(t, failure));
    }
  };

  const tapped = async (uid: string, add = false) => {
    const at = stepNow.current;
    setError(null);
    setNotice(null);
    try {
      const answer = await api.tapInTrip(trip.id, uid, at, add);
      setTrip(answer.trip);
      if (answer.outcome === "not_on_list") {
        setAsking({ uid, title: answer.title ?? "" });
        return;
      }
      setAsking(null);
      if (answer.outcome === "unknown") setError(t("tappedUnknown"));
      else setNotice(t("tappedTicked", { name: answer.title ?? "", step: stepName(t, at) }));
    } catch (failure) {
      setError(problemText(t, failure));
    }
  };

  return (
    <>
      <TripView
        ctx={ctx}
        trip={trip}
        step={step}
        error={error}
        notice={notice}
        asking={asking}
        reader={reader}
        scanning={scanning}
        simulated={simulated ? simulatedTags(t, fleet) : []}
        onStep={(next) => {
          setChosenStep(next);
          setNotice(null);
        }}
        onPress={(row, ticked) => act(() => api.tick(trip.id, row.vehicle.id, step, ticked))}
        onTap={(uid) => tapped(uid)}
        onAdd={() => (asking ? tapped(asking.uid, true) : undefined)}
        onDismiss={() => setAsking(null)}
        onStart={async () => {
          setError(null);
          const controller = new AbortController();
          stop.current = controller;
          setScanning(true);
          try {
            // Keep reading until Sluta: one vehicle after the other into the bag.
            await scan((serial) => void tapped(serial), controller.signal, () => setError(t("tapReadError")));
          } catch {
            setScanning(false);
            setError(t("tapNoNfcAllowed"));
          }
        }}
        onStop={() => {
          stop.current?.abort();
          setScanning(false);
        }}
        onPackList={() => {
          if (fleet === null) loadFleet();
          setChoosing(true);
        }}
        onArchive={() => setArchiving(true)}
        onFromThis={() => setNewFrom(true)}
      />
      <PackListDialog
        ctx={ctx}
        open={choosing}
        fleet={fleet}
        chosen={trip.rows.map((row) => row.vehicle.id)}
        onClose={() => setChoosing(false)}
        onSave={async (vehicles) => {
          setChoosing(false);
          await act(() => api.packList(trip.id, vehicles));
        }}
      />
      <Dialog open={archiving} title={t("archiveTrip")} onClose={() => setArchiving(false)}>
        <p>{t("archiveConfirm", { name: trip.name })}</p>
        <div className="cat-dialogknappar">
          <button type="button" className="tm-knapp" onClick={() => setArchiving(false)}>
            {t("cancel")}
          </button>
          <button
            type="button"
            className="tm-knapp primar"
            onClick={async () => {
              setArchiving(false);
              await act(() => api.archiveTrip(trip.id));
            }}
          >
            {t("archiveTrip")}
          </button>
        </div>
      </Dialog>
      <NewMeetDialog
        ctx={ctx}
        open={newFrom}
        meets={[trip]}
        template={trip.id}
        onClose={() => setNewFrom(false)}
        onCreate={async (body) => {
          try {
            const made = await api.newTrip(body);
            setNewFrom(false);
            ctx.navigate?.(meetPath(made.id));
          } catch (failure) {
            setNewFrom(false);
            setError(problemText(t, failure));
          }
        }}
      />
    </>
  );
}

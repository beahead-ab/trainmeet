// Fordonskortet: the core fields, the EVN, where it is, the history, and removing it
// (CAT-53, CAT-57–CAT-60, CAT-68, CAT-72, CAT-76, CAT-77).
import { linkClick } from "@trainmeet/design";
import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError, qrAddress, type PendingState, type Place, type Vehicle, type VehicleEvent, type VehicleTag } from "./api";
import { Crumbs, dateText, Dialog, ErrorLine, isOwner, kindText, mayEdit, problemText, StatePill, subtitle, timeText, title, type Ctx, type T } from "./common";
import { nfcSupported, writeAddress } from "./nfc";
import { PicturesSection } from "./Pictures";
import { editPath, lendPath, PATHS } from "./routes";
import { MoveDialog } from "./VehiclesPage";

function Row({ label, value, extra, mono }: { label: string; value: string; extra?: ReactNode; mono?: boolean }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td className={mono ? "tm-mono" : undefined}>{value}</td>
      <td className="cat-extra">{extra}</td>
    </tr>
  );
}

export type EvnNote = "none" | "ok" | "wrong";

export function evnLine(t: T, vehicle: Vehicle): { value: string; note: string; kind: EvnNote } {
  const evn = vehicle.evn;
  if (!evn) return { value: "", note: t("evnNone"), kind: "none" };
  if (!evn.valid) return { value: evn.text, note: t("evnWrong", { check: evn.check }), kind: "wrong" };
  return { value: evn.text, note: evn.given === null ? t("evnComputed") : t("evnOk"), kind: "ok" };
}

const EVN_CLASS: Record<EvnNote, string> = { none: "cat-under", ok: "cat-ok", wrong: "cat-varning" };

export function eventText(t: T, event: VehicleEvent): string {
  return [stateEventText(t, event), event.meet_name].filter(Boolean).join(" · ");
}

/** The state and the place; the meet's name follows when the trip moved it (CAT-182). */
function stateEventText(t: T, event: VehicleEvent): string {
  if (event.state === "lent") return t("eventLent", { name: event.lent_to ?? "" });
  if (event.state === "home") return event.place_name ? t("eventHomeAt", { place: event.place_name }) : t("eventHome");
  return t(`state_${event.state}`);
}

/** The tags on the card: kind, name, address and when linked, with Ersätt and Koppla bort (CAT-97). */
export function TagSection({
  ctx,
  vehicle,
  pending,
  onWait,
  onStopWaiting,
  onUnlink,
  onNewLabel,
}: {
  ctx: Ctx;
  vehicle: Vehicle;
  pending: PendingState["pending"];
  onWait?: (replace: VehicleTag | null) => void;
  onStopWaiting?: () => void;
  onUnlink?: (tag: VehicleTag) => void;
  onNewLabel?: (replace: VehicleTag | null) => void;
}) {
  const { t, language } = ctx;
  const tags = vehicle.tags ?? [];
  const nfc = tags.find((tag) => tag.kind !== "qr") ?? null;
  const qr = tags.find((tag) => tag.kind === "qr") ?? null;
  const waiting = pending?.vehicle_id === vehicle.id;
  const ready = vehicle.status === "ready";
  return (
    <section className="tm-kort cat-taggen" aria-labelledby="taggen-rubrik">
      <h2 id="taggen-rubrik">{t("tagSection")}</h2>
      {tags.length === 0 ? <p className="cat-under">{t("noTag")}</p> : null}
      {tags.map((tag) => (
        <div key={tag.assignment} className="cat-tagg">
          <span className={`cat-pill cat-pill-tagg-${tag.kind}`}>{t(`tagKind_${tag.kind}`)}</span>
          <p>
            <b>{tag.name}</b> <span className="cat-under">{t("linkedAt", { date: dateText(language, tag.linked_at) })}</span>
          </p>
          <p className="tm-mono cat-adress">{tag.address.replace(/^https:\/\//, "")}</p>
          {tag.kind === "qr" ? <img className="cat-qr" src={qrAddress(tag.uid)} alt={t("qrAlt", { address: tag.address })} width={132} height={132} /> : null}
          <div className="cat-knappar">
            {tag.kind === "qr" ? (
              <button type="button" className="tm-knapp" onClick={() => onNewLabel?.(tag)}>
                {t("replaceLabel")}
              </button>
            ) : (
              <button type="button" className="tm-knapp" onClick={() => onWait?.(tag)}>
                {t("replaceTag")}
              </button>
            )}
            <button type="button" className="tm-knapp" onClick={() => onUnlink?.(tag)}>
              {t("unlinkTag")}
            </button>
          </div>
        </div>
      ))}
      {waiting ? (
        <div className="cat-vantar" role="status">
          <p>{t("waitingFor", { name: title(t, vehicle) })}</p>
          <button type="button" className="tm-knapp" onClick={onStopWaiting}>
            {t("stopWaiting")}
          </button>
        </div>
      ) : null}
      {!ready ? (
        <p className="cat-under">{t("draftNoTag")}</p>
      ) : (
        <div className="cat-knappar">
          {!nfc && !waiting ? (
            <button type="button" className="tm-knapp primar" onClick={() => onWait?.(null)}>
              {t("linkTag")}
            </button>
          ) : null}
          {!qr ? (
            <button type="button" className="tm-knapp" onClick={() => onNewLabel?.(null)}>
              {t("newLabel")}
            </button>
          ) : null}
        </div>
      )}
    </section>
  );
}

/** Android writes the address on the tag when it is linked, so an iPhone can tap it too (CAT-118). */
export function WritePanel({ t, address, state, onWrite }: { t: T; address: string; state: "ready" | "done" | "failed"; onWrite?: () => void }) {
  return (
    <section className="tm-kort cat-avsnitt cat-skriv" aria-labelledby="skriv-rubrik" aria-live="polite">
      <h2 id="skriv-rubrik">{t("writeTitle")}</h2>
      {state === "done" ? (
        <p role="status">{t("writeDone")}</p>
      ) : (
        <>
          <p>{t("writeIntro")}</p>
          <p className="tm-mono cat-adress">{address.replace(/^https:\/\//, "")}</p>
          <button type="button" className="tm-knapp primar" onClick={onWrite}>
            {t("writeButton")}
          </button>
          {state === "failed" ? <p className="cat-fel">{t("writeFailed")}</p> : null}
        </>
      )}
    </section>
  );
}

/** Någon sa till: where others saw the vehicle, without who said it (CAT-113). */
export function Notices({ ctx, vehicle, onClear }: { ctx: Ctx; vehicle: Vehicle; onClear?: (id: string) => void }) {
  const { t, language } = ctx;
  const notices = vehicle.notices ?? [];
  if (notices.length === 0) return null;
  return (
    <section className="tm-kort cat-avsnitt cat-besked" aria-labelledby="besked-rubrik">
      <h2 id="besked-rubrik">{t("noticesTitle")}</h2>
      <ul className="cat-handelser">
        {notices.map((notice) => (
          <li key={notice.id}>
            <span>
              «{notice.text}» <time className="cat-under" dateTime={notice.at}>{timeText(language, notice.at)}</time>
            </span>
            <button type="button" className="tm-knapp" aria-label={`${t("noticeRemove")}: ${notice.text}`} onClick={() => onClear?.(notice.id)}>
              {t("removeYes")}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export type CardViewProps = {
  ctx: Ctx;
  vehicle: Vehicle;
  events: VehicleEvent[];
  error: string | null;
  pending?: PendingState["pending"];
  onMove?: () => void;
  onGiveBack?: () => void;
  onRemove?: () => void;
  onWait?: (replace: VehicleTag | null) => void;
  onStopWaiting?: () => void;
  onUnlink?: (tag: VehicleTag) => void;
  onNewLabel?: (replace: VehicleTag | null) => void;
  onClearNotice?: (id: string) => void;
  writing?: { address: string; state: "ready" | "done" | "failed" } | null;
  onWrite?: () => void;
  /** Bilderna, above the card: PicturesSection, or PicturesView in the tests (CAT-05). */
  pictures?: ReactNode;
};

export function CardView(props: CardViewProps) {
  const { ctx, vehicle, events, error, onMove, onGiveBack, onRemove } = props;
  const { t, language, navigate } = ctx;
  const name = title(t, vehicle);
  const missing = t("notFilled");
  const evn = evnLine(t, vehicle);
  const model = [vehicle.maker, vehicle.article_number].filter(Boolean).join(" · ");
  const engine = vehicle.kind === "locomotive" || vehicle.kind === "multiple_unit";
  const functions = (vehicle.functions ?? []).map((f) => `F${f.number} ${f.name}`).join(", ");
  return (
    <>
      <Crumbs ctx={ctx} items={[{ href: PATHS.vehicles, label: t("vehicles") }, { label: name }]} />
      <p className="tm-overrubrik">{t("cardEyebrow")}</p>
      <h1>
        {name} {vehicle.status === "draft" ? <span className="cat-pill">{t("draft")}</span> : null}
      </h1>
      <p className="cat-ingress">{subtitle(t, vehicle)}</p>
      <ErrorLine text={error} />
      {props.writing ? <WritePanel t={t} address={props.writing.address} state={props.writing.state} onWrite={props.onWrite} /> : null}
      <div className="cat-kortet">
        <div className="cat-huvudkolumn">
          {props.pictures}
          <section className="tm-kort" aria-labelledby="kortet-rubrik">
            <div className="cat-kortrubrik">
              <h2 id="kortet-rubrik">{t("card")}</h2>
              {mayEdit(ctx) ? (
                <a className="tm-knapp" href={editPath(vehicle.id)} onClick={linkClick(navigate, editPath(vehicle.id))}>
                  {t("edit")}
                </a>
              ) : null}
            </div>
            <table className="cat-falttabell">
              <tbody>
                <Row label={t("fKind")} value={kindText(t, vehicle.kind) || missing} />
                <Row label={t("fLittNumber")} value={`${vehicle.litt ?? ""} ${vehicle.number ?? ""}`.trim() || missing} />
                <Row
                  label={t("fEvn")}
                  value={evn.value}
                  mono
                  extra={
                    <span className={EVN_CLASS[evn.kind]}>
                      {evn.kind === "ok" ? "✓ " : ""}
                      {evn.note}
                    </span>
                  }
                />
                <Row label={t("fOperator")} value={vehicle.operator || missing} />
                <Row label={t("fEpoch")} value={vehicle.epoch || missing} />
                <Row label={t("fScale")} value={vehicle.scale || missing} />
                <Row label={t("fModel")} value={model || missing} />
                {engine ? <Row label={t("fDcc")} value={vehicle.dcc_address || missing} mono /> : null}
                {engine ? <Row label={t("fFunctions")} value={functions || missing} /> : null}
                <Row label={t("fNote")} value={vehicle.note || missing} />
              </tbody>
            </table>
          </section>
        </div>

        <div className="cat-sidokolumn">
          <Notices ctx={ctx} vehicle={vehicle} onClear={props.onClearNotice} />
          <section className={`tm-kort cat-laget cat-laget-${vehicle.state}`} aria-labelledby="laget-rubrik">
            <StatePill t={t} state={vehicle.state} />
            <h2 id="laget-rubrik">
              {vehicle.state === "home"
                ? vehicle.place_name
                  ? t("homeAt", { place: vehicle.place_name })
                  : t("homeNoPlace")
                : vehicle.state === "lent" && vehicle.lending
                  ? vehicle.lending.to
                  : t(`state_${vehicle.state}`)}
            </h2>
            {vehicle.state === "lent" && vehicle.lending ? (
              <p>
                {t("lentTo", { name: vehicle.lending.to, date: dateText(language, vehicle.lending.since) })}
                {vehicle.lending.until ? ` ${t("lentUntil", { date: dateText(language, vehicle.lending.until) })}` : ""}
              </p>
            ) : null}
            {vehicle.state !== "home" && vehicle.place_name ? <p>{t("livesIn", { place: vehicle.place_name })}</p> : null}
            {isOwner(ctx) ? (
            <div className="cat-knappar">
              <button type="button" className="tm-knapp" onClick={onMove}>
                {t("move")}
              </button>
              {vehicle.state === "lent" ? (
                <button type="button" className="tm-knapp" onClick={onGiveBack}>
                  {t("giveBack")}
                </button>
              ) : vehicle.state === "home" && vehicle.status === "ready" ? (
                <a className="tm-knapp" href={lendPath(vehicle.id)} onClick={linkClick(navigate, lendPath(vehicle.id))}>
                  {t("lend")}
                </a>
              ) : null}
            </div>
            ) : null}
          </section>

          {isOwner(ctx) ? (
          <>
          <TagSection
            ctx={ctx}
            vehicle={vehicle}
            pending={props.pending ?? null}
            onWait={props.onWait}
            onStopWaiting={props.onStopWaiting}
            onUnlink={props.onUnlink}
            onNewLabel={props.onNewLabel}
          />

          <section className="tm-kort" aria-labelledby="handelser-rubrik">
            <h2 id="handelser-rubrik">{t("history")}</h2>
            {events.length === 0 ? (
              <p className="cat-under">{t("historyEmpty")}</p>
            ) : (
              <ol className="cat-handelser">
                {events.map((event, index) => (
                  <li key={index}>
                    <span>{eventText(t, event)}</span>
                    <time className="cat-under" dateTime={event.at}>
                      {timeText(language, event.at)}
                    </time>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <button type="button" className="tm-knapp cat-fara" onClick={onRemove}>
            {t("remove")}
          </button>
          </>
          ) : vehicle.tagged ? (
            <section className="tm-kort">
              <h2>{t("tagTitle")}</h2>
              <p className="cat-under">{t("hasTag")}</p>
            </section>
          ) : null}
        </div>
      </div>
    </>
  );
}

export function VehicleCardPage({ ctx, id }: { ctx: Ctx; id: string }) {
  const { t } = ctx;
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [events, setEvents] = useState<VehicleEvent[]>([]);
  const [places, setPlaces] = useState<Place[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [moving, setMoving] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [pending, setPending] = useState<PendingState["pending"]>(null);
  const [unlinking, setUnlinking] = useState<VehicleTag | null>(null);
  // ?skriv=<uid>: just linked on Android, so offer to write the address on the tag (CAT-118).
  const [writeUid] = useState(() => (nfcSupported() ? new URLSearchParams(window.location.search).get("skriv") : null));
  const [written, setWritten] = useState<"ready" | "done" | "failed">("ready");

  const load = () => {
    api.vehicle(id).then(setVehicle, (failure) => setError(problemText(t, failure)));
    if (isOwner(ctx)) api.events(id).then(setEvents, () => setEvents([]));
    api.pending().then((state) => setPending(state.pending), () => setPending(null));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- load reads only id
  useEffect(load, [id]);

  if (!vehicle) return error ? <ErrorLine text={error} /> : <p className="cat-laddar">{t("loading")}</p>;
  const act = async (work: () => Promise<unknown>) => {
    try {
      setError(null);
      await work();
    } catch (failure) {
      setError(problemText(t, failure));
      if (failure instanceof ApiError && (failure.code === "changed" || failure.code === "tag_changed")) load();
      return;
    }
    load();
  };
  return (
    <>
      <CardView
        ctx={ctx}
        vehicle={vehicle}
        events={events}
        error={error}
        onMove={() => {
          api.places().then(setPlaces, () => setPlaces([]));
          setMoving(true);
        }}
        onGiveBack={() => act(() => api.giveBack(vehicle.id, vehicle.version))}
        onRemove={() => setRemoving(true)}
        pending={pending}
        onWait={(replace) => act(() => api.waitForTag(vehicle.id, replace?.assignment ?? null))}
        onStopWaiting={() => act(() => api.stopWaiting())}
        onUnlink={setUnlinking}
        onNewLabel={(replace) => act(() => api.newLabel(vehicle.id, replace?.assignment ?? null))}
        onClearNotice={(notice) => act(() => api.clearNotice(vehicle.id, notice))}
        pictures={<PicturesSection ctx={ctx} vehicle={vehicle} />}
        writing={(() => {
          const tag = writeUid ? (vehicle.tags ?? []).find((each) => each.uid === writeUid.toLowerCase().replace(/[:-]/g, "")) : undefined;
          return tag ? { address: tag.address, state: written } : null;
        })()}
        onWrite={async () => {
          const tag = (vehicle.tags ?? []).find((each) => each.uid === (writeUid ?? "").toLowerCase().replace(/[:-]/g, ""));
          if (!tag) return;
          try {
            await writeAddress(tag.address);
            setWritten("done");
          } catch {
            setWritten("failed");
          }
        }}
      />
      <Dialog open={unlinking !== null} title={t("unlinkTag")} onClose={() => setUnlinking(null)}>
        <p>{unlinking ? t("unlinkConfirm", { tag: unlinking.name, name: title(t, vehicle) }) : ""}</p>
        <div className="cat-dialogknappar">
          <button type="button" className="tm-knapp" onClick={() => setUnlinking(null)}>
            {t("cancel")}
          </button>
          <button
            type="button"
            className="tm-knapp primar"
            onClick={async () => {
              const tag = unlinking;
              setUnlinking(null);
              if (tag) await act(() => api.unlink(vehicle.id, tag.assignment));
            }}
          >
            {t("unlinkTag")}
          </button>
        </div>
      </Dialog>
      <MoveDialog
        ctx={ctx}
        open={moving}
        places={places}
        onClose={() => setMoving(false)}
        onMove={async (place) => {
          setMoving(false);
          await act(() => api.move([vehicle.id], place));
        }}
      />
      <Dialog open={removing} title={t("remove")} onClose={() => setRemoving(false)}>
        <p>{t("removeConfirm", { name: title(t, vehicle) })}</p>
        <div className="cat-dialogknappar">
          <button type="button" className="tm-knapp" onClick={() => setRemoving(false)}>
            {t("cancel")}
          </button>
          <button
            type="button"
            className="tm-knapp cat-fara"
            onClick={async () => {
              setRemoving(false);
              try {
                await api.removeVehicle(vehicle.id, vehicle.version);
                ctx.navigate?.(PATHS.vehicles);
              } catch (failure) {
                setError(problemText(t, failure));
              }
            }}
          >
            {t("removeYes")}
          </button>
        </div>
      </Dialog>
    </>
  );
}

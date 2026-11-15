// Fordonskortet: the core fields, the EVN, where it is, the history, and removing it
// (CAT-53, CAT-57–CAT-60, CAT-68, CAT-72, CAT-76, CAT-77).
import { linkClick } from "@trainmeet/design";
import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError, type Place, type Vehicle, type VehicleEvent } from "./api";
import { Crumbs, dateText, Dialog, ErrorLine, kindText, problemText, StatePill, subtitle, timeText, title, type Ctx, type T } from "./common";
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
  if (event.state === "lent") return t("eventLent", { name: event.lent_to ?? "" });
  if (event.state === "home") return event.place_name ? t("eventHomeAt", { place: event.place_name }) : t("eventHome");
  return t(`state_${event.state}`);
}

export type CardViewProps = {
  ctx: Ctx;
  vehicle: Vehicle;
  events: VehicleEvent[];
  error: string | null;
  onMove?: () => void;
  onGiveBack?: () => void;
  onRemove?: () => void;
};

export function CardView({ ctx, vehicle, events, error, onMove, onGiveBack, onRemove }: CardViewProps) {
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
      <div className="cat-kortet">
        <section className="tm-kort" aria-labelledby="kortet-rubrik">
          <div className="cat-kortrubrik">
            <h2 id="kortet-rubrik">{t("card")}</h2>
            <a className="tm-knapp" href={editPath(vehicle.id)} onClick={linkClick(navigate, editPath(vehicle.id))}>
              {t("edit")}
            </a>
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

        <div className="cat-sidokolumn">
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
          </section>

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

  const load = () => {
    api.vehicle(id).then(setVehicle, (failure) => setError(problemText(t, failure)));
    api.events(id).then(setEvents, () => setEvents([]));
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
      if (failure instanceof ApiError && failure.code === "changed") load();
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
      />
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

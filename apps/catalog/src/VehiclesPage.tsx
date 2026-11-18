// Fordon: the fleet with search, filters and moving several at once (CAT-65, CAT-72, CAT-73).
import { linkClick } from "@trainmeet/design";
import { useEffect, useState } from "react";
import { api, STATES, type Account, type Place, type Vehicle, type VehicleKind, type VehicleList, type VehicleState } from "./api";
import { Dialog, ErrorLine, isOwner, mayEdit, problemText, StatePill, subtitle, title, type Ctx } from "./common";
import { PATHS, vehiclePath } from "./routes";

type KindGroup = "all" | "engines" | "wagons";
const GROUPS: Record<KindGroup, VehicleKind[]> = {
  all: [],
  engines: ["locomotive", "multiple_unit"],
  wagons: ["freight_wagon", "passenger_coach"],
};

export function whereText(vehicle: Vehicle): string {
  if (vehicle.state === "lent") return vehicle.lending?.to ?? "";
  if (vehicle.state === "home") return vehicle.place_name ?? "";
  return "";
}

export type VehiclesViewProps = {
  ctx: Ctx;
  account: Account;
  list: VehicleList | null;
  q: string;
  state: VehicleState | null;
  group: KindGroup;
  selected: Set<string>;
  error: string | null;
  onQ?: (q: string) => void;
  onState?: (state: VehicleState | null) => void;
  onGroup?: (group: KindGroup) => void;
  onSelect?: (id: string, on: boolean) => void;
  onMove?: () => void;
};

/** The fleet as it looks, from its state. Rendered in the tests without fetching. */
export function VehiclesView(props: VehiclesViewProps) {
  const { ctx, account, list, q, state, group, selected } = props;
  const { t, navigate } = ctx;
  const total = list?.total ?? 0;
  const searching = q.trim() !== "" || group !== "all" || state !== null;
  // The thumbnails get a column only when some vehicle in the list has a picture (CAT-125).
  const pictured = list?.vehicles.some((vehicle) => vehicle.picture) ?? false;
  return (
    <>
      <div className="cat-rubrikrad">
        <div>
          <p className="tm-overrubrik">{ctx.fleetTitle ?? t("fleetOf", { name: account.name })}</p>
          <h1>{t("vehicles")}</h1>
          {list ? <p className="cat-ingress">{total === 1 ? t("fleetSummaryOne") : t("fleetSummary", { n: total })}</p> : null}
        </div>
        <div className="cat-knappar">
          {isOwner(ctx) && ctx.shareUrl ? (
            <a className="tm-knapp" href={ctx.shareUrl}>
              {t("shareFleet")}
            </a>
          ) : null}
          {isOwner(ctx) ? (
            <a className="tm-knapp" href={PATHS.places} onClick={linkClick(navigate, PATHS.places)}>
              {t("places")}
            </a>
          ) : null}
          {mayEdit(ctx) ? (
            <a className="tm-knapp primar cat-huvudknapp" href={PATHS.newVehicle} onClick={linkClick(navigate, PATHS.newVehicle)}>
              {t("addVehicle")}
            </a>
          ) : null}
        </div>
      </div>

      <section className="tm-kort cat-lista" aria-label={t("vehicles")}>
        <div className="cat-verktyg">
          <input
            className="cat-sok"
            type="search"
            value={q}
            aria-label={t("search")}
            placeholder={t("search")}
            onChange={(event) => props.onQ?.(event.target.value)}
          />
          <div className="cat-chips" role="group" aria-label={t("stateFilter")}>
            <button type="button" className="cat-chip" aria-pressed={state === null} onClick={() => props.onState?.(null)}>
              {t("chipAll")} <span className="cat-antal">{total}</span>
            </button>
            {STATES.map((s) => (
              <button key={s} type="button" className="cat-chip" aria-pressed={state === s} onClick={() => props.onState?.(s)}>
                {t(`chip_${s}`)} <span className="cat-antal">{list?.counts[s] ?? 0}</span>
              </button>
            ))}
          </div>
          <div className="cat-segment" role="group" aria-label={t("kindFilter")}>
            {(["all", "engines", "wagons"] as KindGroup[]).map((g) => (
              <button key={g} type="button" aria-pressed={group === g} onClick={() => props.onGroup?.(g)}>
                {t(g === "all" ? "kindAll" : g === "engines" ? "kindEngines" : "kindWagons")}
              </button>
            ))}
          </div>
        </div>

        {selected.size > 0 ? (
          <div className="cat-urval">
            <button type="button" className="tm-knapp" onClick={props.onMove}>
              {t("moveSelected", { n: selected.size })}
            </button>
          </div>
        ) : null}

        <ErrorLine text={props.error} />

        {list === null ? (
          <p className="cat-laddar">{t("loading")}</p>
        ) : list.vehicles.length === 0 ? (
          <p className="cat-tom-lista">{searching ? t("noMatch") : t("fleetNone")}</p>
        ) : (
          <table className="cat-tabell">
            <thead>
              <tr>
                <th className="cat-val">
                  <span className="cat-dold">{t("move")}</span>
                </th>
                {pictured ? <th className="cat-bildcell">{t("colPicture")}</th> : null}
                <th>{t("colVehicle")}</th>
                <th className="cat-evn">{t("colEvn")}</th>
                <th>{t("colWhere")}</th>
              </tr>
            </thead>
            <tbody>
              {list.vehicles.map((vehicle) => (
                <tr key={vehicle.id}>
                  <td className="cat-val">
                    {isOwner(ctx) ? (
                      <input
                        type="checkbox"
                        checked={selected.has(vehicle.id)}
                        aria-label={t("selectVehicle", { name: title(t, vehicle) })}
                        onChange={(event) => props.onSelect?.(vehicle.id, event.target.checked)}
                      />
                    ) : null}
                  </td>
                  {pictured ? (
                    <td className="cat-bildcell">
                      {vehicle.picture ? (
                        // The name beside it is the link and says what it is: this one is for the finger and the mouse.
                        <a href={vehiclePath(vehicle.id)} onClick={linkClick(navigate, vehiclePath(vehicle.id))} tabIndex={-1} aria-hidden="true">
                          <img className="cat-listbild" src={vehicle.picture.thumb_url} alt="" width={72} height={48} loading="lazy" decoding="async" />
                        </a>
                      ) : null}
                    </td>
                  ) : null}
                  <td>
                    <a className="cat-fordon" href={vehiclePath(vehicle.id)} onClick={linkClick(navigate, vehiclePath(vehicle.id))}>
                      <b>{title(t, vehicle)}</b>
                      {vehicle.status === "draft" ? <span className="cat-pill">{t("draft")}</span> : null}
                    </a>
                    <span className="cat-under">{subtitle(t, vehicle)}</span>
                  </td>
                  <td className="cat-evn tm-mono">{vehicle.evn?.text ?? ""}</td>
                  <td>
                    <div className="cat-var">
                      {vehicle.state !== "home" ? <StatePill t={t} state={vehicle.state} /> : null}
                      <span>{whereText(vehicle)}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

/** Choose a place to move one or several vehicles to (CAT-73). */
export function MoveDialog({
  ctx,
  open,
  places,
  onClose,
  onMove,
}: {
  ctx: Ctx;
  open: boolean;
  places: Place[];
  onClose: () => void;
  onMove: (place: string | null) => Promise<void>;
}) {
  const { t } = ctx;
  const [busy, setBusy] = useState(false);
  const choose = async (place: string | null) => {
    setBusy(true);
    await onMove(place);
    setBusy(false);
  };
  return (
    <Dialog open={open} title={t("moveTitle")} onClose={onClose}>
      <ul className="cat-platsval">
        {places.map((place) => (
          <li key={place.id}>
            <button type="button" className="tm-knapp" disabled={busy} onClick={() => choose(place.id)}>
              {place.name}
            </button>
          </li>
        ))}
        <li>
          <button type="button" className="tm-knapp" disabled={busy} onClick={() => choose(null)}>
            {t("noPlace")}
          </button>
        </li>
      </ul>
      <div className="cat-dialogknappar">
        <button type="button" className="tm-knapp" onClick={onClose}>
          {t("cancel")}
        </button>
      </div>
    </Dialog>
  );
}

export function VehiclesPage({ ctx, account }: { ctx: Ctx; account: Account }) {
  const [q, setQ] = useState("");
  const [state, setState] = useState<VehicleState | null>(null);
  const [group, setGroup] = useState<KindGroup>("all");
  const [list, setList] = useState<VehicleList | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [places, setPlaces] = useState<Place[]>([]);
  const [moving, setMoving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState(0);

  useEffect(() => {
    let current = true;
    const timer = window.setTimeout(() => {
      api.vehicles({ q, state, kinds: GROUPS[group] }).then(
        (found) => current && (setList(found), setError(null)),
        (failure) => current && setError(problemText(ctx.t, failure)),
      );
    }, 200);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [q, state, group, round, ctx.t]);

  return (
    <>
      <VehiclesView
        ctx={ctx}
        account={account}
        list={list}
        q={q}
        state={state}
        group={group}
        selected={selected}
        error={error}
        onQ={setQ}
        onState={setState}
        onGroup={setGroup}
        onSelect={(id, on) =>
          setSelected((before) => {
            const next = new Set(before);
            if (on) next.add(id);
            else next.delete(id);
            return next;
          })
        }
        onMove={() => {
          api.places().then(setPlaces, () => setPlaces([]));
          setMoving(true);
        }}
      />
      <MoveDialog
        ctx={ctx}
        open={moving}
        places={places}
        onClose={() => setMoving(false)}
        onMove={async (place) => {
          try {
            await api.move([...selected], place);
            setSelected(new Set());
            setMoving(false);
            setRound((n) => n + 1);
          } catch (failure) {
            setMoving(false);
            setError(problemText(ctx.t, failure));
          }
        }}
      />
    </>
  );
}

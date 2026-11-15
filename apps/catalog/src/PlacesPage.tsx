// Platser: the owner's own boxes and shelves, with how many are at home, and what is lent out
// (CAT-71, CAT-74, CAT-76).
import { linkClick } from "@trainmeet/design";
import { useEffect, useId, useState } from "react";
import { api, type Place, type Vehicle } from "./api";
import { Crumbs, dateText, Dialog, ErrorLine, problemText, title, type Ctx } from "./common";
import { PATHS, vehiclePath } from "./routes";

export type PlacesViewProps = {
  ctx: Ctx;
  places: Place[] | null;
  lent: Vehicle[];
  error: string | null;
  showName?: boolean | null;
  onShowName?: (on: boolean) => void;
  onAdd?: (name: string) => Promise<boolean>;
  onRename?: (place: Place, name: string) => Promise<boolean>;
  onRemove?: (place: Place) => void;
  onGiveBack?: (vehicle: Vehicle) => void;
};

function PlaceCard({ ctx, place, onRename, onRemove }: { ctx: Ctx; place: Place; onRename?: PlacesViewProps["onRename"]; onRemove?: PlacesViewProps["onRemove"] }) {
  const { t } = ctx;
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(place.name);
  const id = useId();
  return (
    <li className="tm-kort cat-plats">
      {editing ? (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            if (await onRename?.(place, name.trim())) setEditing(false);
          }}
        >
          <label htmlFor={id}>{t("placeName")}</label>
          <input id={id} value={name} maxLength={60} autoFocus onChange={(e) => setName(e.target.value)} />
          <div className="cat-knappar">
            <button type="button" className="tm-knapp" onClick={() => (setEditing(false), setName(place.name))}>
              {t("cancel")}
            </button>
            <button type="submit" className="tm-knapp primar" disabled={!name.trim()}>
              {t("save")}
            </button>
          </div>
        </form>
      ) : (
        <>
          <div className="cat-platsrubrik">
            <h2>{place.name}</h2>
            <span className="tm-mono" aria-label={t("placeCountLabel", { home: place.vehicles_home, all: place.vehicles })}>
              {t("placeCount", { home: place.vehicles_home, all: place.vehicles })}
            </span>
          </div>
          <div className="cat-knappar">
            <button type="button" className="tm-knapp" aria-label={`${t("rename")}: ${place.name}`} onClick={() => setEditing(true)}>
              {t("rename")}
            </button>
            <button type="button" className="tm-knapp" aria-label={`${t("removePlace")}: ${place.name}`} onClick={() => onRemove?.(place)}>
              {t("removePlace")}
            </button>
          </div>
        </>
      )}
    </li>
  );
}

export function PlacesView({ ctx, places, lent, error, onAdd, onRename, onRemove, onGiveBack, showName, onShowName }: PlacesViewProps) {
  const { t, language, navigate } = ctx;
  const [name, setName] = useState("");
  const id = useId();
  return (
    <>
      <Crumbs ctx={ctx} items={[{ href: PATHS.vehicles, label: t("vehicles") }, { label: t("places") }]} />
      <p className="tm-overrubrik">{t("placesEyebrow")}</p>
      <h1>{t("placesTitle")}</h1>
      <p className="cat-ingress">{t("placesIntro")}</p>
      <ErrorLine text={error} />
      <div className="cat-kortet">
        <div>
          {places === null ? (
            <p className="cat-laddar">{t("loading")}</p>
          ) : (
            <ul className="cat-platser">
              {places.map((place) => (
                <PlaceCard key={place.id} ctx={ctx} place={place} onRename={onRename} onRemove={onRemove} />
              ))}
              <li className="tm-kort cat-plats cat-ny-plats">
                <form
                  onSubmit={async (event) => {
                    event.preventDefault();
                    if (name.trim() && (await onAdd?.(name.trim()))) setName("");
                  }}
                >
                  <label htmlFor={id}>{t("newPlace")}</label>
                  <input id={id} value={name} maxLength={60} placeholder={t("placeName")} onChange={(e) => setName(e.target.value)} />
                  <button type="submit" className="tm-knapp" disabled={!name.trim()}>
                    {t("add")}
                  </button>
                </form>
              </li>
            </ul>
          )}
        </div>
        <div className="cat-sidokolumn">
        <section className="tm-kort" aria-labelledby="utlanat-rubrik">
          <h2 id="utlanat-rubrik">{t("lentOut")}</h2>
          {lent.length === 0 ? (
            <p className="cat-under">{t("lentNone")}</p>
          ) : (
            <ul className="cat-utlanat">
              {lent.map((vehicle) => (
                <li key={vehicle.id}>
                  <div>
                    <a href={vehiclePath(vehicle.id)} onClick={linkClick(navigate, vehiclePath(vehicle.id))}>
                      <b>{title(t, vehicle)}</b>
                    </a>
                    {vehicle.lending ? (
                      <span className="cat-under">{t("lentTo", { name: vehicle.lending.to, date: dateText(language, vehicle.lending.since) })}</span>
                    ) : null}
                  </div>
                  <button type="button" className="tm-knapp" onClick={() => onGiveBack?.(vehicle)}>
                    {t("giveBack")}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="tm-kort cat-avsnitt" aria-labelledby="installningar-rubrik">
          <h2 id="installningar-rubrik">{t("settingsTitle")}</h2>
          <label className="cat-vaxel">
            <input
              type="checkbox"
              role="switch"
              checked={showName ?? false}
              disabled={showName === null || showName === undefined}
              aria-describedby="visa-namn-hjalp"
              onChange={(event) => onShowName?.(event.target.checked)}
            />
            <span>{t("showName")}</span>
          </label>
          <p id="visa-namn-hjalp" className="cat-hjalp">
            {t("showNameHelp")}
          </p>
        </section>
        </div>
      </div>
    </>
  );
}

export function PlacesPage({ ctx }: { ctx: Ctx }) {
  const { t } = ctx;
  const [places, setPlaces] = useState<Place[] | null>(null);
  const [lent, setLent] = useState<Vehicle[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Place | null>(null);
  const [showName, setShowName] = useState<boolean | null>(null);
  const load = () => {
    api.settings().then((settings) => setShowName(settings.show_name), () => setShowName(null));
    api.places().then(setPlaces, (failure) => setError(problemText(t, failure)));
    api.vehicles({ state: "lent" }).then((list) => setLent(list.vehicles), () => setLent([]));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- load once
  useEffect(load, []);
  const attempt = async (work: () => Promise<unknown>) => {
    try {
      setError(null);
      await work();
      load();
      return true;
    } catch (failure) {
      setError(problemText(t, failure));
      return false;
    }
  };
  return (
    <>
      <PlacesView
        ctx={ctx}
        places={places}
        lent={lent}
        error={error}
        onAdd={(name) => attempt(() => api.addPlace(name))}
        onRename={(place, name) => attempt(() => api.renamePlace(place.id, name))}
        onRemove={setRemoving}
        onGiveBack={(vehicle) => void attempt(() => api.giveBack(vehicle.id, vehicle.version))}
        showName={showName}
        onShowName={(on) => {
          setShowName(on);
          void attempt(() => api.changeSettings(on));
        }}
      />
      <Dialog open={removing !== null} title={t("removePlace")} onClose={() => setRemoving(null)}>
        <p>{removing ? t("removePlaceConfirm", { name: removing.name }) : ""}</p>
        <div className="cat-dialogknappar">
          <button type="button" className="tm-knapp" onClick={() => setRemoving(null)}>
            {t("cancel")}
          </button>
          <button
            type="button"
            className="tm-knapp cat-fara"
            onClick={async () => {
              const place = removing;
              setRemoving(null);
              if (place) await attempt(() => api.removePlace(place.id));
            }}
          >
            {t("removeYes")}
          </button>
        </div>
      </Dialog>
    </>
  );
}

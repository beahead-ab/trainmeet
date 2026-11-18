// Bilderna on the vehicle card: the main picture large and all of them as thumbnails in their
// order, and for someone who may edit, adding, choosing the main one, changing the background
// and removing (CAT-05, CAT-17, CAT-123–CAT-133).
import { useEffect, useId, useState } from "react";
import {
  api,
  ApiError,
  BACKGROUNDS,
  PICTURE_KINDS,
  PICTURE_MAX_BYTES,
  PICTURES_PER_VEHICLE,
  type Picture,
  type PictureBackground,
  type StorageUse,
  type Vehicle,
} from "./api";
import { Dialog, ErrorLine, isOwner, mayEdit, problemText, title, type Ctx, type T } from "./common";
import type { Language } from "./i18n";

const MB = 1024 * 1024;
const GB = 1024 * MB;

/** What Catalog would refuse anyway, seen before the picture is sent (CAT-123). */
export function checkPicture(file: { size: number; type: string }): "bad_picture" | "picture_too_large" | null {
  if (!(PICTURE_KINDS as readonly string[]).includes(file.type)) return "bad_picture";
  if (file.size > PICTURE_MAX_BYTES) return "picture_too_large";
  return null;
}

/** The storage as the line shows it: what is paid over the free level is optional. */
export type StorageLine = Pick<StorageUse, "used" | "limit" | "club"> & Partial<Pick<StorageUse, "over_free" | "paid_blocks" | "price_per_gb" | "unpaid">>;

/** "Lagring: 12 av 100 MB", the club's in GB (CAT-131, TOKEN-29), or the owner's for someone
 * who edits a fleet shared with them (CAT-133). Over the free level, what is paid this month,
 * "Lagring: 1,3 av 0,1 GB · 40 tokens den här månaden", or that the month is not paid (CAT-132). */
export function storageText(t: T, language: Language, storage: StorageLine, shared = false): string {
  const unit = Math.max(storage.limit, storage.used) >= GB ? "GB" : "MB";
  const size = unit === "GB" ? GB : MB;
  const number = new Intl.NumberFormat(language === "sv" ? "sv-SE" : "en-GB", { maximumFractionDigits: 1 });
  const used = storage.used / size;
  const line = t(storage.club ? "storageClub" : shared ? "storageOwner" : "storage", {
    used: number.format(storage.used > 0 && used < 0.1 ? 0.1 : used),
    limit: number.format(storage.limit / size),
    unit,
  });
  const price = storage.price_per_gb ?? 20;
  const paid = storage.paid_blocks ?? 0;
  if (storage.unpaid) return `${line} · ${t("storageUnpaid")}`;
  if (paid > 0) return `${line} · ${t("storagePaid", { tokens: number.format(paid * price) })}`;
  if (storage.over_free) return `${line} · ${t("storagePrice", { price })}`;
  return line;
}

/** Why a picture could not be added or changed. A 413 may come from the proxy, without Catalog's answer. */
export function pictureProblem(t: T, error: unknown): string {
  if (error instanceof ApiError && error.status === 413) return t("problem_picture_too_large");
  if (error instanceof ApiError && error.code === "unavailable") return t("picturesUnavailable");
  // For a picture, too many is the cap of tokens per day in ID (TK15, CAT-132).
  if (error instanceof ApiError && error.code === "too_many") return t("storageCap");
  return problemText(t, error);
}

/** What is going on just now: the upload with how much is sent (0–1), a new background, or the rest. */
export type PicturesWork = { what: "upload"; sent: number } | { what: "background" } | { what: "other" };

export type PicturesViewProps = {
  ctx: Ctx;
  vehicle: Vehicle;
  /** The pictures in order, or null while they are read. */
  pictures: Picture[] | null;
  /** The fleet owner's storage, for someone who may edit. */
  storage: StorageUse | null;
  work: PicturesWork | null;
  error: string | null;
  /** The picture shown large; the main one when none is chosen. */
  chosen?: string | null;
  onChoose?: (picture: string) => void;
  onAdd?: (file: File, keepOriginal: boolean, background: PictureBackground) => void;
  onMain?: (picture: Picture) => void;
  onBackground?: (picture: Picture) => void;
  onRemove?: (picture: Picture) => void;
};

function WorkLine({ t, work }: { t: T; work: PicturesWork | null }) {
  const sending = work?.what === "upload" && work.sent < 1 ? work.sent : null;
  const label =
    work?.what === "upload"
      ? sending !== null
        ? t("uploading", { percent: Math.round(sending * 100) })
        : t("preparing")
      : work?.what === "background"
        ? t("changingBackground")
        : null;
  return (
    <div className="cat-arbete" aria-live="polite">
      {label ? (
        <>
          <progress max={1} value={sending ?? undefined} aria-hidden="true" />
          <span>{label}</span>
        </>
      ) : null}
    </div>
  );
}

/** The pictures as they look, from the state. Rendered in the tests without fetching. */
export function PicturesView(props: PicturesViewProps) {
  const { ctx, vehicle, pictures, storage, work, error } = props;
  const { t, language } = ctx;
  const [keepOriginal, setKeepOriginal] = useState(false);
  const [background, setBackground] = useState<PictureBackground>("original");
  const id = useId();
  const editing = mayEdit(ctx);
  const name = title(t, vehicle);
  const list = pictures ?? [];
  const shown = list.find((p) => p.id === props.chosen) ?? list.find((p) => p.main) ?? list[0] ?? null;
  // While the pictures are read, the vehicle's main picture is already known (CAT-125).
  const early = pictures === null ? (vehicle.picture ?? null) : null;
  if (!editing && !shown && !early && !error) return null;

  const busy = work !== null;
  const full = list.length >= PICTURES_PER_VEHICLE;
  const backgrounds = storage?.backgrounds ?? false;
  const place = shown ? list.indexOf(shown) + 1 : 0;
  return (
    <section className="tm-kort cat-bilder" aria-labelledby="bilder-rubrik">
      <div className="cat-kortrubrik">
        <h2 id="bilder-rubrik">{t("pictures")}</h2>
        {editing && list.length > 0 ? <span className="cat-under">{t("pictureCount", { n: list.length, max: PICTURES_PER_VEHICLE })}</span> : null}
      </div>

      {shown ? (
        <figure className="cat-huvudbild">
          <img src={shown.display_url} alt={list.length > 1 ? t("pictureAlt", { name, n: place, of: list.length }) : name} width={shown.width} height={shown.height} />
          {editing ? (
            <figcaption className="cat-under">
              {shown.main ? t("mainPicture") : t("pictureN", { n: place, of: list.length })} · {t("backgroundNow", { background: t(`bg_${shown.background}`) })}
            </figcaption>
          ) : null}
        </figure>
      ) : early ? (
        <figure className="cat-huvudbild">
          <img src={early.display_url} alt={name} />
        </figure>
      ) : pictures === null ? (
        error ? null : <p className="cat-laddar">{t("loading")}</p>
      ) : (
        <p className="cat-under">{t("noPictures")}</p>
      )}

      {editing && shown ? (
        <div className="cat-knappar">
          {!shown.main ? (
            <button type="button" className="tm-knapp" disabled={busy} onClick={() => props.onMain?.(shown)}>
              {t("makeMain")}
            </button>
          ) : null}
          {backgrounds || shown.background !== "original" ? (
            <button type="button" className="tm-knapp" disabled={busy} onClick={() => props.onBackground?.(shown)}>
              {t("changeBackground")}
            </button>
          ) : null}
          <button type="button" className="tm-knapp cat-fara" disabled={busy} onClick={() => props.onRemove?.(shown)}>
            {t("removeYes")}
          </button>
        </div>
      ) : null}

      {list.length > 1 ? (
        <ul className="cat-miniatyrer">
          {list.map((picture, index) => (
            <li key={picture.id}>
              <button
                type="button"
                className="cat-miniatyr"
                aria-pressed={picture.id === shown?.id}
                aria-label={`${t("showPicture", { n: index + 1, of: list.length })}${picture.main ? `, ${t("mainPicture")}` : ""}`}
                onClick={() => props.onChoose?.(picture.id)}
              >
                <img src={picture.thumb_url} alt="" width={96} height={64} loading="lazy" decoding="async" />
              </button>
              {picture.main ? <span className="cat-miniatyr-huvud">{t("mainPicture")}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}

      <ErrorLine text={error} />
      <WorkLine t={t} work={work} />

      {editing ? (
        <div className="cat-nybild">
          <div className="cat-bildval">
            {backgrounds ? (
              <div className="cat-falt">
                <label htmlFor={`${id}-bakgrund`}>{t("background")}</label>
                <select id={`${id}-bakgrund`} value={background} disabled={busy} onChange={(event) => setBackground(event.target.value as PictureBackground)}>
                  {BACKGROUNDS.map((choice) => (
                    <option key={choice} value={choice}>
                      {t(`bg_${choice}`)}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <label className="cat-vaxel">
              <input type="checkbox" checked={keepOriginal} disabled={busy} aria-describedby={`${id}-original`} onChange={(event) => setKeepOriginal(event.target.checked)} />
              <span>{t("keepOriginal")}</span>
            </label>
          </div>
          <p id={`${id}-original`} className="cat-hjalp">
            {t("keepOriginalHelp")}
          </p>
          {storage && !backgrounds ? <p className="cat-hjalp">{t("backgroundsOff")}</p> : null}
          <label className={`tm-knapp cat-bildknapp${full || busy || pictures === null ? " cat-av" : ""}`}>
            <input
              className="cat-dold"
              type="file"
              accept={PICTURE_KINDS.join(",")}
              disabled={full || busy || pictures === null}
              aria-describedby={`${id}-ny`}
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) props.onAdd?.(file, keepOriginal, backgrounds ? background : "original");
              }}
            />
            {t("addPicture")}
          </label>
          <p id={`${id}-ny`} className="cat-hjalp">
            {full ? t("picturesFull", { max: PICTURES_PER_VEHICLE }) : t("addPictureHelp")}
          </p>
          {storage ? <p className={storage.unpaid ? "cat-lagring cat-obetald" : "cat-lagring"}>{storageText(t, language, storage, !isOwner(ctx))}</p> : null}
        </div>
      ) : null}
    </section>
  );
}

/** The pictures with their state: read, and read again after every change, since the
 * addresses expire after about an hour (CAT-130). */
export function PicturesSection({ ctx, vehicle }: { ctx: Ctx; vehicle: Vehicle }) {
  const { t } = ctx;
  const editing = mayEdit(ctx);
  const [pictures, setPictures] = useState<Picture[] | null>(null);
  const [storage, setStorage] = useState<StorageUse | null>(null);
  const [work, setWork] = useState<PicturesWork | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [changing, setChanging] = useState<Picture | null>(null);
  const [removing, setRemoving] = useState<Picture | null>(null);

  const load = () => {
    // Without a main picture the vehicle has none (CAT-125), so someone who looks need not ask.
    if (editing || vehicle.picture) api.pictures(vehicle.id).then(setPictures, (failure) => setError(pictureProblem(t, failure)));
    else setPictures([]);
    if (editing) api.storage().then(setStorage, () => setStorage(null));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- load reads only the vehicle's id
  useEffect(load, [vehicle.id]);

  const act = async (what: PicturesWork, job: () => Promise<unknown>) => {
    setError(null);
    setWork(what);
    try {
      await job();
    } catch (failure) {
      setError(pictureProblem(t, failure));
    }
    setWork(null);
    load();
  };

  const add = (file: File, keepOriginal: boolean, background: PictureBackground) => {
    const problem = checkPicture(file);
    if (problem) {
      setError(t(`problem_${problem}`));
      return;
    }
    void act({ what: "upload", sent: 0 }, async () => {
      const added = await api.addPicture(vehicle.id, file, keepOriginal, background, (sent) => setWork({ what: "upload", sent }));
      setChosen(added.id);
    });
  };

  return (
    <>
      <PicturesView
        ctx={ctx}
        vehicle={vehicle}
        pictures={pictures}
        storage={storage}
        work={work}
        error={error}
        chosen={chosen}
        onChoose={setChosen}
        onAdd={add}
        onMain={(picture) => void act({ what: "other" }, () => api.mainPicture(vehicle.id, picture.id))}
        onBackground={setChanging}
        onRemove={setRemoving}
      />
      {editing ? (
        <>
          <Dialog open={changing !== null} title={t("changeBackground")} onClose={() => setChanging(null)}>
            {storage && !storage.backgrounds ? <p className="cat-hjalp">{t("backgroundsOff")}</p> : null}
            <ul className="cat-platsval">
              {BACKGROUNDS.map((choice) => (
                <li key={choice}>
                  <button
                    type="button"
                    className="tm-knapp"
                    aria-pressed={changing?.background === choice}
                    disabled={changing?.background === choice || (!storage?.backgrounds && choice !== "original")}
                    onClick={() => {
                      const picture = changing;
                      setChanging(null);
                      if (picture) void act({ what: "background" }, () => api.pictureBackground(vehicle.id, picture.id, choice));
                    }}
                  >
                    {t(`bg_${choice}`)}
                  </button>
                </li>
              ))}
            </ul>
            <div className="cat-dialogknappar">
              <button type="button" className="tm-knapp" onClick={() => setChanging(null)}>
                {t("cancel")}
              </button>
            </div>
          </Dialog>
          <Dialog open={removing !== null} title={t("removePictureTitle")} onClose={() => setRemoving(null)}>
            {removing ? <img className="cat-dialogbild" src={removing.thumb_url} alt="" width={120} height={80} /> : null}
            <p>{t("removePictureConfirm", { name: title(t, vehicle) })}</p>
            <div className="cat-dialogknappar">
              <button type="button" className="tm-knapp" onClick={() => setRemoving(null)}>
                {t("cancel")}
              </button>
              <button
                type="button"
                className="tm-knapp cat-fara"
                onClick={() => {
                  const picture = removing;
                  setRemoving(null);
                  if (picture)
                    void act({ what: "other" }, async () => {
                      await api.removePicture(vehicle.id, picture.id);
                      setChosen(null);
                    });
                }}
              >
                {t("removeYes")}
              </button>
            </div>
          </Dialog>
        </>
      ) : null}
    </>
  );
}

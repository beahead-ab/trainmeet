// Lägg till med foto (#52, CAT-134–CAT-146): fota, AI:n föreslår, granska, plats och tagg,
// klart. Every step can be skipped. The AI only suggests: the suggestions stand marked in the
// ordinary form until the owner accepts or edits them, and Spara accepts the rest (CAT-136). A
// reading stores nothing (CAT-143): Spara makes the vehicle through its own address, and the
// photos become its pictures afterwards. The logic is in reading.ts.
import { linkClick } from "@trainmeet/design";
import { useEffect, useId, useState, type ReactNode } from "react";
import { api, PICTURE_KINDS, READING_PICTURES, type Place, type ReadingConsent, type SuggestedField, type Vehicle } from "./api";
import { Crumbs, Dialog, ErrorLine, isOwner, problemText, title, type Ctx, type T } from "./common";
import type { TextKey } from "./i18n";
import { pictureProblem } from "./Pictures";
import { SuggestedPrototype } from "./PrototypeBlock";
import {
  accept,
  addPhotos,
  answer,
  applyReading,
  attemptReading,
  edit,
  needsConsent,
  newFlow,
  openQuestion,
  readingTrouble,
  removePhoto,
  saveVehicle,
  skipReading,
  stillUnreadable,
  uncertainPart,
  uploadPhotos,
  type Flow,
  type FlowStep,
  type Trouble,
} from "./reading";
import { PATHS, vehiclePath } from "./routes";
import { FormView, PlaceField } from "./VehicleForm";

const STEPS: TextKey[] = ["photoStepPhoto", "photoStepDetails", "photoStepPlace"];
const AT: Record<FlowStep, number> = { photo: 1, reading: 2, review: 2, place: 3, done: 4 };
const LABELS: Record<SuggestedField, TextKey> = {
  kind: "fKind",
  litt: "fLitt",
  number: "fNumber",
  operator: "fOperator",
  maker: "fMaker",
  article_number: "fArticle",
};

/** Foto, Uppgifter, Plats och tagg: where the person is. */
export function Steps({ t, step }: { t: T; step: FlowStep }) {
  const at = AT[step];
  return (
    <ol className="cat-fotosteg" aria-label={t("photoSteps")}>
      {STEPS.map((label, index) => (
        <li key={label} className={index + 1 < at ? "cat-gjort" : undefined} aria-current={index + 1 === at ? "step" : undefined}>
          {t(label)}
          {index + 1 < at ? <span className="cat-dold">, {t("photoStepDone")}</span> : null}
        </li>
      ))}
    </ol>
  );
}

const slotText = (t: T, index: number) => t(index === 0 ? "photoSlotSide" : index === 1 ? "photoSlotNumber" : "photoSlotMore");

function Crumb({ ctx }: { ctx: Ctx }) {
  return <Crumbs ctx={ctx} items={[{ href: PATHS.vehicles, label: ctx.t("vehicles") }, { label: ctx.t("photoTitle") }]} />;
}

function BuyTokens({ ctx }: { ctx: Ctx }) {
  return ctx.tokensUrl ? (
    <a className="tm-knapp" href={ctx.tokensUrl}>
      {ctx.t("buyTokens")}
    </a>
  ) : (
    <p>{ctx.t("buyTokens")}.</p>
  );
}

/** The price before the reading starts (CAT-19): 12 tokens a picture, or nothing with own AI. */
export function Price({ ctx, consent, photos }: { ctx: Ctx; consent: ReadingConsent | null; photos: number }) {
  const { t, language } = ctx;
  if (!consent) return <p className="cat-laddar">{t("loading")}</p>;
  if (consent.own_ai) return <p className="cat-pris">{t("readOwnAi", { model: consent.own_ai })}</p>;
  const number = (n: number) => n.toLocaleString(language === "en" ? "en-GB" : "sv-SE");
  const price = consent.price_per_picture;
  const total = price * photos;
  const balance = consent.balance;
  return (
    <>
      <p className="cat-pris">
        <span>{photos ? t("readPrice", { n: photos, price }) : t("readPriceEach", { price })}</span>
        {photos ? <b>{t("readTotal", { total: number(total) })}</b> : null}
      </p>
      {balance !== null ? (
        <p className="cat-hjalp">{consent.payer ? t("readBalanceOf", { balance: number(balance), payer: consent.payer }) : t("readBalance", { balance: number(balance) })}</p>
      ) : null}
      {balance !== null && total > balance ? (
        <div className="cat-besvar">
          <p className="cat-varning">{t("readShort")}</p>
          <BuyTokens ctx={ctx} />
        </div>
      ) : null}
    </>
  );
}

function TroubleLine({ ctx, trouble }: { ctx: Ctx; trouble: Trouble | null }) {
  if (!trouble) return null;
  return (
    <div className="cat-besvar" role="alert">
      <p className="cat-fel">{trouble.text}</p>
      {trouble.buyTokens ? <BuyTokens ctx={ctx} /> : null}
    </div>
  );
}

function Strip({ t, previews }: { t: T; previews: string[] }) {
  if (previews.length === 0) return null;
  return (
    <ul className="cat-fotoremsa">
      {previews.map((url, index) => (
        <li key={url}>
          <img src={url} alt={t("photoAlt", { n: index + 1, what: slotText(t, index) })} />
        </li>
      ))}
    </ul>
  );
}

export type PhotoStepProps = {
  ctx: Ctx;
  flow: Flow;
  /** The photos' addresses in the browser, for the thumbnails. */
  previews: string[];
  consent: ReadingConsent | null;
  trouble: Trouble | null;
  /** A photo Catalog would refuse anyway (CAT-123). */
  problem: string | null;
  onAdd?: (files: File[]) => void;
  onRemove?: (index: number) => void;
  onRead?: () => void;
  onSkip?: () => void;
};

/** Fota: 1–4 photos with the advice (CAT-135), and the price before anything is read (CAT-19). */
export function PhotoStepView({ ctx, flow, previews, consent, trouble, problem, onAdd, onRemove, onRead, onSkip }: PhotoStepProps) {
  const { t } = ctx;
  const id = useId();
  const count = flow.photos.length;
  const full = count >= READING_PICTURES;
  const notHere = consent !== null && !consent.available;
  const manual = notHere || (trouble?.byHand ?? false);
  return (
    <>
      <Crumb ctx={ctx} />
      <Steps t={t} step="photo" />
      <p className="tm-overrubrik">{t("photoStepOf", { n: 1 })}</p>
      <h1>{t("photoHeading")}</h1>
      <p className="cat-ingress">{t("photoAdvice")}</p>
      <div className="cat-kortet">
        <section className="tm-kort cat-foton" aria-labelledby={`${id}-foton`}>
          <div className="cat-kortrubrik">
            <h2 id={`${id}-foton`}>{t("photosTitle")}</h2>
            <span className="cat-under">{t("photosCount", { n: count })}</span>
          </div>
          {count ? (
            <ul className="cat-fotoval">
              {flow.photos.map((photo, index) => (
                <li key={`${index}-${photo.name}`}>
                  {previews[index] ? <img src={previews[index]} alt={t("photoAlt", { n: index + 1, what: slotText(t, index) })} /> : <span className="cat-fotoplats" />}
                  <span className="cat-under">
                    {slotText(t, index)}
                    {index === 0 ? ` · ${t("photoMain")}` : ""}
                  </span>
                  <button type="button" className="tm-knapp cat-godkann" aria-label={t("photoRemove", { n: index + 1 })} onClick={() => onRemove?.(index)}>
                    {t("removeYes")}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <label className={`tm-knapp cat-bildknapp${full ? " cat-av" : ""}`}>
            <input
              className="cat-dold"
              type="file"
              accept={PICTURE_KINDS.join(",")}
              multiple
              disabled={full}
              aria-describedby={`${id}-hjalp`}
              onChange={(event) => {
                const files = [...(event.target.files ?? [])];
                event.target.value = "";
                if (files.length) onAdd?.(files);
              }}
            />
            {t("photoAdd")}
          </label>
          <p id={`${id}-hjalp`} className="cat-hjalp">
            {full ? t("photosFull") : t("photoHelp")}
          </p>
          <ErrorLine text={problem} />
        </section>

        <section className="tm-kort cat-lasav" aria-labelledby={`${id}-lasav`}>
          <h2 id={`${id}-lasav`}>{t("readTitle")}</h2>
          <p>{t("photoReads")}</p>
          <p className="cat-hjalp">{t("readIntro")}</p>
          {notHere ? <p className="cat-varning">{t("readNotHere")}</p> : <Price ctx={ctx} consent={consent} photos={count} />}
          <TroubleLine ctx={ctx} trouble={trouble} />
          {notHere ? null : (
            <button type="button" className={manual ? "tm-knapp" : "tm-knapp primar"} disabled={count === 0} onClick={onRead}>
              {count === 1 ? t("readButtonOne") : t("readButton", { n: Math.max(count, 1) })}
            </button>
          )}
          <button type="button" className={manual ? "tm-knapp primar" : "tm-knapp"} onClick={onSkip}>
            {flow.reading ? t("backToDetails") : t("skipReading")}
          </button>
        </section>
      </div>
    </>
  );
}

/** AI:n läser: the progress while the photos are read. */
export function ReadingView({ ctx, flow, previews }: { ctx: Ctx; flow: Flow; previews: string[] }) {
  const { t } = ctx;
  const count = flow.photos.length;
  return (
    <>
      <Crumb ctx={ctx} />
      <Steps t={t} step="reading" />
      <p className="tm-overrubrik">{t("photoStepOf", { n: 2 })}</p>
      <h1>{t("readingTitle")}</h1>
      <section className="tm-kort cat-lasning" role="status">
        <p>
          <b>{count === 1 ? t("readingNowOne") : t("readingNow", { n: count })}</b>
        </p>
        <progress aria-hidden="true" />
        <p className="cat-hjalp">{t("readingWait")}</p>
        <Strip t={t} previews={previews} />
      </section>
    </>
  );
}

/** What is sent and to whom, before the first reading (CAT-142). In Swedish, the very text the
 * person says yes to, whose version Catalog keeps; in English the same in English. */
export function ConsentView({ ctx, consent, photos, onYes, onNo }: { ctx: Ctx; consent: ReadingConsent | null; photos: number; onYes?: () => void; onNo?: () => void }) {
  const { t, language } = ctx;
  const to = consent?.own_ai ? t("consentOwnAi", { model: consent.own_ai }) : t("consentTrainMeets");
  return (
    <div className="cat-samtycke">
      <p>{language === "sv" && consent ? consent.text : t("consentSent", { to })}</p>
      <Price ctx={ctx} consent={consent} photos={photos} />
      <p className="cat-hjalp">{t("consentKeeps")}</p>
      <p className="cat-hjalp">{t("consentOnce")}</p>
      <div className="cat-dialogknappar">
        <button type="button" className="tm-knapp" onClick={onNo}>
          {t("cancel")}
        </button>
        <button type="button" className="tm-knapp primar" onClick={onYes}>
          {t("consentYes")}
        </button>
      </div>
    </div>
  );
}

const orList = (t: T, items: string[]) => (items.length < 2 ? (items[0] ?? "") : `${items.slice(0, -1).join(", ")} ${t("or")} ${items[items.length - 1]}`);

/** The uncertain digit, with the options whose EVN check digit adds up (CAT-140). */
export function QuestionView({ ctx, number, options, canAdd, onAnswer, onCloseUp }: { ctx: Ctx; number: string; options: string[]; canAdd: boolean; onAnswer?: (option: string) => void; onCloseUp?: () => void }) {
  const { t } = ctx;
  const id = useId();
  const parts = options.map((option) => uncertainPart(number, option));
  return (
    <section className="tm-kort cat-kolla" aria-labelledby={id}>
      <p className="tm-overrubrik">{t("checkTitle")}</p>
      <h2 id={id}>{parts.length === 1 ? t("questionOne", { a: parts[0] ?? "" }) : t("questionMany", { list: orList(t, parts) })}</h2>
      <p className="tm-mono cat-osaker">{number}</p>
      <div className="cat-knappar">
        {options.map((option, index) => (
          <button key={option} type="button" className="tm-knapp" aria-label={t("questionOption", { option })} onClick={() => onAnswer?.(option)}>
            {t("questionOption", { option: parts[index] ?? option })}
          </button>
        ))}
        {canAdd ? (
          <button type="button" className="tm-knapp" onClick={onCloseUp}>
            {t("closeUp")}
          </button>
        ) : null}
      </div>
      <p className="cat-hjalp">{t("questionWhy")}</p>
    </section>
  );
}

export type ReviewProps = {
  ctx: Ctx;
  flow: Flow;
  previews: string[];
  busy: boolean;
  error: string | null;
  onChange?: (flow: Flow) => void;
  onMorePhotos?: () => void;
  onSave?: () => void;
};

/** AI:n föreslår, and granska: the ordinary form, with the suggestions marked (CAT-136), the
 * question (CAT-140), the AI's wish for another photo (CAT-135), and what it saw. Without a
 * reading it is simply the form. */
export function ReviewView({ ctx, flow, previews, busy, error, onChange, onMorePhotos, onSave }: ReviewProps) {
  const { t } = ctx;
  const reading = flow.reading;
  const options = openQuestion(flow);
  const unreadable = stillUnreadable(flow);
  const canAdd = flow.photos.length < READING_PICTURES;
  const marked = Object.keys(flow.marks).length > 0;
  const warnings = reading?.warnings ?? [];
  const before = (
    <div className="cat-fore">
      <Strip t={t} previews={previews} />
      {options ? (
        <QuestionView ctx={ctx} number={String(flow.fields.number ?? "")} options={options} canAdd={canAdd} onAnswer={(option) => onChange?.(answer(flow, option))} onCloseUp={onMorePhotos} />
      ) : null}
      {reading?.suggested_next_photo ? (
        <section className="tm-kort cat-avsnitt" aria-label={t("nextPhotoTitle")}>
          <h2>{t("nextPhotoTitle")}</h2>
          <p>{reading.suggested_next_photo}</p>
          <button type="button" className="tm-knapp" disabled={!canAdd} onClick={onMorePhotos}>
            {t("nextPhoto")}
          </button>
          <p className="cat-hjalp">{canAdd ? t("nextPhotoNew") : t("photosFull")}</p>
        </section>
      ) : null}
      {reading ? (
        <section className="tm-kort cat-avsnitt" aria-label={t("summaryTitle")}>
          <h2>{t("summaryTitle")}</h2>
          {reading.summary ? <p>{reading.summary}</p> : null}
          {warnings.length ? (
            <>
              <p className="cat-varning">{t("checkTitle")}</p>
              <ul className="cat-varningar">
                {warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </>
          ) : null}
          <p className="cat-hjalp">{reading.cost ? t("readCost", { model: reading.model, cost: reading.cost }) : t("readCostFree", { model: reading.model })}</p>
        </section>
      ) : null}
      {marked ? (
        <div className="cat-godkannrad">
          <button type="button" className="tm-knapp" onClick={() => onChange?.(accept(flow))}>
            {t("acceptAll")}
          </button>
          <span className="cat-hjalp">{t("acceptHint")}</span>
        </div>
      ) : null}
    </div>
  );
  return (
    <FormView
      ctx={ctx}
      fields={flow.fields}
      places={[]}
      withPlace={false}
      steps={<Steps t={t} step="review" />}
      eyebrow={reading ? t("reviewEyebrow") : t("photoStepOf", { n: 2 })}
      heading={reading ? t("reviewTitle") : t("handTitle")}
      intro={reading ? (flow.read === 1 ? t("reviewIntroOne") : t("reviewIntro", { n: flow.read })) : undefined}
      crumb={t("photoTitle")}
      before={before}
      marks={flow.marks}
      onAccept={(field) => onChange?.(accept(flow, field))}
      unreadable={unreadable}
      blocked={unreadable.length ? t("unreadableBlocks", { fields: unreadable.map((field) => t(LABELS[field])).join(", ") }) : null}
      busy={busy}
      error={error}
      backHref={PATHS.vehicles}
      onChange={(fields) => onChange?.(edit(flow, fields))}
      onSave={onSave}
    />
  );
}

/** The photos on their way to the vehicle: how many are sent, and what went wrong. */
export type Uploads = { done: number; of: number; problem: string | null };

export type PlaceStepProps = {
  ctx: Ctx;
  vehicle: Vehicle;
  places: Place[];
  place: string | null;
  uploads: Uploads | null;
  busy: boolean;
  error: string | null;
  onPlace?: (place: string | null) => void;
  onTag?: () => void;
  onDone?: () => void;
  /** The prototype the AI suggests from the catalog, with Koppla (#53, CAT-141). */
  suggestion?: ReactNode;
};

/** Plats och tagg, once the vehicle is saved: the place picker, and a tag now or later through
 * the card's waiting link (CAT-94). Klar without either skips the step. */
export function PlaceStepView({ ctx, vehicle, places, place, uploads, busy, error, onPlace, onTag, onDone, suggestion }: PlaceStepProps) {
  const { t } = ctx;
  const id = useId();
  const uploading = uploads !== null && uploads.done < uploads.of;
  const working = busy || uploading;
  return (
    <>
      <Crumb ctx={ctx} />
      <Steps t={t} step="place" />
      <p className="tm-overrubrik">{t("placeEyebrow", { name: title(t, vehicle) })}</p>
      <h1>{t("placeTitle")}</h1>
      <p className="cat-ingress">{t("placeIntro")}</p>
      <div className="cat-arbete cat-fotoarbete" aria-live="polite">
        {uploads && uploading ? (
          <>
            <progress max={uploads.of} value={uploads.done} aria-hidden="true" />
            <span>{t("picturesSaving", { done: uploads.done, of: uploads.of })}</span>
          </>
        ) : uploads && !uploads.problem ? (
          <span className="cat-ok">{t("picturesSaved")}</span>
        ) : null}
      </div>
      {uploads?.problem && !uploading ? <p className="cat-varning cat-fotoarbete">{t("picturesFailed", { problem: uploads.problem })}</p> : null}
      {suggestion}
      <form
        className="tm-kort cat-formular"
        onSubmit={(event) => {
          event.preventDefault();
          onDone?.();
        }}
      >
        <PlaceField ctx={ctx} places={places} value={place} onChange={onPlace} />
        {places.length === 0 ? <p className="cat-hjalp">{t("placesNone")}</p> : null}
        <section className="cat-taggruta" aria-labelledby={`${id}-tagg`}>
          <div>
            <h2 id={`${id}-tagg`}>{t("tagTitle")}</h2>
            <p className="cat-hjalp">{vehicle.status === "ready" ? t("tagNow") : t("draftNoTag")}</p>
          </div>
          {vehicle.status === "ready" ? (
            <button type="button" className="tm-knapp" disabled={working} onClick={onTag}>
              {t("tagNowButton")}
            </button>
          ) : null}
        </section>
        <ErrorLine text={error} />
        <div className="cat-formknappar">
          <button type="submit" className="tm-knapp primar" disabled={working}>
            {busy ? t("saving") : t("doneButton")}
          </button>
        </div>
      </form>
    </>
  );
}

/** Klart. */
export function DoneView({ ctx, vehicle, onAnother }: { ctx: Ctx; vehicle: Vehicle; onAnother?: () => void }) {
  const { t, navigate } = ctx;
  const card = vehiclePath(vehicle.id);
  return (
    <>
      <Crumb ctx={ctx} />
      <Steps t={t} step="done" />
      <h1>{t("doneTitle", { name: title(t, vehicle) })}</h1>
      <p className="cat-ingress">{t("doneIntro")}</p>
      <div className="cat-knappar">
        <a className="tm-knapp primar" href={card} onClick={linkClick(navigate, card)}>
          {t("openCard")}
        </a>
        <button type="button" className="tm-knapp" onClick={onAnother}>
          {t("addAnother")}
        </button>
        <a className="tm-knapp" href={PATHS.vehicles} onClick={linkClick(navigate, PATHS.vehicles)}>
          {t("toVehicles")}
        </a>
      </div>
    </>
  );
}

/** Someone the fleet is shared with adds by hand: the AI reading is the owner's (CAT-46). */
export function PhotoOwnerOnly({ ctx }: { ctx: Ctx }) {
  const { t, navigate } = ctx;
  return (
    <>
      <Crumb ctx={ctx} />
      <h1>{t("photoTitle")}</h1>
      <section className="tm-kort cat-tomt">
        <p className="cat-tomt-rubrik">{t("photoOwnerOnly")}</p>
        <a className="tm-knapp primar" href={PATHS.newVehicle} onClick={linkClick(navigate, PATHS.newVehicle)}>
          {t("addByHand")}
        </a>
      </section>
    </>
  );
}

/** The photos' addresses in the browser, made anew when the photos change and let go after. */
function usePreviews(photos: File[]): string[] {
  const [urls, setUrls] = useState<string[]>([]);
  useEffect(() => {
    const made = photos.map((photo) => URL.createObjectURL(photo));
    setUrls(made);
    return () => made.forEach((url) => URL.revokeObjectURL(url));
  }, [photos]);
  return urls;
}

export function PhotoFlowPage({ ctx }: { ctx: Ctx }) {
  return isOwner(ctx) ? <PhotoFlow ctx={ctx} /> : <PhotoOwnerOnly ctx={ctx} />;
}

function PhotoFlow({ ctx }: { ctx: Ctx }) {
  const { t } = ctx;
  const [flow, setFlow] = useState<Flow>(newFlow);
  const [consent, setConsent] = useState<ReadingConsent | null>(null);
  const [asking, setAsking] = useState(false);
  const [trouble, setTrouble] = useState<Trouble | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [places, setPlaces] = useState<Place[]>([]);
  const [saved, setSaved] = useState<Vehicle | null>(null);
  const [place, setPlace] = useState<string | null>(null);
  const [uploads, setUploads] = useState<Uploads | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const previews = usePreviews(flow.photos);

  useEffect(() => {
    api.readingConsent().then(setConsent, () => setConsent(null));
    api.places().then(setPlaces, () => setPlaces([]));
  }, []);

  const read = async (agreedNow: boolean) => {
    setTrouble(null);
    const agreed = flow.agreed || agreedNow;
    // The price is shown before anything is read (CAT-19): without it, it is fetched first.
    if (!consent) {
      const known = await api.readingConsent().catch(() => null);
      setConsent(known);
      if (!known) setTrouble(readingTrouble(t, null));
      return;
    }
    if (needsConsent(consent, agreed)) {
      setAsking(true);
      return;
    }
    // The id is kept while the same photos are retried, so nothing is read or drawn twice (CAT-144).
    const id = flow.readingId ?? crypto.randomUUID();
    setFlow((now) => ({ ...now, agreed, readingId: id, step: "reading" }));
    const outcome = await attemptReading(id, flow.photos, consent, agreed);
    if (outcome.kind === "consent") {
      setFlow((now) => ({ ...now, step: "photo" }));
      setAsking(true);
    } else if (outcome.kind === "read") {
      setConsent((before) => (before ? { ...before, given: true } : before));
      setFlow((now) => applyReading(now, outcome.reading));
    } else {
      setTrouble(readingTrouble(t, outcome.error));
      setFlow((now) => ({ ...now, step: "photo", readingId: outcome.keepId ? id : null }));
    }
  };

  const save = async () => {
    if (stillUnreadable(flow).length) return;
    setBusy(true);
    setError(null);
    let vehicle: Vehicle;
    try {
      vehicle = await saveVehicle(flow);
    } catch (failure) {
      setError(problemText(t, failure));
      setBusy(false);
      return;
    }
    setSaved(vehicle);
    setPlace(vehicle.place ?? null);
    setFlow((now) => ({ ...now, step: "place" }));
    setBusy(false);
    if (flow.photos.length) {
      setUploads({ done: 0, of: flow.photos.length, problem: null });
      const failed = await uploadPhotos(vehicle, flow.photos, (done) => setUploads((now) => now && { ...now, done }));
      if (failed) setUploads((now) => now && { ...now, problem: pictureProblem(t, failed) });
    }
  };

  const finish = async (tag: boolean) => {
    if (!saved) return;
    setBusy(true);
    setError(null);
    try {
      if (place !== (saved.place ?? null)) {
        const moved = (await api.move([saved.id], place)).vehicles.find((vehicle) => vehicle.id === saved.id);
        if (moved) setSaved(moved);
      }
      if (tag) {
        // The card waits for the next tag the owner taps, for 10 minutes (CAT-94).
        await api.waitForTag(saved.id, null);
        ctx.navigate?.(vehiclePath(saved.id));
        return;
      }
      setFlow((now) => ({ ...now, step: "done" }));
    } catch (failure) {
      setError(problemText(t, failure));
    } finally {
      setBusy(false);
    }
  };

  const restart = () => {
    setFlow(newFlow());
    setSaved(null);
    setPlace(null);
    setUploads(null);
    setTrouble(null);
    setProblem(null);
    setError(null);
  };

  let page;
  if (saved && flow.step === "done") page = <DoneView ctx={ctx} vehicle={saved} onAnother={restart} />;
  else if (saved)
    page = (
      <PlaceStepView
        ctx={ctx}
        vehicle={saved}
        places={places}
        place={place}
        uploads={uploads}
        busy={busy}
        error={error}
        onPlace={setPlace}
        onTag={() => void finish(true)}
        onDone={() => void finish(false)}
        suggestion={flow.reading?.prototype ? <SuggestedPrototype ctx={ctx} suggestion={flow.reading.prototype} vehicle={saved} onLinked={setSaved} /> : null}
      />
    );
  else if (flow.step === "reading") page = <ReadingView ctx={ctx} flow={flow} previews={previews} />;
  else if (flow.step === "review")
    page = (
      <ReviewView
        ctx={ctx}
        flow={flow}
        previews={previews}
        busy={busy}
        error={error}
        onChange={setFlow}
        onMorePhotos={() => setFlow((now) => ({ ...now, step: "photo" }))}
        onSave={() => void save()}
      />
    );
  else
    page = (
      <PhotoStepView
        ctx={ctx}
        flow={flow}
        previews={previews}
        consent={consent}
        trouble={trouble}
        problem={problem}
        onAdd={(files) => {
          const added = addPhotos(flow, files);
          setFlow(added.flow);
          setProblem(added.problem ? t(added.problem === "photos_full" ? "photosFull" : `problem_${added.problem}`) : null);
          setTrouble(null);
        }}
        onRemove={(index) => {
          setFlow(removePhoto(flow, index));
          setProblem(null);
        }}
        onRead={() => void read(false)}
        onSkip={() => setFlow(skipReading(flow))}
      />
    );

  return (
    <>
      {page}
      <Dialog open={asking} title={t("consentTitle")} onClose={() => setAsking(false)}>
        <ConsentView
          ctx={ctx}
          consent={consent}
          photos={flow.photos.length}
          onNo={() => setAsking(false)}
          onYes={() => {
            setAsking(false);
            void read(true);
          }}
        />
      </Dialog>
    </>
  );
}

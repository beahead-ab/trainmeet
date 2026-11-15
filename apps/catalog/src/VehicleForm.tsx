// Lägg till fordon för hand, och Ändra: the core fields (CAT-53, CAT-62, CAT-66, CAT-134).
import { linkClick } from "@trainmeet/design";
import { useEffect, useId, useState, type ReactNode } from "react";
import { api, ApiError, ENGINES, fieldsOf, KINDS, statusFor, type Place, type Vehicle, type VehicleFields } from "./api";
import { Crumbs, Dialog, ErrorLine, isOwner, kindText, problemText, title, type Ctx } from "./common";
import { PATHS, vehiclePath } from "./routes";
import { afterLinking } from "./TagPage";

export const EMPTY: VehicleFields = {
  status: "draft",
  kind: null,
  litt: "",
  number: "",
  operator: "",
  epoch: "",
  scale: "",
  maker: "",
  article_number: "",
  note: "",
  dcc_address: "",
  functions: [],
  place: null,
};
const EPOCHS = ["I", "II", "III", "IV", "V", "VI"];
const SCALES = ["H0", "N", "TT", "0", "Z", "1", "G"];

function Field({ label, help, children }: { label: string; help?: string; children: (id: string, helpId?: string) => ReactNode }) {
  const id = useId();
  const helpId = help ? `${id}-hjalp` : undefined;
  return (
    <div className="cat-falt">
      <label htmlFor={id}>{label}</label>
      {children(id, helpId)}
      {help ? (
        <p className="cat-hjalp" id={helpId}>
          {help}
        </p>
      ) : null}
    </div>
  );
}

export type FormViewProps = {
  /** Someone else's fleet: where a new vehicle goes (CAT-50). */
  addTo?: ReactNode;
  ctx: Ctx;
  fields: VehicleFields;
  places: Place[];
  heading: string;
  crumb: string;
  busy: boolean;
  error: string | null;
  backHref: string;
  changedHref?: string | null;
  onChange?: (fields: VehicleFields) => void;
  onSave?: () => void;
};

export function FormView(props: FormViewProps) {
  const { ctx, fields, places, busy } = props;
  const { t, navigate } = ctx;
  const set = (change: Partial<VehicleFields>) => props.onChange?.({ ...fields, ...change });
  const engine = fields.kind ? ENGINES.includes(fields.kind) : false;
  const functions = fields.functions ?? [];
  const nextNumber = functions.length ? Math.min(68, Math.max(...functions.map((f) => f.number)) + 1) : 0;
  return (
    <>
      <Crumbs ctx={ctx} items={[{ href: PATHS.vehicles, label: t("vehicles") }, { label: props.crumb }]} />
      <h1>{props.heading}</h1>
      <p className="cat-ingress">{t("newIntro")}</p>
      <form
        className="tm-kort cat-formular"
        onSubmit={(event) => {
          event.preventDefault();
          props.onSave?.();
        }}
      >
        <Field label={t("fKind")}>
          {(id) => (
            <select id={id} value={fields.kind ?? ""} onChange={(e) => set({ kind: (e.target.value || null) as VehicleFields["kind"] })}>
              <option value="">{t("chooseKind")}</option>
              {KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {kindText(t, kind)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <div className="cat-par">
          <Field label={t("fLitt")}>{(id) => <input id={id} value={fields.litt ?? ""} maxLength={80} onChange={(e) => set({ litt: e.target.value })} />}</Field>
          <Field label={t("fNumber")} help={t("fNumberHelp")}>
            {(id, helpId) => (
              <input
                id={id}
                className="tm-mono"
                value={fields.number ?? ""}
                maxLength={80}
                aria-describedby={helpId}
                spellCheck={false}
                onChange={(e) => set({ number: e.target.value })}
              />
            )}
          </Field>
        </div>
        <Field label={t("fOperator")}>{(id) => <input id={id} value={fields.operator ?? ""} maxLength={80} onChange={(e) => set({ operator: e.target.value })} />}</Field>
        <div className="cat-par">
          <Field label={t("fEpoch")}>
            {(id) => (
              <>
                <input id={id} list={`${id}-val`} value={fields.epoch ?? ""} maxLength={12} onChange={(e) => set({ epoch: e.target.value })} />
                <datalist id={`${id}-val`}>
                  {EPOCHS.map((epoch) => (
                    <option key={epoch} value={epoch} />
                  ))}
                </datalist>
              </>
            )}
          </Field>
          <Field label={t("fScale")}>
            {(id) => (
              <>
                <input id={id} list={`${id}-val`} value={fields.scale ?? ""} maxLength={12} onChange={(e) => set({ scale: e.target.value })} />
                <datalist id={`${id}-val`}>
                  {SCALES.map((scale) => (
                    <option key={scale} value={scale} />
                  ))}
                </datalist>
              </>
            )}
          </Field>
        </div>
        <div className="cat-par">
          <Field label={t("fMaker")}>{(id) => <input id={id} value={fields.maker ?? ""} maxLength={80} onChange={(e) => set({ maker: e.target.value })} />}</Field>
          <Field label={t("fArticle")}>
            {(id) => <input id={id} className="tm-mono" value={fields.article_number ?? ""} maxLength={80} onChange={(e) => set({ article_number: e.target.value })} />}
          </Field>
        </div>
        {props.addTo}
        {isOwner(ctx) ? (
        <Field label={t("fPlace")}>
          {(id) => (
            <select id={id} value={fields.place ?? ""} onChange={(e) => set({ place: e.target.value || null })}>
              <option value="">{t("noPlace")}</option>
              {places.map((place) => (
                <option key={place.id} value={place.id}>
                  {place.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        ) : null}
        <Field label={t("fNote")} help={t("fNoteHelp")}>
          {(id, helpId) => <textarea id={id} rows={3} maxLength={2000} aria-describedby={helpId} value={fields.note ?? ""} onChange={(e) => set({ note: e.target.value })} />}
        </Field>
        {engine ? (
          <fieldset className="cat-dcc">
            <legend>{t("fDcc")}</legend>
            <Field label={t("fDcc")}>
              {(id) => (
                <input id={id} className="tm-mono" inputMode="numeric" maxLength={8} value={fields.dcc_address ?? ""} onChange={(e) => set({ dcc_address: e.target.value })} />
              )}
            </Field>
            <p className="cat-etikett">{t("fFunctions")}</p>
            <ul className="cat-funktioner">
              {functions.map((fn, index) => (
                <li key={index}>
                  <span className="tm-mono">F</span>
                  <input
                    className="tm-mono cat-fnr"
                    type="number"
                    min={0}
                    max={68}
                    aria-label={t("fnNumber")}
                    value={fn.number}
                    onChange={(e) => set({ functions: functions.map((f, i) => (i === index ? { ...f, number: Number(e.target.value) } : f)) })}
                  />
                  <input
                    aria-label={t("fnName", { n: fn.number })}
                    value={fn.name}
                    maxLength={80}
                    onChange={(e) => set({ functions: functions.map((f, i) => (i === index ? { ...f, name: e.target.value } : f)) })}
                  />
                  <button type="button" className="tm-knapp" onClick={() => set({ functions: functions.filter((_, i) => i !== index) })}>
                    {t("removeFunction", { n: fn.number })}
                  </button>
                </li>
              ))}
            </ul>
            <button type="button" className="tm-knapp" onClick={() => set({ functions: [...functions, { number: nextNumber, name: "" }] })}>
              {t("addFunction")}
            </button>
          </fieldset>
        ) : null}
        {statusFor(fields) === "draft" ? <p className="cat-hjalp">{t("draftHint")}</p> : null}
        <ErrorLine text={props.error} />
        {props.changedHref ? (
          <p>
            <a href={props.changedHref}>{t("openAgain")}</a>
          </p>
        ) : null}
        <div className="cat-formknappar">
          <a className="tm-knapp" href={props.backHref} onClick={linkClick(navigate, props.backHref)}>
            {t("cancel")}
          </a>
          <button type="submit" className="tm-knapp primar" disabled={busy}>
            {busy ? t("saving") : t("save")}
          </button>
        </div>
      </form>
    </>
  );
}

/** What is sent: the status follows the fields, and a non-engine carries no DCC (CAT-62). */
export function outgoing(fields: VehicleFields): VehicleFields {
  const engine = fields.kind ? ENGINES.includes(fields.kind) : false;
  const clean = {
    ...fields,
    dcc_address: engine ? fields.dcc_address : "",
    functions: engine ? (fields.functions ?? []).filter((f) => f.name.trim()) : [],
  };
  return { ...clean, status: statusFor(clean) };
}

export function VehicleFormPage({ ctx, id }: { ctx: Ctx; id?: string }) {
  const { t } = ctx;
  const [fields, setFields] = useState<VehicleFields>(EMPTY);
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [places, setPlaces] = useState<Place[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [changed, setChanged] = useState(false);
  // Lägg till nytt fordon med taggen (CAT-105): the tag is offered to the new vehicle.
  const [tag] = useState(() => (id ? null : new URLSearchParams(window.location.search).get("tagg")));
  const [offer, setOffer] = useState<Vehicle | null>(null);
  const [own, setOwn] = useState(false);

  useEffect(() => {
    if (isOwner(ctx)) api.places().then(setPlaces, () => setPlaces([]));
    if (id) {
      api.vehicle(id).then(
        (found) => {
          setVehicle(found);
          setFields(fieldsOf(found));
        },
        (failure) => setError(problemText(t, failure)),
      );
    }
  }, [id, t, ctx]);

  const name = vehicle ? title(t, vehicle) : t("newTitle");
  const addTo =
    !id && !isOwner(ctx) ? (
      <fieldset className="cat-val">
        <legend>{t("addTo")}</legend>
        <label>
          <input type="radio" name="fleet" checked={!own} onChange={() => setOwn(false)} /> {ctx.fleetTitle}
        </label>
        <label>
          <input type="radio" name="fleet" checked={own} onChange={() => setOwn(true)} /> {t("ownFleet")}
        </label>
      </fieldset>
    ) : null;
  const done = (saved: Vehicle) => {
    if (own) ctx.workIn?.(null); // it went into the person's own fleet
    ctx.navigate?.(vehiclePath(saved.id));
  };
  return (
    <>
    <FormView
      ctx={ctx}
      fields={fields}
      places={places}
      addTo={addTo}
      heading={id ? t("editTitle", { name }) : t("newTitle")}
      crumb={id ? name : t("newTitle")}
      busy={busy || (id !== undefined && vehicle === null)}
      error={error}
      backHref={id ? vehiclePath(id) : PATHS.vehicles}
      changedHref={changed && id ? vehiclePath(id) : null}
      onChange={setFields}
      onSave={async () => {
        setBusy(true);
        setError(null);
        try {
          const saved = id && vehicle ? await api.changeVehicle(id, { ...outgoing(fields), version: vehicle.version }) : await api.addVehicle(outgoing(fields), own);
          if (tag && saved.status === "ready") setOffer(saved);
          else done(saved);
        } catch (failure) {
          setError(problemText(t, failure));
          setChanged(failure instanceof ApiError && failure.code === "changed");
        } finally {
          setBusy(false);
        }
      }}
    />
    <Dialog open={offer !== null} title={t("linkTag")} onClose={() => offer && done(offer)}>
      <p>{offer ? t("tagOffer", { name: title(t, offer) }) : ""}</p>
      <div className="cat-dialogknappar">
        <button type="button" className="tm-knapp" onClick={() => offer && done(offer)}>
          {t("cancel")}
        </button>
        <button
          type="button"
          className="tm-knapp primar"
          onClick={async () => {
            if (!offer || !tag) return;
            try {
              await api.link(tag, { vehicle: offer.id, confirm: true, replace: null, move_from: null });
              ctx.navigate?.(afterLinking(offer.id, tag));
              return;
            } catch (failure) {
              setError(problemText(t, failure));
            }
            done(offer);
          }}
        >
          {t("linkYes")}
        </button>
      </div>
    </Dialog>
    </>
  );
}

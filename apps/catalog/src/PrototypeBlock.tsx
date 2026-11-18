// The prototype on the vehicle card (#53, CAT-160–CAT-162): the type data as a block of their
// own, apart from the core fields, each inherited from the prototype or the owner's own value.
// Koppla förebild, Ny version finns · Uppdatera, and Koppla bort; and the AI's suggested
// prototype after a reading (CAT-141), which is linked only when the owner says so (CAT-136).
import { linkClick } from "@trainmeet/design";
import { useEffect, useId, useState } from "react";
import { api, type FieldRegister, type Prototype, type PrototypeSummary, type TypeData, type Vehicle } from "./api";
import { Dialog, ErrorLine, mayEdit, problemText, type Ctx } from "./common";
import { profileFields, profileName, TypeDataInputs, TypeDataTable, typeSummary, useRegister } from "./PrototypesPage";
import { prototypePath } from "./routes";

export type PrototypeBlockProps = {
  ctx: Ctx;
  vehicle: Vehicle;
  register: FieldRegister | null;
  /** The type data being changed, or null when they are only shown. */
  editing: TypeData | null;
  busy: boolean;
  error: string | null;
  onChoose?: () => void;
  onUpdate?: () => void;
  onUnlink?: () => void;
  onEdit?: (values: TypeData | null) => void;
  onSave?: () => void;
};

/** Förebilden on the card: what is shown, from the state. Rendered in the tests without fetching. */
export function PrototypeBlockView({ ctx, vehicle, register, editing, busy, error, onChoose, onUpdate, onUnlink, onEdit, onSave }: PrototypeBlockProps) {
  const { t, navigate, language } = ctx;
  const id = useId();
  const linked = vehicle.prototype ?? null;
  const edit = mayEdit(ctx);
  return (
    <section className="tm-kort cat-forebild" aria-labelledby={`${id}-rubrik`}>
      <div className="cat-kortrubrik">
        <h2 id={`${id}-rubrik`}>{linked ? t("protoOnCard", { name: linked.name }) : t("protoOnCardNone")}</h2>
        {linked ? (
          <a className="cat-under" href={prototypePath(linked.id)} onClick={linkClick(navigate, prototypePath(linked.id))}>
            {t("protoVersion", { n: linked.revision })} · {profileName(register, linked.profile, language)}
          </a>
        ) : null}
      </div>
      {!linked ? (
        <>
          <p className="cat-hjalp">{t("protoNoneIntro")}</p>
          <ErrorLine text={error} />
          {edit ? (
            <div className="cat-knappar">
              <button type="button" className="tm-knapp" disabled={busy} onClick={onChoose}>
                {t("protoLink")}
              </button>
            </div>
          ) : null}
        </>
      ) : editing ? (
        <form
          className="cat-formular"
          onSubmit={(event) => {
            event.preventDefault();
            onSave?.();
          }}
        >
          <p className="cat-hjalp">{t("protoOwnHelp")}</p>
          {register ? <TypeDataInputs id={id} fields={profileFields(register, linked.profile, language)} values={editing} onChange={(values) => onEdit?.(values)} /> : null}
          <ErrorLine text={error} />
          <div className="cat-formknappar">
            <button type="button" className="tm-knapp" onClick={() => onEdit?.(null)}>
              {t("cancel")}
            </button>
            <button type="submit" className="tm-knapp primar" disabled={busy}>
              {busy ? t("saving") : t("save")}
            </button>
          </div>
        </form>
      ) : (
        <>
          {linked.newer ? (
            <div className="cat-vantar cat-nyversion" role="status">
              <p>{t("protoNewer", { n: linked.latest })}</p>
              {edit ? (
                <button type="button" className="tm-knapp primar" disabled={busy} onClick={onUpdate}>
                  {t("protoUpdate")}
                </button>
              ) : null}
            </div>
          ) : null}
          <TypeDataTable ctx={ctx} fields={linked.fields} register={register} profile={linked.profile} own={linked.overrides} snapshot={linked.snapshot} />
          <ErrorLine text={error} />
          {edit ? (
            <div className="cat-knappar">
              <button type="button" className="tm-knapp" disabled={busy} onClick={() => onEdit?.({ ...linked.fields, ...linked.overrides })}>
                {t("protoEditOwn")}
              </button>
              <button type="button" className="tm-knapp" disabled={busy} onClick={onUnlink}>
                {t("protoUnlink")}
              </button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

/** Koppla förebild: the reviewed prototypes, searched as in the catalog (CAT-173). */
export function ChooseView({ ctx, q, found, busy, onQ, onChoose }: { ctx: Ctx; q: string; found: Prototype[] | null; busy: boolean; onQ?: (q: string) => void; onChoose?: (prototype: Prototype) => void }) {
  const { t } = ctx;
  const id = useId();
  const reviewed = (found ?? []).filter((prototype) => prototype.status === "reviewed" && prototype.revision);
  return (
    <>
      <label className="cat-dold" htmlFor={`${id}-sok`}>
        {t("protoSearch")}
      </label>
      <input id={`${id}-sok`} className="cat-sok" type="search" value={q} placeholder={t("protoSearch")} onChange={(event) => onQ?.(event.target.value)} />
      {found === null ? (
        <p className="cat-laddar">{t("loading")}</p>
      ) : reviewed.length === 0 ? (
        <p className="cat-hjalp">{t("protoNoMatch")}</p>
      ) : (
        <ul className="cat-platsval cat-forebildsval">
          {reviewed.map((prototype) => (
            <li key={prototype.id}>
              <button type="button" className="tm-knapp" disabled={busy} onClick={() => onChoose?.(prototype)}>
                <b>{prototype.name}</b>
                <span className="cat-under">{[prototype.fields.operator, prototype.fields.description, typeSummary(t, prototype.fields)].filter(Boolean).join(" · ")}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

/** The block on the card, with its dialogs. onChanged gets the vehicle after each change. */
export function PrototypeSection({ ctx, vehicle, onChanged }: { ctx: Ctx; vehicle: Vehicle; onChanged: (vehicle: Vehicle) => void }) {
  const { t } = ctx;
  const register = useRegister();
  const [editing, setEditing] = useState<TypeData | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [unlinking, setUnlinking] = useState(false);
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Prototype[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!choosing) return;
    let current = true;
    const timer = window.setTimeout(() => {
      api.prototypes(q).then(
        (list) => current && setFound(list.prototypes),
        () => current && setFound([]),
      );
    }, 200);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [choosing, q]);

  const act = async (work: () => Promise<Vehicle>) => {
    setBusy(true);
    setError(null);
    try {
      onChanged(await work());
      setEditing(null);
    } catch (failure) {
      setError(problemText(t, failure));
    }
    setBusy(false);
  };
  const linked = vehicle.prototype ?? null;
  return (
    <>
      <PrototypeBlockView
        ctx={ctx}
        vehicle={vehicle}
        register={register}
        editing={editing}
        busy={busy}
        error={error}
        onChoose={() => {
          setFound(null);
          setChoosing(true);
        }}
        onUpdate={() => linked && void act(() => api.linkPrototype(vehicle.id, { version: vehicle.version, prototype: linked.id, revision: linked.latest }))}
        onUnlink={() => setUnlinking(true)}
        onEdit={setEditing}
        onSave={() => editing && void act(() => api.changeTypeData(vehicle.id, vehicle.version, editing))}
      />
      <Dialog open={choosing} title={t("protoLink")} onClose={() => setChoosing(false)}>
        <ChooseView
          ctx={ctx}
          q={q}
          found={found}
          busy={busy}
          onQ={setQ}
          onChoose={(prototype) => {
            setChoosing(false);
            void act(() => api.linkPrototype(vehicle.id, { version: vehicle.version, prototype: prototype.id, revision: prototype.revision ?? 1 }));
          }}
        />
        <div className="cat-dialogknappar">
          <button type="button" className="tm-knapp" onClick={() => setChoosing(false)}>
            {t("cancel")}
          </button>
        </div>
      </Dialog>
      <Dialog open={unlinking} title={t("protoUnlink")} onClose={() => setUnlinking(false)}>
        <p>{linked ? t("protoUnlinkConfirm", { name: linked.name }) : ""}</p>
        <div className="cat-dialogknappar">
          <button type="button" className="tm-knapp" onClick={() => setUnlinking(false)}>
            {t("cancel")}
          </button>
          <button
            type="button"
            className="tm-knapp primar"
            onClick={() => {
              setUnlinking(false);
              void act(() => api.unlinkPrototype(vehicle.id, vehicle.version));
            }}
          >
            {t("protoUnlink")}
          </button>
        </div>
      </Dialog>
    </>
  );
}

// --- The AI's suggestion (CAT-141) -------------------------------------------------------------

export function SuggestedPrototypeView({ ctx, suggestion, linked, busy, error, onLink }: { ctx: Ctx; suggestion: PrototypeSummary; linked: boolean; busy: boolean; error: string | null; onLink?: () => void }) {
  const { t } = ctx;
  return (
    <section className="tm-kort cat-avsnitt cat-forslag-forebild" aria-label={t("protoSuggested")} aria-live="polite">
      <h2>{t("protoSuggested")}</h2>
      <p>{t("protoSuggestedText", { name: suggestion.name, n: suggestion.revision })}</p>
      {linked ? (
        <p className="cat-ok">{t("protoLinked", { name: suggestion.name })}</p>
      ) : (
        <button type="button" className="tm-knapp" disabled={busy} onClick={onLink}>
          {t("protoLinkShort")}
        </button>
      )}
      <ErrorLine text={error} />
    </section>
  );
}

/** The suggestion on a saved vehicle: Koppla links that revision, and nothing else changes. */
export function SuggestedPrototype({ ctx, suggestion, vehicle, onLinked }: { ctx: Ctx; suggestion: PrototypeSummary; vehicle: Vehicle; onLinked?: (vehicle: Vehicle) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const linked = vehicle.prototype?.id === suggestion.id;
  return (
    <SuggestedPrototypeView
      ctx={ctx}
      suggestion={suggestion}
      linked={linked}
      busy={busy}
      error={error}
      onLink={async () => {
        setBusy(true);
        setError(null);
        try {
          onLinked?.(await api.linkPrototype(vehicle.id, { version: vehicle.version, prototype: suggestion.id, revision: suggestion.revision }));
        } catch (failure) {
          setError(problemText(ctx.t, failure));
        }
        setBusy(false);
      }}
    />
  );
}

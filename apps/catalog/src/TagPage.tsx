// /t/<uid>: what a tap opens (CAT-98–CAT-106). Mine opens the card, someone else's shows the
// mini card, an unknown tag offers to add or link a vehicle, and the vehicle waiting for a tag
// is offered first (CAT-94).
import { linkClick } from "@trainmeet/design";
import { useEffect, useState } from "react";
import { api, ApiError, type Account, type Lookup, type PendingState, type Vehicle, type VehicleTag } from "./api";
import { Dialog, ErrorLine, kindText, problemText, title, type Ctx, type T } from "./common";
import { PATHS, vehiclePath } from "./routes";
import { VehicleCardPage } from "./VehicleCard";

type Mini = Extract<Lookup, { outcome: "shared" | "private" }>;

/** Someone else's vehicle: exactly litt and number, kind, operator and scale (CAT-100). */
export function MiniCardView({ t, found }: { t: T; found: Mini }) {
  const card = found.card;
  return (
    <>
      <p className="tm-overrubrik">{t("someoneElses")}</p>
      <h1>{`${card.litt} ${card.number}`.trim() || t("draftTitle")}</h1>
      <section className="tm-kort cat-minikort">
        <p className="cat-ingress">{[kindText(t, card.kind), card.operator, card.scale].filter(Boolean).join(" · ")}</p>
        {found.outcome === "shared" ? <p>{t("ownerIs", { name: found.owner_name })}</p> : null}
      </section>
    </>
  );
}

/** The slot a tag takes on a vehicle: NFC and simulated tags share one, a QR label has its own. */
export const slotOf = (uid: string) => (/^q[a-z0-9]{11}$/.test(uid) ? "qr" : "nfc");
const tagIn = (vehicle: Vehicle, uid: string): VehicleTag | undefined =>
  (vehicle.tags ?? []).find((tag) => (tag.kind === "qr" ? "qr" : "nfc") === slotOf(uid));

type Ask = { vehicle: Vehicle; replace: VehicleTag | null } | null;

export function UnknownView({
  ctx,
  uid,
  account,
  pending,
  choosing,
  vehicles,
  ask,
  error,
  onChoose,
  onPick,
  onConfirm,
  onCancel,
  onPending,
}: {
  ctx: Ctx;
  uid: string;
  account: Account | null;
  pending: PendingState["pending"];
  choosing: boolean;
  vehicles: Vehicle[];
  ask: Ask;
  error: string | null;
  onChoose?: () => void;
  onPick?: (vehicle: Vehicle) => void;
  onConfirm?: () => void;
  onCancel?: () => void;
  onPending?: () => void;
}) {
  const { t, navigate } = ctx;
  if (!account) {
    const login = `${PATHS.login}?next=${encodeURIComponent(`/t/${uid}`)}`;
    return (
      <>
        <h1>{t("tagTitle")}</h1>
        <section className="tm-kort cat-tomt">
          <p className="cat-tomt-rubrik">{t("tagUnknown")}</p>
          <p>{t("tagUnknownLogin")}</p>
          <a className="tm-knapp primar" href={login} onClick={linkClick(navigate, login)}>
            {t("logIn")}
          </a>
        </section>
      </>
    );
  }
  const newVehicle = `${PATHS.newVehicle}?tagg=${encodeURIComponent(uid)}`;
  return (
    <>
      <h1>{t("tagTitle")}</h1>
      <p className="cat-ingress tm-mono">{uid}</p>
      <ErrorLine text={error} />
      <section className="tm-kort cat-tomt">
        <p className="cat-tomt-rubrik">{t("tagUnknown")}</p>
        {pending ? (
          <div className="cat-knappar">
            <button type="button" className="tm-knapp primar" onClick={onPending}>
              {t("linkTo", { name: pending.title })}
            </button>
          </div>
        ) : null}
        <div className="cat-knappar">
          <a className={pending ? "tm-knapp" : "tm-knapp primar"} href={newVehicle} onClick={linkClick(navigate, newVehicle)}>
            {t("tagNewVehicle")}
          </a>
          <button type="button" className="tm-knapp" aria-expanded={choosing} onClick={onChoose}>
            {t("tagExisting")}
          </button>
        </div>
        {choosing ? (
          vehicles.length === 0 ? (
            <p>{t("noReadyVehicles")}</p>
          ) : (
            <ul className="cat-platsval" aria-label={t("chooseVehicle")}>
              {vehicles.map((vehicle) => (
                <li key={vehicle.id}>
                  <button type="button" className="tm-knapp" onClick={() => onPick?.(vehicle)}>
                    {title(t, vehicle)}
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : null}
      </section>
      <Dialog open={ask !== null} title={t("linkTag")} onClose={() => onCancel?.()}>
        <p>
          {ask?.replace
            ? t("tagReplaceQ", { name: title(t, ask.vehicle), tag: ask.replace.name })
            : t("tagOffer", { name: ask ? title(t, ask.vehicle) : "" })}
        </p>
        <div className="cat-dialogknappar">
          <button type="button" className="tm-knapp" onClick={onCancel}>
            {t("cancel")}
          </button>
          <button type="button" className="tm-knapp primar" onClick={onConfirm}>
            {ask?.replace ? t("replaceYes") : t("linkYes")}
          </button>
        </div>
      </Dialog>
    </>
  );
}

export function TagPage({ ctx, uid, account }: { ctx: Ctx; uid: string; account: Account | null }) {
  const { t } = ctx;
  const [found, setFound] = useState<Lookup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingState["pending"]>(null);
  const [choosing, setChoosing] = useState(false);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [ask, setAsk] = useState<Ask>(null);

  useEffect(() => {
    api.lookup(uid).then(setFound, (failure) => setError(problemText(t, failure)));
    if (account) api.pending().then((state) => setPending(state.pending), () => setPending(null));
  }, [uid, account, t]);

  useEffect(() => {
    // Mine: the card opens directly (CAT-99), at its own address, in place of the tag's.
    if (found?.outcome === "mine" || found?.outcome === "fleet") ctx.replace?.(vehiclePath(found.vehicle_id));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per answer
  }, [found]);

  const doLink = async (vehicle: Vehicle, replace: VehicleTag | null) => {
    try {
      await api.link(uid, { vehicle: vehicle.id, confirm: true, replace: replace?.assignment ?? null, move_from: null });
      ctx.navigate?.(vehiclePath(vehicle.id));
    } catch (failure) {
      setAsk(null);
      setError(problemText(t, failure));
    }
  };

  if (error && !found) return <ErrorLine text={error} />;
  if (!found) return <p className="cat-laddar">{t("loading")}</p>;
  if (found.outcome === "mine" || found.outcome === "fleet") return <VehicleCardPage ctx={ctx} id={found.vehicle_id} />;
  if (found.outcome === "shared" || found.outcome === "private") return <MiniCardView t={t} found={found} />;
  return (
    <UnknownView
      ctx={ctx}
      uid={found.tag_uid ?? uid}
      account={account}
      pending={pending}
      choosing={choosing}
      vehicles={vehicles}
      ask={ask}
      error={error}
      onChoose={() => {
        setChoosing((open) => !open);
        api.vehicles().then((list) => setVehicles(list.vehicles.filter((v) => v.status === "ready")), () => setVehicles([]));
      }}
      onPick={(vehicle) => setAsk({ vehicle, replace: tagIn(vehicle, found.tag_uid ?? uid) ?? null })}
      onCancel={() => setAsk(null)}
      onConfirm={() => ask && doLink(ask.vehicle, ask.replace)}
      onPending={async () => {
        if (!pending) return;
        try {
          const vehicle = await api.vehicle(pending.vehicle_id);
          const current = tagIn(vehicle, found.tag_uid ?? uid);
          // Ersätt tagg on the card carried the link seen there (CAT-89).
          setAsk({ vehicle, replace: current && current.assignment === pending.replace ? current : null });
        } catch (failure) {
          setError(problemText(t, failure));
          if (failure instanceof ApiError && failure.code === "not_found") setPending(null);
        }
      }}
    />
  );
}

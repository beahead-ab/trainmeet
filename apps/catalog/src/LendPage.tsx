// Låna ut: to a name, with an optional date back (CAT-74, CAT-75). The people in the club come
// with TrainMeet ID (#67).
import { linkClick } from "@trainmeet/design";
import { useEffect, useId, useState } from "react";
import { api, type Vehicle } from "./api";
import { ErrorLine, problemText, title, type Ctx } from "./common";
import { vehiclePath } from "./routes";

export function LendView({
  ctx,
  vehicle,
  name,
  until,
  busy,
  error,
  onName,
  onUntil,
  onLend,
}: {
  ctx: Ctx;
  vehicle: Vehicle;
  name: string;
  until: string;
  busy: boolean;
  error: string | null;
  onName?: (name: string) => void;
  onUntil?: (until: string) => void;
  onLend?: () => void;
}) {
  const { t, navigate } = ctx;
  const nameId = useId();
  const untilId = useId();
  const canLend = vehicle.state === "home" && vehicle.status === "ready";
  return (
    <>
      <p className="tm-overrubrik">{title(t, vehicle)}</p>
      <h1>{t("lendTitle")}</h1>
      <form
        className="tm-kort cat-formular cat-smal"
        onSubmit={(event) => {
          event.preventDefault();
          onLend?.();
        }}
      >
        {canLend ? null : <p className="cat-varning">{t("lendNotReady")}</p>}
        <p className="cat-hjalp">{t("clubLater")}</p>
        <div className="cat-falt">
          <label htmlFor={nameId}>{t("lendWho")}</label>
          <input id={nameId} value={name} maxLength={80} autoComplete="off" onChange={(e) => onName?.(e.target.value)} />
        </div>
        <div className="cat-falt">
          <label htmlFor={untilId}>{t("lendUntilLabel")}</label>
          <input id={untilId} type="date" value={until} onChange={(e) => onUntil?.(e.target.value)} />
        </div>
        <p className="cat-hjalp">{t("lendNote")}</p>
        <ErrorLine text={error} />
        <div className="cat-formknappar">
          <a className="tm-knapp" href={vehiclePath(vehicle.id)} onClick={linkClick(navigate, vehiclePath(vehicle.id))}>
            {t("cancel")}
          </a>
          <button type="submit" className="tm-knapp primar" disabled={busy || !canLend || !name.trim()}>
            {name.trim() ? t("lendTo", { name: name.trim() }) : t("lend")}
          </button>
        </div>
      </form>
    </>
  );
}

export function LendPage({ ctx, id }: { ctx: Ctx; id: string }) {
  const { t } = ctx;
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [name, setName] = useState("");
  const [until, setUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.vehicle(id).then(setVehicle, (failure) => setError(problemText(t, failure)));
  }, [id, t]);
  if (!vehicle) return error ? <ErrorLine text={error} /> : <p className="cat-laddar">{t("loading")}</p>;
  return (
    <LendView
      ctx={ctx}
      vehicle={vehicle}
      name={name}
      until={until}
      busy={busy}
      error={error}
      onName={setName}
      onUntil={setUntil}
      onLend={async () => {
        setBusy(true);
        try {
          await api.lend(vehicle.id, { version: vehicle.version, to: name.trim(), until: until || null });
          ctx.navigate?.(vehiclePath(vehicle.id));
        } catch (failure) {
          setError(problemText(t, failure));
        } finally {
          setBusy(false);
        }
      }}
    />
  );
}

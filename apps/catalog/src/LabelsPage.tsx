// Skriv ut QR-etiketter (#56, CAT-184): the owner chooses the vehicles and the size, and prints an
// A4 sheet of QR labels with the litt and the number under each code. The sheet is the page's own
// print view (catalog.css, @media print). The logic is in labels.ts.
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { api, qrAddress, type Vehicle } from "./api";
import { Crumbs, Dialog, ErrorLine, isOwner, problemText, title, type Ctx, type T } from "./common";
import { chosenFromAddress, LABEL_SIZES, labelPlan, labelText, makeLabels, perSheet, printWhenReady, qrLabel, withChanged, type LabelSize } from "./labels";
import { PATHS } from "./routes";

/** The sheet as it is printed: the labels in the list's order. A vehicle that gets its label
 * when the sheet is printed shows where it will be. */
export function LabelSheet({ t, vehicles, size }: { t: T; vehicles: Vehicle[]; size: LabelSize }) {
  return (
    <section className={`cat-ark cat-ark-${size}`} aria-label={t("labelsSheet")}>
      {vehicles.length === 0 ? <p className="cat-under cat-ark-tomt">{t("labelsSheetEmpty")}</p> : null}
      {vehicles.map((vehicle) => {
        const tag = qrLabel(vehicle);
        return (
          <figure key={vehicle.id} className="cat-qretikett">
            {tag ? (
              <img src={qrAddress(tag.uid)} alt={t("qrAlt", { address: tag.address })} />
            ) : (
              <span className="cat-qretikett-ny" role="img" aria-label={t("labelsNew")}>
                {t("labelsNew")}
              </span>
            )}
            <figcaption>{labelText(vehicle) || title(t, vehicle)}</figcaption>
          </figure>
        );
      })}
    </section>
  );
}

export type LabelsViewProps = {
  ctx: Ctx;
  vehicles: Vehicle[] | null;
  chosen: Set<string>;
  size: LabelSize;
  renew: boolean;
  busy?: boolean;
  error?: string | null;
  onChoose?: (id: string, on: boolean) => void;
  onChooseAll?: (on: boolean) => void;
  onSize?: (size: LabelSize) => void;
  onRenew?: (renew: boolean) => void;
  onPrint?: () => void;
};

/** The page as it looks, from its state. Rendered in the tests without fetching. */
export function LabelsView(props: LabelsViewProps) {
  const { ctx, vehicles, chosen, size, renew } = props;
  const { t } = ctx;
  const id = useId();
  const plan = labelPlan(vehicles ?? [], chosen, renew);
  const count = plan.print.length;
  return (
    <>
      <Crumbs ctx={ctx} items={[{ href: PATHS.vehicles, label: t("vehicles") }, { label: t("labelsTitle") }]} />
      <h1>{t("labelsTitle")}</h1>
      <p className="cat-ingress">{t("labelsIntro")}</p>
      <ErrorLine text={props.error ?? null} />
      <div className="cat-kortet cat-utskriftsval">
        <section className="tm-kort cat-avsnitt" aria-labelledby={`${id}-fordon`}>
          <div className="cat-kortrubrik">
            <h2 id={`${id}-fordon`}>{t("labelsVehicles")}</h2>
            <div className="cat-knappar">
              <button type="button" className="tm-knapp" onClick={() => props.onChooseAll?.(true)}>
                {t("labelsAll")}
              </button>
              <button type="button" className="tm-knapp" onClick={() => props.onChooseAll?.(false)}>
                {t("labelsNone")}
              </button>
            </div>
          </div>
          {vehicles === null ? (
            <p className="cat-laddar">{t("loading")}</p>
          ) : vehicles.length === 0 ? (
            <p className="cat-tom-lista">{t("fleetNone")}</p>
          ) : (
            <ul className="cat-etikettval">
              {vehicles.map((vehicle) => {
                const draft = vehicle.status !== "ready";
                const has = qrLabel(vehicle) !== null;
                return (
                  <li key={vehicle.id}>
                    <label>
                      <input
                        type="checkbox"
                        checked={chosen.has(vehicle.id) && !draft}
                        disabled={draft}
                        onChange={(event) => props.onChoose?.(vehicle.id, event.target.checked)}
                      />
                      <b>{title(t, vehicle)}</b>
                      <span className="cat-under">{draft ? t("labelsDraft") : has ? (renew ? t("labelsRenewed") : t("labelsHasLabel")) : t("labelsGetsLabel")}</span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <div className="cat-sidokolumn">
          <section className="tm-kort cat-avsnitt" aria-labelledby={`${id}-storlek`}>
            <h2 id={`${id}-storlek`}>{t("labelsSize")}</h2>
            <div className="cat-val-lista" role="radiogroup" aria-labelledby={`${id}-storlek`}>
              {LABEL_SIZES.map((choice) => (
                <label key={choice}>
                  <input type="radio" name={`${id}-storlek`} checked={size === choice} onChange={() => props.onSize?.(choice)} />
                  {t(choice === "small" ? "labelsSmall" : "labelsLarge", { n: perSheet(choice) })}
                </label>
              ))}
            </div>
            <label className="cat-val-rad">
              <input type="checkbox" checked={renew} onChange={(event) => props.onRenew?.(event.target.checked)} />
              {t("labelsRenew")}
            </label>
            <p className="cat-hjalp">{t("labelsRenewHelp")}</p>
            <button type="button" className="tm-knapp primar" disabled={count === 0 || props.busy} onClick={props.onPrint}>
              {props.busy ? t("labelsMaking") : count === 1 ? t("labelsPrintOne") : t("labelsPrint", { n: count })}
            </button>
            {count === 0 && vehicles?.length ? <p className="cat-hjalp">{t("labelsChooseFirst")}</p> : null}
            {plan.make.length ? <p className="cat-hjalp">{t("labelsWillMake", { n: plan.make.length })}</p> : null}
          </section>
        </div>
      </div>
      <h2 className="cat-arkrubrik">{t("labelsSheet")}</h2>
      <LabelSheet t={t} vehicles={plan.print} size={size} />
    </>
  );
}

export function LabelsPage({ ctx }: { ctx: Ctx }) {
  const { t } = ctx;
  const [vehicles, setVehicles] = useState<Vehicle[] | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(() => chosenFromAddress(window.location.search));
  const [size, setSize] = useState<LabelSize>("small");
  const [renew, setRenew] = useState(false);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState(0);
  const owner = isOwner(ctx);
  const page = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (owner) api.vehicles().then((list) => setVehicles(list.vehicles), (failure) => setError(problemText(t, failure)));
  }, [owner, t]);

  useEffect(() => {
    // The labels are made and on the sheet: print when their codes have come.
    if (round > 0) void printWhenReady(page.current?.querySelector(".cat-ark") ?? null);
  }, [round]);

  const print = useCallback(
    async (confirmed: boolean) => {
      if (!vehicles) return;
      const plan = labelPlan(vehicles, chosen, renew);
      if (plan.replace.length && !confirmed) {
        setAsking(true);
        return;
      }
      setBusy(true);
      setError(null);
      const done = await makeLabels(plan);
      setVehicles((now) => (now ? withChanged(now, done.made) : now));
      setBusy(false);
      if (done.error) {
        setError(problemText(t, done.error));
        return;
      }
      // Printed once; replacing again needs a new yes.
      setRenew(false);
      setRound((n) => n + 1);
    },
    [vehicles, chosen, renew, t],
  );

  if (!owner)
    return (
      <>
        <Crumbs ctx={ctx} items={[{ href: PATHS.vehicles, label: t("vehicles") }, { label: t("labelsTitle") }]} />
        <h1>{t("labelsTitle")}</h1>
        <section className="tm-kort cat-tomt">
          <p className="cat-tomt-rubrik">{t("labelsOwnerOnly")}</p>
        </section>
      </>
    );

  const replacing = vehicles ? labelPlan(vehicles, chosen, renew).replace.length : 0;
  return (
    <div ref={page} className="cat-etikettsida">
      <LabelsView
        ctx={ctx}
        vehicles={vehicles}
        chosen={chosen}
        size={size}
        renew={renew}
        busy={busy}
        error={error}
        onChoose={(vehicle, on) =>
          setChosen((before) => {
            const next = new Set(before);
            if (on) next.add(vehicle);
            else next.delete(vehicle);
            return next;
          })
        }
        onChooseAll={(on) => setChosen(on ? new Set((vehicles ?? []).filter((v) => v.status === "ready").map((v) => v.id)) : new Set())}
        onSize={setSize}
        onRenew={setRenew}
        onPrint={() => void print(false)}
      />
      <Dialog open={asking} title={t("labelsReplaceTitle")} onClose={() => setAsking(false)}>
        <p>{t("labelsReplaceText", { n: replacing })}</p>
        <div className="cat-dialogknappar">
          <button type="button" className="tm-knapp" onClick={() => setAsking(false)}>
            {t("cancel")}
          </button>
          <button
            type="button"
            className="tm-knapp primar"
            onClick={() => {
              setAsking(false);
              void print(true);
            }}
          >
            {t("labelsReplaceYes")}
          </button>
        </div>
      </Dialog>
    </div>
  );
}

// Förebildskatalogen (#53, CAT-03, CAT-155–CAT-165, CAT-173, CAT-213): the catalog with one
// type per row, a prototype with its revisions, Föreslå förebild and Föreslå ändring, and the
// review queue for the reviewers TrainMeet ID names. The web search (CAT-166–CAT-172) is in
// SearchPage.tsx; its evidence per field is shown here, on the prototype's page and in the queue.
import { linkClick } from "@trainmeet/design";
import { useEffect, useId, useState } from "react";
import {
  api,
  ApiError,
  KINDS,
  type FieldProfile,
  type FieldRegister,
  type Prototype,
  type PrototypeList,
  type PrototypeProposal,
  type PrototypeRevision,
  type PrototypeSourceKind,
  type PrototypeStatus,
  type TypeData,
  type VehicleKind,
} from "./api";
import { Crumbs, dateText, ErrorLine, kindText, problemText, type Ctx, type T } from "./common";
import { EvidenceTable, staleCount } from "./Evidence";
import type { Language } from "./i18n";
import { changePrototypePath, PATHS, prototypePath } from "./routes";

export const PROFILES: FieldProfile[] = ["SE", "EU", "US"];
const SOURCES: PrototypeSourceKind[] = ["own", "reference"];
const LICENSE = { name: "CC BY-SA 4.0", url: "https://creativecommons.org/licenses/by-sa/4.0/" };

// --- The field register (CAT-156, CAT-158) ---------------------------------------------------

let registered: Promise<FieldRegister> | null = null;

/** The register, fetched once: it changes only with a new Catalog. */
export function fieldRegister(): Promise<FieldRegister> {
  registered ??= api.fieldRegister().catch((failure: unknown) => {
    registered = null;
    throw failure;
  });
  return registered;
}

export function useRegister(): FieldRegister | null {
  const [register, setRegister] = useState<FieldRegister | null>(null);
  useEffect(() => {
    fieldRegister().then(setRegister, () => setRegister(null));
  }, []);
  return register;
}

export type ShownField = { key: string; label: string; unit: string; kind: "text" | "number" | "integer"; long: boolean };

/** The keys a profile shows, in its order, with its label in the language and the unit. */
export function profileFields(register: FieldRegister, profile: FieldProfile, language: Language): ShownField[] {
  const shown = register.profiles.find((each) => each.profile === profile) ?? register.profiles[0];
  const byKey = new Map(register.fields.map((each) => [each.key, each]));
  return (shown?.fields ?? []).flatMap((each) => {
    const field = byKey.get(each.key);
    if (!field) return [];
    return [{ key: each.key, label: language === "sv" ? each.label : each.label_en, unit: field.unit, kind: field.kind, long: field.max_length > 200 }];
  });
}

export function profileName(register: FieldRegister | null, profile: FieldProfile, language: Language): string {
  const found = register?.profiles.find((each) => each.profile === profile);
  return found ? (language === "sv" ? found.name : found.name_en) : profile;
}

/** A value with its unit: 100 km/h. */
export function valueText(field: Pick<ShownField, "unit">, value: string | undefined): string {
  if (!value) return "";
  return field.unit ? `${value} ${field.unit}` : value;
}

/** The type data in short, for the catalog's row: 100 km/h · 2 axlar. */
export function typeSummary(t: T, fields: TypeData): string {
  const speed = fields.max_speed ? `${fields.max_speed} km/h` : fields.max_speed_mph ? `${fields.max_speed_mph} mph` : "";
  const axles = fields.axles ? t("protoAxles", { n: fields.axles }) : "";
  return [speed, axles].filter(Boolean).join(" · ");
}

export function StatusPill({ t, status }: { t: T; status: PrototypeStatus }) {
  return <span className={`cat-pill cat-pill-forebild-${status}`}>{t(`protoStatus_${status}`)}</span>;
}

/** The type data as a table, in the profile's order. own marks the owner's own values on a
 * vehicle (CAT-162), with the prototype's value beside it. */
export function TypeDataTable({
  ctx,
  fields,
  register,
  profile,
  own,
  snapshot,
}: {
  ctx: Ctx;
  fields: TypeData;
  register: FieldRegister | null;
  profile: FieldProfile;
  own?: TypeData;
  snapshot?: TypeData;
}) {
  const { t, language } = ctx;
  if (!register) return <p className="cat-laddar">{t("loading")}</p>;
  return (
    <table className="cat-falttabell cat-typtabell">
      <tbody>
        {profileFields(register, profile, language).map((field) => {
          const mine = own !== undefined && field.key in own;
          return (
            <tr key={field.key} className={mine ? "cat-egen" : undefined}>
              <th scope="row">{field.label}</th>
              <td>{valueText(field, fields[field.key]) || t("notFilled")}</td>
              <td className="cat-extra">
                {mine ? (
                  <>
                    <span className="cat-pill cat-pill-egen">{t("protoOwnValue")}</span>
                    <span className="cat-under">{t("protoPrototypeSays", { value: valueText(field, snapshot?.[field.key]) || t("notFilled") })}</span>
                  </>
                ) : own !== undefined ? (
                  <span className="cat-under">{t("protoInherited")}</span>
                ) : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** CC BY-SA 4.0, said on the catalog's pages and in the proposal (CAT-213). */
export function LicenseLine({ t, license = LICENSE.name, url = LICENSE.url }: { t: T; license?: string; url?: string }) {
  return (
    <p className="cat-hjalp cat-licens">
      {t("protoLicense")}{" "}
      <a href={url} rel="license">
        {license}
      </a>
      .
    </p>
  );
}

// --- The catalog (CAT-173) -----------------------------------------------------------------------

export type KindGroup = "all" | "engines" | "coaches" | "wagons";
export const KIND_GROUPS: Record<KindGroup, VehicleKind[]> = {
  all: [],
  engines: ["locomotive", "multiple_unit"],
  coaches: ["passenger_coach"],
  wagons: ["freight_wagon"],
};
const GROUP_TEXT = { all: "protoChipAll", engines: "protoChipEngines", coaches: "protoChipCoaches", wagons: "protoChipWagons" } as const;

export type PrototypesViewProps = {
  ctx: Ctx;
  list: PrototypeList | null;
  mine: PrototypeRevision[];
  q: string;
  group: KindGroup;
  error: string | null;
  onQ?: (q: string) => void;
  onGroup?: (group: KindGroup) => void;
};

export function PrototypesView({ ctx, list, mine, q, group, error, onQ, onGroup }: PrototypesViewProps) {
  const { t, navigate, language } = ctx;
  const searching = q.trim() !== "" || group !== "all";
  return (
    <>
      <div className="cat-rubrikrad">
        <div>
          <p className="tm-overrubrik">{t("protoEyebrow")}</p>
          <h1>{t("prototypes")}</h1>
          <p className="cat-ingress">{t("protoIntro")}</p>
        </div>
        <div className="cat-knappar">
          {list?.reviewer ? (
            <a className="tm-knapp" href={PATHS.reviewQueue} onClick={linkClick(navigate, PATHS.reviewQueue)}>
              {t("protoToReview")} <span className="cat-antal">{list.to_review ?? 0}</span>
            </a>
          ) : null}
          <a className="tm-knapp" href={PATHS.searchPrototype} onClick={linkClick(navigate, PATHS.searchPrototype)}>
            {t("protoSearchWeb")}
          </a>
          <a className="tm-knapp primar" href={PATHS.newPrototype} onClick={linkClick(navigate, PATHS.newPrototype)}>
            {t("protoNew")}
          </a>
        </div>
      </div>

      <section className="tm-kort cat-lista" aria-label={t("protoCatalog")}>
        <div className="cat-verktyg">
          <input className="cat-sok" type="search" value={q} aria-label={t("protoSearch")} placeholder={t("protoSearch")} onChange={(event) => onQ?.(event.target.value)} />
          <div className="cat-chips" role="group" aria-label={t("kindFilter")}>
            {(Object.keys(KIND_GROUPS) as KindGroup[]).map((each) => (
              <button key={each} type="button" className="cat-chip" aria-pressed={group === each} onClick={() => onGroup?.(each)}>
                {t(GROUP_TEXT[each])}
              </button>
            ))}
          </div>
        </div>
        <ErrorLine text={error} />
        {list === null ? (
          error ? null : <p className="cat-laddar">{t("loading")}</p>
        ) : list.prototypes.length === 0 ? (
          <p className="cat-tom-lista">{searching ? t("protoNoMatch") : `${t("prototypesEmpty")} ${t("prototypesEmptyDetail")}`}</p>
        ) : (
          <table className="cat-tabell cat-forebilder">
            <thead>
              <tr>
                <th>{t("protoColType")}</th>
                <th>{t("protoColDescription")}</th>
                <th>{t("protoColTypeData")}</th>
                <th>{t("protoColUsed")}</th>
                <th>{t("protoColState")}</th>
              </tr>
            </thead>
            <tbody>
              {list.prototypes.map((prototype) => (
                <tr key={prototype.id}>
                  <td>
                    <a className="cat-fordon" href={prototypePath(prototype.id)} onClick={linkClick(navigate, prototypePath(prototype.id))}>
                      <b>{prototype.name}</b>
                    </a>
                    <span className="cat-under">{[prototype.fields.litt, prototype.fields.operator, kindText(t, prototype.kind)].filter(Boolean).join(" · ")}</span>
                  </td>
                  <td>{prototype.fields.description ?? ""}</td>
                  <td>{prototype.status === "reviewed" ? typeSummary(t, prototype.fields) : t("protoWaiting")}</td>
                  <td>{t("protoVehicles", { n: prototype.vehicles })}</td>
                  <td>
                    <StatusPill t={t} status={prototype.status} />
                    {prototype.status === "reviewed" && (prototype.waiting ?? 0) > 0 ? <span className="cat-under">{t("protoChangeWaiting")}</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {mine.length ? (
        <section className="tm-kort cat-avsnitt" aria-labelledby="mina-forslag">
          <h2 id="mina-forslag">{t("protoMine")}</h2>
          <ul className="cat-handelser">
            {mine.map((revision) => (
              <li key={revision.id}>
                <span>
                  <a href={prototypePath(revision.prototype)} onClick={linkClick(navigate, prototypePath(revision.prototype))}>
                    {revision.name}
                  </a>{" "}
                  · {revision.base ? t("protoChangeOf", { n: revision.base }) : t("protoNewOne")}
                  {revision.comment ? <span className="cat-under">«{revision.comment}»</span> : null}
                </span>
                <span className="cat-var">
                  <StatusPill t={t} status={revision.status} />
                  <time className="cat-under" dateTime={revision.created_at}>
                    {dateText(language, revision.created_at)}
                  </time>
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className="cat-hjalp">{t("protoShared")}</p>
      <LicenseLine t={t} license={list?.license} url={list?.license_url} />
    </>
  );
}

export function PrototypesPage({ ctx }: { ctx: Ctx }) {
  const [q, setQ] = useState("");
  const [group, setGroup] = useState<KindGroup>("all");
  const [list, setList] = useState<PrototypeList | null>(null);
  const [mine, setMine] = useState<PrototypeRevision[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    const timer = window.setTimeout(() => {
      api.prototypes(q, KIND_GROUPS[group]).then(
        (found) => current && (setList(found), setError(null)),
        (failure) => current && setError(problemText(ctx.t, failure)),
      );
    }, 200);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [q, group, ctx.t]);

  useEffect(() => {
    api.myProposals().then(setMine, () => setMine([]));
  }, []);

  return <PrototypesView ctx={ctx} list={list} mine={mine} q={q} group={group} error={error} onQ={setQ} onGroup={setGroup} />;
}

// --- Belägget per fält (CAT-169, CAT-170) ------------------------------------------------------

/** The evidence of a prototype or a proposal from the web search: per field its sources, with
 * the publisher's class and whether the excerpt still agrees with the value. Nothing without
 * evidence. */
export function EvidenceBlock({ ctx, fields, evidence, register, profile }: { ctx: Ctx; fields: TypeData; evidence: Prototype["evidence"]; register: FieldRegister | null; profile: FieldProfile }) {
  const { t, language } = ctx;
  if (!evidence || Object.keys(evidence).length === 0 || !register) return null;
  const stale = staleCount(evidence);
  return (
    <div className="cat-belaggblock">
      <h3>{t("evidenceTitle")}</h3>
      <p className="cat-hjalp">{t("evidenceIntro")}</p>
      {stale ? (
        <p className="cat-varning" role="status">
          {t("evidenceStale")}: {stale}
        </p>
      ) : null}
      <EvidenceTable ctx={ctx} fields={profileFields(register, profile, language)} values={fields} evidence={evidence} onlyEvidence />
    </div>
  );
}

// --- One prototype, with its revisions (CAT-159) -------------------------------------------------

function SourceLine({ t, source }: { t: T; source: Prototype["source"] }) {
  return (
    <p className="cat-hjalp">
      <b>{t(`protoSource_${source.kind}`)}:</b> {source.text}
    </p>
  );
}

export function PrototypeView({ ctx, prototype, register }: { ctx: Ctx; prototype: Prototype; register: FieldRegister | null }) {
  const { t, navigate, language } = ctx;
  const revisions = prototype.revisions ?? [];
  const change = changePrototypePath(prototype.id);
  return (
    <>
      <Crumbs ctx={ctx} items={[{ href: PATHS.prototypes, label: t("prototypes") }, { label: prototype.name }]} />
      <p className="tm-overrubrik">{t("protoEyebrowOne")}</p>
      <h1>
        {prototype.name} <StatusPill t={t} status={prototype.status} />
      </h1>
      <p className="cat-ingress">
        {[kindText(t, prototype.kind), profileName(register, prototype.profile, language), prototype.revision ? t("protoRevision", { n: prototype.revision }) : ""]
          .filter(Boolean)
          .join(" · ")}
      </p>
      <div className="cat-kortet">
        <div className="cat-huvudkolumn">
          <section className="tm-kort" aria-labelledby="typuppgifter">
            <div className="cat-kortrubrik">
              <h2 id="typuppgifter">{t("protoTypeData")}</h2>
              {prototype.status === "reviewed" ? (
                <a className="tm-knapp" href={change} onClick={linkClick(navigate, change)}>
                  {t("protoProposeChange")}
                </a>
              ) : null}
            </div>
            <TypeDataTable ctx={ctx} fields={prototype.fields} register={register} profile={prototype.profile} />
            <SourceLine t={t} source={prototype.source} />
            <EvidenceBlock ctx={ctx} fields={prototype.fields} evidence={prototype.evidence} register={register} profile={prototype.profile} />
            <p className="cat-hjalp">{t("protoVehicles", { n: prototype.vehicles })}</p>
          </section>
          <LicenseLine t={t} />
        </div>
        <div className="cat-sidokolumn">
          <section className="tm-kort" aria-labelledby="revisioner">
            <h2 id="revisioner">{t("protoRevisions")}</h2>
            <ol className="cat-handelser cat-revisioner">
              {revisions.map((revision) => (
                <li key={revision.id}>
                  <span>
                    <b>{t("protoRevision", { n: revision.number })}</b> <StatusPill t={t} status={revision.status} />
                    {revision.proposed_by ? <span className="cat-under">{t("protoBy", { name: revision.proposed_by })}</span> : null}
                    {revision.comment ? <span className="cat-under">«{revision.comment}»</span> : null}
                  </span>
                  <time className="cat-under" dateTime={revision.reviewed_at ?? revision.created_at}>
                    {dateText(language, revision.reviewed_at ?? revision.created_at)}
                  </time>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </div>
    </>
  );
}

export function PrototypePage({ ctx, id }: { ctx: Ctx; id: string }) {
  const register = useRegister();
  const [prototype, setPrototype] = useState<Prototype | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.prototype(id).then(setPrototype, (failure) => setError(problemText(ctx.t, failure)));
  }, [id, ctx.t]);
  if (!prototype) return error ? <ErrorLine text={error} /> : <p className="cat-laddar">{ctx.t("loading")}</p>;
  return <PrototypeView ctx={ctx} prototype={prototype} register={register} />;
}

// --- Föreslå förebild and Föreslå ändring (CAT-163, CAT-213) ---------------------------------------

export type Draft = {
  name: string;
  kind: VehicleKind | null;
  profile: FieldProfile;
  fields: TypeData;
  sourceKind: PrototypeSourceKind;
  source: string;
  mayShare: boolean;
};

export const EMPTY_DRAFT: Draft = { name: "", kind: null, profile: "SE", fields: {}, sourceKind: "own", source: "", mayShare: false };

/** A change starts from the prototype as it is now; the source is the proposer's own. */
export function draftOf(prototype: Prototype): Draft {
  return { name: prototype.name, kind: prototype.kind ?? null, profile: prototype.profile, fields: { ...prototype.fields }, sourceKind: "own", source: "", mayShare: false };
}

/** What is sent: only the profile's keys, and the base for a change. */
export function proposalOf(draft: Draft, register: FieldRegister, change: Prototype | null): PrototypeProposal {
  const keys = new Set(profileFields(register, draft.profile, "sv").map((field) => field.key));
  const fields = Object.fromEntries(Object.entries(draft.fields).filter(([key, value]) => keys.has(key) && value.trim()));
  return {
    prototype: change?.id ?? null,
    base: change?.revision ?? null,
    name: draft.name.trim(),
    kind: draft.kind,
    profile: draft.profile,
    fields,
    source: { kind: draft.sourceKind, text: draft.source.trim() },
    may_share: true,
    search: null,
  };
}

export const readyToSend = (draft: Draft) => draft.mayShare && draft.name.trim() !== "" && draft.source.trim() !== "";

export type ProposalViewProps = {
  ctx: Ctx;
  draft: Draft;
  register: FieldRegister | null;
  change: Prototype | null;
  busy: boolean;
  error: string | null;
  onDraft?: (draft: Draft) => void;
  onSend?: () => void;
};

export function ProposalView({ ctx, draft, register, change, busy, error, onDraft, onSend }: ProposalViewProps) {
  const { t, navigate, language } = ctx;
  const id = useId();
  const set = (update: Partial<Draft>) => onDraft?.({ ...draft, ...update });
  const back = change ? prototypePath(change.id) : PATHS.prototypes;
  return (
    <>
      <Crumbs ctx={ctx} items={[{ href: PATHS.prototypes, label: t("prototypes") }, ...(change ? [{ href: back, label: change.name }] : []), { label: change ? t("protoChangeTitle") : t("protoNewTitle") }]} />
      <p className="tm-overrubrik">{change ? t("protoChangeEyebrow", { n: change.revision ?? 1 }) : t("protoNewEyebrow")}</p>
      <h1>{change ? t("protoChangeHeading", { name: change.name }) : t("protoNewTitle")}</h1>
      <p className="cat-ingress">{t("protoProposalIntro")}</p>
      <form
        className="tm-kort cat-formular"
        onSubmit={(event) => {
          event.preventDefault();
          if (readyToSend(draft)) onSend?.();
        }}
      >
        <div className="cat-par">
          <div className="cat-falt">
            <label htmlFor={`${id}-namn`}>{t("protoName")}</label>
            <input id={`${id}-namn`} value={draft.name} maxLength={80} required onChange={(event) => set({ name: event.target.value })} />
          </div>
          <div className="cat-falt">
            <label htmlFor={`${id}-slag`}>{t("fKind")}</label>
            <select id={`${id}-slag`} value={draft.kind ?? ""} onChange={(event) => set({ kind: (event.target.value || null) as VehicleKind | null })}>
              <option value="">{t("notFilled")}</option>
              {KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {kindText(t, kind)}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="cat-falt">
          <label htmlFor={`${id}-profil`}>{t("protoProfile")}</label>
          <select id={`${id}-profil`} value={draft.profile} onChange={(event) => set({ profile: event.target.value as FieldProfile })}>
            {PROFILES.map((profile) => (
              <option key={profile} value={profile}>
                {profileName(register, profile, language)}
              </option>
            ))}
          </select>
        </div>
        <fieldset className="cat-typfalt">
          <legend>{t("protoTypeData")}</legend>
          {register ? (
            <TypeDataInputs id={id} fields={profileFields(register, draft.profile, language)} values={draft.fields} onChange={(fields) => set({ fields })} />
          ) : (
            <p className="cat-laddar">{t("loading")}</p>
          )}
        </fieldset>
        <fieldset className="cat-typfalt">
          <legend>{t("protoSource")}</legend>
          <div className="cat-chips" role="radiogroup" aria-label={t("protoSource")}>
            {SOURCES.map((kind) => (
              <label key={kind} className="cat-vaxel">
                <input type="radio" name={`${id}-kalla`} checked={draft.sourceKind === kind} onChange={() => set({ sourceKind: kind })} />
                {t(`protoSource_${kind}`)}
              </label>
            ))}
          </div>
          <div className="cat-falt">
            <label htmlFor={`${id}-kalltext`}>{t("protoSourceText")}</label>
            <textarea id={`${id}-kalltext`} value={draft.source} maxLength={1000} rows={2} required aria-describedby={`${id}-kallhjalp`} onChange={(event) => set({ source: event.target.value })} />
            <p id={`${id}-kallhjalp`} className="cat-hjalp">
              {t("protoSourceHelp")}
            </p>
          </div>
        </fieldset>
        <label className="cat-vaxel cat-dela">
          <input type="checkbox" checked={draft.mayShare} onChange={(event) => set({ mayShare: event.target.checked })} />
          <span>
            {t("protoMayShare")}{" "}
            <a href={LICENSE.url} rel="license">
              {LICENSE.name}
            </a>
            .
          </span>
        </label>
        <p className="cat-hjalp">{t("protoReviewNote")}</p>
        <ErrorLine text={error} />
        <div className="cat-formknappar">
          <a className="tm-knapp" href={back} onClick={linkClick(navigate, back)}>
            {t("cancel")}
          </a>
          <button type="submit" className="tm-knapp primar" disabled={busy || !readyToSend(draft) || !register}>
            {busy ? t("saving") : t("protoSend")}
          </button>
        </div>
      </form>
    </>
  );
}

/** One input per key in the profile, with the unit beside the label. */
export function TypeDataInputs({ id, fields, values, onChange }: { id: string; fields: ShownField[]; values: TypeData; onChange: (values: TypeData) => void }) {
  return (
    <div className="cat-typfalten">
      {fields.map((field) => {
        const inputId = `${id}-${field.key}`;
        const label = field.unit ? `${field.label} (${field.unit})` : field.label;
        const change = (value: string) => onChange({ ...values, [field.key]: value });
        return (
          <div key={field.key} className={field.long ? "cat-falt cat-hela" : "cat-falt"}>
            <label htmlFor={inputId}>{label}</label>
            {field.long ? (
              <textarea id={inputId} value={values[field.key] ?? ""} rows={2} maxLength={1000} onChange={(event) => change(event.target.value)} />
            ) : (
              <input id={inputId} value={values[field.key] ?? ""} inputMode={field.kind === "text" ? undefined : field.kind === "integer" ? "numeric" : "decimal"} onChange={(event) => change(event.target.value)} />
            )}
          </div>
        );
      })}
    </div>
  );
}

export function ProposalPage({ ctx, id }: { ctx: Ctx; id?: string }) {
  const register = useRegister();
  const [change, setChange] = useState<Prototype | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!id) return;
    api.prototype(id).then(
      (found) => {
        setChange(found);
        setDraft(draftOf(found));
      },
      (failure) => setError(problemText(ctx.t, failure)),
    );
  }, [id, ctx.t]);
  if (id && !change) return error ? <ErrorLine text={error} /> : <p className="cat-laddar">{ctx.t("loading")}</p>;
  const send = async () => {
    if (!register) return;
    setBusy(true);
    setError(null);
    try {
      const sent = await api.propose(proposalOf(draft, register, change));
      ctx.navigate?.(prototypePath(sent.prototype));
    } catch (failure) {
      setError(failure instanceof ApiError && failure.code === "changed" ? ctx.t("protoChanged") : problemText(ctx.t, failure));
      setBusy(false);
    }
  };
  return <ProposalView ctx={ctx} draft={draft} register={register} change={change} busy={busy} error={error} onDraft={setDraft} onSend={() => void send()} />;
}

// --- Granskningskön (CAT-164, CAT-165) -------------------------------------------------------------

export type ReviewQueueViewProps = {
  ctx: Ctx;
  queue: PrototypeRevision[] | null;
  register: FieldRegister | null;
  comments: Record<string, string>;
  busy: string | null;
  error: string | null;
  onComment?: (revision: string, text: string) => void;
  onReview?: (revision: PrototypeRevision, decision: "approve" | "reject") => void;
};

export function ReviewQueueView({ ctx, queue, register, comments, busy, error, onComment, onReview }: ReviewQueueViewProps) {
  const { t, navigate, language } = ctx;
  return (
    <>
      <Crumbs ctx={ctx} items={[{ href: PATHS.prototypes, label: t("prototypes") }, { label: t("protoQueueTitle") }]} />
      <p className="tm-overrubrik">{t("protoQueueEyebrow")}</p>
      <h1>{t("protoQueueTitle")}</h1>
      <p className="cat-ingress">{t("protoQueueIntro")}</p>
      <ErrorLine text={error} />
      {queue === null ? (
        error ? null : <p className="cat-laddar">{t("loading")}</p>
      ) : queue.length === 0 ? (
        <section className="tm-kort cat-tomt">
          <p className="cat-tomt-rubrik">{t("protoQueueEmpty")}</p>
        </section>
      ) : (
        queue.map((revision) => {
          const comment = comments[revision.id] ?? "";
          const page = prototypePath(revision.prototype);
          return (
            <section key={revision.id} className="tm-kort cat-avsnitt cat-granska" aria-labelledby={`granska-${revision.id}`}>
              <div className="cat-kortrubrik">
                <h2 id={`granska-${revision.id}`}>
                  {revision.name}: {revision.base ? t("protoChangeOf", { n: revision.base }) : t("protoNewOne")}
                </h2>
                {revision.base ? (
                  <a className="tm-knapp" href={page} onClick={linkClick(navigate, page)}>
                    {t("protoOpenCurrent")}
                  </a>
                ) : null}
              </div>
              <p className="cat-hjalp">
                {revision.proposed_by ? t("protoBy", { name: revision.proposed_by }) : t("protoByNobody")} · {dateText(language, revision.created_at)}
                {revision.kind ? ` · ${kindText(t, revision.kind)}` : ""} · {profileName(register, revision.profile, language)}
              </p>
              <TypeDataTable ctx={ctx} fields={revision.fields} register={register} profile={revision.profile} />
              <SourceLine t={t} source={revision.source} />
              <EvidenceBlock ctx={ctx} fields={revision.fields} evidence={revision.evidence} register={register} profile={revision.profile} />
              <div className="cat-falt">
                <label htmlFor={`kommentar-${revision.id}`}>{t("protoComment")}</label>
                <textarea id={`kommentar-${revision.id}`} value={comment} maxLength={1000} rows={2} onChange={(event) => onComment?.(revision.id, event.target.value)} />
                <p className="cat-hjalp">{t("protoCommentHelp")}</p>
              </div>
              <div className="cat-knappar">
                <button type="button" className="tm-knapp primar" disabled={busy !== null} onClick={() => onReview?.(revision, "approve")}>
                  {t("protoApprove")}
                </button>
                <button type="button" className="tm-knapp" disabled={busy !== null || !comment.trim()} onClick={() => onReview?.(revision, "reject")}>
                  {t("protoReject")}
                </button>
              </div>
            </section>
          );
        })
      )}
    </>
  );
}

export function ReviewQueuePage({ ctx }: { ctx: Ctx }) {
  const register = useRegister();
  const [queue, setQueue] = useState<PrototypeRevision[] | null>(null);
  const [comments, setComments] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () =>
    api.reviewQueue().then(setQueue, (failure) => {
      setQueue(null);
      setError(failure instanceof ApiError && failure.code === "forbidden" ? ctx.t("protoQueueOnly") : problemText(ctx.t, failure));
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps -- load once
  useEffect(() => void load(), []);
  return (
    <ReviewQueueView
      ctx={ctx}
      queue={queue}
      register={register}
      comments={comments}
      busy={busy}
      error={error}
      onComment={(revision, text) => setComments((now) => ({ ...now, [revision]: text }))}
      onReview={async (revision, decision) => {
        setBusy(revision.id);
        setError(null);
        try {
          await api.review(revision.id, { decision, comment: (comments[revision.id] ?? "").trim() });
        } catch (failure) {
          setError(failure instanceof ApiError && failure.code === "changed" ? ctx.t("protoChanged") : problemText(ctx.t, failure));
        }
        setBusy(null);
        await load();
      }}
    />
  );
}

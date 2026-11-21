// Sök på webben (#53 del b, CAT-166–CAT-172, CAT-219), as the design's Ny förebild med
// webbsökning: the marking to search for with the price and the balance, the consent the first
// time, the wait, and the AI's proposal with its sources per field, which the person sends to
// the review queue as it is or after changing it. The search fills the catalog, never a vehicle.
import { linkClick } from "@trainmeet/design";
import { useEffect, useId, useState } from "react";
import { api, ApiError, KINDS, SEARCH_PRICE, type FieldProfile, type FieldRegister, type PrototypeSearch, type PrototypeSearchConsent, type VehicleKind } from "./api";
import { Crumbs, Dialog, ErrorLine, kindText, problemText, type Ctx } from "./common";
import { EvidenceTable } from "./Evidence";
import type { TextKey } from "./i18n";
import { LicenseLine, PROFILES, profileFields, profileName, TypeDataInputs, useRegister } from "./PrototypesPage";
import { PATHS, prototypePath, searchPath } from "./routes";
import { askOf, canPay, draftOf, EMPTY_FORM, formOf, markingOk, needsConsent, proposalOf, readyToSend, runSearch, searchProblem, type SearchDraft, type SearchForm } from "./search";

const LICENSE = { name: "CC BY-SA 4.0", url: "https://creativecommons.org/licenses/by-sa/4.0/" };
const number = (value: number) => value.toLocaleString("sv-SE");

export type SearchViewProps = {
  ctx: Ctx;
  register: FieldRegister | null;
  consent: PrototypeSearchConsent | null;
  form: SearchForm;
  /** The search is running: the meter is asked, and the page waits. */
  searching: boolean;
  result: PrototypeSearch | null;
  draft: SearchDraft | null;
  /** The proposal is being sent. */
  busy: boolean;
  error: string | null;
  onForm?: (form: SearchForm) => void;
  onSearch?: () => void;
  onDraft?: (draft: SearchDraft) => void;
  onSend?: () => void;
};

/** The price, the balance and the button, or why the search cannot be used here (CAT-219). */
function SearchCard({ ctx, register, consent, form, searching, result, onForm, onSearch }: SearchViewProps) {
  const { t, navigate, language } = ctx;
  const id = useId();
  const off = consent !== null && !consent.available;
  const price = consent?.price ?? SEARCH_PRICE;
  const short = consent !== null && consent.available && !canPay(consent);
  const set = (update: Partial<SearchForm>) => onForm?.({ ...form, ...update });
  // The other searches that wait to be sent: the one shown is not one to open again.
  const unsent = (consent?.unsent ?? []).filter((each) => each.id !== result?.id);
  return (
    <section className="tm-kort cat-avsnitt cat-sokkort" aria-labelledby={`${id}-sok`}>
      <h2 id={`${id}-sok`}>{t("searchForm")}</h2>
      {off ? (
        <div className="cat-besvar" role="status">
          {/* Why not, in Catalog's own words: not connected (CAT-219), or ID does not answer. */}
          <p className="cat-varning">{language === "sv" && consent.message ? consent.message : t("problem_search_off")}</p>
          <a className="tm-knapp primar" href={PATHS.newPrototype} onClick={linkClick(navigate, PATHS.newPrototype)}>
            {t("searchByHand")}
          </a>
        </div>
      ) : (
        <form
          className="cat-formular cat-sokform"
          onSubmit={(event) => {
            event.preventDefault();
            if (markingOk(form) && canPay(consent) && !searching) onSearch?.();
          }}
        >
          <div className="cat-falt">
            <label htmlFor={`${id}-litt`}>{t("searchLitt")}</label>
            <input id={`${id}-litt`} value={form.litt} maxLength={40} required disabled={searching} aria-describedby={`${id}-litthjalp`} onChange={(event) => set({ litt: event.target.value })} />
            <p id={`${id}-litthjalp`} className="cat-hjalp">
              {t("searchLittHelp")}
            </p>
          </div>
          <div className="cat-falt">
            <label htmlFor={`${id}-bolag`}>{t("searchOperator")}</label>
            <input id={`${id}-bolag`} value={form.operator} maxLength={80} disabled={searching} onChange={(event) => set({ operator: event.target.value })} />
          </div>
          <div className="cat-par">
            <div className="cat-falt">
              <label htmlFor={`${id}-slag`}>{t("fKind")}</label>
              <select id={`${id}-slag`} value={form.kind ?? ""} disabled={searching} onChange={(event) => set({ kind: (event.target.value || null) as VehicleKind | null })}>
                <option value="">{t("notFilled")}</option>
                {KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {kindText(t, kind)}
                  </option>
                ))}
              </select>
            </div>
            <div className="cat-falt">
              <label htmlFor={`${id}-profil`}>{t("protoProfile")}</label>
              <select id={`${id}-profil`} value={form.profile} disabled={searching} onChange={(event) => set({ profile: event.target.value as FieldProfile })}>
                {PROFILES.map((profile) => (
                  <option key={profile} value={profile}>
                    {profileName(register, profile, language)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <p className="cat-hjalp">{t("searchPays", { price })}</p>
          {consent?.own_ai ? <p className="cat-hjalp">{t("searchOwnAi", { model: consent.own_ai })}</p> : null}
          {consent?.available && consent.balance !== null && consent.balance !== undefined ? (
            <p className="cat-hjalp cat-saldo">{t("searchBalance", { balance: number(consent.balance), payer: consent.payer ?? "" })}</p>
          ) : null}
          {short ? (
            <div className="cat-besvar">
              <p className="cat-varning">{t("searchShort")}</p>
              {ctx.tokensUrl ? (
                <a className="tm-knapp" href={ctx.tokensUrl}>
                  {t("searchBuy")}
                </a>
              ) : null}
            </div>
          ) : null}
          <button type="submit" className="tm-knapp primar" disabled={searching || consent === null || short || !markingOk(form)}>
            {t(result ? "searchAgain" : "searchGo", { price })}
          </button>
        </form>
      )}
      {unsent.length ? (
        <div className="cat-osanda">
          <h3>{t("searchUnsent")}</h3>
          <ul className="cat-handelser">
            {unsent.map((each) => (
              <li key={each.id}>
                <a href={searchPath(each.id)} onClick={linkClick(navigate, searchPath(each.id))}>
                  {t("searchUnsentRow", { name: [each.litt, each.operator].filter(Boolean).join(" · "), n: each.fields ?? 0 })}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/** The AI's proposal: each field's value with its sources, what was taken away and why, and the
 * way on to the review queue (CAT-169, CAT-171). */
function ProposalCard({ ctx, register, result, draft, busy, error, onDraft, onSend }: SearchViewProps & { result: PrototypeSearch; draft: SearchDraft }) {
  const { t, navigate, language } = ctx;
  const id = useId();
  const shown = register ? profileFields(register, result.profile, language) : [];
  const label = (key: string) => shown.find((field) => field.key === key)?.label ?? key;
  const evidence = result.evidence ?? {};
  const found = Object.keys(evidence).length;
  const sent = result.revision !== null && result.revision !== undefined;
  const set = (update: Partial<SearchDraft>) => onDraft?.({ ...draft, ...update });
  const proposal = result.prototype ? prototypePath(result.prototype) : PATHS.prototypes;
  return (
    <section className="tm-kort cat-forslag" aria-labelledby={`${id}-forslag`}>
      <div className="cat-kortrubrik">
        <h2 id={`${id}-forslag`}>{t("searchProposal")}</h2>
        <span className="cat-pill cat-pill-ai">{t("searchPill")}</span>
      </div>
      <p className="cat-hjalp" role="status">
        {found ? t("searchFound", { n: found, sources: result.sources }) : t("searchFoundNone")} {t("searchCost", { cost: result.cost, model: result.model })}
      </p>
      {result.existing ? (
        <p className="cat-besvar cat-finns">
          <span className="cat-varning">{t("searchExisting", { name: result.existing.name })}</span>{" "}
          <a href={prototypePath(result.existing.id)} onClick={linkClick(navigate, prototypePath(result.existing.id))}>
            {t("searchExistingOpen")}
          </a>
        </p>
      ) : null}
      {draft.editing && !sent ? (
        <div className="cat-formular cat-andraforst">
          <div className="cat-falt">
            <label htmlFor={`${id}-namn`}>{t("protoName")}</label>
            <input id={`${id}-namn`} value={draft.name} maxLength={80} required onChange={(event) => set({ name: event.target.value })} />
          </div>
          <fieldset className="cat-typfalt">
            <legend>{t("protoTypeData")}</legend>
            {register ? <TypeDataInputs id={id} fields={shown} values={draft.fields} onChange={(fields) => set({ fields })} /> : <p className="cat-laddar">{t("loading")}</p>}
          </fieldset>
          <p className="cat-hjalp">{t("searchEditHelp")}</p>
          <div className="cat-knappar">
            <button type="button" className="tm-knapp" onClick={() => set({ editing: false })}>
              {t("searchEditDone")}
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className="cat-forslagsnamn">
            <span>{t("protoName")}:</span> <b>{draft.name || t("notFilled")}</b>
            <span>
              {result.kind ? ` · ${kindText(t, result.kind)}` : ""} · {profileName(register, result.profile, language)}
            </span>
          </p>
          {register ? (
            <EvidenceTable
              ctx={ctx}
              fields={shown}
              values={draft.fields}
              evidence={evidence}
              searched={result.fields}
              without={(key) => (key === "litt" || key === "operator" ? t("searchGiven") : t("searchNoEvidence"))}
            />
          ) : (
            <p className="cat-laddar">{t("loading")}</p>
          )}
        </>
      )}
      {result.dropped?.length ? (
        <div className="cat-borttaget">
          <p className="cat-hjalp">{t("searchDropped")}</p>
          <ul>
            {result.dropped.map((dropped) => (
              <li key={dropped.key}>{t(`searchDropped_${dropped.reason}` as TextKey, { field: label(dropped.key) })}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {sent ? (
        <div className="cat-besvar cat-skickad" role="status">
          <p className={result.refunded ? "cat-ok" : "cat-hjalp"}>{result.refunded ? t("searchRefunded", { cost: result.cost }) : t("searchSentNote")}</p>
          <a className="tm-knapp" href={proposal} onClick={linkClick(navigate, proposal)}>
            {t("searchOpenProposal")}
          </a>
        </div>
      ) : (
        <form
          className="cat-skicka"
          onSubmit={(event) => {
            event.preventDefault();
            if (readyToSend(draft) && !busy) onSend?.();
          }}
        >
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
          <div className="cat-knappar">
            <button type="submit" className="tm-knapp primar" disabled={busy || !readyToSend(draft) || !register}>
              {busy ? t("saving") : t("searchSend")}
            </button>
            {draft.editing ? null : (
              <button type="button" className="tm-knapp" disabled={busy} onClick={() => set({ editing: true })}>
                {t("searchEdit")}
              </button>
            )}
          </div>
        </form>
      )}
    </section>
  );
}

export function SearchView(props: SearchViewProps) {
  const { ctx, form, searching, result, draft, error } = props;
  const { t } = ctx;
  const name = [form.litt.trim(), form.operator.trim()].filter(Boolean).join(" · ");
  const sent = result?.revision !== null && result?.revision !== undefined;
  const heading = result ? t(sent ? "searchHeadingSent" : "searchHeadingFor", { name: draft?.name || result.litt }) : t("searchHeadingNew");
  return (
    <>
      <Crumbs ctx={ctx} items={[{ href: PATHS.prototypes, label: t("prototypes") }, { label: t("searchTitle") }]} />
      <p className="tm-overrubrik">{t("searchEyebrow")}</p>
      <h1>{heading}</h1>
      <p className="cat-ingress">{t("searchIntro")}</p>
      <div className="cat-kortet">
        <div className="cat-huvudkolumn">
          {searching ? (
            <section className="tm-kort cat-lasning" role="status">
              <p>
                <b>{t("searchingTitle")}</b>
              </p>
              <progress aria-hidden="true" />
              <p>{t("searchingFor", { name })}</p>
              <p className="cat-hjalp">{t("searchingWait")}</p>
            </section>
          ) : result && draft ? (
            <ProposalCard {...props} result={result} draft={draft} />
          ) : (
            <section className="tm-kort cat-forslag">
              <div className="cat-kortrubrik">
                <h2>{t("searchProposal")}</h2>
                <span className="cat-pill cat-pill-ai">{t("searchPill")}</span>
              </div>
              <p className="cat-hjalp">{t("searchNothingYet")}</p>
              <ErrorLine text={error} />
            </section>
          )}
          <LicenseLine t={t} />
        </div>
        <div className="cat-sidokolumn">
          <SearchCard {...props} />
          <section className="tm-kort cat-avsnitt" aria-label={t("searchHow")}>
            <h2>{t("searchHow")}</h2>
            <ol className="cat-sagardet">
              <li>{t("searchHow1")}</li>
              <li>{t("searchHow2")}</li>
              <li>{t("searchHow3")}</li>
            </ol>
            <p className="cat-hjalp">{t("searchHowNote")}</p>
          </section>
        </div>
      </div>
    </>
  );
}

/** What is sent and to whom, before the first search (CAT-142, C40). */
export function SearchConsentView({ ctx, consent, onYes, onNo }: { ctx: Ctx; consent: PrototypeSearchConsent | null; onYes?: () => void; onNo?: () => void }) {
  const { t, language } = ctx;
  return (
    <div className="cat-samtycke">
      <p>{language === "sv" && consent ? consent.text : t("searchHowNote")}</p>
      <p>{t("searchConsentTo", { to: consent?.sent_to ?? "" })}</p>
      <p className="cat-pris">{t("searchConsentPrice", { price: consent?.price ?? SEARCH_PRICE })}</p>
      <p className="cat-hjalp">{t("searchConsentOnce")}</p>
      <div className="cat-dialogknappar">
        <button type="button" className="tm-knapp" onClick={onNo}>
          {t("cancel")}
        </button>
        <button type="button" className="tm-knapp primar" onClick={onYes}>
          {t("searchConsentYes")}
        </button>
      </div>
    </div>
  );
}

export function SearchPage({ ctx, id }: { ctx: Ctx; id?: string }) {
  const register = useRegister();
  const [consent, setConsent] = useState<PrototypeSearchConsent | null>(null);
  const [form, setForm] = useState<SearchForm>(EMPTY_FORM);
  const [searching, setSearching] = useState(false);
  const [result, setResult] = useState<PrototypeSearch | null>(null);
  const [draft, setDraft] = useState<SearchDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const { t } = ctx;

  const loadConsent = () => api.searchConsent().then(setConsent, () => setConsent(null));
  // eslint-disable-next-line react-hooks/exhaustive-deps -- once
  useEffect(() => void loadConsent(), []);

  const show = (found: PrototypeSearch) => {
    setResult(found);
    setDraft(draftOf(found));
    setForm(formOf(found));
  };

  // A search opened again by its address: one's own, as it is now.
  useEffect(() => {
    if (!id || id === result?.id) return;
    api.prototypeSearch(id).then(show, (failure) => setError(problemText(t, failure)));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when the address names another search
  }, [id]);

  const run = async (yes: boolean) => {
    setSearching(true);
    setError(null);
    setResult(null);
    setDraft(null);
    try {
      const found = await runSearch(askOf(crypto.randomUUID(), form, yes));
      show(found);
      ctx.replace?.(searchPath(found.id));
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === "consent_required") setAsking(true);
      else setError(searchProblem(t, failure));
    }
    setSearching(false);
    void loadConsent();
  };

  const search = () => {
    if (!consent) return;
    if (needsConsent(consent, agreed)) setAsking(true);
    else void run(agreed);
  };

  const send = async () => {
    if (!result || !draft || !register) return;
    setBusy(true);
    setError(null);
    try {
      const keys = profileFields(register, result.profile, "sv").map((field) => field.key);
      const sent = await api.propose(proposalOf(result, draft, keys, t("protoSource_web_search")));
      ctx.navigate?.(prototypePath(sent.prototype));
    } catch (failure) {
      setError(failure instanceof ApiError && failure.code === "bad_type_data" ? problemText(t, failure) : searchProblem(t, failure));
      setBusy(false);
    }
  };

  return (
    <>
      <SearchView
        ctx={ctx}
        register={register}
        consent={consent}
        form={form}
        searching={searching}
        result={result}
        draft={draft}
        busy={busy}
        error={error}
        onForm={setForm}
        onSearch={search}
        onDraft={setDraft}
        onSend={() => void send()}
      />
      <Dialog open={asking} title={t("searchConsentTitle")} onClose={() => setAsking(false)}>
        <SearchConsentView
          ctx={ctx}
          consent={consent}
          onNo={() => setAsking(false)}
          onYes={() => {
            setAsking(false);
            setAgreed(true);
            void run(true);
          }}
        />
      </Dialog>
    </>
  );
}

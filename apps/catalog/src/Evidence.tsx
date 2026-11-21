// Belägget per fält (#53 del b, CAT-168–CAT-170): the sources the web search found a value in,
// each with its publisher's class by Catalog's reviewed list, the excerpt, and whether the
// excerpt still agrees with the value that stands in the field. Shown in the search's proposal,
// in the review queue and on the prototype's page.
import type { Evidence, FieldEvidence, PublisherKind, TypeData } from "./api";
import { dateText, type Ctx, type T } from "./common";
import type { TextKey } from "./i18n";

/** A field as the tables show it: PrototypesPage.tsx makes them from the field register. */
export type EvidenceField = { key: string; label: string; unit: string };

export const publisherText = (t: T, kind: PublisherKind) => t(`evidencePublisher_${kind}` as TextKey);

/** The host of a source, for showing beside its title. Only an http(s) address is a link. */
export function hostOf(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.hostname.replace(/^www\./, "") : null;
  } catch {
    return null;
  }
}

const withUnit = (field: EvidenceField, value: string | undefined) => (value ? (field.unit ? `${value} ${field.unit}` : value) : "");

/** How many fields have evidence that no longer agrees with the value (CAT-170). */
export function staleCount(evidence: Evidence | undefined): number {
  return Object.values(evidence ?? {}).filter((items) => items.some((item) => !item.agrees)).length;
}

export function EvidenceItem({ ctx, field, item, changed = false }: { ctx: Ctx; field: EvidenceField; item: FieldEvidence; changed?: boolean }) {
  const { t, language } = ctx;
  const host = hostOf(item.url);
  const agrees = item.agrees && !changed;
  return (
    <li className={agrees ? "cat-belagg-rad" : "cat-belagg-rad cat-belagg-gammalt"}>
      <span className="cat-kalla">
        {host ? (
          <a href={item.url} target="_blank" rel="noopener noreferrer nofollow">
            {item.title || host}
          </a>
        ) : (
          <span>{item.title || item.url}</span>
        )}
        <span className={`cat-pill cat-pill-utgivare cat-pill-utgivare-${item.publisher}`}>{publisherText(t, item.publisher)}</span>
      </span>
      <span className="cat-under">
        {host ?? ""} · {t("evidenceSearched", { date: dateText(language, item.searched_at) })}
      </span>
      <q className="cat-utdrag" aria-label={t("evidenceFrom")}>
        {item.excerpt}
      </q>
      {agrees ? (
        <span className="cat-ok cat-belagg-lage">{t("evidenceAgrees")}</span>
      ) : (
        <span className="cat-belagg-lage">
          <b className="cat-varning">{t("evidenceStale")}</b> <span className="cat-under">{t("evidenceStaleDetail", { value: withUnit(field, item.value) })}</span>
        </span>
      )}
    </li>
  );
}

export type EvidenceTableProps = {
  ctx: Ctx;
  /** The fields to show, in the profile's order: those without a value are left out. */
  fields: EvidenceField[];
  values: TypeData;
  evidence: Evidence;
  /** Only the fields that have evidence: the review queue and the prototype's page show the
   * values in their own table above. */
  onlyEvidence?: boolean;
  /** What stands for a field with a value but no evidence, by its key. */
  without?: (key: string) => string;
  /** The values as the search found them, when the proposer may have changed them since: a
   * changed value no longer agrees with its evidence (CAT-170). */
  searched?: TypeData;
};

/** Each field's value with its sources: the address, the publisher, the excerpt and whether it
 * still agrees (CAT-169, CAT-170). */
export function EvidenceTable({ ctx, fields, values, evidence, onlyEvidence = false, without, searched }: EvidenceTableProps) {
  const { t } = ctx;
  const rows = fields.filter((field) => values[field.key] && (!onlyEvidence || evidence[field.key]?.length));
  if (rows.length === 0) return null;
  return (
    <table className="cat-falttabell cat-belaggtabell">
      <thead className="cat-dold">
        <tr>
          <th scope="col">{t("searchField")}</th>
          <th scope="col">{t("searchValue")}</th>
          <th scope="col">{t("searchSources")}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((field) => {
          const items = evidence[field.key] ?? [];
          const changed = searched !== undefined && items.length > 0 && (searched[field.key] ?? "") !== (values[field.key] ?? "");
          return (
            <tr key={field.key}>
              <th scope="row">{field.label}</th>
              <td>
                <span className={items.length ? "cat-belagt" : undefined}>{withUnit(field, values[field.key])}</span>
                {items.length ? <span className="cat-under">{items.length === 1 ? t("searchSourcesOne") : t("searchSourcesMany", { n: items.length })}</span> : null}
              </td>
              <td>
                {items.length ? (
                  <ul className="cat-belagg">
                    {items.map((item) => (
                      <EvidenceItem key={item.url} ctx={ctx} field={field} item={item} changed={changed} />
                    ))}
                  </ul>
                ) : (
                  <span className="cat-under">{without?.(field.key) ?? t("searchNoEvidence")}</span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

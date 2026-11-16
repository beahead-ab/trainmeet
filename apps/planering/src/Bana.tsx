import { useEffect, useRef, useState } from "react";
import { Problem } from "@trainmeet/hubben";
import { planning, type Draft } from "./api";
import { CERTAINTY, Facts, KINDS, MODES, TRACKS, plural, sourceKind, type Package, type Place, type Section } from "./data";
import { layout, links, sectionLabel, STEP_X, STEP_Y } from "./karta";

// Bana (S6): the map with the places and the clearance sections, with their parts under. Choose
// a section or a place to see it beside; logged in, a section's tracks and clearance mode are
// changed there and saved at once, as on the old page.

type Choice = { kind: "section" | "place"; id: string } | null;

export type BanaProps = {
  admin: boolean;
  meet: string;
  draft: Draft | null;
  initialChoice?: Choice;
  onDraft?: (draft: Draft) => void;
  onTell?: (text: string, good?: boolean) => void;
  onFail?: (error: unknown) => void;
};

export function BanaPage({ admin, meet, draft, initialChoice = null, onDraft, onTell, onFail }: BanaProps) {
  const [choice, setChoice] = useState<Choice>(initialChoice);
  if (!draft) return <p className="liten">Hämtar träffen …</p>;
  const heading = (
    <div className="sidrubrik">
      <div>
        <p className="overrubrik">{draft.meet.name}</p>
        <h1>Bana</h1>
      </div>
      <span className="under">klareringssträckor med delsträckor under</span>
    </div>
  );
  const pkg = draft.package;
  if (!pkg) {
    return (
      <>
        {heading}
        <section className="kort" id="empty">
          <p className="liten">Lägg till underlag under Data först.</p>
        </section>
      </>
    );
  }
  const facts = new Facts(draft.facts ?? []);
  const unsure = new Set((draft.facts ?? []).filter((fact) => fact.certainty === "unsure").map((fact) => fact.ref));
  const doubtful = [...unsure].filter((ref) => ref.startsWith("place:") || ref.startsWith("section:"));
  const sections = pkg.sections ?? [];
  const section = choice?.kind === "section" ? sections.find((item) => item.id === choice.id) : undefined;
  const place = choice?.kind === "place" ? pkg.places.find((item) => item.id === choice.id) : undefined;

  const saveNow = async (change: { section: string; tracks: "single" | "double" } | { section: string; clearance_mode: "requested" | "direct" | null }, text: string) => {
    try {
      onDraft?.(await planning.change(meet, { revision: draft?.revision ?? 0, changes: [change] }));
      onTell?.(text, true);
    } catch (error) {
      // PLAN-38: someone else saved in between; show the new draft with the message.
      if (error instanceof Problem && error.status === 412) onDraft?.(await planning.draft(meet).catch(() => draft as Draft));
      onFail?.(error);
    }
  };

  return (
    <>
      {heading}
      {doubtful.length > 0 && (
        <div className="notis" id="unsure">
          <b>{`▲ ${plural(doubtful.length, "uppgift", "uppgifter")} är osäkra.`}</b> Kontrollera dem under Data, med filtret Osäker.
        </div>
      )}
      <div className="bana-yta" id="map-page">
        <section className="kort karta-kort" aria-labelledby="karta-rubrik">
          <header className="kort-rubrik">
            <h2 id="karta-rubrik">Banan</h2>
            <span id="map-count" className="liten">{`${plural(sections.length, "sträcka", "sträckor")} · ${plural(pkg.places.length, "driftplats", "driftplatser")}`}</span>
          </header>
          <div id="map" className="karta-yta">
            <Karta pkg={pkg} choice={choice} unsure={unsure} onSelect={(kind, id) => setChoice({ kind, id })} />
          </div>
          <footer className="forklaring">
            <span>Fyrkant = driftplats med klarering</span>
            <span>Ring = hållplats eller industri</span>
            <span>Streckad ram = skuggbangård</span>
            <span>Dubbla linjer = dubbelspår</span>
            <span>Grå streckad = spår utan klarering i planen</span>
            <span className="bla">Blå = vald</span>
          </footer>
        </section>
        <aside className="kort vald" id="choice" aria-label="Valt på kartan">
          {section ? (
            <SectionChoice admin={admin} draft={draft} pkg={pkg} section={section} facts={facts} onSave={(change, text) => void saveNow(change, text)} />
          ) : place ? (
            <PlaceChoice draft={draft} pkg={pkg} place={place} facts={facts} />
          ) : (
            <p className="liten">Välj en sträcka eller en driftplats på kartan.</p>
          )}
        </aside>
      </div>
    </>
  );
}

const nameOf = (pkg: Package, id: string) => pkg.places.find((place) => place.id === id)?.name ?? id;

/** The map itself: an SVG fitted to the card's width, never smaller than the names can be read. */
export function Karta({ pkg, choice, unsure, onSelect }: { pkg: Package; choice: Choice; unsure: Set<string>; onSelect: (kind: "section" | "place", id: string) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const [room, setRoom] = useState(0);
  useEffect(() => {
    const measure = () => setRoom((host.current?.parentElement?.clientWidth ?? 0) - 24);
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  const plan = layout(pkg);
  const margin = { x: 90, y: 70 };
  const width = (plan.width - 1) * STEP_X + margin.x * 2;
  const height = (plan.height - 1) * STEP_Y + margin.y * 2;
  const scale = room > 0 ? Math.min(1, Math.max(0.78, room / width)) : 1;
  const places = new Map(pkg.places.map((place) => [place.id, place]));
  const point = (id: string): [number, number] => {
    const [column, row] = plan.at.get(id) ?? [0, 0];
    return [margin.x + (column - plan.left) * STEP_X, margin.y + (row - plan.top) * STEP_Y];
  };
  const curve = (a: string, b: string) => {
    const [ax, ay] = point(a);
    const [bx, by] = point(b);
    if (ay === by || ax === bx) return `M${ax},${ay} L${bx},${by}`;
    const middle = (ax + bx) / 2;
    return `M${ax},${ay} C${middle},${ay} ${middle},${by} ${bx},${by}`;
  };
  const shown = links(pkg).filter((link) => plan.at.has(link.a) && plan.at.has(link.b));
  return (
    <div ref={host}>
      <svg className="karta" viewBox={`0 0 ${width} ${height}`} width={Math.round(width * scale)} height={Math.round(height * scale)} role="group" aria-label="Banan">
        <g className="lankar">
          {shown.map((link) => {
            const section = link.section;
            const chosen = section !== null && choice?.kind === "section" && choice.id === section.id;
            const classes = ["lank", section ? section.tracks : "utan", chosen ? "vald" : "", section && unsure.has(`section:${section.id}`) ? "osaker" : ""].filter(Boolean).join(" ");
            const path = curve(link.a, link.b);
            return (
              <g key={`${link.a}|${link.b}`} className={classes} onClick={section ? () => onSelect("section", section.id) : undefined}>
                {section?.tracks === "double" ? (
                  <>
                    <path d={path} className="yttre" />
                    <path d={path} className="inre" />
                  </>
                ) : (
                  <path d={path} className="enkel" />
                )}
                <path d={path} className="traff" />
                <title>{section ? `${places.get(section.place_a)?.name} – ${places.get(section.place_b)?.name}` : "Spår utan klarering i planen"}</title>
              </g>
            );
          })}
        </g>
        <g className="etiketter">
          {shown.map((link) => {
            const section = link.section;
            const parts = section?.parts ?? [];
            // The section's name once, at its middle part.
            if (!section || !link.part || parts.indexOf(link.part) !== Math.floor((parts.length - 1) / 2)) return null;
            const [ax, ay] = point(link.a);
            const [bx, by] = point(link.b);
            const chosen = choice?.kind === "section" && choice.id === section.id;
            return (
              <text key={`${section.id}-namn`} x={(ax + bx) / 2} y={(ay + by) / 2 - 10} className={"strackanamn" + (chosen ? " vald" : "")}>
                {sectionLabel(section)}
              </text>
            );
          })}
        </g>
        <g className="platser">
          {pkg.places
            .filter((place) => plan.at.has(place.id))
            .map((place) => {
              const [x, y] = point(place.id);
              const chosen = choice?.kind === "place" && choice.id === place.id;
              const remote = place.remote_from ? places.get(place.remote_from) : undefined;
              const note = place.kind === "shadow_yard" ? "skuggbangård" : remote ? `fjärrstyrd från ${remote.name}` : place.kind === "unmanned" ? "obemannad" : null;
              const boxWidth = Math.max(54, place.code.length * 9 + 22);
              return (
                <g
                  key={place.id}
                  className={`plats ${place.kind}${chosen ? " vald" : ""}`}
                  tabIndex={0}
                  role="button"
                  aria-label={place.name}
                  aria-pressed={chosen}
                  onClick={() => onSelect("place", place.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect("place", place.id);
                    }
                  }}
                >
                  {place.kind === "halt" ? (
                    <>
                      <circle cx={x} cy={y} r={9} className="ring" />
                      <text x={x} y={y + 27} className="namn under">
                        {place.name}
                      </text>
                    </>
                  ) : (
                    <>
                      <rect x={x - boxWidth / 2} y={y - 16} width={boxWidth} height={32} rx={6} className="ruta" />
                      <text x={x} y={y + 5} className="kod">
                        {place.code}
                      </text>
                      <text x={x} y={y - 24} className="namn">
                        {place.name}
                      </text>
                      {note && (
                        <text x={x} y={y + 34} className="not">
                          {note}
                        </text>
                      )}
                    </>
                  )}
                </g>
              );
            })}
        </g>
      </svg>
    </div>
  );
}

function Origins({ draft, facts, ref_ }: { draft: Draft; facts: Facts; ref_: string }) {
  const found = facts.of(ref_);
  if (!found.length) return null;
  return (
    <div className="varifran">
      <p className="overrubrik">Varifrån</p>
      <ul>
        {found.flatMap((fact) =>
          fact.origins.map((origin, index) => {
            const [label, kind] = sourceKind(origin, draft.sources);
            const field = fact.ref === ref_ ? "" : ` (${fact.ref.slice(ref_.length + 1)})`;
            return (
              <li key={`${fact.ref}-${index}`}>
                <span className={`kalla ${kind}`.trim()}>{label}</span>
                <span>
                  {origin.at + field}
                  {fact.note && <span className="liten block">{fact.note}</span>}
                </span>
                <span className={`pill ${fact.certainty}`}>{CERTAINTY[fact.certainty]}</span>
              </li>
            );
          }),
        )}
      </ul>
    </div>
  );
}

type SectionSave = (change: { section: string; tracks: "single" | "double" } | { section: string; clearance_mode: "requested" | "direct" | null }, text: string) => void;

function SectionChoice({ admin, draft, pkg, section, facts, onSave }: { admin: boolean; draft: Draft; pkg: Package; section: Section; facts: Facts; onSave: SectionSave }) {
  const parts = section.parts ?? [];
  const between = parts.slice(0, -1).map((part) => {
    const place = pkg.places.find((item) => item.id === part.to_place);
    return place ? `${place.name} (${(KINDS[place.kind] ?? place.kind).toLowerCase()})` : part.to_place;
  });
  const base = MODES[draft.meet.clearance_mode] ?? draft.meet.clearance_mode;
  const fact = facts.byRef.get(`section:${section.id}`);
  const name = `${nameOf(pkg, section.place_a)} – ${nameOf(pkg, section.place_b)}`;
  return (
    <>
      <header>
        <span className="overrubrik">Vald sträcka</span>
        {fact && <span className={`pill ${fact.certainty}`}>{CERTAINTY[fact.certainty]}</span>}
      </header>
      <h2>{`${sectionLabel(section)} · ${name}`}</h2>
      <dl>
        <div className="par">
          <dt>Spår</dt>
          <dd>
            {admin ? (
              <div className="segment" role="group" aria-label="Spår">
                {Object.entries(TRACKS).map(([key, text]) => (
                  <button key={key} type="button" aria-pressed={section.tracks === key} onClick={() => section.tracks !== key && onSave({ section: section.id, tracks: key as "single" | "double" }, `${name} är ${text.toLowerCase()}spår.`)}>
                    {text}
                  </button>
                ))}
              </div>
            ) : (
              `${TRACKS[section.tracks] ?? section.tracks}spår`
            )}
          </dd>
        </div>
        <div className="par">
          <dt>Klarering</dt>
          <dd>
            {admin ? (
              <select className="cell" aria-label="Klarering" value={section.clearance_mode ?? ""} onChange={(event) => onSave({ section: section.id, clearance_mode: (event.target.value || null) as "requested" | "direct" | null }, "Klareringsläget är sparat.")}>
                <option value="">{`${base} (träffens grundläge)`}</option>
                {Object.entries(MODES).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            ) : section.clearance_mode ? (
              MODES[section.clearance_mode]
            ) : (
              `${base} (träffens grundläge)`
            )}
          </dd>
        </div>
        <div className="par">
          <dt>Delsträckor</dt>
          <dd>{parts.map((part) => `${nameOf(pkg, part.from_place)} – ${nameOf(pkg, part.to_place)}`).join(" · ")}</dd>
        </div>
        <div className="par">
          <dt>Driftplatser emellan</dt>
          <dd>{between.join(", ") || "Inga"}</dd>
        </div>
        <div className="par">
          <dt>Sidor och utfarter</dt>
          <dd className="liten">Kommer från stationernas utsida när ställverken ansluter.</dd>
        </div>
      </dl>
      <Origins draft={draft} facts={facts} ref_={`section:${section.id}`} />
    </>
  );
}

function PlaceChoice({ draft, pkg, place, facts }: { draft: Draft; pkg: Package; place: Place; facts: Facts }) {
  const fact = facts.byRef.get(`place:${place.id}`);
  const sections = (pkg.sections ?? []).filter((section) => section.place_a === place.id || section.place_b === place.id);
  return (
    <>
      <header>
        <span className="overrubrik">Vald driftplats</span>
        {fact && <span className={`pill ${fact.certainty}`}>{CERTAINTY[fact.certainty]}</span>}
      </header>
      <h2>{`${place.code} · ${place.name}`}</h2>
      <dl>
        <div className="par">
          <dt>Platstyp</dt>
          <dd>{(KINDS[place.kind] ?? place.kind) + (place.remote_from ? `, från ${nameOf(pkg, place.remote_from)}` : "")}</dd>
        </div>
        <div className="par">
          <dt>Telefon</dt>
          <dd>{place.phone ?? "–"}</dd>
        </div>
        <div className="par">
          <dt>Spår</dt>
          <dd>{(place.tracks ?? []).map((track) => track.name).join(" ") || "–"}</dd>
        </div>
        <div className="par">
          <dt>Sträckor</dt>
          <dd>{sections.map((section) => `${nameOf(pkg, section.place_a)} – ${nameOf(pkg, section.place_b)}`).join(" · ") || "Inga"}</dd>
        </div>
      </dl>
      <Origins draft={draft} facts={facts} ref_={`place:${place.id}`} />
    </>
  );
}

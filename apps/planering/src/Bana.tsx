import { useEffect, useRef, useState } from "react";
import { Problem } from "@trainmeet/hubben";
import { planning, type Changes, type Draft, type TrackPicture } from "./api";
import { CERTAINTY, Facts, KINDS, MODES, TRACKS, areaPlaces, modelLength, partOf, plural, prototypeLength, remoteFrom, sourceKind, type Package, type Place, type Section } from "./data";
import { layout, links, sectionLabel, STEP_X, STEP_Y } from "./karta";

// Bana (S6): the map with the places and the clearance sections, with their parts under. Choose
// a section or a place to see it beside; logged in, a section's tracks and clearance mode are
// changed there and saved at once, as on the old page. What the import derived is confirmed
// here, one at a time or all at once (IMPORT-04), and with a track picture among the sources the
// map stands where the picture has the places, with the picture's lines under it (PLAN-02).
// With CAD's assembly among the sources, a section has its length along the track from the
// modules' real geometry, with its origin, and the map stands where the assembly has the places
// when it has them all (CAD-11, K4).

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
  const [picture, setPicture] = useState<TrackPicture | null>(null);
  const drawn = draft?.sources?.find((source) => source.kind === "track_picture")?.id;
  useEffect(() => {
    if (!drawn) return setPicture(null);
    let live = true;
    planning
      .picture(meet)
      .then((found) => live && setPicture(found))
      .catch(() => live && setPicture(null));
    return () => {
      live = false;
    };
  }, [meet, drawn]);
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
  // CAD's assembly comes first for the map (import 5): the picture is not drawn under it.
  const cadMap = Boolean(draft.assembly && facts.byRef.get("display:map")?.origins.some((origin) => origin.source === draft.assembly?.source));
  const unsure = new Set((draft.facts ?? []).filter((fact) => fact.certainty === "unsure").map((fact) => fact.ref));
  const doubtful = [...unsure].filter((ref) => ref.startsWith("place:") || ref.startsWith("section:"));
  const confirmable = [...unsure].filter((ref) => /^(place|section|part):/.test(ref));
  const sections = pkg.sections ?? [];
  const section = choice?.kind === "section" ? sections.find((item) => item.id === choice.id) : undefined;
  const place = choice?.kind === "place" ? pkg.places.find((item) => item.id === choice.id) : undefined;

  const saveNow = async (change: Changes["changes"][number] | Changes["changes"], text: string) => {
    try {
      const changes = Array.isArray(change) ? change : [change];
      onDraft?.(await planning.change(meet, { revision: draft?.revision ?? 0, changes }));
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
          <b>{`▲ ${plural(doubtful.length, "uppgift", "uppgifter")} är osäkra.`}</b>{" "}
          {admin ? "Bekräfta dem på kartan en i taget, eller alla på en gång om banan stämmer." : "Kontrollera dem under Data, med filtret Osäker."}
          {admin && (
            <button type="button" id="confirm-all" className="sekundar" onClick={() => void saveNow(confirmable.map((ref) => ({ confirm: ref })), `${plural(confirmable.length, "uppgift", "uppgifter")} bekräftade.`)}>
              Bekräfta alla
            </button>
          )}
        </div>
      )}
      <div className="bana-yta" id="map-page">
        <section className="kort karta-kort" aria-labelledby="karta-rubrik">
          <header className="kort-rubrik">
            <h2 id="karta-rubrik">Banan</h2>
            <span id="map-count" className="liten">{`${plural(sections.length, "sträcka", "sträckor")} · ${plural(pkg.places.length, "driftplats", "driftplatser")}`}</span>
          </header>
          <div id="map" className="karta-yta">
            <Karta pkg={pkg} choice={choice} unsure={unsure} picture={cadMap ? null : picture} photo={`/api/planering/1/meets/${encodeURIComponent(meet)}/picture/photo`} lengths={draft.lengths ?? []} onSelect={(kind, id) => setChoice({ kind, id })} />
          </div>
          <footer className="forklaring">
            <span>Fyrkant = driftplats med klarering</span>
            <span>Ring = hållplats eller industri</span>
            <span>Streckad ram = skuggbangård</span>
            <span>Dubbla linjer = dubbelspår</span>
            <span>Grå streckad = spår utan klarering i planen</span>
            {pkg.places.some((item) => item.part_of) && <span id="part-legend">Prickad = del av en station, egen driftplats</span>}
            {(pkg.remote_areas ?? []).map((area) => (
              <span key={area.id} className="fjarromrade">{`Fjärrområdet ${area.name}: ${areaPlaces(area, (id) => nameOf(pkg, id))}`}</span>
            ))}
            <span className="bla">Blå = vald</span>
            {picture && !cadMap && <span id="picture-legend">Grått under = banbilden</span>}
            {cadMap && <span id="cad-legend">{`Kartan står där anläggningen ${draft.assembly?.name ?? ""} har driftplatserna`}</span>}
          </footer>
        </section>
        <aside className="kort vald" id="choice" aria-label="Valt på kartan">
          {section ? (
            <SectionChoice admin={admin} draft={draft} pkg={pkg} section={section} facts={facts} unsure={unsure} onSave={(change, text) => void saveNow(change, text)} />
          ) : place ? (
            <PlaceChoice admin={admin} draft={draft} pkg={pkg} place={place} facts={facts} unsure={unsure} onSave={(change, text) => void saveNow(change, text)} />
          ) : (
            <p className="liten">Välj en sträcka eller en driftplats på kartan.</p>
          )}
        </aside>
      </div>
    </>
  );
}

/** Points on the organiser's picture to pixels on the map: places a few points apart stay apart. */
const PICTURE_SCALE = 3;

const nameOf = (pkg: Package, id: string) => pkg.places.find((place) => place.id === id)?.name ?? id;

/** The map itself: an SVG fitted to the card's width, never smaller than the names can be read. */
export function Karta({ pkg, choice, unsure, picture = null, photo, lengths = [], onSelect }: { pkg: Package; choice: Choice; unsure: Set<string>; picture?: TrackPicture | null; photo?: string; lengths?: { section: string; length: number }[]; onSelect: (kind: "section" | "place", id: string) => void }) {
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
  // Where the organiser's picture has every place, the map stands there (PLAN-02).
  const reference = (pkg.display?.reference_layout ?? {}) as Record<string, { x: number; y: number }>;
  const drawnIds = [...plan.at.keys()];
  const onPicture = drawnIds.length > 1 && drawnIds.every((id) => reference[id]);
  // A photographed picture is drawn whole under the map (IMPORT-17): its corners count too.
  const corners = picture?.photo ? [{ x: 0, y: 0 }, picture.photo] : [];
  const spots = onPicture ? [...drawnIds.map((id) => reference[id] as { x: number; y: number }), ...Object.values(picture?.points ?? {}), ...corners] : [];
  const minX = Math.min(...spots.map((spot) => spot.x));
  const minY = Math.min(...spots.map((spot) => spot.y));
  const at = (spot: { x: number; y: number }): [number, number] => [margin.x + (spot.x - minX) * PICTURE_SCALE, margin.y + (spot.y - minY) * PICTURE_SCALE];
  const width = onPicture ? Math.max(...spots.map((spot) => at(spot)[0])) + margin.x : (plan.width - 1) * STEP_X + margin.x * 2;
  const height = onPicture ? Math.max(...spots.map((spot) => at(spot)[1])) + margin.y : (plan.height - 1) * STEP_Y + margin.y * 2;
  const scale = room > 0 ? Math.min(1, Math.max(0.78, room / width)) : 1;
  const places = new Map(pkg.places.map((place) => [place.id, place]));
  const point = (id: string): [number, number] => {
    if (onPicture) return at(reference[id] as { x: number; y: number });
    const [column, row] = plan.at.get(id) ?? [0, 0];
    return [margin.x + (column - plan.left) * STEP_X, margin.y + (row - plan.top) * STEP_Y];
  };
  const curve = (a: string, b: string) => {
    const [ax, ay] = point(a);
    const [bx, by] = point(b);
    if (onPicture || ay === by || ax === bx) return `M${ax},${ay} L${bx},${by}`;
    const middle = (ax + bx) / 2;
    return `M${ax},${ay} C${middle},${ay} ${middle},${by} ${bx},${by}`;
  };
  const shown = links(pkg).filter((link) => plan.at.has(link.a) && plan.at.has(link.b));
  const lengthOf = (section: string) => lengths.find((found) => found.section === section)?.length;
  // On the picture, halts can stand close together: every other name goes above its ring.
  const above = new Set<string>();
  if (onPicture) {
    const halts = pkg.places.filter((place) => place.kind === "halt" && plan.at.has(place.id)).sort((a, b) => point(a.id)[0] - point(b.id)[0]);
    halts.forEach((halt, index) => {
      const before = halts.slice(0, index).reverse().find((other) => Math.abs(point(other.id)[1] - point(halt.id)[1]) < 8);
      if (before && point(halt.id)[0] - point(before.id)[0] < 80 && !above.has(before.id)) above.add(halt.id);
    });
  }
  return (
    <div ref={host}>
      <svg className="karta" viewBox={`0 0 ${width} ${height}`} width={Math.round(width * scale)} height={Math.round(height * scale)} role="group" aria-label="Banan">
        {onPicture && picture && (
          <g className="banbild" id="picture" aria-hidden="true">
            {picture.photo && photo && (
              <image href={photo} x={at({ x: 0, y: 0 })[0]} y={at({ x: 0, y: 0 })[1]} width={picture.photo.x * PICTURE_SCALE} height={picture.photo.y * PICTURE_SCALE} preserveAspectRatio="none" opacity={0.5} id="photo" />
            )}
            {(picture.links ?? []).map((link) => {
              const a = picture.points?.[link.a];
              const b = picture.points?.[link.b];
              if (!a || !b) return null;
              const [ax, ay] = at(a);
              const [bx, by] = at(b);
              return <line key={`${link.a}|${link.b}`} x1={ax} y1={ay} x2={bx} y2={by} className={link.double ? "dubbel" : undefined} />;
            })}
            {Object.entries(picture.points ?? {}).map(([code, spot]) => {
              const [x, y] = at(spot);
              return <circle key={code} cx={x} cy={y} r={5} />;
            })}
          </g>
        )}
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
                <title>{section ? `${places.get(section.place_a)?.name} – ${places.get(section.place_b)?.name}` + (lengthOf(section.id) ? ` · ${modelLength(lengthOf(section.id) ?? 0)}` : "") : "Spår utan klarering i planen"}</title>
              </g>
            );
          })}
        </g>
        <g className="delar">
          {pkg.places
            .filter((place) => place.part_of && plan.at.has(place.id) && plan.at.has(place.part_of))
            .map((place) => {
              const [ax, ay] = point(place.part_of as string);
              const [bx, by] = point(place.id);
              return <line key={`${place.id}-del`} x1={ax} y1={ay} x2={bx} y2={by} className="del" aria-hidden="true" />;
            })}
        </g>
        <g className="etiketter">
          {shown.map((link) => {
            const section = link.section;
            const parts = section?.parts ?? [];
            // The section's name once, at its middle part.
            if (!section || !sectionLabel(section) || !link.part || parts.indexOf(link.part) !== Math.floor((parts.length - 1) / 2)) return null;
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
              // Fjärrstyrd från sitt fjärrområde (FR49), or from the place an older plan named.
              const remote = remoteFrom(pkg, place, (id) => places.get(id)?.name ?? id);
              const note = partOf(place, (id) => places.get(id)?.name ?? id) ?? (place.kind === "shadow_yard" ? "skuggbangård" : remote ? `fjärrstyrd från ${remote}` : place.kind === "unmanned" ? "obemannad" : null);
              const boxWidth = Math.max(54, place.code.length * 9 + 22);
              return (
                <g
                  key={place.id}
                  className={`plats ${place.kind}${place.part_of ? " del" : ""}${chosen ? " vald" : ""}`}
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
                      <text x={x} y={above.has(place.id) ? y - 16 : y + 27} className="namn under">
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
            const name = fact.ref.slice(ref_.length + 1);
            const field = fact.ref === ref_ ? "" : ` (${FIELDS[name] ?? name})`;
            return (
              <li key={`${fact.ref}-${index}`}>
                <span className={`kalla ${kind}`.trim()}>{label}</span>
                <span>
                  {origin.at + field}
                  {fact.note && index === 0 && <span className="liten block">{fact.note}</span>}
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

/** What a field of a fact is about, as Varifrån says it. */
const FIELDS: Record<string, string> = { length: "längd", modules: "moduler", phone: "telefon", tracks: "spår", station: "station" };

type Save = (change: Changes["changes"][number] | Changes["changes"], text: string) => void;

/** Bekräfta (IMPORT-04): what is osäker about the chosen thing, approved as it is. */
function Confirm({ refs, what, onSave }: { refs: string[]; what: string; onSave: Save }) {
  if (!refs.length) return null;
  return (
    <div className="bekrafta">
      <p className="liten">{`${what} är härledd och osäker. Stämmer den med banan?`}</p>
      <button type="button" id="confirm-choice" className="sekundar" onClick={() => onSave(refs.map((ref) => ({ confirm: ref })), `${what} är bekräftad.`)}>
        Bekräfta
      </button>
    </div>
  );
}

function SectionChoice({ admin, draft, pkg, section, facts, unsure, onSave }: { admin: boolean; draft: Draft; pkg: Package; section: Section; facts: Facts; unsure: Set<string>; onSave: Save }) {
  const parts = section.parts ?? [];
  const between = parts.slice(0, -1).map((part) => {
    const place = pkg.places.find((item) => item.id === part.to_place);
    return place ? `${place.name} (${(KINDS[place.kind] ?? place.kind).toLowerCase()})` : part.to_place;
  });
  const base = MODES[draft.meet.clearance_mode] ?? draft.meet.clearance_mode;
  const fact = facts.byRef.get(`section:${section.id}`);
  const name = `${nameOf(pkg, section.place_a)} – ${nameOf(pkg, section.place_b)}`;
  // Längden i Bana (CAD-11): from CAD's assembly, with its origin and certainty.
  const length = (draft.lengths ?? []).find((found) => found.section === section.id);
  const lengthFact = facts.byRef.get(`section:${section.id}.length`);
  return (
    <>
      <header>
        <span className="overrubrik">Vald sträcka</span>
        {fact && <span className={`pill ${fact.certainty}`}>{CERTAINTY[fact.certainty]}</span>}
      </header>
      <h2>{sectionLabel(section) ? `${sectionLabel(section)} · ${name}` : name}</h2>
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
        <div className="par" id="length">
          <dt>Längd</dt>
          <dd>
            {length ? (
              <>
                <span>{`${modelLength(length.length)} i modellen · ${prototypeLength(length.prototype)} i ${draft.assembly?.scale ?? "förebilden"}`}</span>
                {lengthFact && <span className={`pill ${lengthFact.certainty}`}>{CERTAINTY[lengthFact.certainty]}</span>}
                <span className="liten block">{`Längs spåret ur anläggningen ${draft.assembly?.name ?? ""}${length.tracks > 1 ? `, ${plural(length.tracks, "spår", "spår")} bredvid varandra` : ""}.`}</span>
              </>
            ) : draft.assembly ? (
              <span className="liten">Sträckan finns inte i anläggningen från CAD.</span>
            ) : (
              <span className="liten">Lägg till anläggningen från CAD under Data för exakta längder.</span>
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
      {admin && <Confirm refs={[...unsure].filter((ref) => ref === `section:${section.id}` || ref.startsWith(`part:${section.id}.`))} what="Sträckan" onSave={onSave} />}
      {admin && lengthFact?.certainty === "likely" && (
        <div className="bekrafta">
          <p className="liten">Längden kommer ur anläggningen i CAD. Stämmer den med banan på träffen?</p>
          <button type="button" id="confirm-length" className="sekundar" onClick={() => onSave({ confirm: lengthFact.ref }, "Längden är bekräftad.")}>
            Bekräfta längden
          </button>
        </div>
      )}
      <Origins draft={draft} facts={facts} ref_={`section:${section.id}`} />
    </>
  );
}

function PlaceChoice({ admin, draft, pkg, place, facts, unsure, onSave }: { admin: boolean; draft: Draft; pkg: Package; place: Place; facts: Facts; unsure: Set<string>; onSave: Save }) {
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
          <dd>{(KINDS[place.kind] ?? place.kind) + (remoteFrom(pkg, place, (id) => nameOf(pkg, id)) ? `, från ${remoteFrom(pkg, place, (id) => nameOf(pkg, id))}` : "")}</dd>
        </div>
        {place.part_of && (
          <div className="par">
            <dt>Del av</dt>
            <dd>{`${nameOf(pkg, place.part_of)}, egen driftplats som bemannas för sig`}</dd>
          </div>
        )}
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
      {admin && <Confirm refs={[...unsure].filter((ref) => ref === `place:${place.id}` || ref.startsWith(`place:${place.id}.`))} what="Platsen" onSave={onSave} />}
      <Origins draft={draft} facts={facts} ref_={`place:${place.id}`} />
    </>
  );
}

import { Banoversikt, nextHappenings, numbers, trafficOf, type Leg, type Package as HubPackage } from "@trainmeet/hubben";
export { nextHappenings, numbers, type Happening } from "@trainmeet/hubben";
import type { Package, ScreenPicture } from "./api";
import { clockText } from "./Klocka";

// Skärm · Översikt (SKARM-18): the clock, four numbers, Banöversikten smaller, the next four
// things that happen and the trains on the line just now.

type Now = NonNullable<ScreenPicture["now"]>;
const DAYS: Record<string, string> = { mon: "Måndag", tue: "Tisdag", wed: "Onsdag", thu: "Torsdag", fri: "Fredag", sat: "Lördag", sun: "Söndag" };

export function OversiktView({ picture, pkg, fetchedAt, now }: { picture: ScreenPicture; pkg: Package | null; fetchedAt: number; now: number }) {
  const seen = picture.now as Now | null | undefined;
  if (!seen || !pkg) return <p className="laddar">Hämtar träffen …</p>;
  const hub = pkg as unknown as HubPackage;
  const traffic = trafficOf(hub, seen);
  const names = new Map(pkg.places.map((place) => [place.id, place.name]));
  const name = (id: string) => names.get(id) ?? id;
  const sections = new Map((pkg.sections ?? []).map((section) => [section.id, section]));
  const label = (leg: Leg) => (sections.get(leg.section)?.source_ids as Record<string, string> | undefined)?.["planning_json"] ?? leg.section;
  const days = (pkg.meet as { traffic_week?: { days?: number } | null }).traffic_week?.days ?? 1;
  return (
    <section id="overview-view" className="oversikt-vy">
      <div className="oversikt-topp">
        <article className="kort klock-kort">
          <p className="tid-stor">{clockText(picture, fetchedAt, now)}</p>
          <div>
            <h1 id="meet">{picture.meet}</h1>
            <p className={picture.clock.running ? "gar" : "star"}>{picture.clock.running ? `Klockan går · ×${picture.clock.speed}` : "Klockan står still"}</p>
            <p>{`${DAYS[picture.traffic_day] ?? ""} · dag ${picture.clock.game_day} av ${days}`}</p>
          </div>
        </article>
        {numbers(traffic).map(([count, text]) => (
          <article key={text} className="kort tal-kort">
            <p className="tal">{count}</p>
            <p>{text}</p>
          </article>
        ))}
      </div>
      <article className="kort oversikt-bana">
        <h2>
          Banöversikt <span className="liten">{`${traffic.online.length} tåg på linjen`}</span>
        </h2>
        <div className="oversikt-ritning">
          <Banoversikt pkg={hub} now={seen} traffic={traffic} aspect={4.2} />
        </div>
      </article>
      <div className="oversikt-botten">
        <article className="kort lista-kort">
          <h2>
            Nästa händelser <span className="liten">de fyra närmaste</span>
          </h2>
          <ul id="next">
            {nextHappenings(seen, names).map((item) => (
              <li key={`${item.leg.leg}-${item.text}`}>
                <span className="tid-kol">{`${String(Math.floor(item.minute / 60) % 24).padStart(2, "0")}:${String(item.minute % 60).padStart(2, "0")}`}</span>
                <b>{item.number}</b>
                <span className="vad">{item.text}</span>
                <span className={`not ${item.note === "väntar på svar" ? "gul" : ""}`}>{item.note}</span>
              </li>
            ))}
            {!nextHappenings(seen, names).length && <li className="tom">Inget de närmaste timmarna.</li>}
          </ul>
        </article>
        <article className="kort lista-kort">
          <h2>
            På linjen just nu <span className="liten">tåg · sträcka · riktning</span>
          </h2>
          <ul id="online">
            {traffic.online.slice(0, 4).map((leg) => (
              <li key={leg.leg}>
                <b>{leg.train_number}</b>
                <span className="vad">{`${label(leg)} · ${name(leg.from_place)} → ${name(leg.to_place)}`}</span>
                <span className="not">{`ankomst ${leg.arrival ?? "–"}`}</span>
              </li>
            ))}
            {traffic.online.length > 4 && <li className="tom">{`och ${traffic.online.length - 4} till`}</li>}
            {!traffic.online.length && <li className="tom">Inga tåg på linjen.</li>}
          </ul>
        </article>
      </div>
    </section>
  );
}

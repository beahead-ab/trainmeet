import { Banoversikt, between, minutesOf, plural, summary, trafficOf, type Leg, type Package as HubPackage, type Traffic } from "@trainmeet/hubben";
import type { Package, ScreenPicture } from "./api";
import { clockText } from "./Klocka";

// Skärm · Banöversikt (SKARM-21, H47): the meet and what is on the line, the clock top right,
// the line drawn from the package, and below it the trains on the line, cleared and not gone,
// waiting for an answer and ending here.

type Now = NonNullable<ScreenPicture["now"]>;
const SHOWN = 3;
const DAYS: Record<string, string> = { mon: "måndag", tue: "tisdag", wed: "onsdag", thu: "torsdag", fri: "fredag", sat: "lördag", sun: "söndag" };

function Group({ title, legs, line, note, state }: { title: string; legs: Leg[]; line: (leg: Leg) => string; note: (leg: Leg) => string; state: string }) {
  return (
    <section className="remsa-del" aria-label={title}>
      <h2>{title}</h2>
      <ul>
        {legs.slice(0, SHOWN).map((leg) => (
          <li key={leg.leg}>
            <span className={`bricka ${state}`}>{leg.train_number}</span>
            <span>
              <b>{line(leg)}</b>
              <span className="liten">{note(leg)}</span>
            </span>
          </li>
        ))}
        {legs.length > SHOWN && <li className="liten">{`och ${legs.length - SHOWN} till`}</li>}
        {!legs.length && <li className="tom">Inga.</li>}
      </ul>
    </section>
  );
}

export function BanaView({ picture, pkg, fetchedAt, now }: { picture: ScreenPicture; pkg: Package | null; fetchedAt: number; now: number }) {
  const seen = picture.now as Now | null | undefined;
  if (!seen || !pkg) return <p className="laddar">Hämtar banan …</p>;
  const hub = pkg as unknown as HubPackage;
  const traffic: Traffic = trafficOf(hub, seen);
  const names = new Map(pkg.places.map((place) => [place.id, place.name]));
  const name = (id: string) => names.get(id) ?? id;
  const clock = minutesOf(seen.clock.time) ?? 0;
  const asked = new Map(seen.clearances.map((clearance) => [clearance.clearance_id, clearance]));
  const way = (leg: Leg) => `${name(leg.from_place)} → ${name(leg.to_place)}`;
  return (
    <section id="tracks-view" className="bana-vy">
      <header className="bana-rubrik">
        <div>
          <h1 id="meet">{picture.meet}</h1>
          <p id="summary">{`Banöversikt · ${summary(traffic)}`}</p>
        </div>
        <div className="bana-klocka">
          <p className="tid-liten">{clockText(picture, fetchedAt, now)}</p>
          <p className={picture.clock.running ? "gar" : "star"}>{`${picture.clock.running ? "går" : "står"} · ×${picture.clock.speed} · ${DAYS[picture.traffic_day] ?? ""} dag ${picture.clock.game_day}`}</p>
        </div>
      </header>
      <div className="bana-ritning">
        <Banoversikt pkg={hub} now={seen} traffic={traffic} />
      </div>
      <div className="remsa">
        <Group title="På linjen" state="belagt" legs={traffic.online} line={way} note={(leg) => `ankomst ${leg.arrival ?? "–"}${leg.track ? ` · spår ${leg.track}` : ""}`} />
        <Group title="Klart, inte avgått" state="klar" legs={traffic.cleared} line={way} note={(leg) => `avgång ${leg.departure ?? "–"}`} />
        <Group
          title="Väntar på svar"
          state="begard"
          legs={traffic.requested}
          line={way}
          note={(leg) => {
            const clearance = leg.clearance_id ? asked.get(leg.clearance_id) : undefined;
            const waited = clearance ? between(minutesOf(clearance.requested_at) ?? clock, clock) : null;
            return clearance ? `begärt ${clearance.requested_at}${waited !== null && waited > 0 ? ` · väntat ${plural(waited, "min", "min")}` : ""}${clearance.reminders ? " · påmint" : ""}` : "begärt";
          }}
        />
        <Group title="Slutar här" state="slutar" legs={traffic.ends} line={(leg) => `${name(leg.to_place)}${leg.track ? ` spår ${leg.track}` : ""}`} note={(leg) => `ankom ${leg.arrival ?? "–"}`} />
      </div>
      <footer className="bana-fot">
        <span>Utan detektering följer tågnumret knapparna: startspåret, sträckan vid avgång och målspåret vid ankomst.</span>
        <span className="teckning klar">klart</span>
        <span className="teckning belagt">belagt</span>
        <span className="teckning begard">begärt</span>
        <span className="teckning kommer">på väg hit</span>
        <span className="teckning slutar">slutar här</span>
      </footer>
    </section>
  );
}

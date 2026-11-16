import type { ScreenPicture } from "./api";

// Klockskärmen (SKARM-23, H74): two built-in styles, analog and digital, drawn for 1920 × 1080.
// The meet clock runs on at its speed between the hub's answers. When it stands still, that is
// said over the lower half. Own dials come as clock packages later (ärende 64).

const DAYS: Record<ScreenPicture["traffic_day"], string> = {
  mon: "Måndag",
  tue: "Tisdag",
  wed: "Onsdag",
  thu: "Torsdag",
  fri: "Fredag",
  sat: "Lördag",
  sun: "Söndag",
};

/** The meet clock in seconds now: the hub's time, run on at its speed since it was fetched. */
export function clockSeconds(picture: ScreenPicture, fetchedAt: number, now: number): number {
  const { clock } = picture;
  const passed = clock.running ? ((now - fetchedAt) / 1000) * clock.speed : 0;
  return (clock.seconds + passed) % 86400;
}

/** The meet clock now as TT:MM. */
export function clockText(picture: ScreenPicture, fetchedAt: number, now: number): string {
  const minutes = Math.floor(clockSeconds(picture, fetchedAt, now) / 60) % 1440;
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

/** Where the hands point, in degrees from twelve. */
export function hands(seconds: number): { hour: number; minute: number; second: number } {
  return { hour: ((seconds / 3600) % 12) * 30, minute: ((seconds / 60) % 60) * 6, second: (Math.floor(seconds) % 60) * 6 };
}

const R = 470;
const C = 500;
const at = (angle: number, radius: number): [number, number] => [C + radius * Math.sin((angle * Math.PI) / 180), C - radius * Math.cos((angle * Math.PI) / 180)];

function Face({ seconds }: { seconds: number }) {
  const { hour, minute, second } = hands(seconds);
  const hand = (angle: number, length: number, back: number) => {
    const [x1, y1] = at(angle + 180, back);
    const [x2, y2] = at(angle, length);
    return { x1, y1, x2, y2 };
  };
  return (
    <svg className="urtavla" viewBox="0 0 1000 1000" role="img" aria-label={`Klockan är ${Math.floor(seconds / 3600) % 24} och ${Math.floor(seconds / 60) % 60}`}>
      <circle cx={C} cy={C} r={R} className="tavla" />
      {Array.from({ length: 60 }, (_, i) => {
        const long = i % 5 === 0;
        const [x1, y1] = at(i * 6, R - (long ? 70 : 34));
        const [x2, y2] = at(i * 6, R - 14);
        return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} className={long ? "streck langt" : "streck"} />;
      })}
      {Array.from({ length: 12 }, (_, i) => {
        const [x, y] = at((i + 1) * 30, R - 150);
        return (
          <text key={i} x={x} y={y} className="siffra" textAnchor="middle" dominantBaseline="central">
            {i + 1}
          </text>
        );
      })}
      <line {...hand(hour, 250, 40)} className="visare timme" />
      <line {...hand(minute, 400, 40)} className="visare minut" />
      <line {...hand(second, 420, 90)} className="visare sekund" />
      <circle cx={C} cy={C} r={16} className="nav" />
      <circle cx={C} cy={C} r={6} className="nav-mitt" />
    </svg>
  );
}

/** The clock view: the meet and its day above, the clock in the middle. */
export function Klocka({ picture, fetchedAt, now }: { picture: ScreenPicture; fetchedAt: number; now: number }) {
  const seconds = clockSeconds(picture, fetchedAt, now);
  const digital = picture.view === "clock_digital";
  const { clock } = picture;
  return (
    <section id="clock-view" className={`klocka ${clock.running ? "gar" : "star"} ${digital ? "digital" : "analog"}`}>
      <header className="klocka-rubrik">
        <h1 id="meet">{picture.meet}</h1>
        <p id="day">{`${DAYS[picture.traffic_day]} · dag ${clock.game_day} · ×${clock.speed}`}</p>
      </header>
      {digital ? (
        <p id="time" className="tid">
          {clockText(picture, fetchedAt, now)}
        </p>
      ) : (
        <Face seconds={seconds} />
      )}
      <p id="state" className={clock.running ? "lage" : "lage stopp"}>
        {clock.running ? `Klockan går i ${clock.speed}×` : "Klockan står still"}
      </p>
    </section>
  );
}

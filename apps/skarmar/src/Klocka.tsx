import type { ScreenPicture } from "./api";

// Klockskärmen (SKARM-23, H74, H75): analog, digital, or the meet's own face custom:<id>.
// The meet clock runs on at its speed between the hub's answers. When it stands still, that is
// said over the lower half. A clock pack is pictures and clock.json: the layers are stacked
// and the hands turn about the centre, in light and in dark (F13, ärende 64).

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

export type HandMotion = {
  hour?: string;
  minute?: string;
  minute_bounce?: boolean;
  second?: string;
  sweep_seconds?: number;
};

/** A clock pack's layers, as addresses the screen has already fetched. */
export type ClockFace = {
  id: string;
  name: string;
  motion: HandMotion;
  layers: Record<string, string>;
  dark: Record<string, string>;
};

/** Where a clock pack's hands point, in degrees from twelve (clock.json motion). */
export function handAngles(seconds: number, motion: HandMotion = {}, bounce = 0): { hour: number; minute: number; second: number } {
  const day = ((seconds % 86400) + 86400) % 86400;
  const hour = Math.floor(day / 3600) % 12;
  const minute = Math.floor((day % 3600) / 60);
  const second = day % 60;
  const hourAngle = motion.hour === "minute" ? (hour + minute / 60) * 30 : (hour + minute / 60 + second / 3600) * 30;
  const minuteAngle = motion.minute === "jump" ? minute * 6 + bounce : (minute + second / 60) * 6;
  const sweep = Math.min(second / (motion.sweep_seconds ?? 60), 1) * 360;
  const secondAngle = motion.second === "sweep" ? sweep : motion.second === "tick" ? Math.floor(second) * 6 : second * 6;
  return { hour: hourAngle, minute: minuteAngle, second: secondAngle };
}

/** Where the built-in hands point, in degrees from twelve. */
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

function layerOf(face: ClockFace, name: string, theme: "morkt" | "ljust"): string {
  return (theme === "morkt" && face.dark[name]) || face.layers[name] || "";
}

/** The meet's own face: layers stacked, hands turned about the centre. About 90 % of the short side. */
function OwnFace({ face, seconds, theme }: { face: ClockFace; seconds: number; theme: "morkt" | "ljust" }) {
  const { hour, minute, second } = handAngles(seconds, face.motion);
  const image = (name: string, angle?: number) => {
    const href = layerOf(face, name, theme);
    if (!href) return null;
    const turn = angle === undefined ? undefined : `rotate(${angle} 100 100)`;
    return <image key={name} href={href} x="0" y="0" width="200" height="200" transform={turn} />;
  };
  return (
    <svg className="urtavla urtavla-egen" viewBox="0 0 200 200" role="img" aria-label={face.name} data-face={face.id} data-tema={theme}>
      {image("dial")}
      {image("hour", hour)}
      {image("minute", minute)}
      {image("second", second)}
      {image("top")}
    </svg>
  );
}

/** The clock view: the meet and its day above, the clock in the middle. */
export function Klocka({
  picture,
  fetchedAt,
  now,
  face = null,
  theme = "morkt",
}: {
  picture: ScreenPicture;
  fetchedAt: number;
  now: number;
  face?: ClockFace | null;
  theme?: "morkt" | "ljust";
}) {
  const seconds = clockSeconds(picture, fetchedAt, now);
  const digital = picture.view === "clock_digital";
  const own = !digital && face !== null;
  const { clock } = picture;
  return (
    <section id="clock-view" className={`klocka ${theme} ${clock.running ? "gar" : "star"} ${digital ? "digital" : own ? "egen" : "analog"}`}>
      <header className="klocka-rubrik">
        <h1 id="meet">{picture.meet}</h1>
        <p id="day">{`${DAYS[picture.traffic_day]} · dag ${clock.game_day} · ×${clock.speed}`}</p>
      </header>
      {digital ? (
        <p id="time" className="tid">
          {clockText(picture, fetchedAt, now)}
        </p>
      ) : own && face ? (
        <OwnFace face={face} seconds={seconds} theme={theme} />
      ) : (
        <Face seconds={seconds} />
      )}
      <p id="state" className={clock.running ? "lage" : "lage stopp"}>
        {clock.running ? `Klockan går i ${clock.speed}×` : "Klockan står still"}
      </p>
      {picture.share && <QrCorner share={picture.share} />}
    </section>
  );
}

/** QR-koderna i hörnet (SKARM-18): 1 · Wi-Fi and 2 · Träffen, as in Dela träffen. Without the
 * Wi-Fi, one code: everything about the meet. */
export function QrCorner({ share }: { share: NonNullable<ScreenPicture["share"]> }) {
  const meet = `/api/deltagare/traffen.svg?address=${encodeURIComponent(share.link)}`;
  return (
    <aside id="qr-koder" className="qr-horn" aria-label="QR-koder">
      {share.wifi ? (
        <>
          <figure>
            <img src="/api/deltagare/wifi.svg" alt="Träffens Wi-Fi" />
            <figcaption>1 · Wi-Fi</figcaption>
          </figure>
          <figure>
            <img src={meet} alt="Träffen" />
            <figcaption>2 · Träffen</figcaption>
          </figure>
        </>
      ) : (
        <figure>
          <img src={meet} alt="Träffen" />
          <figcaption>Skanna – allt om träffen</figcaption>
        </figure>
      )}
    </aside>
  );
}

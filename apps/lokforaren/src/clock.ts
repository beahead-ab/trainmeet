// The meet clock in the phone (LOK-12): always Drift's. The hub says the clock's seconds, its
// speed and whether it runs; the phone counts on from there with its own monotonic time since
// the answer, multiplied by Drift's speed. The phone's own time of day (Date) is never used.
// Without contact the clock stands still where it was, as in the old Lokföraren.
import type { Clock } from "./api";

export const DAY = 86400;
/** Without a word from the hub for this long, the clock is lost and stands still. */
export const LOST_AFTER_MS = 30_000;
/** A reading this little behind the phone's estimate does not turn the clock back. */
const SMALL_STEP_BACK = 3;

export type ClockMode = "none" | "running" | "stopped" | "lost";

type Anchor = { seconds: number; at: number; speed: number; running: boolean; gameDay: number };

export class MeetClock {
  private anchor: Anchor | null = null;
  private heard = 0;

  /** monotonic: milliseconds that only go forward (performance.now), never the time of day. */
  constructor(private readonly monotonic: () => number = () => performance.now()) {}

  /** Drift's clock as the hub read it, in /clock, /me or /korplan. */
  accept(clock: Clock): void {
    const at = this.monotonic();
    const current = this.anchor && this.mode() !== "lost" ? this.estimate(at) : null;
    let seconds = clock.seconds;
    const same = this.anchor && this.anchor.running === clock.running && this.anchor.speed === clock.speed && this.anchor.gameDay === clock.game_day;
    if (same && clock.running && current !== null && seconds < current && current - seconds < SMALL_STEP_BACK) seconds = current;
    this.anchor = { seconds, at, speed: clock.speed, running: clock.running, gameDay: clock.game_day };
    this.heard = at;
  }

  private estimate(at: number): number {
    const anchor = this.anchor!;
    if (!anchor.running) return anchor.seconds;
    return anchor.seconds + (Math.max(0, at - anchor.at) / 1000) * anchor.speed;
  }

  mode(): ClockMode {
    if (!this.anchor) return "none";
    if (this.monotonic() - this.heard > LOST_AFTER_MS) return "lost";
    return this.anchor.running ? "running" : "stopped";
  }

  /** The meet clock's seconds since the game day's midnight (may pass 24 h), or null. Lost, it
   * stands where it was when the contact went. */
  seconds(): number | null {
    if (!this.anchor) return null;
    const now = this.monotonic();
    return this.estimate(Math.min(now, this.heard + LOST_AFTER_MS));
  }

  speed(): number {
    return this.anchor?.speed ?? 1;
  }

  running(): boolean {
    return this.mode() === "running";
  }

  gameDay(): number | null {
    return this.anchor?.gameDay ?? null;
  }
}

const pad = (value: number) => String(value).padStart(2, "0");

/** 05:26:40, or 05:26 without the seconds. */
export function clockText(seconds: number | null, withSeconds = true): string {
  if (seconds === null) return withSeconds ? "--:--:--" : "--:--";
  const whole = Math.floor(seconds);
  const day = ((whole % DAY) + DAY) % DAY;
  const text = `${pad(Math.floor(day / 3600))}:${pad(Math.floor(day / 60) % 60)}`;
  return withSeconds ? `${text}:${pad(day % 60)}` : text;
}

/** "HH:MM" as seconds into the day, or null. */
export function timeSeconds(value: string | null | undefined): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value ?? "");
  return match ? Number(match[1]) * 3600 + Number(match[2]) * 60 : null;
}

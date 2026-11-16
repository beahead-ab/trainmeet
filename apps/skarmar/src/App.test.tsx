import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ScreenPicture } from "./api";
import { clockText, Screen } from "./App";
import { clockSeconds, hands } from "./Klocka";

const picture = (change: Partial<ScreenPicture> = {}): ScreenPicture => ({
  name: "TV vid entrén",
  view: "clock",
  meet: "Provbanan",
  traffic_day: "mon",
  clock: { time: "06:00", seconds: 6 * 3600, running: true, speed: 4, game_day: 1 },
  ...change,
});

describe("a meet screen (SKARM-14)", () => {
  it("joins with the meet's code, which a link can fill in", () => {
    const html = renderToStaticMarkup(<Screen picture={null} fetchedAt={0} now={0} message="" code="482915" />);
    expect(html).toContain('id="login-form"');
    expect(html).toContain('pattern="[0-9]{6}"');
    expect(html).toContain('value="482915"');
  });

  it("waits under Väntar until the dispatcher gives it a view", () => {
    const html = renderToStaticMarkup(<Screen picture={picture({ view: null })} fetchedAt={0} now={0} message="" code="" />);
    expect(html).toContain("Väntar på en vy");
    expect(html).toContain("TV vid entrén");
  });

  it("shows the meet clock, analog or digital, running on at its speed between the hub's answers (SKARM-23)", () => {
    const html = renderToStaticMarkup(<Screen picture={picture()} fetchedAt={0} now={0} message="" code="" />);
    expect(html).toContain('id="clock-view" class="klocka gar analog"');
    expect(html).toContain('<h1 id="meet">Provbanan</h1><p id="day">Måndag · dag 1 · ×4</p>');
    expect(html).toContain('class="urtavla"');
    expect(html).toContain("Klockan går i 4×");
    const digital = renderToStaticMarkup(<Screen picture={picture({ view: "clock_digital" })} fetchedAt={0} now={0} message="" code="" />);
    expect(digital).toContain('<p id="time" class="tid">06:00</p>');
    expect(digital).not.toContain("urtavla");
    expect(hands(3 * 3600 + 30 * 60)).toEqual({ hour: 105, minute: 180, second: 0 });
    expect(clockSeconds(picture(), 0, 2_500)).toBe(6 * 3600 + 10);
    expect(clockText(picture(), 0, 30_000)).toBe("06:02"); // 30 s at 4× is two minutes
    expect(clockText(picture({ clock: { ...picture().clock, running: false } }), 0, 30_000)).toBe("06:00");
    expect(clockText(picture({ clock: { ...picture().clock, seconds: 23 * 3600 + 59 * 60 } }), 0, 60_000)).toBe("00:03");
  });

  it("says when the clock stands still", () => {
    const html = renderToStaticMarkup(<Screen picture={picture({ clock: { ...picture().clock, running: false } })} fetchedAt={0} now={0} message="" code="" />);
    expect(html).toContain("klocka star");
    expect(html).toContain('<p id="state" class="lage stopp">Klockan står still</p>');
  });
});

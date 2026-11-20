// Fotohjälpen (#90): the camera view's checks on synthetic frames, a module on a floor.
import { describe, expect, it } from "vitest";
import {
  analysisSize,
  clipped,
  finalWay,
  findQuad,
  frameCheck,
  grayOf,
  hold,
  motion,
  sharpness,
  shadowRatio,
  tiltOf,
  trackSharpness,
  verdict,
  type Frame,
  type Point,
  type Quad,
  type Seen,
} from "./fotohjalp";

/** A deterministic noise in 0..1. */
function noise(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

function inside(quad: Point[], x: number, y: number): boolean {
  let sign = 0;
  for (let i = 0; i < 4; i += 1) {
    const a = quad[i] as Point;
    const b = quad[(i + 1) % 4] as Point;
    const c = (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]);
    if (c === 0) continue;
    if (!sign) sign = Math.sign(c);
    else if (Math.sign(c) !== sign) return false;
  }
  return true;
}

type Scene = { width?: number; height?: number; corners: Point[]; shadow?: boolean; glare?: boolean; seed?: number };

/** A wooden floor with a module on it: green scenery, grey ballast and dark rails along it. */
function scene({ width = 240, height = 180, corners, shadow = false, glare = false, seed = 3 }: Scene): Frame {
  const data = new Uint8ClampedArray(width * height * 4);
  const random = noise(seed);
  const [a, b, , d] = corners as [Point, Point, Point, Point];
  const along: Point = [b[0] - a[0], b[1] - a[1]];
  const across: Point = [d[0] - a[0], d[1] - a[1]];
  const acrossLength = Math.hypot(...across);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const p = (y * width + x) * 4;
      const grain = 12 * Math.sin(y * 0.9 + x * 0.05) + 16 * (random() - 0.5);
      let rgb = [150 + grain, 105 + grain, 70 + grain];
      if (inside(corners, x + 0.5, y + 0.5)) {
        const v = ((x - a[0]) * across[0] + (y - a[1]) * across[1]) / (acrossLength * acrossLength);
        const u = ((x - a[0]) * along[0] + (y - a[1]) * along[1]) / Math.hypot(...along) ** 2;
        const speck = 14 * (random() - 0.5);
        rgb = [95 + speck, 140 + speck, 80 + speck];
        for (const track of [0.3, 0.42]) {
          if (Math.abs(v - track) < 0.05) rgb = [150 + speck, 150 + speck, 145 + speck];
          if (Math.abs(Math.abs(v - track) - 0.025) < 0.006) rgb = [55, 50, 45];
        }
        if (shadow && u > 0.5) rgb = rgb.map((c) => c * 0.35);
        if (glare && u < 0.25) rgb = [255, 255, 255];
      }
      data[p] = rgb[0] ?? 0;
      data[p + 1] = rgb[1] ?? 0;
      data[p + 2] = rgb[2] ?? 0;
      data[p + 3] = 255;
    }
  }
  return { data, width, height };
}

/** A box blur, as a phone that moves or misses the focus gives it. */
function blurred(frame: Frame, radius = 2): Frame {
  const { width, height, data } = frame;
  const out = new Uint8ClampedArray(data.length);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      for (let c = 0; c < 4; c += 1) {
        let sum = 0;
        let n = 0;
        for (let dy = -radius; dy <= radius; dy += 1) {
          for (let dx = -radius; dx <= radius; dx += 1) {
            const xx = Math.min(width - 1, Math.max(0, x + dx));
            const yy = Math.min(height - 1, Math.max(0, y + dy));
            sum += data[(yy * width + xx) * 4 + c] ?? 0;
            n += 1;
          }
        }
        out[(y * width + x) * 4 + c] = sum / n;
      }
    }
  }
  return { width, height, data: out };
}

/** A module turned 8° and seen a little from the side, filling most of the frame. */
const MODULE: Point[] = [
  [20, 46],
  [221, 31],
  [227, 134],
  [16, 146],
];

function near(found: Quad | null, truth: Point[], tolerance: number): void {
  expect(found).not.toBeNull();
  (found as Quad).forEach((p, i) => {
    const t = truth[i] as Point;
    expect(Math.hypot(p[0] - t[0], p[1] - t[1])).toBeLessThan(tolerance);
  });
}

describe("Ram: the module's corners in the frame", () => {
  it("finds the four corners of a turned module on a floor, clockwise from the top left", () => {
    const frame = scene({ corners: MODULE });
    near(findQuad(frame), MODULE, 3);
  });

  it("finds them with a shadow over half the module", () => {
    near(findQuad(scene({ corners: MODULE, shadow: true })), MODULE, 4);
  });

  it("finds nothing on a bare floor", () => {
    expect(
      findQuad(
        scene({
          corners: [
            [0, 0],
            [0, 0],
            [0, 0],
            [0, 0],
          ],
        }),
      ),
    ).toBeNull();
  });

  it("is green when the module is inside with a margin, fills 80 % and lies in the middle", () => {
    const check = frameCheck(findQuad(scene({ corners: MODULE })) as Quad, 240, 180);
    expect(check.inside).toBe(true);
    expect(check.fill).toBeGreaterThan(0.8);
    expect(check.offCentre).toBeLessThan(0.15);
  });

  it("says when the module is small, at the side, or over the edge", () => {
    const small: Quad = [
      [80, 70],
      [160, 70],
      [160, 110],
      [80, 110],
    ];
    expect(frameCheck(small, 240, 180).fill).toBeCloseTo(80 / 240, 2);
    const aside: Quad = [
      [130, 10],
      [238, 10],
      [238, 60],
      [130, 60],
    ];
    expect(frameCheck(aside, 240, 180).offCentre).toBeGreaterThan(0.15);
    const over: Quad = [
      [-5, 40],
      [235, 40],
      [235, 140],
      [-5, 140],
    ];
    expect(frameCheck(over, 240, 180).inside).toBe(false);
  });

  it("measures a module turned 90° against the frame's height", () => {
    const upright: Quad = [
      [100, 5],
      [150, 5],
      [150, 175],
      [100, 175],
    ];
    expect(frameCheck(upright, 240, 180).fill).toBeCloseTo(170 / 180, 2);
  });
});

describe("Skärpa, ljus och stillhet", () => {
  it("a blurred frame is less sharp than the same frame in focus", () => {
    const sharp = scene({ corners: MODULE });
    const soft = blurred(sharp);
    const s1 = sharpness(grayOf(sharp), 240, 180);
    const s2 = sharpness(grayOf(soft), 240, 180);
    expect(s1).toBeGreaterThan(3 * s2);
    // Against the best of the last seconds: the blurred frame is not sharp, the sharp one is.
    let track = trackSharpness({ best: 0, at: 0 }, s1, 0).track;
    expect(trackSharpness(track, s2, 100).sharp).toBe(false);
    track = trackSharpness(track, s2, 100).track;
    expect(trackSharpness(track, s1 * 0.9, 200).sharp).toBe(true);
    // The best is forgotten after a while, so a duller scene can be sharp in its turn.
    expect(trackSharpness(track, s2, 5000).sharp).toBe(s2 >= 12);
  });

  it("counts clipped highlights inside the module", () => {
    const quad = MODULE as Quad;
    expect(clipped(scene({ corners: MODULE }), quad)).toBe(0);
    expect(clipped(scene({ corners: MODULE, glare: true }), quad)).toBeGreaterThan(0.15);
  });

  it("sees a hard shadow edge across the module, and not even light", () => {
    const quad = MODULE as Quad;
    const even = scene({ corners: MODULE });
    const shaded = scene({ corners: MODULE, shadow: true });
    expect(shadowRatio(even, quad)).toBeGreaterThan(0.55);
    expect(shadowRatio(shaded, quad)).toBeLessThan(0.55);
  });

  it("stillness is the frames' mean difference", () => {
    const a = grayOf(scene({ corners: MODULE, seed: 3 }));
    const moved = grayOf(scene({ corners: MODULE.map(([x, y]) => [x + 6, y + 4] as Point), seed: 3 }));
    expect(motion(null, a)).toBe(Infinity);
    expect(motion(a, a)).toBe(0);
    expect(motion(a, moved)).toBeGreaterThan(6);
  });
});

describe("Vinkel, all green and the automatic photo", () => {
  it("the tilt from DeviceOrientation is 0 flat and grows either way", () => {
    expect(tiltOf(0, 0)).toBe(0);
    expect(tiltOf(20, 0)).toBeCloseTo(20, 5);
    expect(tiltOf(0, -15)).toBeCloseTo(15, 5);
    expect(tiltOf(15, 15)).toBeGreaterThan(20);
  });

  const good: Seen = {
    quad: MODULE as Quad,
    check: { inside: true, fill: 0.86, offCentre: 0.02 },
    tilt: 4,
    sharp: true,
    clipped: 0,
    shadow: 0.9,
    motion: 1,
  };

  it("is green only when the frame, the level, the focus, the light and the stillness are", () => {
    expect(verdict(good).green).toBe(true);
    expect(verdict(good).advice).toMatch(/bilden tas av sig själv/);
    const cases: [Partial<Seen>, RegExp][] = [
      [{ quad: null, check: null }, /Lägg modulen på golvet och stå över mitten/],
      [{ check: { inside: false, fill: 1.1, offCentre: 0 } }, /fota i delar/],
      [{ check: { inside: true, fill: 0.7, offCentre: 0 } }, /minst 80 %/],
      [{ check: { inside: true, fill: 0.9, offCentre: 0.3 } }, /mitt/],
      [{ tilt: 25 }, /25° snett/],
      [{ motion: 20 }, /stilla/],
      [{ sharp: false }, /suddig/],
      [{ clipped: 0.1 }, /bländar/],
      [{ shadow: 0.3 }, /skugga/],
    ];
    for (const [change, advice] of cases) {
      const said = verdict({ ...good, ...change });
      expect(said.green).toBe(false);
      expect(said.advice).toMatch(advice);
    }
    // Exactly 20° is still green; without a sensor the level does not stop the photo.
    expect(verdict({ ...good, tilt: 20 }).green).toBe(true);
    expect(verdict({ ...good, tilt: null }).lights.vinkel).toBe("unknown");
    expect(verdict({ ...good, tilt: null }).green).toBe(true);
    // Not yet turned on (iOS asks first): it holds the photo until the owner taps.
    const off = verdict({ ...good, tilt: null, levelOff: true });
    expect(off.green).toBe(false);
    expect(off.advice).toMatch(/Slå på vattenpasset/);
  });

  it("takes the photo after everything has been green for 800 ms, once, and starts over on a red", () => {
    let state = { since: null as number | null, fired: false };
    let step = hold(state, true, 1000);
    expect(step.fire).toBe(false);
    state = step.state;
    step = hold(state, true, 1500);
    expect(step.progress).toBeCloseTo(500 / 800);
    state = hold(state, false, 1600).state;
    expect(state.since).toBeNull();
    state = hold(state, true, 1700).state;
    step = hold(state, true, 2400);
    expect(step.fire).toBe(false);
    step = hold(step.state, true, 2500);
    expect(step.fire).toBe(true);
    expect(hold(step.state, true, 2600).fire).toBe(false);
  });

  it("takes the final photo with ImageCapture, else from a large stream, else with the phone's camera", () => {
    expect(finalWay(1920, 1080, true)).toBe("takePhoto");
    expect(finalWay(4032, 3024, false)).toBe("stream");
    expect(finalWay(1920, 1080, false)).toBe("picker");
  });

  it("analyses a stream at 240 px on its long side", () => {
    expect(analysisSize(4032, 3024)).toEqual({ width: 240, height: 180 });
    expect(analysisSize(1080, 1920)).toEqual({ width: 135, height: 240 });
  });
});

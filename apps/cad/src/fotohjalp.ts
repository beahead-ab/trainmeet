// Fotohjälpen i mobilen (#90, CAD1, bildkedjan "1. Fotohjälp i mobilen"): what the phone's camera
// view checks on every frame, as pure functions the tests can run on synthetic frames.
//
// Ram: the module's four corners are found on a downscaled frame in the browser, so no frame
// leaves the phone and the overlay follows without waiting for the network. The floor's colour is
// read from the frame's border; the module is the largest region that differs from it (Otsu on the
// colour distance, closed, the biggest component); its convex hull is reduced to the four corners
// that keep the most area. Green when the whole module is in view with a margin, fills at least
// 80 % of the frame lengthwise and lies under the frame's middle.
// Vinkel: the phone's tilt from DeviceOrientation, at most 20° from straight down.
// Skärpa: the variance of the Laplacian, against the best of the last seconds (focus peaking), so
// it follows the scene rather than a fixed number. Stillhet: the frames' mean difference.
// Ljus: clipped highlights, and a hard shadow edge as dark and bright cells side by side inside the
// module. When everything has been green for HOLD_MS the photo is taken by itself.

export type Point = [number, number];
export type Quad = [Point, Point, Point, Point];
/** An RGBA frame, as a canvas's ImageData has it. */
export type Frame = { data: Uint8ClampedArray; width: number; height: number };

export const ANALYSIS_SIZE = 240;
/** Lengthwise share of the frame the module must fill. */
export const MIN_FILL = 0.8;
/** The margin to the frame's edges, as a share of its shorter side. */
export const MARGIN = 0.02;
/** How far the module's middle may lie from the frame's, as a share of its size. */
export const MAX_OFF_CENTRE = 0.15;
export const MAX_TILT = 20;
export const MAX_CLIPPED = 0.02;
/** A shadow edge: the darkest cell this much darker than its brightest neighbour. */
export const SHADOW_RATIO = 0.55;
export const MAX_MOTION = 6;
export const SHARP_FLOOR = 12;
export const SHARP_SHARE = 0.65;
export const HOLD_MS = 800;
/** The final photo from the stream itself needs this many pixels on its long side. */
export const FULL_SIDE = 3000;

/** The analysis frame's size for a stream: the long side ANALYSIS_SIZE. */
export function analysisSize(width: number, height: number, long = ANALYSIS_SIZE): { width: number; height: number } {
  if (!(width > 0 && height > 0)) return { width: long, height: Math.round((long * 3) / 4) };
  const scale = long / Math.max(width, height);
  return { width: Math.max(8, Math.round(width * scale)), height: Math.max(8, Math.round(height * scale)) };
}

export function grayOf(frame: Frame): Float32Array {
  const { data, width, height } = frame;
  const gray = new Float32Array(width * height);
  for (let i = 0, p = 0; i < gray.length; i += 1, p += 4) {
    gray[i] = 0.299 * (data[p] ?? 0) + 0.587 * (data[p + 1] ?? 0) + 0.114 * (data[p + 2] ?? 0);
  }
  return gray;
}

/** Otsu's threshold of values in 0..255. */
export function otsu(values: ArrayLike<number>): number {
  const bins = new Float64Array(256);
  for (let i = 0; i < values.length; i += 1) {
    const bin = Math.max(0, Math.min(255, Math.round(values[i] ?? 0)));
    bins[bin] = (bins[bin] ?? 0) + 1;
  }
  const total = values.length;
  let sum = 0;
  for (let t = 0; t < 256; t += 1) sum += t * (bins[t] ?? 0);
  let below = 0;
  let sumBelow = 0;
  let best = 0;
  let threshold = 128;
  for (let t = 0; t < 256; t += 1) {
    below += bins[t] ?? 0;
    if (below === 0) continue;
    const above = total - below;
    if (above === 0) break;
    sumBelow += t * (bins[t] ?? 0);
    const meanBelow = sumBelow / below;
    const meanAbove = (sum - sumBelow) / above;
    const between = below * above * (meanBelow - meanAbove) ** 2;
    if (between > best) {
      best = between;
      threshold = t;
    }
  }
  return threshold;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)] ?? 0;
}

/** A pixel in an opponent colour space: two colour axes and the lightness, the lightness weighed
 * down so that a floor's light and dark planks stay floor and a module's other colour stands out. */
function opponent(data: Uint8ClampedArray, p: number): [number, number, number] {
  const r = data[p] ?? 0;
  const g = data[p + 1] ?? 0;
  const b = data[p + 2] ?? 0;
  return [(r - g) / Math.SQRT2, (r + g - 2 * b) / Math.sqrt(6), 0.35 * ((r + g + b) / Math.sqrt(3))];
}

/** The frame's border, where the floor is when the module is in view with a margin. */
function onBorder(x: number, y: number, width: number, height: number, ring: number): boolean {
  return x < ring || x >= width - ring || y < ring || y >= height - ring;
}

/** Dilate (grow) or erode the mask by one pixel, 8-connected; outside the frame is empty. */
function morph(mask: Uint8Array, width: number, height: number, grow: boolean): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(mask.length);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      // Growing: is any neighbour set? Eroding: is any neighbour empty?
      let found = false;
      for (let dy = -1; dy <= 1 && !found; dy += 1) {
        for (let dx = -1; dx <= 1 && !found; dx += 1) {
          const xx = x + dx;
          const yy = y + dy;
          const v = xx < 0 || yy < 0 || xx >= width || yy >= height ? 0 : (mask[yy * width + xx] ?? 0);
          found = grow ? v === 1 : v === 0;
        }
      }
      out[y * width + x] = grow ? (found ? 1 : 0) : found ? 0 : 1;
    }
  }
  return out;
}

/** The module's region: the largest 4-connected one that keeps off the frame's border, or else
 * the largest of all (a module over the edge), as each row's leftmost and rightmost pixels. */
function moduleRegion(mask: Uint8Array, width: number, height: number): { area: number; points: Point[] } {
  const label = new Int32Array(mask.length);
  const found: { id: number; area: number; edge: boolean }[] = [];
  let next = 0;
  const stack: number[] = [];
  for (let start = 0; start < mask.length; start += 1) {
    if (!mask[start] || label[start]) continue;
    next += 1;
    label[start] = next;
    stack.push(start);
    let size = 0;
    let edge = false;
    while (stack.length) {
      const i = stack.pop() as number;
      size += 1;
      const x = i % width;
      const y = (i - x) / width;
      if (x === 0 || y === 0 || x === width - 1 || y === height - 1) edge = true;
      const near = [x > 0 ? i - 1 : -1, x < width - 1 ? i + 1 : -1, y > 0 ? i - width : -1, y < height - 1 ? i + width : -1];
      for (const j of near) {
        if (j >= 0 && mask[j] && !label[j]) {
          label[j] = next;
          stack.push(j);
        }
      }
    }
    found.push({ id: next, area: size, edge });
  }
  const enough = width * height * 0.05;
  const inside = found.filter((r) => !r.edge && r.area >= enough).sort((a, b) => b.area - a.area)[0];
  const best = inside ?? [...found].sort((a, b) => b.area - a.area)[0];
  if (!best) return { area: 0, points: [] };
  const points: Point[] = [];
  for (let y = 0; y < height; y += 1) {
    let left = -1;
    let right = -1;
    for (let x = 0; x < width; x += 1) {
      if (label[y * width + x] === best.id) {
        if (left < 0) left = x;
        right = x;
      }
    }
    if (left >= 0) points.push([left, y], [right + 1, y], [left, y + 1], [right + 1, y + 1]);
  }
  return { area: best.area, points };
}

const cross = (o: Point, a: Point, b: Point) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

/** The convex hull, counterclockwise in image coordinates (y down: clockwise as seen). */
export function hull(points: Point[]): Point[] {
  const sorted = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (sorted.length < 3) return sorted;
  const lower: Point[] = [];
  for (const p of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2] as Point, lower[lower.length - 1] as Point, p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper: Point[] = [];
  for (const p of [...sorted].reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2] as Point, upper[upper.length - 1] as Point, p) <= 0) upper.pop();
    upper.push(p);
  }
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}

export function area(polygon: Point[]): number {
  let sum = 0;
  for (let i = 0; i < polygon.length; i += 1) {
    const a = polygon[i] as Point;
    const b = polygon[(i + 1) % polygon.length] as Point;
    sum += a[0] * b[1] - b[0] * a[1];
  }
  return Math.abs(sum) / 2;
}

/** The hull reduced to four corners: the vertex that loses the least area goes first. */
export function fourCorners(polygon: Point[]): Point[] {
  const left = [...polygon];
  while (left.length > 4) {
    let weakest = 0;
    let least = Infinity;
    for (let i = 0; i < left.length; i += 1) {
      const lost = Math.abs(cross(left[(i + left.length - 1) % left.length] as Point, left[i] as Point, left[(i + 1) % left.length] as Point)) / 2;
      if (lost < least) {
        least = lost;
        weakest = i;
      }
    }
    left.splice(weakest, 1);
  }
  return left;
}

/** Clockwise as seen (y down), from the corner nearest the top left. */
export function ordered(corners: Point[]): Quad {
  const cx = corners.reduce((s, p) => s + p[0], 0) / corners.length;
  const cy = corners.reduce((s, p) => s + p[1], 0) / corners.length;
  const round = [...corners].sort((a, b) => Math.atan2(a[1] - cy, a[0] - cx) - Math.atan2(b[1] - cy, b[0] - cx));
  let first = 0;
  round.forEach((p, i) => {
    if (p[0] + p[1] < (round[first] as Point)[0] + (round[first] as Point)[1]) first = i;
  });
  return [0, 1, 2, 3].map((k) => round[(first + k) % 4] as Point) as Quad;
}

function angleAt(a: Point, b: Point, c: Point): number {
  const u = [a[0] - b[0], a[1] - b[1]];
  const v = [c[0] - b[0], c[1] - b[1]];
  const dot = (u[0] ?? 0) * (v[0] ?? 0) + (u[1] ?? 0) * (v[1] ?? 0);
  const norm = Math.hypot(u[0] ?? 0, u[1] ?? 0) * Math.hypot(v[0] ?? 0, v[1] ?? 0);
  return norm ? (Math.acos(Math.max(-1, Math.min(1, dot / norm))) * 180) / Math.PI : 0;
}

/** The module's four corners in the frame, or null when no module-like region is in it. */
export function findQuad(frame: Frame): Quad | null {
  const { data, width, height } = frame;
  const ring = Math.max(1, Math.round(Math.min(width, height) * 0.03));
  const colours = new Float32Array(width * height * 3);
  const border: [number[], number[], number[]] = [[], [], []];
  for (let y = 0, i = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1, i += 1) {
      const c = opponent(data, i * 4);
      colours.set(c, i * 3);
      if (onBorder(x, y, width, height, ring)) c.forEach((v, k) => border[k]?.push(v));
    }
  }
  const floorColour = border.map(median);
  const distance = new Float32Array(width * height);
  for (let i = 0; i < distance.length; i += 1) {
    let sum = 0;
    for (let k = 0; k < 3; k += 1) sum += ((colours[i * 3 + k] ?? 0) - (floorColour[k] ?? 0)) ** 2;
    distance[i] = Math.min(255, Math.sqrt(sum));
  }
  // The floor's own spread (grain, pattern) from the border: anything clearly beyond it is not
  // floor, also a module half in shadow, which Otsu alone would split down the middle.
  const floor: number[] = [];
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (onBorder(x, y, width, height, ring)) floor.push(distance[y * width + x] ?? 0);
    }
  }
  floor.sort((p, q) => p - q);
  const spread = floor[Math.floor(floor.length * 0.98)] ?? 0;
  const t = Math.max(12, Math.min(otsu(distance), spread + 10));
  let mask: Uint8Array<ArrayBuffer> = new Uint8Array(distance.length);
  for (let i = 0; i < distance.length; i += 1) mask[i] = (distance[i] ?? 0) > t ? 1 : 0;
  // Close the small gaps (rails, sleepers and shadows in the scenery): grow twice, shrink twice.
  mask = morph(morph(mask, width, height, true), width, height, true);
  mask = morph(morph(mask, width, height, false), width, height, false);
  const region = moduleRegion(mask, width, height);
  if (region.area < width * height * 0.05) return null;
  const outline = hull(region.points);
  if (outline.length < 4) return null;
  const corners = fourCorners(outline);
  const quad = ordered(corners);
  // A module seen from above is a convex quadrilateral that fills its hull, with no sharp corner.
  if (area(quad) < 0.85 * area(outline)) return null;
  for (let i = 0; i < 4; i += 1) {
    const angle = angleAt(quad[(i + 3) % 4] as Point, quad[i] as Point, quad[(i + 1) % 4] as Point);
    if (angle < 35 || angle > 145) return null;
  }
  return quad;
}

export type FrameCheck = {
  /** Every corner is inside the frame with the margin. */
  inside: boolean;
  /** The module's long sides against the frame's extent the same way. */
  fill: number;
  /** The module's middle from the frame's, as a share of the frame. */
  offCentre: number;
};

export function frameCheck(quad: Quad, width: number, height: number): FrameCheck {
  const margin = MARGIN * Math.min(width, height);
  const inside = quad.every(([x, y]) => x >= margin && y >= margin && x <= width - margin && y <= height - margin);
  const side = (i: number) => {
    const a = quad[i] as Point;
    const b = quad[(i + 1) % 4] as Point;
    return { length: Math.hypot(b[0] - a[0], b[1] - a[1]), angle: Math.atan2(b[1] - a[1], b[0] - a[0]) };
  };
  const sides = [0, 1, 2, 3].map(side);
  const pairA = ((sides[0]?.length ?? 0) + (sides[2]?.length ?? 0)) / 2;
  const pairB = ((sides[1]?.length ?? 0) + (sides[3]?.length ?? 0)) / 2;
  const long = pairA >= pairB ? sides[0] : sides[1];
  const length = Math.max(pairA, pairB);
  const angle = long?.angle ?? 0;
  const cos = Math.abs(Math.cos(angle));
  const sin = Math.abs(Math.sin(angle));
  const extent = Math.min(cos > 1e-6 ? width / cos : Infinity, sin > 1e-6 ? height / sin : Infinity);
  const cx = quad.reduce((s, p) => s + p[0], 0) / 4;
  const cy = quad.reduce((s, p) => s + p[1], 0) / 4;
  const offCentre = Math.max(Math.abs(cx - width / 2) / width, Math.abs(cy - height / 2) / height);
  return { inside, fill: extent ? length / extent : 0, offCentre };
}

/** The variance of the 4-neighbour Laplacian: higher is sharper. */
export function sharpness(gray: Float32Array, width: number, height: number): number {
  let sum = 0;
  let squares = 0;
  let n = 0;
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const i = y * width + x;
      const value = (gray[i - 1] ?? 0) + (gray[i + 1] ?? 0) + (gray[i - width] ?? 0) + (gray[i + width] ?? 0) - 4 * (gray[i] ?? 0);
      sum += value;
      squares += value * value;
      n += 1;
    }
  }
  if (!n) return 0;
  const mean = sum / n;
  return squares / n - mean * mean;
}

/** Sharp enough: above the floor, and near the best of the last seconds while the phone is held. */
export type SharpTrack = { best: number; at: number };

export function trackSharpness(track: SharpTrack, value: number, now: number, keep = 3000): { track: SharpTrack; sharp: boolean } {
  const best = now - track.at > keep ? value : Math.max(track.best, value);
  const next = { best, at: best === value ? now : track.at };
  return { track: next, sharp: value >= SHARP_FLOOR && value >= SHARP_SHARE * best };
}

function inQuad(quad: Quad, x: number, y: number): boolean {
  let sign = 0;
  for (let i = 0; i < 4; i += 1) {
    const c = cross(quad[i] as Point, quad[(i + 1) % 4] as Point, [x, y]);
    if (c === 0) continue;
    if (sign === 0) sign = Math.sign(c);
    else if (Math.sign(c) !== sign) return false;
  }
  return true;
}

/** The share of the module's pixels (the whole frame without a quad) with a channel clipped. */
export function clipped(frame: Frame, quad: Quad | null): number {
  const { data, width, height } = frame;
  let count = 0;
  let n = 0;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (quad && !inQuad(quad, x + 0.5, y + 0.5)) continue;
      const p = (y * width + x) * 4;
      n += 1;
      if ((data[p] ?? 0) >= 250 || (data[p + 1] ?? 0) >= 250 || (data[p + 2] ?? 0) >= 250) count += 1;
    }
  }
  return n ? count / n : 0;
}

/** A hard shadow over the module: neighbouring cells of a grid inside it with the same colour but
 * not the same light, the darker against the brighter (1 is even light). A shadow darkens all three
 * channels alike, so grass in shadow keeps grass's colour; ballast beside grass differs in colour
 * and is scenery, not a shadow. */
export function shadowRatio(frame: Frame, quad: Quad, cells = 6): number {
  const { data, width, height } = frame;
  const xs = quad.map((p) => p[0]);
  const ys = quad.map((p) => p[1]);
  const x0 = Math.min(...xs);
  const y0 = Math.min(...ys);
  const w = (Math.max(...xs) - x0) / cells;
  const h = (Math.max(...ys) - y0) / cells;
  const means: ({ light: number; r: number; g: number } | null)[][] = [];
  for (let j = 0; j < cells; j += 1) {
    const row: ({ light: number; r: number; g: number } | null)[] = [];
    for (let i = 0; i < cells; i += 1) {
      const sum = [0, 0, 0];
      let n = 0;
      for (let y = Math.floor(y0 + j * h); y < Math.floor(y0 + (j + 1) * h); y += 1) {
        for (let x = Math.floor(x0 + i * w); x < Math.floor(x0 + (i + 1) * w); x += 1) {
          if (x < 0 || y < 0 || x >= width || y >= height || !inQuad(quad, x + 0.5, y + 0.5)) continue;
          const p = (y * width + x) * 4;
          sum[0] = (sum[0] ?? 0) + (data[p] ?? 0);
          sum[1] = (sum[1] ?? 0) + (data[p + 1] ?? 0);
          sum[2] = (sum[2] ?? 0) + (data[p + 2] ?? 0);
          n += 1;
        }
      }
      const total = (sum[0] ?? 0) + (sum[1] ?? 0) + (sum[2] ?? 0);
      row.push(n > (w * h) / 2 && total > 0 ? { light: total / (3 * n), r: (sum[0] ?? 0) / total, g: (sum[1] ?? 0) / total } : null);
    }
    means.push(row);
  }
  let worst = 1;
  for (let j = 0; j < cells; j += 1) {
    for (let i = 0; i < cells; i += 1) {
      const here = means[j]?.[i];
      if (!here) continue;
      for (const [dx, dy] of [
        [1, 0],
        [0, 1],
      ] as const) {
        const there = means[j + dy]?.[i + dx];
        if (!there || Math.hypot(here.r - there.r, here.g - there.g) > 0.03) continue;
        worst = Math.min(worst, Math.min(here.light, there.light) / Math.max(here.light, there.light, 1));
      }
    }
  }
  return worst;
}

/** The mean absolute difference of two grey frames of the same size; Infinity without the first. */
export function motion(before: Float32Array | null, now: Float32Array): number {
  if (!before || before.length !== now.length || !now.length) return Infinity;
  let sum = 0;
  for (let i = 0; i < now.length; i += 1) sum += Math.abs((now[i] ?? 0) - (before[i] ?? 0));
  return sum / now.length;
}

/** Degrees from straight down, from DeviceOrientation's beta and gamma: 0 with the phone flat over
 * the module, screen up. */
export function tiltOf(beta: number, gamma: number): number {
  const b = (beta * Math.PI) / 180;
  const g = (gamma * Math.PI) / 180;
  const c = Math.max(-1, Math.min(1, Math.cos(b) * Math.cos(g)));
  return (Math.acos(c) * 180) / Math.PI;
}

export type Light = "ok" | "warn" | "unknown";
export type Lights = { ram: Light; vinkel: Light; skarpa: Light; ljus: Light; stilla: Light };

export type Seen = {
  quad: Quad | null;
  check: FrameCheck | null;
  /** Degrees from straight down; null: the phone gives no orientation. */
  tilt: number | null;
  sharp: boolean;
  clipped: number;
  shadow: number;
  motion: number;
  /** The level can be turned on (iOS asks first) but is not yet: it holds the photo. */
  levelOff?: boolean;
};

export type Verdict = { lights: Lights; green: boolean; advice: string };

/** The lights, whether all is green, and the one piece of advice that matters most now. */
export function verdict(seen: Seen): Verdict {
  const { quad, check, tilt } = seen;
  const frameOk = Boolean(quad && check && check.inside && check.fill >= MIN_FILL && check.offCentre <= MAX_OFF_CENTRE);
  const lights: Lights = {
    ram: frameOk ? "ok" : "warn",
    vinkel: seen.levelOff ? "warn" : tilt == null ? "unknown" : tilt <= MAX_TILT ? "ok" : "warn",
    skarpa: seen.sharp ? "ok" : "warn",
    ljus: seen.clipped <= MAX_CLIPPED && seen.shadow >= SHADOW_RATIO ? "ok" : "warn",
    stilla: seen.motion <= MAX_MOTION ? "ok" : "warn",
  };
  // Without an orientation sensor (a computer, or a no to the permission) the level does not stop the
  // photo: the chain measures the tilt from the photo itself. Not yet asked, it does.
  const green = Object.values(lights).every((light) => light !== "warn");
  let advice = "Allt är grönt. Håll stilla, bilden tas av sig själv.";
  if (!quad || !check) advice = "Lägg modulen på golvet och stå över mitten, så att hela modulen syns.";
  else if (!check.inside) advice = "Hela modulen syns inte. Backa eller stå högre. Går det inte: fota i delar.";
  else if (check.fill < MIN_FILL) advice = "Gå närmare: modulen ska fylla minst 80 % av bilden på längden.";
  else if (check.offCentre > MAX_OFF_CENTRE) advice = "Håll telefonen över modulens mitt.";
  else if (seen.levelOff) advice = "Slå på vattenpasset, så att bilden blir tagen rakt ovanifrån.";
  else if (lights.vinkel === "warn") advice = `Håll telefonen plant, rakt ovanför modulen. Nu ${Math.round(tilt ?? 0)}° snett.`;
  else if (lights.stilla === "warn") advice = "Håll telefonen stilla.";
  else if (lights.skarpa === "warn") advice = "Bilden är suddig. Håll stilla, eller tryck på modulen i bilden för att ställa skärpan.";
  else if (seen.clipped > MAX_CLIPPED) advice = "Ljuset bländar. Släck blixten eller flytta bort reflexen.";
  else if (seen.shadow < SHADOW_RATIO) advice = "Hård skugga över modulen. Ställ dig så att din skugga inte faller på den, och sök jämnt ljus.";
  return { lights, green, advice };
}

/** Automatic capture: everything green for HOLD_MS in a row, once. */
export type Hold = { since: number | null; fired: boolean };

export function hold(state: Hold, green: boolean, now: number, ms = HOLD_MS): { state: Hold; progress: number; fire: boolean } {
  if (state.fired) return { state, progress: 1, fire: false };
  if (!green) return { state: { since: null, fired: false }, progress: 0, fire: false };
  const since = state.since ?? now;
  const progress = Math.min(1, (now - since) / ms);
  if (progress >= 1) return { state: { since, fired: true }, progress: 1, fire: true };
  return { state: { since, fired: false }, progress, fire: false };
}

/** How the final photo is taken in full resolution: ImageCapture.takePhoto (Android), the stream
 * itself when it is large enough, or else the phone's own camera through the file picker (iOS). */
export function finalWay(streamWidth: number, streamHeight: number, imageCapture: boolean): "takePhoto" | "stream" | "picker" {
  if (imageCapture) return "takePhoto";
  return Math.max(streamWidth, streamHeight) >= FULL_SIDE ? "stream" : "picker";
}

/** The quad from the analysis frame to the video's own pixels. */
export function scaleQuad(quad: Quad, factor: number): Quad {
  return quad.map(([x, y]) => [x * factor, y * factor]) as Quad;
}

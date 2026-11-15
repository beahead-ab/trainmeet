// The product names in 5×7 dots, as in the header of every TrainMeet product. The same
// glyphs as hub/brand.py and tools/punkter.py in trainmeet-spec (the departure boards).

const ROWS: Record<string, string> = {
  A: ".###.|#...#|#...#|#####|#...#|#...#|#...#",
  B: "####.|#...#|#...#|####.|#...#|#...#|####.",
  C: ".###.|#...#|#....|#....|#....|#...#|.###.",
  D: "####.|#...#|#...#|#...#|#...#|#...#|####.",
  E: "#####|#....|#....|####.|#....|#....|#####",
  F: "#####|#....|#....|####.|#....|#....|#....",
  G: ".###.|#...#|#....|#.###|#...#|#...#|.####",
  H: "#...#|#...#|#...#|#####|#...#|#...#|#...#",
  I: ".###.|..#..|..#..|..#..|..#..|..#..|.###.",
  J: "..###|...#.|...#.|...#.|...#.|#..#.|.##..",
  K: "#...#|#..#.|#.#..|##...|#.#..|#..#.|#...#",
  L: "#....|#....|#....|#....|#....|#....|#####",
  M: "#...#|##.##|#.#.#|#.#.#|#...#|#...#|#...#",
  N: "#...#|#...#|##..#|#.#.#|#..##|#...#|#...#",
  O: ".###.|#...#|#...#|#...#|#...#|#...#|.###.",
  P: "####.|#...#|#...#|####.|#....|#....|#....",
  R: "####.|#...#|#...#|####.|#.#..|#..#.|#...#",
  S: ".####|#....|#....|.###.|....#|....#|####.",
  T: "#####|..#..|..#..|..#..|..#..|..#..|..#..",
  U: "#...#|#...#|#...#|#...#|#...#|#...#|.###.",
  V: "#...#|#...#|#...#|#...#|#...#|.#.#.|..#..",
  X: "#...#|#...#|.#.#.|..#..|.#.#.|#...#|#...#",
  Y: "#...#|#...#|.#.#.|..#..|..#..|..#..|..#..",
  Å: "..#..|.....|.###.|#...#|#####|#...#|#...#",
  Ä: ".#.#.|.....|.###.|#...#|#####|#...#|#...#",
  Ö: ".#.#.|.....|.###.|#...#|#...#|#...#|.###.",
  " ": ".....|.....|.....|.....|.....|.....|.....",
};

export const PITCH = 3;
export const RADIUS = 1.32;

export type Dot = { cx: number; cy: number };

/** The lit dots of a name, in the units of an SVG viewBox. Unknown characters throw. */
export function dotsFor(name: string): { dots: Dot[]; width: number; height: number } {
  const text = name.toUpperCase();
  const dots: Dot[] = [];
  [...text].forEach((char, index) => {
    const glyph = ROWS[char];
    if (glyph === undefined) {
      throw new Error(`No 5×7 glyph for: ${char}`);
    }
    glyph.split("|").forEach((line, row) => {
      [...line].forEach((cell, col) => {
        if (cell === "#") {
          dots.push({ cx: (index * 6 + col) * PITCH + PITCH / 2, cy: row * PITCH + PITCH / 2 });
        }
      });
    });
  });
  return { dots, width: ([...text].length * 6 - 1) * PITCH, height: 7 * PITCH };
}

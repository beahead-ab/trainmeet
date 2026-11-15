import { describe, expect, it } from "vitest";
import { dotsFor, PITCH } from "./glyphs";

describe("the product names in dots", () => {
  it("draws every product name, LOKFÖRAREN included", () => {
    for (const name of ["HUB", "TKL", "CAD", "CATALOG", "TMBOX", "LOKFÖRAREN", "ID"]) {
      expect(dotsFor(name).dots.length).toBeGreaterThan(0);
    }
  });

  it("is six dots wide per letter less the last gap, and seven high", () => {
    const { width, height } = dotsFor("HUB");
    expect(width).toBe((3 * 6 - 1) * PITCH);
    expect(height).toBe(7 * PITCH);
  });

  it("draws the same dots as the hub's header (hub/brand.py) for H", () => {
    expect(dotsFor("H").dots).toHaveLength(17);
  });

  it("refuses a letter it has no glyph for", () => {
    expect(() => dotsFor("Q")).toThrow("No 5×7 glyph for: Q");
  });
});

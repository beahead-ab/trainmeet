import { describe, expect, it } from "vitest";
import { pageFor, PATHS } from "./routes";

describe("the addresses", () => {
  it("starts in Fordon, also from the home screen", () => {
    expect(pageFor("/")).toBe("vehicles");
    expect(pageFor("/fordon")).toBe("vehicles");
  });

  it("knows every page, with or without a trailing slash", () => {
    for (const [page, path] of Object.entries(PATHS)) {
      expect(pageFor(path)).toBe(page);
      expect(pageFor(path + "/")).toBe(page);
      expect(pageFor(path.toUpperCase())).toBe(page);
    }
  });

  it("says when a page does not exist", () => {
    expect(pageFor("/fordon/okand")).toBe("missing");
  });
});

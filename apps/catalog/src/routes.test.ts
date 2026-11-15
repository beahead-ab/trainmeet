import { describe, expect, it } from "vitest";
import { editPath, lendPath, PATHS, routeFor, tabOf, vehiclePath } from "./routes";

const ID = "8a3e1f0c-1111-4222-8333-944455556666";

describe("the addresses", () => {
  it("starts in Fordon, also from the home screen", () => {
    expect(routeFor("/")).toEqual({ page: "vehicles" });
    expect(routeFor("/fordon")).toEqual({ page: "vehicles" });
  });

  it("knows every fixed page, with or without a trailing slash", () => {
    for (const [page, path] of Object.entries(PATHS)) {
      expect(routeFor(path).page).toBe(page);
      expect(routeFor(path + "/").page).toBe(page);
      expect(routeFor(path.toUpperCase()).page).toBe(page);
    }
  });

  it("reads a vehicle's card, its edit page and its lending page", () => {
    expect(routeFor(vehiclePath(ID))).toEqual({ page: "vehicle", id: ID });
    expect(routeFor(editPath(ID))).toEqual({ page: "editVehicle", id: ID });
    expect(routeFor(lendPath(ID))).toEqual({ page: "lend", id: ID });
  });

  it("says when a page does not exist", () => {
    expect(routeFor("/fordon/okand").page).toBe("missing");
    expect(routeFor("/fordon/" + ID + "/okand").page).toBe("missing");
  });

  it("keeps the Fordon tab for the vehicle pages and the places", () => {
    expect(tabOf("vehicle")).toBe("vehicles");
    expect(tabOf("places")).toBe("vehicles");
    expect(tabOf("meets")).toBe("meets");
  });
});

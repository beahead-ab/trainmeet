import { describe, expect, it } from "vitest";
import { editPath, lendPath, nextAfterLogin, PATHS, routeFor, tabOf, uidFrom, vehiclePath } from "./routes";

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

  it("reads a tag's address whatever the case and with a trailing slash (CAT-80)", () => {
    expect(routeFor("/t/04A1B2C3D4E5F6/")).toEqual({ page: "tag", id: "04a1b2c3d4e5f6" });
    expect(routeFor("/t/04%3Aa1%3Ab2%3Ac3")).toEqual({ page: "tag", id: "04:a1:b2:c3" });
    expect(tabOf("tag")).toBe("tap");
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

  it("returns to the tag after logging in, and nowhere outside Catalog", () => {
    expect(nextAfterLogin("?next=%2Ft%2F04a1b2c3")).toBe("/t/04a1b2c3");
    expect(nextAfterLogin("?next=//example.com")).toBe(PATHS.vehicles);
    expect(nextAfterLogin("?next=https%3A%2F%2Fexample.com")).toBe(PATHS.vehicles);
    expect(nextAfterLogin("")).toBe(PATHS.vehicles);
    expect(routeFor("/logga-in?next=%2Ft%2Fx").page).toBe("login");
  });

  it("finds the uid in a tag's address", () => {
    expect(uidFrom("https://trainmeet.app/t/04A1B2C3D4E5F6")).toBe("04A1B2C3D4E5F6");
    expect(uidFrom(" 04:a1:b2:c3 ")).toBe("04:a1:b2:c3");
  });
});

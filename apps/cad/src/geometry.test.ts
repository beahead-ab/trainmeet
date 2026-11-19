import { describe, expect, it } from "vitest";
import { arcLength, fromChord, lineRadius, preview, toChord } from "./geometry";
import { routeFor } from "./routes";

describe("the curve, as cad/geometry.py", () => {
  it("gives radius and angle from the string and sagitta, and back", () => {
    const found = fromChord(1035, 68)!;
    expect(Math.round(found.radius)).toBe(2003);
    expect(found.radius.toFixed(1)).toBe("2003.2");
    expect(found.angle.toFixed(2)).toBe("29.94");
    const back = toChord(2000, 30);
    expect(Math.round(back.chord)).toBe(1035);
    expect(Math.round(back.sagitta)).toBe(68);
    expect(Math.round(arcLength(2000, 30))).toBe(1047);
    expect(fromChord(1000, 600)).toBeNull();
  });

  it("knows the lines' radii from Kant 1, outer and inner", () => {
    const curve = { radius: 2000, angle: 30, width: 500, edge: "outer" };
    expect(lineRadius(curve, 200, 0)).toBe(2200);
    expect(lineRadius(curve, 200, 500)).toBe(1700);
    expect(lineRadius({ ...curve, edge: "inner" }, 200, 500)).toBe(2300);
  });

  it("previews the graph: through tracks when the gables agree, else only the ends", () => {
    const straight = { kind: "straight" as const, length: 1500, width: 500 };
    expect(preview(straight, [140], [140]).pieces).toEqual([{ kind: "line", start: [0, 140], end: [1500, 140] }]);
    const differ = preview(straight, [330, 380], [245, 295, 345]);
    expect(differ.complete).toBe(false);
    expect(differ.pieces).toEqual([]);
    expect(differ.ends).toHaveLength(5);
  });
});

describe("the addresses", () => {
  it("has a page for each view", () => {
    expect(routeFor("/")).toEqual({ page: "library" });
    expect(routeFor("/moduler/ny/kurva")).toEqual({ page: "form", kind: "curve" });
    const id = "0e6c2f0a-1b2c-4d3e-8f40-5a6b7c8d9e0f";
    expect(routeFor(`/moduler/${id}/historik`)).toEqual({ page: "module", id, tab: "historik" });
    expect(routeFor(`/moduler/${id}`, "?version=2")).toEqual({ page: "module", id, tab: "oversikt", version: 2 });
    expect(routeFor(`/moduler/${id}/andra`)).toEqual({ page: "form", kind: "straight", id });
    expect(routeFor("/gavelprofiler")).toEqual({ page: "profiles" });
    expect(routeFor("/moduler/nej")).toEqual({ page: "missing" });
  });
});

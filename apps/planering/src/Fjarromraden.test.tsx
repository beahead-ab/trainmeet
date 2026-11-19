import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Draft } from "./api";
import { Karta } from "./Bana";
import { DataPage } from "./Data";
import { areaChange, areaId, areaPlaces, remoteFrom, type Package } from "./data";
import { Fjarromraden } from "./Fjarromraden";

// Fjärrområden i planen (PLAN-04, PLAN-33, FR49): a driftplats planned as remote-controlled points
// at a remote area, a name and a row of driftplatser along the line, in Data and in Bana.

const pkg = {
  meet: { traffic_week: { start_weekday: "mon", days: 1 } },
  clock: { start_time: "06:00" },
  places: [
    { id: "nby", code: "Nby", name: "Norrby", kind: "manned", remote_from: null, remote_area: null, phone: null, tracks: [] },
    { id: "asn", code: "Ån", name: "Åsen", kind: "remote", remote_from: null, remote_area: "vast", phone: null, tracks: [] },
    { id: "lvh", code: "Lvh", name: "Lövhult", kind: "halt", remote_from: null, remote_area: null, phone: null, tracks: [] },
    { id: "mla", code: "Mlå", name: "Mellanå", kind: "remote", remote_from: null, remote_area: "vast", phone: null, tracks: [] },
    { id: "sjv", code: "Sjv", name: "Sjövik", kind: "remote", remote_from: "mla", remote_area: null, phone: null, tracks: [] },
  ],
  sections: [
    { id: "s1", place_a: "nby", place_b: "asn", tracks: "single", clearance_mode: null, parts: [{ id: "p1", from_place: "nby", to_place: "asn" }] },
    { id: "s2", place_a: "asn", place_b: "mla", tracks: "double", clearance_mode: null, parts: [{ id: "p2", from_place: "asn", to_place: "lvh" }, { id: "p3", from_place: "lvh", to_place: "mla" }] },
  ],
  trains: [],
  duties: [],
  turns: [],
  shunting: [],
  remote_areas: [{ id: "vast", name: "Västra", places: ["asn", "mla"] }],
  display: { graph_pages: [] },
} as unknown as Package;

const draft = {
  meet: { id: "prov", name: "Provträffen", clearance_mode: "requested" },
  revision: 4,
  package: pkg,
  facts: [{ ref: "remote_area:vast", certainty: "confirmed", origins: [{ source: "planner", at: "Planering" }], note: null }],
  sources: [],
  questions: [],
  rulebook: { train_types: [] },
} as unknown as Draft;
const name = (id: string) => pkg.places.find((place) => place.id === id)?.name ?? id;

describe("Fjärrområden i Data (PLAN-33, FR49)", () => {
  it("shows each remote area and where a remote place is controlled from", () => {
    const place = (id: string) => pkg.places.find((item) => item.id === id)!;
    expect(remoteFrom(pkg, place("asn"), name)).toBe("fjärrområdet Västra");
    expect(remoteFrom(pkg, place("sjv"), name)).toBe("Mellanå");
    expect(remoteFrom(pkg, place("nby"), name)).toBeNull();
    const html = renderToStaticMarkup(<DataPage admin={false} meet="prov" draft={draft} findings={[]} versions={[]} initialBlocks={["places", "remote_areas"]} />);
    expect(html).toContain("<b>1 </b>Fjärrområden");
    expect(html).toContain("<td><b>Västra</b></td><td>Åsen – Mellanå</td>");
    expect(html).toContain("Fjärrstyrd<span class=\"liten block\">från fjärrområdet Västra</span>");
    // Only the administrator changes them.
    expect(html).not.toContain('id="fjarromraden"');
    expect(renderToStaticMarkup(<DataPage admin meet="prov" draft={draft} findings={[]} versions={[]} />)).toContain('id="fjarromraden"');
  });

  it("lets the administrator name an area and choose its driftplatser, never a halt", () => {
    const html = renderToStaticMarkup(<Fjarromraden meet="prov" draft={draft} pkg={pkg} />);
    expect(html).toContain("<b>Västra</b><span class=\"liten\">Åsen – Mellanå</span>");
    expect(html).toContain(">Ändra<");
    expect(html).toContain(">Ta bort<");
    expect(html).toContain('id="new-area"');
    expect(areaPlaces(pkg.remote_areas![0]!, name)).toBe("Åsen – Mellanå");
    // Spara sends the places in the plan's order; no name takes the area away.
    expect(areaChange(pkg, "vast", " Västra ", ["mla", "asn"])).toEqual({ remote_area: "vast", name: "Västra", places: ["asn", "mla"] });
    expect(areaChange(pkg, "vast", null, ["asn"])).toEqual({ remote_area: "vast", name: null, places: [] });
    expect(areaId("Östra linjen", ["vast"])).toBe("ostra-linjen");
    expect(areaId("Västra", ["vastra"])).toBe("vastra-2");
  });
});

describe("Fjärrområden i Bana", () => {
  it("marks the remote places and lists the areas", () => {
    const html = renderToStaticMarkup(<Karta pkg={pkg} choice={null} unsure={new Set()} onSelect={() => undefined} />);
    expect(html).toContain("fjärrstyrd från fjärrområdet Västra");
    expect(html).toContain("fjärrstyrd från Mellanå");
  });
});

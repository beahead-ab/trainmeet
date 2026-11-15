import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { statusFor, type Vehicle, type VehicleList } from "./api";
import type { Ctx } from "./common";
import { title } from "./common";
import { text } from "./i18n";
import { LendView } from "./LendPage";
import { PlacesView } from "./PlacesPage";
import { CardView, evnLine, eventText } from "./VehicleCard";
import { EMPTY, FormView, outgoing } from "./VehicleForm";
import { VehiclesView } from "./VehiclesPage";

const ctx = (language: "sv" | "en" = "sv"): Ctx => ({ t: (key, vars) => text(language, key, vars), language });
const account = { id: "8a3e1f0c-1111-5222-8333-944455556666", name: "Provkonto A", initials: "PA" };
const NOW = "2026-11-15T12:00:00Z";

function vehicle(change: Partial<Vehicle> = {}): Vehicle {
  return {
    id: "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
    version: 1,
    status: "ready",
    kind: "freight_wagon",
    litt: "Hbis",
    number: "21 74 245 2 253-0",
    operator: "Green Cargo",
    epoch: "V",
    scale: "H0",
    maker: "",
    article_number: "",
    note: "",
    dcc_address: "",
    functions: [],
    place: "5f0c7a2e-0000-4000-8000-000000000001",
    place_name: "Låda 3",
    state: "home",
    lending: null,
    evn: { text: "21 74 245 2 253-0", interop: "21", country: "74", country_letters: "S", serial: "245 2 253", check: 0, given: 0, valid: true },
    field_sources: { litt: "owner" },
    tagged: false,
    created_at: NOW,
    updated_at: NOW,
    ...change,
  };
}

function list(vehicles: Vehicle[]): VehicleList {
  const counts = { home: 0, packed: 0, at_meet: 0, lent: 0 };
  for (const v of vehicles) counts[v.state] += 1;
  return { vehicles, counts, total: vehicles.length };
}

const t = ctx().t;

describe("the fleet", () => {
  it("lists the vehicles with EVN and place, and counts per state", () => {
    const lent = vehicle({ id: "2b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed", litt: "Gbs", number: "3112", state: "lent", lending: { to: "Olle", since: NOW, until: null }, evn: null });
    const html = renderToStaticMarkup(
      <VehiclesView ctx={ctx()} account={account} list={list([vehicle(), lent])} q="" state={null} group="all" selected={new Set()} error={null} />,
    );
    expect(html).toContain("Vagnparken · Provkonto A");
    expect(html).toContain("2 fordon.");
    expect(html).toContain("Hbis 21 74 245 2 253-0");
    expect(html).toContain("Godsvagn · Green Cargo · H0");
    expect(html).toContain("Låda 3");
    expect(html).toContain("Utlånad");
    expect(html).toContain("Olle");
    expect(html).toMatch(/Utlånade <span class="cat-antal">1<\/span>/);
    expect(html).toContain('href="/fordon/nytt"');
    expect(html).toContain('href="/platser"');
  });

  it("says when nothing matches, and offers to move what is selected", () => {
    const html = renderToStaticMarkup(
      <VehiclesView ctx={ctx()} account={account} list={list([])} q="Rc6" state={null} group="engines" selected={new Set(["x", "y"])} error={null} />,
    );
    expect(html).toContain("Inga fordon passar sökningen.");
    expect(html).toContain("Flytta 2 valda");
    expect(html).toMatch(/aria-pressed="true"[^>]*>Lok</);
  });

  it("names a draft without litt and number", () => {
    expect(title(t, { litt: "", number: "" })).toBe("Utkast utan namn");
    expect(title(t, { litt: "Rc6", number: "1340" })).toBe("Rc6 1340");
  });
});

describe("the card", () => {
  it("shows the core fields, the EVN with its check digit and where the vehicle is", () => {
    const html = renderToStaticMarkup(<CardView ctx={ctx()} vehicle={vehicle()} events={[]} error={null} />);
    expect(html).toContain("Fordonskortet");
    expect(html).toContain("21 74 245 2 253-0");
    expect(html).toContain("kontrollsiffran stämmer");
    expect(html).toContain("Hemma i Låda 3");
    expect(html).toContain(">Låna ut<");
    expect(html).toContain("Ta bort fordonet");
    expect(html).not.toContain("DCC-adress");
  });

  it("reports a wrong painted check digit and never corrects the number", () => {
    const wrong = vehicle({ number: "21 74 245 2 253-9", evn: { ...vehicle().evn!, given: 9, valid: false } });
    expect(evnLine(t, wrong)).toEqual({ value: "21 74 245 2 253-0", note: "Kontrollsiffran stämmer inte. Den ska vara 0.", kind: "wrong" });
    const html = renderToStaticMarkup(<CardView ctx={ctx()} vehicle={wrong} events={[]} error={null} />);
    expect(html).toContain("Hbis 21 74 245 2 253-9");
  });

  it("shows a lent vehicle with the borrower, the place it lives and Tillbaka", () => {
    const lent = vehicle({ state: "lent", lending: { to: "Olle", since: NOW, until: "2026-12-01" } });
    const html = renderToStaticMarkup(<CardView ctx={ctx()} vehicle={lent} events={[]} error={null} />);
    expect(html).toContain("Till Olle sedan 15 november.");
    expect(html).toContain("Tillbaka senast 1 december.");
    expect(html).toContain("Bor annars i Låda 3.");
    expect(html).toContain(">Tillbaka<");
    expect(html).not.toContain(">Låna ut<");
  });

  it("shows the DCC address and functions for a locomotive", () => {
    const engine = vehicle({ kind: "locomotive", litt: "Rc6", number: "1340", dcc_address: "1340", functions: [{ number: 0, name: "Ljus" }], evn: null });
    const html = renderToStaticMarkup(<CardView ctx={ctx("en")} vehicle={engine} events={[]} error={null} />);
    expect(html).toContain("DCC address");
    expect(html).toContain("F0 Ljus");
    expect(html).toContain("No EVN in the number.");
  });

  it("tells the history in words", () => {
    expect(eventText(t, { at: NOW, state: "lent", place_name: "Låda 3", lent_to: "Olle" })).toBe("Utlånad till Olle");
    expect(eventText(t, { at: NOW, state: "home", place_name: "Låda 3", lent_to: null })).toBe("Hemma i Låda 3");
    expect(eventText(t, { at: NOW, state: "home", place_name: null, lent_to: null })).toBe("Hemma");
  });
});

describe("adding and changing", () => {
  it("is ready only with a kind and a litt or number, otherwise a draft", () => {
    expect(statusFor(EMPTY)).toBe("draft");
    expect(statusFor({ ...EMPTY, kind: "other" })).toBe("draft");
    expect(statusFor({ ...EMPTY, kind: "other", number: " 7 " })).toBe("ready");
    expect(statusFor({ ...EMPTY, litt: "Hbis" })).toBe("draft");
  });

  it("sends no DCC for a wagon, and no function without a name", () => {
    const sent = outgoing({ ...EMPTY, kind: "freight_wagon", litt: "Hbis", dcc_address: "3", functions: [{ number: 0, name: "Ljus" }] });
    expect(sent).toMatchObject({ status: "ready", dcc_address: "", functions: [] });
    const engine = outgoing({ ...EMPTY, kind: "locomotive", litt: "Rc6", dcc_address: "1340", functions: [{ number: 0, name: "Ljus" }, { number: 1, name: " " }] });
    expect(engine.functions).toEqual([{ number: 0, name: "Ljus" }]);
  });

  it("has a label for every field and the draft hint", () => {
    const html = renderToStaticMarkup(
      <FormView ctx={ctx()} fields={EMPTY} places={[]} heading="Lägg till fordon" crumb="Lägg till fordon" busy={false} error={null} backHref="/fordon" />,
    );
    for (const label of ["Slag", "Littera", "Nummer", "Bolag", "Epok", "Skala", "Tillverkare", "Artikelnummer", "Plats", "Anteckning"]) {
      expect(html).toMatch(new RegExp(`<label for="[^"]+">${label}</label>`));
    }
    expect(html).toContain("sparas som utkast");
    expect(html).not.toContain("DCC-adress");
    const engine = renderToStaticMarkup(
      <FormView ctx={ctx()} fields={{ ...EMPTY, kind: "locomotive" }} places={[]} heading="x" crumb="x" busy={false} error={null} backHref="/fordon" />,
    );
    expect(engine).toContain("DCC-adress");
    expect(engine).toContain("Lägg till funktion");
  });
});

describe("lending and the places", () => {
  it("lends to a typed name, and only a ready vehicle at home", () => {
    const html = renderToStaticMarkup(<LendView ctx={ctx()} vehicle={vehicle()} name="Olle" until="" busy={false} error={null} />);
    expect(html).toContain("Låna ut till Olle");
    expect(html).toContain("låntagaren får inget i Catalog");
    const draft = renderToStaticMarkup(<LendView ctx={ctx()} vehicle={vehicle({ status: "draft" })} name="Olle" until="" busy={false} error={null} />);
    expect(draft).toContain("Bara ett klart fordon som är hemma kan lånas ut.");
  });

  it("shows the places with how many are at home, and what is lent out", () => {
    const places = [{ id: "5f0c7a2e-0000-4000-8000-000000000001", name: "Låda 3", vehicles_home: 0, vehicles: 3 }];
    const lent = [vehicle({ litt: "Gbs", number: "3112", state: "lent", lending: { to: "Olle", since: NOW, until: null } })];
    const html = renderToStaticMarkup(<PlacesView ctx={ctx()} places={places} lent={lent} error={null} />);
    expect(html).toContain("Var fordonen bor");
    expect(html).toContain("Låda 3");
    expect(html).toContain("0 av 3");
    expect(html).toContain("Gbs 3112");
    expect(html).toContain("Till Olle sedan 15 november.");
    expect(html).toContain("Ny plats");
  });
});

describe("a fleet shared with someone (#49)", () => {
  const shared = (right: "view" | "edit"): Ctx => ({ ...ctx(), right, fleetTitle: "Vagnparken · Provkonto A" });

  it("shows the owner the button to share the fleet in ID, and the places", () => {
    const html = renderToStaticMarkup(
      <VehiclesView ctx={{ ...ctx(), shareUrl: "https://test.id.trainmeet.app/vagnparker/a" }} account={account} list={list([vehicle()])} q="" state={null} group="all" selected={new Set()} error={null} />,
    );
    expect(html).toContain('href="https://test.id.trainmeet.app/vagnparker/a"');
    expect(html).toContain("Dela vagnparken");
    expect(html).toContain('type="checkbox"');
  });

  it("to look: whose fleet it is, and nothing to add, move or share", () => {
    const html = renderToStaticMarkup(
      <VehiclesView ctx={{ ...shared("view"), shareUrl: "https://x" }} account={account} list={list([vehicle()])} q="" state={null} group="all" selected={new Set()} error={null} />,
    );
    expect(html).toContain("Vagnparken · Provkonto A");
    expect(html).not.toContain("Dela vagnparken");
    expect(html).not.toContain("Lägg till fordon");
    expect(html).not.toContain('type="checkbox"');
    expect(html).not.toContain(">Platser<");
  });

  it("to edit: add a vehicle, but the card keeps the owner's things to the owner", () => {
    const html = renderToStaticMarkup(
      <VehiclesView ctx={shared("edit")} account={account} list={list([vehicle()])} q="" state={null} group="all" selected={new Set()} error={null} />,
    );
    expect(html).toContain("Lägg till fordon");
    const card = renderToStaticMarkup(<CardView ctx={shared("edit")} vehicle={vehicle({ tagged: true, tags: [] })} events={[]} error={null} />);
    expect(card).toContain(">Ändra<");
    expect(card).toContain("Fordonet har en tagg. Bara ägaren ser den."); // CAT-47
    for (const owners of ["Låna ut", "Flytta", "Ta bort fordonet", "Händelser"]) expect(card).not.toContain(owners);
    const looking = renderToStaticMarkup(<CardView ctx={shared("view")} vehicle={vehicle()} events={[]} error={null} />);
    expect(looking).not.toContain(">Ändra<");
  });

  it("a new vehicle in someone else's fleet, or in one's own", () => {
    const html = renderToStaticMarkup(<FormView ctx={shared("edit")} fields={EMPTY} places={[]} heading="Nytt" crumb="Nytt" busy={false} error={null} backHref="/fordon" addTo={<p>Lägg fordonet i</p>} />);
    expect(html).toContain("Lägg fordonet i");
    expect(html).not.toContain(text("sv", "fPlace")); // the places are the owner's
  });
});

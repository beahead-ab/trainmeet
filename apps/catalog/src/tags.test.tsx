import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Vehicle } from "./api";
import type { Ctx } from "./common";
import { text } from "./i18n";
import { MiniCardView, slotOf, UnknownView } from "./TagPage";
import { TagSection } from "./VehicleCard";

const ctx: Ctx = { t: (key, vars) => text("sv", key, vars), language: "sv" };
const NOW = "2026-11-15T12:00:00Z";
const account = { id: "8a3e1f0c-1111-5222-8333-944455556666", name: "Provkonto A", initials: "PA" };
const card = { litt: "Hbis", number: "2253", kind: "freight_wagon" as const, operator: "Green Cargo", scale: "H0", thumbnail: null };

function vehicle(change: Partial<Vehicle> = {}): Vehicle {
  return {
    id: "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
    version: 1,
    status: "ready",
    kind: "freight_wagon",
    litt: "Hbis",
    number: "2253",
    operator: "",
    epoch: "",
    scale: "",
    maker: "",
    article_number: "",
    note: "Privat anteckning",
    dcc_address: "",
    functions: [],
    place: null,
    place_name: null,
    state: "home",
    lending: null,
    evn: null,
    field_sources: {},
    tags: [],
    created_at: NOW,
    updated_at: NOW,
    ...change,
  };
}

describe("someone else's vehicle", () => {
  it("shows exactly the mini card, without the owner", () => {
    const html = renderToStaticMarkup(<MiniCardView t={ctx.t} found={{ outcome: "private", card }} />);
    expect(html).toContain("Någon annans fordon");
    expect(html).toContain("Hbis 2253");
    expect(html).toContain("Godsvagn · Green Cargo · H0");
    expect(html).not.toContain("Ägare");
  });

  it("shows the owner's name when the owner shows it", () => {
    const html = renderToStaticMarkup(<MiniCardView t={ctx.t} found={{ outcome: "shared", owner_name: "Provkonto A", card }} />);
    expect(html).toContain("Ägare: Provkonto A");
  });
});

describe("an unknown tag", () => {
  it("asks a visitor to log in and comes back to the tag (CAT-103, CAT-106)", () => {
    const html = renderToStaticMarkup(
      <UnknownView ctx={ctx} uid="04a1b2c3" account={null} pending={null} choosing={false} vehicles={[]} ask={null} error={null} />,
    );
    expect(html).toContain("Taggen är inte kopplad till något fordon.");
    expect(html).toContain('href="/logga-in?next=%2Ft%2F04a1b2c3"');
    expect(html).not.toContain("Lägg till nytt fordon");
  });

  it("offers to add a new vehicle or link one the owner has (CAT-105)", () => {
    const html = renderToStaticMarkup(
      <UnknownView ctx={ctx} uid="04a1b2c3" account={account} pending={null} choosing={true} vehicles={[vehicle()]} ask={null} error={null} />,
    );
    expect(html).toContain('href="/fordon/nytt?tagg=04a1b2c3"');
    expect(html).toContain("Koppla till ett fordon jag redan har");
    expect(html).toContain(">Hbis 2253<");
  });

  it("offers the vehicle that waits for a tag first (CAT-94)", () => {
    const pending = { vehicle_id: vehicle().id, title: "Hbis 2253", replace: null, expires_at: NOW };
    const html = renderToStaticMarkup(
      <UnknownView ctx={ctx} uid="04a1b2c3" account={account} pending={pending} choosing={false} vehicles={[]} ask={null} error={null} />,
    );
    expect(html).toContain("Koppla till Hbis 2253");
  });

  it("knows a QR label's slot from an NFC tag's", () => {
    expect(slotOf("qabcdefghjk2")).toBe("qr");
    expect(slotOf("04a1b2c3d4e5f6")).toBe("nfc");
    expect(slotOf("6f1d2c1e-6a43-4b8e-9c5a-0c3a7d4f9b21")).toBe("nfc");
  });
});

describe("the tag on the card (CAT-97)", () => {
  const tag = {
    assignment: "11111111-1111-4111-8111-111111111111",
    tag: "22222222-2222-4222-8222-222222222222",
    uid: "04a1b2c3d4e5f6",
    name: "NFC D4E5F6",
    kind: "nfc" as const,
    address: "https://trainmeet.app/t/04a1b2c3d4e5f6",
    linked_at: NOW,
  };

  it("offers Koppla tagg and a QR label when there is none", () => {
    const html = renderToStaticMarkup(<TagSection ctx={ctx} vehicle={vehicle()} pending={null} />);
    expect(html).toContain("Ingen tagg än.");
    expect(html).toContain(">Koppla tagg<");
    expect(html).toContain(">Skapa QR-etikett<");
  });

  it("shows the tag's kind, name, address and date, with Ersätt and Koppla bort", () => {
    const html = renderToStaticMarkup(<TagSection ctx={ctx} vehicle={vehicle({ tags: [tag] })} pending={null} />);
    expect(html).toContain("NFC-tagg");
    expect(html).toContain("NFC D4E5F6");
    expect(html).toContain("trainmeet.app/t/04a1b2c3d4e5f6");
    expect(html).toContain("Kopplad 15 november.");
    expect(html).toContain(">Ersätt tagg<");
    expect(html).toContain(">Koppla bort<");
    expect(html).not.toContain(">Koppla tagg<");
  });

  it("says the vehicle waits for a tag, and a draft cannot get one", () => {
    const pending = { vehicle_id: vehicle().id, title: "Hbis 2253", replace: null, expires_at: NOW };
    expect(renderToStaticMarkup(<TagSection ctx={ctx} vehicle={vehicle()} pending={pending} />)).toContain("väntar på en tagg i 10 minuter");
    expect(renderToStaticMarkup(<TagSection ctx={ctx} vehicle={vehicle({ status: "draft" })} pending={null} />)).toContain("Spara fordonet som klart");
  });
});

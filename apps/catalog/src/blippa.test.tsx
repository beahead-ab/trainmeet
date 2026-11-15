import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Vehicle } from "./api";
import type { Ctx } from "./common";
import { text } from "./i18n";
import { isIos } from "./nfc";
import { PlacesView } from "./PlacesPage";
import { afterLinking, isSerialNumber, MiniCardView } from "./TagPage";
import { TapView } from "./TapPage";
import { Notices, WritePanel } from "./VehicleCard";

const ctx: Ctx = { t: (key, vars) => text("sv", key, vars), language: "sv" };
const account = { id: "8a3e1f0c-1111-5222-8333-944455556666", name: "Provkonto A", initials: "PA" };
const card = { litt: "Hbis", number: "2253", kind: "freight_wagon" as const, operator: "Green Cargo", scale: "H0", thumbnail: null };
const VEHICLE = "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed";

describe("Blippa (CAT-114, CAT-117, CAT-119)", () => {
  const view = (reader: "nfc" | "ios" | "none", scanning = false, logged: typeof account | null = account) =>
    renderToStaticMarkup(<TapView ctx={ctx} account={logged} simulated={false} reader={reader} scanning={scanning} error={null} />);

  it("starts reading on Android, and says to hold the phone to the tag", () => {
    expect(view("nfc")).toContain(">Börja blippa<");
    expect(view("nfc", true)).toContain("Håll telefonen mot taggen under fordonet.");
    expect(view("nfc", true)).toContain(">Sluta<");
  });

  it("explains the iPhone's own reader, and Safari's own login", () => {
    expect(view("ios")).toContain("iPhone läser bara taggar som redan bär adressen");
    expect(view("ios", false, null)).toContain("Safari och Catalog på hemskärmen har var sin inloggning.");
    expect(view("ios")).not.toContain("Börja blippa");
  });

  it("says when the browser cannot read NFC", () => {
    expect(view("none")).toContain("Den här webbläsaren kan inte läsa NFC-taggar.");
  });

  it("knows an iPhone", () => {
    expect(isIos("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)")).toBe(true);
    expect(isIos("Mozilla/5.0 (Linux; Android 15; Pixel 9) Chrome/140")).toBe(false);
  });
});

describe("writing the address on the tag (CAT-118)", () => {
  it("is offered on Android after linking a physical tag, not a simulated one or a QR label", () => {
    expect(afterLinking(VEHICLE, "04a1b2c3d4e5f6", true)).toBe(`/fordon/${VEHICLE}?skriv=04a1b2c3d4e5f6`);
    expect(afterLinking(VEHICLE, "04a1b2c3d4e5f6", false)).toBe(`/fordon/${VEHICLE}`);
    expect(afterLinking(VEHICLE, "6f1d2c1e-6a43-4b8e-9c5a-0c3a7d4f9b21", true)).toBe(`/fordon/${VEHICLE}`);
    expect(isSerialNumber("qabcdefghjk2")).toBe(false);
    expect(isSerialNumber("04:A1:B2:C3")).toBe(true);
  });

  it("asks to hold the tag to the phone again, and says when it is done", () => {
    const address = "https://trainmeet.app/t/04a1b2c3d4e5f6";
    expect(renderToStaticMarkup(<WritePanel t={ctx.t} address={address} state="ready" />)).toContain("Håll taggen mot telefonen igen");
    expect(renderToStaticMarkup(<WritePanel t={ctx.t} address={address} state="done" />)).toContain("Adressen är skriven på taggen.");
    expect(renderToStaticMarkup(<WritePanel t={ctx.t} address={address} state="failed" />)).toContain("Adressen gick inte att skriva.");
  });
});

describe("Säg till ägaren (CAT-113)", () => {
  it("lets someone logged in tell the owner, and asks others to log in", () => {
    const logged = renderToStaticMarkup(<MiniCardView t={ctx.t} found={{ outcome: "private", card }} loggedIn />);
    expect(logged).toContain("Var står fordonet?");
    expect(logged).toContain("du får inte veta vem ägaren är");
    expect(renderToStaticMarkup(<MiniCardView t={ctx.t} found={{ outcome: "private", card }} />)).toContain("Logga in för att säga till ägaren");
    expect(renderToStaticMarkup(<MiniCardView t={ctx.t} found={{ outcome: "private", card }} loggedIn told />)).toContain("Ägaren har fått beskedet.");
  });

  it("shows the owner what someone said, without who", () => {
    const vehicle = { notices: [{ id: "n1", text: "Står på spår 3", at: "2026-11-15T12:00:00Z" }] } as unknown as Vehicle;
    const html = renderToStaticMarkup(<Notices ctx={ctx} vehicle={vehicle} />);
    expect(html).toContain("Någon sa till");
    expect(html).toContain("«Står på spår 3»");
  });
});

describe("Visa mitt namn (CAT-101)", () => {
  it("is a switch, off from the start", () => {
    const html = renderToStaticMarkup(<PlacesView ctx={ctx} places={[]} lent={[]} error={null} showName={false} />);
    expect(html).toContain('role="switch"');
    expect(html).toContain("Visa mitt namn när någon blippar mina fordon");
    expect(html).not.toContain("checked");
  });
});

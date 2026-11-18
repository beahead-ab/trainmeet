import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ApiError, PICTURE_MAX_BYTES, uploadAddress, workIn, type Picture, type StorageUse, type Vehicle, type VehicleList } from "./api";
import type { Ctx } from "./common";
import { text, TEXTS } from "./i18n";
import { checkPicture, pictureProblem, PicturesView, storageText, type PicturesViewProps } from "./Pictures";
import { CardView } from "./VehicleCard";
import { VehiclesView } from "./VehiclesPage";

const ctx = (language: "sv" | "en" = "sv"): Ctx => ({ t: (key, vars) => text(language, key, vars), language });
const viewer: Ctx = { ...ctx(), right: "view", fleetTitle: "Vagnparken · Provkonto A" };
const editor: Ctx = { ...ctx(), right: "edit", fleetTitle: "Vagnparken · Provkonto A" };
const account = { id: "8a3e1f0c-1111-5222-8333-944455556666", name: "Provkonto A", initials: "PA" };
const NOW = "2026-11-15T12:00:00Z";
const MB = 1024 * 1024;
const t = ctx().t;

function vehicle(change: Partial<Vehicle> = {}): Vehicle {
  return {
    id: "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
    version: 1,
    status: "ready",
    kind: "freight_wagon",
    litt: "Hbis",
    number: "2253",
    operator: "Green Cargo",
    epoch: "V",
    scale: "H0",
    maker: "",
    article_number: "",
    note: "",
    dcc_address: "",
    functions: [],
    place: null,
    place_name: null,
    state: "home",
    lending: null,
    evn: null,
    field_sources: {},
    tags: [],
    tagged: false,
    picture: { thumb_url: "https://bilder.example/m2.jpg", display_url: "https://bilder.example/d2.jpg" },
    created_at: NOW,
    updated_at: NOW,
    ...change,
  };
}

function picture(n: number, change: Partial<Picture> = {}): Picture {
  return {
    id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
    main: false,
    position: n - 1,
    width: 1800,
    height: 1200,
    bytes: 400_000,
    display_url: `https://bilder.example/d${n}.jpg`,
    thumb_url: `https://bilder.example/m${n}.jpg`,
    original_url: null,
    background: "original",
    ...change,
  };
}

const storage = (change: Partial<StorageUse> = {}): StorageUse => ({ used: 12 * MB, limit: 100 * MB, club: false, pictures: 3, backgrounds: true, ...change });
const three = [picture(1), picture(2, { main: true, background: "white" }), picture(3)];

function view(props: Partial<PicturesViewProps> = {}): string {
  return renderToStaticMarkup(<PicturesView ctx={ctx()} vehicle={vehicle()} pictures={three} storage={storage()} work={null} error={null} {...props} />);
}

function list(vehicles: Vehicle[]): VehicleList {
  return { vehicles, counts: { home: vehicles.length, packed: 0, at_meet: 0, lent: 0 }, total: vehicles.length };
}

describe("the pictures on the card (CAT-05, CAT-125)", () => {
  it("shows the main picture large, and all of them as thumbnails in their order", () => {
    const html = view();
    expect(html).toContain('<img src="https://bilder.example/d2.jpg" alt="Hbis 2253, bild 2 av 3" width="1800" height="1200"/>');
    expect(html).not.toContain("d1.jpg");
    const thumbs = [...html.matchAll(/src="https:\/\/bilder\.example\/(m\d)\.jpg"/g)].map((match) => match[1]);
    expect(thumbs).toEqual(["m1", "m2", "m3"]);
    expect(html).toContain('aria-pressed="true" aria-label="Visa bild 2 av 3, Huvudbild"');
    expect(html).toContain("Huvudbild · Bakgrund: Vit");
  });

  it("gives the one who edits the add control, Spara original, the backgrounds and the storage", () => {
    const html = renderToStaticMarkup(
      <CardView ctx={editor} vehicle={vehicle()} events={[]} error={null} pictures={<PicturesView ctx={editor} vehicle={vehicle()} pictures={three} storage={storage()} work={null} error={null} />} />,
    );
    expect(html).toContain('<h2 id="bilder-rubrik">Bilder</h2>');
    expect(html).toContain("3 av 10");
    expect(html).toMatch(/<input class="cat-dold" type="file" accept="image\/jpeg,image\/png,image\/webp"/);
    expect(html).toContain(">Lägg till bild<");
    expect(html).toContain("Spara original");
    for (const label of ["Original", "Vit", "Grå", "Genomskinlig", "Räls"]) expect(html).toContain(`>${label}</option>`);
    expect(html).toContain(">Byt bakgrund<");
    expect(html).toContain(">Ta bort<");
    expect(html).not.toContain(">Gör till huvudbild<"); // the main picture is the one shown
    expect(html).toContain("Ägarens lagring: 12 av 100 MB"); // CAT-133
    expect(html.indexOf("bilder-rubrik")).toBeLessThan(html.indexOf("kortet-rubrik"));
    expect(view()).toContain("Lagring: 12 av 100 MB");
  });

  it("offers Gör till huvudbild on a picture that is not the main one", () => {
    const html = view({ chosen: three[0]!.id });
    expect(html).toContain('<img src="https://bilder.example/d1.jpg" alt="Hbis 2253, bild 1 av 3"');
    expect(html).toContain(">Gör till huvudbild<");
    expect(html).toContain("Bild 1 av 3 · Bakgrund: Original");
  });

  it("shows someone who may only look the pictures, without a button", () => {
    const html = renderToStaticMarkup(
      <CardView ctx={viewer} vehicle={vehicle()} events={[]} error={null} pictures={<PicturesView ctx={viewer} vehicle={vehicle()} pictures={three} storage={null} work={null} error={null} />} />,
    );
    expect(html).toContain('src="https://bilder.example/d2.jpg"');
    expect(html).toContain('src="https://bilder.example/m3.jpg"');
    for (const control of ["Gör till huvudbild", "Byt bakgrund", ">Ta bort<", 'type="file"', "Spara original", "Lagring", "<select", "3 av 10"]) {
      expect(html).not.toContain(control);
    }
  });

  it("leaves the section out for someone who looks at a vehicle without pictures", () => {
    const none = vehicle({ picture: null });
    expect(renderToStaticMarkup(<PicturesView ctx={viewer} vehicle={none} pictures={[]} storage={null} work={null} error={null} />)).toBe("");
    const html = renderToStaticMarkup(<PicturesView ctx={ctx()} vehicle={none} pictures={[]} storage={storage({ used: 0, pictures: 0 })} work={null} error={null} />);
    expect(html).toContain("Inga bilder än.");
    expect(html).toContain(">Lägg till bild<");
    expect(html).not.toContain("cat-miniatyrer");
  });

  it("shows the vehicle's main picture while the pictures are read", () => {
    const html = view({ pictures: null });
    expect(html).toContain('<img src="https://bilder.example/d2.jpg" alt="Hbis 2253"/>');
    expect(html).toMatch(/type="file"[^>]*disabled=""/);
  });

  it("says when the vehicle has its 10 pictures, and the add control is off (CAT-17)", () => {
    const ten = Array.from({ length: 10 }, (_, index) => picture(index + 1, { main: index === 0 }));
    const html = view({ pictures: ten });
    expect(html).toContain("10 av 10");
    expect(html).toMatch(/<input class="cat-dold" type="file"[^>]*disabled=""/);
    expect(html).toContain("tm-knapp cat-bildknapp cat-av");
    expect(html).toContain("Fordonet har 10 bilder, så många som går. Ta bort en för att lägga till en ny.");
    expect(view()).not.toMatch(/type="file"[^>]*disabled=""/);
  });

  it("offers only the original background when the background removal is off (CAT-127, CAT-128)", () => {
    const off = storage({ backgrounds: false });
    const html = view({ storage: off, pictures: [picture(1, { main: true })] });
    expect(html).not.toContain("<select");
    expect(html).not.toContain("Räls");
    expect(html).not.toContain(">Byt bakgrund<");
    expect(html).toContain("Friläggningen är inte på just nu, så bilden behåller sin egen bakgrund.");
    // A picture that already has another background can still go back to the original.
    expect(view({ storage: off })).toContain(">Byt bakgrund<");
  });

  it("shows how far the upload has come, and stops the buttons meanwhile", () => {
    const sending = view({ work: { what: "upload", sent: 0.45 } });
    expect(sending).toContain('<progress max="1" value="0.45" aria-hidden="true"></progress><span>Skickar bilden … 45 %</span>');
    expect(sending).toMatch(/<button type="button" class="tm-knapp" disabled="">Byt bakgrund</);
    expect(sending).toMatch(/type="file"[^>]*disabled=""/);
    expect(view({ work: { what: "upload", sent: 1 } })).toContain('<progress max="1" aria-hidden="true"></progress><span>Bilden förbereds …</span>');
    expect(view({ work: { what: "background" } })).toContain("Byter bakgrund …");
    expect(view()).toContain('<div class="cat-arbete" aria-live="polite"></div>');
  });

  it("shows Catalog's no in the app's words", () => {
    expect(view({ error: t("problem_storage_full") })).toContain('role="alert">Lagringen är full.');
    expect(pictureProblem(t, new ApiError(413, null))).toBe(t("problem_picture_too_large"));
    expect(pictureProblem(t, new ApiError(503, "unavailable"))).toBe("Bilderna kan inte sparas just nu. Försök igen om en stund.");
    expect(pictureProblem(t, new ApiError(422, "too_many_pictures"))).toBe("Fordonet har redan 10 bilder. Ta bort en först.");
    expect(pictureProblem(t, new TypeError("offline"))).toBe(t("problem_other"));
    for (const code of ["bad_picture", "picture_too_large", "too_many_pictures", "storage_full", "backgrounds_off", "no_vehicle", "changed"]) {
      for (const language of ["sv", "en"] as const) expect(TEXTS[language]).toHaveProperty(`problem_${code}`);
    }
  });
});

describe("before a picture is sent (CAT-123)", () => {
  it("stops a picture over 15 MB, with Catalog's own words", () => {
    expect(checkPicture({ size: PICTURE_MAX_BYTES, type: "image/jpeg" })).toBeNull();
    expect(checkPicture({ size: PICTURE_MAX_BYTES + 1, type: "image/jpeg" })).toBe("picture_too_large");
    expect(t(`problem_${checkPicture({ size: 20 * MB, type: "image/png" })!}`)).toBe("Bilden är för stor. Högst 15 MB per bild.");
  });

  it("takes JPEG, PNG and WebP only", () => {
    for (const type of ["image/jpeg", "image/png", "image/webp"]) expect(checkPicture({ size: 1, type })).toBeNull();
    for (const type of ["image/heic", "image/gif", ""]) expect(checkPicture({ size: 1, type })).toBe("bad_picture");
  });

  it("sends Spara original and the background, in the fleet worked in", () => {
    const id = vehicle().id;
    expect(uploadAddress(id, false, "original")).toBe(`/api/catalog/1/vehicles/${id}/pictures?keep_original=false&background=original`);
    workIn("0f0e0d0c-3333-4444-8555-966677778888");
    expect(uploadAddress(id, true, "rails")).toBe(
      `/api/catalog/1/vehicles/${id}/pictures?keep_original=true&background=rails&fleet=0f0e0d0c-3333-4444-8555-966677778888`,
    );
    workIn(null);
  });
});

describe("the storage (CAT-131)", () => {
  it("counts in MB for a person and in GB for a club", () => {
    expect(storageText(t, "sv", { used: 12 * MB, limit: 100 * MB, club: false })).toBe("Lagring: 12 av 100 MB");
    expect(storageText(t, "sv", { used: 12.34 * MB, limit: 100 * MB, club: false })).toBe("Lagring: 12,3 av 100 MB");
    expect(storageText(t, "sv", { used: 400 * MB, limit: 2048 * MB, club: true })).toBe("Klubbens lagring: 0,4 av 2 GB");
    expect(storageText(t, "sv", { used: 400 * MB, limit: 2048 * MB, club: true }, true)).toBe("Klubbens lagring: 0,4 av 2 GB");
    expect(storageText(t, "sv", { used: 12 * MB, limit: 100 * MB, club: false }, true)).toBe("Ägarens lagring: 12 av 100 MB");
    expect(storageText(ctx("en").t, "en", { used: 12.34 * MB, limit: 100 * MB, club: false })).toBe("Storage: 12.3 of 100 MB");
    expect(storageText(t, "sv", { used: 0, limit: 100 * MB, club: false })).toBe("Lagring: 0 av 100 MB");
    expect(storageText(t, "sv", { used: 20_000, limit: 100 * MB, club: false })).toBe("Lagring: 0,1 av 100 MB");
  });
});

describe("the thumbnail in the list", () => {
  it("shows the main picture's thumbnail beside the name", () => {
    const bare = vehicle({ id: "2b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed", litt: "Gbs", number: "3112", picture: null });
    const html = renderToStaticMarkup(
      <VehiclesView ctx={ctx()} account={account} list={list([vehicle(), bare])} q="" state={null} group="all" selected={new Set()} error={null} />,
    );
    expect(html).toContain('<th class="cat-bildcell">Bild</th>');
    expect(html).toContain('<img class="cat-listbild" src="https://bilder.example/m2.jpg" alt="" width="72" height="48" loading="lazy" decoding="async"/>');
    expect(html).toContain('tabindex="-1" aria-hidden="true"');
    expect(html.match(/<td class="cat-bildcell">/g)).toHaveLength(2);
  });

  it("has no picture column when no vehicle has a picture", () => {
    const html = renderToStaticMarkup(
      <VehiclesView ctx={ctx()} account={account} list={list([vehicle({ picture: null })])} q="" state={null} group="all" selected={new Set()} error={null} />,
    );
    expect(html).not.toContain("cat-bildcell");
    expect(html).not.toContain("<img");
  });
});

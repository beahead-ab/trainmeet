// TKL i molnet (#88, TKL5): the login screen, Dina stationer with Öppna and Ny station, the account
// row with the choice when the cloud has a newer version (H71, TKLMOLN-09), the meets through the
// relay, and PROV (TKLMOLN-11). A made-up station; nothing here names a real one (RS13).
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { CloudStation, Meet, Saved, State } from "./api";
import { TraffarVy, wayOf } from "./Installningar";
import { copySaid, DinaStationerVy, Inloggning, KontoradVy, LOGIN } from "./Konto";
import { PROV_SAID, ProvChip, ProvRad } from "./Provmarkering";

/** The elements of a view's own tree; nested components are left as they are. */
function elements(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!isValidElement(node)) return [];
  const props = node.props as { children?: ReactNode };
  return [node as ReactElement<Record<string, unknown>>, ...elements(props.children)];
}

const textOf = (node: ReactNode): string => {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement(node)) return textOf((node.props as { children?: ReactNode }).children);
  return "";
};

const button = (found: ReactElement<Record<string, unknown>>[], label: string) => {
  const hit = found.find((e) => e.type === "button" && textOf(e.props.children as ReactNode).trim() === label);
  expect(hit, label).toBeTruthy();
  return hit as ReactElement<{ onClick: () => void; disabled?: boolean }>;
};

const cloudState = (more: Partial<State> = {}): State =>
  ({
    mode: "cloud",
    software: "TKL 0.1.0",
    set_up: false,
    unlocked: false,
    station: null,
    locked: false,
    remote: null,
    login: true,
    account: null,
    ...more,
  }) as State;

const opened = (more: Partial<NonNullable<State["account"]>> = {}): State =>
  cloudState({
    set_up: true,
    unlocked: true,
    station: { station_id: "exb", name: "Exempelby", level: 0, tried: false },
    account: { person: "Tomas Ek", base: 3, changed: false, ...more },
  });

const stations: CloudStation[] = [
  { station_id: "exb", name: "Exempelby", version: 3, saved: "2026-11-19T10:15:00Z" },
  { station_id: "vby", name: "Västby", version: 1, saved: "2026-11-18T08:00:00Z" },
];

describe("Logga in med TrainMeet ID (TKLMOLN-01, TKLMOLN-10)", () => {
  it("is the first thing TKL in the cloud shows, with no PIN", () => {
    const html = renderToStaticMarkup(<Inloggning state={cloudState()} />);
    expect(html).toContain(`id="id-login" class="knapp primar" href="${LOGIN}">Logga in med TrainMeet ID<`);
    expect(html).toContain("ingen PIN-kod");
    expect(html).not.toContain('type="password"');
    expect(html).not.toContain("Inloggningen gick inte");
  });

  it("opens a working copy locked with Lås, and says when the login failed", () => {
    const locked = cloudState({ set_up: true, unlocked: false, locked: true, station: { station_id: "exb", name: "Exempelby", level: 0, tried: false }, account: { person: "Tomas Ek", base: 1, changed: false } });
    const html = renderToStaticMarkup(<Inloggning state={locked} failed />);
    expect(html).toContain("Exempelby är låst.");
    expect(html).toContain("Logga in med TrainMeet ID igen för att låsa upp.");
    expect(html).toContain("Inloggningen gick inte. Försök igen.");
  });
});

describe("Dina stationer (TKLMOLN-02)", () => {
  const view = (more: Partial<Parameters<typeof DinaStationerVy>[0]> = {}) => ({
    person: "Tomas Ek",
    stations,
    open: null,
    openName: null,
    changed: false,
    busy: false,
    message: "",
    onOpen: vi.fn(),
    onNew: vi.fn(),
    onRemote: vi.fn(),
    onBack: null,
    ...more,
  });

  it("lists the account's stations with their version, and Öppna opens one", () => {
    const props = view();
    const html = renderToStaticMarkup(<DinaStationerVy {...props} />);
    expect(html).toContain("<b>Exempelby</b>");
    expect(html).toContain(" · version 3 · sparad ");
    expect(html).toContain("<b>Västby</b>");
    expect(html).toContain("Ny station");
    expect(html).toContain("Skapa och spara i molnet");
    button(elements(DinaStationerVy(props)), "Öppna").props.onClick();
    expect(props.onOpen).toHaveBeenCalledWith("exb");
  });

  it("marks the open station, and warns before its unsaved changes go", () => {
    const props = view({ open: "exb", openName: "Exempelby", changed: true, onBack: vi.fn() });
    const html = renderToStaticMarkup(<DinaStationerVy {...props} />);
    expect(html).toContain("Öppen här");
    expect(html).toContain("Exempelby har ändringar som inte är sparade i molnet.");
    const found = elements(DinaStationerVy(props));
    button(found, "Läs in igen").props.onClick();
    expect(props.onOpen).toHaveBeenCalledWith("exb");
    button(found, "Tillbaka till Exempelby").props.onClick();
    expect(props.onBack).toHaveBeenCalled();
  });

  it("says when there are none yet, and while it is fetching", () => {
    expect(renderToStaticMarkup(<DinaStationerVy {...view({ stations: [] })} />)).toContain("Du har inga stationer i molnet än.");
    expect(renderToStaticMarkup(<DinaStationerVy {...view({ stations: null })} />)).toContain("Hämtar dina stationer");
  });
});

describe("The account row: Spara i molnet and the choice (TKLMOLN-07, TKLMOLN-09, H71)", () => {
  const row = (state: State, saved: Saved | null = null) => ({ state, saved, busy: false, message: "", onSave: vi.fn(), onReadNew: vi.fn(), onStations: vi.fn() });

  it("says which version in the cloud the working copy builds on, and what is not saved", () => {
    expect(copySaid(3, false)).toBe("version 3 i molnet · sparad");
    expect(copySaid(3, true)).toBe("version 3 i molnet · osparade ändringar");
    expect(copySaid(null, true)).toBe("inte sparad i molnet än");
    const clean = row(opened());
    const html = renderToStaticMarkup(<KontoradVy {...clean} />);
    expect(html).toContain("<b>Exempelby</b>");
    expect(html).toContain("version 3 i molnet · sparad");
    expect(button(elements(KontoradVy(clean)), "Spara i molnet").props.disabled).toBe(true);
    const dirty = row(opened({ changed: true }));
    const save = button(elements(KontoradVy(dirty)), "Spara i molnet");
    expect(save.props.disabled).toBe(false);
    save.props.onClick();
    expect(dirty.onSave).toHaveBeenCalledWith(null);
    button(elements(KontoradVy(dirty)), "Dina stationer").props.onClick();
    expect(dirty.onStations).toHaveBeenCalled();
  });

  it("offers Läs in den nya and Spara ändå ovanpå when the cloud has a newer version", () => {
    const saved: Saved = { version: null, behind: 4, message: "Molnet har version 4, sparad från en annan dator eller flik efter den du arbetar i. Läs in den nya, eller spara ändå ovanpå om stationen här är den som gäller." };
    const props = row(opened({ changed: true }), saved);
    const html = renderToStaticMarkup(<KontoradVy {...props} />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("Molnet har version 4");
    const found = elements(KontoradVy(props));
    button(found, "Läs in den nya (version 4)").props.onClick();
    expect(props.onReadNew).toHaveBeenCalled();
    button(found, "Spara ändå ovanpå version 4").props.onClick();
    expect(props.onSave).toHaveBeenCalledWith(4);
  });

  it("says when the save went through", () => {
    const html = renderToStaticMarkup(<KontoradVy {...row(opened(), { version: 5, behind: null, message: null })} />);
    expect(html).toContain("Sparad som version 5 i molnet.");
  });

  it("is not there without an account", () => {
    expect(KontoradVy(row(cloudState({ login: false })))).toBeNull();
  });
});

describe("The meets through the relay, and PROV (TKLMOLN-03, TKLMOLN-11)", () => {
  const meets: Meet[] = [
    { meet: "hosttraffen", name: "Höstträffen", club_name: "Exempelby MJK", starts_on: "2026-11-20", ends_on: "2026-11-22", way: "relay", hub_name: "Pi:n hemma", address: "https://moln.example.test/relay/hub-1" },
    { meet: "vartraffen", name: "Vårträffen", club_name: "Exempelby MJK", starts_on: "2027-04-10", ends_on: "2027-04-10", way: "none", hub_name: null, address: null },
    { meet: null, name: "Provbanan", club_name: null, starts_on: null, ends_on: null, way: "preview", hub_name: "Molnet", address: "https://moln.example.test" },
  ];

  it("lists the account's meets with the way there, and Provbanan marked PROV", () => {
    const props = { meets: { meets, message: null }, chosen: null, code: "", sending: false, onChoose: vi.fn(), onCode: vi.fn(), onConnect: vi.fn() };
    const html = renderToStaticMarkup(<TraffarVy {...props} />);
    expect(html).toContain("<b>Höstträffen</b>");
    expect(html).toContain("Pi:n hemma leder träffen · genom molnhubbens relä");
    expect(html).toContain("Körs inte just nu");
    expect(html).toContain("Provkörning på Molnet, skild från de riktiga träffarna");
    expect(html.match(/>PROV</g)?.length).toBe(1);
    expect(wayOf(meets[0] as Meet)).toContain("relä");
    // A meet that is not run now has nothing to choose; the others have Välj.
    const choose = elements(TraffarVy(props)).filter((e) => e.type === "button");
    expect(choose.length).toBe(2);
    (choose[0] as ReactElement<{ onClick: () => void }>).props.onClick();
    expect(props.onChoose).toHaveBeenCalledWith(0);
  });

  it("asks for the code of the chosen meet and connects to its address", () => {
    const props = { meets: { meets, message: null }, chosen: 0, code: "123456", sending: false, onChoose: vi.fn(), onCode: vi.fn(), onConnect: vi.fn() };
    const html = renderToStaticMarkup(<TraffarVy {...props} />);
    expect(html).toContain("Kod");
    const form = elements(TraffarVy(props)).find((e) => e.type === "form") as ReactElement<{ onSubmit: (event: { preventDefault: () => void }) => void }>;
    form.props.onSubmit({ preventDefault: () => undefined });
    expect(props.onConnect).toHaveBeenCalledWith(meets[0]);
  });

  it("marks a preview run PROV, in the header and in Ställverket", () => {
    const chip = renderToStaticMarkup(<ProvChip />);
    expect(chip).toContain('class="tm-chip prov"');
    expect(chip).toContain(">PROV<");
    expect(chip).toContain(`title="${PROV_SAID}"`);
    const row = renderToStaticMarkup(<ProvRad hub="Molnet" />);
    expect(row).toContain('<span class="prov-markering">PROV</span>');
    expect(row).toContain("Provkörning i Provbanan på Molnet, skild från den riktiga träffen.");
    expect(row).toContain("Inget här går till träffen.");
  });
});

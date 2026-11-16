import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { DriftEvent, Now, PlanVersion } from "./api";
import { describe as text, shown } from "./drift";
import { newer, Spärrad, Versionsbyte } from "./Versionsbyte";

const now = { meet_id: "varnamo", version: 1, changes: [{ change_id: "c1", change: { kind: "cancel", train: "t43" }, status: "applied", train_number: "43", made: "06:00", waiting_for: [] }, { change_id: "c2", change: { kind: "number", train: "t44", number: "144" }, status: "applied", train_number: "44", made: "06:01", waiting_for: [] }] } as unknown as Now;
const versions = [1, 2].map((number) => ({ meet: "varnamo", number, published: "2026-11-16T09:00:00Z", checksum: "a".repeat(64) })) as PlanVersion[];

describe("Versionsbyte (TRAFIK-03, DRIFT-29, H4, H38, H66)", () => {
  it("offers the newest version after the one that runs", () => {
    expect(newer(versions, 1).map((v) => v.number)).toEqual([2]);
    const html = renderToStaticMarkup(<Versionsbyte now={now} pkg={null} versions={versions} preview={null} />);
    expect(html).toContain(">Version 2 finns<");
    expect(html).toContain(">Byt till version 2<");
    expect(renderToStaticMarkup(<Versionsbyte now={now} pkg={null} versions={versions.slice(0, 1)} preview={null} />)).toBe("");
  });

  it("lists the changes: the one taken into the version falls away, the rest kept by default", () => {
    const preview = { version: 2, changes: [{ change_id: "c1", included: true }, { change_id: "c2", included: false }], waits_for: [] };
    const html = renderToStaticMarkup(<Versionsbyte now={now} pkg={null} versions={versions} preview={preview} />);
    expect(html).toContain("<b>Inställt tåg 43</b>");
    expect(html).toContain("Med i version 2 · faller bort");
    expect(html).toContain("Ligger kvar ovanpå den nya versionen");
    expect(html).toContain('aria-pressed="true">Behåll</button>');
    expect(html).toContain('id="switch-go" type="button" class="primar">Byt till version 2<');
    const waits = renderToStaticMarkup(<Versionsbyte now={now} pkg={null} versions={versions} preview={{ ...preview, waits_for: ["8042"] }} />);
    expect(waits).toContain("Tåg 8042 är ute och får ändringar i version 2. Bytet väntar tills de är framme, om du inte tvingar igenom det.");
    expect(waits).toContain(">Byt när tåg 8042 är framme<");
    expect(waits).toContain(">Tvinga igenom<");
  });

  it("says when a switch waits, with Tvinga igenom and Avbryt bytet", () => {
    const html = renderToStaticMarkup(<Versionsbyte now={{ ...now, switch: { version: 2, waits_for: ["8042"] } } as Now} pkg={null} versions={versions} preview={null} />);
    expect(html).toContain(">Byte till version 2 väntar<");
    expect(html).toContain("Tåg 8042 är ute och får ändringar i version 2. Bytet görs när de är framme.");
    expect(html).toContain(">Avbryt bytet<");
  });

  it("says Drift is locked, with Lås upp (DRIFT-47)", () => {
    const html = renderToStaticMarkup(<Spärrad now={{ ...now, locked: "version" } as Now} />);
    expect(html).toContain("Ett versionsbyte påbörjades och blev aldrig klart.");
    expect(html).toContain(">Lås upp<");
    expect(renderToStaticMarkup(<Spärrad now={now} />)).toBe("");
  });

  it("tells Logg of the switch, and keeps begun and done to Drift's own record", () => {
    const event = (kind: string, data: object = {}) => ({ kind, data }) as unknown as DriftEvent;
    expect(text(event("version.switched", { version: 2, forced: true }))).toBe("Version 2 körs nu, tvingad igenom");
    expect(text(event("version.waiting", { version: 2 }))).toBe("Byte till version 2 väntar på tåg som är ute");
    expect([shown(event("transition.begun")), shown(event("transition.done")), shown(event("transition.done", { unlocked: true }))]).toEqual([false, false, true]);
    expect(text(event("transition.done", { kind: "version", unlocked: true }))).toBe("Drift upplåst");
  });
});

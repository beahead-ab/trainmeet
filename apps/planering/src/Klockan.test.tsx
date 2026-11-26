import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Godkann, KlockanPage, chosenStyle } from "./Klockan";
import type { Draft } from "./api";

const nothing = () => undefined;
const draft = {
  package: {
    clock: { styles: ["custom:mitt-ur"] },
    attachments: [{ id: "mitt-ur", kind: "clock_face", filename: "mitt-ur.tmclock", media_type: "application/zip", size: 800, sha256: "ab".repeat(32) }],
  },
} as unknown as Draft;

describe("Klockan (F13, H75)", () => {
  it("is a page of the meet", () => {
    expect(chosenStyle(["digital", "custom:mitt-ur"])).toBe("custom:mitt-ur");
    expect(chosenStyle(["analog"])).toBe("analog");
  });

  it("lists the face, the style and the rights stamp", () => {
    const html = renderToStaticMarkup(
      <KlockanPage
        admin
        meet="grimslov"
        draft={draft}
        stamps={[{ id: "mitt-ur", name: "Mitt ur", filename: "mitt-ur.tmclock", at: "2026-11-23T18:00:00Z", by: "pin", warnings: [] }]}
        onDraft={nothing}
        onTell={nothing}
        onFail={nothing}
      />,
    );
    expect(html).toContain("träffens egna urtavlor");
    expect(html).toContain("custom:mitt-ur");
    expect(html).toContain('<p id="vald-stil">Mitt ur, egen urtavla</p>');
    expect(html).toContain("Visas på klockskärmen");
    expect(html).toContain("Godkänd att visas");
    expect(html).toContain("av den som har PIN");
    expect(html).toContain('id="klockfil"');
    expect(html).toContain('accept=".tmclock,.zip,application/zip"');
  });

  it("asks for the right before anything is saved, one clock at a time", () => {
    const html = renderToStaticMarkup(
      <Godkann
        text={{
          approve: "Godkänn urtavlorna",
          rightsNote: "Varje klocka godkänns för sig.",
          rights: "Jag intygar att jag har rätt att använda tavlan.",
          save: "Lägg in de godkända",
          cancel: "Avbryt",
          replaces: "Ersätter den som redan finns.",
          noWarnings: "Inga varningar.",
        } as never}
        preview={{
          packs: [
            { id: "ur-a", name: "Ur A", version: "1", warnings: ["dial.svg: text"], replaces: false, unchanged: false, layers: { dial: "data:image/svg+xml,a" }, dark: {} },
            { id: "ur-b", name: "Ur B", version: "1", warnings: [], replaces: true, unchanged: true, layers: {}, dark: {} },
          ],
        }}
        onSave={nothing}
        onCancel={nothing}
      />,
    );
    expect(html).toContain("Ur A");
    expect(html).toContain("Ur B");
    expect(html).toContain("dial.svg: text");
    expect(html).toContain("Ersätter den som redan finns.");
    expect(html).toContain('id="ratt"');
    expect(html).toContain("disabled");
  });
});

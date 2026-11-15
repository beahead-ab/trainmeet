import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Frame } from "./api";
import { BoxPage, onProvbanan, type BoxPageProps } from "./App";

const session = { client_id: "c1", session_key: "k".repeat(40), name: "Box 12" };
const frame = { station: "Norrby", lines: ["Norrby          ", "1:Begär         "], keys: { "1": { label: "Begär", short: "Begär", acts: true } }, view_token: "v1", attention: { epoch: "e", seq: 1, kind: null }, entry: { lines: [], labels: {} }, status: "Ingen klarering", requests: { label: "1 begäran väntar", count: 1 } } as unknown as Frame;

const render = (change: Partial<BoxPageProps> = {}) =>
  renderToStaticMarkup(<BoxPage provbanan={false} hubName="Testhubben" session={null} frame={null} entry={null} message="" loginError="" code="" {...change} />);

describe("TMBox web (BOXWEB-01, BOXWEB-10)", () => {
  it("says where the code comes from: Anslut on /box, Boxar on /provbanan/box", () => {
    const meet = render();
    expect(meet).toContain('<a href="/">← Hubben</a>');
    expect(meet).toContain("under Anslut");
    expect(meet).toContain('pattern="[0-9]{6}"');
    const trial = render({ provbanan: true, code: "123456" });
    expect(trial).toContain('<a href="/provbanan">← Provbanan</a>');
    expect(trial).toContain("under Boxar");
    expect(trial).toContain('value="123456"');
    expect(onProvbanan("/provbanan/box")).toBe(true);
    expect(onProvbanan("/box")).toBe(false);
  });

  it("is built as the old web box: tmbox-case > lcd-frame > lcd, and 16 keys with A–D as function keys", () => {
    const html = render({ session, frame });
    expect(html).toContain('<div class="tmbox-case"><div class="lcd-frame"><div id="lcd" class="lcd" role="img"');
    expect((html.match(/class="lcd-row"/g) ?? []).length).toBe(2);
    expect((html.match(/class="lcd-cell"/g) ?? []).length).toBe(32);
    expect((html.match(/class="key( function)?"/g) ?? []).length).toBe(16);
    expect((html.match(/class="key function"/g) ?? []).length).toBe(4);
    expect(html).toContain('aria-label="1 · Begär"');
    expect(html).toContain("Box 12 · Norrby");
    expect(html).toContain("Ingen klarering");
    expect(html).toContain('class="boxko vantar"');
  });
});

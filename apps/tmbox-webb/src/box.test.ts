import { describe, expect, it } from "vitest";
import type { Frame } from "./api";
import { parseEvents } from "./api";
import { columnsOf, keyFor, labels, press, shownLines } from "./box";

const frame = (change: Partial<Frame> = {}): Frame =>
  ({
    profile: "terminal16",
    device_id: "box-1",
    station: "Norrby",
    station_code: "Nb",
    rows: 2,
    cols: 16,
    lines: ["Norrby          ", "A:Begär  C:Kö   "],
    lcd: {},
    attention: { epoch: "e1", seq: 1, kind: null },
    view_token: "v1",
    revision: 1,
    view_revision: 1,
    input_guard_ms: 500,
    language: "sv",
    keys: { A: { label: "Begär", short: "Begär", acts: true }, C: { label: "Kö", short: "Kö", acts: false } },
    entry: { context: "train", max_length: 5, lines: ["Tåg:            ", "#:OK   *:Avbryt "], lcd: {}, row: 0, column: 5, commit: "#", cancel: "*", erase: "B", shortcut: "A", labels: { "#": "OK", "*": "Avbryt" } },
    ...change,
  }) as Frame;

describe("the box's keys (BOXWEB-03)", () => {
  it("keeps the typed train number until #, and sends it with the entry's context", () => {
    let entry: string | null = null;
    for (const key of ["4", "7", "1"] as const) entry = press(frame(), entry, key, 9999).entry;
    expect(entry).toBe("471");
    expect(shownLines(frame(), entry)[0]).toBe("Tåg: 471__      ");
    expect(press(frame(), entry, "B", 9999).entry).toBe("47");
    expect(press(frame(), entry, "*", 9999)).toEqual({ entry: null });
    expect(press(frame(), entry, "#", 9999)).toEqual({ entry: null, send: { key: "#", train_number: "471", entry_context: "train" } });
    expect(press(frame(), "", "#", 9999)).toEqual({ entry: null });
    expect(press(frame(), "12345", "6", 9999).entry).toBe("12345"); // at most max_length
  });

  it("sends a key that does something, and waits a moment after a new picture", () => {
    expect(press(frame(), null, "A", 9999).send).toEqual({ key: "A" });
    expect(press(frame(), null, "A", 100).send).toBeUndefined(); // input_guard_ms
    expect(press(frame(), null, "1", 9999)).toEqual({ entry: "1" }); // a digit always types the number
    expect(press(frame(), null, "C", 100).send).toEqual({ key: "C" }); // does not change the traffic
    expect(press(frame(), null, "D", 9999).send).toBeUndefined(); // does nothing now
    expect(press(frame({ waiting: true }), null, "A", 9999)).toEqual({ entry: null });
  });

  it("names what the keys do, and maps the keyboard to the keypad", () => {
    expect(labels(frame(), null)).toEqual({ A: "Begär", C: "Kö" });
    expect(labels(frame(), "4")).toEqual({ "#": "OK", "*": "Avbryt" });
    expect(labels(frame({ waiting: true }), null)).toEqual({});
    expect([keyFor("Enter"), keyFor("Backspace"), keyFor("Escape"), keyFor("a"), keyFor("x")]).toEqual(["#", "B", "*", "A", null]);
  });

  it("draws 16 cells, or as many as a 20×4 box announced", () => {
    expect(columnsOf(frame().lines)).toBe(16);
    expect(columnsOf(["Norrby              ", "", "", ""])).toBe(20);
  });

  it("reads the hub's events from the stream, also when a chunk is cut in two", () => {
    const first = parseEvents('event: frame\ndata: {"a":1}\n\nevent: fr');
    expect(first.events).toEqual([{ event: "frame", data: '{"a":1}' }]);
    const second = parseEvents(first.rest + "ame\ndata: {}\n\n: vänta\n\nevent: gone\ndata: {}\n\n");
    expect(second.events.map((e) => e.event)).toEqual(["frame", "message", "gone"]);
  });
});

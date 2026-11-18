import { describe as group, expect, it } from "vitest";
import type { DriftEvent, Now } from "./api";
import { busyTrains, buildChange, changeText, emptyDraft, KINDS, statusText, type ChangeNow, type DriftChange, type Package } from "./changes";
import { describe } from "./drift";

const call = (id: string, place: string, arrival: string | null, departure: string | null) => ({ id, place, arrival, departure, track: "1", day_offset: 0, stops: true, exchange: true, note: null });
const pkg = {
  places: [
    { id: "nby", code: "Nby", name: "Norrby", kind: "manned", tracks: [{ name: "1" }, { name: "2" }] },
    { id: "lvh", code: "Lvh", name: "Lövhult", kind: "halt", tracks: [] },
    { id: "asn", code: "Asn", name: "Åsen", kind: "manned", tracks: [{ name: "1" }] },
  ],
  sections: [{ id: "s1", place_a: "nby", place_b: "asn" }],
  trains: [
    { id: "t102", number: "102", days: ["mon"], calls: [call("t102-asn", "asn", null, "06:20"), call("t102-nby", "nby", "06:30", null)] },
    { id: "t101", number: "101", days: ["mon"], calls: [call("t101-nby", "nby", null, "06:00"), call("t101-lvh", "lvh", "06:04", "06:04"), call("t101-asn", "asn", "06:08", null)] },
  ],
} as unknown as Package;
const now = { traffic_day: "mon", clock: { time: "07:00" }, clearances: [{ train_number: "101", section: "s1" }] } as unknown as Now;

group("Driftändringar (DRIFT-41, TRAFIK-02)", () => {
  it("has the ten kinds of the prototype", () => {
    expect(KINDS.map(([kind]) => kind)).toEqual(["cancel", "extra", "times", "place", "track", "tracks", "days", "number", "no_stop", "note"]);
  });

  it("says what each change does", () => {
    const text = (change: unknown, number: string | null = null) => changeText(change as DriftChange, pkg, number);
    expect(text({ kind: "cancel", train: "t101" })).toBe("Inställt tåg 101");
    expect(text({ kind: "cancel", train: "t9" }, "43")).toBe("Inställt tåg 43");
    expect(text({ kind: "extra", number: "9101", departure: "07:30", copy_of: "t101" })).toBe("Extratåg 9101, kopia av 101 kl. 07:30");
    expect(text({ kind: "extra", number: "9801", departure: "10:00", copy_of: null, from_place: "nby", to_place: "asn" })).toBe("Extratåg 9801 Norrby–Åsen kl. 10:00");
    expect(text({ kind: "times", train: "t101", minutes: 10, from_call: "t101-asn", calls: [] })).toBe("Tåg 101: +10 min från Åsen");
    expect(text({ kind: "times", train: "t101", minutes: -5, from_call: null, calls: [] })).toBe("Tåg 101: −5 min");
    expect(text({ kind: "place", section: "s1", closed: true })).toBe("Sträckan Nby–Asn stängd");
    expect(text({ kind: "place", section: "s1", closed: null, clearance_mode: "direct" })).toBe("Sträckan Nby–Asn klareras direkt");
    expect(text({ kind: "place", section: null, place: "asn", place_kind: "unmanned" })).toBe("Åsen obemannad, sköts av automatiken");
    expect(text({ kind: "track", call: "t101-asn", track: "2" }, "101")).toBe("Tåg 101 i Åsen: spår 2");
    expect(text({ kind: "tracks", section: "s1", tracks: "double" })).toBe("Sträckan Nby–Asn dubbelspårig");
    expect(text({ kind: "days", train: "t101", days: ["sat", "sun"] })).toBe("Tåg 101 går lördag, söndag");
    expect(text({ kind: "number", train: "t101", number: "111" }, "101")).toBe("Tåg 101 får nummer 111");
    expect(text({ kind: "no_stop", call: "t101-asn", stops: false }, "101")).toBe("Tåg 101 passerar utan uppehåll Åsen");
    expect(text({ kind: "note", train: "t101", text: "Ånglok" })).toBe("Anmärkning på tåg 101: Ånglok");
  });

  it("says where a change stands", () => {
    const change = (part: Partial<ChangeNow>) => ({ status: "applied", forced: false, waiting_for: [], ...part }) as ChangeNow;
    expect(statusText(change({}))).toBe("Gäller");
    expect(statusText(change({ forced: true }))).toBe("Gäller, tvingad igenom");
    expect(statusText(change({ status: "waiting", waiting_for: ["101"] }))).toBe("Väntar på tåg 101");
    expect(statusText(change({ status: "dropped" }))).toBe("Släppt");
    expect(statusText(change({ proposal: "waiting" }))).toBe("Gäller · förslaget väntar i Planering");
    expect(statusText(change({ proposal: "taken" }))).toBe("Gäller · tagen med i nästa version");
    expect(statusText(change({ status: "dropped", proposal: "withdrawn" }))).toBe("Släppt · förslaget återtaget");
  });

  it("turns the form into a change, or says what is missing", () => {
    const draft = (kind: Parameters<typeof emptyDraft>[0], part: object = {}) => ({ ...emptyDraft(kind, now), ...part });
    expect(buildChange(draft("cancel"))).toBe("Välj ett tåg.");
    expect(buildChange(draft("cancel", { train: "t101" }))).toEqual({ kind: "cancel", train: "t101" });
    expect(buildChange(draft("extra", { number: "9101", copyOf: "t101" }))).toEqual({ kind: "extra", number: "9101", departure: "07:00", copy_of: "t101", from_place: null, to_place: null, days: ["mon"], calls: [], paper: null });
    expect(buildChange(draft("extra", { number: "9", copy: false, from: "nby", to: "nby" }))).toBe("Från och till är samma driftplats.");
    expect(buildChange(draft("times", { train: "t101", minutes: "x" }))).toBe("Skriv hur många minuter, till exempel 10 eller −5.");
    expect(buildChange(draft("times", { train: "t101", minutes: "-5", call: "t101-asn" }))).toEqual({ kind: "times", train: "t101", minutes: -5, from_call: "t101-asn", calls: [] });
    expect(buildChange(draft("place", { section: "s1", sectionChange: "direct" }))).toEqual({ kind: "place", section: "s1", closed: null, clearance_mode: "direct", place: null, place_kind: null });
    expect(buildChange(draft("place", { onSection: false, place: "asn" }))).toEqual({ kind: "place", section: null, closed: null, clearance_mode: null, place: "asn", place_kind: "unmanned" });
    expect(buildChange(draft("days", { train: "t101", days: [] }))).toBe("Välj minst en dag.");
    expect(buildChange(draft("note", { train: "t101", text: " " }))).toEqual({ kind: "note", train: "t101", call: null, text: null });
  });

  it("says when the change will wait for a train that is out", () => {
    expect(busyTrains({ ...emptyDraft("cancel", now), train: "t101" }, pkg, now)).toEqual(["101"]);
    expect(busyTrains({ ...emptyDraft("cancel", now), train: "t102" }, pkg, now)).toEqual([]);
    expect(busyTrains({ ...emptyDraft("tracks", now), section: "s1" }, pkg, now)).toEqual(["101"]);
    expect(busyTrains({ ...emptyDraft("note", now), train: "t101" }, pkg, now)).toEqual([]);
  });

  it("tells Logg what was done", () => {
    const event = (kind: string, data: object) => ({ kind, data }) as unknown as DriftEvent;
    expect(describe(event("change.made", { change: { kind: "cancel", train: "t9" }, train_number: "43", waiting: true }), pkg)).toBe("Driftändring: Inställt tåg 43, väntar på tåget");
    expect(describe(event("change.applied", { change_id: "c1", forced: true }))).toBe("Driftändringen gäller nu, tvingad igenom");
    expect(describe(event("change.dropped", { change_id: "c1" }))).toBe("Driftändringen släppt");
  });
});

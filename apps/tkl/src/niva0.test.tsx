import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CallHere, Outside, Snapshot } from "./api";
import { FirstStart, shortId } from "./Forsta";
import { happenings } from "./handelser";
import { Molnet } from "./Installningar";
import { readSounds } from "./ljud";
import { blocks, clockAt, revisionOf, trains } from "./niva0";
import { Stallverket } from "./Stallverket";
import { problems } from "./Studio";

// Åsen in Provbanan, as the hub's snapshot has it: Norrby to the west, Mellanå to the east.
const call = (given: Partial<CallHere> & Pick<CallHere, "call" | "train_number">): CallHere => ({
  train: `t${given.train_number}`,
  train_label: null,
  train_type: null,
  manual: false,
  arrival: null,
  departure: null,
  day_offset: 0,
  planned_track: null,
  track: null,
  from_place: null,
  to_place: null,
  arrival_state: "none",
  departure_state: "planned",
  positioned: false,
  crew_ready: false,
  revision: 0,
  allowed_actions: [],
  paper: false,
  ...given,
});

const base: Snapshot = {
  protocol: "trainmeet.station/1",
  place: { place: "asn", code: "Ån", name: "Åsen", phone: "22" },
  context: { meet_id: "provbanan", version: 1, game_day: 1, epoch: 0 },
  clock: { time: "06:10:00", seconds: 6 * 3600 + 600, running: true, speed: 4, game_day: 1 },
  place_revision: 3,
  sections: [
    { section: "s-nby-asn", other_place: "nby", other_code: "Nby", tracks: "single", clearance_mode: "requested", side: "left", exit: "v", occupied: false },
    { section: "s-asn-mla", other_place: "mla", other_code: "Mlå", tracks: "double", clearance_mode: "requested", side: "right", exit: "o", occupied: true },
  ],
  calls: [
    call({ call: "t102-asn", train_number: "102", arrival: "06:24", departure: "06:26", planned_track: "2", from_place: "mla", to_place: "nby", arrival_state: "on_the_way", allowed_actions: ["train.arrived", "train.track.change"] }),
    call({ call: "t101-asn", train_number: "101", arrival: "06:08", departure: "06:10", planned_track: "1", track: "1", from_place: "nby", to_place: "mla", arrival_state: "arrived", allowed_actions: ["clearance.request", "line.available.publish", "train.track.change"] }),
    call({ call: "t4501-asn", train_number: "4501", arrival: "06:43", departure: "06:45", planned_track: "1", from_place: "nby", to_place: "mla" }),
  ],
  on_the_way: [{ call: "t102-asn", train_number: "102", train_type: null, section: "s-asn-mla", other_place: "mla", planned_track: "2", departed_at: "06:05", paper: false }],
  have_left: [],
  clearances: [
    { clearance_id: "c-7", call: "t7-nby", train_number: "7", section: "s-nby-asn", from_place: "nby", to_place: "asn", status: "waiting", departed: false, requested_at: "06:06", reminders: 1, revision: 2, paper: false },
  ],
  line_messages: [],
  neighbours: [
    { place: "nby", code: "Nby", name: "Norrby", phone: "21" },
    { place: "mla", code: "Mlå", name: "Mellanå", phone: null },
  ],
  all_places: [
    { place: "nby", code: "Nby", name: "Norrby", phone: "21" },
    { place: "asn", code: "Ån", name: "Åsen", phone: "22" },
    { place: "mla", code: "Mlå", name: "Mellanå", phone: null },
  ],
  automatic: false,
  questions: [],
};

const calls: CallHere[] = base.calls;

const outside: Outside = {
  format: "trainmeet.station-outside/1",
  station_id: "asen",
  name: "Åsen",
  tracks: [
    { id: "1", label: "Spår 1" },
    { id: "2", label: "Spår 2" },
  ],
  exits: [
    { id: "v", side: "left", name: "Mot Norrby", tracks: [], signals: [] },
    { id: "o", side: "right", name: "Mot Mellanå", tracks: [], signals: [] },
  ],
  sides: [],
};

describe("Tåg (KLAR-03, H22, H32)", () => {
  it("on its way here, at the station and next by the timetable", () => {
    const seen = trains(base);
    expect(seen.coming.map((c) => [c.train.train_number, c.from, c.exit, c.call?.call])).toEqual([["102", "Mellanå", "o", "t102-asn"]]);
    expect(seen.atStation.map((a) => [a.call.train_number, a.to])).toEqual([["101", "Mellanå"]]);
    expect(seen.next.map((n) => [n.time, n.kind, n.call.train_number, n.other])).toEqual([["06:43", "Ank", "4501", "Norrby"]]);
  });

  it("draws Ankommit, the track and the clearance view (TKLAPP 02)", () => {
    const html = renderToStaticMarkup(
      <Stallverket view={{ snapshot: base, stale: false, heard: null, message: null }} outside={outside} journal={[]} sounds={readSounds(null)} busy={false} onSend={() => undefined} onExit={() => undefined} />,
    );
    expect(html).toContain("Nivå 0");
    expect(html).toContain("Klarering utan spårplan.");
    expect(html).toContain("Ljud på för begäran, tåg på väg hit, larm");
    expect(html).toContain(">Ankommit<");
    expect(html).toContain("planerat spår 2");
    expect(html).toContain('aria-label="Byt spår för 102"');
    expect(html).toContain("Norrby begär klart för <b class=\"tm-mono\">7</b> hit");
    expect(html).toContain("▲ Påminnelse");
    expect(html).toContain(">Ge klart<");
    expect(html).toContain(">Neka<");
    expect(html).toContain("Norrby v · enkelspår · väster");
    expect(html).toContain("tel 21");
    expect(html).toContain("Linjen har ett tåg på sig.");
    expect(html).toContain(">Linjen ledig<");
    expect(html).toContain("Inget har hänt sedan sidan öppnades.");
  });

  it("stays at level 0 when the station has a track plan, and says the rest comes next (#83)", () => {
    const view = { snapshot: base, stale: false, heard: null, message: null };
    const plain = renderToStaticMarkup(<Stallverket view={view} outside={outside} journal={[]} sounds={readSounds(null)} busy={false} onSend={() => undefined} onExit={() => undefined} />);
    expect(plain).not.toContain("Stationen har en spårplan");
    const html = renderToStaticMarkup(<Stallverket view={view} level={2} outside={outside} journal={[]} sounds={readSounds(null)} busy={false} onSend={() => undefined} onExit={() => undefined} />);
    expect(html).toContain("Stationen har en spårplan; ställverket på nivå 1–2 kommer med nästa steg.");
    expect(html).toContain("Klarering utan spårplan.");
  });

  it("asks for the line for the train at the station, when it may", () => {
    const free = { ...base, sections: base.sections.map((s) => ({ ...s, occupied: false })), on_the_way: [], clearances: [] };
    const [toNorrby, toMellana] = blocks(free, outside);
    expect(toNorrby?.canAsk).toBeUndefined();
    expect(toMellana?.canAsk?.train_number).toBe("101");
    expect(toMellana?.free).toBe(true);
  });

  it("says the hub could not be reached and keeps the last good picture", () => {
    const html = renderToStaticMarkup(
      <Stallverket view={{ snapshot: base, stale: true, heard: null, message: "Ingen kontakt med hubben." }} outside={outside} journal={[]} sounds={readSounds(null)} busy={false} onSend={() => undefined} onExit={() => undefined} />,
    );
    expect(html).toContain("Ingen kontakt med hubben. Det här är det senaste TKL fick");
  });

  it("shows Hubbens question about an exit with the station's exits (H26)", () => {
    const asked: Snapshot = {
      ...base,
      questions: [{ station_id: "mellana", place: "mla", section: "s-asn-mla", other_place: "asn", other_name: "Åsen", side: "left", alternatives: [{ exit: "AU", side: "left", name: "Åsen uppspår" }, { exit: "AN", side: "left", name: null }] }],
    };
    const html = renderToStaticMarkup(
      <Stallverket view={{ snapshot: asked, stale: false, heard: null, message: null }} outside={outside} journal={[]} sounds={readSounds(null)} busy={false} onSend={() => undefined} onExit={() => undefined} />,
    );
    expect(html).toContain("Vilken utfart går mot Åsen?");
    expect(html).toContain(">AU · Åsen uppspår<");
    expect(html).toContain(">AN<");
  });
});

describe("Händelser (KLAR-05) and the sounds (TKL33)", () => {
  it("writes what changed between two snapshots, latest first, with its sound", () => {
    expect(happenings(null, base)).toEqual([]);
    const later: Snapshot = {
      ...base,
      clock: { ...base.clock, time: "06:12:00" },
      place_revision: 4,
      clearances: [
        { ...base.clearances[0]!, status: "waiting", reminders: 2 },
        { clearance_id: "c-9", call: "t9-mla", train_number: "9", section: "s-asn-mla", from_place: "mla", to_place: "asn", status: "waiting", departed: false, requested_at: "06:11", reminders: 0, revision: 1, paper: false },
      ],
      calls: calls.map((c) => (c.call === "t102-asn" ? call({ ...c, arrival_state: "arrived", track: "2" }) : c)),
      on_the_way: [],
    };
    const found = happenings(base, later);
    expect(found.map((h) => [h.time, h.text, h.sound])).toEqual([
      ["06:12", "102 ankom spår 2 (knapp)", undefined],
      ["06:12", "Mellanå begär klart för 9 hit", "request"],
      ["06:12", "Påminnelse: Norrby väntar på svar för 7", "alarm"],
    ]);
    const coming = happenings({ ...base, on_the_way: [] }, base);
    expect(coming.map((h) => [h.text, h.sound])).toEqual([["102 avgick från Mellanå mot spår 2", "coming"]]);
  });

  it("keeps each screen's sounds, all on to begin with", () => {
    expect(readSounds(null)).toEqual({ request: true, coming: true, alarm: true });
    expect(readSounds({ getItem: () => JSON.stringify({ coming: false }) })).toEqual({ request: true, coming: false, alarm: true });
    expect(readSounds({ getItem: () => "inte json" })).toEqual({ request: true, coming: true, alarm: true });
  });
});

describe("The clock and the revisions", () => {
  it("runs the hub's clock on between snapshots at the meet's speed", () => {
    expect(clockAt(base, 0, 0)).toBe("06:10");
    expect(clockAt(base, 0, 30_000)).toBe("06:12");
    expect(clockAt({ ...base, clock: { ...base.clock, running: false } }, 0, 30_000)).toBe("06:10");
  });

  it("sends the call's or the clearance's own revision (v2 §5)", () => {
    expect(revisionOf("clearance.response", undefined, base.clearances[0])).toEqual({ scope: "case", key: "c-7", value: 2 });
    expect(revisionOf("train.arrived", base.calls[0], undefined)).toEqual({ scope: "call", key: "t102-asn", value: 0 });
  });
});

describe("Första start and Studio (KLAR-01, TKL18, TKL21)", () => {
  it("makes the station's id from its short name", () => {
    expect(shortId("Åsen")).toBe("asen");
    expect(shortId("Exempelby Norra 2")).toBe("exempelby-norra-2");
    const html = renderToStaticMarkup(<FirstStart cloud={false} onSetUp={async () => undefined} />);
    expect(html).toContain("Första start · tre rutor");
    expect(html).toContain("Lås med PIN och starta");
    expect(html).toContain("Minst fyra siffror.");
  });

  it("says what is wrong with the list", () => {
    expect(problems(outside)).toEqual([]);
    expect(problems({ ...outside, tracks: [] })).toEqual(["Stationen behöver minst ett spår."]);
    expect(problems({ ...outside, exits: [...outside.exits, { id: "v", side: "right", name: null, tracks: [], signals: [] }] })).toEqual(["Två utfarter har samma id."]);
    expect(problems({ ...outside, tracks: [{ id: "spår 3", label: "Spår 3" }] })).toEqual(['"spår 3" går inte som id: bokstäver, siffror, punkt, kolon eller bindestreck.']);
  });
});

describe("TrainMeet ID och molnet (TKL18, SYNK-30, H71)", () => {
  it("offers the login with ID, and then Spara i molnet with what is where", () => {
    const out = renderToStaticMarkup(<Molnet initial={{ available: true, person: null, cloud: "https://moln.example.test", saved: null, local: 2 }} />);
    expect(out).toContain('id="id-login" class="knapp primar" href="/api/tkl/1/id/login">Logga in med TrainMeet ID<');
    const inside = renderToStaticMarkup(<Molnet initial={{ available: true, person: "Tomas Ek", cloud: "https://moln.example.test", saved: 1, local: 2 }} />);
    expect(inside).toContain("Inloggad som <b>Tomas Ek</b>.");
    expect(inside).toContain("Utsidan på datorn: version 2. I molnet: version 1.");
    expect(inside).toContain('id="spara-i-molnet"');
  });

  it("says when this TKL has no login with ID", () => {
    const html = renderToStaticMarkup(<Molnet initial={{ available: false, person: null, cloud: null, saved: null, local: null }} />);
    expect(html).toContain("Den här TKL har ingen inloggning med TrainMeet ID.");
  });
});

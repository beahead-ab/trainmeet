import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Problem } from "@trainmeet/hubben";
import { planning, type Changes, type Draft, type Finding, type Version } from "./api";
import {
  CERTAINTY,
  CONTENT,
  Facts,
  KINDS,
  MODES,
  SHOWN,
  TRACKS,
  byStation,
  callKind,
  days,
  partOf,
  plural,
  reportSummary,
  sourceKind,
  trainName,
  type Call,
  type Duty,
  type Package,
  type Part,
  type Place,
  type Question,
  type Section,
  type Shunting,
  type Source,
  type Train,
  type TrainTypeRule,
  type Turn,
} from "./data";
import { levelText, number, when } from "./text";
import { Underlag } from "./Underlag";

// Data (S6, PLAN-37): everything in the meet, in blocks, each row with where it comes from and
// how sure it is. Filters for place, source and certainty, and a search. Logged in, one changes
// a place's phone, a section's tracks and clearance mode, and in the grid (PLAN-01) a call's
// times and track and a train's number, days and note, with undo, redo and Spara. Spara carries
// the draft's revision; if someone else saved in between, the new draft is shown with the
// changes on top (PLAN-38). One also answers the import's questions and adds a source (Lägg
// till underlag). Everyone may look (S1).

export type Edit = { kind: "place" | "station" | "tracks" | "section" | "arrival" | "departure" | "track" | "number" | "note" | "days"; id: string; before: string | null; after: string | null };

type AnyChange = Changes["changes"][number];
type Days = Extract<AnyChange, { days: unknown }>["days"];
const WEEK: [Days[number], string][] = [
  ["mon", "Mån"],
  ["tue", "Tis"],
  ["wed", "Ons"],
  ["thu", "Tor"],
  ["fri", "Fre"],
  ["sat", "Lör"],
  ["sun", "Sön"],
];

/** A time as the planner types it, 615, 6.15 or 6:15, as TT:MM. Anything else stays as typed,
 * and Spara says what is wrong. */
export function clockValue(text: string): string {
  const digits = text.replace(/[.:]/g, "");
  if (!/^\d{3,4}$/.test(digits)) return text;
  const padded = digits.padStart(4, "0");
  return `${padded.slice(0, 2)}:${padded.slice(2)}`;
}

type Column<Row> = { name: string; cls?: string; text: (row: Row) => string; cell?: (row: Row) => ReactNode };

type Block<Row> = {
  key: string;
  label: string;
  /** What the detail panel calls a chosen row: Vald driftplats, Valt tåg … */
  chosen: string;
  text: string;
  rows: Row[];
  ref: (row: Row) => string;
  places: (row: Row) => string[];
  columns: Column<Row>[];
  title: (row: Row) => string;
  detail: (row: Row) => [string, ReactNode][];
};

type AnyBlock = Block<unknown>;
const block = <Row,>(given: Block<Row>) => given as unknown as AnyBlock;

type Filters = { search: string; place: string; source: string; certainty: string };
const NO_FILTERS: Filters = { search: "", place: "", source: "", certainty: "" };

/** The value a field shows: the latest unsaved change, or what the draft has. */
export function shownValue(pending: Edit[], kind: Edit["kind"], id: string, original: string | null): string | null {
  for (let i = pending.length - 1; i >= 0; i--) {
    const change = pending[i];
    if (change && change.kind === kind && change.id === id) return change.after;
  }
  return original;
}

/** The changes Spara sends: a place's phone, a section's tracks or its clearance mode, a
 * call's time or track, a train's number, note or days. */
export function changesOf(pending: Edit[]): AnyChange[] {
  return pending.map((change): AnyChange => {
    switch (change.kind) {
      case "place":
        return { place: change.id, phone: change.after };
      case "station":
        return { place: change.id, station: change.after };
      case "tracks":
        return { section: change.id, tracks: change.after as "single" | "double" };
      case "section":
        return { section: change.id, clearance_mode: change.after as "requested" | "direct" | null };
      case "arrival":
      case "departure":
      case "track":
        return { call: change.id, field: change.kind, value: change.after };
      case "number":
      case "note":
        return { train: change.id, field: change.kind, value: change.after };
      case "days":
        return { train: change.id, days: (change.after ?? "").split(",").filter(Boolean) as Days };
    }
  });
}

type Context = {
  draft: Draft;
  pkg: Package;
  admin: boolean;
  meet: string;
  findings: Finding[];
  pending: Edit[];
  selectedRef: string | null;
  edit: (change: Edit) => void;
};

function makeBlocks(context: Context): AnyBlock[] {
  const { draft, pkg, admin, meet, findings, pending, selectedRef, edit } = context;
  const places = pkg.places;
  const sections = pkg.sections ?? [];
  const value = (kind: Edit["kind"], id: string, original: string | null) => shownValue(pending, kind, id, original);
  // The trains as the grid shows them: with the unsaved changes on top.
  const trains: Train[] = (pkg.trains ?? []).map((train) => ({
    ...train,
    number: value("number", train.id, train.number) ?? train.number,
    note: value("note", train.id, train.note ?? null),
    days: (value("days", train.id, train.days.join(",")) ?? "").split(",").filter(Boolean) as Train["days"],
    calls: train.calls.map((call) => ({
      ...call,
      arrival: value("arrival", call.id, call.arrival ?? null),
      departure: value("departure", call.id, call.departure ?? null),
      track: value("track", call.id, call.track ?? null),
    })),
  }));
  const placeName = (id: string) => places.find((place) => place.id === id)?.name ?? id;
  const trainLabel = (id: string) => {
    const train = trains.find((item) => item.id === id);
    return train ? trainName(train) : id;
  };
  const trainCalls = (id: string) => trains.find((train) => train.id === id)?.calls ?? [];
  const via = (section: Section) => {
    const names = (section.parts ?? []).slice(0, -1).map((part) => placeName(part.to_place));
    return names.length ? `via ${names.join(", ")}` : "–";
  };
  const refName = (id: string) => {
    const place = places.find((item) => item.id === id);
    if (place) return place.name;
    const train = trains.find((item) => item.id === id);
    return train ? trainName(train) : id;
  };
  const base = MODES[draft.meet.clearance_mode] ?? draft.meet.clearance_mode;
  const stop = (event: { stopPropagation: () => void }) => event.stopPropagation();

  // The phone field opens on the chosen row; the others read as text (as in the sketch).
  const phoneCell = (place: Place) => {
    const shown = value("place", place.id, place.phone ?? null);
    if (!admin || selectedRef !== `place:${place.id}`) return shown ?? "–";
    return (
      <input
        className="cell"
        defaultValue={shown ?? ""}
        inputMode="tel"
        maxLength={40}
        aria-label={`Telefon ${place.name}`}
        placeholder="–"
        onClick={stop}
        onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
        onBlur={(event) => {
          const next = event.currentTarget.value.trim() || null;
          if (next !== shown) edit({ kind: "place", id: place.id, before: shown, after: next });
        }}
      />
    );
  };
  // Kopplad (PLAN-05): a station's outside among the sources, coupled to the place in advance.
  const stations = draft.stations ?? [];
  const stationName = (id: string | null) => (id ? (stations.find((s) => s.outside.station_id === id)?.outside.name ?? id) : null);
  const stationCell = (place: Place) => {
    const shown = value("station", place.id, place.station?.station_id ?? null);
    // A part follows its station's coupling (PLAN-34): it is coupled with the station, not here.
    if (place.part_of) return <span>{`${stationName(place.station?.station_id ?? null) ?? "–"} · del`}</span>;
    if (!admin || !stations.length || selectedRef !== `place:${place.id}`) return shown ? <span>{stationName(shown)}</span> : <span className="svag">–</span>;
    return (
      <select
        className="cell"
        value={shown ?? ""}
        aria-label={`Station för ${place.name}`}
        onClick={stop}
        onChange={(event) => {
          const next = event.currentTarget.value || null;
          if (next !== shown) edit({ kind: "station", id: place.id, before: shown, after: next });
        }}
      >
        <option value="">–</option>
        {stations.map((s) => (
          <option key={s.outside.station_id} value={s.outside.station_id}>{`${s.outside.name} · version ${s.version}`}</option>
        ))}
      </select>
    );
  };
  const tracksCell = (section: Section) => {
    const shown = value("tracks", section.id, section.tracks) ?? section.tracks;
    if (!admin) return TRACKS[shown] ?? shown;
    return (
      <select className="cell" aria-label="Spår" value={shown} onClick={stop} onChange={(event) => edit({ kind: "tracks", id: section.id, before: shown, after: event.target.value })}>
        {Object.entries(TRACKS).map(([key, label]) => (
          <option key={key} value={key}>
            {label}
          </option>
        ))}
      </select>
    );
  };
  const modeCell = (section: Section) => {
    const shown = value("section", section.id, section.clearance_mode ?? null);
    if (!admin) return shown ? MODES[shown] : `${base} (träffens)`;
    return (
      <select className="cell" aria-label="Klareringsläge" value={shown ?? ""} onClick={stop} onChange={(event) => edit({ kind: "section", id: section.id, before: shown, after: event.target.value || null })}>
        <option value="">{`${base} (träffens)`}</option>
        {Object.entries(MODES).map(([key, label]) => (
          <option key={key} value={key}>
            {label}
          </option>
        ))}
      </select>
    );
  };

  // Rutnätet (PLAN-01): the chosen row's fields open; the others read as text.
  const open = (ref: string) => admin && selectedRef === ref;
  const textCell = (kind: Edit["kind"], id: string, ref: string, shown: string | null, label: string, time = false) => {
    if (!open(ref)) return shown ?? (time ? "" : "–");
    return (
      <input
        key={shown ?? ""}
        className="cell"
        defaultValue={shown ?? ""}
        size={time ? 5 : kind === "note" ? 24 : 7}
        maxLength={time ? 5 : 200}
        inputMode={time ? "numeric" : undefined}
        placeholder={time ? "TT:MM" : "–"}
        aria-label={label}
        onClick={stop}
        onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
        onBlur={(event) => {
          const typed = event.currentTarget.value.trim();
          const next = typed ? (time ? clockValue(typed) : typed) : null;
          if (next !== shown) edit({ kind, id, before: shown, after: next });
        }}
      />
    );
  };
  const trackCell = (row: { train: Train; call: Call }) => {
    const shown = row.call.track ?? null;
    const known = places.find((place) => place.id === row.call.place)?.tracks ?? [];
    if (!open(`call:${row.call.id}`) || !known.length) return textCell("track", row.call.id, `call:${row.call.id}`, shown, `Spår, tåg ${trainName(row.train)} i ${placeName(row.call.place)}`);
    return (
      <select className="cell" aria-label={`Spår, tåg ${trainName(row.train)} i ${placeName(row.call.place)}`} value={shown ?? ""} onClick={stop} onChange={(event) => edit({ kind: "track", id: row.call.id, before: shown, after: event.target.value || null })}>
        <option value="">–</option>
        {known.map((track) => (
          <option key={track.name} value={track.name}>
            {track.name}
          </option>
        ))}
      </select>
    );
  };
  const daysCell = (train: Train) => {
    if (!open(`train:${train.id}`)) return days(train.days);
    const shown = train.days.join(",");
    return (
      <span className="dagar" role="group" aria-label={`Trafikdagar, tåg ${trainName(train)}`} onClick={stop}>
        {WEEK.map(([day, name]) => {
          const on = train.days.includes(day);
          const next = WEEK.map(([key]) => key).filter((key) => (key === day ? !on : train.days.includes(key)));
          return (
            <button key={day} type="button" aria-pressed={on} disabled={on && next.length === 0} onClick={() => edit({ kind: "days", id: train.id, before: shown, after: next.join(",") })}>
              {name}
            </button>
          );
        })}
      </span>
    );
  };

  const calls = trains.flatMap((train) => train.calls.map((call, index) => ({ train, call, index })));
  type CallRow = { train: Train; call: Call; index: number };
  const offset = (call: Call | undefined) => (call?.arrival ?? "–") + (call?.day_offset ? " +1" : "");
  const questions = (draft.questions ?? []).filter((question) => question.answer === null);
  type CheckRow = { id: string; severity: string; message: string; refs: string[]; question?: Question };
  const SEVERITY: Record<string, string> = { conflict: "Konflikt", observation: "Iakttagelse", question: "Fråga" };

  return [
    block<Train>({
      key: "trains",
      label: "Tåg",
      chosen: "Valt tåg",
      text: "planens tåg, med trafikdagar och första och sista besök",
      rows: trains,
      ref: (train) => `train:${train.id}`,
      places: (train) => train.calls.map((call) => call.place),
      columns: [
        { name: "Tåg", text: trainName, cell: (train) => (open(`train:${train.id}`) ? textCell("number", train.id, `train:${train.id}`, train.number, `Tågnummer, tåg ${trainName(train)}`) : <b>{trainName(train)}</b>) },
        { name: "Bolag", text: (train) => train.operator ?? "–" },
        { name: "Dagar", text: (train) => days(train.days), cell: daysCell },
        { name: "Från", text: (train) => placeName(train.calls[0]?.place ?? "") },
        { name: "Avg", text: (train) => train.calls[0]?.departure ?? "–" },
        { name: "Till", text: (train) => placeName(train.calls.at(-1)?.place ?? "") },
        { name: "Ank", text: (train) => offset(train.calls.at(-1)) },
        { name: "Besök", cls: "tal", text: (train) => String(train.calls.length) },
        { name: "Anmärkning", text: (train) => train.note ?? "", cell: (train) => (open(`train:${train.id}`) ? textCell("note", train.id, `train:${train.id}`, train.note ?? null, `Anmärkning, tåg ${trainName(train)}`) : <span className="liten">{train.note ?? ""}</span>) },
      ],
      title: trainName,
      detail: (train) => [
        ["Bolag", train.operator ?? "–"],
        ["Dagar", days(train.days)],
        ["Anmärkning", train.note ?? "–"],
        ["Isärhållning", train.service_key ?? "–"],
        [
          "Väg",
          train.calls
            .filter((call) => call.stops !== false)
            .map((call) => placeName(call.place))
            .join(" – "),
        ],
      ],
    }),
    block<CallRow>({
      key: "calls",
      label: "Tågbesök",
      chosen: "Valt tågbesök",
      text: "varje tågs besök i tur och ordning",
      rows: calls,
      ref: (row) => `call:${row.call.id}`,
      places: (row) => [row.call.place],
      columns: [
        { name: "Tåg", text: (row) => trainName(row.train), cell: (row) => <b>{trainName(row.train)}</b> },
        { name: "Driftplats", text: (row) => placeName(row.call.place) },
        { name: "Spår", text: (row) => row.call.track ?? "–", cell: trackCell },
        {
          name: "Ank",
          text: (row) => (row.call.arrival ?? "") + (row.call.arrival && row.call.day_offset ? " +1" : ""),
          cell: (row) => (open(`call:${row.call.id}`) ? textCell("arrival", row.call.id, `call:${row.call.id}`, row.call.arrival ?? null, `Ankomst, tåg ${trainName(row.train)} i ${placeName(row.call.place)}`, true) : (row.call.arrival ?? "") + (row.call.arrival && row.call.day_offset ? " +1" : "")),
        },
        {
          name: "Avg",
          text: (row) => row.call.departure ?? "",
          cell: (row) => textCell("departure", row.call.id, `call:${row.call.id}`, row.call.departure ?? null, `Avgång, tåg ${trainName(row.train)} i ${placeName(row.call.place)}`, true),
        },
        { name: "Sort", text: (row) => callKind(row.train, row.call, row.index) },
        { name: "Anmärkning", text: (row) => row.call.note ?? "", cell: (row) => <span className="liten">{row.call.note ?? ""}</span> },
      ],
      title: (row) => `${trainName(row.train)} · ${placeName(row.call.place)}`,
      detail: (row) => [
        ["Tåg", trainName(row.train)],
        ["Spår", row.call.track ?? "–"],
        ["Ankomst", row.call.arrival ?? "–"],
        ["Avgång", row.call.departure ?? "–"],
        ["Sort", callKind(row.train, row.call, row.index)],
        ["Anmärkning", row.call.note ?? "–"],
      ],
    }),
    block<Place>({
      key: "places",
      label: "Driftplatser",
      chosen: "Vald driftplats",
      text: "planens platser; ett ställverk eller en handbox kopplas när den ansluter",
      rows: byStation(places),
      ref: (place) => `place:${place.id}`,
      places: (place) => [place.id],
      columns: [
        { name: "Kod", text: (place) => place.code, cell: (place) => <span className="kod">{place.code}</span> },
        {
          name: "Driftplats",
          text: (place) => [place.name, partOf(place, placeName)].filter(Boolean).join(" · "),
          cell: (place) => (
            <span>
              {place.name}
              {place.part_of && <span className="del-av liten block">{partOf(place, placeName)}</span>}
            </span>
          ),
        },
        {
          name: "Platstyp",
          text: (place) => KINDS[place.kind] ?? place.kind,
          cell: (place) => (
            <span>
              {KINDS[place.kind] ?? place.kind}
              {place.remote_from && <span className="liten block">{`från ${placeName(place.remote_from)}`}</span>}
            </span>
          ),
        },
        { name: "Telefon", text: (place) => value("place", place.id, place.phone ?? null) ?? "–", cell: phoneCell },
        { name: "Kopplad", text: (place) => stationName(value("station", place.id, place.station?.station_id ?? null)) ?? "–", cell: stationCell },
        { name: "Spår", cls: "tal", text: (place) => String((place.tracks ?? []).length) },
      ],
      title: (place) => `${place.code} · ${place.name}`,
      detail: (place) => [
        ["Platstyp", (KINDS[place.kind] ?? place.kind) + (place.remote_from ? `, från ${placeName(place.remote_from)}` : "")],
        ...(place.part_of ? ([["Del av", `${placeName(place.part_of)}, egen driftplats som bemannas för sig`]] as [string, ReactNode][]) : []),
        ["Telefon", value("place", place.id, place.phone ?? null) ?? "–"],
        [
          "Spår",
          (place.tracks ?? [])
            .map((track) => track.name)
            .join(" ") || "–",
        ],
        ["Instruktioner", Object.values((place.instructions ?? {}) as Record<string, string>)[0] ?? "–"],
      ],
    }),
    block<{ place: Place; track: NonNullable<Place["tracks"]>[number] }>({
      key: "tracks",
      label: "Spår",
      chosen: "Valt spår",
      text: "driftplatsernas spår i tidtabellen",
      rows: places.flatMap((place) => (place.tracks ?? []).map((track) => ({ place, track }))),
      ref: (row) => `place:${row.place.id}`,
      places: (row) => [row.place.id],
      columns: [
        { name: "Driftplats", text: (row) => row.place.name },
        { name: "Spår", text: (row) => row.track.name, cell: (row) => <b>{row.track.name}</b> },
        { name: "Ordning", cls: "tal", text: (row) => String((row.track.sort_order ?? 0) + 1) },
      ],
      title: (row) => `${row.place.name} · spår ${row.track.name}`,
      detail: (row) => [
        ["Driftplats", row.place.name],
        ["Spår", row.track.name],
      ],
    }),
    block<Section>({
      key: "sections",
      label: "Sträckor",
      chosen: "Vald sträcka",
      text: "klareringssträckor mellan driftplatser",
      rows: sections,
      ref: (section) => `section:${section.id}`,
      places: (section) => [section.place_a, section.place_b, ...(section.parts ?? []).map((part) => part.to_place)],
      columns: [
        { name: "Från", text: (section) => placeName(section.place_a) },
        { name: "Till", text: (section) => placeName(section.place_b) },
        { name: "Delsträckor", text: via },
        { name: "Spår", text: (section) => TRACKS[value("tracks", section.id, section.tracks) ?? section.tracks] ?? "", cell: tracksCell },
        {
          name: "Klarering",
          text: (section) => {
            const shown = value("section", section.id, section.clearance_mode ?? null);
            return shown ? (MODES[shown] ?? shown) : `${base} (träffens)`;
          },
          cell: modeCell,
        },
      ],
      title: (section) => `${placeName(section.place_a)} – ${placeName(section.place_b)}`,
      detail: (section) => [
        ["Spår", TRACKS[value("tracks", section.id, section.tracks) ?? section.tracks] ?? "–"],
        [
          "Delsträckor",
          (section.parts ?? [])
            .map((part) => `${placeName(part.from_place)} – ${placeName(part.to_place)}`)
            .join(" · ") || "–",
        ],
        [
          "Driftplatser emellan",
          (section.parts ?? [])
            .slice(0, -1)
            .map((part) => placeName(part.to_place))
            .join(", ") || "–",
        ],
      ],
    }),
    block<{ section: Section; part: Part }>({
      key: "parts",
      label: "Delsträckor",
      chosen: "Vald delsträcka",
      text: "de fysiska bitarna mellan platserna",
      rows: sections.flatMap((section) => (section.parts ?? []).map((part) => ({ section, part }))),
      ref: (row) => `part:${row.part.id}`,
      places: (row) => [row.part.from_place, row.part.to_place],
      columns: [
        { name: "Från", text: (row) => placeName(row.part.from_place) },
        { name: "Till", text: (row) => placeName(row.part.to_place) },
        { name: "Sträcka", text: (row) => `${placeName(row.section.place_a)} – ${placeName(row.section.place_b)}` },
      ],
      title: (row) => `${placeName(row.part.from_place)} – ${placeName(row.part.to_place)}`,
      detail: (row) => [["Sträcka", `${placeName(row.section.place_a)} – ${placeName(row.section.place_b)}`]],
    }),
    block<Duty>({
      key: "duties",
      label: "Köruppdrag",
      chosen: "Valt köruppdrag",
      text: "förarnas uppdrag, tåg för tåg",
      rows: pkg.duties ?? [],
      ref: (duty) => `duty:${duty.id}`,
      places: (duty) => (duty.legs ?? []).flatMap((leg) => trainCalls(leg.train).map((call) => call.place)),
      columns: [
        { name: "Uppdrag", text: (duty) => duty.name, cell: (duty) => <b>{duty.name}</b> },
        { name: "Tåg", text: (duty) => (duty.legs ?? []).map((leg) => trainLabel(leg.train)).join(", ") },
        { name: "Delar", cls: "tal", text: (duty) => String((duty.legs ?? []).length) },
      ],
      title: (duty) => `Köruppdrag ${duty.name}`,
      detail: (duty) => [["Tåg", (duty.legs ?? []).map((leg) => trainLabel(leg.train)).join(", ")]],
    }),
    block<Turn>({
      key: "turns",
      label: "Omlopp",
      chosen: "Valt omlopp",
      text: "fordonens omlopp",
      rows: pkg.turns ?? [],
      ref: (turn) => `turn:${turn.id}`,
      places: (turn) => (turn.trains ?? []).flatMap((id) => trainCalls(id).map((call) => call.place)),
      columns: [
        { name: "Omlopp", text: (turn) => turn.name, cell: (turn) => <b>{turn.name}</b> },
        { name: "Tåg", text: (turn) => (turn.trains ?? []).map(trainLabel).join(", ") },
      ],
      title: (turn) => `Omlopp ${turn.name}`,
      detail: (turn) => [["Tåg", (turn.trains ?? []).map(trainLabel).join(", ")]],
    }),
    block<Shunting>({
      key: "shunting",
      label: "Växling",
      chosen: "Vald växling",
      text: "växlingsuppdrag på driftplatserna",
      rows: pkg.shunting ?? [],
      ref: (task) => `shunting:${task.id}`,
      places: (task) => [task.place],
      columns: [
        { name: "Driftplats", text: (task) => placeName(task.place) },
        { name: "Uppdrag", text: (task) => task.name, cell: (task) => <b>{task.name}</b> },
        { name: "Tid", text: (task) => task.time ?? "–" },
        { name: "Beskrivning", text: (task) => task.description ?? "" },
      ],
      title: (task) => `Växling ${task.name}`,
      detail: (task) => [
        ["Driftplats", placeName(task.place)],
        ["Beskrivning", task.description ?? "–"],
      ],
    }),
    block<TrainTypeRule>({
      key: "types",
      label: "Tågslag",
      chosen: "Valt tågslag",
      text: "regelboken: tågslagen och förkortningarna",
      rows: draft.rulebook?.train_types ?? [],
      ref: (rule) => `train_type:${rule.code}`,
      places: () => [],
      columns: [
        { name: "Förkortning", text: (rule) => rule.code, cell: (rule) => <span className="kod">{rule.code}</span> },
        { name: "Tågslag i underlaget", text: (rule) => (rule.names ?? []).join(", ") || "–" },
        { name: "Kör", text: (rule) => (rule.content ? (CONTENT[rule.content] ?? rule.content) : "Okänt"), cell: (rule) => (rule.content ? CONTENT[rule.content] : <span className="osaker">Okänt</span>) },
      ],
      title: (rule) => `Tågslaget ${rule.code}`,
      detail: (rule) => [
        ["Namn", (rule.names ?? []).join(", ") || "–"],
        ["Kör", rule.content ? (CONTENT[rule.content] ?? rule.content) : "Okänt"],
      ],
    }),
    block<Source>({
      key: "sources",
      label: "Underlag",
      chosen: "Valt underlag",
      text: "filerna träffen bygger på, som de kom",
      rows: draft.sources ?? [],
      ref: (source) => `source:${source.id}`,
      places: () => [],
      columns: [
        { name: "Fil", text: (source) => source.filename, cell: (source) => (admin ? <a href={planning.sourceFile(meet, source.id)}>{source.filename}</a> : source.filename) },
        { name: "Slag", text: () => "JSON", cell: () => <span className="kalla">JSON</span> },
        { name: "Nivå", text: (source) => levelText(source.level), cell: (source) => <span className="niva">{levelText(source.level)}</span> },
        { name: "Storlek", cls: "tal", text: (source) => `${number(Math.round(source.size / 1024))} kB` },
        { name: "Läst", text: (source) => when(source.added) },
      ],
      title: (source) => source.filename,
      detail: () => {
        const report = draft.report;
        if (!report) return [];
        return [
          ["Gav", reportSummary(report)],
          [
            "Reglerna",
            (report.notes ?? []).length ? (
              <ul className="punkter">
                {(report.notes ?? []).map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : (
              "Inget särskilt."
            ),
          ],
          [
            "Lästes inte",
            <ul className="punkter">
              {(report.left_out ?? []).map((note) => (
                <li key={note}>{note}</li>
              ))}
              <li>Deltagare, fordonsbidrag och ägare är personuppgifter och läses aldrig.</li>
            </ul>,
          ],
        ];
      },
    }),
    block<CheckRow>({
      key: "check",
      label: "Kontroll",
      chosen: "Valt fynd",
      text: "trafikkontrollens fynd; de stoppar inte publiceringen",
      rows: [
        ...findings.map((finding) => ({ id: finding.id, severity: finding.severity, message: finding.message, refs: finding.refs ?? [] })),
        ...questions.map((question) => ({ id: question.id, severity: "question", message: question.message, refs: [], question })),
      ],
      ref: (row) => `finding:${row.id}`,
      places: (row) => row.refs,
      columns: [
        { name: "Fynd", text: (row) => SEVERITY[row.severity] ?? row.severity, cell: (row) => <span className={`pill ${row.severity}`}>{SEVERITY[row.severity]}</span> },
        { name: "", text: (row) => row.message },
      ],
      title: (row) => SEVERITY[row.severity] ?? row.severity,
      detail: (row) => [
        ["Fynd", row.message],
        ["Gäller", row.refs.map(refName).join(", ") || "–"],
      ],
    }),
  ];
}

export type DataProps = {
  admin: boolean;
  meet: string;
  draft: Draft | null;
  findings: Finding[];
  versions: Version[] | null;
  /** For tests: the blocks shown from the start. */
  initialBlocks?: string[];
  /** Visa i rutnätet: the search Data opens with. */
  initialSearch?: string;
  onDraft?: (draft: Draft) => void;
  onTell?: (text: string, good?: boolean) => void;
  onFail?: (error: unknown) => void;
};

export function DataPage({ admin, meet, draft, findings, versions, initialBlocks, initialSearch, onDraft, onTell, onFail }: DataProps) {
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(initialBlocks ?? ["places", "sections"]));
  const [filters, setFilters] = useState<Filters>({ ...NO_FILTERS, search: initialSearch ?? "" });
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<{ block: string; ref: string; row: unknown } | null>(null);
  const [pending, setPending] = useState<Edit[]>([]);
  const [undone, setUndone] = useState<Edit[]>([]);
  const [drawer, setDrawer] = useState(false);
  const [saving, setSaving] = useState(false);

  // Unsaved changes are not lost by mistake: the browser asks before leaving.
  useEffect(() => {
    if (!pending.length) return;
    const ask = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", ask);
    return () => window.removeEventListener("beforeunload", ask);
  }, [pending.length]);

  const facts = useMemo(() => new Facts(draft?.facts ?? []), [draft]);
  const edit = (change: Edit) => {
    if (change.before === change.after) return;
    setPending((list) => [...list, change]);
    setUndone([]);
  };

  if (!draft) return <p className="liten">Hämtar träffen …</p>;
  const latest = versions?.at(-1);
  const badge = latest ? `Utkast · bygger på version ${latest.number}` : "Utkast";
  const heading = (
    <div className="sidrubrik">
      <div>
        <p className="overrubrik">{draft.meet.name}</p>
        <h1>Data</h1>
      </div>
      <span className="under">allt i träffen, i block</span>
      <span className="fyll" />
      <span id="draft-badge" className="bricka">
        {badge}
      </span>
    </div>
  );
  const applied = (next: Draft) => {
    onDraft?.(next);
    setDrawer(false);
    setSelected(null);
    onTell?.("Underlaget är inlagt i utkastet.", true);
  };
  const drawerNode = admin && drawer ? <Underlag meet={meet} onClose={() => setDrawer(false)} onApplied={applied} onFail={onFail} /> : null;

  const pkg = draft.package;
  if (!pkg) {
    return (
      <>
        {heading}
        <section className="kort data-kort" id="empty" aria-labelledby="empty-rubrik">
          <h2 id="empty-rubrik">Inget underlag än</h2>
          <p className="liten">Lägg till Tellurians planeringsfil eller stationslistorna. De läses med kod, skannade listor skrivs av med hubbens egna AI, och allt får sitt ursprung och sin säkerhet.</p>
          {admin && (
            <div className="rad">
              <button id="add-first" type="button" className="sekundar" onClick={() => setDrawer(true)}>
                + Lägg till underlag
              </button>
            </div>
          )}
        </section>
        {drawerNode}
      </>
    );
  }

  const blocks = makeBlocks({ draft, pkg, admin, meet, findings, pending, selectedRef: selected?.ref ?? null, edit });
  const search = filters.search.trim().toLowerCase();
  const matches = (shown: AnyBlock, row: unknown) => {
    const ref = shown.ref(row);
    if (filters.place && !shown.places(row).includes(filters.place)) return false;
    if (filters.source && !facts.sources(ref).has(filters.source)) return false;
    if (filters.certainty && !facts.certainties(ref).has(filters.certainty)) return false;
    if (search && !shown.columns.map((column) => column.text(row)).join(" ").toLowerCase().includes(search)) return false;
    return true;
  };
  const findingsFor = (ref: string) => {
    const id = ref.split(":")[1] ?? "";
    return findings.filter((finding) => (finding.refs ?? []).includes(id));
  };
  const all = blocks.every((item) => chosen.has(item.key));
  const setFilter = (change: Partial<Filters>) => {
    setFilters({ ...filters, ...change });
    setOpened(new Set());
  };
  let total = 0;
  const tables = blocks
    .filter((item) => chosen.has(item.key))
    .map((item) => {
      const rows = item.rows.filter((row) => matches(item, row));
      total += rows.length;
      const limit = opened.has(item.key) ? rows.length : SHOWN;
      return { item, rows, limit };
    });

  const save = async () => {
    setSaving(true);
    try {
      const next = await planning.change(meet, { revision: draft?.revision ?? 0, changes: changesOf(pending) });
      onDraft?.(next);
      onTell?.(pending.length === 1 ? "Ändringen är sparad." : `${number(pending.length)} ändringar är sparade.`, true);
      setPending([]);
      setUndone([]);
    } catch (error) {
      // PLAN-38: someone else saved in between. The new draft is shown, the changes stay on top.
      if (error instanceof Problem && error.status === 412) {
        try {
          onDraft?.(await planning.draft(meet));
        } catch {
          // The message below says what happened; the draft is read again on the next visit.
        }
      }
      onFail?.(error);
    }
    setSaving(false);
  };

  const answer = async (question: string, value: string) => {
    try {
      onDraft?.(await planning.answer(meet, { question, value }));
      onTell?.("Svaret är sparat i regelboken.", true);
    } catch (error) {
      onFail?.(error);
    }
  };

  return (
    <>
      {heading}
      <section className="kort data-kort" id="data" aria-label="Data">
        <div className="chiprad">
          <div id="blocks" className="chips" role="group" aria-label="Datablock">
            <button type="button" className="chip" aria-pressed={all} onClick={() => setChosen(all ? new Set(["places"]) : new Set(blocks.map((item) => item.key)))}>
              Alla
            </button>
            {blocks.map((item) => {
              const count = item.rows.length;
              const extra = item.key === "check" ? (findings.some((finding) => finding.severity === "conflict") ? " fel" : count ? " varning" : "") : "";
              const toggle = () => {
                const next = new Set(chosen);
                if (next.has(item.key) && next.size > 1) next.delete(item.key);
                else next.add(item.key);
                setChosen(next);
              };
              return (
                <button key={item.key} type="button" className={`chip${extra}`} aria-pressed={chosen.has(item.key)} onClick={toggle}>
                  {item.key === "check" ? (
                    <>
                      {`${item.label} `}
                      <b>{number(count)}</b>
                    </>
                  ) : (
                    <>
                      <b>{`${number(count)} `}</b>
                      {item.label}
                    </>
                  )}
                </button>
              );
            })}
          </div>
          {admin && (
            <button id="add-source" type="button" className="sekundar" onClick={() => setDrawer(true)}>
              + Lägg till underlag
            </button>
          )}
        </div>
        <div className="filterrad">
          <input id="search" type="search" placeholder="Sök i all data" aria-label="Sök i all data" value={filters.search} onChange={(event) => setFilter({ search: event.target.value })} />
          <select id="filter-place" aria-label="Driftplats" value={filters.place} onChange={(event) => setFilter({ place: event.target.value })}>
            <option value="">Alla driftplatser</option>
            {pkg.places.map((place) => (
              <option key={place.id} value={place.id}>{`${place.name} (${place.code})`}</option>
            ))}
          </select>
          <select id="filter-source" aria-label="Underlag" value={filters.source} onChange={(event) => setFilter({ source: event.target.value })}>
            <option value="">Alla underlag</option>
            {(draft.sources ?? []).map((source) => (
              <option key={source.id} value={source.id}>
                {source.filename}
              </option>
            ))}
            <option value="planner">Ändrat i Planering</option>
            <option value="regelboken">Regelboken</option>
          </select>
          <select id="filter-certainty" aria-label="Säkerhet" value={filters.certainty} onChange={(event) => setFilter({ certainty: event.target.value })}>
            <option value="">Alla säkerheter</option>
            {Object.entries(CERTAINTY).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
          <button id="clear" type="button" className="lank" onClick={() => setFilter(NO_FILTERS)}>
            Rensa
          </button>
          <span className="fyll" />
          <span id="row-count" className="liten">
            {plural(total, "rad", "rader") + (pending.length ? ` · ${plural(pending.length, "osparad ändring", "osparade ändringar")}` : "")}
          </span>
          {admin && (
            <>
              <button
                id="undo"
                type="button"
                className="ikon"
                title="Ångra"
                aria-label="Ångra"
                disabled={!pending.length}
                onClick={() => {
                  const last = pending.at(-1);
                  if (!last) return;
                  setPending(pending.slice(0, -1));
                  setUndone([...undone, last]);
                }}
              >
                ↶
              </button>
              <button
                id="redo"
                type="button"
                className="ikon"
                title="Gör om"
                aria-label="Gör om"
                disabled={!undone.length}
                onClick={() => {
                  const last = undone.at(-1);
                  if (!last) return;
                  setUndone(undone.slice(0, -1));
                  setPending([...pending, last]);
                }}
              >
                ↷
              </button>
              <button id="save" type="button" className="primar" disabled={!pending.length || saving} onClick={() => void save()}>
                Spara
              </button>
            </>
          )}
        </div>
        <div className={"data-yta" + (selected ? " med-vald" : "")}>
          <div id="tables" className="tabeller">
            {tables.map(({ item, rows, limit }) => (
              <section key={item.key} className="block" aria-labelledby={`block-${item.key}`}>
                <h2 id={`block-${item.key}`} className="blockrubrik">
                  {item.label}
                  <span className="liten">{` ${number(rows.length)} av ${number(item.rows.length)} · ${item.text}`}</span>
                </h2>
                <div className="rulla">
                  <table className="tabell">
                    <thead>
                      <tr>
                        {item.columns.map((column, index) => (
                          <th key={index} className={column.cls}>
                            {column.name || <span className="osynlig">Text</span>}
                          </th>
                        ))}
                        <th>Källa</th>
                        <th>Säkerhet</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.length ? (
                        rows.slice(0, limit).map((row) => {
                          const ref = item.ref(row);
                          const marked = findingsFor(ref).length > 0;
                          const sureness = facts.certainty(ref);
                          return (
                            <tr key={`${ref}-${item.columns[0]?.text(row) ?? ""}-${item.columns[1]?.text(row) ?? ""}`} className={[selected?.ref === ref ? "vald-rad" : "", marked ? "markerad" : ""].join(" ").trim() || undefined} onClick={() => setSelected({ block: item.key, ref, row })}>
                              {item.columns.map((column, index) => (
                                <td key={index} className={column.cls}>
                                  {column.cell ? column.cell(row) : column.text(row)}
                                </td>
                              ))}
                              <td>
                                <Badges facts={facts} ref_={ref} sources={draft.sources} />
                              </td>
                              <td>{sureness ? <span className={`pill ${sureness}`}>{CERTAINTY[sureness]}</span> : <span className="svag">–</span>}</td>
                            </tr>
                          );
                        })
                      ) : (
                        <tr>
                          <td colSpan={item.columns.length + 2} className="tom">
                            {item.rows.length ? "Inget som passar filtret." : "Inget här än."}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                {rows.length > limit && (
                  <button type="button" className="lank visa-fler" onClick={() => setOpened(new Set([...opened, item.key]))}>
                    {`Visa alla ${number(rows.length)}`}
                  </button>
                )}
              </section>
            ))}
          </div>
          {selected && (
            <Detail
              admin={admin}
              block={blocks.find((item) => item.key === selected.block)}
              selected={selected}
              facts={facts}
              draft={draft}
              findings={findingsFor(selected.ref)}
              onClose={() => setSelected(null)}
              onAnswer={(question, value) => void answer(question, value)}
            />
          )}
        </div>
        <p className="forklaring">
          <span className="kalla">JSON</span> Tellurians plan <span className="kalla andrad">PLAN</span> ändrat i Planering <span className="kalla regel">REGEL</span> regelboken
        </p>
      </section>
      {drawerNode}
    </>
  );
}

function Badges({ facts, ref_, sources }: { facts: Facts; ref_: string; sources: Draft["sources"] }) {
  const seen = new Map<string, ReactNode>();
  for (const fact of facts.of(ref_)) {
    for (const origin of fact.origins) {
      const [label, kind, title] = sourceKind(origin, sources);
      if (!seen.has(label))
        seen.set(
          label,
          <span key={label} className={`kalla ${kind}`.trim()} title={title}>
            {label}
          </span>,
        );
    }
  }
  return seen.size ? <>{[...seen.values()]}</> : <span className="svag">–</span>;
}

function Detail({
  admin,
  block: shown,
  selected,
  facts,
  draft,
  findings,
  onClose,
  onAnswer,
}: {
  admin: boolean;
  block: AnyBlock | undefined;
  selected: { ref: string; row: unknown };
  facts: Facts;
  draft: Draft;
  findings: Finding[];
  onClose: () => void;
  onAnswer: (question: string, value: string) => void;
}) {
  if (!shown) return null;
  const fact = facts.byRef.get(selected.ref);
  // The questions about the chosen row, and the question itself when it is the row (Kontroll).
  const asked = (draft.questions ?? []).filter((question) => (question.refs ?? []).includes(selected.ref) || selected.ref === `finding:${question.id}`);
  const from = facts.of(selected.ref);
  return (
    <aside id="detail" className="vald" aria-label={shown.chosen}>
      <header>
        <span className="overrubrik">{shown.chosen}</span>
        {fact && <span className={`pill ${fact.certainty}`}>{CERTAINTY[fact.certainty]}</span>}
        <button type="button" className="ikon" aria-label="Stäng" onClick={onClose}>
          ×
        </button>
      </header>
      <h2>{shown.title(selected.row)}</h2>
      <dl>
        {shown.detail(selected.row).map(([name, value]) => (
          <div key={name} className="par">
            <dt>{name}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {findings.map((finding) => (
        <div key={finding.id} className="att-kolla">
          <b>{finding.severity === "conflict" ? "▲ Konflikt" : "Iakttagelse"}</b>
          <p>{finding.message}</p>
        </div>
      ))}
      {asked.map((question) => (
        <div key={question.id} className="att-kolla">
          <b>▲ Att kolla</b>
          <p>{question.message}</p>
          <div className="svar">
            {(question.alternatives ?? []).map((alternative) =>
              admin ? (
                <button key={alternative.value} type="button" aria-pressed={question.answer === alternative.value} onClick={() => onAnswer(question.id, alternative.value)}>
                  {alternative.label}
                </button>
              ) : question.answer === alternative.value ? (
                <b key={alternative.value}>{alternative.label}</b>
              ) : null,
            )}
          </div>
        </div>
      ))}
      {from.length > 0 && (
        <div className="varifran">
          <p className="overrubrik">Varifrån</p>
          <ul>
            {from.flatMap((item) =>
              item.origins.map((origin, index) => {
                const [label, kind] = sourceKind(origin, draft.sources);
                const field = item.ref === selected.ref ? "" : ` (${item.ref.slice(selected.ref.length + 1)})`;
                return (
                  <li key={`${item.ref}-${index}`}>
                    <span className={`kalla ${kind}`.trim()}>{label}</span>
                    <span>
                      {origin.at + field}
                      {item.note && <span className="liten block">{item.note}</span>}
                    </span>
                    <span className={`pill ${item.certainty}`}>{CERTAINTY[item.certainty]}</span>
                  </li>
                );
              }),
            )}
          </ul>
        </div>
      )}
    </aside>
  );
}

// Tågdiagrammet: the train graph as a graphical timetable, after the planning program's sheets.
// Places lie at their distance along the line (the plan's km, or else the typical running
// time), a stop is a horizontal stroke, and the train number stands at the start of its line
// in its kind's colour. The same drawer is meant for Planering · Graf and later the screen.
// Pure over a meet package; nothing is fetched here.
"use strict";

(function (root) {
  const SVG = "http://www.w3.org/2000/svg";
  const DAY = 1440;
  const WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  const KIND = { passengers: "resande", goods: "gods", service: "tjanst" };

  const minutes = text => (text ? Number(text.slice(0, 2)) * 60 + Number(text.slice(3, 5)) : null);
  const clock = value => {
    const minute = ((Math.round(value) % DAY) + DAY) % DAY;
    return `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
  };
  const median = values => {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  };
  const pair = (a, b) => (a < b ? `${a}|${b}` : `${b}|${a}`);

  function node(tag, attributes = {}, text = null) {
    const element = document.createElementNS(SVG, tag);
    for (const [name, value] of Object.entries(attributes)) {
      if (value !== null && value !== undefined) element.setAttribute(name, String(value));
    }
    if (text !== null) element.textContent = text;
    return element;
  }

  /** The minutes a call holds, counted from its train's first day. */
  function times(call) {
    const offset = (call.day_offset || 0) * DAY;
    let arrival = minutes(call.arrival);
    let departure = minutes(call.departure);
    if (arrival !== null) arrival += offset;
    if (departure !== null) {
      departure += offset;
      if (arrival !== null && departure < arrival) departure += DAY;
    }
    return { arrival, departure };
  }

  /** The typical running time between two places next to each other, from the trains. */
  function runTimes(pkg) {
    const samples = new Map();
    for (const train of pkg.trains) {
      for (let i = 1; i < train.calls.length; i++) {
        const a = train.calls[i - 1], b = train.calls[i];
        const start = times(a).departure ?? times(a).arrival;
        const end = times(b).arrival ?? times(b).departure;
        if (start === null || end === null || end <= start || end - start > 240) continue;
        const key = pair(a.place, b.place);
        if (!samples.has(key)) samples.set(key, []);
        samples.get(key).push(end - start);
      }
    }
    const typical = new Map([...samples].map(([key, values]) => [key, median(values)]));
    const fallback = median([...typical.values()]) ?? 5;
    return (a, b) => typical.get(pair(a, b)) ?? fallback;
  }

  /** The graph's lines: the plan's sheets, or else one line along the sections. */
  function lines(pkg) {
    const pages = pkg.display?.graph_pages ?? [];
    if (pages.length) {
      return pages.map(page => ({
        id: page.id,
        name: page.number ? `${page.number} · ${page.name}` : page.name,
        places: page.places,
        distances: page.distances,
        color: page.color,
      }));
    }
    // Without the plan's lines: the longest way through the sections' parts.
    const next = new Map();
    const link = (a, b) => {
      if (!next.has(a)) next.set(a, new Set());
      next.get(a).add(b);
    };
    for (const section of pkg.sections) {
      for (const part of section.parts) {
        link(part.from_place, part.to_place);
        link(part.to_place, part.from_place);
      }
    }
    const longest = (from, seen) => {
      seen.add(from);
      let best = [from];
      for (const other of next.get(from) ?? []) {
        if (seen.has(other)) continue;
        const way = [from, ...longest(other, seen)];
        if (way.length > best.length) best = way;
      }
      seen.delete(from);
      return best;
    };
    let way = [];
    for (const place of next.keys()) {
      if ((next.get(place)?.size ?? 0) > 1) continue;
      const candidate = longest(place, new Set());
      if (candidate.length > way.length) way = candidate;
    }
    if (way.length < 2) way = pkg.places.map(place => place.id);
    const order = pkg.places.map(place => place.id);
    if (order.indexOf(way[0]) > order.indexOf(way.at(-1))) way.reverse();
    const names = new Map(pkg.places.map(place => [place.id, place.name]));
    return [{ id: "linjen", name: `${names.get(way[0])}–${names.get(way.at(-1))}`, places: way,
      distances: null, color: null }];
  }

  /** The weekdays the meet's game week covers, in order. */
  function trafficDays(pkg) {
    const week = pkg.meet.traffic_week ?? { start_weekday: "mon", days: 1 };
    const start = WEEK.indexOf(week.start_weekday);
    const result = [];
    for (let i = 0; i < Math.min(week.days, 7); i++) result.push(WEEK[(start + i) % 7]);
    return result;
  }

  /** The runs of one train along the line on a day: points of [minute, row]. A train from the
   * day before that runs on past midnight comes in at the left edge. */
  function runs(train, rows, day) {
    const index = WEEK.indexOf(day);
    const before = WEEK[(index + 6) % 7];
    const shifts = [];
    if (train.days.includes(day)) shifts.push(0);
    if (train.days.includes(before) && train.calls.some(call => call.day_offset > 0)) shifts.push(-DAY);
    const result = [];
    for (const shift of shifts) {
      let current = [];
      for (const call of train.calls) {
        const row = rows.get(call.place);
        if (row === undefined) {
          if (current.length > 1) result.push(current);
          current = [];
          continue;
        }
        const { arrival, departure } = times(call);
        if (arrival !== null) current.push([arrival + shift, row, call]);
        if (departure !== null && departure !== arrival) current.push([departure + shift, row, call]);
      }
      if (current.length > 1) result.push(current);
    }
    return result.filter(points => points.some(([minute]) => minute >= 0 && minute <= DAY));
  }

  /**
   * Draws one line of the graph for one day into `host`: a fixed column with the places and a
   * scrolling sheet with the trains. options: line, day, kinds (train type code → content),
   * marks ([{number, place, minute, severity, from, to}]), perMinute, height, compact (print).
   * Returns { trains, first } for the caller's text and scroll position.
   */
  function draw(host, pkg, options) {
    const { line, day, kinds = new Map(), marks = [], perMinute = 4, compact = false } = options;
    const names = new Map(pkg.places.map(place => [place.id, place]));
    const run = runTimes(pkg);
    const distance = [0];
    for (let i = 1; i < line.places.length; i++) {
      distance.push(line.distances ? line.distances[i] : distance[i - 1] + run(line.places[i - 1], line.places[i]));
    }
    const total = Math.max(distance.at(-1), 1);
    const gaps = distance.slice(1).map((value, i) => value - distance[i]).filter(gap => gap > 0);
    const smallest = Math.min(...gaps, total);
    const top = compact ? 34 : 36, bottom = compact ? 26 : 30;
    const inner = Math.min(Math.max(options.height ?? 520, (22 * total) / smallest), compact ? 1600 : 1100);
    const height = top + inner + bottom;
    const y = value => top + (value / total) * inner;
    const rows = new Map(line.places.map((place, i) => [place, i]));
    const rowY = line.places.map((_, i) => y(distance[i]));
    const left = compact ? 150 : 0;
    const width = DAY * perMinute;

    host.replaceChildren();
    const labels = node("svg", { class: "graf-namn", width: compact ? 0 : 168, height,
      viewBox: `0 0 168 ${height}`, "aria-hidden": "true" });
    const sheet = node("svg", { class: "graf-blad", width: left + width + 16, height,
      viewBox: `0 0 ${left + width + 16} ${height}`, role: "img",
      "aria-label": `Tågdiagram ${line.name}` });
    const x = minute => left + minute * perMinute;

    // The hours and ten minutes, and a row per place.
    const grid = node("g", { class: "rutnat" });
    const step = perMinute >= 3 ? 10 : 30;
    for (let minute = 0; minute <= DAY; minute += step) {
      const hour = minute % 60 === 0;
      grid.append(node("line", { x1: x(minute), x2: x(minute), y1: top, y2: top + inner,
        class: hour ? "timme" : "tiominut" }));
      if (hour && (perMinute >= 1 || minute % 120 === 0)) {
        grid.append(node("text", { x: x(minute), y: top - 12, class: "tid" }, clock(minute)));
        grid.append(node("text", { x: x(minute), y: top + inner + 20, class: "tid" }, clock(minute)));
      }
    }
    line.places.forEach((place, i) => {
      grid.append(node("line", { x1: x(0), x2: x(DAY), y1: rowY[i], y2: rowY[i],
        class: names.get(place)?.kind === "halt" ? "rad halt" : "rad" }));
    });
    sheet.append(grid);

    const target = compact ? sheet : labels;
    line.places.forEach((place, i) => {
      const info = names.get(place);
      target.append(node("text", { x: compact ? left - 12 : 156, y: rowY[i] + 4,
        class: info?.kind === "halt" ? "plats halt" : "plats" }, info?.name ?? place));
    });

    // The marks from the traffic check: a band for a pair of places, a ring for a moment.
    const markLayer = node("g", { class: "fynd" });
    for (const mark of marks) {
      if (mark.from !== undefined) {
        const a = rows.get(mark.from), b = rows.get(mark.to);
        if (a === undefined || b === undefined) continue;
        const [y1, y2] = [rowY[a], rowY[b]].sort((p, q) => p - q);
        markLayer.append(node("rect", { x: x(0), y: y1, width, height: Math.max(y2 - y1, 2),
          class: "band " + mark.severity }));
        markLayer.append(node("text", { x: x(0) + 6, y: (y1 + y2) / 2 + 4,
          class: "nummer " + mark.severity }, String(mark.number)));
      } else {
        const row = rows.get(mark.place);
        if (row === undefined || mark.minute === null) continue;
        markLayer.append(node("circle", { cx: x(mark.minute), cy: rowY[row], r: 11,
          class: "ring " + mark.severity }));
        markLayer.append(node("text", { x: x(mark.minute), y: rowY[row] - 16,
          class: "nummer " + mark.severity }, String(mark.number)));
      }
    }
    sheet.append(markLayer);

    // The trains.
    const trainLayer = node("g", { class: "tag" });
    let count = 0, first = null;
    for (const train of pkg.trains) {
      const found = runs(train, rows, day);
      if (!found.length) continue;
      count += 1;
      const kind = KIND[kinds.get(train.train_type)] ?? "okand";
      const label = [train.train_type, train.number].filter(Boolean).join(" ");
      for (const points of found) {
        first = Math.min(first ?? Infinity, points[0][0]);
        const path = points.map(([minute, row], i) =>
          `${i ? "L" : "M"}${x(minute).toFixed(1)},${rowY[row].toFixed(1)}`).join(" ");
        const from = names.get(points[0][2].place)?.name ?? "";
        const to = names.get(points.at(-1)[2].place)?.name ?? "";
        const group = node("g", { class: "tagg " + kind });
        group.append(node("title", {}, `${label} · ${from} ${clock(points[0][0])} – ${to} ${clock(points.at(-1)[0])}`));
        group.append(node("path", { d: path }));
        const [m0, r0] = points[0];
        const down = rowY[points[1][1]] >= rowY[r0];
        group.append(node("text", { x: x(m0) + 3, y: rowY[r0] + (down ? 14 : -6),
          class: "nr" }, train.number));
        trainLayer.append(group);
      }
    }
    sheet.append(trainLayer);

    if (compact) {
      host.append(sheet);
    } else {
      const fixed = document.createElement("div");
      fixed.className = "graf-vanster";
      fixed.append(labels);
      const scroll = document.createElement("div");
      scroll.className = "graf-rulla";
      scroll.append(sheet);
      host.append(fixed, scroll);
    }
    return { trains: count, first, x, perMinute };
  }

  root.TrainMeetGraph = { lines, draw, trafficDays, times, clock, minutes, DAY, WEEK };
})(globalThis);

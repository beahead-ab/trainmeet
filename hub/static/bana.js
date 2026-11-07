// Banan som karta: driftplatserna och klareringssträckorna med delsträckorna under, ritade ur
// träffpaketet. Planen har inga koordinater, så kartan läggs ut här: den längsta vägen genom
// banan står vågrätt, och varje gren hänger av till en egen rad. Spår som bara står i grafens
// linjer (utan klarering) ritas streckade. Pure over a meet package; nothing is fetched here.
"use strict";

(function (root) {
  const SVG = "http://www.w3.org/2000/svg";
  const STEP_X = 118;
  const STEP_Y = 118;
  const pair = (a, b) => (a < b ? `${a}|${b}` : `${b}|${a}`);

  function node(tag, attributes = {}, text = null) {
    const element = document.createElementNS(SVG, tag);
    for (const [name, value] of Object.entries(attributes)) {
      if (value !== null && value !== undefined) element.setAttribute(name, String(value));
    }
    if (text !== null) element.textContent = text;
    return element;
  }

  /** The physical links: every part of a section, and the graph's lines between places that
   * no section joins (track without clearance in the plan). */
  function links(pkg) {
    const found = new Map();
    for (const section of pkg.sections) {
      for (const part of section.parts) {
        found.set(pair(part.from_place, part.to_place),
          { a: part.from_place, b: part.to_place, section, part });
      }
    }
    for (const page of pkg.display?.graph_pages ?? []) {
      for (let i = 1; i < page.places.length; i++) {
        const key = pair(page.places[i - 1], page.places[i]);
        if (!found.has(key)) found.set(key, { a: page.places[i - 1], b: page.places[i], section: null });
      }
    }
    return [...found.values()];
  }

  /** Where every place stands: [column, row]. */
  function layout(pkg) {
    const next = new Map(pkg.places.map(place => [place.id, []]));
    for (const link of links(pkg)) {
      next.get(link.a)?.push(link.b);
      next.get(link.b)?.push(link.a);
    }
    const order = pkg.places.map(place => place.id);
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
    let main = [];
    for (const place of order) {
      if ((next.get(place)?.length ?? 0) !== 1) continue;
      const way = longest(place, new Set());
      if (way.length > main.length) main = way;
    }
    if (!main.length && order.length) main = [order[0]];
    if (order.indexOf(main[0]) > order.indexOf(main.at(-1))) main.reverse();

    const at = new Map();
    const taken = new Set();
    const claim = (place, column, row) => {
      at.set(place, [column, row]);
      taken.add(`${column},${row}`);
    };
    main.forEach((place, i) => claim(place, i, 0));
    const queue = [...main];
    const rows = [1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6];
    while (queue.length) {
      const from = queue.shift();
      const [column, row] = at.get(from);
      for (const first of next.get(from) ?? []) {
        if (at.has(first)) continue;
        // The branch: on from the first place as long as the way does not split.
        const chain = [first];
        let previous = from;
        while (true) {
          const last = chain.at(-1);
          const onward = (next.get(last) ?? []).filter(other => other !== previous && !at.has(other)
            && !chain.includes(other));
          if (onward.length !== 1 || (next.get(last)?.length ?? 0) > 2) break;
          previous = last;
          chain.push(onward[0]);
        }
        const right = column < (main.length - 1) / 2 || column === 0 ? 1 : -1;
        const free = (step, branchRow) => chain.every((_, k) =>
          !taken.has(`${column + step * (k + 1)},${branchRow}`));
        let chosen = null;
        for (const offset of rows) {
          const candidate = row + (row < 0 ? -Math.abs(offset) : offset);
          for (const step of [right, -right]) {
            if (free(step, candidate)) {
              chosen = [step, candidate];
              break;
            }
          }
          if (chosen) break;
        }
        const [step, branchRow] = chosen ?? [right, row + 7];
        chain.forEach((place, k) => claim(place, column + step * (k + 1), branchRow));
        queue.push(...chain);
      }
    }
    // Places no link reaches stand in a row of their own under the rest.
    const bottom = Math.max(0, ...[...at.values()].map(([, row]) => row)) + 1;
    let spare = 0;
    for (const place of order) if (!at.has(place)) claim(place, spare++, bottom);
    const columns = [...at.values()].map(([column]) => column);
    const rowsUsed = [...at.values()].map(([, row]) => row);
    return { at, left: Math.min(...columns), top: Math.min(...rowsUsed),
      width: Math.max(...columns) - Math.min(...columns) + 1,
      height: Math.max(...rowsUsed) - Math.min(...rowsUsed) + 1 };
  }

  /**
   * Draws the map into `host`. options: selected ({kind: "section"|"place", id}),
   * onSelect(kind, id), label(section) → its short name, unsure (Set of refs that are unsure).
   */
  function draw(host, pkg, options = {}) {
    const { selected = null, onSelect = () => {}, label = () => "", unsure = new Set() } = options;
    const plan = layout(pkg);
    const margin = { x: 90, y: 70 };
    const width = (plan.width - 1) * STEP_X + margin.x * 2;
    const height = (plan.height - 1) * STEP_Y + margin.y * 2;
    const point = place => {
      const [column, row] = plan.at.get(place);
      return [margin.x + (column - plan.left) * STEP_X, margin.y + (row - plan.top) * STEP_Y];
    };
    const svg = node("svg", { class: "karta", viewBox: `0 0 ${width} ${height}`,
      width, height, role: "img", "aria-label": "Banan" });
    const places = new Map(pkg.places.map(place => [place.id, place]));
    const curve = (a, b) => {
      const [ax, ay] = point(a), [bx, by] = point(b);
      if (ay === by || ax === bx) return `M${ax},${ay} L${bx},${by}`;
      const middle = (ax + bx) / 2;
      return `M${ax},${ay} C${middle},${ay} ${middle},${by} ${bx},${by}`;
    };

    // The links: clearance sections under, track without clearance dashed.
    const lines = node("g", { class: "lankar" });
    const labels = node("g", { class: "etiketter" });
    for (const link of links(pkg)) {
      if (!plan.at.has(link.a) || !plan.at.has(link.b)) continue;
      const section = link.section;
      const chosen = section && selected?.kind === "section" && selected.id === section.id;
      const classes = ["lank", section ? section.tracks : "utan",
        chosen ? "vald" : "", section && unsure.has(`section:${section.id}`) ? "osaker" : ""];
      const group = node("g", { class: classes.join(" ") });
      const path = curve(link.a, link.b);
      if (section?.tracks === "double") {
        group.append(node("path", { d: path, class: "yttre" }), node("path", { d: path, class: "inre" }));
      } else {
        group.append(node("path", { d: path, class: "enkel" }));
      }
      group.append(node("path", { d: path, class: "traff" }));
      if (section) {
        group.append(node("title", {},
          `${places.get(section.place_a)?.name} – ${places.get(section.place_b)?.name}`));
        group.addEventListener("click", () => onSelect("section", section.id));
        // The section's name once, at its middle part.
        if (section.parts.indexOf(link.part) === Math.floor((section.parts.length - 1) / 2)) {
          const [ax, ay] = point(link.a), [bx, by] = point(link.b);
          labels.append(node("text", { x: (ax + bx) / 2, y: (ay + by) / 2 - 10,
            class: "strackanamn" + (chosen ? " vald" : "") }, label(section)));
        }
      } else {
        group.append(node("title", {}, "Spår utan klarering i planen"));
      }
      lines.append(group);
    }
    svg.append(lines, labels);

    // The places: a box with the code where one clears, a ring where trains only stop.
    const marks = node("g", { class: "platser" });
    for (const place of pkg.places) {
      if (!plan.at.has(place.id)) continue;
      const [x, y] = point(place.id);
      const chosen = selected?.kind === "place" && selected.id === place.id;
      const group = node("g", { class: `plats ${place.kind}${chosen ? " vald" : ""}`,
        tabindex: 0, role: "button", "aria-label": place.name });
      group.addEventListener("click", () => onSelect("place", place.id));
      group.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") onSelect("place", place.id);
      });
      const remote = place.remote_from ? places.get(place.remote_from) : null;
      if (place.kind === "halt") {
        group.append(node("circle", { cx: x, cy: y, r: 9, class: "ring" }));
        group.append(node("text", { x, y: y + 27, class: "namn under" }, place.name));
      } else {
        const boxWidth = Math.max(54, place.code.length * 9 + 22);
        group.append(node("rect", { x: x - boxWidth / 2, y: y - 16, width: boxWidth, height: 32,
          rx: 6, class: "ruta" }));
        group.append(node("text", { x, y: y + 5, class: "kod" }, place.code));
        group.append(node("text", { x, y: y - 24, class: "namn" }, place.name));
        const note = place.kind === "shadow_yard" ? "skuggbangård"
          : remote ? `fjärrstyrd från ${remote.name}` : place.kind === "unmanned" ? "obemannad" : null;
        if (note) group.append(node("text", { x, y: y + 34, class: "not" }, note));
      }
      group.append(node("title", {}, place.name));
      marks.append(group);
    }
    svg.append(marks);
    host.replaceChildren(svg);
    // Fit the width of the card, but never smaller than the names can be read.
    const room = host.clientWidth - 24;
    const scale = room > 0 ? Math.min(1, Math.max(0.78, room / width)) : 1;
    svg.setAttribute("width", String(Math.round(width * scale)));
    svg.setAttribute("height", String(Math.round(height * scale)));
    return plan;
  }

  root.TrainMeetMap = { layout, links, draw };
})(globalThis);

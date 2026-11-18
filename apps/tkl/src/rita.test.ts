import { describe, expect, it } from "vitest";
import {
  addDrag,
  addTrack,
  bendTrack,
  changed,
  confirm,
  drags,
  editor,
  flipSignal,
  geometry,
  isReversed,
  joinTogether,
  litBy,
  looseEnds,
  markStationTrack,
  moveNode,
  nodeAt,
  ownParts,
  pieceAt,
  placeBoundary,
  placeBufferStop,
  placeLineExit,
  placeSignal,
  placeSwitch,
  redo,
  refOf,
  removeAt,
  removeTrack,
  renameSwitch,
  RitaError,
  setReversed,
  setSwitchAddress,
  snapStraight,
  straight,
  undo,
  type Cell,
  type FullDrawing,
} from "./rita";
import { blank, provby } from "./ritaprov";

function pieceOn(d: FullDrawing, at: Cell): string {
  const found = pieceAt(geometry(d.model), at);
  if (!found) throw new Error(`no piece at ${at}`);
  return found.piece;
}

const nodeOf = (d: FullDrawing, at: Cell) => nodeAt(geometry(d.model), at);

describe("Rita: the six objects", () => {
  it("draws a track from cell to cell, horizontally, vertically or at 45°, with red dots at its ends", () => {
    const d = addTrack(blank(), [2, 4], [12, 4]);
    expect(d.model.pieces).toHaveLength(1);
    expect(d.model.panel.tracks).toEqual([{ start: "n1", end: "n2", pieces: [{ id: "s1", reversed: false }], via: [], joints: [], link: false, free: false }]);
    expect(d.model.panel.nodes).toEqual({ n1: [2, 4], n2: [12, 4] });
    expect(looseEnds(d.model)).toEqual(["n1", "n2"]);
    expect(() => addTrack(blank(), [0, 0], [3, 1])).toThrow(RitaError);
    expect(straight([0, 0], [3, 3])).toBe(true);
    expect(snapStraight([0, 0], [5, 1.4])).toEqual([5, 0]);
    expect(snapStraight([0, 0], [4, 3.6])).toEqual([4, 4]);
    expect(() => addTrack(d, [4, 4], [8, 4])).toThrow("Spåret ligger på ett spår som redan finns.");
  });

  it("joins a track drawn into another: a switch where three meet, a crossing where four cross", () => {
    let d = addTrack(blank(), [2, 4], [20, 4]);
    d = addTrack(d, [8, 4], [11, 7]);
    const sw = d.model.switches[0]!;
    expect(sw).toMatchObject({ number: "1", type: "ordinary", node: nodeOf(d, [8, 4]) });
    const g = geometry(d.model);
    expect(g.paths.get(sw.trunk!)?.[0]).toEqual([2, 4]);
    expect(g.paths.get(sw.diverging!)).toEqual([
      [8, 4],
      [11, 7],
    ]);
    expect(d.model.nodes.find((n) => n.id === sw.node)?.type).toBe("switch");
    // A track across both: a crossing at each meeting, with the ways straight through.
    d = addTrack(d, [12, 2], [12, 8]);
    const crossing = d.model.switches.find((s) => s.type === "crossing");
    expect(crossing?.number).toBe("X1");
    expect(crossing?.paths).toHaveLength(2);
    expect(geometry(d.model).cells.get(crossing!.node)).toEqual([12, 4]);
  });

  it("places a switch on a track with its type and the side of the diverging leg", () => {
    const d = placeSwitch(addTrack(blank(), [2, 4], [20, 4]), [10, 4], "ordinary", "ne");
    const sw = d.model.switches[0]!;
    const g = geometry(d.model);
    expect(g.paths.get(sw.diverging!)).toEqual([
      [10, 4],
      [13, 1],
    ]);
    expect(g.paths.get(sw.straight!)?.at(-1)).toEqual([20, 4]);
    expect(looseEnds(d.model)).toContain(nodeOf(d, [13, 1]));
    const y = placeSwitch(d, [10, 4], "y", "ne");
    expect(y.model.switches[0]?.type).toBe("y");
    expect(() => placeSwitch(d, [16, 4], "double_slip", "ne")).toThrow("En korsningsväxel sätts där två spår korsar varandra.");
  });

  it("makes a crossing a double slip with two parts and four ways through it", () => {
    let d = addTrack(blank(), [2, 4], [20, 4]);
    d = addTrack(d, [8, 1], [14, 7]);
    d = placeSwitch(d, [11, 4], "double_slip", "ne");
    const slip = d.model.switches[0]!;
    expect(slip.type).toBe("double_slip");
    expect(slip.parts?.map((p) => p.number)).toEqual(["1", "2"]);
    expect(slip.number).toBe("1/2");
    expect(slip.paths).toHaveLength(4);
    expect(new Set(slip.paths?.map((p) => JSON.stringify(p.positions)))).toHaveProperty("size", 4);
  });

  it("places a signal of a type from the catalogue, in a direction, named after track and direction", () => {
    let d = markStationTrack(addTrack(blank(), [2, 4], [20, 4]), "s1");
    const east = placeSignal(d, [6, 4], "hsi", "east", 3);
    expect(east.name).toBe("H1ö");
    d = east.drawing;
    const signal = d.model.signals[0]!;
    expect(signal).toMatchObject({ type: "hsi", lamps: 3, approach: "s1" });
    expect(d.model.nodes.find((n) => n.id === signal.node)?.type).toBe("signal_point");
    // The piece was split inside its track, with a joint: the node is no cell of its own.
    expect(d.model.panel.tracks[0]?.joints).toEqual([4]);
    expect(Object.keys(d.model.panel.nodes)).toHaveLength(2);
    const west = placeSignal(d, [6, 4], "dvsi", "west");
    expect(west.name).toBe("D1v");
    expect(west.drawing.model.signals[1]?.approach).not.toBe("s1");
    expect(placeSignal(west.drawing, [6, 4], "hsi", "east").name).toBe("H1ö2");
    const lamp = placeSignal(placeBufferStop(d, [20, 4]), [20, 4], "stop_lamp", "east");
    expect(lamp.name).toBe("S1ö");
    expect(() => placeSignal(d, [20, 4], "hsi", "west")).toThrow(RitaError);
    const flipped = flipSignal(d, "H1ö");
    expect(flipped.model.signals[0]?.approach).not.toBe("s1");
  });

  it("places a track-circuit boundary on a track, and a buffer stop and a line exit at its ends", () => {
    let d = addTrack(blank(), [2, 4], [20, 4]);
    d = placeBoundary(d, [9, 4]);
    expect(d.model.nodes.filter((n) => n.type === "block_boundary")).toHaveLength(1);
    expect(() => placeBoundary(d, [2, 4])).toThrow("Ett blockstreck sätts på ett spår, mellan två spårbitar.");
    d = placeBufferStop(d, [20, 4]);
    const exit = placeLineExit(d, [2, 4]);
    expect(exit.id).toBe("A");
    d = exit.drawing;
    expect(d.model.line_exits[0]).toMatchObject({ id: "A", neighbour: null });
    expect(looseEnds(d.model)).toEqual([]);
    expect(() => placeLineExit(d, [9, 4])).toThrow("En linjeutfart sätts där ett spår slutar.");
  });

  it("draws a whole small station: two station tracks, switches, signals, exits and buffer stops", () => {
    const d = provby();
    expect(d.model.switches.map((s) => s.number)).toEqual(["1", "2"]);
    expect(d.model.signals.map((s) => s.name)).toEqual(["A1", "B1", "1V", "1Ö"]);
    expect(d.model.line_exits.map((e) => e.id)).toEqual(["A", "B"]);
    expect(d.model.station_tracks.map((t) => [t.id, t.label])).toEqual([
      ["1", "Spår 1"],
      ["2", "Spår 2"],
    ]);
    expect(d.model.nodes.filter((n) => n.type === "buffer_stop")).toHaveLength(2);
    expect(looseEnds(d.model)).toEqual([]);
  });
});

describe("Rita: numbers, levers and naming", () => {
  it("numbers a switch after the LocoNet address by default, and the owner can change it", () => {
    let d = provby();
    const node = d.model.switches[0]!.node;
    d = setSwitchAddress(d, node, 101);
    expect(d.model.switches[0]).toMatchObject({ number: "101", address: { bus: "LocoNet", number: 101 } });
    d = renameSwitch(d, node, "Vx4");
    d = setSwitchAddress(d, node, 102);
    expect(d.model.switches[0]?.number).toBe("Vx4");
    expect(() => renameSwitch(d, d.model.switches[1]!.node, "Vx4")).toThrow("Numret Vx4 finns redan.");
  });

  it("lays two or more switches together on one lever, one reversed, and drags another along", () => {
    let d = provby();
    d = placeSwitch(d, [16, 7], "ordinary", "se");
    const joined = joinTogether(d, ["1", "2", "3"]);
    expect(joined.id).toBe("1/2/3");
    d = setReversed(joined.drawing, "1/2/3", "2", true);
    const lever = d.model.levers[0]!;
    expect(ownParts(lever)).toEqual(["1", "2", "3"]);
    expect(lever.plus).toEqual({ "1": "+", "2": "-", "3": "+" });
    expect(isReversed(lever, "2")).toBe(true);
    // Dragging: switch 4 is laid diverging when the lever goes to -, and not the other way.
    d = placeSwitch(d, [18, 4], "ordinary", "ne");
    d = addDrag(d, "1/2/3", "-", "4", "-");
    expect(drags(d.model.levers[0]!)).toEqual([{ when: "-", part: "4", position: "-" }]);
    expect(() => addDrag(d, "1/2/3", "+", "2", "-")).toThrow("Växel 2 ligger redan på spaken.");
    // A switch on a new lever leaves the old one.
    const again = joinTogether(d, ["3", "4"]).drawing;
    expect(again.model.levers.map((l) => l.id)).toEqual(["1/2/3", "3/4"]);
    expect(ownParts(again.model.levers[0]!)).toEqual(["1", "2"]);
    expect(() => joinTogether(d, ["1"])).toThrow(RitaError);
  });
});

describe("Rita: redrawing the panel (STUDIO-30)", () => {
  it("moves a switch to another cell; its tracks follow at 45° and keep their joints' share", () => {
    const d = provby();
    const node = d.model.switches[0]!.node;
    const moved = moveNode(d, node, [9, 4]);
    expect(moved.model.panel.nodes[node]).toEqual([9, 4]);
    const g = geometry(moved.model);
    for (const path of g.paths.values()) for (let i = 1; i < path.length; i++) expect(straight(path[i - 1]!, path[i]!)).toBe(true);
    expect(() => moveNode(d, node, [24, 4])).toThrow("Rutan är upptagen.");
  });

  it("joins a loose end dropped on a track, and redraws a track's way with a bend", () => {
    let d = addTrack(blank(), [2, 4], [20, 4]);
    d = addTrack(d, [6, 8], [10, 8]);
    const end = nodeOf(d, [10, 8])!;
    expect(looseEnds(d.model)).toContain(end);
    const before = d;
    d = moveNode(d, end, [13, 4]);
    expect(d.model.switches).toHaveLength(1);
    expect(looseEnds(d.model)).not.toContain(end);
    const bent = bendTrack(before, "s2", [8, 8], [8, 6]);
    expect(bent.model.panel.tracks[1]?.via).toEqual([[8, 6]]);
  });

  it("removes a track with what stood only on it, and a switch with its diverging track", () => {
    const d = provby();
    // Switch 1's diverging leg is a track of its own, to track 2: without it there is no switch,
    // and track 2 ends in the air.
    const gone = removeTrack(d, pieceOn(d, [9, 5]));
    expect(gone.model.switches.map((s) => s.number)).toEqual(["2"]);
    expect(looseEnds(gone.model)).toEqual([nodeOf(d, [11, 7])]);
    expect(gone.model.station_tracks.map((t) => t.id)).toEqual(["1", "2"]);
    const both = removeTrack(gone, pieceOn(gone, [16, 7]));
    expect(both.model.station_tracks.map((t) => t.id)).toEqual(["1"]);
    const sw = removeAt(d, { kind: "switch", id: "2" });
    expect(sw.model.switches.map((s) => s.number)).toEqual(["1"]);
    const signal = removeAt(d, { kind: "signal", id: "A1" });
    expect(signal.model.signals.map((s) => s.name)).toEqual(["B1", "1V", "1Ö"]);
    const exit = removeAt(d, { kind: "exit", id: "B" });
    expect(looseEnds(exit.model)).toEqual([nodeOf(d, [30, 4])]);
  });

  it("confirms an assumed switch, which is then no longer yellow (RS7)", () => {
    const d = provby();
    const assumed = { ...d, model: { ...d.model, switches: d.model.switches.map((s) => ({ ...s, origin: { source: "assumed" as const, confirmed: false, ref: null, note: null } })) } };
    const done = confirm(assumed, { kind: "switch", id: "1" });
    expect(done.model.switches[0]?.origin?.confirmed).toBe(true);
    expect(done.model.switches[1]?.origin?.confirmed).toBe(false);
  });
});

describe("Rita: undo and redo, and what lights up", () => {
  it("undoes and redoes every change of the session", () => {
    let state = editor(blank());
    state = changed(state, addTrack(state.drawing, [2, 4], [12, 4]));
    state = changed(state, placeBufferStop(state.drawing, [12, 4]));
    expect(state.drawing.model.nodes.map((n) => n.type)).toEqual(["joint", "buffer_stop"]);
    state = undo(state);
    expect(state.drawing.model.nodes.map((n) => n.type)).toEqual(["joint", "joint"]);
    state = undo(state);
    expect(state.drawing.model.pieces).toEqual([]);
    expect(undo(state)).toBe(state);
    state = redo(redo(state));
    expect(state.drawing.model.nodes.map((n) => n.type)).toEqual(["joint", "buffer_stop"]);
    expect(redo(state)).toBe(state);
    state = changed(undo(state), placeLineExit(undo(state).drawing, [12, 4]).drawing);
    expect(state.future).toEqual([]);
  });

  it("lights up what a finding is about", () => {
    const d = provby();
    expect(refOf({ kind: "signal", id: "A1" })).toEqual({ kind: "signal", id: "A1" });
    expect(refOf(null)).toBeNull();
    const lit = litBy(d.model, { kind: "signal", id: "A1" });
    expect(lit.pieces.size).toBe(1);
    expect(litBy(d.model, { kind: "switch", id: "2" }).nodes).toEqual(new Set([d.model.switches[1]!.node]));
  });
});

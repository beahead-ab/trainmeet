// The drawings Rita's tests start from (#85): a new station's empty grid, and a small station
// drawn with the tools. Only the tests use this file. Nothing here names a real station (RS13).
import { addTrack, full, geometry, markStationTrack, pieceAt, placeBufferStop, placeLineExit, placeSignal, placeSwitch, renameSignal, type Cell, type FullDrawing } from "./rita";

/** A new station's drawing, as TKL's server sends it: the grid and nothing on it. */
export function blank(): FullDrawing {
  return full({
    proposal: false,
    model: {
      format: "trainmeet.station-model/1",
      station_id: "provby",
      name: "Provby",
      level: 1,
      origin: { source: "drawn", confirmed: true, ref: null, note: null },
      nodes: [],
      pieces: [],
      panel: { basis: "Ritad i Studio.", grid: { dx: 24, dy: 24 }, turntable: null, nodes: {}, tracks: [], name_offset: null, building: null, deviation: null },
    },
  });
}

/** A small station drawn with the tools: the line from A to B, switch 1 to track 2 and its
 * buffer stop, switch 2 to a short siding, an entry signal at each end and exit signals on
 * track 1 both ways. */
export function provby(): FullDrawing {
  let d = blank();
  d = addTrack(d, [2, 4], [30, 4]);
  d = placeLineExit(d, [2, 4]).drawing;
  d = placeLineExit(d, [30, 4]).drawing;
  d = placeSwitch(d, [8, 4], "ordinary", "se");
  d = addTrack(d, [11, 7], [20, 7]);
  d = placeBufferStop(d, [20, 7]);
  d = placeSwitch(d, [24, 4], "ordinary", "ne");
  d = placeBufferStop(d, [27, 1]);
  const signals: [Cell, "east" | "west", string][] = [
    [[5, 4], "east", "A1"],
    [[27, 4], "west", "B1"],
    [[10, 4], "west", "1V"],
    [[22, 4], "east", "1Ö"],
  ];
  for (const [at, facing, name] of signals) {
    const placed = placeSignal(d, at, "hsi", facing, 2);
    d = renameSignal(placed.drawing, placed.name, name);
  }
  d = markStationTrack(d, pieceOn(d, [16, 4]));
  d = markStationTrack(d, pieceOn(d, [16, 7]));
  return d;
}

function pieceOn(d: FullDrawing, at: Cell): string {
  const found = pieceAt(geometry(d.model), at);
  if (!found) throw new Error(`no piece at ${at}`);
  return found.piece;
}

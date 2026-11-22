"""The checks before a model file may run (STD-04, §6), as Swedish texts with the object's name.

- Every switch has a trunk, a straight and a diverging leg, and they reach it.
- Every train route ends at a signal in its direction or at a buffer stop.
- Every track circuit has a name and at least one piece.
- The levers have unambiguous positions.
- No number or name is used twice.
- At level 3: addresses are unique per bus, a switch's number counting as its address by default
  (STUDIO-19), and every switch has its feedback: from the card, two sensors, none or manual
  (STUDIO-24). A manual switch is Utan adress and has no address (TKL26).
- The panel can be made: the station's own track plan holds (STD-26, STD-28), or, without one,
  the engine lays the station out so that it fits, or proposes fields (STD-03).
- The station's outside can be derived: the model has station tracks and line exits, each gets
  an id in the outside, and each exit's side can be read from the panel (STD-08, TKL92).
- At level 3, a train route that ends on a station track whose track circuit is Utan givare is
  a note: the interlocking cannot see the passage, so the arrival is given with Ankommit
  (STV-16, beslut 22 november, #251).

Some findings are notes, not problems: they are shown, but the model may still run. A track
without a sensor at level 3 is one. A line exit without a neighbouring station is another, since
an exit is tied to a section per meet (H26, Utfart in ORDLISTA), so the neighbour is not known in
the station file. So are the fields the engine proposes, and a panel too high for the screen.

The model itself may be saved with problems, so that Studio can keep a station that is not
finished; it just may not run.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from contracts.station_model import (
    Address,
    FeedbackType,
    NodeType,
    StationModel,
    SwitchControl,
    SwitchType,
)
from contracts.tkl import AddressState, ObjectKind, Panel
from tkl.loconet.objects import objects
from tkl.standard import outside, plan
from tkl.standard.graph import SLIP_TYPES, Graph, Step, parts
from tkl.standard.layout import FITS, LayoutError, lay_out
from tkl.standard.levers import Levers, own_parts
from tkl.standard.route import RouteKind
from tkl.standard.routes import TRAIN_ENDS, TRAIN_STARTS, derive

TWO_PIECES = {
    NodeType.SIGNAL_POINT,
    NodeType.BLOCK_BOUNDARY,
    NodeType.MODULE_JOINT,
    NodeType.JOINT,
}
ONE_PIECE = {NodeType.BUFFER_STOP, NodeType.LINE_EXIT}


def problems(model: StationModel) -> list[str]:
    """Everything that stops the model from running. Empty: it may run."""
    return checks(model)[0]


def notes(model: StationModel) -> list[str]:
    """What is shown with the model but does not stop it."""
    return checks(model)[1]


def checks(model: StationModel) -> tuple[list[str], list[str]]:
    """The problems, which stop the model from running, and the notes, which do not."""
    found = [
        *_twice(model),
        *_graph(model),
        *_switches(model),
        *_track_circuits(model),
        *_levers(model),
        *_train_routes(model),
        *_line_exits(model),
        *(_level_3(model) if model.level == 3 else []),
        *outside.problems(model),
    ]
    remarks = _neighbours(model)
    if not found:
        if model.level == 3:
            remarks += _unseen_arrivals(model)
        trouble, more, panel = _panel(model)
        found += trouble
        remarks += more
        if panel is not None:
            found += _outside(model, panel)
    return found, remarks


def _outside(model: StationModel, panel: Panel) -> list[str]:
    """The station's outside can be derived from the model (STD-08)."""
    try:
        outside.outside_of(model, model.station_id, model.name, panel=panel)
    except outside.OutsideError as error:
        return error.problems
    return []


def _neighbours(model: StationModel) -> list[str]:
    return [
        f"Linjeutfarten {e.id} saknar grannstation." for e in model.line_exits if not e.neighbour
    ]


def _panel(model: StationModel) -> tuple[list[str], list[str], Panel | None]:
    """The panel can be made: from the station's own track plan, or by the engine (§6). The
    panel itself too, when it can."""
    if model.panel is not None:
        try:
            return [], [], plan.build(model)
        except plan.PlanError as error:
            return error.problems, [], None
    try:
        found = lay_out(model)
    except LayoutError as error:
        return [f"Motorn kan inte lägga ut panelen. {error}"], [], None
    remarks: list[str] = []
    if found.fields:
        remarks.append(
            f"Stationen får inte plats på skärmen ({found.width:g} rutor bred, högst "
            f"{FITS[0]}): motorn föreslår {len(found.fields)} fält."
        )
    if found.height > FITS[1]:
        remarks.append(
            f"Panelen är {found.height:g} rutor hög och får inte plats på skärmen på höjden "
            f"(högst {FITS[1]})."
        )
    return [], remarks, found


def _unseen_arrivals(model: StationModel) -> list[str]:
    """At level 3: the train routes that end on a station track whose track circuit is Utan
    givare, one note per track circuit. The interlocking cannot see the passage there, so the
    arrival is given with Ankommit (STV-16, beslut 22 november, #251)."""
    blind = {
        o.name
        for o in objects(model)
        if o.kind == ObjectKind.TRACK_CIRCUIT and o.state == AddressState.WITHOUT
    }
    if not blind:
        return []
    on_tracks = {p for t in model.station_tracks for p in t.pieces}
    circuits = {c.name: set(c.pieces) for c in model.track_circuits}
    ending: dict[str, list[str]] = {}
    for route in derive(model):
        if route.kind != RouteKind.TRAIN or not route.track_circuits:
            continue
        last = route.track_circuits[-1]
        if last in blind and circuits.get(last, set()) & on_tracks:
            ending.setdefault(last, []).append(route.name)
    found = []
    for name, routes in ending.items():
        which = f"tågvägen {routes[0]}" if len(routes) == 1 else f"tågvägarna {_and(routes)}"
        found.append(
            f"Spårledningen {name} saknar givare, och {which} slutar där. På nivå 3 kan "
            "ställverket inte se när tåget har kommit in, så ankomsten ges med Ankommit. Med en "
            "givare på spåret blir den automatisk."
        )
    return found


def _and(names: list[str]) -> str:
    return names[0] if len(names) < 2 else f"{', '.join(names[:-1])} och {names[-1]}"


def _repeated(names: Iterable[str]) -> list[str]:
    counts = Counter(names)
    return [name for name, count in counts.items() if count > 1]


def _twice(model: StationModel) -> list[str]:
    numbers = [n for s in model.switches for n in {s.number, *parts(s)}]
    found = [f"Två spårbitar heter {x}." for x in _repeated(p.id for p in model.pieces)]
    found += [f"Två noder heter {x}." for x in _repeated(n.id for n in model.nodes)]
    found += [f"Två växlar har numret {x}." for x in _repeated(numbers)]
    found += [f"Två signaler heter {x}." for x in _repeated(s.name for s in model.signals)]
    found += [f"Två spakar heter {x}." for x in _repeated(lv.id for lv in model.levers)]
    found += [
        f"Två spårledningar heter {x}." for x in _repeated(c.name for c in model.track_circuits)
    ]
    found += [
        f"Två stationsspår har id {x}." for x in _repeated(t.id for t in model.station_tracks)
    ]
    found += [f"Två linjeutfarter heter {x}." for x in _repeated(e.id for e in model.line_exits)]
    found += [f"Två vändskivor heter {x}." for x in _repeated(t.id for t in model.turntables)]
    return found


def _graph(model: StationModel) -> list[str]:
    graph = Graph(model)
    nodes = graph.node_type
    found: list[str] = []
    for piece in model.pieces:
        for word, end in (("börjar", piece.start), ("slutar", piece.end)):
            if end not in nodes:
                found.append(f"Spårbiten {piece.id} {word} i noden {end}, som inte finns.")
    switch_nodes = {s.node for s in model.switches}
    table_nodes = {t.node for t in model.turntables}
    for node in model.nodes:
        count = len(graph.touching.get(node.id, []))
        if node.type in TWO_PIECES and count != 2:
            found.append(f"Noden {node.id} ska ha två spårbitar men har {count}.")
        elif node.type in ONE_PIECE and count != 1:
            found.append(f"Noden {node.id} ska ha en spårbit men har {count}.")
        elif node.type == NodeType.STOP_POINT and count not in (1, 2):
            found.append(f"Stoppunkten {node.id} ska ha en eller två spårbitar men har {count}.")
        elif node.type in (NodeType.SWITCH, NodeType.CROSSING) and node.id not in switch_nodes:
            found.append(f"Noden {node.id} är en växel eller korsning, men ingen står där.")
        elif node.type == NodeType.TURNTABLE and node.id not in table_nodes:
            found.append(f"Noden {node.id} är en vändskiva, men ingen vändskiva står där.")
    for signal in model.signals:
        if signal.node not in nodes:
            found.append(f"Signalen {signal.name} står i noden {signal.node}, som inte finns.")
        elif signal.approach not in graph.touching.get(signal.node, []):
            found.append(f"Signalen {signal.name}: spårbiten {signal.approach} når inte signalen.")
    for table in model.turntables:
        for track in table.tracks:
            if track.piece not in graph.touching.get(table.node, []):
                found.append(f"Vändskivan {table.id}: spåret {track.piece} når inte skivan.")
    return found


def _switches(model: StationModel) -> list[str]:
    graph = Graph(model)
    found: list[str] = []
    for switch in model.switches:
        name = f"Växel {switch.number}"
        at_node = graph.touching.get(switch.node)
        if at_node is None:
            found.append(f"{name} står i noden {switch.node}, som inte finns.")
            continue
        if switch.type in SLIP_TYPES:
            if switch.type == SwitchType.CROSSING:
                name = f"Korsningen {switch.number}"
            else:
                name = f"Korsningsväxeln {switch.number}"
            if len(at_node) != 4:
                found.append(f"{name} ska ha fyra spårbitar men har {len(at_node)}.")
            numbers = {p.number for p in switch.parts}
            if switch.type != SwitchType.CROSSING and not numbers:
                found.append(f"{name} har inga växeldelar.")
            if not switch.paths:
                found.append(f"{name} har inga vägar genom sig.")
            for path in switch.paths:
                a, b = path.between
                if a not in at_node or b not in at_node or a == b:
                    found.append(f"{name}: vägen {a}–{b} går inte genom korsningen.")
                for part in path.positions:
                    if part not in numbers:
                        found.append(f"{name}: vägen {a}–{b} kräver delen {part}, som saknas.")
            continue
        legs = [
            ("stam", switch.trunk),
            ("rakt ben", switch.straight),
            ("avvikande ben", switch.diverging),
        ]
        for word, leg in legs:
            if leg is None:
                found.append(f"{name} saknar {word}.")
            elif leg not in at_node:
                found.append(f"{name}: benet {leg} når inte växeln.")
        named = [leg for _, leg in legs if leg is not None]
        if len(set(named)) != len(named):
            found.append(f"{name} har samma spårbit på två ben.")
    return found


def _track_circuits(model: StationModel) -> list[str]:
    pieces = {p.id for p in model.pieces}
    found: list[str] = []
    seen: dict[str, str] = {}
    for circuit in model.track_circuits:
        if not circuit.pieces:
            found.append(f"Spårledningen {circuit.name} har ingen spårbit.")
        for piece in circuit.pieces:
            if piece not in pieces:
                found.append(f"Spårledningen {circuit.name}: spårbiten {piece} finns inte.")
            elif piece in seen and seen[piece] != circuit.name:
                found.append(
                    f"Spårbiten {piece} ligger i två spårledningar: {seen[piece]} och "
                    f"{circuit.name}."
                )
            seen.setdefault(piece, circuit.name)
    return found


def _levers(model: StationModel) -> list[str]:
    control = {n: s.control for s in model.switches for n in parts(s)}
    found: list[str] = []
    owner: dict[str, str] = {}
    for lever in model.levers:
        name = f"Spaken {lever.id}"
        for part in dict.fromkeys([*lever.plus, *lever.minus]):
            if part not in control:
                found.append(f"{name}: växel {part} finns inte.")
            elif control[part] != SwitchControl.TKL:
                found.append(f"{name}: växel {part} läggs inte av TKL.")
        own = own_parts(lever)
        if not own:
            found.append(f"{name} har ingen egen växel: ingen växel står i både + och -.")
        for part in own:
            if lever.plus[part] == lever.minus[part]:
                found.append(f"{name}: växel {part} får samma läge i + och -.")
            if part in owner:
                found.append(f"Växel {part} ligger på två spakar: {owner[part]} och {lever.id}.")
            owner.setdefault(part, lever.id)
    if found:
        return found
    levers = Levers(model)
    for lever in model.levers:
        for sign, side in (("+", lever.plus), ("-", lever.minus)):
            if levers.lay(side) is None:
                found.append(f"Spaken {lever.id} i läget {sign} kräver en växel i två lägen.")
    return found


def _train_routes(model: StationModel) -> list[str]:
    """Every way forward from a main signal must end at a signal in its direction or a buffer
    stop. An exit signal at a line exit leads onto the line, which is the line's, not a route."""
    if model.level == 1:
        return []
    graph = Graph(model)
    exits = {e.node: e for e in model.line_exits}
    found: list[str] = []
    for signal in model.signals:
        if signal.type not in TRAIN_STARTS or signal.planned:
            continue
        if signal.node not in graph.touching or signal.approach not in graph.pieces:
            continue
        reached: set[str] = set()
        start = graph.arriving(signal.approach, signal.node)
        stack: list[tuple[Step, frozenset[str]]] = [(start, frozenset())]
        while stack:
            step, seen = stack.pop()
            for move in graph.moves(step):
                if not graph.laid_by_tkl(move.switch) or move.step.piece in seen:
                    continue
                node = graph.end_node(move.step)
                ahead = [
                    s
                    for s in graph.signals_at.get(node, [])
                    if s.approach == move.step.piece and s.type in TRAIN_ENDS
                ]
                if ahead or graph.node_type.get(node) in (NodeType.BUFFER_STOP,):
                    continue
                if graph.node_type.get(node) == NodeType.LINE_EXIT:
                    line = exits.get(node)
                    if line is None or signal.name not in line.signals:
                        reached.add(line.id if line else node)
                    continue
                stack.append((move.step, seen | {move.step.piece}))
        for exit_id in sorted(reached):
            found.append(
                f"Tågvägen från {signal.name} slutar inte vid en signal eller en stoppbock: "
                f"den når linjeutfarten {exit_id}."
            )
    return found


def _line_exits(model: StationModel) -> list[str]:
    nodes = {n.id: n.type for n in model.nodes}
    found: list[str] = []
    for line in model.line_exits:
        if nodes.get(line.node) != NodeType.LINE_EXIT:
            found.append(
                f"Linjeutfarten {line.id} står i noden {line.node}, som inte är en utfart."
            )
    return found


def _level_3(model: StationModel) -> list[str]:
    found: list[str] = []
    outputs: dict[tuple[str, int], str] = {}
    sensors: dict[tuple[str, int], str] = {}

    def claim(table: dict[tuple[str, int], str], address: Address, who: str, word: str) -> None:
        key = (address.bus, address.number)
        if key in table:
            found.append(
                f"{word} {address.bus} {address.number} används av både {table[key]} och {who}."
            )
        table.setdefault(key, who)

    for wired in objects(model):
        who = wired.said
        if wired.kind == ObjectKind.SWITCH:
            if wired.control != SwitchControl.TKL:
                continue
            if wired.address is None:
                found.append(f"Växel {wired.name} saknar adress.")
            else:
                claim(outputs, wired.address, who, "Adressen")
            feedback = wired.feedback
            if feedback is None:
                found.append(
                    f"Växel {wired.name} saknar återrapport: välj från kortet, två givare, ingen "
                    "eller manuell."
                )
            elif feedback.type == FeedbackType.MANUAL:
                found.append(
                    f"Växel {wired.name} har manuell återrapport men läggs av ställverket: välj "
                    "Utan adress för en manuell växel."
                )
            elif feedback.type == FeedbackType.SENSORS:
                for sensor, word in (
                    (feedback.straight, "rakt"),
                    (feedback.diverging, "avvikande"),
                ):
                    if sensor is None:
                        found.append(f"Växel {wired.name} saknar givaren för {word}.")
                    else:
                        claim(sensors, sensor, f"{who} ({word})", "Givaren")
        elif wired.kind == ObjectKind.SIGNAL:
            if wired.address is not None:
                claim(outputs, wired.address, who, "Adressen")
        elif wired.address is not None:
            claim(sensors, wired.address, f"spårledningen {wired.name}", "Givaren")
        elif wired.state != AddressState.WITHOUT:
            found.append(f"Spårledningen {wired.name} saknar givare: ange en givare eller utan.")
    return found

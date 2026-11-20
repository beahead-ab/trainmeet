"""Från skiss (#89 del c2, CAD-01, CAD-17, CAD-18, CAD-29): a hand-drawn sketch read into a
module by the photo chain's profile Skiss (cad/bildkedjan/skiss.py), through the same job, queue,
price and meter as a photo.

1. The upload: one sketch, scanned or photographed, through the intake (its metadata gone), the
   sheet straightened and its frames found. The owner picks the frame that is this module (the
   simpler of the two ways: one module per frame read, another frame is another upload), drags
   its corners if they are off, and says which long side is Kant 1 and which end gable A. The
   module's length and width give the sketch its scale.
2. Läs av: code reads the tracks. AI is asked only where code cannot decide (a node with four
   ends that may be two switches), with the photo's fixed answers; the price is the photo's, 12
   tokens per sketch read, drawn only when the AI reads, and nothing without AI.
3. The result is a new version of the module: every piece and switch a proposal from the
   sketch (orange) until Godkänn spårplanen (CAD-17), every measure ± 20 mm with the source
   skiss.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import cv2
import numpy as np
from psycopg.types.json import Jsonb

from cad import curves, graph
from cad.bildkedjan import chain, intake, questions, skiss
from cad.bildkedjan.camera import apply, homography
from cad.bildkedjan.corners import clockwise
from cad.bildkedjan.paths import Terminal
from cad.bildkedjan.rectify import Grid
from cad.editor import Drawing
from cad.library import SHAPE, Who
from cad.store import StoreFailed
from contracts.cad import (
    Certainty,
    CheckChoice,
    CheckItem,
    CheckKind,
    CheckSource,
    Deviation,
    DrawingSource,
    DrawingState,
    FactSource,
    Gable,
    GableEnd,
    ModuleEventKind,
    PhotoChoice,
    PhotoFact,
    PhotoMeasure,
    PhotoQuestion,
    PhotoQuestionKind,
    PhotoSummary,
    Scale,
    Smoothing,
    Straight,
    TrackGraph,
    Trapezoid,
)

if TYPE_CHECKING:
    from cad.photos import Photos

PREVIEW_SIDE = 2000


def sheet_of(data: bytes) -> tuple[intake.Intake, skiss.Sheet]:
    taken = intake.take(data)
    return taken, skiss.prepare(taken.pixels)


def frame_corners(sheet: skiss.Sheet) -> tuple[np.ndarray[Any, Any], list[np.ndarray[Any, Any]]]:
    """The frame chosen at first (the largest) and all of them; a frame inside the sheet's
    margin when none was found, to drag into place."""
    frames = list(sheet.frames)
    if not frames:
        h, w = sheet.pixels.shape[:2]
        guess = np.array(
            [[0.1 * w, 0.3 * h], [0.9 * w, 0.3 * h], [0.9 * w, 0.7 * h], [0.1 * w, 0.7 * h]]
        )
        return guess, []
    largest = max(frames, key=lambda q: cv2.contourArea(q.astype(np.float32)))
    return largest, frames


def top_kant1(corners: np.ndarray[Any, Any]) -> int:
    """A sketch's Kant 1 at first: its upper long side, as a drawing has it."""
    c = clockwise(np.asarray(corners, np.float64))
    lengths = [float(np.linalg.norm(c[(i + 1) % 4] - c[i])) for i in range(4)]
    long_sides = sorted(range(4), key=lambda i: -lengths[i])[:2]
    return min(long_sides, key=lambda i: c[i][1] + c[(i + 1) % 4][1])


def measures(shape: Any) -> tuple[float, float, float, float]:
    """length, width at A, width at B and offset of the module the sketch is read as."""
    if isinstance(shape, Trapezoid):
        return shape.length, shape.width_a, shape.width_b, shape.offset
    if isinstance(shape, Straight):
        return shape.length, shape.width, shape.width, 0.0
    raise ValueError("Från skiss tar raka moduler och trapetser.")


def run(photos: Photos, job: dict[str, Any]) -> None:
    """Profile Skiss in the queue: read the frame, ask the AI only where code cannot decide,
    and make the module's new version."""
    job_id = job["id"]
    setup = chain.Setup.of({k: v for k, v in job["setup"].items() if k != "ai"})
    use_ai = bool(job["setup"].get("ai"))
    photos._step(job_id, "prepare")
    with photos.db.transaction() as conn:
        files = photos._files(conn, job_id)
    original = files.one("original")
    if original is None:
        raise chain.Stop("Skissen finns inte längre. Ladda upp den igen.")
    _, sheet = sheet_of(photos.store.get(original["key"]))
    assert setup.corners is not None
    corners = chain.ordered(np.array(setup.corners, np.float64), setup.kant1, setup.gable)
    length = setup.length or 0.0
    photos._step(job_id, "measure")
    sketched = skiss.read(
        sheet.pixels,
        sheet.paper,
        corners,
        length,
        setup.width_a,
        setup.width_b,
        setup.offset or 0.0,
    )
    image = sketched.image
    with photos.db.transaction() as conn:
        for old in ("measure", "display", "sheet"):
            conn.execute(
                "UPDATE photo_file SET removed_at = now() WHERE job_id = %s AND kind = %s",
                (job_id, old),
            )
        for kind in ("measure", "display"):
            photos._put(
                conn,
                job_id,
                job["owner_id"],
                kind,
                _jpeg(image, 88),
                counted=True,
                size=(image.shape[1], image.shape[0]),
            )
        conn.execute(
            "UPDATE photo_job SET measured = %s WHERE id = %s",
            (Jsonb({"sketch": skiss.to_json(sketched), "corners": corners.tolist()}), job_id),
        )
    reading: questions.AiReading | None = None
    message: str | None = None
    if use_ai and sketched.uncertain:
        photos._step(job_id, "ai")
        try:
            reading = photos._ask(
                job, image, _grid(sketched), _terminals(sketched), sketched.uncertain
            )
        except Exception as error:  # the meter's refusals: the owner gets the questions
            text = getattr(error, "message", None)
            if text is None:
                raise
            message = f"AI:n kunde inte läsa skissen: {text} Du får frågorna i stället."
    photos._step(job_id, "assemble")
    with photos.db.transaction() as conn:
        fresh = photos._row(conn, job_id)
    assemble(photos, job_id, sketched, corners, reading, dict(fresh["answers"] or {}), message)


def _jpeg(pixels: np.ndarray[Any, Any], quality: int) -> bytes:
    ok, data = cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise StoreFailed("Skissen kunde inte sparas.")
    return bytes(data.tobytes())


def _grid(sketched: skiss.Sketched) -> Grid:
    x0, y0, ppm, w, h = sketched.grid
    return Grid(x0, y0, ppm, w, h)


def _terminals(sketched: skiss.Sketched) -> list[Terminal]:
    found = []
    for n in sketched.graph.nodes.values():
        if n.kind == "gable" and n.gable is not None and n.track is not None:
            found.append(Terminal(f"{n.gable}{n.track}", "gable", n.at, n.gable, n.track))
    return found


def stored(photos: Photos, row: dict[str, Any]) -> tuple[skiss.Sketched, np.ndarray[Any, Any]]:
    with photos.db.transaction() as conn:
        files = photos._files(conn, row["id"])
    measure = files.one("measure")
    if row["measured"] is None or measure is None or "sketch" not in row["measured"]:
        raise chain.Stop("Skissen är inte läst än.")
    image = cv2.imdecode(np.frombuffer(photos.store.get(measure["key"]), np.uint8), 1)
    if image is None:
        raise chain.Stop("Skissen kunde inte läsas.")
    return skiss.from_json(row["measured"]["sketch"], image), np.array(row["measured"]["corners"])


def node_questions(
    sketched: skiss.Sketched, reading: questions.AiReading | None, answers: dict[str, str]
) -> list[PhotoQuestion]:
    """Osäkert parti: a node with four ends that may be two switches, unless the AI called it a
    crossing (code and AI agree)."""
    found: list[PhotoQuestion] = []
    for name, at in sketched.uncertain.items():
        said = reading.nodes.get(name) if reading is not None else None
        if said == "korsning":
            continue
        choices = [
            PhotoChoice(id=k, text=t, hint=h, sketch=s)  # type: ignore[arg-type]
            for k, (t, h, s) in questions.NODE_CHOICES.items()
        ]
        key = questions.node_key(name)
        found.append(
            PhotoQuestion(
                key=key,
                kind=PhotoQuestionKind.NODE,
                source=CheckSource.AI if reading is not None else CheckSource.CODE,
                title="Två växlar eller en korsning?",
                text="Två spår möts och byter sida här i skissen. Koden ser en korsning"
                + (
                    f", AI:n {questions.NODE_CHOICES[said][0].lower()}"
                    if said in questions.NODE_CHOICES
                    else ", och ingen AI har läst skissen"
                    if reading is None
                    else ", AI:n är osäker"
                )
                + ". Du avgör.",
                choices=choices,
                code="korsning",
                ai=said if said in questions.NODE_CHOICES else None,
                answer=answers.get(key),
                at=at,
                topology=True,
                closeup=False,
            )
        )
    return found


def assemble(
    photos: Photos,
    job_id: UUID,
    sketched: skiss.Sketched,
    corners: np.ndarray[Any, Any],
    reading: questions.AiReading | None,
    answers: dict[str, str],
    message: str | None,
) -> None:
    """The module's new version from the sketch: the track plan, the facts with the source
    skiss and ± 20 mm, and the questions."""
    with photos.db.transaction() as conn:
        job = photos._row(conn, job_id)
        module = job["module_id"]
        latest = conn.execute(
            "SELECT latest FROM module WHERE id = %s AND removed_at IS NULL FOR UPDATE", (module,)
        ).fetchone()
        if latest is None:
            raise chain.Stop("Modulen finns inte längre.")
        before = photos.modules._row(conn, module, int(latest["latest"]))
        known = photos.modules._profiles_for(conn, [before["gables"]])
    if reading is None and job["ai"] is not None:
        reading = questions.AiReading(
            {tuple(p) for p in job["ai"]["pairs"]},
            dict(job["ai"]["nodes"]),
            str(job["ai"].get("note", "")),
        )
    shape = SHAPE.validate_python(before["shape"])
    gables = [Gable.model_validate(g) for g in before["gables"]]
    old_graph = TrackGraph.model_validate(before["graph"])
    found_tracks: dict[str, list[float]] = {"A": [], "B": []}
    for n in sorted(sketched.graph.nodes.values(), key=lambda n: (n.gable or "", n.track or 0)):
        if n.kind == "gable" and n.gable in found_tracks:
            found_tracks[n.gable].append(n.at[1] - (sketched.offset if n.gable == "B" else 0.0))
    if not any(g.tracks for g in gables):
        gables = [
            Gable(end=GableEnd.A, tracks=[round(v) for v in found_tracks["A"]]),
            Gable(end=GableEnd.B, tracks=[round(v) for v in found_tracks["B"]]),
        ]
    target = Drawing.of(
        Scale(before["scale"]),
        shape,
        gables,
        TrackGraph(issued=old_graph.issued),
        DrawingState(),
        known,
    )
    asked = node_questions(sketched, reading, answers)
    open_topology = [q for q in asked if q.answer is None]
    # What each uncertain X is: the owner's answer, else the AI's (part c3: two switches are
    # drawn as two).
    decided = {
        name: answers.get(questions.node_key(name))
        or (reading.nodes.get(name, "") if reading is not None else "")
        for name in sketched.uncertain
    }
    built, deviation = skiss.drawing(
        sketched,
        target,
        decided,
        Certainty.UNCERTAIN if open_topology else Certainty.PROBABLE,
    )
    built.photo = job_id
    built.source = DrawingSource.SKETCH
    built.smoothing = Smoothing.LIGHT
    built.questions = [
        CheckItem(
            key=f"foto:{q.key}"[:120],
            kind=CheckKind.QUESTION,
            source=q.source,
            at=(round(q.at[0], 1), round(q.at[1], 1)),
            title=q.title,
            text=q.text,
            choices=[
                CheckChoice(id="svara", text="Svara i Osäkert parti", closes=False, action="photo")
            ],
            assumed=False,
        )
        for q in open_topology
    ]
    graph_ = built.graph()
    switch_count, crossing_count = skiss.counts(sketched, decided)
    facts = [
        PhotoFact(
            key="langd",
            label="Längd",
            value=sketched.length,
            source=FactSource.OWNER,
            certainty=Certainty.CONFIRMED,
        ),
        PhotoFact(
            key="vaxlar",
            label="Växlar ur skissen",
            value=float(switch_count),
            source=FactSource.SKETCH,
            certainty=Certainty.PROBABLE,
        ),
        PhotoFact(
            key="korsningar",
            label="Korsningar ur skissen",
            value=float(crossing_count),
            source=FactSource.SKETCH,
            certainty=Certainty.PROBABLE if not open_topology else Certainty.UNCERTAIN,
        ),
    ]
    measures_: list[PhotoMeasure] = []
    for end in ("A", "B"):
        own = [g for g in gables if g.end.value == end]
        owner = list(own[0].tracks) if own else []
        for k, v in enumerate(found_tracks[end], start=1):
            given = owner[k - 1] if k <= len(owner) else None
            facts.append(
                PhotoFact(
                    key=f"gavel.{end.lower()}.{k}",
                    label=f"Gavel {end} · spår {k} från Kant 1",
                    value=round(v, 1),
                    plus_minus=skiss.SKETCH_MM,
                    source=FactSource.SKETCH,
                    certainty=Certainty.PROBABLE,
                )
            )
            measures_.append(
                PhotoMeasure(
                    key=f"gavel.{end.lower()}.{k}",
                    label=f"Gavel {end} · spår {k}",
                    owner=given,
                    owner_source=FactSource.OWNER if given is not None else None,
                    photo=round(v, 1),
                    plus_minus=skiss.SKETCH_MM,
                    agrees=given is None or abs(given - v) <= skiss.SKETCH_MM,
                    gable=GableEnd(end),
                    track=k,
                )
            )
    # The plan on the sheet, for Foto och kontroll.
    length, wa, wb, offset = sketched.length, sketched.width_a, sketched.width_b, sketched.offset
    outline = np.array([[0.0, 0.0], [length, offset], [length, offset + wb], [0.0, wa]])
    to_sheet = homography(outline, corners)
    factor = float((job["result"] or {}).get("preview_factor", 1.0))
    lines = []
    for piece in built.pieces.values():
        points = np.array(curves.sample_path(piece.segs, 10.0), np.float64)
        px = apply(to_sheet, points) * factor
        lines.append([[round(float(x), 1), round(float(y), 1)] for x, y in px])
    x0, y0, ppm, w, h = sketched.grid
    found = {
        "grid": [x0, y0, ppm, w, h],
        "frame": None,
        "quality": None,
        "length": None,
        "length_plus_minus": None,
        "offset": round(offset, 1),
        "tracks_on_photo": lines,
        "facts": [f.model_dump(mode="json") for f in facts],
        "measures": [m.model_dump(mode="json") for m in measures_],
        "questions": [q.model_dump(mode="json") for q in asked],
        "summary": PhotoSummary(
            tracks_a=len(found_tracks["A"]),
            tracks_b=len(found_tracks["B"]),
            switches=len(built.switches),
            crossings=sum(1 for n in built.nodes.values() if n.type.value == "crossing"),
            ends=sum(1 for n in sketched.graph.nodes.values() if n.kind == "end"),
            track_length=round(graph.track_length(graph_), 1),
            deviation=Deviation(
                median=round(float(np.median(deviation)), 2),
                max=round(float(max(deviation)), 2),
                count=len(deviation),
            )
            if deviation
            else None,
        ).model_dump(mode="json"),
        "sleepers": None,
        "gauge": None,
    }
    with photos.db.transaction() as conn:
        row = conn.execute(
            "SELECT latest FROM module WHERE id = %s AND removed_at IS NULL FOR UPDATE", (module,)
        ).fetchone()
        if row is None:
            raise chain.Stop("Modulen finns inte längre.")
        version = int(row["latest"]) + 1
        who = Who(person=job["person_id"], name=job["person_name"], access=photos.modules.access)
        photos.modules._insert_version(
            conn,
            who,
            module,
            version,
            str(before["name"]),
            Scale(before["scale"]),
            shape,
            gables,
            graph_,
            built.state(),
        )
        conn.execute("UPDATE module SET latest = %s WHERE id = %s", (version, module))
        photos.modules._event(
            conn,
            who,
            module,
            ModuleEventKind.PHOTO,
            version,
            f"Version {version}: spårplanen ur skissen, förslag ± 20 mm"
            + (f" ({len(open_topology)} frågor)" if open_topology else ""),
        )
        conn.execute(
            "UPDATE photo_job SET state = 'done', progress = 100, step = 'Klart', result = "
            "result || %s, version = %s, message = %s, updated_at = now() WHERE id = %s",
            (Jsonb(found), version, message, job_id),
        )

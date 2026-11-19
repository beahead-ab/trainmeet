"""What the chain says: the connections decided from the code's, the AI's and the owner's
answers, the questions (bildkedjan step 15), and the facts with their origin and certainty
(principle 4): säker when two independent sources agree, trolig when code measured it within the
tolerance, osäker when only AI saw it, it is assumed or outside the tolerance, and bekräftad when
the owner confirmed it.

Where code and AI say differently the owner is always asked (CAD5, CAD-30), and the owner's
answer counts. Until then the AI's answer draws the plan (CAD2), and the question stops Godkänn
spårplanen. A question that only checks a measure does not change the plan; the owner answers
it in Ritningen or here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from cad import switches
from cad.bildkedjan.chain import Assembled, Measured
from cad.bildkedjan.paths import Path
from cad.bildkedjan.questions import (
    NODE_CHOICES,
    AiReading,
    node_key,
    pair_key,
)
from contracts.cad import (
    Certainty,
    CheckChoice,
    CheckItem,
    CheckKind,
    CheckSource,
    FactSource,
    Gable,
    GableEnd,
    GaugeCheck,
    PhotoChoice,
    PhotoFact,
    PhotoMeasure,
    PhotoQuestion,
    PhotoQuestionKind,
    Scale,
    SleeperCheck,
)
from contracts.station_model import Point

CONNECTED = [
    PhotoChoice(
        id="ja", text="Spåren hänger ihop", hint="Ett tåg kan köra mellan ändarna.", sketch="joined"
    ),
    PhotoChoice(
        id="nej", text="Spåren hänger inte ihop", hint="Ingen förbindelse här.", sketch="apart"
    ),
]
GABLE_AGREE = switches.GABLE_TOLERANCE
"""A gable track within 2 mm of the owner's or the norm's measure agrees (step 13)."""
NEAR_NODE_MM = 25.0


@dataclass
class Decision:
    connections: set[tuple[str, str]]
    certainty: dict[tuple[str, str], Certainty]
    questions: list[PhotoQuestion] = field(default_factory=list)


def _through(paths: list[Path], at: Point, exclude: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """The pairs whose paths pass the place but are not the code's: those that would turn there."""
    found: set[tuple[str, str]] = set()
    for p in paths:
        if p.pair in exclude:
            continue
        lo, hi = p.xs[0], p.xs[-1]
        if not lo <= at[0] <= hi:
            continue
        if abs(float(np.interp(at[0], p.xs, p.ys)) - at[1]) <= NEAR_NODE_MM:
            found.add(p.pair)
    return found


def decide(
    measured: Measured,
    ai: AiReading | None,
    answers: dict[str, str],
    crossings: dict[str, Point],
) -> Decision:
    """The connections the plan is drawn with, how sure each is, and the topology questions."""
    code = measured.code_pairs()
    hidden = {p.pair for p in measured.paths if p.status == "hidden"}
    has_path = {p.pair for p in measured.paths}
    by_pair = {p.pair: p for p in measured.paths}
    questions: list[PhotoQuestion] = []
    connections = set(code)
    certainty: dict[tuple[str, str], Certainty] = {pair: Certainty.PROBABLE for pair in code}
    candidates = sorted(code | hidden | (ai.pairs if ai else set()))
    for pair in candidates:
        in_code = pair in code
        in_ai = ai is not None and pair in ai.pairs
        key = pair_key(pair)
        a, b = pair
        if ai is not None and in_code == in_ai and pair not in hidden:
            if in_code:
                certainty[pair] = Certainty.CERTAIN
            continue
        if ai is None and pair not in hidden:
            continue
        # The AI's answer draws the plan until the owner answers (CAD2), where there is a path.
        draft = in_ai if ai is not None else in_code
        hidden_part = pair in hidden and not in_code
        text = (
            f"Koden ser {'en' if in_code else 'ingen'} förbindelse mellan {a} och {b}"
            + ("; spåret är dolt en bit" if hidden_part else "")
            + (
                f". AI:n ser {'en' if in_ai else 'ingen'}."
                if ai is not None
                else ". Ingen AI har läst fotot."
            )
            + " Du avgör."
        )
        path = by_pair.get(pair)
        at = (float(np.mean(path.xs)), float(np.mean(path.ys))) if path is not None else (0.0, 0.0)
        questions.append(
            PhotoQuestion(
                key=key,
                kind=PhotoQuestionKind.HIDDEN if hidden_part else PhotoQuestionKind.CONNECTION,
                source=CheckSource.AI if ai is not None else CheckSource.CODE,
                title=f"Hänger {a} ihop med {b}?",
                text=text,
                choices=CONNECTED,
                code="ja" if in_code else "nej",
                ai=("ja" if in_ai else "nej") if ai is not None else None,
                at=at,
                topology=True,
                closeup=True,
            )
        )
        if draft and pair in has_path:
            connections.add(pair)
            certainty[pair] = Certainty.UNCERTAIN
        elif not draft:
            connections.discard(pair)
    for name, at in crossings.items():
        said = ai.nodes.get(name) if ai is not None else None
        if said == "korsning":
            continue
        turning = _through(measured.paths, at, code)
        choices = [
            PhotoChoice(id=k, text=t, hint=h, sketch=s)  # type: ignore[arg-type]
            for k, (t, h, s) in NODE_CHOICES.items()
        ]
        questions.append(
            PhotoQuestion(
                key=node_key(name),
                kind=PhotoQuestionKind.NODE,
                source=CheckSource.AI if ai is not None else CheckSource.CODE,
                title="Två växlar eller en korsning?",
                text=(
                    "Två spår möts och byter sida här. Koden ser en korsning"
                    + (
                        f", AI:n {NODE_CHOICES[said][0].lower()}"
                        if said in NODE_CHOICES
                        else ", AI:n är osäker"
                        if said == "vet-inte"
                        else ", och ingen AI har läst fotot"
                    )
                    + ". Bedömningarna gick isär, så du får avgöra."
                ),
                choices=choices,
                code="korsning",
                ai=said if said in NODE_CHOICES else None,
                at=at,
                topology=True,
                closeup=True,
            )
        )
        del turning
    if ai is None and code:
        listed = ", ".join(f"{a}–{b}" for a, b in sorted(code))
        questions.append(
            PhotoQuestion(
                key="forbindelser",
                kind=PhotoQuestionKind.CONNECTION,
                source=CheckSource.CODE,
                title="Stämmer spårens förbindelser?",
                text="Ingen AI har läst fotot. Koden ser att de här ändarna hänger ihop: "
                f"{listed}.",
                choices=[
                    PhotoChoice(id="ja", text="Det stämmer", sketch="joined"),
                    PhotoChoice(id="nej", text="Nej, jag rättar i ritningen", sketch="apart"),
                ],
                code="ja",
                at=(measured.length / 2, measured.setup.width_a / 2),
                topology=True,
            )
        )
    # The owner's answers count.
    questions = [
        q.model_copy(update={"answer": answers[q.key]}) if q.key in answers else q
        for q in questions
    ]
    for question in questions:
        answer = answers.get(question.key)
        if answer is None:
            continue
        if question.kind in (PhotoQuestionKind.CONNECTION, PhotoQuestionKind.HIDDEN):
            asked = _pair(question.key)
            if asked is None:
                for p in code:
                    certainty[p] = Certainty.CONFIRMED
                continue
            pair = asked
            if answer == "ja" and pair in has_path:
                connections.add(pair)
                certainty[pair] = Certainty.CONFIRMED
            elif answer == "nej":
                connections.discard(pair)
                certainty.pop(pair, None)
        elif question.kind == PhotoQuestionKind.NODE:
            at = question.at
            turning = _through(measured.paths, at, code)
            if answer == "korsning":
                connections -= turning
            else:
                connections |= {p for p in turning if p in has_path}
    return Decision(connections, certainty, questions)


def _pair(key: str) -> tuple[str, str] | None:
    from cad.bildkedjan.questions import pair_of

    return pair_of(key)


def check_items(questions: list[PhotoQuestion]) -> list[CheckItem]:
    """The questions as Att kolla items kept with the version: a topology question is answered
    in Osäkert parti and stops the approval until then; a measure's in Ritningen."""
    found: list[CheckItem] = []
    for q in questions:
        if q.answer is not None and q.topology:
            continue
        if q.topology:
            choices = [
                CheckChoice(id="svara", text="Svara i Osäkert parti", closes=False, action="photo")
            ]
        else:
            choices = [
                CheckChoice(
                    id=c.id,
                    text=c.text,
                    closes=c.id != "anvand",
                    action="photo" if c.id == "anvand" else None,
                )
                for c in q.choices
            ]
        found.append(
            CheckItem(
                key=f"foto:{q.key}"[:120],
                kind=CheckKind.QUESTION,
                source=q.source,
                at=(round(q.at[0], 1), round(q.at[1], 1)),
                title=q.title,
                text=q.text,
                choices=choices,
                assumed=False,
            )
        )
    return found


def _gable_measure(gables: list[Gable], end: GableEnd, track: int) -> float | None:
    gable = gables[0] if end == GableEnd.A else gables[1]
    return gable.tracks[track - 1] if track <= len(gable.tracks) else None


@dataclass
class Report:
    facts: list[PhotoFact]
    measures: list[PhotoMeasure]
    questions: list[PhotoQuestion]
    gauge: GaugeCheck
    sleepers: SleeperCheck


def report(
    measured: Measured,
    assembled: Assembled,
    gables: list[Gable],
    given_length: float | None,
    photo_length: float | None,
    length_plus_minus: float | None,
    decision: Decision,
    answers: dict[str, str],
    ai_used: bool,
) -> Report:
    """The facts, Dina mått mot fotot, and the questions about the measures."""
    setup = measured.setup
    scale = setup.scale
    nominal = switches.GAUGE[scale]
    facts: list[PhotoFact] = []
    measures_: list[PhotoMeasure] = []
    questions: list[PhotoQuestion] = []
    gauge = assembled.gauge
    gauge_agrees: bool | None = None
    if gauge.value is not None and gauge.places >= 3:
        gauge_agrees = abs(gauge.value / nominal - 1) <= 0.01
    width = setup.width_a
    facts.append(
        PhotoFact(
            key="bredd",
            label="Bredd",
            value=width,
            plus_minus=None,
            source=FactSource.OWNER,
            certainty=Certainty.CERTAIN if gauge_agrees else Certainty.CONFIRMED,
        )
    )
    if photo_length is not None:
        facts.append(
            PhotoFact(
                key="langd",
                label="Längd",
                value=round(photo_length, 1),
                plus_minus=length_plus_minus,
                source=FactSource.OWNER if given_length is not None else FactSource.PHOTO,
                certainty=(
                    Certainty.CONFIRMED
                    if given_length is not None
                    else Certainty.PROBABLE
                    if measured.quality.length_from_photo
                    else Certainty.UNCERTAIN
                ),
            )
        )
    if gauge.value is not None:
        facts.append(
            PhotoFact(
                key="sparvidd",
                label="Spårvidd",
                value=round(gauge.value, 2),
                text=f"{scale.value} {nominal:g} mm, på {gauge.places} ställen".replace(".", ","),
                plus_minus=round(max(0.05, 2 * gauge.spread), 2),
                source=FactSource.PHOTO,
                certainty=Certainty.CERTAIN if gauge_agrees else Certainty.UNCERTAIN,
            )
        )
        if gauge_agrees is False:
            suggested = round(width * nominal / gauge.value)
            if f"skala:{round(width)}-{suggested}" not in answers:
                questions.append(
                    PhotoQuestion(
                        key=f"skala:{round(width)}-{suggested}",
                        kind=PhotoQuestionKind.SCALE,
                        source=CheckSource.CODE,
                        title=f"Bredden {width:g} mm stämmer inte med spårvidden".replace(".", ","),
                        text=(
                            f"Spårvidden blir {gauge.value:.2f} mm med bredden {width:g} mm, inte "
                            f"{nominal:g}. Är modulen {suggested} mm bred?"
                        ).replace(".", ","),
                        choices=[
                            PhotoChoice(id="anvand", text=f"Använd {suggested} mm"),
                            PhotoChoice(id="behall", text=f"Behåll {width:g} mm".replace(".", ",")),
                        ],
                        code="anvand",
                        at=(measured.length / 2, width / 2),
                        topology=False,
                    )
                )
        if gauge.worst is not None and gauge.worst_at is not None:
            value, _ = gauge.worst
            if abs(value / nominal - 1) > 0.05:
                questions.append(
                    PhotoQuestion(
                        key=f"sparvidd:{round(gauge.worst_at[0])}",
                        kind=PhotoQuestionKind.GAUGE,
                        source=CheckSource.CODE,
                        title=f"Spårvidden blir {value:.1f} mm på ett ställe".replace(".", ","),
                        text=(
                            "Där följde koden troligen något annat än spåret, som en plattform "
                            "eller en kant. Kontrollera spåret där."
                        ),
                        choices=[PhotoChoice(id="stammer", text="Spåret stämmer")],
                        at=gauge.worst_at,
                        topology=False,
                        closeup=True,
                    )
                )
    sleepers = assembled.sleepers
    if sleepers.straight is not None:
        facts.append(
            PhotoFact(
                key="sliper.raka",
                label="Sliperdelning, raka spår",
                value=round(sleepers.straight, 2),
                source=FactSource.PHOTO,
                certainty=Certainty.PROBABLE,
            )
        )
    if sleepers.slanting is not None:
        facts.append(
            PhotoFact(
                key="sliper.sneda",
                label=f"Sliperdelning, sneda spår ({sleepers.slanting_angle:.0f}°)",
                value=round(sleepers.slanting, 2),
                source=FactSource.PHOTO,
                certainty=Certainty.CERTAIN if sleepers.agree else Certainty.PROBABLE,
            )
        )
    if sleepers.agree is False:
        questions.append(
            PhotoQuestion(
                key="sliper",
                kind=PhotoQuestionKind.SLEEPERS,
                source=CheckSource.CODE,
                title="Sliperdelningen skiljer mellan raka och sneda spår",
                text=(
                    f"Raka spår {sleepers.straight:.2f} mm, sneda {sleepers.slanting:.2f} mm. "
                    "Uträtningen kan vara fel: kontrollera hörnen."
                ).replace(".", ","),
                choices=[PhotoChoice(id="stammer", text="Det stämmer")],
                at=(measured.length / 2, width / 2),
                topology=False,
            )
        )
    # The gables' tracks against the owner's or the norm's measures (step 13).
    for t in measured.terminals:
        if t.kind != "gable" or t.gable is None or t.track is None:
            continue
        end = GableEnd(t.gable)
        position = assembled.gable_positions.get(t.id)
        if position is None:
            continue
        pm = assembled.gable_plus_minus.get(t.id, 0.5)
        owner = _gable_measure(gables, end, t.track)
        agrees = owner is not None and abs(owner - position) <= max(GABLE_AGREE, pm)
        measures_.append(
            PhotoMeasure(
                key=f"gavel.{end.value.lower()}.{t.track}",
                label=f"Gavel {end.value} · spår {t.track}",
                owner=owner,
                owner_source=FactSource.OWNER if owner is not None else None,
                photo=round(position, 1),
                plus_minus=pm,
                agrees=agrees,
                gable=end,
                track=t.track,
            )
        )
        facts.append(
            PhotoFact(
                key=f"gavel.{end.value.lower()}.{t.track}",
                label=f"Gavel {end.value} · spår {t.track} från Kant 1",
                value=round(position, 1),
                plus_minus=pm,
                source=FactSource.PHOTO,
                certainty=Certainty.CERTAIN
                if agrees
                else Certainty.UNCERTAIN
                if owner is not None
                else Certainty.PROBABLE,
            )
        )
    if given_length is not None and photo_length is not None:
        pm = length_plus_minus or 1.0
        measures_.insert(
            0,
            PhotoMeasure(
                key="langd",
                label="Längd",
                owner=given_length,
                owner_source=FactSource.OWNER,
                photo=round(photo_length, 1),
                plus_minus=pm,
                agrees=abs(given_length - photo_length) <= max(pm, 0.004 * given_length),
            ),
        )
        measures_.insert(
            0,
            PhotoMeasure(
                key="proportion",
                label="Proportion längd/bredd",
                owner=round(given_length / width, 3),
                owner_source=FactSource.OWNER,
                photo=round(photo_length / width, 3),
                plus_minus=round(pm / width, 3),
                agrees=abs(given_length - photo_length) <= max(pm, 0.004 * given_length),
            ),
        )
    if gauge.value is not None:
        implied = width * nominal / gauge.value
        measures_.insert(
            1 if measures_ and measures_[0].key == "proportion" else 0,
            PhotoMeasure(
                key="bredd",
                label="Bredd",
                owner=width,
                owner_source=FactSource.OWNER,
                photo=round(implied, 1),
                plus_minus=round(max(0.5, width * 2 * gauge.spread / gauge.value), 1),
                agrees=bool(gauge_agrees),
            ),
        )
    # The switches: their points, radius and type.
    for info_number, (from_a, pm) in assembled.switch_points.items():
        sw = next(
            s
            for s in assembled.built.drawing.switches.values()
            if (s.number or s.id) == info_number
        )
        matched = switches.match(sw.radius, sw.angle, scale)
        facts.append(
            PhotoFact(
                key=f"vaxel.{info_number}",
                label=f"Växel {info_number}: tungspetsar från gavel A",
                value=round(from_a, 1),
                text=(f"R {sw.radius:.0f} mm" if sw.radius else "radien okänd")
                + (f" · {matched.name}" if matched else " · ingen känd växeltyp"),
                plus_minus=pm,
                source=FactSource.PHOTO,
                certainty=Certainty.PROBABLE if matched else Certainty.UNCERTAIN,
            )
        )
    for fit in assembled.net.switches:
        if fit.deviation > 1.0 and math.isfinite(fit.deviation):
            node = assembled.net.nodes.get(fit.node)
            if node is None:
                continue
            key = f"vaxelpassning:{round(node.x)}"
            if key in answers:
                continue
            questions.append(
                PhotoQuestion(
                    key=key,
                    kind=PhotoQuestionKind.SWITCH_FIT,
                    source=CheckSource.CODE,
                    title="En växel passar fotot dåligt",
                    text=f"Växelns bana ligger i median {fit.deviation:.1f} mm från fotot.".replace(
                        ".", ","
                    ),
                    choices=[PhotoChoice(id="stammer", text="Växeln stämmer")],
                    at=(node.x, node.y),
                    topology=False,
                )
            )
    connections = sorted(decision.connections)
    agreed = all(decision.certainty.get(p) == Certainty.CERTAIN for p in connections)
    facts.append(
        PhotoFact(
            key="forbindelser",
            label="Spårens förbindelser",
            text=", ".join(f"{a}–{b}" for a, b in connections) or "inga",
            source=FactSource.AI if ai_used else FactSource.CODE,
            certainty=Certainty.CERTAIN if ai_used and agreed else Certainty.PROBABLE,
        )
    )
    questions = [
        q.model_copy(update={"answer": answers[q.key]}) if q.key in answers else q
        for q in questions
    ]
    return Report(
        facts,
        measures_,
        questions,
        GaugeCheck(
            value=round(gauge.value, 2) if gauge.value is not None else None,
            nominal=nominal,
            places=gauge.places,
            agrees=gauge_agrees,
        ),
        SleeperCheck(
            straight=round(sleepers.straight, 2) if sleepers.straight else None,
            slanting=round(sleepers.slanting, 2) if sleepers.slanting else None,
            slanting_angle=round(sleepers.slanting_angle, 1) if sleepers.slanting_angle else None,
            agree=sleepers.agree,
        ),
    )


def scale_of(measured: Measured) -> Scale:
    return measured.setup.scale

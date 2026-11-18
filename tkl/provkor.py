"""Provkör (#85 del c, STUDIO-05, STUDIO-27): with LocoNet connected to the layout, Prova runs
each route on the real layout, one at a time, with the owner.

For every route, as Prova's simulated test has them: TKL sets the route through the station's
own interlocking, which orders the switches and waits for their feedback (STV-11). A route the
interlocking refuses fails at once with its reason, and one whose feedback does not come within
the time is held and fails with that. When every switch has reported, TKL asks the owner to
look: does the signal show kör, and does the train's path lie right? The owner answers right or
wrong, or skips the route. Then the route is released and the next one is set. No train runs:
the owner follows the path on the layout.

Provkör has no thread of its own: it moves on when the page asks how it stands (`tick`, with
the interlocking as it is now, while the LocoNet service pumps the layout's reports in) and
when the owner answers. Nothing goes up to Hubben. No code here names a station (RS13).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final, Literal

from contracts.tkl import (
    TklInterlocking,
    TklProvaResult,
    TklProvaRoute,
    TklProvkor,
    TklSetRoute,
)
from tkl.prova import WORD, failures_first, way_of
from tkl.stallverk import Interlocking, Outcome, Way
from tkl.standard import PointKind

Operate = Callable[[Callable[[Interlocking], Outcome]], tuple[Outcome, TklInterlocking]]
"""One operation on the station's interlocking, its orders sent on the bus."""
Answer = Literal["right", "wrong", "skip"]
WRONG: Final = "Ägaren: signalen eller vägen stämde inte på banan."
SKIPPED: Final = "Hoppades över."
GONE: Final = "Vägen löstes ut innan den var provkörd."


class NoQuestion(Exception):
    """Provkör has nothing to answer now."""


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _listed(names: list[str]) -> str:
    if len(names) < 2:
        return "".join(names)
    return f"{', '.join(names[:-1])} och {names[-1]}"


def question(way: Way) -> str:
    """What the owner is asked when the route lies on the layout."""
    path = f"{WORD[way.kind]} {way.start} → {way.end}"
    if way.route.start.kind == PointKind.SIGNAL:
        aspect = "kör" if way.kind.value == "train" else "växling"
        return (
            f"Visar signalen {way.start} {aspect}, och ligger växlarna rätt för {path}? "
            "Följ vägen på banan."
        )
    return f"Ligger växlarna rätt för {path}? Följ vägen på banan."


class Provkor:
    """One Provkör: the routes in order, the one on the layout now, and the answers."""

    def __init__(
        self,
        ways: list[Way],
        operate: Operate,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        on_change: Callable[[Provkor], None] = lambda _provkor: None,
    ) -> None:
        self.ways = ways
        self.operate = operate
        self.now = now
        self.on_change = on_change
        self.index = 0
        self.route_id: int | None = None
        self.pieces: list[str] = []
        self.results: list[TklProvaRoute] = []
        self.waiting: str | None = None
        self.asking = False
        self.running = False
        self.finished: datetime | None = None

    @property
    def way(self) -> Way | None:
        return self.ways[self.index] if self.running and self.index < len(self.ways) else None

    def begin(self) -> None:
        self.running, self.index, self.results, self.finished = True, 0, [], None
        self._next()

    def _next(self) -> None:
        """The next route set on the layout; one the interlocking refuses fails at once."""
        while self.index < len(self.ways):
            way = self.ways[self.index]
            outcome, state = self.operate(_setting(way))
            route = _found(state, outcome.route) if outcome.accepted else None
            if route is not None:
                self.route_id = outcome.route
                self.pieces = [p for s in route.sections for p in s.pieces]
                self._settle(route)
                return
            reason = outcome.message if not outcome.accepted else GONE
            self._record(way, TklProvaResult.FAILED, reason)
            self.index += 1
        self._end()

    def _end(self) -> None:
        self.running, self.route_id, self.waiting, self.asking = False, None, None, False
        self.finished = self.now()
        self.on_change(self)

    def _record(self, way: Way, result: TklProvaResult, reason: str | None) -> None:
        shown = way_of(way, self.pieces or None)
        self.results.append(TklProvaRoute(**shown.model_dump(), result=result, reason=reason))
        self.pieces = []
        self.on_change(self)

    def tick(self, state: TklInterlocking) -> None:
        """How the route stands on the layout now: still waiting for feedback, held, or ready
        for the owner to look."""
        if not self.running or self.route_id is None:
            return
        route = _found(state, self.route_id)
        if route is None:
            self._done(TklProvaResult.FAILED, GONE)
            return
        self._settle(route)

    def _settle(self, route: TklSetRoute) -> None:
        if route.held:
            self._done(TklProvaResult.FAILED, _cap(route.held) + ".")
        elif route.waiting:
            self.waiting = f"Väntar på återrapport från växel {_listed(route.waiting)} …"
            self.asking = False
        else:
            self.waiting, self.asking = None, True

    def answer(self, answer: Answer) -> None:
        """Right, wrong or skip; then the next route. Skip is always possible, also while TKL
        waits for the feedback."""
        if not self.running or (not self.asking and answer != "skip"):
            raise NoQuestion()
        if answer == "right":
            self._done(TklProvaResult.PASSED, None)
        elif answer == "wrong":
            self._done(TklProvaResult.FAILED, WRONG)
        else:
            self._done(TklProvaResult.SKIPPED, SKIPPED)

    def _done(self, result: TklProvaResult, reason: str | None) -> None:
        way = self.ways[self.index]
        self._release()
        self._record(way, result, reason)
        self.waiting, self.asking = None, False
        self.index += 1
        self._next()

    def _release(self) -> None:
        if self.route_id is not None:
            route_id = self.route_id
            self.operate(lambda it: it.release(route_id))
            self.route_id = None

    def stop(self) -> None:
        if not self.running:
            return
        self._release()
        self._end()

    def shown(self, available: bool, reason: str | None) -> TklProvkor:
        way = self.way
        return TklProvkor(
            available=available,
            reason=reason,
            running=self.running,
            done=len(self.results),
            total=len(self.ways),
            route=way_of(way, self.pieces or None) if way is not None else None,
            waiting=self.waiting if self.running else None,
            question=question(way) if way is not None and self.asking else None,
            routes=failures_first(self.results),
            finished=self.finished,
        )


def idle(
    available: bool,
    reason: str | None,
    routes: list[TklProvaRoute] | None = None,
    finished: datetime | None = None,
) -> TklProvkor:
    """Provkör when none runs: what the last one found, kept with the station."""
    return TklProvkor(
        available=available,
        reason=reason,
        routes=failures_first(routes or []),
        done=len(routes or []),
        finished=finished,
    )


def _setting(way: Way) -> Callable[[Interlocking], Outcome]:
    def act(it: Interlocking) -> Outcome:
        return it.set_route(way.start, way.end, way.kind)

    return act


def _found(state: TklInterlocking, route_id: int | None) -> TklSetRoute | None:
    return next((r for r in state.routes if r.id == route_id), None)

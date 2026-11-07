"""What a source changes in the draft, before it is laid in (Lägg till underlag)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from contracts.meet import MeetPackage
from contracts.planning import Difference, Draft, ImportPreview, ImportResult, Source


def _difference[T](before: Sequence[T], after: Sequence[T], key: Callable[[T], Any]) -> Difference:
    old = {key(item): item for item in before}
    new = {key(item): item for item in after}
    return Difference(
        added=len(new.keys() - old.keys()),
        removed=len(old.keys() - new.keys()),
        changed=sum(old[k] != new[k] for k in old.keys() & new.keys()),
    )


def preview(draft: Draft, fresh: Draft, source: Source, result: ImportResult) -> ImportPreview:
    """The draft now against the draft with the source laid in (with the planner's changes)."""
    before: MeetPackage | None = draft.package
    after = fresh.package if fresh.package is not None else result.package
    times = tracks = 0
    if before is not None:
        calls = {call.id: call for train in before.trains for call in train.calls}
        for train in after.trains:
            for call in train.calls:
                old = calls.get(call.id)
                if old is None:
                    continue
                times += (old.arrival, old.departure, old.day_offset) != (
                    call.arrival,
                    call.departure,
                    call.day_offset,
                )
                tracks += old.track != call.track
    return ImportPreview(
        source=source,
        report=result.report,
        first=before is None,
        places=_difference(before.places if before else [], after.places, lambda p: p.id),
        sections=_difference(before.sections if before else [], after.sections, lambda s: s.id),
        trains=_difference(before.trains if before else [], after.trains, lambda t: t.id),
        times=times,
        tracks=tracks,
        questions=sum(q.answer is None for q in fresh.questions),
        kept=len(draft.changes),
    )

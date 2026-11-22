"""Catalogs del av provet av webbsökningen (CAT-172, CAT-167–CAT-169): belägget per fält.

    python -m catalog.prov_webbsokning prov [--rapport prov/rapport.md]

Läser fallen som ID:s prov sparade (id/prov_webbsokning.py --spara prov, en fil per fall,
MeterSearchTrial i contracts/tokens.py) och kör Catalogs egen kontroll av belägget på samma svar
(catalog/evidence.py, check), som när en person söker. För varje fält syns då vad som hände:

    fylls       värdet har en källa ur sökningen vars utdrag håller det
    ur sidan    värdet står längre in på den citerade sidan, från de citerade orden
                (catalog/source_pages.py, CAT-169); räknas också som fylls
    saknas      Claude gav inget värde: det fanns inte i källorna, eller Claude lämnade det
    format      värdet är inte ett tal som fältregistret tar (BAD_VALUE)
    utan källa  Claude gav ingen källhänvisning (NO_SOURCE)
    påhittad    källan finns inte i sökresultatet (INVENTED_SOURCE)
    håller inte inget utdrag håller värdet (UNSUPPORTED)

Det som skrivs ut är antalen och fältens namn, aldrig värdena eller källornas text. Med --rapport
skrivs allt till en fil i Markdown: sammanfattningen, en tabell med fälten per fall, och för
varje fall värdena, utdragen med adresserna och Claudes svar som det skrevs. Det är bara det
sökningen hittade på webben, och märkningen. Kostnaden är den ID:s prov räknade.

Programmet läser de citerade sidorna som Catalog gör, när sökningens eget utdrag inte håller
värdet; med --utan-sidor bara filerna. Ingen databas, ingen nyckel och ingen sökning. Körs för
hand och av jobbet "Prov av webbsökningen" (.github/workflows/prov-webbsokning.yml), som också
skriver rapporten i sin logg och kan kontrollera en tidigare körnings fall igen utan att söka.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from catalog.evidence import check
from catalog.prototype_search import wanted
from catalog.source_pages import SourcePages, WebPages
from contracts.catalog import DroppedReason, FieldProfile
from contracts.tokens import TOKENS_PER_SEARCH, MeterSearchTrial

FILLED = "fylls"
FROM_PAGE = "ur sidan"
MISSING = "saknas"
SAID: dict[DroppedReason, str] = {
    DroppedReason.BAD_VALUE: "format",
    DroppedReason.NO_SOURCE: "utan källa",
    DroppedReason.INVENTED_SOURCE: "påhittad",
    DroppedReason.UNSUPPORTED: "håller inte",
}


@dataclass(frozen=True)
class Outcome:
    """One case as Catalog's check left it: per field what happened, in the profile's order."""

    name: str
    trial: MeterSearchTrial
    fields: dict[str, str]

    @property
    def filled(self) -> int:
        return sum(1 for each in self.fields.values() if each in (FILLED, FROM_PAGE))

    @property
    def from_page(self) -> int:
        return sum(1 for each in self.fields.values() if each == FROM_PAGE)

    @property
    def answered(self) -> int:
        return sum(1 for each in self.fields.values() if each != MISSING)


def outcome(name: str, trial: MeterSearchTrial, pages: SourcePages | None = None) -> Outcome:
    """Catalog's check of the evidence on the trial's answer, as for a person's search: with
    pages, the cited pages are read where the search's excerpt does not hold the value."""
    profile = FieldProfile(trial.asked.profile)
    asked = {each.key for each in trial.asked.fields}
    keys = [key for key in wanted(profile) if key in asked]
    now = datetime.now(UTC)
    checked = check(profile, keys, trial.values, trial.results, now)
    if checked.unread and pages is not None:
        texts = pages.read(checked.unread)
        checked = check(profile, keys, trial.values, trial.results, now, pages=texts)
    dropped = {each.key: SAID[each.reason] for each in checked.dropped}

    def said(key: str) -> str:
        if key in checked.from_page:
            return FROM_PAGE
        return FILLED if key in checked.fields else dropped.get(key, MISSING)

    return Outcome(name=name, trial=trial, fields={key: said(key) for key in keys})


def read(folder: Path, pages: SourcePages | None = None) -> list[Outcome]:
    """Every case in the folder, in the order of their names. Raises ValueError."""
    found = []
    for path in sorted(folder.glob("*.json")):
        try:
            trial = MeterSearchTrial.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise ValueError(f"{path.name} är inte ett fall ur provet.") from error
        found.append(outcome(path.stem, trial, pages))
    return found


def _marking(trial: MeterSearchTrial) -> str:
    asked = trial.asked
    return f"{asked.litt}, {asked.operator}" if asked.operator else asked.litt


def _mean_tokens(outcomes: list[Outcome]) -> float:
    return sum(each.trial.tokens for each in outcomes) / len(outcomes)


def summary(outcomes: list[Outcome]) -> list[str]:
    """The counts per case and in all, as Markdown: no values and no sources."""
    lines = [
        "| Fall | Märkning | Fylls | I svaret | Källor | Sökningar | Tokens in | Kostnad (kr) "
        "| Tokens med faktorn |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for each in outcomes:
        trial = each.trial
        lines.append(
            f"| {each.name} | {_marking(trial)} | {each.filled} av {len(each.fields)} "
            f"| {each.answered} | {len(trial.results)} | {trial.searches} | {trial.input_tokens} "
            f"| {trial.cost_sek:.2f} | {trial.tokens} |"
        )
    asked = sum(len(each.fields) for each in outcomes)
    filled = sum(each.filled for each in outcomes)
    from_page = sum(each.from_page for each in outcomes)
    answered = sum(each.answered for each in outcomes)
    sek = sum(each.trial.cost_sek for each in outcomes)
    lines += [
        "",
        f"{len(outcomes)} fall. {filled} av {asked} fält fylls, {from_page} av dem ur den "
        f"citerade sidan, och {answered} hade ett värde i svaret. Kostnaden var {sek:.2f} kr, "
        f"i medel {sek / len(outcomes):.2f} kr och "
        f"{_mean_tokens(outcomes):.1f} tokens med faktorn per sökning. Priset i Catalog är "
        f"{TOKENS_PER_SEARCH} tokens (CAT-172).",
    ]
    return lines


def by_field(outcomes: list[Outcome]) -> list[str]:
    """What happened to each field in each case, as Markdown: no values."""
    keys = list(dict.fromkeys(key for each in outcomes for key in each.fields))
    lines = [
        "| Fält | " + " | ".join(each.name for each in outcomes) + " |",
        "| --- |" + " --- |" * len(outcomes),
    ]
    for key in keys:
        lines.append(
            f"| {key} | " + " | ".join(each.fields.get(key, "") for each in outcomes) + " |"
        )
    return lines


def _cell(text: str) -> str:
    return " ".join(text.replace("|", "/").split())


def report(outcomes: list[Outcome]) -> str:
    """Everything, for the person who sets the price: the counts, the fields per case, and for
    each case the values with their excerpts and Claude's answer as written."""
    first = outcomes[0].trial
    lines = [
        "# Prov av webbsökningen",
        "",
        f"Modell {first.model}, verktyget {first.tool}. Catalogs kontroll av belägget "
        f"(catalog/evidence.py) körd {datetime.now(UTC):%Y-%m-%d %H:%M} UTC.",
        "",
        "## Sammanfattning",
        "",
        *summary(outcomes),
        "",
        "## Fälten per fall",
        "",
        *by_field(outcomes),
    ]
    for each in outcomes:
        trial = each.trial
        values = {value.key: value for value in trial.values}
        lines += [
            "",
            f"## {each.name}: {_marking(trial)}",
            "",
            "| Fält | Utfall | Värde | Källor |",
            "| --- | --- | --- | --- |",
        ]
        for key, happened in each.fields.items():
            value = values.get(key)
            if value is None:
                lines.append(f"| {key} | {happened} | | |")
                continue
            cited = "<br>".join(
                f"{_cell(citation.cited_text) or '(inget utdrag)'} ({_cell(citation.url)})"
                for citation in value.citations
            )
            lines.append(f"| {key} | {happened} | {_cell(value.value)} | {cited} |")
        lines += ["", "Claudes svar:", "", "```text", trial.text.replace("```", "'''"), "```"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("mapp", help="mappen med fallen från id.prov_webbsokning --spara")
    parser.add_argument("--rapport", default="", help="filen där allt skrivs, i Markdown")
    parser.add_argument(
        "--utan-sidor",
        action="store_true",
        help="läs inte de citerade sidorna: bara sökningens eget utdrag",
    )
    args = parser.parse_args(argv)
    try:
        outcomes = read(Path(args.mapp), None if args.utan_sidor else WebPages())
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if not outcomes:
        print(f"Inga fall i {args.mapp}.", file=sys.stderr)
        return 2
    print("\n".join(summary(outcomes)))
    print()
    print("\n".join(by_field(outcomes)))
    if args.rapport:
        Path(args.rapport).write_text(report(outcomes), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

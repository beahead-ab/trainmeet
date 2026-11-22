"""Provet av webbsökningen med den riktiga nyckeln (#53 del b, CAT-172, TOKEN-30, C40).

    python -m id.prov_webbsokning --litt Hbis --bolag "Green Cargo" --slag freight_wagon
    python -m id.prov_webbsokning --fall alla --spara prov
    python -m catalog.prov_webbsokning prov --rapport prov/rapport.md

Gör riktiga sökningar hos Anthropic, med nyckeln i filen som ID_SEARCH_KEY_FILE pekar på (eller
--nyckelfil): ett fall med --litt, eller fallen i FALL med --fall alla (eller numren, --fall 1,6).
För varje fall skrivs antalen ut: tokens in och ut, sökningar, källor, värden med och utan
källhänvisning, och vad det kostade. Med --spara sparas varje fall som en fil (MeterSearchTrial,
contracts/tokens.py) med Claudes svar, värdena med källhänvisningarna och källorna. Catalogs
prov (catalog/prov_webbsokning.py) kontrollerar sedan belägget per fält på samma svar, så att det
syns om ett fält saknades i källorna eller föll i bearbetningen. Priset i Catalog, 24 tokens,
stäms av mot verklig kostnad (CAT-172, C22): det här är provet.

Programmet körs aldrig av testerna. I GitHub körs det bara av jobbet "Prov av webbsökningen"
(.github/workflows/prov-webbsokning.yml), när någon startar det för hand (beslut 22 november).
Det kostar riktiga pengar hos Anthropic, ungefär 0,15 dollar per fall, men drar inga
TrainMeet-tokens och rör ingen databas. Nyckeln skrivs aldrig ut, och inte heller värdena eller
källornas text: bara antalen. Filerna har värdena och källorna, aldrig nyckeln. Bara märkningen
skickas, som i mätaren (id/search.py).

I testmiljön körs det i ID:s container, där nyckeln ligger i valvet:

    docker compose exec id-api python -m id.prov_webbsokning --litt Hbis --bolag "Green Cargo"
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx

from contracts.tokens import TOKENS_PER_SEARCH, MeterSearch, MeterSearchField, MeterSearchTrial
from id.owner import TOKEN_VALUE_SEK
from id.search import AnthropicSearch, Searched, SearchFailed, settings_from

FIELDS = [
    # The metric type data a search fills for a Swedish or European prototype (CAT-157), as
    # Catalog's field register names them.
    MeterSearchField(key="epoch", label="Epoch", unit="", kind="text"),
    MeterSearchField(
        key="length_over_buffers", label="Length over buffers", unit="mm", kind="number"
    ),
    MeterSearchField(key="wheelbase", label="Wheelbase", unit="mm", kind="number"),
    MeterSearchField(key="weight", label="Weight", unit="t", kind="number"),
    MeterSearchField(key="max_speed", label="Top speed", unit="km/h", kind="number"),
    MeterSearchField(key="load", label="Load", unit="t", kind="number"),
    MeterSearchField(key="axles", label="Axles", unit="", kind="integer"),
    MeterSearchField(key="built", label="Built", unit="", kind="text"),
    MeterSearchField(key="brake", label="Brake", unit="", kind="text"),
]

Kind = Literal["locomotive", "freight_wagon", "passenger_coach", "multiple_unit", "other"]


@dataclass(frozen=True)
class Fall:
    """A marking to search for, and why it is one of the cases."""

    litt: str
    bolag: str
    slag: Kind | None
    profil: Literal["SE", "EU"]
    varfor: str


FALL: tuple[Fall, ...] = (
    # Swedish and European prototypes of every kind, easy and hard, so that the price is set on
    # what a search usually costs and fills (CAT-172): the report of 22 November.
    Fall("Hbis", "Green Cargo", "freight_wagon", "SE", "det första provet, ett svårt fall"),
    Fall("Rc4", "Green Cargo", "locomotive", "SE", "svenskt ellok med många källor"),
    Fall("T44", "Green Cargo", "locomotive", "SE", "svenskt diesellok"),
    Fall("B7", "SJ", "passenger_coach", "SE", "personvagn"),
    Fall("X2", "SJ", "multiple_unit", "SE", "motorvagnståg"),
    Fall("Hbis-tt 293", "DB Cargo", "freight_wagon", "EU", "bolagets katalog, enheten i rubriken"),
    Fall("Hbbins", "Rail Cargo Austria", "freight_wagon", "EU", "faktablad som PDF"),
    Fall("185", "DB Cargo", "locomotive", "EU", "europeiskt ellok"),
    Fall("Fals", "Green Cargo", "freight_wagon", "SE", "svensk vagn med bara en UIC-kod"),
)


def chosen(given: str) -> list[int]:
    """The cases' numbers, from 1: alla, or numbers with commas. Raises ValueError."""
    if given.strip().casefold() == "alla":
        return list(range(1, len(FALL) + 1))
    numbers = [int(part) for part in given.split(",") if part.strip()]
    if not numbers or any(not 1 <= number <= len(FALL) for number in numbers):
        raise ValueError(given)
    return list(dict.fromkeys(numbers))


def _file_name(number: int, litt: str) -> str:
    return f"{number:02d}-{re.sub(r'[^a-z0-9]+', '-', litt.casefold()).strip('-') or 'fall'}.json"


def main(argv: list[str] | None = None, http: httpx.Client | None = None) -> int:
    """http is the tests' own, which answers instead of Anthropic."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--litt", default="", help="littera eller UIC-typ, t.ex. Hbis")
    parser.add_argument("--bolag", default="", help="bolaget, t.ex. Green Cargo")
    parser.add_argument(
        "--slag",
        default=None,
        choices=["locomotive", "freight_wagon", "passenger_coach", "multiple_unit", "other"],
    )
    parser.add_argument("--profil", default="SE", choices=["SE", "EU"])
    parser.add_argument("--fall", default="", help="alla, eller fallens nummer: 1,6")
    parser.add_argument("--spara", default="", help="mappen där varje fall sparas som en fil")
    parser.add_argument("--nyckelfil", default=None, help="i stället för ID_SEARCH_KEY_FILE")
    parser.add_argument("--in-usd", type=float, default=2.0, help="dollar per miljon tokens in")
    parser.add_argument("--ut-usd", type=float, default=10.0, help="dollar per miljon tokens ut")
    parser.add_argument("--usd-sek", type=float, default=9.7, help="kronor per dollar")
    parser.add_argument("--faktor", type=float, default=2.0, help="påslaget för AI (TK6)")
    args = parser.parse_args(argv)

    if args.fall:
        try:
            cases = [(number, FALL[number - 1]) for number in chosen(args.fall)]
        except ValueError:
            print(f"--fall är alla eller nummer från 1 till {len(FALL)}.", file=sys.stderr)
            return 2
    elif args.litt:
        cases = [(1, Fall(args.litt, args.bolag, args.slag, args.profil, "för hand"))]
    else:
        print("Ange --litt för ett fall, eller --fall alla.", file=sys.stderr)
        return 2
    env = dict(os.environ)
    if args.nyckelfil:
        env["ID_SEARCH_KEY_FILE"] = args.nyckelfil
    settings = settings_from(env)
    if settings is None:
        print("Nyckeln saknas: ID_SEARCH_KEY_FILE pekar inte på en fil.", file=sys.stderr)
        return 2
    folder = Path(args.spara) if args.spara else None
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)

    search = AnthropicSearch(settings, http=http)
    print(
        f"Modell: {settings.model}, verktyg: {settings.tool}, högst {settings.max_uses} sökningar"
    )
    failed = 0
    spent: list[tuple[float, float, int]] = []
    for number, case in cases:
        print(f"\nFall {number}: {case.litt}, {case.bolag or 'utan bolag'} ({case.varfor})")
        asked = MeterSearch(
            reservation=uuid4(),  # the meter's own, never sent to Anthropic
            litt=case.litt,
            operator=case.bolag,
            kind=case.slag,
            profile=case.profil,
            fields=FIELDS,
        )
        try:
            found = search.search(asked)
        except SearchFailed as error:
            print(f"Sökningen gick inte: {error}", file=sys.stderr)
            failed += 1
            continue
        usd, sek, tokens = _cost(found, settings.price_usd, args)
        spent.append((usd, sek, tokens))
        _print(found, usd, sek, tokens, args.faktor)
        if folder is not None:
            trial = MeterSearchTrial(
                asked=asked,
                model=settings.model,
                tool=settings.tool,
                text=found.text,
                values=found.values,
                results=found.results,
                searches=found.searches,
                input_tokens=found.input_tokens,
                output_tokens=found.output_tokens,
                cost_usd=round(usd, 6),
                cost_sek=round(sek, 4),
                tokens=tokens,
            )
            (folder / _file_name(number, case.litt)).write_text(
                trial.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
    if len(cases) > 1 and spent:
        usd_all = sum(each[0] for each in spent)
        sek_all = sum(each[1] for each in spent)
        mean = sek_all / len(spent)
        tokens_mean = max(1, math.ceil(mean * args.faktor / TOKEN_VALUE_SEK))
        print(
            f"\nTotalt för {len(spent)} fall: {usd_all:.4f} dollar, {sek_all:.2f} kr. "
            f"I medel {mean:.2f} kr per sökning, {tokens_mean} tokens med faktorn "
            f"{args.faktor:g}. Priset i Catalog är {TOKENS_PER_SEARCH} tokens (CAT-172)."
        )
    if failed:
        print(f"{failed} av {len(cases)} sökningar gick inte.", file=sys.stderr)
    return 1 if failed else 0


def _cost(found: Searched, price_usd: float, args: argparse.Namespace) -> tuple[float, float, int]:
    """What one search cost: the tokens in and out and the search fee, in dollars, in kronor and
    in TrainMeet tokens with the factor (TK6)."""
    usd = (found.input_tokens * args.in_usd + found.output_tokens * args.ut_usd) / 1e6
    usd += found.searches * price_usd / 1000
    sek = usd * args.usd_sek
    return usd, sek, max(1, math.ceil(sek * args.faktor / TOKEN_VALUE_SEK))


def _print(found: Searched, usd: float, sek: float, tokens: int, factor: float) -> None:
    """The counts only: never a value or a source's text."""
    cited = sum(1 for value in found.values if value.citations)
    print(f"Tokens in: {found.input_tokens}")
    print(f"Tokens ut: {found.output_tokens}")
    print(f"Sökningar: {found.searches}")
    print(f"Källor i sökresultatet: {len(found.results)}")
    print(f"Värden: {len(found.values)} av {len(FIELDS)} fält, {cited} med källhänvisning")
    print(f"Kostnad: {usd:.4f} dollar, {sek:.2f} kr")
    print(
        f"Med faktorn {factor:g} är det {tokens} tokens. Priset i Catalog är "
        f"{TOKENS_PER_SEARCH} tokens (CAT-172)."
    )


if __name__ == "__main__":
    raise SystemExit(main())

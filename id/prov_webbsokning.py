"""Ett första prov av webbsökningen med den riktiga nyckeln (#53 del b, CAT-172, TOKEN-30, C40).

    python -m id.prov_webbsokning --litt Hbis --bolag "Green Cargo" --slag freight_wagon

Gör EN riktig sökning hos Anthropic, med nyckeln i filen som ID_SEARCH_KEY_FILE pekar på (eller
--nyckelfil), och skriver ut vad den kostade: tokens in och ut, antal sökningar, antal källor
och hur många värden som kom med och utan källhänvisning. Priset i Catalog, 24 tokens, ska
stämmas av mot verklig kostnad i första provet (CAT-172, C22): det här är det provet.

Programmet körs för hand, aldrig av testerna eller av GitHub, och kostar riktiga pengar hos
Anthropic: en sökning är några ören till någon krona. Det drar inga TrainMeet-tokens och rör
ingen databas. Nyckeln skrivs aldrig ut, och inte heller värdena eller källornas text: bara
antalen. Bara märkningen skickas, som i mätaren (id/search.py).

I testmiljön körs det i ID:s container, där nyckeln ligger i valvet:

    docker compose exec id-api python -m id.prov_webbsokning --litt Hbis --bolag "Green Cargo"
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from uuid import uuid4

import httpx

from contracts.tokens import TOKENS_PER_SEARCH, MeterSearch, MeterSearchField
from id.owner import TOKEN_VALUE_SEK
from id.search import AnthropicSearch, SearchFailed, settings_from

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


def main(argv: list[str] | None = None, http: httpx.Client | None = None) -> int:
    """http is the tests' own, which answers instead of Anthropic."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--litt", required=True, help="littera eller UIC-typ, t.ex. Hbis")
    parser.add_argument("--bolag", default="", help="bolaget, t.ex. Green Cargo")
    parser.add_argument(
        "--slag",
        default=None,
        choices=["locomotive", "freight_wagon", "passenger_coach", "multiple_unit", "other"],
    )
    parser.add_argument("--profil", default="SE", choices=["SE", "EU"])
    parser.add_argument("--nyckelfil", default=None, help="i stället för ID_SEARCH_KEY_FILE")
    parser.add_argument("--in-usd", type=float, default=2.0, help="dollar per miljon tokens in")
    parser.add_argument("--ut-usd", type=float, default=10.0, help="dollar per miljon tokens ut")
    parser.add_argument("--usd-sek", type=float, default=9.7, help="kronor per dollar")
    parser.add_argument("--faktor", type=float, default=2.0, help="påslaget för AI (TK6)")
    args = parser.parse_args(argv)

    env = dict(os.environ)
    if args.nyckelfil:
        env["ID_SEARCH_KEY_FILE"] = args.nyckelfil
    settings = settings_from(env)
    if settings is None:
        print("Nyckeln saknas: ID_SEARCH_KEY_FILE pekar inte på en fil.", file=sys.stderr)
        return 2
    asked = MeterSearch(
        reservation=uuid4(),  # the meter's own, never sent to Anthropic
        litt=args.litt,
        operator=args.bolag,
        kind=args.slag,
        profile=args.profil,
        fields=FIELDS,
    )
    search = AnthropicSearch(settings, http=http)
    try:
        found = search.search(asked)
    except SearchFailed as failed:
        print(f"Sökningen gick inte: {failed}", file=sys.stderr)
        return 1

    cited = sum(1 for value in found.values if value.citations)
    usd = (found.input_tokens * args.in_usd + found.output_tokens * args.ut_usd) / 1e6
    usd += found.searches * settings.price_usd / 1000
    sek = usd * args.usd_sek
    tokens = max(1, math.ceil(sek * args.faktor / TOKEN_VALUE_SEK))
    print(
        f"Modell: {settings.model}, verktyg: {settings.tool}, högst {settings.max_uses} sökningar"
    )
    print(f"Tokens in: {found.input_tokens}")
    print(f"Tokens ut: {found.output_tokens}")
    print(f"Sökningar: {found.searches}")
    print(f"Källor i sökresultatet: {len(found.results)}")
    print(f"Värden: {len(found.values)} av {len(FIELDS)} fält, {cited} med källhänvisning")
    print(f"Kostnad: {usd:.4f} dollar, {sek:.2f} kr")
    print(
        f"Med faktorn {args.faktor:g} är det {tokens} tokens. Priset i Catalog är "
        f"{TOKENS_PER_SEARCH} tokens (CAT-172)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

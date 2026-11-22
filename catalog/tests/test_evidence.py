"""Webbsökningens krav på källor (#53 del b, CAT-167–CAT-170): a source must be in the real
search result, the publisher is classed against the small reviewed list, and an excerpt must
hold the value. Ported from TrainCatalog's catalog/test_research.py (ResearchProviderTests):
the old tests' rules, for the answer the meter gives now. No database and no search.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from catalog.evidence import MOST_PER_FIELD, carried, check, normalized, numbers, shown, supports
from catalog.prototype_fields import BY_KEY
from catalog.prototype_search import NOT_SEARCHED, fields_for, wanted
from catalog.publishers import PUBLISHERS, publisher_kind, safe_url
from contracts.catalog import DroppedReason, FieldProfile, PublisherKind
from contracts.tokens import MeterSearchResult, MeterSearchValue

URL = "https://www.museum.example.org/fordon/testtyp"
OTHER = "https://unreviewed.example/testtyp"
AT = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)
SE = FieldProfile.SE
WANTED = wanted(SE)


@pytest.fixture(autouse=True)
def a_pretend_museum(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tests' sources are made up, so their known publisher is a pretend museum, put on
    the list for the test: no real publisher is given words it never wrote."""
    monkeypatch.setitem(PUBLISHERS, "museum.example.org", PublisherKind.MUSEUM)


def result(url: str = URL, title: str = "Testtyp – Museet") -> MeterSearchResult:
    return MeterSearchResult(url=url, title=title)


def value(key: str, said: str, *cited: tuple[str, str]) -> MeterSearchValue:
    """A value as the meter gives it, with (address, excerpt) for each citation."""
    return MeterSearchValue.model_validate(
        {
            "key": key,
            "value": said,
            "citations": [{"url": url, "title": "", "cited_text": text} for url, text in cited],
        }
    )


def reasons(checked: Any) -> dict[str, DroppedReason]:
    return {dropped.key: dropped.reason for dropped in checked.dropped}


# --- A source must be in the real search result (CAT-167) ---------------------------------------


def test_a_source_the_search_did_not_find_is_invented_and_refused() -> None:
    """The AI names a page with the right words on it, but the search never found that page."""
    invented = "https://www.museum.example.org/fordon/en-sida-som-inte-finns"
    checked = check(
        SE,
        WANTED,
        [
            value("max_speed", "100", (invented, "Största tillåtna hastighet 100 km/h")),
            value("axles", "2", (URL, "En tvåaxlig godsvagn")),
        ],
        [result()],
        AT,
    )
    assert checked.fields == {"axles": "2"}
    assert reasons(checked) == {"max_speed": DroppedReason.INVENTED_SOURCE}
    assert "max_speed" not in checked.evidence


@pytest.mark.parametrize(
    "link",
    [
        "javascript:alert(1)",
        "https://localhost/test",
        "http://127.0.0.1/x",
        "https://a.local/x",
        "https://u:p@www.museum.example.org/a",
        "https://www.museum.example.org:22/a",
        "ftp://www.museum.example.org/a",
        "https://www.museum.example.org/a b",
        "",
    ],
)
def test_only_a_public_web_address_is_a_source(link: str) -> None:
    """Also when the search itself is said to have found it: such an address is never a source,
    and never becomes a link."""
    assert safe_url(link) is None
    checked = check(
        SE,
        WANTED,
        [value("max_speed", "100", (link or "x", "Största tillåtna hastighet 100 km/h"))],
        [MeterSearchResult(url=link or "x")],
        AT,
    )
    assert checked.fields == {} and reasons(checked) == {"max_speed": DroppedReason.INVENTED_SOURCE}


def test_the_same_page_is_the_same_address_without_its_tracking() -> None:
    assert safe_url("https://WWW.Museum.Example.ORG/fordon?utm_source=x&id=7#top") == (
        "https://www.museum.example.org/fordon?id=7"
    )
    checked = check(
        SE,
        WANTED,
        [value("max_speed", "100", (URL + "?utm_campaign=sok", "sth 100 km/h"))],
        [result()],
        AT,
    )
    assert checked.evidence["max_speed"][0]["url"] == URL


def test_a_value_without_any_source_is_dropped() -> None:
    checked = check(SE, WANTED, [value("max_speed", "100")], [result()], AT)
    assert checked.fields == {} and reasons(checked) == {"max_speed": DroppedReason.NO_SOURCE}


def test_an_empty_search_gives_nothing_and_invents_nothing() -> None:
    checked = check(SE, WANTED, [], [], AT)
    assert (checked.fields, checked.evidence, checked.dropped) == ({}, {}, [])


# --- The publisher is classed against the small reviewed list (CAT-168) -------------------------


def test_the_reviewed_list_is_small_and_names_exact_hosts() -> None:
    """One file holds the list. A host is written bare: no scheme, no www, no path, in lower
    case, and its class is never unknown."""
    assert 5 <= len(PUBLISHERS) <= 60
    assert publisher_kind("https://www.jarnvagsmuseet.se/x") is PublisherKind.MUSEUM
    for host, kind in PUBLISHERS.items():
        assert host == host.lower().strip() and "." in host
        assert not host.startswith("www.") and "/" not in host and ":" not in host
        assert kind is not PublisherKind.UNKNOWN
    assert publisher_kind("https://www.sj.se/fleet") is PublisherKind.OPERATOR
    assert publisher_kind("https://sj.se/fleet") is PublisherKind.OPERATOR
    assert publisher_kind("https://www.mobility.siemens.com/global") is PublisherKind.MANUFACTURER
    assert publisher_kind(URL) is PublisherKind.MUSEUM
    assert publisher_kind("https://bransch.trafikverket.se/x") is PublisherKind.ARCHIVE


@pytest.mark.parametrize(
    "url",
    [
        "https://jmedia.wiki/rc6",
        "https://handwiki.org/wiki/Rc6",
        "https://www.sj.se.evil.example/rc6",
        "https://forum.sj.se/rc6",
        "https://unreviewed.example/rc6",
        "https://evil.example/www.sj.se/rc6",
        "https://sj.se.example/rc6",
        "inte en adress",
    ],
)
def test_a_wiki_a_subdomain_or_a_lookalike_is_never_a_known_publisher(url: str) -> None:
    """Only the exact host counts: nothing inherits a publisher's class by naming it."""
    assert publisher_kind(url) is PublisherKind.UNKNOWN


def test_the_class_is_catalogs_own_and_a_known_publisher_comes_first() -> None:
    """The evidence keeps the address; the class is read from the list when it is shown, so the
    AI has no say in it. Of several sources that hold the value, a known publisher's is first,
    and at most three are kept."""
    excerpt = "Största tillåtna hastighet 100 km/h"
    unknown = [f"https://okand{i}.example/typ" for i in range(4)]
    checked = check(
        SE,
        WANTED,
        [value("max_speed", "100", *[(url, excerpt) for url in unknown], (URL, excerpt))],
        [result(url, "Okänd") for url in unknown] + [result()],
        AT,
    )
    kept = checked.evidence["max_speed"]
    assert len(kept) == MOST_PER_FIELD == 3
    assert [item["url"] for item in kept] == [URL, unknown[0], unknown[1]]
    assert "publisher" not in kept[0], "the class is not stored"
    seen = shown(checked.evidence, checked.fields)["max_speed"]
    assert [e.publisher for e in seen] == [
        PublisherKind.MUSEUM,
        PublisherKind.UNKNOWN,
        PublisherKind.UNKNOWN,
    ]


# --- An excerpt of the source must hold the value (CAT-169) -------------------------------------


@pytest.mark.parametrize("text", ["", "kort", "En text som inte säger något om hastigheten alls"])
def test_a_missing_or_unrelated_excerpt_cannot_fill_a_field(text: str) -> None:
    checked = check(SE, WANTED, [value("max_speed", "100", (URL, text))], [result()], AT)
    assert checked.fields == {} and reasons(checked) == {"max_speed": DroppedReason.UNSUPPORTED}


def test_when_it_was_ordered_or_presented_is_not_when_it_was_built() -> None:
    for text in ("Ordered in 1970 from the works", "Beställdes 1970 av SJ", "Presented 1970"):
        assert supports("built", "1970", text) is False
    assert supports("built", "1970", "Byggd 1970 av Kalmar Verkstad") is True
    assert supports("built", "1967-1988", "Loken byggdes 1967–1988 av ASEA") is True
    assert supports("built", "1975", "Tillverkningsnummer 19750") is False


@pytest.mark.parametrize(
    ("key", "said", "excerpt", "holds"),
    [
        # 1 435 mm = 1435 mm = 1,435 m: the same number, however it is written.
        ("wheelbase", "1435", "Mått 1 435 mm", True),
        ("wheelbase", "1435", "Mått 1435 mm.", True),
        ("wheelbase", "1435", "Mått 1,435 m", True),
        ("wheelbase", "1435", "Maß 1.435 mm", True),
        ("wheelbase", "1435", "Mått 1.435 m", True),
        ("wheelbase", "1435", "Mått 143,5 cm", True),
        ("wheelbase", "1435", "Mått 1\u00a0435\u00a0mm", True),
        ("wheelbase", "1435", "Mått 1436 mm", False),
        ("wheelbase", "1435", "Mått 11 435 mm", False),
        ("wheelbase", "1435", "Mått 1435", False),
        ("wheelbase", "1435", "Mått 1435 kg", False),
        ("length_over_buffers", "14020", "Längd över buffertar 14 020 mm", True),
        ("length_over_buffers", "14020", "Länge über Puffer: 14,02 m", True),
        ("length_over_buffers", "14020", "LüP 14.020 mm", True),
        ("length_over_buffers", "14020", "Längd 14,2 m", False),
        ("weight", "78", "Tjänstevikt 78 ton", True),
        ("weight", "78", "Tjänstevikt 78 000 kg", True),
        ("weight", "78.5", "Dienstmasse 78,5 t", True),
        ("weight", "78", "78 tåg om dagen", False),
        ("max_speed", "100", "Största tillåtna hastighet 100 km/h", True),
        ("max_speed", "100", "sth 100 km/tim", True),
        ("max_speed", "100", "sth 1100 km/h", False),
        ("max_speed", "100", "Top speed 100 mph", False),
        ("max_speed_mph", "60", "Top speed 60 mph", True),
        ("max_speed_mph", "60", "Top speed 60 km/h", False),
        ("weight_lbs", "62000", "LT WT 62,000 lbs", True),
        ("length_ft", "40.5", "Inside length 40 ft 6 in", True),
        ("length_ft", "40.5", "Length 41 ft", False),
        # A whole number of something: the word says of what.
        ("axles", "2", "En tvåaxlig godsvagn", True),
        ("axles", "4", "Loket har 4 axlar", True),
        ("axles", "4", "vierachsige Lokomotive", True),
        ("axles", "4", "sechsachsige Lokomotive", False),
        ("axles", "4", "4-achsig", True),
        ("axles", "4", "Byggd 1984 i 4 exemplar", False),
        # Text after normalising: case, spaces and the kind of dash do not matter.
        ("brake", "KE-GP", "Broms:  ke–gp", True),
        ("epoch", "IV", "aktiv i epok IV", True),
        ("epoch", "IV", "in active service", False),
        ("built", "1967-1988", "byggda 1967 – 1988", True),
    ],
)
def test_numbers_with_units_are_compared_as_numbers_and_text_after_normalising(
    key: str, said: str, excerpt: str, holds: bool
) -> None:
    assert supports(key, said, excerpt) is holds, excerpt


@pytest.mark.parametrize(
    ("key", "said", "excerpt"),
    [
        # The first trial with the real key (22 November): the values as two companies' own
        # pages write them. Five of the ten were dropped before, though the source holds them.
        ("weight", "15.5", "Average tare weight (kg) 15,500"),
        ("max_speed", "120", "Maximum speed (km/h) 120"),
        ("axles", "2", "Freight wagon with two wheelsets"),
        ("built", "1976", "First year of delivery … 1976"),
        ("brake", "KE-GP-A", "Brake type KE-GP-A"),
        ("length_over_buffers", "14020", "Length over buffers 14.020 mm"),
        ("wheelbase", "8000", "Wheel base 8.000 mm"),
        ("weight", "14.1", "Own weight 14.100 kg"),
        ("axles", "2", "Number of axles 2"),
        # A table whose cells lost the space between them.
        ("length_over_buffers", "14040", "Length over buffers14 040 mm"),
        # The nine cases (22 November): the excerpts as the search gave them, with a middle dot
        # where the table had a cell, and the axles as a wheel arrangement.
        ("weight", "15.5", "Average tare weight (kg) · 15,500 Maximum s..."),
        ("max_speed", "120", "Average tare weight (kg) · 15,500 Maximum speed (km/h) · 120"),
        ("brake", "KE-GP-A", "Brake type · KE-GP-A"),
        ("built", "2000-2008", "Datenblatt Baureihe 185 - Baujahre: · 2000-2008 - Betriebsnummern"),
        (
            "length_over_buffers",
            "15520",
            "Gauge: · 1435 mm - UIC axles: · Bo'Bo' - Length: · 15.52 m",
        ),
        ("axles", "4", "Gauge: · 1435 mm - UIC axles: · Bo'Bo' - Length: · 15.52 m"),
        ("axles", "4", "The TRAXX F140 AC is a four-axle locomotive with an output of 5600 kW"),
    ],
)
def test_a_primary_sources_table_holds_its_values(key: str, said: str, excerpt: str) -> None:
    """A company's table writes the unit in the label, the count after it, and wheelsets for
    axles: the value stands there all the same."""
    assert supports(key, said, excerpt) is True, excerpt
    checked = check(SE, WANTED, [value(key, said, (URL, excerpt))], [result()], AT)
    assert checked.fields == {key: said} and reasons(checked) == {}


@pytest.mark.parametrize(
    ("key", "said", "excerpt", "holds"),
    [
        # The unit in the label holds only the number right after it.
        ("weight", "22.5", "Axle load (t) 22.5", True),
        ("weight", "15.5", "Weight [t]: 15,5", True),
        ("max_speed", "100", "Maximum speed (km/h) 100/120", True),
        ("max_speed", "120", "Maximum speed (km/h) 1200", False),
        ("max_speed", "12", "Maximum speed (km/h) 12.5", False),
        ("max_speed", "120", "Maximum speed (mph) 120", False),
        # A number after a word is read beside the plain one, never instead of it.
        ("max_speed", "120", "BR185 120 km/h", True),
        ("wheelbase", "1435", "Typ11 435 mm", False),
        ("length_over_buffers", "14020", "Length over buffers14020", False),
        # A count after a label only when the label says it is the count.
        ("axles", "4", "Achsen: 4", True),
        ("axles", "4", "Achszahl 4", True),
        ("axles", "4", "Antal axlar: 4", True),
        ("axles", "2", "zwei Radsätze", True),
        ("axles", "2", "2 hjulpar", True),
        ("axles", "2", "4 axles 2 bogies", False),
        ("axles", "2", "Number of axles 24", False),
        ("axles", "2", "Axle load: 22.5 t", False),
        # The wheel arrangement counts the axles, a letter its driven ones and a digit the
        # others, but only after its label.
        ("axles", "6", "Achsfolge Co'Co'", True),
        ("axles", "6", "Axle arrangement: 1'D1'", True),
        ("axles", "4", "Wheel arrangement · B-B", True),
        ("axles", "4", "Bo'Bo' locomotive", False),
        ("axles", "4", "Achsfolge: Bobby", False),
        ("axles", "4", "UIC axles: · Bo'Bo'", True),
        ("axles", "2", "UIC axles: · Bo'Bo'", False),
        ("axles", "4", "Achsen: · 4", True),
        # So many per bogie is not the vehicle's count.
        ("axles", "2", "2 axlar per boggi", False),
        ("axles", "2", "två hjulpar per boggi", False),
        ("axles", "2", "2 Radsätze je Drehgestell", False),
    ],
)
def test_a_label_or_a_glued_number_holds_only_what_it_says(
    key: str, said: str, excerpt: str, holds: bool
) -> None:
    assert supports(key, said, excerpt) is holds, excerpt


def test_how_a_written_number_is_read() -> None:
    assert numbers("1 435") == {1435}
    assert numbers("14,5") == {numbers("14.5").pop()}
    assert len(numbers("1.435")) == 2, "a point before three digits: a decimal or a thousand"
    assert numbers("1.435.000") == {1_435_000}
    assert numbers("62,000.5") == {numbers("62000.5").pop()}
    assert normalized("  KE – GP\n") == "ke-gp"


def test_a_value_the_register_does_not_take_is_dropped_and_a_number_is_written_its_way() -> None:
    checked = check(
        SE,
        WANTED,
        [
            value("max_speed", "ungefär hundra", (URL, "sth 100 km/h")),
            value("length_over_buffers", "14 020,0", (URL, "Längd över buffertar 14 020 mm")),
            value("litt", "Rc6", (URL, "Rc6 är ett lok")),
            value("owner", "Kim", (URL, "Kim äger vagnen")),
        ],
        [result()],
        AT,
    )
    assert checked.fields == {"length_over_buffers": "14020"}
    assert reasons(checked) == {"max_speed": DroppedReason.BAD_VALUE}, "the others were not asked"


def test_the_evidence_and_the_address_are_kept_per_field() -> None:
    """CAT-169: for each field its own source: the value, the address, the title, the excerpt
    and when it was searched."""
    checked = check(
        SE,
        WANTED,
        [
            value("max_speed", "100", (OTHER, "sth 100 km/h")),
            value("axles", "2", (URL, "En  tvåaxlig\ngodsvagn"), (OTHER, "har fyra axlar")),
        ],
        [result(), result(OTHER, "En annan sida")],
        AT,
    )
    assert checked.fields == {"max_speed": "100", "axles": "2"}
    assert checked.evidence == {
        "max_speed": [
            {
                "value": "100",
                "url": OTHER,
                "title": "En annan sida",
                "excerpt": "sth 100 km/h",
                "searched_at": "2026-11-21T09:00:00+00:00",
            }
        ],
        "axles": [
            {
                "value": "2",
                "url": URL,
                "title": "Testtyp – Museet",
                "excerpt": "En tvåaxlig godsvagn",
                "searched_at": "2026-11-21T09:00:00+00:00",
            }
        ],
    }, "only the source whose excerpt holds the value is kept"


# --- Does the evidence still agree with the value that stands there (CAT-170)? -------------------


def test_the_evidence_says_whether_it_still_agrees_with_the_value() -> None:
    checked = check(
        SE,
        WANTED,
        [
            value("max_speed", "100", (URL, "sth 100 km/h")),
            value("axles", "2", (URL, "En tvåaxlig godsvagn")),
        ],
        [result()],
        AT,
    )
    as_searched = shown(checked.evidence, checked.fields)
    assert all(e.agrees for items in as_searched.values() for e in items)
    # The value is changed afterwards: the excerpt no longer holds it, and the evidence says so.
    changed = shown(checked.evidence, {"max_speed": "120", "axles": "2"})
    assert [e.agrees for e in changed["max_speed"]] == [False]
    assert changed["max_speed"][0].value == "100", "what the excerpt was found to hold"
    assert [e.agrees for e in changed["axles"]] == [True]
    # The same value written another way still agrees: it is compared as a number.
    assert shown(checked.evidence, {"max_speed": "100.0"})["max_speed"][0].agrees is True
    # A field that is emptied has no evidence to show, and a change does not take it along.
    assert "axles" not in shown(checked.evidence, {"max_speed": "100"})
    assert set(carried(checked.evidence, {"max_speed": "120"})) == {"max_speed"}


def test_evidence_that_cannot_be_read_is_not_shown() -> None:
    assert shown({"max_speed": [{"url": URL}], "axles": "trasigt"}, {"max_speed": "100"}) == {}
    assert shown(None, {"max_speed": "100"}) == {}


# --- What is asked for ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", list(FieldProfile))
def test_the_search_asks_for_the_profiles_type_data_with_the_registers_units(
    profile: FieldProfile,
) -> None:
    """The fields that are sent come from the register: the key, the English label, the unit
    and the kind. The litt and the operator are the marking itself, and the description is the
    proposer's own words."""
    asked = fields_for(profile)
    assert [f.key for f in asked] == wanted(profile)
    assert not NOT_SEARCHED & {f.key for f in asked}
    for each in asked:
        known = BY_KEY[each.key]
        assert (each.unit, each.kind) == (known.unit, known.kind.value)
    labels = {f.key: f.label for f in fields_for(FieldProfile.US)}
    assert labels["epoch"] == "Era" and labels["length_ft"] == "Length"

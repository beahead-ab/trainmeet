"""Catalogs del av provet av webbsökningen (CAT-172): belägget per fält på fall som ID:s prov
sparade (MeterSearchTrial). Fallen är påhittade här: ingen sökning, ingen nyckel och ingen
databas.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from catalog import prov_webbsokning
from catalog.publishers import PUBLISHERS
from contracts.catalog import PublisherKind
from contracts.tokens import MeterSearchTrial

URL = "https://www.museum.example.org/fordon/hbis"
OTHER = "https://okand.example/hbis"
FIELDS = [
    {"key": "epoch", "label": "Epoch", "unit": "", "kind": "text"},
    {"key": "length_over_buffers", "label": "Length over buffers", "unit": "mm", "kind": "number"},
    {"key": "weight", "label": "Weight", "unit": "t", "kind": "number"},
    {"key": "max_speed", "label": "Top speed", "unit": "km/h", "kind": "number"},
    {"key": "axles", "label": "Axles", "unit": "", "kind": "integer"},
    {"key": "built", "label": "Built", "unit": "", "kind": "text"},
    {"key": "brake", "label": "Brake", "unit": "", "kind": "text"},
]


@pytest.fixture(autouse=True)
def a_pretend_museum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(PUBLISHERS, "museum.example.org", PublisherKind.MUSEUM)


def cited(key: str, said: str, url: str, text: str) -> dict[str, Any]:
    return {"key": key, "value": said, "citations": [{"url": url, "cited_text": text}]}


def trial(litt: str = "Hbis", **changes: Any) -> MeterSearchTrial:
    return MeterSearchTrial.model_validate(
        {
            "asked": {
                "reservation": "00000000-0000-4000-8000-000000000001",
                "litt": litt,
                "operator": "Green Cargo",
                "kind": "freight_wagon",
                "profile": "SE",
                "fields": FIELDS,
            },
            "model": "claude-sonnet-5-5",
            "tool": "web_search_20260318",
            "text": "length_over_buffers: 14020\nweight: 15.5\n",
            "values": [
                cited("length_over_buffers", "14020", URL, "Length over buffers 14.020 mm"),
                cited("weight", "15.5", URL, "Average tare weight (kg) 15,500"),
                cited("max_speed", "120", URL, "Loaded 100 km/h"),
                cited("axles", "två", URL, "two wheelsets"),
                {"key": "built", "value": "1976"},
                cited("brake", "KE-GP", OTHER, "Brake KE-GP"),
            ],
            "results": [{"url": URL, "title": "Hbis – Museet"}],
            "searches": 3,
            "input_tokens": 58_642,
            "output_tokens": 431,
            "cost_usd": 0.1516,
            "cost_sek": 1.47,
            "tokens": 38,
            **changes,
        }
    )


def test_each_field_says_what_catalogs_check_did_with_it() -> None:
    """The same check as for a person's search: kept with its evidence, or dropped and why, or
    not in the answer at all."""
    found = prov_webbsokning.outcome("01-hbis", trial())
    assert found.fields == {
        "epoch": "saknas",
        "length_over_buffers": "fylls",
        "weight": "fylls",
        "max_speed": "håller inte",
        "axles": "format",
        "built": "utan källa",
        "brake": "påhittad",
    }, "in the profile's order, only the fields that were asked"
    assert (found.filled, found.answered) == (2, 6)


class Pages:
    """The cited pages as Catalog would read them, without the network."""

    def __init__(self, texts: dict[str, str]) -> None:
        self.texts = texts
        self.asked: list[list[str]] = []

    def read(self, urls: Sequence[str]) -> dict[str, str]:
        self.asked.append(list(urls))
        return {url: self.texts[url] for url in urls if url in self.texts}


def test_a_value_further_on_in_the_cited_page_is_filled_from_the_page() -> None:
    """The search's excerpt ends before the speed; the page goes on to it (CAT-169)."""
    pages = Pages({URL: "Hbis\nLoaded 100 km/h · empty · Maximum speed (km/h) · 120\nBrake KE-GP"})
    found = prov_webbsokning.outcome("01-hbis", trial(), pages)
    assert found.fields["max_speed"] == "ur sidan"
    assert found.fields["weight"] == "fylls", "the search's own excerpt still comes first"
    assert pages.asked == [[URL]], "only the cited page whose excerpt fell short, once"
    assert (found.filled, found.from_page) == (3, 1)


def test_the_report_has_the_counts_the_fields_and_each_cases_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "prov"
    folder.mkdir()
    (folder / "01-hbis.json").write_text(trial().model_dump_json())
    (folder / "02-rc4.json").write_text(
        trial("Rc4", values=[], text="", cost_sek=0.53, tokens=14).model_dump_json()
    )
    rapport = tmp_path / "rapport.md"
    assert prov_webbsokning.main([str(folder), "--rapport", str(rapport), "--utan-sidor"]) == 0
    printed = capsys.readouterr().out
    assert "| 01-hbis | Hbis, Green Cargo | 2 av 7 | 6 | 1 | 3 | 58642 | 1.47 | 38 |" in printed
    assert "| 02-rc4 | Rc4, Green Cargo | 0 av 7 | 0 |" in printed
    assert (
        "2 fall. 2 av 14 fält fylls, 0 av dem ur den citerade sidan, och 6 hade ett värde i svaret."
    ) in printed
    assert "i medel 1.00 kr och 26.0 tokens med faktorn per sökning" in printed
    assert "| max_speed | håller inte | saknas |" in printed
    for hidden in ("Average tare weight", URL, "15,500"):
        assert hidden not in printed, "the values and the sources only in the report"
    written = rapport.read_text()
    assert "## 01-hbis: Hbis, Green Cargo" in written
    assert (
        "| weight | fylls | 15.5 | Average tare weight (kg) 15,500 "
        "(https://www.museum.example.org/fordon/hbis) |"
    ) in written
    assert "| epoch | saknas | | |" in written
    assert "```text\nlength_over_buffers: 14020\nweight: 15.5\n```" in written


def test_a_folder_without_cases_or_with_another_file_is_refused(tmp_path: Path) -> None:
    assert prov_webbsokning.main([str(tmp_path)]) == 2
    (tmp_path / "annat.json").write_text('{"values": []}')
    assert prov_webbsokning.main([str(tmp_path)]) == 2

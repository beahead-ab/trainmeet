"""Egen AI (4c2, H58, H59, H70): both formats against a stand-in service on this machine."""

from __future__ import annotations

import pytest

from integrationer.ai import AiError, Image, Service, ask, check_address, drawn, probe
from integrationer.tests.fake_ai import KEY, FakeAi, serving


@pytest.mark.parametrize("format", ["chat", "claude"])
def test_both_formats_ask_with_pictures(format: str) -> None:
    with serving() as fake:
        service = Service(format, fake.address, "en-modell", KEY)  # type: ignore[arg-type]
        assert ask(service, "Vilket tal?", [Image("image/png", drawn("407"))]) == "407"
        [asked] = fake.asked
        assert asked["path"] == ("/v1/messages" if format == "claude" else "/chat/completions")
        assert asked["body"]["model"] == "en-modell" and asked["body"]["temperature"] == 0


@pytest.mark.parametrize("format", ["chat", "claude"])
def test_the_probe_checks_that_the_model_reads_pictures(format: str) -> None:
    with serving() as fake:
        probe(Service(format, fake.address, "m", KEY))  # type: ignore[arg-type]
    with serving(FakeAi(blind=True)) as fake, pytest.raises(AiError, match="läste inte talet"):
        probe(Service(format, fake.address, "m", KEY))  # type: ignore[arg-type]


def test_the_key_is_never_in_an_error() -> None:
    with serving() as fake:
        wrong = Service("chat", fake.address, "m", "sk-secret-1234")
        with pytest.raises(AiError) as caught:
            probe(wrong)
        assert str(caught.value) == "AI-tjänsten godtog inte nyckeln."
        assert "1234" not in repr(caught.value) and "1234" not in repr(wrong)
        assert caught.value.__cause__ is None, "the service's own words are not kept"
        with pytest.raises(AiError, match="känner inte adressen"):
            ask(Service("chat", fake.address + "/fel", "m", KEY), "x")
    with pytest.raises(AiError, match="svarar inte"):
        ask(Service("chat", "http://127.0.0.1:9", "m", KEY), "x")


def test_the_address() -> None:
    assert check_address(" https://api.anthropic.com/ ") == "https://api.anthropic.com"
    for bad in ("api.anthropic.com", "ftp://x", "https://user:pw@x", "https://x/?key=1"):
        with pytest.raises(AiError):
            check_address(bad)


def test_the_probe_picture_is_a_png_of_the_number() -> None:
    picture = drawn("042")
    assert picture.startswith(b"\x89PNG") and drawn("042") == picture != drawn("043")

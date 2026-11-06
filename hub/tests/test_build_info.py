from __future__ import annotations

from datetime import UTC, datetime

from hub.build_info import DEFAULT_HUB_NAME, from_env, package_version


def test_without_variables_it_is_a_local_build() -> None:
    info = from_env({})
    assert info.is_local
    assert info.hub_name == DEFAULT_HUB_NAME
    assert info.version == package_version()


def test_the_deploy_variables_are_read() -> None:
    info = from_env(
        {
            "TRAINMEET_COMMIT": "29B7BB260A50B27C29F5147BCB43CCD469F41431",
            "TRAINMEET_PR": "3",
            "TRAINMEET_TITLE": "Grundstommen",
            "TRAINMEET_BUILT": "2026-11-06T07:12:00Z",
            "TRAINMEET_HUB_NAME": "Testhubben",
        }
    )
    assert not info.is_local
    assert info.commit == "29b7bb260a50b27c29f5147bcb43ccd469f41431"
    assert info.short_commit == "29b7bb2"
    assert info.pr == 3
    assert info.pr_url == "https://github.com/beahead-ab/trainmeet/pull/3"
    assert info.title == "Grundstommen"
    assert info.built == datetime(2026, 11, 6, 7, 12, tzinfo=UTC)
    assert info.hub_name == "Testhubben"


def test_values_that_look_wrong_are_left_out() -> None:
    info = from_env(
        {
            "TRAINMEET_COMMIT": "not-a-commit",
            "TRAINMEET_PR": "#3",
            "TRAINMEET_BUILT": "i morse",
            "TRAINMEET_HUB_NAME": "   ",
        }
    )
    assert info.commit is None
    assert info.pr is None
    assert info.built is None
    assert info.hub_name == DEFAULT_HUB_NAME


def test_the_version_comes_from_the_project() -> None:
    assert package_version() != "0.0.0"

import pytest

from ucbranch.root_diagnostics import PROFILES, _base_params, _root_lite_params


def test_diagnostic_profiles_are_explicit():
    assert PROFILES == (
        "official_default",
        "official_root_lite",
        "compact_root_lite",
    )


def test_root_lite_caps_optional_root_work():
    params = _root_lite_params(12.5)
    assert params["limits/time"] == 12.5
    assert params["parallel/maxnthreads"] == 1
    assert params["presolving/maxrestarts"] == 0
    assert params["separating/maxroundsroot"] == 1
    assert params["separating/maxcutsroot"] == 100


def test_time_limit_must_be_positive():
    with pytest.raises(ValueError):
        _base_params(0)

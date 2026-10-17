import pytest

from ucbranch.public_branching import (
    PROGRAM_ROOT,
    PUBLISHED_PROGRAMS,
    _candidate_type,
    _root_lite_params,
    run_mps_branch_budget,
)
from ucbranch.integration import load_program


def test_published_programs_load_unchanged():
    for name in PUBLISHED_PROGRAMS:
        score, features, params, bounds = load_program(PROGRAM_ROOT / name / "program.py")
        assert callable(score)
        assert features and params and bounds
        assert all(0 <= feature < 91 for feature in features)


def test_official_mps_variable_categories():
    assert _candidate_type("t_is_on[g1,1]") == "is_on"
    assert _candidate_type("switch_on[g1,1]") == "switch_on"
    assert _candidate_type("startup[g1,1,1]") == "startup"


def test_root_lite_protocol_is_explicit():
    params = _root_lite_params(300)
    assert params["limits/time"] == 300
    assert params["separating/maxroundsroot"] == 1
    assert params["separating/maxcutsroot"] == 100
    assert params["presolving/maxrestarts"] == 0


def test_branch_budget_rejects_unknown_method(tmp_path):
    path = tmp_path / "toy.mps"
    path.write_text("not read because method validation follows existence check")
    with pytest.raises(ValueError, match="unknown method"):
        run_mps_branch_budget(path, "unknown")

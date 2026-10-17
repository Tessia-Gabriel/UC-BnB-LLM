import itertools
import numpy as np
import pytest
from ucbranch.uc import Instance, build, generate, validate
from ucbranch.solver import solve
from ucbranch.evaluator import check_program
from ucbranch.integration import ROOT


def test_tiny_enumeration():
    instance = Instance(
        0,
        [50.0, 80.0, 40.0],
        [
            dict(
                pmin=10, pmax=60, cost=10, fixed=50, startup=100, ramp=30, up=2, down=2
            ),
            dict(
                pmin=10, pmax=60, cost=20, fixed=30, startup=80, ramp=30, up=2, down=2
            ),
        ],
    )
    best = float("inf")
    for bits in itertools.product((0, 1), repeat=6):
        m = build(instance)
        variables = {v.name: v for v in m.getVars()}
        for k, on in enumerate(bits):
            m.addCons(variables[f"u_{k//3}_{k%3}"] == on)
        m.optimize()
        if str(m.getStatus()) == "optimal":
            values = {v.name: m.getVal(v) for v in m.getVars()}
            best = min(best, validate(instance, values))
    assert solve(instance)["objective"] == pytest.approx(best)


def test_real_branching_and_objective_agreement():
    instance = generate(0, 12, 24)
    score, features, params, _ = check_program(
        ROOT / "configs/phase0/initial_program.py"
    )
    reference = solve(instance)
    assert reference["validity"]
    for method in ("pseudocost", "most_fractional", "llm4branch"):
        result = solve(instance, method, score, features, params)
        assert result["validity"] and result["decisions"] > 0
        assert result["objective"] == pytest.approx(reference["objective"], abs=1e-4)


def test_invalid_output_rejected():
    with pytest.raises(ValueError, match="finite"):
        solve(
            generate(0, 12, 24),
            "llm4branch",
            lambda x, p: np.full(len(x), np.nan),
            [9],
            [1],
        )


def test_upstream_seed_feature_mismatch_rejected():
    with pytest.raises(ValueError, match="undeclared"):
        check_program(
            ROOT / "third_party/llm4branch/examples/brancher/initial_program.py"
        )

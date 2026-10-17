import itertools
import math
import pytest
from ucbranch.uc import generate
from ucbranch.solver import solve
from ucbranch.structured import BranchDecision, KINDS, specifications, solve_structured


def prefer(kind):
    def policy(candidates):
        pool = [c for c in candidates if c.kind == kind]
        if not pool:
            return None
        c = max(pool, key=lambda c: c.features["fractionality"])
        return BranchDecision(c.kind, c.params, 1.0)

    return policy


@pytest.fixture(scope="module")
def reference():
    return solve(generate(0, 12, 24))


@pytest.mark.parametrize("kind", KINDS)
def test_real_children_preserve_optimum(kind, reference):
    result = solve_structured(generate(0, 12, 24), prefer(kind), max_depth=2)
    assert result["validity"]
    assert result["objective"] == pytest.approx(reference["objective"], abs=1e-4)
    assert any(b["kind"] == kind for b in result["branches"])
    for branch in result["branches"]:
        assert branch["down_ub"] < branch["lp_value"] < branch["up_lb"]
        assert branch["up_lb"] == branch["down_ub"] + 1


@pytest.mark.parametrize(
    "policy,reason",
    [
        (lambda c: BranchDecision("BLOCK_ON_COUNT", {}, 0), "unknown_candidate"),
        (
            lambda c: BranchDecision(c[0].kind, c[0].params, float("nan")),
            "invalid_decision",
        ),
        (lambda c: 1 / 0, "policy_error"),
    ],
)
def test_bad_policy_falls_back(policy, reason, reference):
    result = solve_structured(generate(0, 12, 24), policy)
    assert result["validity"] and result["fallbacks"].get(reason, 0) > 0
    assert not result["branches"]
    assert result["objective"] == pytest.approx(reference["objective"], abs=1e-4)


def test_exhaustive_integer_disjunctions():
    instance = generate(0, 2, 4)
    specs = list(specifications(instance))
    assert {s[0] for s in specs} == set(KINDS) - {"GROUP_ON_COUNT"}
    for bits in itertools.product((0, 1), repeat=8):
        values = {f"u_{i}_{t}": bits[i * 4 + t] for i in range(2) for t in range(4)}
        values.update(
            {
                f"v_{i}_{t}": max(
                    0, bits[i * 4 + t] - (bits[i * 4 + t - 1] if t else 0)
                )
                for i in range(2)
                for t in range(4)
            }
        )
        for _, _, names in specs:
            value = sum(values[n] for n in names)
            assert value == int(value)
            for lo in range(len(names)):
                assert (value <= lo) != (value >= lo + 1)
    # Group expressions partition all binary assignments as well.
    for _, _, names in specifications(generate(1, 4, 2)):
        for bits in itertools.product((0, 1), repeat=len(names)):
            for lo in range(len(names)):
                assert (sum(bits) <= lo) != (sum(bits) >= lo + 1)


def test_window_validation_and_depth_fallback(reference):
    with pytest.raises(ValueError):
        list(specifications(generate(0), windows=(0,)))
    result = solve_structured(generate(0, 12, 24), max_depth=-1)
    assert result["validity"] and result["fallbacks"]["depth_limit"] > 0
    assert not result["branches"]
    assert result["objective"] == pytest.approx(reference["objective"], abs=1e-4)

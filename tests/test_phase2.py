import pytest
from ucbranch.phase2 import instances, METHODS, SCENARIOS, bounded_gap, run
from ucbranch.phase2 import VariableRule, HybridRule
from pyscipopt import SCIP_RESULT


def test_suite_is_balanced_and_deterministic():
    suite = list(instances())
    assert len(suite) == 30 and len({x[0] for x in suite}) == 30
    assert {len(x.units) for _,_,x in suite} == {10,20,50}
    assert {s for _,s,_ in suite} == set(SCENARIOS)
    assert [x.to_dict() for _,_,x in suite] == [x.to_dict() for _,_,x in instances()]
    assert all(len(x.demand) == 8 for _,_,x in suite)


def test_gap_metric():
    assert bounded_gap(100, 90) == pytest.approx(.1)
    assert bounded_gap(100, 100) == 0
    assert bounded_gap(1e20, -1e20) == 1
    assert bounded_gap(-1, 1) == 1


def test_non_lp_callbacks_delegate_without_reading_lp():
    for cls in (VariableRule, HybridRule):
        assert cls.branchexecps(None, False)["result"] == SCIP_RESULT.DIDNOTRUN
        assert cls.branchexecext(None, False)["result"] == SCIP_RESULT.DIDNOTRUN


def test_matched_methods_and_trace():
    instance = next(instances())[2]
    results = [run(instance, method, 10) for method in METHODS]
    assert all(r["status"] == "optimal" and r["schedule_valid"] for r in results)
    assert max(r["objective"] for r in results)-min(r["objective"] for r in results) < 1e-4
    assert all(r["settings"] == results[1]["settings"] for r in results[1:])
    for r in results:
        assert r["time_to_first_incumbent"] is not None
        assert 0 <= r["time_to_first_incumbent"] <= r["solver_time"]
        assert r["primal_dual_integral_sampled"] >= 0
        assert r["bound_gap_trace"][0] == (0.0,1.0)
    assert results[2]["variable_decisions"] > 0
    assert results[3]["variable_decisions"] > 0
    assert any(r["branches"] for r in results[4:])

"""Finite UC branching DSL; counts compile to continuous expression aliases.

Aliases add no integer variables. Child-local bounds implement the exhaustive
integer disjunction without adding a constraint to the parent or sibling.
"""

from dataclasses import dataclass
import math
import time
from pyscipopt import Branchrule, SCIP_RESULT, quicksum
from ucbranch.uc import build, validate

KINDS = ("VAR", "UNIT_ON_COUNT", "START_COUNT", "GROUP_ON_COUNT")


@dataclass(frozen=True)
class BranchCandidate:
    kind: str
    params: dict
    lp_value: float
    features: dict[str, float]


@dataclass(frozen=True)
class BranchDecision:
    kind: str
    params: dict
    score: float


def groups(instance):
    """Deterministic rank halves; ties broken by unit index."""
    result = {}
    for low, high, key in (
        ("SLOW", "FAST", "ramp"),
        ("BASELOAD", "PEAKER", "cost"),
        ("LOW_START_COST", "HIGH_START_COST", "startup"),
    ):
        order = sorted(
            range(len(instance.units)), key=lambda i: (instance.units[i][key], i)
        )
        mid = (len(order) + 1) // 2
        result[low], result[high] = tuple(order[:mid]), tuple(order[mid:])
    return result


def specifications(instance, windows=(2, 4)):
    n, h = len(instance.units), len(instance.demand)
    if not windows or any(type(w) is not int or w < 2 for w in windows):
        raise ValueError("windows must contain integer lengths >= 2")
    for i in range(n):
        for t in range(h):
            yield "VAR", dict(unit=i, time=t), (f"u_{i}_{t}",)
        for width in sorted(set(windows)):
            for start in range(h - width + 1):
                for kind, prefix in (("UNIT_ON_COUNT", "u"), ("START_COUNT", "v")):
                    yield kind, dict(unit=i, start=start, end=start + width - 1), tuple(
                        f"{prefix}_{i}_{t}" for t in range(start, start + width)
                    )
    for group, members in groups(instance).items():
        if len(members) >= 2:
            for t in range(h):
                yield "GROUP_ON_COUNT", dict(group=group, time=t), tuple(
                    f"u_{i}_{t}" for i in members
                )


class StructuredBranchrule(Branchrule):
    def __init__(self, model, instance, policy=None, windows=(2, 4), max_depth=8):
        self.policy = policy
        self.max_depth = max_depth
        self.records = []
        self.fallbacks = {}
        self.objects = []
        # PySCIPOpt 4.4 cannot impose node bounds on multi-aggregated aliases.
        model.setParams(
            {
                "presolving/maxrounds": 0,
                "presolving/maxrestarts": 0,
                "presolving/donotmultaggr": True,
                "presolving/donotaggr": True,
            }
        )
        variables = {v.name: v for v in model.getVars()}
        for idx, (kind, params, names) in enumerate(specifications(instance, windows)):
            if kind == "VAR":
                alias = variables[names[0]]
            else:
                alias = model.addVar(
                    name=f"count_{idx}", lb=0, ub=len(names), vtype="C"
                )
                model.addCons(alias == quicksum(variables[name] for name in names))
            self.objects.append((kind, params, names, alias))

    def fallback(self, reason):
        self.fallbacks[reason] = self.fallbacks.get(reason, 0) + 1
        # Returning DIDNOTRUN delegates to SCIP's next enabled branch rule.
        return {"result": SCIP_RESULT.DIDNOTRUN}

    def branchexeclp(self, allowaddcons):
        m = self.model
        if m.getDepth() > self.max_depth:
            return self.fallback("depth_limit")
        candidates = []
        aliases = []
        for kind, params, names, original in self.objects:
            value = float(m.getSolVal(None, original))
            if not math.isfinite(value) or m.isFeasIntegral(value):
                continue
            alias = m.getTransformedVar(original)
            if alias.getLbLocal() >= alias.getUbLocal() - m.feastol():
                continue
            fraction = value - math.floor(value)
            candidates.append(
                BranchCandidate(
                    kind,
                    dict(params),
                    value,
                    dict(
                        fractionality=min(fraction, 1 - fraction),
                        size=float(len(names)),
                        depth=float(m.getDepth()),
                    ),
                )
            )
            aliases.append(alias)
        if not candidates:
            return self.fallback("empty_candidates")
        try:
            if self.policy is None:
                chosen = max(candidates, key=lambda c: c.features["fractionality"])
                decision = BranchDecision(
                    chosen.kind, chosen.params, chosen.features["fractionality"]
                )
            else:
                # Copies keep untrusted policy mutations away from compiler metadata.
                import copy

                decision = self.policy(copy.deepcopy(candidates))
            if not isinstance(decision, BranchDecision) or not math.isfinite(
                decision.score
            ):
                return self.fallback("invalid_decision")
            index = next(
                (
                    i
                    for i, c in enumerate(candidates)
                    if c.kind == decision.kind and c.params == decision.params
                ),
                None,
            )
            if index is None:
                return self.fallback("unknown_candidate")
        except Exception:
            return self.fallback("policy_error")
        candidate, alias = candidates[index], aliases[index]
        value = candidate.lp_value
        lo, hi = math.floor(value), math.ceil(value)
        # No callbacks or fallible policy execution after the first child mutation.
        estimate = m.getLocalEstimate()
        down, up = m.createChild(0.0, estimate), m.createChild(0.0, estimate)
        m.chgVarUbNode(down, alias, float(lo))
        m.chgVarLbNode(up, alias, float(hi))
        self.records.append(
            dict(
                kind=candidate.kind,
                params=candidate.params,
                lp_value=value,
                down_ub=lo,
                up_lb=hi,
                depth=m.getDepth(),
            )
        )
        return {"result": SCIP_RESULT.BRANCHED}


def solve_structured(instance, policy=None, windows=(2, 4), max_depth=8, limit=60):
    m = build(instance)
    rule = StructuredBranchrule(m, instance, policy, windows, max_depth)
    m.includeBranchrule(
        rule, "uc_structured", "UC count disjunction compiler", 1000000, -1, 1.0
    )
    settings = {
        "limits/time": float(limit),
        "randomization/randomseedshift": 0,
        "randomization/permutationseed": 0,
        "parallel/maxnthreads": 1,
        "presolving/donotmultaggr": True,
        "presolving/donotaggr": True,
        "presolving/maxrounds": 0,
        "presolving/maxrestarts": 0,
    }
    m.setParams(settings)
    begin = time.perf_counter()
    m.optimize()
    result = dict(
        status=str(m.getStatus()),
        nodes=m.getNNodes(),
        time=time.perf_counter() - begin,
        solver_time=m.getSolvingTime(),
        settings=settings,
        branches=rule.records,
        fallbacks=rule.fallbacks,
        validity=False,
    )
    if m.getNSols():
        values = {
            v.name: float(m.getVal(v))
            for v in m.getVars(transformed=False)
            if not v.name.startswith("count_")
        }
        objective = float(m.getObjVal())
        assert abs(validate(instance, values) - objective) < 1e-4
        result.update(
            objective=objective,
            primal=m.getPrimalbound(),
            dual=m.getDualbound(),
            gap=m.getGap(),
            values=values,
            validity=result["status"] == "optimal",
        )
    return result

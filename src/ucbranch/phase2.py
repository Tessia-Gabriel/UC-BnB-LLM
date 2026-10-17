"""No-LLM feasibility experiments with a shared compiler/control formulation."""
import math
import time
import numpy as np
import ecole
from pyscipopt import Branchrule, Eventhdlr, SCIP_EVENTTYPE, SCIP_RESULT
from ucbranch.uc import build, generate, validate
from ucbranch.structured import StructuredBranchrule, BranchDecision
from ucbranch.integration import normalize, load_program, ROOT

METHODS = ("native_default", "matched_default", "pseudocost", "llm4branch",
           "start", "temporal", "hybrid")
SCENARIOS = ("normal", "tight_ramp", "high_startup", "peak", "combined")


def instances():
    for n in (10, 20, 50):
        for scenario in SCENARIOS:
            for seed in (100, 101):
                inst = generate(seed, n, 8)
                for i, unit in enumerate(inst.units):
                    unit["ramp"] = (8 if scenario in ("tight_ramp", "combined") else 20) + i % 3
                    if scenario in ("high_startup", "combined"):
                        unit["startup"] *= 3
                if scenario in ("peak", "combined"):
                    inst.demand[4] = round(sum(u["pmax"] for u in inst.units) * .82, 2)
                yield f"n{n}_{scenario}_{seed}", scenario, inst


def bounded_gap(primal, dual):
    if not math.isfinite(primal) or not math.isfinite(dual) or abs(primal) >= 1e19 or abs(dual) >= 1e19:
        return 1.0
    if primal * dual < 0:
        return 1.0
    return min(1.0, abs(primal-dual) / max(abs(primal), abs(dual), 1e-10))


class Trace(Eventhdlr):
    mask = (SCIP_EVENTTYPE.BESTSOLFOUND | SCIP_EVENTTYPE.LPSOLVED |
            SCIP_EVENTTYPE.NODEFOCUSED | SCIP_EVENTTYPE.NODEFEASIBLE |
            SCIP_EVENTTYPE.NODEINFEASIBLE | SCIP_EVENTTYPE.NODEBRANCHED)

    def __init__(self):
        self.points = [(0.0, 1.0)]
        self.first = None

    def eventinit(self):
        self.model.catchEvent(self.mask, self)

    def eventexit(self):
        self.model.dropEvent(self.mask, self)

    def eventexec(self, event):
        m = self.model
        now = m.getSolvingTime()
        if self.first is None and m.getNSols() > 0:
            self.first = now
        gap = bounded_gap(m.getPrimalbound(), m.getDualbound())
        if gap != self.points[-1][1]:
            self.points.append((now, gap))

    def finish(self, model, budget):
        end = model.getSolvingTime()
        points = self.points + [(end, bounded_gap(model.getPrimalbound(), model.getDualbound()))]
        integral = sum(max(0, b[0]-a[0])*a[1] for a,b in zip(points, points[1:]))
        # Common budget horizon penalizes unsolved runs rather than rewarding timeout.
        integral += max(0, budget-end)*points[-1][1]
        return dict(primal_dual_integral_sampled=integral, time_to_first_incumbent=self.first,
                    bound_gap_trace=points)


class VariableRule(Branchrule):
    def branchexecps(self, allowaddcons):
        return {"result": SCIP_RESULT.DIDNOTRUN}

    def branchexecext(self, allowaddcons):
        return {"result": SCIP_RESULT.DIDNOTRUN}

    def __init__(self, owner, mode):
        self.owner, self.mode, self.calls = owner, mode, 0
        self.pc = ecole.observation.Pseudocosts()
        self.node = ecole.observation.NodeBipartiteFlash()
        self.khalil = ecole.observation.Khalil2016Flash()
        self.node.set_active_features([9])
        self.khalil.set_active_features([24])
        for obs in (self.pc, self.node, self.khalil):
            obs.before_reset(owner)
        self.score = load_program(str(ROOT / "configs/phase0/initial_program.py"))[0]

    def branchexeclp(self, allowaddcons):
        m = self.model
        variables = m.getLPBranchCands()[0]
        if not variables:
            return {"result": SCIP_RESULT.DIDNOTRUN}
        indices = {v.name: i for i,v in enumerate(m.getVars(transformed=True))}
        ids = np.array([indices[v.name] for v in variables])
        assert all(v.name.removeprefix("t_").startswith("u_") for v in variables)
        if self.mode == "llm4branch":
            x = np.concatenate([self.node.extract(self.owner, False).variable_features[ids],
                                self.khalil.extract(self.owner, False).features[ids]], axis=1)
            scores = self.score(normalize(x, [9,43]), [.5,.5])
        else:
            scores = self.pc.extract(self.owner, False)[ids]
        assert np.isfinite(scores).all()
        m.branchVar(variables[int(np.argmax(scores))])
        self.calls += 1
        return {"result": SCIP_RESULT.BRANCHED}


class HybridRule(StructuredBranchrule):
    def branchexecps(self, allowaddcons):
        return {"result": SCIP_RESULT.DIDNOTRUN}

    def branchexecext(self, allowaddcons):
        return {"result": SCIP_RESULT.DIDNOTRUN}

    def __init__(self, model, inst, variable, mode):
        self.variable = variable
        def policy(candidates):
            order = {"start": ("START_COUNT",), "temporal": ("UNIT_ON_COUNT",),
                     "hybrid": ("START_COUNT", "UNIT_ON_COUNT", "GROUP_ON_COUNT")}[mode]
            for kind in order:
                pool = [c for c in candidates if c.kind == kind and c.features["fractionality"] >= .25]
                if pool:
                    c = max(pool, key=lambda c:c.features["fractionality"])
                    return BranchDecision(c.kind, c.params, c.features["fractionality"])
            return None
        super().__init__(model, inst, policy, windows=(2,4), max_depth=2)

    def fallback(self, reason):
        self.fallbacks[reason] = self.fallbacks.get(reason, 0) + 1
        return self.variable.branchexeclp(True)


def run(inst, method, limit=3.0):
    if method not in METHODS:
        raise ValueError(method)
    begin = time.perf_counter()
    m = build(inst)
    owner = ecole.scip.Model.from_pyscipopt(m)
    variable = VariableRule(owner, method)
    # Register to bind the model even when only used as hybrid fallback.
    if method not in ("native_default", "matched_default"):
        m.includeBranchrule(variable, "phase2_variable", "fixed variable baseline", -1000000, -1, 1)
    structured = None
    if method != "native_default":
        if method in ("start", "temporal", "hybrid"):
            structured = HybridRule(m, inst, variable, method)
            m.includeBranchrule(structured, "phase2_structured", "handcrafted", 1000000, -1, 1)
        else:
            StructuredBranchrule(m, inst)  # same aliases/constraints, no active structured callback
        if method in ("pseudocost", "llm4branch"):
            m.setIntParam("branching/phase2_variable/priority", 1000000)
    settings = {"limits/time": float(limit), "parallel/maxnthreads": 1,
                "randomization/randomseedshift": 0, "randomization/permutationseed": 0}
    m.setParams(settings)
    trace = Trace()
    m.includeEventhdlr(trace, "phase2_trace", "sampled primal dual history")
    m.optimize()
    result = dict(method=method, status=str(m.getStatus()), nodes=m.getNNodes(),
                  solver_time=m.getSolvingTime(), wall_time=time.perf_counter()-begin,
                  final_gap=float(m.getGap()), primal=float(m.getPrimalbound()), dual=float(m.getDualbound()),
                  settings={k:m.getParam(k) for k in (*settings, "presolving/maxrounds", "presolving/maxrestarts",
                            "presolving/donotaggr", "presolving/donotmultaggr")},
                  variable_decisions=variable.calls, branches=structured.records if structured else [])
    result.update(trace.finish(m, limit))
    result["schedule_valid"] = False
    if m.getNSols():
        values = {v.name:float(m.getVal(v)) for v in m.getVars(transformed=False) if not v.name.startswith("count_")}
        objective = float(m.getObjVal())
        assert abs(validate(inst, values)-objective) < 1e-4
        result.update(schedule_valid=True, objective=objective, values=values)
    # Drop transformed-stage events while the owning PySCIPOpt view is alive.
    m.freeTransform()
    # Break owner -> SCIP plugin -> VariableRule -> owner before the next run.
    variable.owner = None
    return result

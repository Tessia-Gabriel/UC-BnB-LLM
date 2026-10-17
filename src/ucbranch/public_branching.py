"""Fair branching-policy runner for the frozen public UC instances."""

import time
from pathlib import Path

import ecole
import numpy as np
from pyscipopt import Branchrule, Model, SCIP_PARAMSETTING, SCIP_RESULT

from ucbranch.integration import load_program, normalize
from ucbranch.public_uc import build


PROGRAM_ROOT = (
    Path(__file__).resolve().parents[2]
    / "third_party/llm4branch/examples/brancher/program"
)
PUBLISHED_PROGRAMS = ("setcover", "cauctions", "facilities", "indset")


def _root_lite_params(root_limit):
    """SCIP settings used to reach branching without changing the UC model."""
    return {
        "limits/time": float(root_limit),
        "randomization/randomseedshift": 0,
        "randomization/permutationseed": 0,
        "parallel/maxnthreads": 1,
        "timing/clocktype": 1,
        "presolving/maxrestarts": 0,
        "separating/maxrounds": 0,
        "separating/maxroundsroot": 1,
        "separating/maxcutsroot": 100,
    }


class _FirstBranchBudget(Branchrule):
    """Start a new time budget when SCIP first asks a branch rule to run."""

    def __init__(self, branch_seconds):
        self.branch_seconds = float(branch_seconds)
        self.first_branch_solver_seconds = None
        self.candidate_types = {}

    def branchexeclp(self, allowaddcons):
        if self.first_branch_solver_seconds is None:
            self.first_branch_solver_seconds = float(self.model.getSolvingTime())
            variables, _, _, _, _, _ = self.model.getLPBranchCands()
            for variable in variables:
                prefix = _candidate_type(variable.name)
                self.candidate_types[prefix] = self.candidate_types.get(prefix, 0) + 1
            self.model.setRealParam(
                "limits/time",
                self.first_branch_solver_seconds + self.branch_seconds,
            )
        return {"result": SCIP_RESULT.DIDNOTRUN}


def _result(model, method, protocol, wall_seconds, decisions=0, candidate_types=None):
    result = {
        "method": method,
        "protocol": protocol,
        "status": str(model.getStatus()),
        "nodes": int(model.getNNodes()),
        "lp_iterations": int(model.getNLPIterations()),
        "solver_seconds": float(model.getSolvingTime()),
        "wall_seconds": float(wall_seconds),
        "decisions": decisions,
        "candidate_types": candidate_types or {},
        "solutions": int(model.getNSols()),
    }
    if model.getNSols():
        result.update(
            objective=float(model.getObjVal()),
            primal=float(model.getPrimalbound()),
            dual=float(model.getDualbound()),
            gap=float(model.getGap()),
        )
    return result


def _candidate_type(name):
    name = name.removeprefix("t_")
    for prefix in ("is_on", "switch_on", "switch_off", "startup", "u", "y", "z"):
        if name.startswith(prefix + "[") or name.startswith(prefix + "_"):
            return prefix
    return name.split("[", 1)[0].split("_", 1)[0]


def _run_model(model, method, limit, model_source):
    if limit <= 0:
        raise ValueError("limit must be positive")
    if method not in {"native_scip", "rpb", *PUBLISHED_PROGRAMS}:
        raise ValueError(f"unknown method: {method}")
    seed_settings = {
        "limits/time": float(limit),
        "randomization/randomseedshift": 0,
        "randomization/permutationseed": 0,
        "parallel/maxnthreads": 1,
    }
    begin = time.perf_counter()
    if method == "native_scip":
        model.setParams(seed_settings)
        model.optimize()
        result = _result(
            model, method, "native SCIP with its full default solving machinery",
            time.perf_counter() - begin,
        )
        result["model_source"] = model_source
        return result

    controlled = {
        **seed_settings,
        "separating/maxrounds": 0,
        "presolving/maxrestarts": 0,
        "branching/vanillafullstrong/idempotent": True,
        "timing/clocktype": 1,
    }
    ecole_model = ecole.scip.Model.from_pyscipopt(model)
    if method == "rpb":
        controlled["branching/relpscost/priority"] = 9_999_999
        env = ecole.environment.Configuring(scip_params=controlled)
        env.seed(0)
        _, _, _, _, _ = env.reset(ecole_model)
        _, _, _, _, _ = env.step({})
        solved = env.model.as_pyscipopt()
        result = _result(
            solved, method,
            "LLM4Branch controlled settings; SCIP relative pseudocost branching",
            time.perf_counter() - begin,
        )
        result["model_source"] = model_source
        return result

    score_function, features, params, _ = load_program(
        PROGRAM_ROOT / method / "program.py"
    )
    node = ecole.observation.NodeBipartiteFlash()
    khalil = ecole.observation.Khalil2016Flash()
    node.set_active_features([feature for feature in features if feature < 19])
    khalil.set_active_features([feature - 19 for feature in features if feature >= 19])
    env = ecole.environment.Branching(
        observation_function={"node": node, "khalil": khalil},
        scip_params=controlled,
    )
    env.seed(0)
    observation, actions, _, done, _ = env.reset(ecole_model)
    decisions = 0
    candidate_types = {}
    while not done:
        solved = env.model.as_pyscipopt()
        names = {j: var.name.removeprefix("t_") for j, var in enumerate(
            solved.getVars(transformed=True)
        )}
        for action in actions:
            prefix = _candidate_type(names[int(action)])
            candidate_types[prefix] = candidate_types.get(prefix, 0) + 1
        variable_features = np.concatenate(
            (
                observation["node"].variable_features[actions, :],
                observation["khalil"].features[actions, :],
            ),
            axis=1,
        )
        variable_features[:, features] = np.nan_to_num(
            variable_features[:, features], nan=0.0, posinf=0.0, neginf=0.0
        )
        scores = np.asarray(
            score_function(normalize(variable_features, features), params)
        )
        if scores.shape != (len(actions),) or not np.isfinite(scores).all():
            raise ValueError(f"{method} returned invalid branching scores")
        observation, actions, _, done, _ = env.step(
            actions[int(np.argmax(scores))]
        )
        decisions += 1
    solved = env.model.as_pyscipopt()
    result = _result(
        solved, method,
        "LLM4Branch controlled settings; unchanged published score program",
        time.perf_counter() - begin, decisions, candidate_types,
    )
    result["model_source"] = model_source
    return result


def run(instance, method, limit=60.0):
    """Run on the transparent project-owned formulation (diagnostics only)."""
    model = build(instance, formulation="ucjl03")
    return _run_model(model, method, limit, "project ucjl03 formulation")


def run_mps(path, method, limit=60.0):
    """Run on an MPS exported by the official UnitCommitment.jl model."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    model = Model(path.stem)
    model.hideOutput()
    model.readProblem(str(path))
    return _run_model(
        model, method, limit,
        f"official UnitCommitment.jl v0.3 MPS: {path.name}",
    )


def run_mps_branch_budget(path, method, root_limit=300.0, branch_limit=60.0):
    """Run with a separate time budget that starts at the first branch.

    The official MPS and root-light settings are identical for every method.
    ``root_limit`` is only a safety cap for reaching the first branch.  Once
    branching starts, SCIP's absolute time limit is moved to
    ``first_branch_time + branch_limit``.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if root_limit <= 0 or branch_limit <= 0:
        raise ValueError("root_limit and branch_limit must be positive")
    if method not in {"scip_default", "rpb", *PUBLISHED_PROGRAMS}:
        raise ValueError(f"unknown method: {method}")

    model = Model(path.stem)
    model.hideOutput()
    model.readProblem(str(path))
    model.setHeuristics(SCIP_PARAMSETTING.FAST)
    params = _root_lite_params(root_limit)
    source = f"official UnitCommitment.jl v0.3 MPS: {path.name}"
    begin = time.perf_counter()

    if method in {"scip_default", "rpb"}:
        if method == "rpb":
            params["branching/relpscost/priority"] = 9_999_999
        model.setParams(params)
        budget = _FirstBranchBudget(branch_limit)
        model.includeBranchrule(
            budget,
            "first_branch_budget",
            "start a fixed search budget at the first branching decision",
            priority=10_000_000,
            maxdepth=-1,
            maxbounddist=1.0,
        )
        model.optimize()
        root_seconds = budget.first_branch_solver_seconds
        result = _result(
            model,
            method,
            "official MPS; root-light SCIP; budget starts at first branch",
            time.perf_counter() - begin,
            candidate_types=budget.candidate_types,
        )
        result.update(
            model_source=source,
            first_branch_reached=root_seconds is not None,
            root_solver_seconds=root_seconds,
            branch_budget_seconds=float(branch_limit),
            branch_search_seconds=(
                max(0.0, float(model.getSolvingTime()) - root_seconds)
                if root_seconds is not None else 0.0
            ),
        )
        return result

    score_function, features, program_params, _ = load_program(
        PROGRAM_ROOT / method / "program.py"
    )
    node = ecole.observation.NodeBipartiteFlash()
    khalil = ecole.observation.Khalil2016Flash()
    node.set_active_features([feature for feature in features if feature < 19])
    khalil.set_active_features([feature - 19 for feature in features if feature >= 19])
    environment = ecole.environment.Branching(
        observation_function={"node": node, "khalil": khalil},
        scip_params=params,
    )
    environment.seed(0)
    observation, actions, _, done, _ = environment.reset(
        ecole.scip.Model.from_pyscipopt(model)
    )
    solved = environment.model.as_pyscipopt()
    root_seconds = None if done else float(solved.getSolvingTime())
    decisions = 0
    candidate_types = {}
    if not done:
        solved.setRealParam("limits/time", root_seconds + float(branch_limit))

    while not done:
        solved = environment.model.as_pyscipopt()
        names = {
            index: variable.name.removeprefix("t_")
            for index, variable in enumerate(solved.getVars(transformed=True))
        }
        for action in actions:
            prefix = _candidate_type(names[int(action)])
            candidate_types[prefix] = candidate_types.get(prefix, 0) + 1
        variable_features = np.concatenate(
            (
                observation["node"].variable_features[actions, :],
                observation["khalil"].features[actions, :],
            ),
            axis=1,
        )
        variable_features[:, features] = np.nan_to_num(
            variable_features[:, features], nan=0.0, posinf=0.0, neginf=0.0
        )
        scores = np.asarray(
            score_function(normalize(variable_features, features), program_params)
        )
        if scores.shape != (len(actions),) or not np.isfinite(scores).all():
            raise ValueError(f"{method} returned invalid branching scores")
        observation, actions, _, done, _ = environment.step(
            actions[int(np.argmax(scores))]
        )
        decisions += 1

    solved = environment.model.as_pyscipopt()
    result = _result(
        solved,
        method,
        "official MPS; root-light SCIP; budget starts at first branch; "
        "unchanged published score program",
        time.perf_counter() - begin,
        decisions,
        candidate_types,
    )
    result.update(
        model_source=source,
        first_branch_reached=root_seconds is not None,
        root_solver_seconds=root_seconds,
        branch_budget_seconds=float(branch_limit),
        branch_search_seconds=(
            max(0.0, float(solved.getSolvingTime()) - root_seconds)
            if root_seconds is not None else 0.0
        ),
    )
    return result

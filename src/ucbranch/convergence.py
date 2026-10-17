"""Convergence-trajectory benchmark for public UC branching policies."""

import math
from pathlib import Path
import time

import ecole
import numpy as np
from pyscipopt import Branchrule, Model, SCIP_PARAMSETTING, SCIP_RESULT

from ucbranch.integration import load_program, normalize
from ucbranch.public_branching import (
    PROGRAM_ROOT,
    PUBLISHED_PROGRAMS,
    _candidate_type,
    _result,
    _root_lite_params,
)


METHODS = ("scip_default", "rpb", *PUBLISHED_PROGRAMS)
GAP_THRESHOLDS = (1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7, 0.0)


def _finite(value):
    value = float(value)
    return value if math.isfinite(value) else None


def _snapshot(model, wall_seconds, reason):
    has_solution = model.getNSols() > 0
    return {
        "wall_seconds": float(wall_seconds),
        "solver_seconds": float(model.getSolvingTime()),
        "reason": reason,
        "nodes": int(model.getNNodes()),
        "lp_iterations": int(model.getNLPIterations()),
        "solutions": int(model.getNSols()),
        "primal": _finite(model.getPrimalbound()) if has_solution else None,
        "dual": _finite(model.getDualbound()),
        "gap": _finite(model.getGap()) if has_solution else None,
    }


def trajectory_metrics(trajectory, horizon):
    """Compute conservative stepwise gap integrals and threshold times."""
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    if not trajectory:
        return {
            "gap_integral": None,
            "capped_gap_integral": None,
            "mean_capped_gap": None,
            "time_to_gap": {f"{threshold:.0e}": None for threshold in GAP_THRESHOLDS},
        }
    points = sorted(trajectory, key=lambda row: row["wall_seconds"])
    initial_gap = points[0]["gap"]
    if initial_gap is None:
        initial_gap = 1.0
    gap_integral = 0.0
    capped_integral = 0.0
    previous_time = 0.0
    previous_gap = points[0]["gap"]
    if previous_gap is None:
        previous_gap = 1.0
    for point in points[1:]:
        current_time = min(float(horizon), max(previous_time, point["wall_seconds"]))
        duration = current_time - previous_time
        gap_integral += max(0.0, previous_gap) * duration
        capped_integral += min(1.0, max(0.0, previous_gap)) * duration
        previous_time = current_time
        if point["gap"] is not None:
            previous_gap = point["gap"]
        if previous_time >= horizon:
            break
    if previous_time < horizon:
        duration = horizon - previous_time
        gap_integral += max(0.0, previous_gap) * duration
        capped_integral += min(1.0, max(0.0, previous_gap)) * duration

    within_horizon = [
        point for point in points if float(point["wall_seconds"]) <= horizon
    ]
    gap_at_horizon = next(
        (point["gap"] for point in reversed(within_horizon) if point["gap"] is not None),
        initial_gap,
    )
    time_to_gap = {}
    for threshold in GAP_THRESHOLDS:
        reached = next(
            (
                float(point["wall_seconds"])
                for point in within_horizon
                if point["gap"] is not None and point["gap"] <= threshold
            ),
            None,
        )
        time_to_gap[f"{threshold:.0e}"] = reached
    time_to_gap_ratio = {}
    for ratio in (0.9, 0.5, 0.1, 0.01):
        reached = next(
            (
                float(point["wall_seconds"])
                for point in within_horizon
                if point["gap"] is not None and point["gap"] <= initial_gap * ratio
            ),
            None,
        )
        time_to_gap_ratio[f"{ratio:.2f}"] = reached
    return {
        "initial_gap": float(initial_gap),
        "gap_at_horizon": float(gap_at_horizon),
        "gap_integral": float(gap_integral),
        "capped_gap_integral": float(capped_integral),
        "mean_capped_gap": float(capped_integral / horizon),
        "mean_gap_ratio": (
            float(gap_integral / (initial_gap * horizon))
            if initial_gap > 0 else 0.0
        ),
        "time_to_gap": time_to_gap,
        "time_to_gap_ratio": time_to_gap_ratio,
    }


class _TrajectoryBudget(Branchrule):
    """Observe internal branching and enforce a post-root wall-clock budget."""

    def __init__(self, branch_seconds):
        self.branch_seconds = float(branch_seconds)
        self.first_branch_solver_seconds = None
        self.first_branch_wall_clock = None
        self.trajectory = []
        self.first_candidate_types = {}

    def branchexeclp(self, allowaddcons):
        now = time.perf_counter()
        if self.first_branch_solver_seconds is None:
            self.first_branch_solver_seconds = float(self.model.getSolvingTime())
            self.first_branch_wall_clock = now
            variables, _, _, _, _, _ = self.model.getLPBranchCands()
            for variable in variables:
                prefix = _candidate_type(variable.name)
                self.first_candidate_types[prefix] = (
                    self.first_candidate_types.get(prefix, 0) + 1
                )
            elapsed = 0.0
            reason = "first_branch"
        else:
            elapsed = now - self.first_branch_wall_clock
            reason = "branch"
        self.trajectory.append(_snapshot(self.model, elapsed, reason))
        remaining = max(0.0, self.branch_seconds - elapsed)
        self.model.setRealParam(
            "limits/time", float(self.model.getSolvingTime()) + remaining
        )
        return {"result": SCIP_RESULT.DIDNOTRUN}


def _finish_result(result, trajectory, branch_seconds):
    result["trajectory"] = trajectory
    result["trajectory_metrics"] = trajectory_metrics(trajectory, branch_seconds)
    return result


def run_mps_convergence(path, method, root_limit=300.0, branch_limit=60.0):
    """Run one method and record its post-root wall-clock convergence curve."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if method not in METHODS:
        raise ValueError(f"unknown method: {method}")
    if root_limit <= 0 or branch_limit <= 0:
        raise ValueError("root_limit and branch_limit must be positive")

    model = Model(path.stem)
    model.hideOutput()
    model.readProblem(str(path))
    model.setHeuristics(SCIP_PARAMSETTING.FAST)
    params = _root_lite_params(root_limit)
    source = f"official UnitCommitment.jl v0.3 MPS: {path.name}"
    solve_wall_start = time.perf_counter()

    if method in {"scip_default", "rpb"}:
        if method == "rpb":
            params["branching/relpscost/priority"] = 9_999_999
        model.setParams(params)
        observer = _TrajectoryBudget(branch_limit)
        model.includeBranchrule(
            observer,
            "trajectory_budget",
            "record convergence and start a wall-clock budget at first branch",
            priority=10_000_000,
            maxdepth=-1,
            maxbounddist=1.0,
        )
        model.optimize()
        total_wall = time.perf_counter() - solve_wall_start
        root_wall = (
            observer.first_branch_wall_clock - solve_wall_start
            if observer.first_branch_wall_clock is not None else total_wall
        )
        branch_wall = (
            time.perf_counter() - observer.first_branch_wall_clock
            if observer.first_branch_wall_clock is not None else 0.0
        )
        if observer.first_branch_wall_clock is not None:
            observer.trajectory.append(_snapshot(model, branch_wall, "finished"))
        result = _result(
            model,
            method,
            "official MPS; root-light SCIP; post-root wall-clock trajectory",
            total_wall,
            candidate_types=observer.first_candidate_types,
        )
        result.update(
            model_source=source,
            first_branch_reached=observer.first_branch_wall_clock is not None,
            root_solver_seconds=observer.first_branch_solver_seconds,
            root_wall_seconds=float(root_wall),
            branch_budget_seconds=float(branch_limit),
            branch_wall_seconds=float(branch_wall),
            trajectory_sampling="every internal branching callback plus final state",
        )
        return _finish_result(result, observer.trajectory, branch_limit)

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
    branch_wall_start = time.perf_counter()
    solved = environment.model.as_pyscipopt()
    root_wall = branch_wall_start - solve_wall_start
    root_solver = None if done else float(solved.getSolvingTime())
    trajectory = []
    decisions = 0
    candidate_types = {}
    if not done:
        trajectory.append(_snapshot(solved, 0.0, "first_branch"))

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
        elapsed = time.perf_counter() - branch_wall_start
        remaining = max(0.0, float(branch_limit) - elapsed)
        solved.setRealParam(
            "limits/time", float(solved.getSolvingTime()) + max(1e-3, remaining)
        )
        observation, actions, _, done, _ = environment.step(
            actions[int(np.argmax(scores))]
        )
        decisions += 1
        solved = environment.model.as_pyscipopt()
        trajectory.append(_snapshot(
            solved,
            time.perf_counter() - branch_wall_start,
            "finished" if done else "branch",
        ))

    solved = environment.model.as_pyscipopt()
    branch_wall = time.perf_counter() - branch_wall_start
    total_wall = time.perf_counter() - solve_wall_start
    if not trajectory or trajectory[-1]["reason"] != "finished":
        trajectory.append(_snapshot(solved, branch_wall, "finished"))
    result = _result(
        solved,
        method,
        "official MPS; root-light SCIP; post-root wall-clock trajectory; "
        "unchanged published score program",
        total_wall,
        decisions,
        candidate_types,
    )
    result.update(
        model_source=source,
        first_branch_reached=root_solver is not None,
        root_solver_seconds=root_solver,
        root_wall_seconds=float(root_wall),
        branch_budget_seconds=float(branch_limit),
        branch_wall_seconds=float(branch_wall),
        trajectory_sampling="every external branching decision plus final state",
    )
    return _finish_result(result, trajectory, branch_limit)

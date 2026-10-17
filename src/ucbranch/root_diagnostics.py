"""Measure how long SCIP needs to reach its first branching decision.

This module intentionally stops at the first branching decision.  It is a
diagnostic for selecting instances and solver settings for branching-policy
research, not a replacement for the end-to-end benchmark.
"""

from collections import Counter
from pathlib import Path
import time

import ecole
from pyscipopt import Model, SCIP_PARAMSETTING

from ucbranch.public_branching import _candidate_type
from ucbranch.public_uc import build, read


PROFILES = (
    "official_default",
    "official_root_lite",
    "compact_root_lite",
)


def _base_params(limit):
    if limit <= 0:
        raise ValueError("limit must be positive")
    return {
        "limits/time": float(limit),
        "randomization/randomseedshift": 0,
        "randomization/permutationseed": 0,
        "parallel/maxnthreads": 1,
        "timing/clocktype": 1,
    }


def _root_lite_params(limit):
    """Keep presolve, but cap optional root work before branching.

    One root separation round is retained rather than disabling cuts entirely.
    Non-root separation is irrelevant here because the run stops at the first
    branch, but it is set to zero to document the intended follow-up protocol.
    """
    return {
        **_base_params(limit),
        "presolving/maxrestarts": 0,
        "separating/maxrounds": 0,
        "separating/maxroundsroot": 1,
        "separating/maxcutsroot": 100,
    }


def _load_model(instance_path, mps_path, profile):
    started = time.perf_counter()
    if profile.startswith("official_"):
        mps_path = Path(mps_path)
        if not mps_path.is_file():
            raise FileNotFoundError(mps_path)
        model = Model(mps_path.stem)
        model.hideOutput()
        model.readProblem(str(mps_path))
        source = f"official UnitCommitment.jl v0.3 MPS: {mps_path.name}"
    elif profile == "compact_root_lite":
        instance_path = Path(instance_path)
        instance = read(instance_path)
        model = build(instance, formulation="ucjl03")
        source = f"project compact ucjl03 formulation: {instance_path.name}"
    else:
        raise ValueError(f"unknown profile: {profile}")
    return model, source, time.perf_counter() - started


def diagnose_first_branch(instance_path, mps_path, profile, limit=300.0):
    """Stop at SCIP's first branching decision and return stage metrics."""
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {PROFILES}")
    total_started = time.perf_counter()
    model, source, load_seconds = _load_model(instance_path, mps_path, profile)
    original_variables = int(model.getNVars())
    original_constraints = int(model.getNConss())

    params = (_base_params(limit) if profile == "official_default"
              else _root_lite_params(limit))
    if profile.endswith("root_lite"):
        # FAST reduces expensive primal-heuristic work while retaining cheap
        # heuristics.  Presolve itself remains enabled because turning it off
        # can make the already-large root LP substantially worse.
        model.setHeuristics(SCIP_PARAMSETTING.FAST)

    ecole_model = ecole.scip.Model.from_pyscipopt(model)
    environment = ecole.environment.Branching(scip_params=params)
    environment.seed(0)
    solve_started = time.perf_counter()
    _, actions, _, done, _ = environment.reset(ecole_model)
    solve_to_event_seconds = time.perf_counter() - solve_started
    solved = environment.model.as_pyscipopt()

    first_branch_reached = not done and actions is not None and len(actions) > 0
    candidate_types = Counter()
    if first_branch_reached:
        names = {
            index: variable.name.removeprefix("t_")
            for index, variable in enumerate(solved.getVars(transformed=True))
        }
        for action in actions:
            candidate_types[_candidate_type(names[int(action)])] += 1

    result = {
        "profile": profile,
        "model_source": source,
        "limit_seconds": float(limit),
        "first_branch_reached": bool(first_branch_reached),
        "solve_finished_before_branch": bool(done),
        "status_at_event": str(solved.getStatus()),
        "load_or_build_seconds": float(load_seconds),
        "solve_to_event_seconds": float(solve_to_event_seconds),
        "total_wall_seconds": float(time.perf_counter() - total_started),
        "solver_seconds": float(solved.getSolvingTime()),
        "original_variables": original_variables,
        "original_constraints": original_constraints,
        "variables_at_event": int(solved.getNVars()),
        "constraints_at_event": int(solved.getNConss()),
        "nodes_at_event": int(solved.getNNodes()),
        "lp_iterations_at_event": int(solved.getNLPIterations()),
        "lp_solves_at_event": int(solved.getNLPs()),
        "solutions_at_event": int(solved.getNSols()),
        "branch_candidates": int(len(actions)) if first_branch_reached else 0,
        "candidate_types": dict(sorted(candidate_types.items())),
        "settings": {
            "single_thread": True,
            "deterministic_seed": 0,
            "root_separation_rounds": (
                "SCIP default" if profile == "official_default" else 1
            ),
            "root_cut_limit": (
                "SCIP default" if profile == "official_default" else 100
            ),
            "presolve_restarts": (
                "SCIP default" if profile == "official_default" else 0
            ),
            "heuristics": (
                "SCIP default" if profile == "official_default" else "FAST"
            ),
        },
    }
    if solved.getNSols():
        result.update(
            primal=float(solved.getPrimalbound()),
            dual=float(solved.getDualbound()),
            gap=float(solved.getGap()),
        )
    return result

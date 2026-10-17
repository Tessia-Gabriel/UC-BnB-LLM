"""UC evaluator exposed through the unchanged OpenEvolve cascade contract."""

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import numpy as np
import ecole
import pyscipopt
from ucbranch.uc import generate
from ucbranch.solver import solve
from ucbranch.integration import load_program, parameter_optimizer


def check_program(path):
    tree = ast.parse(Path(path).read_text())
    # Phase 0 retains upstream Python score programs; this is validation, not a sandbox.
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in (
                    "USED_FEATURES",
                    "PARAMS",
                    "BOUNDS",
                ):
                    constants[target.id] = ast.literal_eval(node.value)
    f = constants["USED_FEATURES"]
    p = constants["PARAMS"]
    b = constants["BOUNDS"]
    if (
        not f
        or len(set(f)) != len(f)
        or any(type(i) is not int or not 0 <= i < 91 for i in f)
    ):
        raise ValueError("invalid feature indices")
    if (
        not p
        or len(p) != len(b)
        or any(not lo <= x <= hi or lo >= hi for x, (lo, hi) in zip(p, b))
    ):
        raise ValueError("invalid parameter bounds")
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "variable_features"
        ):
            if isinstance(node.slice, ast.Tuple) and len(node.slice.elts) == 2:
                col = node.slice.elts[1]
                if isinstance(col, ast.Constant) and col.value not in f:
                    raise ValueError("score reads undeclared feature")
    loaded = load_program(str(path))
    for size in (1, 7):
        for x in (
            np.zeros((size, 91)),
            np.random.default_rng(42).uniform(size=(size, 91)),
        ):
            scores = np.asarray(loaded[0](x, loaded[2]))
            if scores.shape != (size,) or not np.isfinite(scores).all():
                raise ValueError("score_function must return finite candidate scores")
    return loaded


def cached_solve(
    seed, method, score=None, features=None, params=None, code="", n=12, horizon=24
):
    instance = generate(seed, n, horizon)
    identity = dict(
        instance=instance.to_dict(),
        method=method,
        code=code,
        features=features,
        params=params,
        version="phase0-v1",
        ecole=ecole.__version__,
        pyscipopt=pyscipopt.__version__,
    )
    identity["scip"] = subprocess.check_output(
        [str(Path(sys.executable).with_name("scip")), "--version"], text=True
    ).splitlines()[0]
    # Include implementation bytes, so implementation changes invalidate cached runs.
    sources = b"".join(
        Path(__file__).with_name(name).read_bytes()
        for name in ("solver.py", "uc.py", "integration.py")
    )
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode() + sources
    ).hexdigest()
    root = Path(os.environ.get("UCBRANCH_OUTPUT", "outputs/phase0")) / "evaluations"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{digest}.json"
    if path.exists():
        return json.loads(path.read_text())["result"]
    result = solve(instance, method, score, features, params)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(identity=identity, result=result), indent=2))
    temporary.replace(path)
    return result


def execute_uc(args):
    """Task tuple adapter for the unchanged LLM4Branch BO objective."""
    (
        task,
        dataset,
        seed,
        cores,
        locks,
        score,
        features,
        params,
        settings,
        _,
        __,
        directory,
    ) = args
    # Full source is passed as dataset_dir solely as the upstream transport slot.
    code = Path(directory).read_text()
    r = cached_solve(seed, "llm4branch", score, features, params, code)
    if not r["validity"]:
        raise RuntimeError("BO solver did not prove optimality")
    return dict(r, task=task)


def evaluate_stage1(program_path, config):
    try:
        check_program(program_path)
        return {"stage1_score": 1.0}
    except Exception:
        return {"stage1_score": 0.0, "combined_score": 0.0}


def evaluate(program_path, config):
    try:
        score, features, params, bounds = check_program(program_path)
        code = Path(program_path).read_text()
        if config.parameter_opt:
            from openevolve.config import EvaConfig

            bo = EvaConfig(
                **dict(config.as_dict(), dataset="uc", dataset_dir=str(program_path))
            )
            params = parameter_optimizer(
                execute_uc,
                "uc",
                list(config.train_seeds),
                [],
                "",
                score,
                features,
                params,
                bounds,
                {},
                bo,
            )
        rows = [
            cached_solve(s, "llm4branch", score, features, params, code)
            for s in config.valid_seeds
        ]
        refs = [cached_solve(s, "default") for s in config.valid_seeds]
        valid = all(
            r["validity"]
            and b["validity"]
            and abs(r["objective"] - b["objective"]) <= 1e-4
            for r, b in zip(rows, refs)
        )
        nodes = float(np.mean([r["nodes"] for r in rows]))
        return {
            "validity": float(valid),
            "combined_score": float(np.log1p(10000 / nodes)) if valid else 0.0,
            "avg_nodes": nodes,
            "avg_time": float(np.mean([r["time"] for r in rows])),
            "params": params,
        }
    except Exception as exc:
        return {"validity": 0.0, "combined_score": 0.0, "error_info": str(exc)}


evaluate_stage2 = evaluate

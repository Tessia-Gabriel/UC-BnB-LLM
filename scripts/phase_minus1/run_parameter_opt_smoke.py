#!/usr/bin/env python3
"""Exercise the official brancher evaluator's Bayesian parameter path."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / "third_party/llm4branch"
BRANCHER = UPSTREAM / "examples/brancher"
sys.path[:0] = [str(UPSTREAM), str(BRANCHER)]

from evaluator import evaluate_stage2  # noqa: E402
from openevolve.config import EvaConfig  # noqa: E402


def main() -> None:
    lock_dir = ROOT / "outputs/phase_minus1/parameter_opt_locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    config = EvaConfig.from_yaml(
        str(ROOT / "configs/phase_minus1/evaluator_smoke.yaml"),
        "setcover",
        "1-1",
        str(lock_dir),
    )
    config._config["parameter_opt"] = True
    result = evaluate_stage2(str(BRANCHER / "initial_program.py"), config)
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result.get("validity") or "params" not in result:
        raise SystemExit("parameter optimization smoke test failed")


if __name__ == "__main__":
    main()

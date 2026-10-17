#!/usr/bin/env python3
"""Resume-safe convergence trajectories for the five representative UC cases."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ucbranch.convergence import METHODS, run_mps_convergence, trajectory_metrics


DEFAULT_INSTANCES = (
    "or-lib_200_0_1_w.json.gz",
    "or-lib_200_0_12_w.json.gz",
    "tejada19_UC_24h_214g.json.gz",
    "tejada19_UC_24h_290g.json.gz",
    "tejada19_UC_24h_480g.json.gz",
)


def _units(filename):
    if filename.startswith("or-lib_"):
        return 200
    match = re.search(r"_(\d+)g\.json\.gz$", filename)
    if not match:
        raise ValueError(f"cannot determine unit count: {filename}")
    return int(match.group(1))


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def _time_to_target(trajectory, target, horizon):
    return next(
        (
            row["wall_seconds"] for row in trajectory
            if row["wall_seconds"] <= horizon
            and row["gap"] is not None and row["gap"] <= target
        ),
        None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mps-dir", type=Path, default=ROOT / "outputs/public_uc_mps")
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "outputs/public_branching/convergence_trajectories_60s",
    )
    parser.add_argument("--root-limit", type=float, default=300.0)
    parser.add_argument("--branch-limit", type=float, default=60.0)
    parser.add_argument("--instances", nargs="+", default=list(DEFAULT_INSTANCES))
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    args = parser.parse_args()

    rows = []
    for filename in args.instances:
        stem = filename.removesuffix(".json.gz")
        mps_path = args.mps_dir / f"{stem}.mps"
        if not mps_path.is_file():
            raise SystemExit(f"missing official MPS: {mps_path}")
        digest = _sha256(mps_path)
        for method in args.methods:
            result_path = args.output / stem / f"{method}.json"
            if result_path.is_file():
                result = json.loads(result_path.read_text())
                print(f"resume {filename} {method}", flush=True)
            else:
                print(f"run {filename} {method}", flush=True)
                result = run_mps_convergence(
                    mps_path, method, args.root_limit, args.branch_limit
                )
                result.update(
                    instance=filename,
                    units=_units(filename),
                    hours=24,
                    root_limit_seconds=args.root_limit,
                    mps_sha256=digest,
                )
                print(json.dumps({
                    "branch_wall_seconds": result["branch_wall_seconds"],
                    "mean_capped_gap": result["trajectory_metrics"]["mean_capped_gap"],
                    "final_gap": result.get("gap"),
                    "status": result["status"],
                }), flush=True)
            result["trajectory_metrics"] = trajectory_metrics(
                result["trajectory"], args.branch_limit
            )
            _atomic_json(result_path, result)
            rows.append(result)

    rpb_gap = {
        row["instance"]: row["trajectory_metrics"]["gap_at_horizon"]
        for row in rows if row["method"] == "rpb"
    }
    for row in rows:
        target = rpb_gap.get(row["instance"])
        row["time_to_rpb_final_gap"] = (
            _time_to_target(row["trajectory"], target, args.branch_limit)
            if target is not None else None
        )
    summary = {
        "protocol": (
            "official UnitCommitment.jl v0.3 MPS; root-light settings; "
            "post-root wall-clock convergence trajectory"
        ),
        "primary_metric": (
            "mean_gap_ratio: area under gap(t)/gap(0) over post-root "
            "wall-clock horizon"
        ),
        "root_limit_seconds": args.root_limit,
        "branch_wall_budget_seconds": args.branch_limit,
        "instances": list(args.instances),
        "methods": list(args.methods),
        "results": rows,
    }
    _atomic_json(args.output / "summary.json", summary)
    print(json.dumps({
        "output": str(args.output / "summary.json"),
        "runs": len(rows),
        "all_reached_first_branch": all(row["first_branch_reached"] for row in rows),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()

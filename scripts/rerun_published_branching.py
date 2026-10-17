#!/usr/bin/env python3
"""Rerun published LLM4Branch programs with a post-root search budget."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ucbranch.public_branching import PUBLISHED_PROGRAMS, run_mps_branch_budget


DEFAULT_INSTANCES = (
    "or-lib_200_0_1_w.json.gz",
    "or-lib_200_0_12_w.json.gz",
    "tejada19_UC_24h_214g.json.gz",
    "tejada19_UC_24h_290g.json.gz",
    "tejada19_UC_24h_480g.json.gz",
)
DEFAULT_METHODS = ("scip_default", "rpb", *PUBLISHED_PROGRAMS)


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mps-dir", type=Path, default=ROOT / "outputs/public_uc_mps")
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "outputs/public_branching/published_postroot_60s",
    )
    parser.add_argument("--root-limit", type=float, default=300.0)
    parser.add_argument("--branch-limit", type=float, default=60.0)
    parser.add_argument("--instances", nargs="+", default=list(DEFAULT_INSTANCES))
    parser.add_argument("--methods", nargs="+", choices=DEFAULT_METHODS,
                        default=list(DEFAULT_METHODS))
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
                result = run_mps_branch_budget(
                    mps_path,
                    method,
                    root_limit=args.root_limit,
                    branch_limit=args.branch_limit,
                )
                result.update(
                    instance=filename,
                    units=_units(filename),
                    hours=24,
                    root_limit_seconds=args.root_limit,
                    mps_sha256=digest,
                )
                _atomic_json(result_path, result)
                print(json.dumps({
                    "root_seconds": result["root_solver_seconds"],
                    "branch_seconds": result["branch_search_seconds"],
                    "nodes": result["nodes"],
                    "gap": result.get("gap"),
                    "status": result["status"],
                }), flush=True)
            rows.append(result)

    summary = {
        "protocol": (
            "official UnitCommitment.jl v0.3 MPS; root-light settings; "
            "equal solver-time budget beginning at first branch"
        ),
        "root_limit_seconds": args.root_limit,
        "branch_budget_seconds": args.branch_limit,
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

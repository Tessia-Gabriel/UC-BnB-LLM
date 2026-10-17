#!/usr/bin/env python3
"""Resume-safe first-branch diagnostic on five representative public UC cases."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ucbranch.root_diagnostics import PROFILES, diagnose_first_branch


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/public_uc")
    parser.add_argument("--mps-dir", type=Path, default=ROOT / "outputs/public_uc_mps")
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "outputs/public_branching/first_branch_diagnostic",
    )
    parser.add_argument("--limit", type=float, default=300.0)
    parser.add_argument("--instances", nargs="+", default=list(DEFAULT_INSTANCES))
    parser.add_argument("--profiles", nargs="+", choices=PROFILES,
                        default=list(PROFILES))
    args = parser.parse_args()

    rows = []
    for filename in args.instances:
        instance_path = args.data_dir / filename
        mps_path = args.mps_dir / f"{filename.removesuffix('.json.gz')}.mps"
        if not instance_path.is_file():
            raise SystemExit(f"missing instance: {instance_path}")
        if not mps_path.is_file():
            raise SystemExit(f"missing official MPS: {mps_path}")
        input_hashes = {
            "json_sha256": _sha256(instance_path),
            "mps_sha256": _sha256(mps_path),
        }
        stem = filename.removesuffix(".json.gz")
        for profile in args.profiles:
            result_path = args.output / stem / f"{profile}.json"
            if result_path.is_file():
                result = json.loads(result_path.read_text())
                print(f"resume {filename} {profile}", flush=True)
            else:
                print(f"run {filename} {profile}", flush=True)
                result = diagnose_first_branch(
                    instance_path, mps_path, profile, args.limit
                )
                result.update(
                    instance=filename,
                    units=_units(filename),
                    hours=24,
                    **input_hashes,
                )
                _atomic_json(result_path, result)
                print(json.dumps({
                    "first_branch_reached": result["first_branch_reached"],
                    "solve_to_event_seconds": result["solve_to_event_seconds"],
                    "branch_candidates": result["branch_candidates"],
                    "status_at_event": result["status_at_event"],
                }), flush=True)
            rows.append(result)

    summary = {
        "protocol": "first-branch diagnostic; stops before choosing a branch",
        "limit_seconds_per_run": args.limit,
        "instances": list(args.instances),
        "profiles": list(args.profiles),
        "results": rows,
    }
    _atomic_json(args.output / "summary.json", summary)
    print(json.dumps({
        "output": str(args.output / "summary.json"),
        "runs": len(rows),
        "reached_first_branch": sum(row["first_branch_reached"] for row in rows),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Resume-safe adaptive benchmark on frozen public instances below 500 units."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ucbranch.public_branching import PUBLISHED_PROGRAMS, run_mps


def unit_count(filename):
    if filename.startswith("or-lib_"):
        return 200
    match = re.search(r"_(\d+)g\.json\.gz$", filename)
    if not match:
        raise ValueError(f"cannot determine unit count: {filename}")
    return int(match.group(1))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mps-dir", type=Path, default=ROOT / "outputs/public_uc_mps")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "outputs/public_branching/adaptive_under500")
    parser.add_argument("--limit", type=float, default=60.0)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "configs/public_uc_splits.json").read_text())
    filenames = [name for split in manifest["splits"].values() for name in split]
    filenames = sorted(
        (name for name in filenames if unit_count(name) < 500),
        key=lambda name: (unit_count(name), name),
    )

    rows = {}
    for filename in filenames:
        stem = filename.removesuffix(".json.gz")
        mps = args.mps_dir / f"{stem}.mps"
        if not mps.is_file():
            raise SystemExit(f"missing official MPS: {mps}")
        digest = hashlib.sha256(mps.read_bytes()).hexdigest()
        for method in ("native_scip", "rpb"):
            result_path = args.output / stem / f"{method}.json"
            if result_path.is_file():
                result = json.loads(result_path.read_text())
                print(f"resume {filename} {method}", flush=True)
            else:
                print(f"run {filename} {method}", flush=True)
                result = run_mps(mps, method, args.limit)
                result.update(instance=filename, units=unit_count(filename),
                              limit=args.limit, mps_sha256=digest)
                atomic_json(result_path, result)
            rows[(filename, method)] = result

    active = []
    for filename in filenames:
        if max(rows[(filename, method)]["nodes"] for method in ("native_scip", "rpb")) > 1:
            active.append(filename)

    for filename in active:
        stem = filename.removesuffix(".json.gz")
        mps = args.mps_dir / f"{stem}.mps"
        digest = hashlib.sha256(mps.read_bytes()).hexdigest()
        for method in PUBLISHED_PROGRAMS:
            result_path = args.output / stem / f"{method}.json"
            if result_path.is_file():
                result = json.loads(result_path.read_text())
                print(f"resume {filename} {method}", flush=True)
            else:
                print(f"run {filename} {method}", flush=True)
                result = run_mps(mps, method, args.limit)
                result.update(instance=filename, units=unit_count(filename),
                              limit=args.limit, mps_sha256=digest)
                atomic_json(result_path, result)
            rows[(filename, method)] = result

    all_rows = [rows[key] for key in sorted(rows)]
    summary = {
        "protocol": "adaptive under-500 public UC benchmark",
        "limit_seconds": args.limit,
        "screening_methods": ["native_scip", "rpb"],
        "published_programs_run_only_if_screening_nodes_gt_one": list(PUBLISHED_PROGRAMS),
        "instances": filenames,
        "branch_active_instances": active,
        "root_limited_instances": [name for name in filenames if name not in active],
        "results": all_rows,
    }
    atomic_json(args.output / "summary.json", summary)
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, indent=2))


if __name__ == "__main__":
    main()

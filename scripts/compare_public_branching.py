#!/usr/bin/env python3
"""Compare native SCIP, RPB, and the four published LLM4Branch programs."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ucbranch.public_branching import PUBLISHED_PROGRAMS, run
from ucbranch.public_uc import read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance", type=Path)
    parser.add_argument("--limit", type=float, default=60)
    parser.add_argument("--methods", nargs="+", default=[
        "native_scip", "rpb", *PUBLISHED_PROGRAMS,
    ])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    instance = read(args.instance)
    rows = []
    for method in args.methods:
        print(f"running {method}...", flush=True)
        row = run(instance, method, args.limit)
        row.update(instance=args.instance.name, units=len(instance.units),
                   hours=instance.hours, limit=args.limit)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    payload = {
        "warning": (
            "native_scip uses full SCIP defaults; RPB and published programs "
            "use the controlled LLM4Branch protocol, so read the protocol field"
        ),
        "results": rows,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

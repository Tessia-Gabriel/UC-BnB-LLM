#!/usr/bin/env python3
"""Export an OpenEvolve checkpoint's evaluated programs as traceable JSONL."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


def program_constants(code: str) -> dict:
    """Read the three literal program declarations without executing code."""
    wanted = {"USED_FEATURES", "PARAMS", "BOUNDS"}
    values = {}
    for node in ast.parse(code).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in wanted:
            values[target.id] = ast.literal_eval(node.value)
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    program_dir = args.checkpoint / "programs"
    if not (args.checkpoint / "metadata.json").is_file() or not program_dir.is_dir():
        raise SystemExit(f"not an OpenEvolve checkpoint: {args.checkpoint}")

    rows = []
    for path in sorted(program_dir.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        constants = program_constants(record["code"])
        rows.append(
            {
                "program_id": record["id"],
                "parent_id": record.get("parent_id"),
                "generation": record.get("generation"),
                "iteration_found": record.get("iteration_found"),
                "code": record["code"],
                "used_features": constants.get("USED_FEATURES"),
                "params": constants.get("PARAMS"),
                "bounds": constants.get("BOUNDS"),
                "metrics": record.get("metrics", {}),
                "metadata": record.get("metadata", {}),
                "prompts": record.get("prompts", {}),
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"exported {len(rows)} evaluated programs to {args.output}")


if __name__ == "__main__":
    main()

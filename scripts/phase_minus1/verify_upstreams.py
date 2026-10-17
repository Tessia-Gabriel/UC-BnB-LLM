#!/usr/bin/env python3
"""Fail if a vendored upstream is missing, dirty, or not at its locked commit."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def main() -> None:
    lock = json.loads((ROOT / "third_party/UPSTREAM_LOCK.json").read_text(encoding="utf-8"))
    for name, spec in lock["dependencies"].items():
        path = ROOT / spec["path"]
        actual = git(path, "rev-parse", "HEAD")
        if actual != spec["commit"]:
            raise SystemExit(f"{name}: expected {spec['commit']}, found {actual}")
        dirty = git(path, "status", "--short", "--untracked-files=no")
        if dirty:
            raise SystemExit(f"{name}: tracked upstream files were modified:\n{dirty}")
        print(f"{name}: {actual} (clean tracked source)")


if __name__ == "__main__":
    main()


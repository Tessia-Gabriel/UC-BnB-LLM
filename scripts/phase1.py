"""Phase 1 compiler smoke, not the Phase 2 performance gate."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ucbranch.structured import KINDS, BranchDecision, solve_structured
from ucbranch.solver import solve
from ucbranch.uc import generate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/phase1")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    instance = generate(0, 12, 24)
    reference = solve(instance)
    assert reference["validity"]
    rows = {}
    for kind in KINDS:

        def policy(candidates):
            pool = [c for c in candidates if c.kind == kind]
            if not pool:
                return None
            c = max(pool, key=lambda c: c.features["fractionality"])
            return BranchDecision(c.kind, c.params, c.features["fractionality"])

        result = solve_structured(instance, policy, max_depth=2)
        assert (
            result["validity"]
            and abs(result["objective"] - reference["objective"]) < 1e-4
        )
        assert any(b["kind"] == kind for b in result["branches"])
        rows[kind] = result
        print(
            kind, result["status"], result["nodes"], len(result["branches"]), flush=True
        )
    report = dict(
        scope="Phase 1 correctness only; Gate 1 performance not assessed",
        instance=instance.to_dict(),
        windows=[2, 4],
        max_depth=2,
        reference=reference,
        results=rows,
        source_sha256={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT / "src/ucbranch").glob("*.py")
        },
    )
    (args.output / "evidence.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()

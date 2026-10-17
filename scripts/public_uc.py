"""Solve a public UC benchmark with the project reference formulation."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ucbranch.public_uc import read, build, validate, to_unitcommitment_solution

DEFAULT = ROOT / "data/public_uc/or-lib_200_0_1_w.json.gz"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance", type=Path, nargs="?", default=DEFAULT)
    parser.add_argument("--limit", type=float, default=60)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--solution", type=Path,
                        help="write a UnitCommitment.jl-compatible solution JSON")
    parser.add_argument("--formulation", choices=("standard", "ucjl03"),
                        default="standard")
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be positive")
    instance = read(args.instance)
    start = time.perf_counter()
    model = build(instance, formulation=args.formulation)
    build_seconds = time.perf_counter() - start
    settings = {
        "limits/time": args.limit,
        "parallel/maxnthreads": 1,
        "randomization/randomseedshift": 0,
        "randomization/permutationseed": 0,
    }
    model.setParams(settings)
    model.optimize()
    result = dict(
        instance=args.instance.name,
        units=len(instance.units),
        hours=instance.hours,
        status=str(model.getStatus()),
        solutions=model.getNSols(),
        nodes=model.getNNodes(),
        gap=model.getGap(),
        primal=model.getPrimalbound(),
        dual=model.getDualbound(),
        build_seconds=build_seconds,
        solver_seconds=model.getSolvingTime(),
        settings=settings,
        formulation=args.formulation,
        independently_validated=False,
    )
    if model.getNSols():
        values = {
            variable.name: float(model.getVal(variable))
            for variable in model.getVars(transformed=False)
        }
        reconstructed = validate(instance, values)
        assert abs(reconstructed - model.getObjVal()) < 1e-3
        result.update(objective=model.getObjVal(), independently_validated=True)
        if args.solution:
            args.solution.parent.mkdir(parents=True, exist_ok=True)
            args.solution.write_text(json.dumps(
                to_unitcommitment_solution(instance, values), indent=2
            ) + "\n")
    print(json.dumps(result, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(result, indent=2) + "\n")
        temporary.replace(args.output)


if __name__ == "__main__":
    main()

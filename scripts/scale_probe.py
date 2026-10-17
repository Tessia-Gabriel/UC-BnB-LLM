"""Plan or run larger native-SCIP UC checks; not a branching performance gate."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ucbranch.uc import generate, build, validate


def plan(units, horizons, seeds, limit):
    if any(type(x) is not int or x <= 0 for x in (*units, *horizons)):
        raise ValueError("units and horizons must be positive integers")
    if not units or not horizons or not seeds or not 0 < limit < float("inf"):
        raise ValueError("nonempty dimensions and a finite positive limit required")
    return [dict(id=f"n{n}_h{h}_s{s}", units=n, horizon=h, seed=s,
                 commitment_count=n*h, original_variable_count=4*n*h, limit=limit)
            for n in sorted(set(units)) for h in sorted(set(horizons)) for s in sorted(set(seeds))]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--units", nargs="+", type=int, default=[100,200,500])
    p.add_argument("--horizons", nargs="+", type=int, default=[24,48])
    p.add_argument("--seeds", nargs="+", type=int, default=[100])
    p.add_argument("--limit", type=float, default=30)
    p.add_argument("--output", type=Path, default=ROOT/"outputs/scale-probe")
    p.add_argument("--run", action="store_true", help="Without this flag only print the plan")
    args = p.parse_args()
    try:
        jobs = plan(args.units, args.horizons, args.seeds, args.limit)
    except ValueError as exc:
        p.error(str(exc))
    protocol = dict(purpose="native capacity check, not research efficacy", jobs=jobs,
                    source_hashes={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
                                   for f in [Path(__file__), ROOT/"src/ucbranch/uc.py"]})
    print(json.dumps(protocol, indent=2), flush=True)
    if not args.run:
        return
    args.output.mkdir(parents=True, exist_ok=True)
    protocol_path = args.output/"protocol.json"
    if protocol_path.exists() and json.loads(protocol_path.read_text()) != protocol:
        raise RuntimeError("Different protocol: use a new output directory")
    protocol_path.write_text(json.dumps(protocol, indent=2)+"\n")
    for job in jobs:
        target = args.output/(job["id"]+".json")
        if target.exists():
            print("Already recorded:",job["id"], flush=True)
            continue
        instance = generate(job["seed"], job["units"], job["horizon"])
        start = time.perf_counter()
        m = build(instance)
        build_time = time.perf_counter()-start
        settings = {"limits/time":job["limit"], "parallel/maxnthreads":1,
                    "randomization/randomseedshift":0, "randomization/permutationseed":0}
        m.setParams(settings)
        nvars, ncons = m.getNVars(), m.getNConss()
        m.optimize()
        result = dict(job=job, instance=instance.to_dict(), settings=settings,
                      presolve_maxrounds=m.getParam("presolving/maxrounds"),
                      original_variables=nvars, original_constraints=ncons,
                      build_seconds=build_time, solver_seconds=m.getSolvingTime(),
                      wall_seconds=time.perf_counter()-start, status=str(m.getStatus()),
                      nodes=m.getNNodes(), gap=m.getGap(), primal=m.getPrimalbound(), dual=m.getDualbound(),
                      schedule_valid=False)
        if m.getNSols():
            values = {v.name:float(m.getVal(v)) for v in m.getVars(transformed=False)}
            objective = float(m.getObjVal())
            assert abs(validate(instance, values)-objective) < 1e-4
            result.update(objective=objective, values=values, schedule_valid=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2)+"\n")
        temporary.replace(target)
        print(job["id"],result["status"],"nodes",result["nodes"],"gap",result["gap"],flush=True)
        m.freeProb()


if __name__ == "__main__":
    main()

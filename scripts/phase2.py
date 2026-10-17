"""Resumable, fixed-protocol Phase 2 pilot; no API/model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import statistics

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ucbranch.phase2 import METHODS, SCENARIOS, instances, run


def summarize(rows):
    summary = {}
    for method in METHODS:
        group = [r for r in rows if r["method"] == method]
        summary[method] = dict(runs=len(group), solved=sum(r["status"] == "optimal" for r in group),
            timeouts=sum(r["status"] == "timelimit" for r in group),
            mean_nodes=statistics.mean(r["nodes"] for r in group),
            mean_wall_time=statistics.mean(r["wall_time"] for r in group),
            mean_sampled_pdi=statistics.mean(r["primal_dual_integral_sampled"] for r in group),
            mean_final_gap=statistics.mean(r["final_gap"] for r in group),
            mean_time_to_first_incumbent=(statistics.mean(r["time_to_first_incumbent"] for r in group
                if r["time_to_first_incumbent"] is not None)
                if any(r["time_to_first_incumbent"] is not None for r in group) else None),
            incumbents=sum(r["time_to_first_incumbent"] is not None for r in group))
    # Predeclared gate: scenario cohort (6 instances), no cherry-picked single seed.
    evidence = []
    by_key = {(r["instance_id"], r["method"]):r for r in rows}
    for scenario in SCENARIOS:
        for method in ("start", "temporal", "hybrid"):
            chosen = [r for r in rows if r["scenario"] == scenario and r["method"] == method]
            comparisons = {}
            for control in ("native_default", "matched_default", "pseudocost", "llm4branch"):
                paired = [(r, by_key[r["instance_id"], control]) for r in chosen]
                solved = all(a["status"] == b["status"] == "optimal" for a,b in paired)
                ratios = {key: sum(a[key] for a,b in paired)/max(1e-10,sum(b[key] for a,b in paired))
                          for key in ("wall_time", "nodes", "primal_dual_integral_sampled")}
                comparisons[control] = dict(all_solved=solved, ratios=ratios)
            passed = (len(chosen) == 6 and any(r["branches"] for r in chosen) and
                      all(c["all_solved"] and c["ratios"]["wall_time"] <= .9 and
                          c["ratios"]["nodes"] <= .9 and c["ratios"]["primal_dual_integral_sampled"] <= 1.05
                          for c in comparisons.values()))
            evidence.append(dict(scenario=scenario, method=method, passed=passed, comparisons=comparisons))
    return dict(methods=summary, gate1_passed=any(e["passed"] for e in evidence), cohorts=evidence)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT/"outputs/phase2")
    parser.add_argument("--limit", type=float, default=3)
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("limit must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    suite = list(instances())
    protocol = dict(limit=args.limit, instances=[dict(id=i,scenario=s,data=x.to_dict()) for i,s,x in suite],
                    methods=METHODS, repetitions=1, horizon=8, thresholds=dict(fractionality=.25,max_depth=2),
                    source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in [*(ROOT/"src/ucbranch").glob("*.py"), Path(__file__), ROOT/"configs/phase0/initial_program.py"]})
    protocol = json.loads(json.dumps(protocol))
    path = args.output/"protocol.json"
    if path.exists() and json.loads(path.read_text()) != protocol:
        raise RuntimeError("Protocol/source changed: use a new output directory")
    path.write_text(json.dumps(protocol, indent=2)+"\n")
    rows = []
    for index,(instance_id,scenario,inst) in enumerate(suite):
        # Rotate deterministic execution order to reduce fixed-order bias.
        order = METHODS[index % len(METHODS):] + METHODS[:index % len(METHODS)]
        for method in order:
            target = args.output/f"{instance_id}__{method}.json"
            if target.exists():
                result = json.loads(target.read_text())
                assert result["instance_id"] == instance_id and result["method"] == method
                assert result["settings"]["limits/time"] == args.limit
            else:
                result = run(inst, method, args.limit)
                result.update(instance_id=instance_id, scenario=scenario)
                temporary = target.with_suffix(".tmp")
                temporary.write_text(json.dumps(result, indent=2)+"\n")
                temporary.replace(target)
            rows.append(result)
            print(instance_id, method, result["status"], result["nodes"], flush=True)
        same = [r for r in rows if r["instance_id"] == instance_id]
        optima = [r["objective"] for r in same if r["status"] == "optimal"]
        if optima:
            assert max(optima)-min(optima) < 1e-4
            assert all(r.get("objective", float("inf")) >= min(optima)-1e-4 for r in same)
            assert all(r["dual"] <= min(optima)+1e-4 for r in same)
    summary = summarize(rows)
    (args.output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print("Gate 1:", summary["gate1_passed"], flush=True)


if __name__ == "__main__":
    main()

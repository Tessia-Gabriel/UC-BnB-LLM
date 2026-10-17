#!/usr/bin/env python3
"""Run Gate 0 baselines and optional upstream evolution smoke."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import hashlib
import ast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ucbranch.evaluator import cached_solve, check_program
from ucbranch.integration import ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--search-config", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/phase0")
    args = parser.parse_args()
    args.output = args.output.resolve()
    os.environ["UCBRANCH_OUTPUT"] = str(args.output)
    args.output.mkdir(parents=True, exist_ok=True)
    initial = ROOT / "configs/phase0/initial_program.py"
    score, features, params, _ = check_program(initial)
    rows = []
    for seed in (0, 1, 2):
        for method in ("default", "pseudocost", "most_fractional", "llm4branch"):
            r = cached_solve(seed, method, score, features, params, initial.read_text())
            rows.append({k: v for k, v in r.items() if k != "values"})
            print(
                seed,
                method,
                r["status"],
                r["nodes"],
                r["decisions"],
                r.get("objective"),
                flush=True,
            )
    for seed in (0, 1, 2):
        group = [r for r in rows if r["seed"] == seed]
        assert all(r["validity"] for r in group)
        assert (
            max(r["objective"] for r in group) - min(r["objective"] for r in group)
            < 1e-4
        )
    for method in ("pseudocost", "most_fractional", "llm4branch"):
        assert sum(r["decisions"] for r in rows if r["method"] == method) > 0
    (args.output / "baselines.json").write_text(json.dumps(rows, indent=2))
    if args.search_config:
        from openevolve.config import Config, EvaConfig
        from openevolve import OpenEvolve

        c = Config.from_yaml(args.search_config)
        # Reuse the upstream 91-feature prompt, including feature definitions.
        import yaml

        official = yaml.safe_load(
            (ROOT / "third_party/llm4branch/examples/brancher/config.yaml").read_text()
        )
        c.prompt.system_message = official["prompt"]["system_message"]
        c.prompt.system_message += (
            "\nOnly commitment variables of a single-bus UC model are candidates."
        )
        c.evaluator.dataset = EvaConfig(
            train_seeds=[12],
            valid_seeds=[16],
            parameter_opt=True,
            target="nodes",
            n_initial=2,
            n_calls=3,
            max_workers=1,
        )
        c.database.db_path = str(args.output / "program_database")
        if (args.output / "program_database/metadata.json").exists():
            raise SystemExit(
                "Search output already exists; select a new --output directory."
            )
        # Store reproducible, credential-free provenance next to the primary DB.
        provenance = dict(
            train_seeds=[12],
            valid_seeds=[16],
            baseline_seeds=[0, 1, 2],
            iterations=2,
            seed=c.random_seed,
            n_initial=2,
            n_calls=3,
            upstream=json.loads((ROOT / "third_party/UPSTREAM_LOCK.json").read_text()),
            models=[
                dict(
                    name=m.name,
                    temperature=m.temperature,
                    top_p=m.top_p,
                    max_tokens=m.max_tokens,
                    random_seed=m.random_seed,
                )
                for m in c.llm.models
            ],
            search_config_sha256=hashlib.sha256(
                args.search_config.read_bytes()
            ).hexdigest(),
        )
        engine = OpenEvolve(
            str(initial),
            str(ROOT / "src/ucbranch/evaluator.py"),
            config=c,
            output_dir=str(args.output / "search"),
        )
        provenance["models"] = [
            dict(
                name=m.name,
                temperature=m.temperature,
                top_p=m.top_p,
                max_tokens=m.max_tokens,
                random_seed=m.random_seed,
            )
            for m in c.llm.models
        ]
        (args.output / "provenance.json").write_text(json.dumps(provenance, indent=2))
        asyncio.run(engine.run(iterations=2))
        engine.database.save(str(args.output / "program_database"))
        assert len(engine.database.programs) >= 2
        assert all(
            p.metrics.get("validity") == 1 for p in engine.database.programs.values()
        )
        # Upstream retains UUID lineage; the derived export deduplicates by source hash.
        unique = {}
        for p in engine.database.programs.values():
            digest = hashlib.sha256(p.code.encode()).hexdigest()
            record = unique.setdefault(
                digest,
                dict(
                    sha256=digest,
                    program_ids=[],
                    code=p.code,
                    metrics=p.metrics,
                    params=None,
                ),
            )
            record["program_ids"].append(p.id)
            for node in ast.parse(p.code).body:
                if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "PARAMS" for t in node.targets
                ):
                    record["params"] = p.metrics.get(
                        "params", ast.literal_eval(node.value)
                    )
        (args.output / "programs_unique.jsonl").write_text(
            "".join(json.dumps(p) + "\n" for p in unique.values())
        )
    print("Gate 0 objective agreement passed", flush=True)


if __name__ == "__main__":
    main()

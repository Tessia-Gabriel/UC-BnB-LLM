# Project specification

The normative technical specification for this repository is
[`UC_BnB_LLM_SFT_DPO_Technical_Roadmap_v0.2.md`](./UC_BnB_LLM_SFT_DPO_Technical_Roadmap_v0.2.md).

## Research objective

Use the LLM4Branch/OpenEvolve stack only as an **offline algorithm-discovery
engine**. Solver feedback is used to discover, and later post-train an LLM to
discover, inexpensive UC-aware branching programs. Deployment contains a
frozen deterministic branching rule or portfolio and makes zero LLM calls.

The research contribution is not another implementation of program evolution
or a variable-scoring clone. It is the UC-specific structured search space,
features, disjunction compiler, solver-feedback datasets, and the final frozen
rule.

## Upstream boundary

Reuse upstream population search, program database, checkpoints, LLM retry and
ensemble support, cascade orchestration, and parameter optimization. Keep
upstream source pinned and unmodified; integrate later work through adapters.

## Current scope: Phase 2

### Scale correction (2026-09-18)

The user's earlier work scaled from 50 to 200 and 500 units. Use 200/500 units
as primary development scales, not only as a final extrapolation check.
Small cases remain correctness controls. Start with a provisional 24-period
horizon; historical period count, time-step duration and data source remain
unconfirmed. The 8-period/3-second Phase 2 pilot is historical evidence only.
See [architecture and scale guide](docs/ARCHITECTURE_AND_SCALE_ZH.md).

Future efficacy experiments use public UC benchmarks as the primary data,
starting with the checked-in OR-LIB 200-unit/24-hour and Tejada19
505-unit/24-hour instances. Synthetic instances remain correctness fixtures.
The project formulation must be cross-validated against UnitCommitment.jl
before reporting benchmark performance.

- Pin and reproduce official LLM4Branch and its custom Ecole dependency.
- Exercise an official benchmark, a short search, checkpoint/resume, program
  export, and parameter optimization.
- Document the actual interfaces and data contracts.
- Phase 0 implements a single-bus thermal UC model and variable-only baselines,
  with an evaluator adapter to the pinned OpenEvolve and BO infrastructure.
- Phase 1 implements VAR, UNIT_ON_COUNT, START_COUNT and GROUP_ON_COUNT,
  a SCIP disjunction compiler, validation, fallback and correctness tests.
- BLOCK_ON_COUNT and SFT/DPO remain out of scope. Phase 2 performance Gate 1
  is not implied by successful Phase 1 correctness tests.
- Phase 2 runs a fixed, no-LLM 30-instance handcrafted-rule feasibility pilot,
  with matched-formulation controls, native SCIP reference and recorded metrics.
  Completing the experiment does not imply Gate 1 passed; consult its evidence.

Phase 0 must not start until the evidence in
[`docs/LLM4BRANCH_INTEGRATION.md`](./docs/LLM4BRANCH_INTEGRATION.md) satisfies
Gate -1.

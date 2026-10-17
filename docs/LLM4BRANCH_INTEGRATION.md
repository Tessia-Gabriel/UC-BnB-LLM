# LLM4Branch integration audit — Phase -1

## Gate decision

**Gate -1 passes for infrastructure integration.** The pinned upstream can run
the official SetCover evaluator end to end, perform a short program evolution,
save and resume a checkpoint, export every evaluated program with metrics, and
execute its Bayesian parameter optimizer. No UC or structured-branching code
was introduced.

The search smoke test uses a deterministic local OpenAI-compatible endpoint
because no external model credential is stored in this repository. Solver
feedback is real (custom Ecole + SCIP); the mock only supplies valid candidate
source code. Therefore this proves the framework contract and reproducibility,
not LLM quality or benchmark superiority.

Machine-readable results are in
[`phase_minus1_evidence.json`](./phase_minus1_evidence.json).

## Pinned upstreams and source policy

The canonical lock is [`third_party/UPSTREAM_LOCK.json`](../third_party/UPSTREAM_LOCK.json).

| Dependency | Repository | Commit | License |
|---|---|---|---|
| LLM4Branch (including its OpenEvolve fork) | `hzn18/LLM4Branch` | `e001d8c9f9f9b7d414922526c8d958a2cbf62462` | Apache-2.0 |
| Custom Ecole | `hzn18/LLM4Branch-ecole` | `debd0e44dc5c5c200fcb3845d511cd0729baaa3b` | BSD-3-Clause |

Both repositories retain their original history and license. Their tracked
source is clean; `scripts/phase_minus1/verify_upstreams.py` enforces both commit
IDs and fails on tracked changes. Later project work should call these modules
through adapters rather than edit them.

## Reproducible environment

The direct dependencies are fixed in [`environment.yml`](../environment.yml).
The verified environment is Python 3.10.14, Ecole 0.8.1, SCIP 8.1.0 (SoPlex
6.0.4), PySCIPOpt 4.4.0, and NumPy 1.26.4 on Ubuntu 24.04 x86-64.

Setup:

```bash
bash scripts/phase_minus1/setup.sh
```

The Ecole fork declares its exact historical C++ dependencies but a modern
conda solve selects xtensor 0.27, whose reorganized headers cannot compile
Ecole 0.8.1. The setup therefore passes `ECOLE_FORCE_DOWNLOAD=ON`; CMake then
fetches the versions and SHA-256 hashes already declared by upstream (including
xtensor 0.23.1 and pybind11 2.9.1). This is an environment/build flag, not a
source patch.

## Minimal commands

Run the official Ecole generator and solver tests:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .conda/llm4branch/bin/pytest -q third_party/llm4branch/tests/test_ecole.py
```

Run a one-iteration search, save `checkpoint_1`, resume for one iteration to
`checkpoint_2`, and export the final database:

```bash
bash scripts/phase_minus1/run_smoke.sh
```

Exercise parameter optimization independently:

```bash
.conda/llm4branch/bin/python scripts/phase_minus1/run_parameter_opt_smoke.py
```

The script uses the unmodified official initial program and SetCover evaluator,
plus the small-budget configs in `configs/phase_minus1/`. Outputs go to
`outputs/phase_minus1/<run-id>/` and are intentionally ignored by version
control.

For a real model, copy `configs/phase_minus1/mock_key_set.yaml` to the ignored
`local_key_set.yaml`, set an OpenAI-compatible endpoint and credential, point a
copy of `search_smoke.yaml` at it, and use the same upstream CLI. Never commit
the credential file.

## Initial program interface

An evolvable program is a complete Python file containing:

```python
USED_FEATURES = [9, 43]
PARAMS = [0.5, 0.5]
BOUNDS = [[0.0, 1.0], [0.0, 1.0]]

def score_function(variable_features, params):
    ...
```

`score_function` receives an `(n_candidates, 91)` NumPy array and the current
parameter vector, and must return one finite score per candidate. The evaluator
selects `argmax`. `USED_FEATURES` controls which Flash columns are extracted
and normalized. `PARAMS` and `BOUNDS` must be literal non-empty lists because
the loader combines Python import, regex parsing, and `ast.literal_eval` rather
than consuming a typed schema. The official seed is
`third_party/llm4branch/examples/brancher/initial_program.py`; parsing lives in
`examples/brancher/utils/utils.py::load_program`.

This interface is directly reusable for the Phase-0 variable-only baseline.
Structured branch objects do not fit it and will later require a project-owned
candidate/decision adapter while preserving OpenEvolve's outer `program code ->
metrics` contract.

The upstream seed itself contains a mismatch: `USED_FEATURES = [1]`, while its
function reads column `43`. As a result, the Flash extractor is not explicitly
asked to activate the feature the seed scores. It is retained verbatim for this
reproduction, but Phase 0 must use a consistent declaration and validate output
shape/finiteness before solving.

## Evaluator contract

OpenEvolve writes candidate source to a temporary file and invokes a synchronous
function with this contract:

```python
def evaluate(program_path: str, config: EvaConfig) -> dict | EvaluationResult:
    ...
```

The dictionary may contain any numeric metrics; `combined_score` is the primary
higher-is-better fitness used by the database. Non-numeric values are tolerated,
and `params` is a special field consumed by the iteration worker. Exceptions,
timeouts, and artifacts are normalized by `openevolve/evaluator.py::Evaluator`.

The official brancher evaluator performs the following real solver loop:

1. Parse the program and requested features.
2. Generate a seeded easy benchmark instance.
3. Configure `NodeBipartiteFlash` and `Khalil2016Flash`.
4. At each Ecole branching state, concatenate features, normalize only requested
   columns, score the SCIP action set, and apply `argmax`.
5. Return validity, CPU time, SCIP node count, gap, and derived aggregate scores.

For `target: nodes`, the official combined fitness is
`log(10000 / avg_nodes + 1)`, hence larger is better.

## Cascade evaluation flow

With `cascade_evaluation: true`, OpenEvolve dynamically imports the evaluator
and looks for `evaluate_stage1`, `evaluate_stage2`, and optionally
`evaluate_stage3`:

```text
temporary program
  -> evaluate_stage1(program_path, EvaConfig)
  -> average numeric stage-1 metrics >= threshold?
       no  -> return stage-1 result
       yes -> evaluate_stage2(...)
              -> merge numeric stage-1/stage-2 metrics
              -> optional stage 3 under the next threshold
```

The brancher implementation uses Stage 1 as a cheap train-seed comparison with
SCIP relative pseudocost and Stage 2 as full validation plus optional BO. The
orchestration, timeouts, and merge behavior are reusable; UC should replace
only the evaluator functions/config.

Important integration caveat: thresholds are applied to the arithmetic mean of
all numeric stage metrics, not to a named metric. UC adapters should return a
single explicit gate score per early stage or carefully control which numeric
fields are exposed. Also, the official Stage-1 code uses runtime speedup for
both `target: time` and `target: nodes`; a node-targeted UC cascade must define
its intended cheap metric explicitly rather than inherit that behavior by
accident.

## Parameter optimization flow

`examples/brancher/evaluator.py::params_optimizer` builds one `skopt.space.Real`
per `BOUNDS` entry and minimizes time, nodes, or gap on training seeds using a
Gaussian-process `Optimizer(acq_func="gp_hedge", random_state=123)`. The chosen
parameters are returned as `metrics["params"]`. The process worker removes that
special metric, rewrites the literal `PARAMS = [...]` in the candidate source,
and stores the tuned source plus ordinary solver metrics in the database.

The smoke run used `n_initial=2`, `n_calls=3` and returned `[0.5]`. Upstream has
an unhandled boundary at `n_initial=1`: it calls `Optimizer.ask(0)` and raises
`ValueError`. Keep `n_initial >= 2` unless a minimal upstream patch is approved.

## Program database schema

The in-memory unit is `openevolve.database.Program`, serialized as one
`programs/<UUID>.json` file:

| Field | Meaning |
|---|---|
| `id`, `code`, `language` | identity and complete executable program |
| `parent_id`, `generation`, `iteration_found`, `timestamp` | lineage |
| `metrics` | fitness and all evaluator outputs |
| `complexity`, `diversity` | MAP-Elites descriptors |
| `metadata` | island, change summary, parent metrics |
| `artifacts_json`, `artifact_dir` | small/large evaluator artifacts |
| `prompts` | optional prompt, response, and template snapshot |

Checkpoint `metadata.json` stores the feature map, island membership, archive,
global/island best IDs, last iteration, island generations, and migration state.
`scripts/phase_minus1/export_programs.py` produces traceable JSONL, including
AST-read `used_features`, `params`, and `bounds`, without executing the program
or inventing another primary database.

Program IDs are random UUIDs, not content hashes. The roadmap's hash-dedup
requirement is therefore **not supplied by upstream** and belongs in the future
integration adapter/cache, not as a Phase -1 core edit.

## Checkpoint and resume

`OpenEvolve._save_checkpoint` calls `ProgramDatabase.save`, writes the best
program and its metrics, and records the completed iteration. The CLI's
`--checkpoint <dir>` loads programs and metadata; `OpenEvolve.run` resumes at
`last_iteration + 1` and skips initial-program evaluation.

Verified transition:

```text
fresh -> checkpoint_1: last_iteration=1, 2 programs
resume checkpoint_1 -> checkpoint_2: last_iteration=2, 3 programs
```

An upstream provenance defect was exposed: `Program.from_dict` filters the
serialized `prompts` extension field and `ProgramDatabase.load` does not restore
it into `prompts_by_program`. A later checkpoint can consequently overwrite an
older program JSON without its prompt. The smoke script exports checkpoint 1
before resuming so evidence is retained. Before Round-0 data collection, add a
minimal upstream patch or an adapter-side prompt ledger and record that patch.

## LLM provider interface

`LLMInterface` exposes async `generate(prompt, **kwargs)` and
`generate_with_context(system_message, messages, **kwargs)`. `OpenAILLM`
implements this with an OpenAI-compatible Chat Completions endpoint, timeout,
retry delay, retry count, temperature/top-p/token settings, and optional seed.
`LLMEnsemble` performs weighted seeded provider selection and offers single,
multiple, parallel, and all-model calls.

This interface can point directly to a later vLLM OpenAI-compatible server. No
new provider abstraction is needed for Phase 0 or the post-training rounds.

## Critical modules and reuse decision

| Module | Responsibility | Decision |
|---|---|---|
| `openevolve/controller.py` | lifecycle, initial evaluation, checkpoints | reuse unchanged |
| `openevolve/process_parallel.py` | async/process iteration scheduling | reuse unchanged |
| `openevolve/database.py` | islands, MAP-Elites, archive, persistence | reuse; add external hash cache later |
| `openevolve/evaluator.py` | temp-file execution and cascade | reuse orchestration; replace evaluator functions |
| `openevolve/prompt/` | mutation/full-rewrite prompts | reuse, later supply UC DSL prompt |
| `openevolve/llm/` | OpenAI-compatible calls, retry, ensemble | reuse unchanged; vLLM fits directly |
| `examples/brancher/evaluator.py` | feature/SCIP benchmark and BO | variable-only baseline reference; later thin UC adapter |
| custom Ecole Flash observations | cheap selected-column features | reuse generic features where semantically valid |

## Test results and remaining blockers

- Upstream source lock/clean check: passed for both repositories.
- Custom Ecole import: passed; both Flash classes exist.
- Official Ecole tests: `2 passed`.
- Official SetCover initial-program evaluation: valid, 363 nodes.
- Cascade short search: complete; candidate evaluated by real SCIP.
- Checkpoint/resume: complete through iteration 2.
- Program export: 3/3 programs exported with fitness and code.
- BO path: complete with a three-call smoke budget.
- Upstream core modifications: **none**.

Remaining before a costly Round-0 run, but not blockers for Gate -1:

1. Supply and validate the chosen real LLM/vLLM endpoint and credential.
2. Resolve prompt-loss-on-resume before treating the program DB as training
   provenance.
3. Add content-hash deduplication/cache in the project adapter for the roadmap's
   stronger data-integrity requirement.
4. Do not interpret single-seed smoke timing as a performance result; use fixed
   multi-seed budgets for research comparisons.

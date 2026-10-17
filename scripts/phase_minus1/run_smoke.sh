#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UPSTREAM_DIR="${ROOT_DIR}/third_party/llm4branch"
ENV_DIR="${ROOT_DIR}/.conda/llm4branch"
RUN_ID="${1:-$(date +%Y%m%d-%H%M%S)}"
OUTPUT_DIR="${ROOT_DIR}/outputs/phase_minus1/${RUN_ID}"
LOCK_DIR="${OUTPUT_DIR}/cpu_locks"

mkdir -p "${LOCK_DIR}"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY="127.0.0.1,localhost"
"${ENV_DIR}/bin/python" "${ROOT_DIR}/scripts/phase_minus1/mock_openai_server.py" &
SERVER_PID=$!
trap 'kill "${SERVER_PID}" 2>/dev/null || true' EXIT
sleep 0.5

cd "${ROOT_DIR}"
export PYTHONPATH="${UPSTREAM_DIR}:${UPSTREAM_DIR}/examples/brancher"

"${ENV_DIR}/bin/python" "${UPSTREAM_DIR}/openevolve-run.py" \
  "${UPSTREAM_DIR}/examples/brancher/initial_program.py" "${UPSTREAM_DIR}/examples/brancher/evaluator.py" \
  --config "${ROOT_DIR}/configs/phase_minus1/search_smoke.yaml" \
  --evaluator-config "${ROOT_DIR}/configs/phase_minus1/evaluator_smoke.yaml" \
  --cores-list 0-0 --lock-dir "${LOCK_DIR}" --dataset setcover \
  --output "${OUTPUT_DIR}" --iterations 1 --log-level INFO

"${ENV_DIR}/bin/python" "${ROOT_DIR}/scripts/phase_minus1/export_programs.py" \
  "${OUTPUT_DIR}/checkpoints/checkpoint_1" "${OUTPUT_DIR}/checkpoint_1_programs.jsonl"

"${ENV_DIR}/bin/python" "${UPSTREAM_DIR}/openevolve-run.py" \
  "${UPSTREAM_DIR}/examples/brancher/initial_program.py" "${UPSTREAM_DIR}/examples/brancher/evaluator.py" \
  --config "${ROOT_DIR}/configs/phase_minus1/search_smoke.yaml" \
  --evaluator-config "${ROOT_DIR}/configs/phase_minus1/evaluator_smoke.yaml" \
  --cores-list 0-0 --lock-dir "${LOCK_DIR}" --dataset setcover \
  --output "${OUTPUT_DIR}" --iterations 1 --log-level INFO \
  --checkpoint "${OUTPUT_DIR}/checkpoints/checkpoint_1"

"${ENV_DIR}/bin/python" "${ROOT_DIR}/scripts/phase_minus1/export_programs.py" \
  "${OUTPUT_DIR}/checkpoints/checkpoint_2" "${OUTPUT_DIR}/evaluated_programs.jsonl"

echo "Phase -1 smoke output: ${OUTPUT_DIR}"

#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"
export PYTHONPATH="${ROOT_DIR}/src"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY=127.0.0.1,localhost
PY="${ROOT_DIR}/.conda/llm4branch/bin/python"
"${PY}" scripts/phase_minus1/mock_openai_server.py &
SERVER_PID=$!
trap 'kill "${SERVER_PID}" 2>/dev/null || true' EXIT
sleep 0.5
kill -0 "${SERVER_PID}"
"${PY}" scripts/phase0.py --search-config configs/phase0/search_smoke.yaml "$@"

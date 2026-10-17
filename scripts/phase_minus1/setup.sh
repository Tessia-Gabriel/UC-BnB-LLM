#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_DIR="${ROOT_DIR}/.conda/llm4branch"

git -C "${ROOT_DIR}/third_party/llm4branch" checkout e001d8c9f9f9b7d414922526c8d958a2cbf62462
git -C "${ROOT_DIR}/third_party/llm4branch-ecole" checkout debd0e44dc5c5c200fcb3845d511cd0729baaa3b
if [[ ! -x "${ENV_DIR}/bin/python" ]]; then
  conda env create -p "${ENV_DIR}" -f "${ROOT_DIR}/environment.yml"
fi
conda run -p "${ENV_DIR}" python -m pip install --no-build-isolation --no-deps -e "${ROOT_DIR}/third_party/llm4branch"

export CMAKE_ARGS="-DSCIP_DIR=${ENV_DIR}/lib/cmake/scip -DCMAKE_INSTALL_RPATH_USE_LINK_PATH=ON -DECOLE_FORCE_DOWNLOAD=ON"
conda run -p "${ENV_DIR}" python -m pip install --no-build-isolation --no-deps -e "${ROOT_DIR}/third_party/llm4branch-ecole"
conda run -p "${ENV_DIR}" python "${ROOT_DIR}/scripts/phase_minus1/verify_upstreams.py"

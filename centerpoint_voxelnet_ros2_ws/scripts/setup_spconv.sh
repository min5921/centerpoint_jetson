#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$WORKSPACE_ROOT/.venv"
THIRD_PARTY="$WORKSPACE_ROOT/third_party"
PIP_CACHE_DIR="$WORKSPACE_ROOT/.cache/pip"
DEFAULT_CENTERPOINT_ROOT="$WORKSPACE_ROOT/../centerpoint"
if [[ ! -d "$DEFAULT_CENTERPOINT_ROOT/src/CenterPoint" ]]; then
  DEFAULT_CENTERPOINT_ROOT="$WORKSPACE_ROOT/../../centerpoint"
fi
CENTERPOINT_ROOT="${CENTERPOINT_ROOT:-$DEFAULT_CENTERPOINT_ROOT}"
POINTPILLARS_VENV="$CENTERPOINT_ROOT/.venv-jetson"
POINTPILLARS_SITE="$POINTPILLARS_VENV/lib/python3.10/site-packages"
CUSPARSELT_LIB="$POINTPILLARS_VENV/vendor/libcusparse_lt-linux-sbsa-0.5.2.1-archive/lib"

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv --system-site-packages "$VENV"
fi

mkdir -p "$THIRD_PARTY" "$PIP_CACHE_DIR"

if [[ ! -d "$THIRD_PARTY/cumm/.git" ]]; then
  git clone --depth 1 --branch v0.7.11 \
    https://github.com/FindDefinition/cumm.git "$THIRD_PARTY/cumm"
fi
if [[ ! -d "$THIRD_PARTY/spconv/.git" ]]; then
  git clone --depth 1 --branch v2.3.8 \
    https://github.com/traveller59/spconv.git "$THIRD_PARTY/spconv"
fi

export PIP_CACHE_DIR
export CUMM_CUDA_ARCH_LIST=8.7
export CUMM_DISABLE_JIT=1
export SPCONV_DISABLE_JIT=1
export CUDA_HOME=/usr/local/cuda
export PYTHONPATH="$POINTPILLARS_SITE${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$CUSPARSELT_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

if "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import cumm
import spconv
import spconv.pytorch

assert cumm.__version__ == "0.7.11"
assert spconv.__version__ == "2.3.8"
PY
then
  echo "cumm 0.7.11 and spconv 2.3.8 are already installed."
  exit 0
fi

"$VENV/bin/python" -m pip install \
  "pccm==0.4.16" "ccimport==0.4.4" "pybind11==2.13.6" \
  "fire==0.7.0" "sympy==1.13.1" "numpy==1.26.1" ninja

"$VENV/bin/python" -m pip install --no-build-isolation --no-deps \
  -e "$THIRD_PARTY/cumm"
"$VENV/bin/python" -m pip install --no-build-isolation --no-deps \
  -e "$THIRD_PARTY/spconv"

"$VENV/bin/python" - <<'PY'
import cumm
import spconv
import spconv.pytorch

print("cumm", cumm.__version__)
print("spconv", spconv.__version__)
print("spconv CUDA import: OK")
PY

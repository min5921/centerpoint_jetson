#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_CENTERPOINT_ROOT="$WORKSPACE_ROOT/../centerpoint"
if [[ ! -d "$DEFAULT_CENTERPOINT_ROOT/src/CenterPoint" ]]; then
  DEFAULT_CENTERPOINT_ROOT="$WORKSPACE_ROOT/../../centerpoint"
fi
CENTERPOINT_ROOT="${CENTERPOINT_ROOT:-$DEFAULT_CENTERPOINT_ROOT}"
POINTPILLARS_VENV="$CENTERPOINT_ROOT/.venv-jetson"
VOXELNET_VENV="$WORKSPACE_ROOT/.venv"
CONFIG="${CONFIG:-$CENTERPOINT_ROOT/src/CenterPoint/configs/waymo/voxelnet/waymo_centerpoint_voxelnet_1x.py}"
CHECKPOINT="${CHECKPOINT:-}"
ALLOW_RANDOM_WEIGHTS="${ALLOW_RANDOM_WEIGHTS:-false}"
CUSPARSELT_LIB="$POINTPILLARS_VENV/vendor/libcusparse_lt-linux-sbsa-0.5.2.1-archive/lib"
POINTPILLARS_SITE="$POINTPILLARS_VENV/lib/python3.10/site-packages"

if [[ ! -f "$WORKSPACE_ROOT/install/local_setup.bash" ]]; then
  echo "ROS 2 workspace is not built. Run: $WORKSPACE_ROOT/scripts/build.sh" >&2
  exit 1
fi
if [[ ! -x "$VOXELNET_VENV/bin/python" ]]; then
  echo "VoxelNet environment is missing. Run: $WORKSPACE_ROOT/scripts/setup_spconv.sh" >&2
  exit 1
fi
if [[ ! -f "$CONFIG" ]]; then
  echo "VoxelNet config is missing: $CONFIG" >&2
  exit 1
fi
if [[ -n "$CHECKPOINT" && ! -f "$CHECKPOINT" ]]; then
  echo "VoxelNet checkpoint is missing: $CHECKPOINT" >&2
  exit 1
fi
if [[ -z "$CHECKPOINT" && "$ALLOW_RANDOM_WEIGHTS" != "true" ]]; then
  echo "Set CHECKPOINT=/absolute/path/model.pth for valid detections." >&2
  echo "For compute benchmarking only, set ALLOW_RANDOM_WEIGHTS=true." >&2
  exit 1
fi

mkdir -p "$WORKSPACE_ROOT/.cache/numba" "$WORKSPACE_ROOT/.cache/ros-log"
set +u
source /opt/ros/humble/setup.bash
source "$WORKSPACE_ROOT/install/local_setup.bash"
set -u

export VOXELNET_PYTHON="$VOXELNET_VENV/bin/python"
export VOXELNET_CONFIG="$CONFIG"
export PYTHONPATH="$POINTPILLARS_SITE:$CENTERPOINT_ROOT/src/CenterPoint${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$CUSPARSELT_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export NUMBA_CACHE_DIR="$WORKSPACE_ROOT/.cache/numba"
export ROS_LOG_DIR="$WORKSPACE_ROOT/.cache/ros-log"
export CUDA_HOME=/usr/local/cuda
export CUMM_CUDA_ARCH_LIST=8.7
export CUMM_DISABLE_JIT=1
export SPCONV_DISABLE_JIT=1

LAUNCH_ARGS=(
  allow_random_weights:="$ALLOW_RANDOM_WEIGHTS"
  input_topic:="${INPUT_TOPIC:-/lidar/points}"
  frame_id:="${FRAME_ID:-lidar}"
  precision:="${PRECISION:-fp16}"
  score_threshold:="${SCORE_THRESHOLD:-0.5}"
  max_detections:="${MAX_DETECTIONS:-200}"
  rviz:="${RVIZ:-true}"
)
if [[ -n "$CHECKPOINT" ]]; then
  LAUNCH_ARGS+=(checkpoint:="$CHECKPOINT")
fi

exec ros2 launch centerpoint_voxelnet_ros inference.launch.py "${LAUNCH_ARGS[@]}"

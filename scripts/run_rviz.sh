#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CENTERPOINT_ROOT="${CENTERPOINT_ROOT:-$WORKSPACE_ROOT/../centerpoint}"
VENV="$CENTERPOINT_ROOT/.venv-jetson"
CONFIG="${CONFIG:-$CENTERPOINT_ROOT/src/CenterPoint/configs/waymo/pp/waymo_centerpoint_pp_two_pfn_stride1_3x.py}"
CHECKPOINT="${CHECKPOINT:-$CENTERPOINT_ROOT/weights/centerpoint_waymo_pointpillars_full_novelocity.pth}"
CUSPARSELT_LIB="$VENV/vendor/libcusparse_lt-linux-sbsa-0.5.2.1-archive/lib"

if [[ ! -f "$WORKSPACE_ROOT/install/local_setup.bash" ]]; then
  echo "ROS 2 workspace is not built. Run: $WORKSPACE_ROOT/scripts/build.sh" >&2
  exit 1
fi
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Native Jetson Python environment is missing: $VENV" >&2
  exit 1
fi
if [[ ! -f "$CONFIG" ]]; then
  echo "CenterPoint config is missing: $CONFIG" >&2
  exit 1
fi
if [[ ! -f "$CHECKPOINT" ]]; then
  echo "PointPillars checkpoint is missing: $CHECKPOINT" >&2
  echo "Set CHECKPOINT=/absolute/path/to/model.pth when running this script." >&2
  exit 1
fi
if ! compgen -G "$CENTERPOINT_ROOT/src/CenterPoint/det3d/ops/iou3d_nms/iou3d_nms_cuda*.so" >/dev/null; then
  echo "CenterPoint CUDA NMS extension is not built." >&2
  exit 1
fi

mkdir -p "$WORKSPACE_ROOT/.cache/numba" "$WORKSPACE_ROOT/.cache/ros-log"
set +u
source /opt/ros/humble/setup.bash
source "$WORKSPACE_ROOT/install/local_setup.bash"
set -u

export CENTERPOINT_PYTHON="$VENV/bin/python"
export CENTERPOINT_CONFIG="$CONFIG"
export CENTERPOINT_CHECKPOINT="$CHECKPOINT"
export PYTHONPATH="$CENTERPOINT_ROOT/src/CenterPoint${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$CUSPARSELT_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export NUMBA_CACHE_DIR="$WORKSPACE_ROOT/.cache/numba"
export ROS_LOG_DIR="$WORKSPACE_ROOT/.cache/ros-log"
export CUDA_HOME=/usr/local/cuda

exec ros2 launch centerpoint_pointpillars_ros inference.launch.py \
  input_topic:="${INPUT_TOPIC:-/lidar/points}" \
  frame_id:="${FRAME_ID:-lidar}" \
  score_threshold:="${SCORE_THRESHOLD:-0.5}" \
  max_detections:="${MAX_DETECTIONS:-200}" \
  rviz:="${RVIZ:-true}"

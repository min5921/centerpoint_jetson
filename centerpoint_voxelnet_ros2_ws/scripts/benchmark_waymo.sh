#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_PID=""

cleanup() {
  if [[ -n "$RUN_PID" ]] && kill -0 "$RUN_PID" 2>/dev/null; then
    kill -INT "$RUN_PID" 2>/dev/null || true
    wait "$RUN_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

ALLOW_RANDOM_WEIGHTS="${ALLOW_RANDOM_WEIGHTS:-true}" \
CHECKPOINT="${CHECKPOINT:-}" \
RVIZ=false \
LOOP="${LOOP:-false}" \
BAG_RATE="${BAG_RATE:-1.0}" \
STARTUP_DELAY="${STARTUP_DELAY:-6}" \
  "$WORKSPACE_ROOT/scripts/run_waymo_bag.sh" &
RUN_PID=$!

sleep "${MEASURE_DELAY:-12}"

set +u
source /opt/ros/humble/setup.bash
source "$WORKSPACE_ROOT/install/local_setup.bash"
set -u
export ROS_LOG_DIR="$WORKSPACE_ROOT/.cache/ros-log"

timeout --signal=INT --kill-after=3s "${MEASURE_SECONDS:-18}" \
  ros2 topic hz /voxelnet/status --window 100 || true

wait "$RUN_PID"
RUN_PID=""

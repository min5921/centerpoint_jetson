#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BAG_PATH="${BAG_PATH:-/home/kopti/Desktop/bag}"
LAUNCH_PID=""

if [[ ! -f "$BAG_PATH/metadata.yaml" ]]; then
  echo "ROS 2 bag metadata is missing: $BAG_PATH/metadata.yaml" >&2
  exit 1
fi

cleanup() {
  if [[ -n "$LAUNCH_PID" ]] && kill -0 "$LAUNCH_PID" 2>/dev/null; then
    kill -INT "$LAUNCH_PID" 2>/dev/null || true
    wait "$LAUNCH_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

INPUT_TOPIC=/waymo/points \
FRAME_ID=vehicle \
PRECISION="${PRECISION:-fp16}" \
SCORE_THRESHOLD="${SCORE_THRESHOLD:-0.5}" \
MAX_DETECTIONS="${MAX_DETECTIONS:-200}" \
RVIZ="${RVIZ:-true}" \
CHECKPOINT="${CHECKPOINT:-}" \
ALLOW_RANDOM_WEIGHTS="${ALLOW_RANDOM_WEIGHTS:-false}" \
  "$WORKSPACE_ROOT/scripts/run_rviz.sh" &
LAUNCH_PID=$!

sleep "${STARTUP_DELAY:-10}"
if ! kill -0 "$LAUNCH_PID" 2>/dev/null; then
  echo "VoxelNet launch exited before bag playback started." >&2
  wait "$LAUNCH_PID"
fi

set +u
source /opt/ros/humble/setup.bash
source "$WORKSPACE_ROOT/install/local_setup.bash"
set -u
mkdir -p "$WORKSPACE_ROOT/.cache/ros-log"
export ROS_LOG_DIR="$WORKSPACE_ROOT/.cache/ros-log"

PLAY_ARGS=(
  play "$BAG_PATH"
  --rate "${BAG_RATE:-0.25}"
  --topics /waymo/points /waymo/ground_truth /waymo/frame_info
)
if [[ "${LOOP:-true}" == "true" ]]; then
  PLAY_ARGS+=(--loop)
fi

ros2 bag "${PLAY_ARGS[@]}"

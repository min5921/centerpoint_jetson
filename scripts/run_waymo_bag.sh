#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BAG_PATH="${BAG_PATH:-/home/kopti/Desktop/bag}"
CHECKPOINT="${CHECKPOINT:-$BAG_PATH/centerpoint_waymo_pointpillars_full_novelocity_epoch12.pth}"
LAUNCH_PID=""

if [[ ! -f "$BAG_PATH/metadata.yaml" ]]; then
  echo "ROS 2 bag metadata is missing: $BAG_PATH/metadata.yaml" >&2
  exit 1
fi
if [[ ! -f "$CHECKPOINT" ]]; then
  echo "Set CHECKPOINT to the trained PointPillars .pth file." >&2
  echo "Example: CHECKPOINT=/absolute/path/model.pth $0" >&2
  exit 1
fi
if [[ ! -f "$WORKSPACE_ROOT/install/local_setup.bash" ]]; then
  echo "ROS 2 workspace is not built. Run: $WORKSPACE_ROOT/scripts/build.sh" >&2
  exit 1
fi

cleanup() {
  if [[ -n "$LAUNCH_PID" ]] && kill -0 "$LAUNCH_PID" 2>/dev/null; then
    kill -INT "$LAUNCH_PID" 2>/dev/null || true
    wait "$LAUNCH_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

CHECKPOINT="$CHECKPOINT" \
INPUT_TOPIC=/waymo/points \
FRAME_ID=vehicle \
PRECISION="${PRECISION:-fp16}" \
PROFILE_STAGES="${PROFILE_STAGES:-false}" \
SCORE_THRESHOLD="${SCORE_THRESHOLD:-0.5}" \
MAX_DETECTIONS="${MAX_DETECTIONS:-200}" \
NMS_PRE_MAX_SIZE="${NMS_PRE_MAX_SIZE:-4096}" \
NMS_POST_MAX_SIZE="${NMS_POST_MAX_SIZE:-500}" \
RVIZ="${RVIZ:-true}" \
  "$WORKSPACE_ROOT/scripts/run_rviz.sh" &
LAUNCH_PID=$!

sleep "${STARTUP_DELAY:-5}"
if ! kill -0 "$LAUNCH_PID" 2>/dev/null; then
  echo "PointPillars launch exited before bag playback started." >&2
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

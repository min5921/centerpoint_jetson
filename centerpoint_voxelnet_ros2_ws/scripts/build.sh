#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_CENTERPOINT_ROOT="$WORKSPACE_ROOT/../centerpoint"
if [[ ! -d "$DEFAULT_CENTERPOINT_ROOT/src/CenterPoint" ]]; then
  DEFAULT_CENTERPOINT_ROOT="$WORKSPACE_ROOT/../../centerpoint"
fi
CENTERPOINT_ROOT="${CENTERPOINT_ROOT:-$DEFAULT_CENTERPOINT_ROOT}"
COLCON="${COLCON:-$CENTERPOINT_ROOT/.venv-jetson/bin/colcon}"

if [[ ! -x "$COLCON" ]]; then
  COLCON="$(command -v colcon || true)"
fi
if [[ -z "$COLCON" || ! -x "$COLCON" ]]; then
  echo "colcon is missing. Install python3-colcon-common-extensions." >&2
  exit 1
fi

set +u
source /opt/ros/humble/setup.bash
set -u

cd "$WORKSPACE_ROOT"
"$COLCON" build --symlink-install --packages-select centerpoint_voxelnet_ros

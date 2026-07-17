#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CENTERPOINT_ROOT="${CENTERPOINT_ROOT:-$WORKSPACE_ROOT/../centerpoint}"
COLCON="$CENTERPOINT_ROOT/.venv-jetson/bin/colcon"

if [[ ! -x "$COLCON" ]]; then
  echo "colcon is missing from the native environment: $COLCON" >&2
  exit 1
fi

set +u
source /opt/ros/humble/setup.bash
set -u
cd "$WORKSPACE_ROOT"
"$COLCON" build --symlink-install --packages-select centerpoint_pointpillars_ros

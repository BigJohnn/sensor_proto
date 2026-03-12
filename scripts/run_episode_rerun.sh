#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common_env.sh"

if [[ $# -lt 1 ]]; then
  echo "usage: bash scripts/run_episode_rerun.sh <episode_dir> [-- extra args]" >&2
  exit 1
fi

uv run --no-project \
  --with rerun-sdk \
  --python "${SENSOR_PROTO_PYTHON}" \
  python -m sensor_proto.episode_rerun_viewer "$@"

#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common_env.sh"

if [[ $# -lt 1 ]]; then
  echo "usage: bash scripts/render_episode_mosaic.sh <episode_dir> [--output output.mp4] [--columns N] [--overwrite]" >&2
  exit 1
fi

if [[ -n "${SENSOR_PROTO_EPISODE_FFMPEG_PATH:-}" ]]; then
  FFMPEG_BIN="${SENSOR_PROTO_EPISODE_FFMPEG_PATH}"
elif command -v ffmpeg >/dev/null 2>&1; then
  FFMPEG_BIN="$(command -v ffmpeg)"
else
  echo "Episode mosaic rendering requires a host ffmpeg executable. Install FFmpeg and set SENSOR_PROTO_EPISODE_FFMPEG_PATH if needed." >&2
  exit 1
fi

"${SENSOR_PROTO_PYTHON}" -m sensor_proto.episode_mosaic --ffmpeg-bin "${FFMPEG_BIN}" "$@"

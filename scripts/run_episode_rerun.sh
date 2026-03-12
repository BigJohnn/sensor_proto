#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common_env.sh"

if [[ $# -lt 1 ]]; then
  echo "usage: bash scripts/run_episode_rerun.sh <episode_dir> [-- extra args]" >&2
  exit 1
fi

if [[ -n "${SENSOR_PROTO_RERUN_FFMPEG_PATH:-}" ]]; then
  FFMPEG_BIN="${SENSOR_PROTO_RERUN_FFMPEG_PATH}"
elif command -v ffmpeg >/dev/null 2>&1; then
  FFMPEG_BIN="$(command -v ffmpeg)"
else
  echo "Episode replay requires a host ffmpeg executable. Install FFmpeg >= 5.1 and set SENSOR_PROTO_RERUN_FFMPEG_PATH if needed." >&2
  exit 1
fi

FFMPEG_VERSION="$("${FFMPEG_BIN}" -version | awk 'NR==1 {print $3}' | sed 's/-.*//')"
if ! "${SENSOR_PROTO_PYTHON}" - "${FFMPEG_VERSION}" <<'PY'
import sys

parts = [int(part) for part in sys.argv[1].split(".")[:3]]
while len(parts) < 3:
    parts.append(0)
sys.exit(0 if tuple(parts) >= (5, 1, 0) else 1)
PY
then
  echo "Episode replay requires FFmpeg >= 5.1, but found ${FFMPEG_VERSION} at ${FFMPEG_BIN}" >&2
  exit 1
fi

export SENSOR_PROTO_RERUN_FFMPEG_PATH="${FFMPEG_BIN}"

"${SENSOR_PROTO_PYTHON}" - <<'PY'
import json
import os
import re
from pathlib import Path

ffmpeg_path = os.environ["SENSOR_PROTO_RERUN_FFMPEG_PATH"]
state_root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "rerun"
app_state_path = state_root / "app.ron"

if not app_state_path.exists():
    raise SystemExit(0)

payload = app_state_path.read_text(encoding="utf-8")
escaped_ffmpeg_path = json.dumps(ffmpeg_path).replace(chr(34), r"\\\"")
patterns = (
    (
        r'video:\(hw_acceleration:([^,]+),override_ffmpeg_path:(?:true|false),ffmpeg_path:\\"(?:[^"\\\\]|\\\\.)*\\"\)',
        lambda match: (
            "video:(hw_acceleration:"
            f"{match.group(1)},override_ffmpeg_path:true,ffmpeg_path:{escaped_ffmpeg_path})"
        ),
    ),
    (
        r'video_decoder_hw_acceleration:([^,]+),video_decoder_override_ffmpeg_path:(?:true|false),video_decoder_ffmpeg_path:\\"(?:[^"\\\\]|\\\\.)*\\"',
        lambda match: (
            "video_decoder_hw_acceleration:"
            f"{match.group(1)},video_decoder_override_ffmpeg_path:true,video_decoder_ffmpeg_path:{escaped_ffmpeg_path}"
        ),
    ),
)

updated_payload = payload
replacements = 0
for pattern, replacement in patterns:
    updated_payload, count = re.subn(pattern, replacement, updated_payload, count=1)
    replacements += count

if replacements:
    app_state_path.write_text(updated_payload, encoding="utf-8")
PY

uv run \
  --extra replay \
  --python "${SENSOR_PROTO_PYTHON}" \
  python -m sensor_proto.episode_rerun_viewer "$@"

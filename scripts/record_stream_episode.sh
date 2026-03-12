#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common_env.sh"

DURATION_S="${1:-10}"
FINALIZE_GRACE_S="${SENSOR_PROTO_RECORD_FINALIZE_GRACE_S:-180}"
MAX_RUNTIME_S="${SENSOR_PROTO_RECORD_MAX_RUNTIME_S:-600}"
TIMESTAMP="$(date +%Y%m%dT%H%M%S)"
BASE_CONFIG="${SENSOR_PROTO_RECORD_TEMPLATE_CONFIG:-configs/realsense-8cam-stream.json}"
GENERATED_CONFIG="${SENSOR_PROTO_RECORD_GENERATED_CONFIG:-artifacts/realsense-8cam-stream-recording-runtime.json}"
OUTPUT_DIR="${SENSOR_PROTO_RECORD_OUTPUT_DIR:-artifacts/lerobot/hw-${DURATION_S}s-episode-${TIMESTAMP}}"
REPO_ID="${SENSOR_PROTO_RECORD_REPO_ID:-local/sensor-proto-hw}"
TASK="${SENSOR_PROTO_RECORD_TASK:-synchronized-multi-camera-observation}"
ROBOT_TYPE="${SENSOR_PROTO_RECORD_ROBOT_TYPE:-camera-rig}"
RECORD_FPS="${SENSOR_PROTO_RECORD_FPS:-30}"
USE_VIDEOS="${SENSOR_PROTO_RECORD_USE_VIDEOS:-true}"
TARGET_ALIGNED_SETS="${SENSOR_PROTO_RECORD_TARGET_ALIGNED_SETS:-$((DURATION_S * RECORD_FPS))}"

mkdir -p "${REPO_ROOT}/artifacts/lerobot"
TEMP_CONFIG="$(mktemp "${REPO_ROOT}/artifacts/realsense-stream-recording-XXXXXX.json")"
TEMP_CONFIG_REL="${TEMP_CONFIG#${REPO_ROOT}/}"

cleanup() {
  rm -f "${TEMP_CONFIG}"
}

trap cleanup EXIT

"${SENSOR_PROTO_PYTHON}" - <<PY
import json
from pathlib import Path

base_config = Path(${BASE_CONFIG@Q})
temp_config = Path(${TEMP_CONFIG@Q})
payload = json.loads(base_config.read_text(encoding="utf-8"))
payload["recording"] = {
    "enabled": True,
    "format": "lerobot_v3",
    "root_dir": ${OUTPUT_DIR@Q},
    "repo_id": ${REPO_ID@Q},
    "task": ${TASK@Q},
    "robot_type": ${ROBOT_TYPE@Q},
    "fps": int(${RECORD_FPS@Q}),
    "use_videos": ${USE_VIDEOS@Q}.lower() in {"1", "true", "yes", "on"},
}
temp_config.write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
PY

set +e
docker compose -f docker/compose.yaml --profile hw run --rm --service-ports --entrypoint bash sensor-stream -lc \
  "timeout --signal=TERM --kill-after=${FINALIZE_GRACE_S}s ${MAX_RUNTIME_S}s python -m sensor_proto.stream_main \
    --config ${TEMP_CONFIG_REL@Q} \
    --generated-config ${GENERATED_CONFIG@Q} \
    --stop-after-aligned-sets ${TARGET_ALIGNED_SETS}"
record_rc=$?
set -e

if [[ "${record_rc}" -eq 124 ]]; then
  echo "Recording watchdog reached ${MAX_RUNTIME_S}s before ${TARGET_ALIGNED_SETS} aligned sets were recorded." >&2
  exit 124
fi

if [[ "${record_rc}" -ne 0 ]]; then
  exit "${record_rc}"
fi

echo "Recorded at least ${TARGET_ALIGNED_SETS} aligned sets."
echo "Saved LeRobot dataset to ${OUTPUT_DIR}"
echo "Generated runtime config at ${GENERATED_CONFIG}"

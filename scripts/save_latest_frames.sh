#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common_env.sh"

uv run --no-project --python "${SENSOR_PROTO_PYTHON}" python -m sensor_proto.stream_client_cli \
  --base-url "${SENSOR_PROTO_BASE_URL:-http://127.0.0.1:8787}" \
  --output-dir "${SENSOR_PROTO_SNAPSHOT_DIR:-artifacts/latest-aligned-frames}" \
  "$@"

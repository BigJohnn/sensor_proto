#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common_env.sh"

docker compose -f docker/compose.yaml --profile hikrobot up -d sensor-hikrobot-stream
echo "Hikrobot stream service started: http://127.0.0.1:8787"

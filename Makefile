SHELL := /bin/bash

PYTEST_DISABLE_PLUGIN_AUTOLOAD ?= 1

.PHONY: test mock-run stream-up stream-down stream-logs stream-viewer stream-shot

test:
	source $$HOME/.local/bin/env && UV_CACHE_DIR=/tmp/uv-cache PYTEST_DISABLE_PLUGIN_AUTOLOAD=$(PYTEST_DISABLE_PLUGIN_AUTOLOAD) PYTHONPATH=src uv run --no-project --python "$$(command -v python3)" python -m pytest

mock-run:
	source $$HOME/.local/bin/env && UV_CACHE_DIR=/tmp/uv-cache PYTHONPATH=src uv run --no-project --python "$$(command -v python3)" python -m sensor_proto.main --config configs/mock-session.json

stream-up:
	bash scripts/run_stream_service.sh

stream-down:
	bash scripts/stop_stream_service.sh

stream-logs:
	docker compose -f docker/compose.yaml --profile hw logs -f sensor-stream

stream-viewer:
	bash scripts/run_stream_viewer.sh

stream-shot:
	bash scripts/save_latest_frames.sh
